from __future__ import annotations

from pathlib import Path

from core.resqml_reader import ResqmlReader
from core.rescue_reader import RescueReader, is_rescue_path


def open_model_reader(path: str | Path):
    model_path = resolve_model_path(path)
    reader = RescueReader(model_path) if is_rescue_path(model_path) else ResqmlReader(model_path)
    reader.open()
    return reader


def resolve_model_path(path: str | Path) -> Path:
    model_path = Path(path)
    if model_path.is_file():
        return model_path

    if not model_path.is_dir():
        return model_path

    rescue_file = _find_rescue_bin(model_path)
    if rescue_file is not None:
        return rescue_file

    epc_file = _find_first_file(model_path, "*.epc")
    if epc_file is not None:
        return epc_file

    return model_path


def _find_rescue_bin(folder: Path) -> Path | None:
    for candidate in sorted(folder.glob("*.bin")):
        if is_rescue_path(candidate):
            return candidate
    for candidate in sorted(folder.rglob("*.bin")):
        if is_rescue_path(candidate):
            return candidate
    return None


def _find_first_file(folder: Path, pattern: str) -> Path | None:
    direct = sorted(folder.glob(pattern))
    if direct:
        return direct[0]
    nested = sorted(folder.rglob(pattern))
    if nested:
        return nested[0]
    return None
