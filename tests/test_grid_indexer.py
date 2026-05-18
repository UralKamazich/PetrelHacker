from __future__ import annotations

from core.grid_indexer import ColumnMatch


def test_column_match_1based_indices() -> None:
    match = ColumnMatch(i=0, j=4, distance=2.5)
    assert match.i_1based == 1
    assert match.j_1based == 5
