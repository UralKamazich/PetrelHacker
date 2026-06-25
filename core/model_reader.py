from __future__ import annotations

from pathlib import Path

from core.resqml_reader import ResqmlReader
from core.rescue_reader import RescueReader, is_rescue_path


def open_model_reader(path: str | Path):
    model_path = Path(path)
    reader = RescueReader(model_path) if is_rescue_path(model_path) else ResqmlReader(model_path)
    reader.open()
    return reader
