from __future__ import annotations

from core.csv_preview import read_csv_preview


def test_read_csv_preview_reads_headers_and_limited_rows(tmp_path) -> None:
    path = tmp_path / "out.csv"
    path.write_text("A,B\n1,2\n3,4\n", encoding="utf-8-sig")

    preview = read_csv_preview(path, max_rows=1)

    assert preview.headers == ["A", "B"]
    assert preview.rows == [["1", "2"]]
