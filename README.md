# PetrelHacker

RESQML Sleeve Property Extractor MVP for Petrel exports.

## Current state

- Console RESQML diagnostics via `scripts/inspect_resqml.py`.
- EPC XML metadata reader in `core/resqml_reader.py`.
- Minimal PySide6 GUI with tabs from the project plan.
- Model loading runs in a worker thread.
- Local RESQML data is ignored by Git.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Inspect RESQML

```powershell
python scripts/inspect_resqml.py RESQML/Urengoy.epc
```

The inspector prints grids and properties without loading full HDF5 arrays.

## Read One Property Cell

```powershell
python scripts/test_single_cell_read.py RESQML/Urengoy.epc NTG 10 20 30
```

RESQML property arrays in the current Petrel export are stored as `NK x NJ x NI`,
so core reads property values as `dataset[k, j, i]`.

## Map Sleeves To Grid Columns

```powershell
python scripts/test_sleeves_index.py RESQML/Urengoy.epc Sleeves_coord.xlsx
```

The current fast indexer uses top XY pillar geometry and nearest column centers.

## Run Fast Extraction

```powershell
python scripts/run_fast_extraction.py RESQML/Urengoy.epc Sleeves_coord.xlsx --properties NTG Layers
```

The extractor reads vertical property slices as `dataset[:, j, i]` for the
current `NK x NJ x NI` HDF5 layout, then streams rows to an XLSX file generated
next to the sleeves file.

## Run GUI

```powershell
python main.py
```

GUI MVP workflow:

1. Open `Model`, select `.epc`, click `Load model`.
2. Open `Sleeves`, select CSV/XLSX coordinates.
3. Open `Properties`, check 1-3 properties.
4. Open `Run` and click `Run extraction`; the output XLSX path is generated next to the sleeves file.

## Notes

The next implementation step is the fast extraction path:

1. Load sleeves CSV/XLSX.
2. Map `Sleeve_ID`, `X`, `Y`.
3. Stream selected property values to XLSX and write `extraction_log.txt`.
