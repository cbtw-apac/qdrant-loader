from __future__ import annotations

import pytest
from pydantic import ValidationError
from qdrant_loader.config.concurrency import ConcurrencyConfig
from qdrant_loader.config.global_config import GlobalConfig


def test_concurrency_config_defaults():
    cfg = ConcurrencyConfig()
    assert cfg.max_chunk_workers == 10
    assert cfg.max_embed_workers == 4
    assert cfg.max_upsert_workers == 4
    assert cfg.queue_size == 1000
    assert cfg.upsert_batch_size is None


def test_concurrency_config_accepts_overrides():
    cfg = ConcurrencyConfig(
        max_chunk_workers=20,
        max_embed_workers=8,
        max_upsert_workers=6,
        queue_size=500,
        upsert_batch_size=100,
    )
    assert cfg.max_chunk_workers == 20
    assert cfg.max_embed_workers == 8
    assert cfg.max_upsert_workers == 6
    assert cfg.queue_size == 500
    assert cfg.upsert_batch_size == 100


@pytest.mark.parametrize(
    "field",
    ["max_chunk_workers", "max_embed_workers", "max_upsert_workers", "queue_size"],
)
def test_concurrency_config_rejects_non_positive_values(field):
    with pytest.raises(ValidationError):
        ConcurrencyConfig(**{field: 0})


def test_concurrency_config_rejects_non_positive_upsert_batch_size():
    with pytest.raises(ValidationError):
        ConcurrencyConfig(upsert_batch_size=0)


def test_global_config_includes_concurrency_defaults():
    cfg = GlobalConfig(skip_validation=True)
    assert isinstance(cfg.concurrency, ConcurrencyConfig)
    assert cfg.concurrency.max_embed_workers == 4
    assert cfg.concurrency.max_upsert_workers == 4


def test_global_config_to_dict_includes_concurrency():
    cfg = GlobalConfig(skip_validation=True)
    data = cfg.to_dict()
    assert data["concurrency"]["max_chunk_workers"] == 10
    assert data["concurrency"]["max_embed_workers"] == 4
    assert data["concurrency"]["max_upsert_workers"] == 4
    assert data["concurrency"]["queue_size"] == 1000
    assert data["concurrency"]["upsert_batch_size"] is None


def test_global_config_parses_concurrency_from_dict():
    cfg = GlobalConfig(
        skip_validation=True,
        concurrency={
            "max_chunk_workers": 15,
            "max_embed_workers": 12,
            "max_upsert_workers": 8,
            "queue_size": 2000,
            "upsert_batch_size": 250,
        },
    )
    assert cfg.concurrency.max_chunk_workers == 15
    assert cfg.concurrency.max_embed_workers == 12
    assert cfg.concurrency.max_upsert_workers == 8
    assert cfg.concurrency.queue_size == 2000
    assert cfg.concurrency.upsert_batch_size == 250
