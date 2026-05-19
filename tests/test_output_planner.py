from __future__ import annotations

from core.exporter import EXCEL_ROW_LIMIT
from core.output_planner import choose_output_plan


def test_choose_output_plan_keeps_xlsx_within_excel_limit() -> None:
    plan = choose_output_plan("out.xlsx", sleeve_count=10, nk=20)
    assert plan.format == "XLSX"
    assert plan.path.name == "out.xlsx"
    assert plan.warning is None


def test_choose_output_plan_switches_xlsx_to_csv_over_excel_limit() -> None:
    plan = choose_output_plan("out.xlsx", sleeve_count=EXCEL_ROW_LIMIT, nk=2)
    assert plan.format == "CSV"
    assert plan.path.name == "out.csv"
    assert plan.warning is not None
    assert "Saved CSV instead" in plan.warning


def test_choose_output_plan_keeps_requested_csv() -> None:
    plan = choose_output_plan("out.csv", sleeve_count=EXCEL_ROW_LIMIT, nk=2)
    assert plan.format == "CSV"
    assert plan.path.name == "out.csv"
    assert plan.warning is None
