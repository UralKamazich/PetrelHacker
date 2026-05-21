from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core.resqml_reader import GridInfo, ResqmlReader


@dataclass(frozen=True)
class ColumnMatch:
    i: int
    j: int
    distance: float

    @property
    def i_1based(self) -> int:
        return self.i + 1

    @property
    def j_1based(self) -> int:
        return self.j + 1


class FastGridIndexer:
    """Nearest-column index for RESQML IJK grids.

    MVP assumptions:
    - Uses top-interface XY geometry only.
    - Uses the base unsplit pillar lattice for column centers.
    - Returns the nearest column center inside the grid XY bounding box.
    """

    def __init__(self, reader: ResqmlReader, grid: GridInfo | None = None) -> None:
        self.reader = reader
        self.grid = grid or self._first_grid()
        self.ni = self._require_int(self.grid.ni, "NI")
        self.nj = self._require_int(self.grid.nj, "NJ")
        self.nk = self._require_int(self.grid.nk, "NK")
        self.column_centers: np.ndarray | None = None
        self._flat_centers: np.ndarray | None = None
        self._bbox: tuple[float, float, float, float] | None = None

    def build_column_index(self) -> None:
        points_path = self._points_hdf_path()
        h5_path = self.reader.h5_path
        if h5_path is None:
            raise ValueError("H5 file was not found next to EPC.")

        top_pillars = self._read_top_base_pillars(h5_path, points_path)
        pillars = top_pillars.reshape(self.nj + 1, self.ni + 1, 2)
        centers = (
            pillars[:-1, :-1, :]
            + pillars[:-1, 1:, :]
            + pillars[1:, :-1, :]
            + pillars[1:, 1:, :]
        ) / 4.0

        self.column_centers = centers
        self._flat_centers = centers.reshape(self.nj * self.ni, 2)
        x_values = pillars[:, :, 0]
        y_values = pillars[:, :, 1]
        self._bbox = (
            float(np.nanmin(x_values)),
            float(np.nanmax(x_values)),
            float(np.nanmin(y_values)),
            float(np.nanmax(y_values)),
        )

    def find_column(self, x: float, y: float) -> ColumnMatch | None:
        self._ensure_built()
        assert self._flat_centers is not None
        assert self._bbox is not None

        x_value = float(x)
        y_value = float(y)
        xmin, xmax, ymin, ymax = self._bbox
        if not (xmin <= x_value <= xmax and ymin <= y_value <= ymax):
            return None

        delta = self._flat_centers - np.array([x_value, y_value], dtype=float)
        distances_sq = np.einsum("ij,ij->i", delta, delta)
        flat_index = int(np.nanargmin(distances_sq))
        j, i = divmod(flat_index, self.ni)
        return ColumnMatch(i=i, j=j, distance=float(np.sqrt(distances_sq[flat_index])))

    def vertical_cells(self, x: float, y: float) -> list[tuple[int, int, int]]:
        match = self.find_column(x, y)
        if match is None:
            return []
        return [(match.i, match.j, k) for k in range(self.nk)]

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        return self._bbox

    def _ensure_built(self) -> None:
        if self._flat_centers is None:
            raise RuntimeError("Column index is not built. Call build_column_index() first.")

    def _first_grid(self) -> GridInfo:
        grids = self.reader.list_grids()
        if not grids:
            raise ValueError("No grids found in RESQML model.")
        return grids[0]

    def _points_hdf_path(self) -> str:
        for path in self.grid.hdf_paths:
            if path.endswith("/Points"):
                return path
        raise ValueError(f"Grid has no Points HDF path: {self.grid.title}")

    def _read_top_base_pillars(self, h5_path: Path, points_path: str) -> np.ndarray:
        try:
            import h5py  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("h5py is required for grid geometry reads.") from exc

        base_pillar_count = (self.ni + 1) * (self.nj + 1)
        with h5py.File(h5_path, "r") as h5:
            if points_path not in h5:
                raise ValueError(f"Points dataset path not found in H5: {points_path}")
            dataset = h5[points_path]
            if len(dataset.shape) == 4 and dataset.shape[1] >= self.nj + 1 and dataset.shape[2] >= self.ni + 1:
                return np.asarray(dataset[0, : self.nj + 1, : self.ni + 1, :2], dtype=float).reshape(
                    base_pillar_count,
                    2,
                )
            if len(dataset.shape) == 3 and dataset.shape[2] >= 2:
                if dataset.shape[1] < base_pillar_count:
                    raise ValueError(
                        f"Points dataset has fewer pillars than expected: {dataset.shape[1]} < {base_pillar_count}"
                    )
                return np.asarray(dataset[0, :base_pillar_count, :2], dtype=float)
            raise ValueError(f"Unsupported Points dataset shape: {dataset.shape}")

    @staticmethod
    def _require_int(value: int | None, name: str) -> int:
        if value is None:
            raise ValueError(f"Grid metadata is missing {name}.")
        return int(value)


class StrictGridIndexer:
    def __init__(self, reader: ResqmlReader, grid: GridInfo | None = None) -> None:
        self.reader = reader
        self.grid = grid

    def find_cells_intersected_by_vertical_line(self, x: float, y: float) -> list[tuple[int, int, int]]:
        raise NotImplementedError("Strict vertical intersection mode is planned for version 2.")
