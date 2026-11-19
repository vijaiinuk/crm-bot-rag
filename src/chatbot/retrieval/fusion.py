"""Reciprocal rank fusion (S2.2.1): merge ranked lists using only rank positions.

    score(chunk) = sum over lists containing it of 1 / (k + rank)

Rank-only, so a cosine distance and a ts_rank_cd score never need to be comparable.
k = 60 is the value from the original RRF paper (Cormack et al., 2009): it damps
the gap between rank 1 and rank 2, so agreement between lists beats one list's top.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

DEFAULT_K = 60


@dataclass(frozen=True, slots=True)
class Fused:
    chunk_id: str
    score: float
    ranks: Mapping[str, int]  # list name -> 1-based rank, only for lists containing it


def rrf(ranked: Mapping[str, Sequence[str]], *, k: int = DEFAULT_K) -> list[Fused]:
    """Fuse named ranked lists, best first.

    Ties (common with two equally weighted lists: ranks (1, 2) and (2, 1) always tie) go
    to the better single rank, then to the better rank in the EARLIER list of `ranked`,
    then to chunk_id. So pass the stronger list first.
    """
    if k < 0:
        raise ValueError(f"k must not be negative, got {k}")
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for name, chunk_ids in ranked.items():
        seen: set[str] = set()
        for rank, chunk_id in enumerate(chunk_ids, start=1):
            if chunk_id in seen:
                raise ValueError(f"{chunk_id!r} appears twice in ranked list {name!r}")
            seen.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            ranks.setdefault(chunk_id, {})[name] = rank
    names = list(ranked)
    missing = len(max(ranked.values(), key=len, default=())) + 1  # worse than any rank

    def key(c: str) -> tuple[float, int, tuple[int, ...], str]:
        by_list = tuple(ranks[c].get(name, missing) for name in names)
        return (-scores[c], min(ranks[c].values()), by_list, c)

    order = sorted(scores, key=key)
    return [Fused(c, scores[c], ranks[c]) for c in order]
