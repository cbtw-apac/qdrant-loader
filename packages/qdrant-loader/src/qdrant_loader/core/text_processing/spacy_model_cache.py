"""Process-wide, thread-safe cache for loaded spaCy models.

``spacy.load()`` is expensive (disk read + model deserialization, often
hundreds of milliseconds), and the returned ``Language`` object is safe to
share for read-only inference across callers. Without this cache, callers
like ``TextProcessor`` and ``SemanticAnalyzer`` were re-loading a model on
every construction -- which happens once per document, since chunking
strategies (and therefore their text processors) are instantiated per
document. Because document chunking runs on a thread pool, that repeated,
heavy CPU-bound load also serializes chunk-worker threads on the GIL,
defeating ``max_chunk_workers`` concurrency.

The cache is held under a lock only while the first load for a given key is
in flight, so concurrent callers block and share that one load instead of
each independently loading the model.
"""

import threading
from collections.abc import Callable
from typing import Any

_cache: dict[Any, Any] = {}
_lock = threading.Lock()


def get_or_load(cache_key: Any, loader: Callable[[], Any]) -> Any:
    """Return the cached value for ``cache_key``, loading it via ``loader()`` once.

    ``loader`` is only ever invoked on a cache miss, and is called by the
    caller's own module so provider-specific error handling (e.g. an
    OSError-triggered model download) stays where it already is.
    """
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    with _lock:
        # Re-check: another thread may have populated it while we waited.
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        value = loader()
        _cache[cache_key] = value
        return value


def clear() -> None:
    """Clear all cached models. Intended for test isolation."""
    with _lock:
        _cache.clear()
