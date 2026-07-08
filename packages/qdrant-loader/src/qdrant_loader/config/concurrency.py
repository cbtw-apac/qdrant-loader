from pydantic import Field

from qdrant_loader.config.base import BaseConfig


class ConcurrencyConfig(BaseConfig):
    """Concurrency knobs for the document ingestion pipeline's stages."""

    max_chunk_workers: int = Field(
        default=10,
        gt=0,
        description="Maximum number of documents chunked concurrently",
    )
    max_embed_workers: int = Field(
        default=4,
        gt=0,
        description="Maximum number of embedding batch requests in flight concurrently",
    )
    max_upsert_workers: int = Field(
        default=4,
        gt=0,
        description="Maximum number of Qdrant upsert batch requests in flight concurrently",
    )
    queue_size: int = Field(
        default=1000,
        gt=0,
        description="Advisory queue size hint passed to pipeline workers",
    )
    upsert_batch_size: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Number of chunks per Qdrant upsert batch. Defaults to the "
            "embedding batch size when unset."
        ),
    )
