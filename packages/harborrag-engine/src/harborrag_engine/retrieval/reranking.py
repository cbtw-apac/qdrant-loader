from harborrag_core.domain.retrieval import RetrievalResult


def keep_top(results: list[RetrievalResult], top_k: int) -> list[RetrievalResult]:
    return sorted(results, key=lambda r: r.score, reverse=True)[:top_k]
