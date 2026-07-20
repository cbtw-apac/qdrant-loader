import logging
from importlib import import_module

import pytest


@pytest.fixture
def isolated_logging_state():
    """Isolate root logger + LoggingConfig class state for each test."""
    logging_mod = import_module("qdrant_loader_core.logging")
    LoggingConfig = logging_mod.LoggingConfig

    root = logging.getLogger()
    prev_handlers = list(root.handlers)
    prev_filters = list(root.filters)
    prev_level = root.level

    prev_initialized = LoggingConfig._initialized
    prev_installed_handlers = list(LoggingConfig._installed_handlers)
    prev_file_handler = LoggingConfig._file_handler
    prev_current_config = LoggingConfig._current_config

    # Start from clean state for deterministic assertions
    for h in list(root.handlers):
        root.removeHandler(h)
    for f in list(root.filters):
        root.removeFilter(f)

    LoggingConfig._initialized = False
    LoggingConfig._installed_handlers = []
    LoggingConfig._file_handler = None
    LoggingConfig._current_config = None

    try:
        yield logging_mod
    finally:
        # Close handlers added during test
        for h in list(root.handlers):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        for f in list(root.filters):
            root.removeFilter(f)

        # Restore root logger
        for h in prev_handlers:
            root.addHandler(h)
        for f in prev_filters:
            root.addFilter(f)
        root.setLevel(prev_level)

        # Restore LoggingConfig state
        LoggingConfig._initialized = prev_initialized
        LoggingConfig._installed_handlers = prev_installed_handlers
        LoggingConfig._file_handler = prev_file_handler
        LoggingConfig._current_config = prev_current_config


def test_setup_invalid_log_level_raises_value_error(isolated_logging_state):
    LoggingConfig = isolated_logging_state.LoggingConfig

    with pytest.raises(ValueError, match="Invalid log level"):
        LoggingConfig.setup(level="NOT_A_LEVEL")


def test_setup_disable_console_via_env(monkeypatch, isolated_logging_state):
    logging_mod = isolated_logging_state
    LoggingConfig = logging_mod.LoggingConfig

    monkeypatch.setenv("MCP_DISABLE_CONSOLE_LOGGING", "true")
    LoggingConfig.setup()

    root = logging.getLogger()
    # No console/file handler should be attached when console disabled and no file set
    assert len(root.handlers) == 0
    assert LoggingConfig._initialized is True


def test_setup_short_circuits_when_config_unchanged(
    monkeypatch, isolated_logging_state
):
    logging_mod = isolated_logging_state
    LoggingConfig = logging_mod.LoggingConfig

    reset_calls = []

    def fake_reset_defaults():
        reset_calls.append("called")

    monkeypatch.setattr(logging_mod.structlog, "reset_defaults", fake_reset_defaults)

    LoggingConfig.setup(level="INFO", format="console", disable_console=True)
    LoggingConfig.setup(level="INFO", format="console", disable_console=True)

    # Second call should short-circuit before structlog.reset_defaults
    assert len(reset_calls) == 1


def test_setup_adds_file_handler_and_tracks_current_config(
    tmp_path, isolated_logging_state
):
    LoggingConfig = isolated_logging_state.LoggingConfig

    log_file = tmp_path / "app.log"
    LoggingConfig.setup(file=str(log_file), disable_console=True)

    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]

    assert len(file_handlers) == 1
    assert LoggingConfig._file_handler is file_handlers[0]
    assert LoggingConfig._current_config is not None
    assert LoggingConfig._current_config[2] == str(log_file)


def test_get_logger_calls_setup_when_uninitialized(monkeypatch, isolated_logging_state):
    logging_mod = isolated_logging_state
    LoggingConfig = logging_mod.LoggingConfig

    called = []

    original_setup = LoggingConfig.setup

    def wrapped_setup(*args, **kwargs):
        called.append(True)
        return original_setup(*args, **kwargs)

    monkeypatch.setattr(LoggingConfig, "setup", wrapped_setup)

    logger = LoggingConfig.get_logger("unit-test")

    assert called
    assert logger is not None


def test_reconfigure_invalid_level_raises_value_error(isolated_logging_state):
    LoggingConfig = isolated_logging_state.LoggingConfig

    with pytest.raises(ValueError, match="Invalid log level"):
        LoggingConfig.reconfigure(level="NOPE")


def test_reconfigure_replaces_file_handler(tmp_path, isolated_logging_state):
    LoggingConfig = isolated_logging_state.LoggingConfig

    first_file = tmp_path / "first.log"
    second_file = tmp_path / "second.log"

    LoggingConfig.setup(file=str(first_file), disable_console=True)
    first_handler = LoggingConfig._file_handler
    assert first_handler is not None

    LoggingConfig.reconfigure(file=str(second_file))

    assert LoggingConfig._file_handler is not None
    assert LoggingConfig._file_handler is not first_handler
    assert LoggingConfig._current_config is not None
    assert LoggingConfig._current_config[2] == str(second_file)


def test_reconfigure_updates_level_and_current_config(tmp_path, isolated_logging_state):
    LoggingConfig = isolated_logging_state.LoggingConfig

    log_file = tmp_path / "level.log"
    LoggingConfig.setup(file=str(log_file), disable_console=True)

    LoggingConfig.reconfigure(level="DEBUG", file=str(log_file))

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert LoggingConfig._current_config is not None
    assert LoggingConfig._current_config[0] == "DEBUG"
