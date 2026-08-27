from __future__ import annotations

import pandas as pd

from app.workers.metrics_worker import MetricsRequest, MetricsWorker
from core.xlsx_preview import read_xlsx_preview


def test_metrics_worker_writes_metrics_xlsx(tmp_path) -> None:
    extracted_path = tmp_path / "extracted.csv"
    intervals_path = tmp_path / "intervals.csv"
    output_path = tmp_path / "metrics.xlsx"
    pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVD_top": [100.0],
            "TVD_base": [110.0],
            "CellHeight": [10.0],
            "NTG": [1.0],
            "PORO": [0.2],
            "PermX": [100.0],
        }
    ).to_csv(extracted_path, index=False)
    pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [110.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [110.0],
        }
    ).to_csv(intervals_path, index=False)
    worker = MetricsWorker(
        MetricsRequest(
            extracted_path=str(extracted_path),
            intervals_path=str(intervals_path),
            output_path=str(output_path),
            ntg_column="NTG",
            poro_column="PORO",
            perm_column="PermX",
            lithology_column=None,
            reservoir_values=[],
            property_columns=["NTG"],
            metric_keys=[],
        )
    )
    results = []
    failures = []
    worker.finished.connect(results.append)
    worker.failed.connect(lambda message, details: failures.append((message, details)))

    worker.run()

    assert failures == []
    assert len(results) == 1
    assert results[0].rows_written == 1
    assert results[0].description_path == str(tmp_path / "metrics.txt")
    assert (tmp_path / "metrics.txt").is_file()
    preview = read_xlsx_preview(output_path)
    assert preview.headers[:2] == ["Well", "Port"]
    assert preview.rows[0][:2] == ["A", "1"]
