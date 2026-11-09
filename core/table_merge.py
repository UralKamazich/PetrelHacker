"""Merge several tables (e.g. metric files of different models) by key columns.

Rows are matched by the key columns. For every cell the first non-empty value in
file order is taken, so files that fill disjoint rows (each model computes
metrics only for its own wells) combine into one table. When two files hold
different non-empty values for the same cell the first one is kept and the
conflict is reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os

import numpy as np
import pandas as pd

from core.exporter import export_xlsx

SOURCE_COLUMN = "Merge_source"
_SEPARATORS = ("_", "-", " ", ".")
_LOOKALIKES = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X"})


@dataclass(frozen=True)
class MergeInput:
    label: str
    frame: pd.DataFrame


@dataclass
class MergeResult:
    frame: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    file_stats: list[dict] = field(default_factory=list)
    conflicts: int = 0


def file_labels(paths: list[str | Path]) -> list[str]:
    """Short labels: file stems with the common prefix/suffix removed (…_metrics_3А → 3А)."""
    stems = [Path(path).stem for path in paths]
    if len(stems) < 2:
        return stems
    # Common parts are cut only at separators so "…_3А" and "…_5А" keep the shared "А".
    prefix = os.path.commonprefix(stems)
    prefix = prefix[: max((prefix.rfind(sep) + 1 for sep in _SEPARATORS), default=0)]
    suffix = os.path.commonprefix([stem[::-1] for stem in stems])[::-1]
    cuts = [suffix.find(sep) for sep in _SEPARATORS if sep in suffix]
    suffix = suffix[min(cuts):] if cuts else ""
    labels = []
    for stem in stems:
        core = stem[len(prefix): len(stem) - len(suffix)].strip("".join(_SEPARATORS))
        labels.append(core or stem)
    if len(set(labels)) != len(labels):
        labels = stems if len(set(stems)) == len(stems) else [f"{stem}#{index}" for index, stem in enumerate(stems, start=1)]
    return labels


def merge_tables(inputs: list[MergeInput], key_columns: list[str], *, add_source_column: bool = True) -> MergeResult:
    if len(inputs) < 2:
        raise ValueError("Select at least two files to merge.")
    keys = [str(column).strip() for column in key_columns if str(column).strip()]
    if not keys:
        raise ValueError("Select key columns.")
    if len(set(keys)) != len(keys):
        raise ValueError("Key columns must be different.")

    warnings: list[str] = []
    prepared: list[tuple[str, pd.DataFrame]] = []
    columns: list[str] = []
    ordered: list[str] = []
    for item in inputs:
        frame = _with_key_columns(item.frame, keys, item.label)
        key_index = pd.MultiIndex.from_frame(frame[keys].apply(lambda series: series.map(_normalize_key)))
        empty_keys = key_index.to_frame().eq("").all(axis=1).to_numpy()
        if empty_keys.any():
            warnings.append(f"{item.label}: {int(empty_keys.sum())} row(s) without key values were skipped.")
            frame, key_index = frame[~empty_keys], key_index[~empty_keys]
        duplicated = key_index.duplicated()
        if duplicated.any():
            examples = ", ".join("/".join(map(str, value)) for value in key_index[duplicated][:5])
            warnings.append(f"{item.label}: {int(duplicated.sum())} duplicate key row(s) ignored (first kept): {examples}.")
            frame, key_index = frame[~duplicated], key_index[~duplicated]
        frame = frame.set_axis(key_index, axis=0)
        frame.index.names = keys
        prepared.append((item.label, frame))
        columns.extend(column for column in frame.columns if column not in columns and column not in keys)
        ordered.extend(column for column in frame.columns if column not in ordered)

    row_index = prepared[0][1].index
    for _label, frame in prepared[1:]:
        row_index = row_index.append(frame.index[~frame.index.isin(row_index)])

    aligned = [(label, frame.reindex(index=row_index, columns=columns).astype(object)) for label, frame in prepared]
    filled = [frame.map(_is_filled).to_numpy() for _label, frame in aligned]

    result = aligned[0][1].copy()
    result_filled = filled[0].copy()
    conflict_counts = np.zeros(len(columns), dtype=int)
    for (_label, frame), frame_filled in zip(aligned[1:], filled[1:], strict=True):
        both = result_filled & frame_filled
        if both.any():
            rows, cols = np.nonzero(both)
            for row, col in zip(rows, cols, strict=True):
                if not _same_value(result.iat[row, col], frame.iat[row, col]):
                    conflict_counts[col] += 1
        take = frame_filled & ~result_filled
        result = result.mask(take, frame)
        result_filled |= take

    file_stats = []
    contributors: list[list[str]] = [[] for _ in range(len(row_index))]
    for index, (label, frame) in enumerate(aligned):
        others_empty = np.zeros_like(filled[index])
        for other, other_filled in enumerate(filled):
            if other != index:
                others_empty |= ~other_filled
        contributes = (filled[index] & others_empty).any(axis=1)
        for row in np.nonzero(contributes)[0]:
            contributors[row].append(label)
        file_stats.append(
            {
                "label": label,
                "rows": int(len(prepared[index][1])),
                "rowsContributed": int(contributes.sum()),
            }
        )

    # Empty cells are written as blanks; keys get back their original spelling from the first file.
    output = result.where(result_filled, None).reset_index()
    original_keys = _original_key_values(prepared, keys, row_index)
    for key in keys:
        output[key] = original_keys[key]
    output = output[ordered]
    if add_source_column:
        source_name = SOURCE_COLUMN if SOURCE_COLUMN not in output.columns else f"{SOURCE_COLUMN}_merged"
        output[source_name] = ["+".join(values) for values in contributors]

    warnings.extend(_unit_mismatch_warnings(prepared))
    conflicts = int(conflict_counts.sum())
    if conflicts:
        worst = sorted(
            ((count, column) for count, column in zip(conflict_counts, columns, strict=True) if count),
            reverse=True,
        )[:5]
        details = ", ".join(f"{column} ({count})" for count, column in worst)
        warnings.append(
            f"{conflicts} cell(s) have different non-empty values in several files; the value from the first file was kept. "
            f"Columns: {details}."
        )
    no_data = sum(1 for values in contributors if not values)
    if add_source_column and no_data:
        warnings.append(f"{no_data} row(s) have identical data in all files (empty {SOURCE_COLUMN}), e.g. no metrics in any model.")
    return MergeResult(frame=output, warnings=warnings, file_stats=file_stats, conflicts=conflicts)


def _unit_mismatch_warnings(prepared: list[tuple[str, pd.DataFrame]]) -> list[str]:
    """Warn when a stress column differs between files by about x10 (MPa vs atm)."""
    reference = "Shmin_avg_Local"
    medians = {}
    for label, frame in prepared:
        if reference in frame.columns:
            values = pd.to_numeric(frame[reference], errors="coerce")
            values = values[values > 0]
            if len(values):
                medians[label] = float(values.median())
    if len(medians) < 2:
        return []
    low, high = min(medians.values()), max(medians.values())
    if low <= 0 or high / low < 5:
        return []
    details = ", ".join(f"{label}: {value:.1f}" for label, value in medians.items())
    return [
        f"Shmin looks to be in different units in the files (median {reference} {details}): "
        "probably MPa vs atm. Recalculate the metrics with the same Shmin units before clustering."
    ]


def write_merged_table(result: MergeResult, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        result.frame.to_csv(path, index=False)
    else:
        export_xlsx(result.frame, path)


def _with_key_columns(frame: pd.DataFrame, keys: list[str], label: str) -> pd.DataFrame:
    rename: dict[object, str] = {}
    lookup = {str(column).strip().lower(): column for column in frame.columns}
    missing = []
    for key in keys:
        if key in frame.columns:
            continue
        match = lookup.get(key.lower())
        if match is None:
            missing.append(key)
        else:
            rename[match] = key
    if missing:
        raise ValueError(f"{label}: key column(s) not found: {', '.join(missing)}.")
    frame = frame.rename(columns=rename)
    frame.columns = [str(column) for column in frame.columns]
    if frame.columns.duplicated().any():
        frame = frame.loc[:, ~frame.columns.duplicated()]
    return frame


def _original_key_values(prepared: list[tuple[str, pd.DataFrame]], keys: list[str], row_index: pd.MultiIndex) -> dict[str, list]:
    values: dict[str, dict] = {key: {} for key in keys}
    for _label, frame in prepared:
        for key in keys:
            for index_value, value in zip(frame.index, frame[key], strict=True):
                values[key].setdefault(index_value, value)
    return {key: [values[key].get(index_value) for index_value in row_index] for key in keys}


def _normalize_key(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NA:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip().upper().translate(_LOOKALIKES)
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        text = text[:-2]
    return text


def _is_filled(value: object) -> bool:
    if value is None or value is pd.NA:
        return False
    if isinstance(value, float) and np.isnan(value):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return not (isinstance(value, pd.Timestamp) and pd.isna(value))


def _same_value(left: object, right: object) -> bool:
    left_number = _as_number(left)
    right_number = _as_number(right)
    if left_number is not None and right_number is not None:
        return bool(np.isclose(left_number, right_number, rtol=1e-9, atol=1e-12))
    return str(left).strip() == str(right).strip()


def _as_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    return None
