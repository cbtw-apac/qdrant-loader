from collections.abc import Sequence

from harborrag_core.domain.retrieval import RetrievalResult


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[RetrievalResult]], k: int = 60
) -> list[RetrievalResult]:
    scores: dict[str, float] = {}
    items: dict[str, RetrievalResult] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (k + rank)
            items[item.id] = item
    return [
        items[item_id]
        for item_id, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    ]
