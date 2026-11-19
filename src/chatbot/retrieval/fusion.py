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
    """Fuse named ranked lists, best first. Ties: best single rank, then chunk_id."""
    raise NotImplementedError("S2.2.1: implement after the tests are reviewed")
