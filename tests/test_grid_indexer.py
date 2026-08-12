from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from core.grid_indexer import ColumnMatch
from core.grid_indexer import FastGridIndexer
from core.resqml_reader import GridInfo


def test_column_match_1based_indices() -> None:
    match = ColumnMatch(i=0, j=4, distance=2.5)
    assert match.i_1based == 1
    assert match.j_1based == 5


def test_grid_indexer_reads_four_dimensional_points_dataset(tmp_path) -> None:
    h5_path = tmp_path / "grid.h5"
    points_path = "/RESQML/Grid/Points"
    points = np.zeros((2, 3, 4, 3), dtype=float)
    for j in range(3):
        for i in range(4):
            points[0, j, i, 0] = i * 10.0
            points[0, j, i, 1] = j * 20.0
    with h5py.File(h5_path, "w") as h5:
        h5.create_dataset(points_path, data=points)

    reader = _DummyReader(h5_path)
    grid = GridInfo(index=0, title="Grid", uuid="grid", ni=3, nj=2, nk=1, hdf_paths=(points_path,))
    indexer = FastGridIndexer(reader, grid)

    indexer.build_column_index()

    assert indexer.bbox == (0.0, 30.0, 0.0, 40.0)
    match = indexer.find_column(15.0, 10.0)
    assert match is not None
    assert (match.i, match.j) == (1, 0)
    matches = indexer.find_columns([(15.0, 10.0), (25.0, 30.0), (-1.0, 10.0)])
    assert [(match.i, match.j) if match else None for match in matches] == [(1, 0), (2, 1), None]
    assert matches[0].distance == match.distance


class _DummyReader:
    def __init__(self, h5_path: Path) -> None:
        self.h5_path = h5_path

    def list_grids(self):
        return []
