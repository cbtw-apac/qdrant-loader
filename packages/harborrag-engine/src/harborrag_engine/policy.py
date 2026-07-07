from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnginePolicy:
    max_concurrency: int = 4
    retrieval_top_k: int = 10

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
