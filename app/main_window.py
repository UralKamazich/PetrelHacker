from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtCore import QSettings, QThread
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.widgets.checklist_dialog import CheckListDialog
from app.widgets.curve_plot import CurvePlotData, CurvePlotWidget, CurveSpec
from app.widgets.log_panel import LogPanel
from app.workers.extraction_worker import ExtractionRequest, ExtractionResult, ExtractionWorker
from app.workers.load_model_worker import LoadModelWorker, ModelLoadResult
from app.workers.metrics_worker import MetricsRequest, MetricsResult, MetricsWorker
from core.interval_metrics import DEFAULT_METRIC_KEYS
from core.multi_model_extractor import ExtractionModelSpec
from core.csv_preview import read_csv_preview
from core.exporter import default_extraction_output_path
from core.property_presets import normalize_property_title, should_select_property
from core.sleeves_loader import load_sleeves_table, validate_sleeves_table
from core.table_io import read_table
from core.xlsx_preview import read_xlsx_headers, read_xlsx_preview


METRIC_OPTIONS = [
    ("Thickness", "thickness"),
    ("Net thickness", "net_thickness"),
    ("NTG avg", "ntg_avg"),
    ("NTG median", "ntg_median"),
    ("PORO avg", "poro_avg"),
    ("PORO median", "poro_median"),
    ("PERM arithmetic avg", "perm_avg_arith"),
    ("PERM geometric avg", "perm_avg_geom"),
    ("PERM median", "perm_median"),
    ("KH", "kh"),
    ("PHIH", "phih"),
    ("Additional: avg", "avg"),
    ("Additional: arithmetic mean", "mean_arith"),
    ("Additional: geometric mean", "geom"),
    ("Additional: median", "median"),
    ("Additional: min", "min"),
    ("Additional: max", "max"),
    ("Additional: integral", "integral"),
    ("Additional: min*", "min_star"),
    ("Additional: max*", "max_star"),
    ("Additional: std", "std"),
    ("Additional: delta", "delta"),
]


class MainWindow(QMainWindow):
    SETTINGS_ORG = "PetrelHacker"
    SETTINGS_APP = "SleeveExtractor"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PetrelHacker - Model Sleeve Property Extractor")
        self.settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self._load_thread: QThread | None = None
        self._load_worker: LoadModelWorker | None = None
        self._extraction_thread: QThread | None = None
        self._extraction_worker: ExtractionWorker | None = None
        self._metrics_thread: QThread | None = None
        self._metrics_worker: MetricsWorker | None = None
        self._model_result: ModelLoadResult | None = None
        self._model_results: list[ModelLoadResult] = []
        self._sleeves_loaded = False
        self._last_extracted_headers: list[str] = []
        self._curve_df: pd.DataFrame | None = None
        self._restoring_curve_settings = False
        self._selected_metric_keys = list(DEFAULT_METRIC_KEYS)

        self.epc_path_edit = QLineEdit()
        self.epc_path_edit.setPlaceholderText("Select .epc file or Rescue folder")
        self.model_path_edits = [self.epc_path_edit, QLineEdit(), QLineEdit()]
        for edit in self.model_path_edits[1:]:
            edit.setPlaceholderText("Optional .epc file or Rescue folder")
        self.model_offset_edits = [QLineEdit(), QLineEdit(), QLineEdit()]
        for edit in self.model_offset_edits:
            edit.setPlaceholderText("0")
            edit.setText("0")
        self.model_browse_buttons = [QPushButton("Browse") for _ in range(3)]
        self.h5_path_label = QLabel("-")
        self.backend_label = QLabel("-")
        self.load_button = QPushButton("Load models")
        self.browse_epc_button = self.model_browse_buttons[0]
        self.grids_table = self._table(["Model", "Title", "UUID", "NI", "NJ", "NK", "Type"])
        self.properties_table = self._table(["Use", "Model", "Title", "UUID", "Indexable", "UOM", "Kind", "Type"])
        self.sleeves_path_edit = QLineEdit()
        self.sleeves_path_edit.setPlaceholderText("Select CSV/XLSX sleeves table")
        self.sleeves_status_label = QLabel("-")
        self.sleeves_preview_table = self._table(["Well", "Port", "X", "Y"])
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Output XLSX is generated next to sleeves file")
        self.skip_inactive_checkbox = QCheckBox("Skip inactive cells")
        self.skip_inactive_checkbox.setChecked(True)
        self.run_button = QPushButton("Run extraction")
        self.cancel_button = QPushButton("Cancel")
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.log_panel = LogPanel()
        self.qc_status_label = QLabel("No extraction results yet.")
        self.qc_preview_table = self._table(["Well", "Port", "X", "Y", "I", "J", "K"])
        self.metrics_extracted_path_edit = QLineEdit()
        self.metrics_extracted_path_edit.setPlaceholderText("Select extracted XLSX/CSV")
        self.metrics_intervals_path_edit = QLineEdit()
        self.metrics_intervals_path_edit.setPlaceholderText("Select intervals XLSX/CSV")
        self.metrics_output_path_edit = QLineEdit()
        self.metrics_output_path_edit.setPlaceholderText("Output metrics XLSX")
        self.metrics_ntg_combo = self._combo()
        self.metrics_poro_combo = self._combo()
        self.metrics_perm_combo = self._combo()
        self.metrics_lithology_combo = self._combo()
        self.metrics_reservoir_values_edit = QLineEdit()
        self.metrics_reservoir_values_edit.setPlaceholderText("Example: 1,2")
        self.metrics_property_list = QListWidget()
        self.metrics_property_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.metrics_select_properties_button = QPushButton("Select channels")
        self.metrics_properties_edit = QLineEdit()
        self.metrics_properties_edit.setPlaceholderText("Example: NTG,PORO,Perm_1A")
        self.metrics_properties_edit.setReadOnly(True)
        self.metrics_select_metrics_button = QPushButton("Select metrics")
        self.metrics_metric_keys_edit = QLineEdit()
        self.metrics_metric_keys_edit.setReadOnly(True)
        self.metrics_run_button = QPushButton("Calculate metrics")
        self.metrics_run_button.setEnabled(False)
        self.metrics_progress_bar = QProgressBar()
        self.metrics_status_label = QLabel("No metrics calculated yet.")
        self.metrics_preview_table = self._table(["Well", "Port"])
        self.curve_extracted_path_edit = QLineEdit()
        self.curve_extracted_path_edit.setPlaceholderText("Select extracted XLSX/CSV")
        self.curve_load_button = QPushButton("Load")
        self.curve_well_combo = self._combo()
        self.curve_port_combo = self._combo()
        self.curve1_combo = self._combo()
        self.curve2_combo = self._combo()
        self.curve3_combo = self._combo()
        self.curve4_combo = self._combo()
        self.curve_depth_min_spin = self._spinbox()
        self.curve_depth_max_spin = self._spinbox()
        self.curve1_min_spin = self._spinbox()
        self.curve1_max_spin = self._spinbox()
        self.curve2_min_spin = self._spinbox()
        self.curve2_max_spin = self._spinbox()
        self.curve3_min_spin = self._spinbox()
        self.curve3_max_spin = self._spinbox()
        self.curve4_min_spin = self._spinbox()
        self.curve4_max_spin = self._spinbox()
        self.curve2_depth_shift_spin = self._spinbox()
        self.curve3_depth_shift_spin = self._spinbox()
        self.curve4_depth_shift_spin = self._spinbox()
        self.curve_auto_range_button = QPushButton("Auto range")
        self.curve_plot_button = QPushButton("Draw")
        self.curve_status_label = QLabel("No curve data loaded.")
        self.curve_plot = CurvePlotWidget()

        tabs = QTabWidget()
        tabs.addTab(self._model_tab(), "Model")
        tabs.addTab(self._sleeves_tab(), "Sleeves")
        tabs.addTab(self._properties_tab(), "Properties")
        tabs.addTab(self._run_tab(), "Run")
        tabs.addTab(self._preview_tab(), "Preview / QC")
        tabs.addTab(self._curves_tab(), "Curves / QC")
        tabs.addTab(self._metrics_tab(), "Metrics")
        self.setCentralWidget(tabs)

        for index, button in enumerate(self.model_browse_buttons):
            button.clicked.connect(lambda _checked=False, model_index=index: self._browse_epc(model_index))
        self.load_button.clicked.connect(self._load_model)
        self.output_path_edit.textChanged.connect(self._update_run_enabled)
        self.run_button.clicked.connect(self._run_extraction)
        self.cancel_button.clicked.connect(self._cancel_extraction)
        self.metrics_extracted_path_edit.textChanged.connect(self._on_metrics_extracted_path_changed)
        self.metrics_intervals_path_edit.textChanged.connect(self._update_metrics_enabled)
        self.metrics_output_path_edit.textChanged.connect(self._update_metrics_enabled)
        self.metrics_property_list.itemSelectionChanged.connect(self._sync_metrics_properties_from_list)
        self.metrics_select_properties_button.clicked.connect(self._open_metrics_properties_dialog)
        self.metrics_select_metrics_button.clicked.connect(self._open_metrics_dialog)
        self.metrics_run_button.clicked.connect(self._run_metrics)
        self.curve_load_button.clicked.connect(self._load_curve_table)
        self.curve_well_combo.currentTextChanged.connect(self._on_curve_well_changed)
        self.curve_port_combo.currentTextChanged.connect(self._on_curve_control_changed)
        self.curve1_combo.currentTextChanged.connect(self._on_curve_control_changed)
        self.curve2_combo.currentTextChanged.connect(self._on_curve_control_changed)
        self.curve3_combo.currentTextChanged.connect(self._on_curve_control_changed)
        self.curve4_combo.currentTextChanged.connect(self._on_curve_control_changed)
        self.curve2_depth_shift_spin.valueChanged.connect(self._on_curve_control_changed)
        self.curve3_depth_shift_spin.valueChanged.connect(self._on_curve_control_changed)
        self.curve4_depth_shift_spin.valueChanged.connect(self._on_curve_control_changed)
        for spinbox in (
            self.curve_depth_min_spin,
            self.curve_depth_max_spin,
            self.curve1_min_spin,
            self.curve1_max_spin,
            self.curve2_min_spin,
            self.curve2_max_spin,
            self.curve3_min_spin,
            self.curve3_max_spin,
            self.curve4_min_spin,
            self.curve4_max_spin,
        ):
            spinbox.valueChanged.connect(self._on_curve_control_changed)
        self.curve_auto_range_button.clicked.connect(self._auto_curve_ranges)
        self.curve_plot_button.clicked.connect(self._update_curve_plot)
        self._restore_last_paths()

    def _model_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        for index, (path_edit, offset_edit, browse_button) in enumerate(
            zip(self.model_path_edits, self.model_offset_edits, self.model_browse_buttons, strict=False),
            start=1,
        ):
            file_row = QHBoxLayout()
            file_row.addWidget(QLabel(f"M{index}"))
            file_row.addWidget(path_edit, 1)
            file_row.addWidget(QLabel("Depth +/- m"))
            file_row.addWidget(offset_edit)
            file_row.addWidget(browse_button)
            layout.addLayout(file_row)

        load_row = QHBoxLayout()
        load_row.addWidget(self.load_button)
        load_row.addStretch(1)
        layout.addLayout(load_row)

        info = QGroupBox("Model info")
        form = QFormLayout(info)
        form.addRow("Backend", self.backend_label)
        form.addRow("Detected H5", self.h5_path_label)
        layout.addWidget(info)
        layout.addWidget(QLabel("Grids"))
        layout.addWidget(self.grids_table, 1)
        return tab

    def _sleeves_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QHBoxLayout()
        browse = QPushButton("Browse")
        row.addWidget(self.sleeves_path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        layout.addWidget(self.sleeves_status_label)
        layout.addWidget(self.sleeves_preview_table, 1)
        browse.clicked.connect(self._browse_sleeves)
        return tab

    def _properties_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        actions = QHBoxLayout()
        select_all = QPushButton("Select all")
        clear = QPushButton("Clear")
        actions.addWidget(select_all)
        actions.addWidget(clear)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self.properties_table, 1)
        select_all.clicked.connect(lambda: self._set_property_checks(True))
        clear.clicked.connect(lambda: self._set_property_checks(False))
        return tab

    def _run_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        fast_mode = QCheckBox("Fast column mode")
        fast_mode.setChecked(True)
        strict_mode = QCheckBox("Strict vertical intersection mode")
        strict_mode.setEnabled(False)
        layout.addWidget(fast_mode)
        layout.addWidget(strict_mode)
        layout.addWidget(self.skip_inactive_checkbox)

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_path_edit, 1)
        layout.addLayout(output_row)

        buttons = QHBoxLayout()
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_panel, 1)
        return tab

    def _preview_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self.qc_status_label)
        layout.addWidget(self.qc_preview_table, 1)
        return tab

    def _curves_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        file_row = QHBoxLayout()
        browse = QPushButton("Browse")
        file_row.addWidget(QLabel("Extracted"))
        file_row.addWidget(self.curve_extracted_path_edit, 1)
        file_row.addWidget(browse)
        file_row.addWidget(self.curve_load_button)
        layout.addLayout(file_row)

        controls = QGroupBox("Curve controls")
        grid = QGridLayout(controls)
        grid.addWidget(QLabel("Well"), 0, 0)
        grid.addWidget(self.curve_well_combo, 0, 1)
        grid.addWidget(QLabel("Port"), 0, 2)
        grid.addWidget(self.curve_port_combo, 0, 3)
        grid.addWidget(QLabel("Range"), 1, 0)
        grid.addWidget(QLabel("Channel"), 1, 1)
        grid.addWidget(QLabel("Min"), 1, 2)
        grid.addWidget(QLabel("Max"), 1, 3)
        grid.addWidget(QLabel("Shift m"), 1, 4)
        grid.addWidget(QLabel("Depth"), 2, 0)
        grid.addWidget(self.curve_depth_min_spin, 2, 1)
        grid.addWidget(self.curve_depth_max_spin, 2, 2)
        grid.addWidget(self.curve_auto_range_button, 2, 3)
        grid.addWidget(QLabel("Scale 1"), 3, 0)
        grid.addWidget(self.curve1_combo, 3, 1)
        grid.addWidget(self.curve1_min_spin, 3, 2)
        grid.addWidget(self.curve1_max_spin, 3, 3)
        grid.addWidget(QLabel("Scale 2"), 4, 0)
        grid.addWidget(self.curve2_combo, 4, 1)
        grid.addWidget(self.curve2_min_spin, 4, 2)
        grid.addWidget(self.curve2_max_spin, 4, 3)
        grid.addWidget(self.curve2_depth_shift_spin, 4, 4)
        grid.addWidget(QLabel("Scale 3"), 5, 0)
        grid.addWidget(self.curve3_combo, 5, 1)
        grid.addWidget(self.curve3_min_spin, 5, 2)
        grid.addWidget(self.curve3_max_spin, 5, 3)
        grid.addWidget(self.curve3_depth_shift_spin, 5, 4)
        grid.addWidget(QLabel("Scale 4"), 6, 0)
        grid.addWidget(self.curve4_combo, 6, 1)
        grid.addWidget(self.curve4_min_spin, 6, 2)
        grid.addWidget(self.curve4_max_spin, 6, 3)
        grid.addWidget(self.curve4_depth_shift_spin, 6, 4)
        grid.addWidget(self.curve_plot_button, 6, 5)
        layout.addWidget(controls)

        layout.addWidget(self.curve_status_label)
        layout.addWidget(self.curve_plot, 1)
        browse.clicked.connect(self._browse_curve_extracted)
        return tab

    def _metrics_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        extracted_row = QHBoxLayout()
        browse_extracted = QPushButton("Browse")
        extracted_row.addWidget(QLabel("Extracted"))
        extracted_row.addWidget(self.metrics_extracted_path_edit, 1)
        extracted_row.addWidget(browse_extracted)
        layout.addLayout(extracted_row)

        intervals_row = QHBoxLayout()
        browse_intervals = QPushButton("Browse")
        intervals_row.addWidget(QLabel("Frac list"))
        intervals_row.addWidget(self.metrics_intervals_path_edit, 1)
        intervals_row.addWidget(browse_intervals)
        layout.addLayout(intervals_row)

        output_row = QHBoxLayout()
        browse_output = QPushButton("Browse")
        output_row.addWidget(QLabel("Output"))
        output_row.addWidget(self.metrics_output_path_edit, 1)
        output_row.addWidget(browse_output)
        layout.addLayout(output_row)

        settings_box = QGroupBox("Settings")
        form = QFormLayout(settings_box)
        form.addRow("NTG column", self.metrics_ntg_combo)
        form.addRow("PORO column", self.metrics_poro_combo)
        form.addRow("PERM column", self.metrics_perm_combo)
        form.addRow("Lithology column", self.metrics_lithology_combo)
        form.addRow("Reservoir values", self.metrics_reservoir_values_edit)
        property_row = QHBoxLayout()
        property_row.addWidget(self.metrics_properties_edit, 1)
        property_row.addWidget(self.metrics_select_properties_button)
        form.addRow("Additional channels", property_row)
        metric_row = QHBoxLayout()
        metric_row.addWidget(self.metrics_metric_keys_edit, 1)
        metric_row.addWidget(self.metrics_select_metrics_button)
        form.addRow("Metrics", metric_row)
        layout.addWidget(settings_box)

        buttons = QHBoxLayout()
        buttons.addWidget(self.metrics_run_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addWidget(self.metrics_progress_bar)
        layout.addWidget(self.metrics_status_label)
        layout.addWidget(self.metrics_preview_table, 1)

        browse_extracted.clicked.connect(self._browse_metrics_extracted)
        browse_intervals.clicked.connect(self._browse_metrics_intervals)
        browse_output.clicked.connect(self._browse_metrics_output)
        return tab

    def _browse_epc(self, model_index: int = 0) -> None:
        dialog = QFileDialog(self, "Select model file or Rescue folder")
        dialog.setFileMode(QFileDialog.AnyFile)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.ShowDirsOnly, False)
        dialog.setNameFilters(["Model files (*.epc *.bin)", "All files (*)"])
        if dialog.exec():
            selected = dialog.selectedFiles()
            if selected:
                self.model_path_edits[model_index].setText(selected[0])
                self._save_last_paths()

    def _browse_sleeves(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select sleeves table",
            "",
            "Tables (*.csv *.xlsx);;All files (*)",
        )
        if path:
            self.sleeves_path_edit.setText(path)
            self._load_sleeves_preview(path)
            self._save_last_paths()

    def _browse_metrics_extracted(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select extracted table", "", "Tables (*.xlsx *.csv);;All files (*)")
        if path:
            self.metrics_extracted_path_edit.setText(path)
            self._set_default_metrics_output(path)
            self._load_metrics_channel_options(path)
            self._save_last_paths()

    def _browse_curve_extracted(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select extracted table", "", "Tables (*.xlsx *.csv);;All files (*)")
        if path:
            self.curve_extracted_path_edit.setText(path)
            self._load_curve_table()
            self._save_last_paths()

    def _browse_metrics_intervals(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select intervals table", "", "Tables (*.xlsx *.csv);;All files (*)")
        if path:
            self.metrics_intervals_path_edit.setText(path)
            self._save_last_paths()

    def _browse_metrics_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save metrics XLSX", "", "Excel workbook (*.xlsx);;All files (*)")
        if path:
            self.metrics_output_path_edit.setText(str(Path(path).with_suffix(".xlsx")))
            self._save_last_paths()

    def _load_model(self) -> None:
        if not self.model_path_edits[0].text().strip():
            QMessageBox.warning(self, "Missing primary model", "Select M1 first; it defines output geometry and rows.")
            return
        offsets = self._model_depth_offsets()
        model_pairs = [
            (edit.text().strip(), offsets[index])
            for index, edit in enumerate(self.model_path_edits)
            if edit.text().strip()
        ]
        model_paths = [path for path, _offset in model_pairs]
        if not model_paths:
            QMessageBox.warning(self, "Missing model", "Select at least one EPC file or Rescue folder first.")
            return
        depth_offsets = [offset for _path, offset in model_pairs]

        self._save_last_paths()
        self.load_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.log_panel.append_message("Starting model load...")

        self._load_thread = QThread(self)
        self._load_worker = LoadModelWorker(model_paths, depth_offsets)
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.log.connect(self.log_panel.append_message)
        self._load_worker.finished.connect(self._on_model_loaded)
        self._load_worker.failed.connect(self._on_model_load_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.failed.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.finished.connect(self._reset_load_worker_refs)
        self._load_thread.start()

    def _on_model_loaded(self, result: ModelLoadResult | list[ModelLoadResult]) -> None:
        results = result if isinstance(result, list) else [result]
        self._model_results = results
        self._model_result = results[0] if results else None
        self.backend_label.setText("; ".join(f"{item.label}:{item.backend}" for item in results) or "-")
        self.h5_path_label.setText("; ".join(f"{item.label}:{item.h5_path or '-'}" for item in results) or "-")
        self._fill_grids(results)
        self._fill_properties(results)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.load_button.setEnabled(True)
        self.log_panel.append_message("Model load finished.")
        self._update_run_enabled()

    def _on_model_load_failed(self, message: str, details: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.load_button.setEnabled(True)
        self.log_panel.append_message(f"Load failed: {message}")
        self.log_panel.append_message(details)
        QMessageBox.critical(self, "Load failed", message)

    def _reset_load_worker_refs(self) -> None:
        self._load_thread = None
        self._load_worker = None

    def _fill_grids(self, results: list[ModelLoadResult]) -> None:
        row_count = sum(len(result.grids) for result in results)
        self.grids_table.setRowCount(row_count)
        row = 0
        for result in results:
            for grid in result.grids:
                values = [
                    result.label,
                    grid.title,
                    grid.uuid,
                    "" if grid.ni is None else str(grid.ni),
                    "" if grid.nj is None else str(grid.nj),
                    "" if grid.nk is None else str(grid.nk),
                    grid.grid_type or "",
                ]
                for col, value in enumerate(values):
                    self.grids_table.setItem(row, col, QTableWidgetItem(value))
                row += 1
        self.grids_table.resizeColumnsToContents()

    def _fill_properties(self, results: list[ModelLoadResult]) -> None:
        saved_uuids = self._saved_property_uuids()
        saved_titles = self._saved_property_titles()
        use_defaults = not saved_uuids and not saved_titles
        row_count = sum(len(result.properties) for result in results)
        self.properties_table.setRowCount(row_count)
        row = 0
        for result in results:
            for prop in result.properties:
                check = QCheckBox()
                check.setChecked(should_select_property(prop, saved_uuids, saved_titles, use_defaults))
                check.stateChanged.connect(self._update_run_enabled)
                check.stateChanged.connect(self._save_selected_properties)
                self.properties_table.setCellWidget(row, 0, check)
                values = [
                    result.label,
                    prop.title,
                    prop.uuid,
                    prop.indexable_element or "",
                    prop.uom or "",
                    prop.property_kind or "",
                    prop.property_type or "",
                ]
                for offset, value in enumerate(values, start=1):
                    self.properties_table.setItem(row, offset, QTableWidgetItem(value))
                row += 1
        self.properties_table.resizeColumnsToContents()
        self._update_run_enabled()

    def _load_sleeves_preview(self, path: str) -> None:
        try:
            df = load_sleeves_table(path)
            warnings = validate_sleeves_table(df)
        except Exception as exc:  # noqa: BLE001
            self.sleeves_status_label.setText(f"Failed to load sleeves: {exc}")
            QMessageBox.critical(self, "Sleeves load failed", str(exc))
            return

        preview = df.head(100)
        self.sleeves_preview_table.setColumnCount(len(preview.columns))
        self.sleeves_preview_table.setHorizontalHeaderLabels([str(column) for column in preview.columns])
        self.sleeves_preview_table.setRowCount(len(preview))
        for row_index, row in preview.reset_index(drop=True).iterrows():
            for col_index, value in enumerate(row.tolist()):
                self.sleeves_preview_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        self.sleeves_preview_table.resizeColumnsToContents()

        status = f"Loaded sleeves: {len(df)} rows"
        if warnings:
            status += " | " + " ".join(warnings)
        self.sleeves_status_label.setText(status)
        self.log_panel.append_message(status)
        self.output_path_edit.setText(str(default_extraction_output_path(path)))
        self._sleeves_loaded = True
        self._save_last_paths()
        self._update_run_enabled()

    def _set_property_checks(self, checked: bool) -> None:
        for row in range(self.properties_table.rowCount()):
            widget = self.properties_table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(checked)
        self._save_selected_properties()
        self._update_run_enabled()

    def _selected_property_uuids(self) -> list[str]:
        uuids: list[str] = []
        for row in range(self.properties_table.rowCount()):
            widget = self.properties_table.cellWidget(row, 0)
            uuid_item = self.properties_table.item(row, 3)
            if isinstance(widget, QCheckBox) and widget.isChecked() and uuid_item is not None:
                uuids.append(uuid_item.text())
        return uuids

    def _selected_property_titles(self) -> list[str]:
        titles: list[str] = []
        for row in range(self.properties_table.rowCount()):
            widget = self.properties_table.cellWidget(row, 0)
            title_item = self.properties_table.item(row, 2)
            if isinstance(widget, QCheckBox) and widget.isChecked() and title_item is not None:
                titles.append(title_item.text())
        return titles

    def _selected_property_uuids_by_model(self) -> dict[str, list[str]]:
        selected: dict[str, list[str]] = {}
        for row in range(self.properties_table.rowCount()):
            widget = self.properties_table.cellWidget(row, 0)
            model_item = self.properties_table.item(row, 1)
            uuid_item = self.properties_table.item(row, 3)
            if (
                isinstance(widget, QCheckBox)
                and widget.isChecked()
                and model_item is not None
                and uuid_item is not None
            ):
                selected.setdefault(model_item.text(), []).append(uuid_item.text())
        return selected

    def _extraction_model_specs(self) -> list[ExtractionModelSpec]:
        selected_by_model = self._selected_property_uuids_by_model()
        specs: list[ExtractionModelSpec] = []
        offsets = self._model_depth_offsets()
        for result in self._model_results:
            specs.append(
                ExtractionModelSpec(
                    path=result.epc_path,
                    selected_property_uuids=selected_by_model.get(result.label, []),
                    depth_offset=offsets[result.model_index] if result.model_index < len(offsets) else result.depth_offset,
                    label=result.label,
                )
            )
        return specs

    def _model_depth_offsets(self) -> list[float]:
        offsets: list[float] = []
        for edit in self.model_offset_edits:
            text = edit.text().strip().replace(",", ".")
            if not text:
                offsets.append(0.0)
                continue
            try:
                offsets.append(float(text))
            except ValueError:
                offsets.append(0.0)
        return offsets

    def _saved_property_uuids(self) -> set[str]:
        return set(self._settings_list("properties/selected_uuids"))

    def _saved_property_titles(self) -> set[str]:
        return {normalize_property_title(value) for value in self._settings_list("properties/selected_titles")}

    def _settings_list(self, key: str) -> list[str]:
        value = self.settings.value(key, [], type=list)
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [str(item) for item in value if str(item)]

    def _save_selected_properties(self, *args) -> None:
        self.settings.setValue("properties/selected_uuids", self._selected_property_uuids())
        self.settings.setValue("properties/selected_titles", self._selected_property_titles())
        self._refresh_metrics_channel_options()

    def _restore_last_paths(self) -> None:
        epc_path = self.settings.value("paths/epc", "", type=str)
        sleeves_path = self.settings.value("paths/sleeves", "", type=str)
        extracted_path = self.settings.value("paths/metrics_extracted", "", type=str)
        curve_extracted_path = self.settings.value("paths/curve_extracted", "", type=str)
        intervals_path = self.settings.value("paths/metrics_intervals", "", type=str)
        metrics_output_path = self.settings.value("paths/metrics_output", "", type=str)
        metric_keys = self._settings_list("metrics/selected_metric_keys")
        if metric_keys:
            self._selected_metric_keys = [key for key in metric_keys if key in set(DEFAULT_METRIC_KEYS)]
        self._update_metrics_metric_summary()
        saved_metrics_properties = self._settings_list("metrics/selected_properties")
        if saved_metrics_properties:
            self.metrics_properties_edit.setText(",".join(saved_metrics_properties))
        for index, edit in enumerate(self.model_path_edits):
            value = self.settings.value(f"paths/model_{index + 1}", "", type=str)
            if value:
                edit.setText(value)
        if epc_path and not self.epc_path_edit.text().strip():
            self.epc_path_edit.setText(epc_path)
        for index, edit in enumerate(self.model_offset_edits):
            value = self.settings.value(f"depth_offsets/model_{index + 1}", "0", type=str)
            edit.setText(value or "0")
        if sleeves_path:
            self.sleeves_path_edit.setText(sleeves_path)
            if Path(sleeves_path).exists():
                self._load_sleeves_preview(sleeves_path)
        if extracted_path:
            self.metrics_extracted_path_edit.setText(extracted_path)
            if Path(extracted_path).exists():
                self._load_metrics_channel_options(extracted_path)
        if curve_extracted_path:
            self.curve_extracted_path_edit.setText(curve_extracted_path)
            if Path(curve_extracted_path).exists():
                self._load_curve_table(auto_range=False)
        if intervals_path:
            self.metrics_intervals_path_edit.setText(intervals_path)
        if metrics_output_path:
            self.metrics_output_path_edit.setText(metrics_output_path)

    def _save_last_paths(self) -> None:
        self.settings.setValue("paths/epc", self.epc_path_edit.text().strip())
        for index, edit in enumerate(self.model_path_edits):
            self.settings.setValue(f"paths/model_{index + 1}", edit.text().strip())
        for index, edit in enumerate(self.model_offset_edits):
            self.settings.setValue(f"depth_offsets/model_{index + 1}", edit.text().strip() or "0")
        self.settings.setValue("paths/sleeves", self.sleeves_path_edit.text().strip())
        self.settings.setValue("paths/metrics_extracted", self.metrics_extracted_path_edit.text().strip())
        self.settings.setValue("paths/curve_extracted", self.curve_extracted_path_edit.text().strip())
        self.settings.setValue("paths/metrics_intervals", self.metrics_intervals_path_edit.text().strip())
        self.settings.setValue("paths/metrics_output", self.metrics_output_path_edit.text().strip())
        self.settings.setValue("metrics/selected_metric_keys", self._selected_metric_keys)
        self.settings.setValue("metrics/selected_properties", self._split_csv_text(self.metrics_properties_edit.text()))

    def _update_run_enabled(self, *args) -> None:
        can_run = (
            bool(self._model_results)
            and self._sleeves_loaded
            and bool(self.output_path_edit.text().strip())
            and bool(self._selected_property_uuids())
            and self._extraction_thread is None
        )
        self.run_button.setEnabled(can_run)

    def _run_extraction(self) -> None:
        if not self._model_results:
            QMessageBox.warning(self, "Missing model", "Load a model first.")
            return
        if not self._sleeves_loaded:
            QMessageBox.warning(self, "Missing sleeves", "Load a sleeves table first.")
            return
        selected_uuids = self._selected_property_uuids()
        if not selected_uuids:
            QMessageBox.warning(self, "Missing properties", "Select at least one property.")
            return

        output_path = self.output_path_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "Missing output", "Load a sleeves file first.")
            return
        if Path(output_path).suffix.lower() != ".xlsx":
            output_path = str(Path(output_path).with_suffix(".xlsx"))
            self.output_path_edit.setText(output_path)

        model_specs = self._extraction_model_specs()
        request = ExtractionRequest(
            epc_path=model_specs[0].path,
            sleeves_path=self.sleeves_path_edit.text().strip(),
            output_path=output_path,
            selected_property_uuids=selected_uuids,
            skip_inactive=self.skip_inactive_checkbox.isChecked(),
            model_specs=model_specs,
        )
        self._save_last_paths()
        self._save_selected_properties()

        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.log_panel.append_message("Starting extraction...")

        self._extraction_thread = QThread(self)
        self._extraction_worker = ExtractionWorker(request)
        self._extraction_worker.moveToThread(self._extraction_thread)
        self._extraction_thread.started.connect(self._extraction_worker.run)
        self._extraction_worker.log.connect(self.log_panel.append_message)
        self._extraction_worker.progress.connect(self.progress_bar.setValue)
        self._extraction_worker.finished.connect(self._on_extraction_finished)
        self._extraction_worker.failed.connect(self._on_extraction_failed)
        self._extraction_worker.finished.connect(self._extraction_thread.quit)
        self._extraction_worker.failed.connect(self._extraction_thread.quit)
        self._extraction_thread.finished.connect(self._extraction_worker.deleteLater)
        self._extraction_thread.finished.connect(self._extraction_thread.deleteLater)
        self._extraction_thread.finished.connect(self._reset_extraction_worker_refs)
        self._extraction_thread.start()

    def _cancel_extraction(self) -> None:
        if self._extraction_worker is not None:
            self.log_panel.append_message("Cancel requested...")
            self._extraction_worker.cancel()
            self.cancel_button.setEnabled(False)

    def _on_extraction_finished(self, result: ExtractionResult) -> None:
        self.progress_bar.setValue(100)
        self.cancel_button.setEnabled(False)
        self.log_panel.append_message(
            f"Extraction finished. Rows: {result.stats.extracted_rows}. Output: {result.output_path}"
        )
        self.log_panel.append_message(f"Log: {result.log_path}")
        self.output_path_edit.setText(result.output_path)
        self.metrics_extracted_path_edit.setText(result.output_path)
        self.curve_extracted_path_edit.setText(result.output_path)
        self._set_default_metrics_output(result.output_path)
        self._load_metrics_channel_options(result.output_path)
        self._load_curve_table()
        self._load_result_preview(result)
        csv_warnings = [warning for warning in result.stats.warnings if "Saved CSV instead" in warning]
        if csv_warnings:
            QMessageBox.information(self, "Saved CSV", csv_warnings[-1])
        self._update_run_enabled()
        self._update_metrics_enabled()

    def _on_extraction_failed(self, message: str, details: str) -> None:
        self.cancel_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_panel.append_message(f"Extraction failed: {message}")
        self.log_panel.append_message(details)
        QMessageBox.critical(self, "Extraction failed", message)
        self._update_run_enabled()

    def _reset_extraction_worker_refs(self) -> None:
        self._extraction_thread = None
        self._extraction_worker = None
        self.cancel_button.setEnabled(False)
        self._update_run_enabled()

    def _load_result_preview(self, result: ExtractionResult) -> None:
        stats = result.stats
        self.qc_status_label.setText(
            " | ".join(
                [
                    f"Sleeves: {stats.sleeves_total}",
                    f"Inside: {stats.sleeves_inside_grid}",
                    f"Outside: {stats.sleeves_outside_grid}",
                    f"Rows: {stats.extracted_rows}",
                    f"Skipped inactive: {stats.skipped_inactive_cells}",
                    f"Warnings: {len(stats.warnings)}",
                ]
            )
        )
        try:
            if Path(result.output_path).suffix.lower() == ".csv":
                preview = read_csv_preview(result.output_path, max_rows=1000)
            else:
                preview = read_xlsx_preview(result.output_path, max_rows=1000)
        except Exception as exc:  # noqa: BLE001
            self.log_panel.append_message(f"Preview load failed: {exc}")
            return

        self.qc_preview_table.setColumnCount(len(preview.headers))
        self.qc_preview_table.setHorizontalHeaderLabels(preview.headers)
        self.qc_preview_table.setRowCount(len(preview.rows))
        for row_index, row in enumerate(preview.rows):
            for col_index, value in enumerate(row):
                self.qc_preview_table.setItem(row_index, col_index, QTableWidgetItem(value))
        self.qc_preview_table.resizeColumnsToContents()

    def _load_curve_table(self, *args, auto_range: bool = True) -> None:
        path = self.curve_extracted_path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Missing extracted table", "Select an extracted XLSX/CSV file first.")
            return
        try:
            df = read_table(path)
        except Exception as exc:  # noqa: BLE001
            self.curve_plot.set_message(f"Failed to load curve table: {exc}")
            QMessageBox.critical(self, "Curve table load failed", str(exc))
            return
        if "TVD_top" not in df.columns:
            self.curve_plot.set_message("Extracted table has no TVD_top column.")
            QMessageBox.warning(self, "Missing depth", "Extracted table has no TVD_top column.")
            return
        self._curve_df = df
        self.curve_status_label.setText(f"Loaded curve table: {len(df)} rows")
        self._refresh_curve_controls()
        self._restore_curve_settings()
        if auto_range:
            self._auto_curve_ranges(save_settings=False)
        else:
            self._update_curve_plot(save_settings=False)

    def _refresh_curve_controls(self) -> None:
        if self._curve_df is None:
            return
        df = self._curve_df
        self.curve_well_combo.blockSignals(True)
        self.curve_well_combo.clear()
        self.curve_well_combo.addItems(_unique_text_values(df["Well"]) if "Well" in df.columns else [""])
        self.curve_well_combo.blockSignals(False)
        self._refresh_curve_port_options()

        channel_columns = self._curve_channel_columns()
        for combo in self._curve_combos():
            current = combo.currentText().strip()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(channel_columns)
            if current:
                self._select_combo_text(combo, current)
            combo.blockSignals(False)
        for index, combo in enumerate(self._curve_combos()):
            if combo.count() > index and not combo.currentText().strip():
                combo.setCurrentIndex(index)

    def _refresh_curve_port_options(self) -> None:
        if self._curve_df is None:
            return
        df = self._curve_df
        well = self.curve_well_combo.currentText().strip()
        if well and "Well" in df.columns:
            df = df[df["Well"].map(str) == well]
        ports = _unique_text_values(df["Port"]) if "Port" in df.columns else [""]
        current = self.curve_port_combo.currentText().strip()
        self.curve_port_combo.blockSignals(True)
        self.curve_port_combo.clear()
        self.curve_port_combo.addItems(ports)
        if current:
            self._select_combo_text(self.curve_port_combo, current)
        self.curve_port_combo.blockSignals(False)

    def _on_curve_well_changed(self, *args) -> None:
        self._refresh_curve_port_options()
        self._on_curve_control_changed()

    def _on_curve_control_changed(self, *args) -> None:
        if self._restoring_curve_settings:
            return
        self._save_curve_settings()
        self._update_curve_plot(save_settings=False)

    def _curve_channel_columns(self) -> list[str]:
        if self._curve_df is None:
            return []
        base_columns = {
            "Well",
            "Port",
            "X",
            "Y",
            "TVDSS_PORT",
            "I",
            "J",
            "K",
            "IsActive",
            "TVD_top",
            "TVD_base",
            "TVD_center",
            "Rel_TVD_top",
            "Rel_TVD_base",
            "Rel_TVD_center",
            "CellHeight",
            "CellSizeI",
            "CellSizeJ",
            "CellAreaXY",
        }
        columns: list[str] = []
        for column in self._curve_df.columns:
            column_name = str(column)
            if column_name in base_columns or _is_source_diagnostic_column(column_name):
                continue
            if pd.to_numeric(self._curve_df[column], errors="coerce").notna().any():
                columns.append(column_name)
        return columns

    def _curve_filtered_df(self) -> pd.DataFrame:
        if self._curve_df is None:
            return pd.DataFrame()
        df = self._curve_df
        well = self.curve_well_combo.currentText().strip()
        port = self.curve_port_combo.currentText().strip()
        if well and "Well" in df.columns:
            df = df[df["Well"].map(str) == well]
        if port and "Port" in df.columns:
            df = df[df["Port"].map(str) == port]
        return df

    def _auto_curve_ranges(self, *args, save_settings: bool = True) -> None:
        df = self._curve_filtered_df()
        selected = self._selected_curve_columns()
        if df.empty or not selected:
            return
        self._set_spin_pair(self.curve_depth_min_spin, self.curve_depth_max_spin, _range_with_padding(_numeric_series(df["TVD_top"]), 0.0))
        for column, min_spin, max_spin, _shift_spin in selected:
            self._set_spin_pair(min_spin, max_spin, _range_with_padding(_numeric_series(df[column]), 0.02))
        if save_settings:
            self._save_curve_settings()
        self._update_curve_plot(save_settings=False)

    def _update_curve_plot(self, *args, save_settings: bool = True) -> None:
        if save_settings:
            self._save_curve_settings()
        df = self._curve_filtered_df()
        selected = self._selected_curve_columns()
        if df.empty:
            self.curve_plot.set_message("No rows for selected Well/Port.")
            return
        if not selected:
            self.curve_plot.set_message("Select at least one numeric channel.")
            return
        curves: list[CurveSpec] = []
        base_depth = _numeric_series(df["TVD_top"])
        for column, min_spin, max_spin, shift_spin in selected:
            shift = shift_spin.value() if shift_spin is not None else 0.0
            curves.append(
                CurveSpec(
                    depth=base_depth + shift,
                    values=_numeric_series(df[column]),
                    name=column,
                    value_range=(min_spin.value(), max_spin.value()),
                    depth_shift=shift,
                )
            )
        data = CurvePlotData(
            curves=tuple(curves),
            depth_range=(self.curve_depth_min_spin.value(), self.curve_depth_max_spin.value()),
        )
        self.curve_plot.set_plot_data(data)
        names = ", ".join(curve.name for curve in curves)
        self.curve_status_label.setText(
            f"Rows: {len(df)} | Curves: {names}"
        )

    def _save_curve_settings(self) -> None:
        self.settings.setValue("paths/curve_extracted", self.curve_extracted_path_edit.text().strip())
        self.settings.setValue("curves/well", self.curve_well_combo.currentText().strip())
        self.settings.setValue("curves/port", self.curve_port_combo.currentText().strip())
        self.settings.setValue("curves/depth_min", self.curve_depth_min_spin.value())
        self.settings.setValue("curves/depth_max", self.curve_depth_max_spin.value())
        for index, (combo, min_spin, max_spin, shift_spin) in enumerate(self._curve_control_sets(), start=1):
            self.settings.setValue(f"curves/curve_{index}/channel", combo.currentText().strip())
            self.settings.setValue(f"curves/curve_{index}/min", min_spin.value())
            self.settings.setValue(f"curves/curve_{index}/max", max_spin.value())
            if shift_spin is not None:
                self.settings.setValue(f"curves/curve_{index}/shift", shift_spin.value())

    def _restore_curve_settings(self) -> None:
        self._restoring_curve_settings = True
        try:
            self._select_combo_text(self.curve_well_combo, self.settings.value("curves/well", "", type=str))
            self._refresh_curve_port_options()
            self._select_combo_text(self.curve_port_combo, self.settings.value("curves/port", "", type=str))
            self.curve_depth_min_spin.setValue(_settings_float(self.settings, "curves/depth_min", self.curve_depth_min_spin.value()))
            self.curve_depth_max_spin.setValue(_settings_float(self.settings, "curves/depth_max", self.curve_depth_max_spin.value()))
            for index, (combo, min_spin, max_spin, shift_spin) in enumerate(self._curve_control_sets(), start=1):
                self._select_combo_text(combo, self.settings.value(f"curves/curve_{index}/channel", "", type=str))
                min_spin.setValue(_settings_float(self.settings, f"curves/curve_{index}/min", min_spin.value()))
                max_spin.setValue(_settings_float(self.settings, f"curves/curve_{index}/max", max_spin.value()))
                if shift_spin is not None:
                    shift_spin.setValue(_settings_float(self.settings, f"curves/curve_{index}/shift", shift_spin.value()))
        finally:
            self._restoring_curve_settings = False

    def _curve_combos(self) -> tuple[QComboBox, QComboBox, QComboBox, QComboBox]:
        return self.curve1_combo, self.curve2_combo, self.curve3_combo, self.curve4_combo

    def _curve_control_sets(
        self,
    ) -> tuple[
        tuple[QComboBox, QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox | None],
        tuple[QComboBox, QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox | None],
        tuple[QComboBox, QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox | None],
        tuple[QComboBox, QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox | None],
    ]:
        return (
            (self.curve1_combo, self.curve1_min_spin, self.curve1_max_spin, None),
            (self.curve2_combo, self.curve2_min_spin, self.curve2_max_spin, self.curve2_depth_shift_spin),
            (self.curve3_combo, self.curve3_min_spin, self.curve3_max_spin, self.curve3_depth_shift_spin),
            (self.curve4_combo, self.curve4_min_spin, self.curve4_max_spin, self.curve4_depth_shift_spin),
        )

    def _selected_curve_columns(self) -> list[tuple[str, QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox | None]]:
        if self._curve_df is None:
            return []
        values: list[tuple[str, QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox | None]] = []
        for combo, min_spin, max_spin, shift_spin in self._curve_control_sets():
            column = combo.currentText().strip()
            if column and column in self._curve_df.columns:
                values.append((column, min_spin, max_spin, shift_spin))
        return values

    @staticmethod
    def _set_spin_pair(min_spin: QDoubleSpinBox, max_spin: QDoubleSpinBox, value_range: tuple[float, float]) -> None:
        min_spin.setValue(value_range[0])
        max_spin.setValue(value_range[1])

    def _update_metrics_enabled(self, *args) -> None:
        can_run = (
            bool(self.metrics_extracted_path_edit.text().strip())
            and bool(self.metrics_intervals_path_edit.text().strip())
            and bool(self.metrics_output_path_edit.text().strip())
            and self._metrics_thread is None
        )
        self.metrics_run_button.setEnabled(can_run)

    def _run_metrics(self) -> None:
        extracted_path = self.metrics_extracted_path_edit.text().strip()
        intervals_path = self.metrics_intervals_path_edit.text().strip()
        output_path = self.metrics_output_path_edit.text().strip()
        if not extracted_path:
            QMessageBox.warning(self, "Missing extracted table", "Select an extracted XLSX/CSV file first.")
            return
        if not intervals_path:
            QMessageBox.warning(self, "Missing intervals", "Select an intervals XLSX/CSV file first.")
            return
        if not output_path:
            QMessageBox.warning(self, "Missing output", "Select metrics output path first.")
            return
        output_path = str(Path(output_path).with_suffix(".xlsx"))
        self.metrics_output_path_edit.setText(output_path)

        request = MetricsRequest(
            extracted_path=extracted_path,
            intervals_path=intervals_path,
            output_path=output_path,
            ntg_column=self._combo_text_or_none(self.metrics_ntg_combo),
            poro_column=self._combo_text_or_none(self.metrics_poro_combo),
            perm_column=self._combo_text_or_none(self.metrics_perm_combo),
            lithology_column=self._combo_text_or_none(self.metrics_lithology_combo),
            reservoir_values=self._split_csv_text(self.metrics_reservoir_values_edit.text()),
            property_columns=self._selected_metrics_properties(),
            metric_keys=self._selected_metrics_metric_keys(),
        )
        self._save_last_paths()
        self.metrics_run_button.setEnabled(False)
        self.metrics_progress_bar.setValue(0)
        self.metrics_status_label.setText("Calculating metrics...")
        self.log_panel.append_message("Starting metrics calculation...")

        self._metrics_thread = QThread(self)
        self._metrics_worker = MetricsWorker(request)
        self._metrics_worker.moveToThread(self._metrics_thread)
        self._metrics_thread.started.connect(self._metrics_worker.run)
        self._metrics_worker.log.connect(self.log_panel.append_message)
        self._metrics_worker.progress.connect(self.metrics_progress_bar.setValue)
        self._metrics_worker.finished.connect(self._on_metrics_finished)
        self._metrics_worker.failed.connect(self._on_metrics_failed)
        self._metrics_worker.finished.connect(self._metrics_thread.quit)
        self._metrics_worker.failed.connect(self._metrics_thread.quit)
        self._metrics_thread.finished.connect(self._metrics_worker.deleteLater)
        self._metrics_thread.finished.connect(self._metrics_thread.deleteLater)
        self._metrics_thread.finished.connect(self._reset_metrics_worker_refs)
        self._metrics_thread.start()

    def _on_metrics_finished(self, result: MetricsResult) -> None:
        self.metrics_progress_bar.setValue(100)
        self.metrics_status_label.setText(
            f"Metrics finished. Rows: {result.rows_written}. Warnings: {len(result.warnings)}. Output: {result.output_path}"
        )
        self.log_panel.append_message(
            f"Metrics finished. Rows: {result.rows_written}. Output: {result.output_path}"
        )
        self._load_metrics_preview(result.output_path)
        self._update_metrics_enabled()

    def _on_metrics_failed(self, message: str, details: str) -> None:
        self.metrics_progress_bar.setValue(0)
        self.metrics_status_label.setText(f"Metrics failed: {message}")
        self.log_panel.append_message(f"Metrics failed: {message}")
        self.log_panel.append_message(details)
        QMessageBox.critical(self, "Metrics failed", message)
        self._update_metrics_enabled()

    def _reset_metrics_worker_refs(self) -> None:
        self._metrics_thread = None
        self._metrics_worker = None
        self._update_metrics_enabled()

    def _load_metrics_preview(self, output_path: str) -> None:
        try:
            preview = read_xlsx_preview(output_path, max_rows=1000)
        except Exception as exc:  # noqa: BLE001
            self.log_panel.append_message(f"Metrics preview load failed: {exc}")
            return
        self.metrics_preview_table.setColumnCount(len(preview.headers))
        self.metrics_preview_table.setHorizontalHeaderLabels(preview.headers)
        self.metrics_preview_table.setRowCount(len(preview.rows))
        for row_index, row in enumerate(preview.rows):
            for col_index, value in enumerate(row):
                self.metrics_preview_table.setItem(row_index, col_index, QTableWidgetItem(value))
        self.metrics_preview_table.resizeColumnsToContents()

    def _set_default_metrics_output(self, extracted_path: str) -> None:
        if self.metrics_output_path_edit.text().strip():
            return
        source = Path(extracted_path)
        self.metrics_output_path_edit.setText(str(source.with_name(f"{source.stem}_metrics.xlsx")))

    def _on_metrics_extracted_path_changed(self, path: str) -> None:
        self._update_metrics_enabled()
        if Path(path).exists():
            self._load_metrics_channel_options(path)

    def _load_metrics_channel_options(self, path: str) -> None:
        try:
            self._last_extracted_headers = self._table_headers(path)
        except Exception as exc:  # noqa: BLE001
            self.log_panel.append_message(f"Metrics channel list load failed: {exc}")
            return
        self._refresh_metrics_channel_options()

    def _refresh_metrics_channel_options(self) -> None:
        headers = self._metric_property_headers_from_extracted()
        for combo in (
            self.metrics_ntg_combo,
            self.metrics_poro_combo,
            self.metrics_perm_combo,
            self.metrics_lithology_combo,
        ):
            current = combo.currentText().strip()
            combo.clear()
            combo.addItem("")
            combo.addItems(headers)
            if current:
                self._select_combo_text(combo, current)
        selected = set(self._split_csv_text(self.metrics_properties_edit.text()))
        self.metrics_property_list.blockSignals(True)
        self.metrics_property_list.clear()
        for header in headers:
            item = QListWidgetItem(header)
            self.metrics_property_list.addItem(item)
            item.setSelected(header in selected)
        self.metrics_property_list.blockSignals(False)
        self._select_combo_text(self.metrics_ntg_combo, "NTG")
        self._select_combo_text(self.metrics_poro_combo, "PORO")
        self._select_first_contains(self.metrics_perm_combo, ("perm",))
        self._select_first_contains(self.metrics_lithology_combo, ("lito", "lith", "layer"))
        self._update_metrics_metric_summary()

    def _property_titles_from_model(self) -> list[str]:
        if not self._model_results:
            return []
        return [prop.title for result in self._model_results for prop in result.properties]

    def _metrics_allowed_property_titles(self) -> list[str]:
        selected = self._selected_property_titles()
        if selected:
            return selected
        saved = self._settings_list("properties/selected_titles")
        if saved:
            return saved
        return self._property_titles_from_model()

    def _metric_property_headers_from_extracted(self) -> list[str]:
        base_columns = {
            "Well",
            "Port",
            "X",
            "Y",
            "TVDSS_PORT",
            "I",
            "J",
            "K",
            "IsActive",
            "TVD_top",
            "TVD_base",
            "TVD_center",
            "Rel_TVD_top",
            "Rel_TVD_base",
            "Rel_TVD_center",
            "CellHeight",
            "CellSizeI",
            "CellSizeJ",
            "CellAreaXY",
        }
        return [
            header
            for header in self._last_extracted_headers
            if header not in base_columns and not _is_source_diagnostic_column(header)
        ]

    def _sync_metrics_properties_from_list(self) -> None:
        self.metrics_properties_edit.setText(",".join(self._selected_metrics_properties()))
        self.settings.setValue("metrics/selected_properties", self._selected_metrics_properties())

    def _selected_metrics_properties(self) -> list[str]:
        selected = [item.text() for item in self.metrics_property_list.selectedItems()]
        return selected or self._split_csv_text(self.metrics_properties_edit.text())

    def _open_metrics_properties_dialog(self) -> None:
        headers = self._metric_property_headers_from_extracted()
        if not headers:
            QMessageBox.warning(self, "No channels", "Load an extracted table first.")
            return
        dialog = CheckListDialog(
            title="Select additional channels",
            items=[(header, header) for header in headers],
            selected_values=set(self._selected_metrics_properties()),
            parent=self,
        )
        if dialog.exec() != CheckListDialog.DialogCode.Accepted:
            return
        selected = set(dialog.selected_values())
        self.metrics_property_list.blockSignals(True)
        for index in range(self.metrics_property_list.count()):
            item = self.metrics_property_list.item(index)
            item.setSelected(item.text() in selected)
        self.metrics_property_list.blockSignals(False)
        self.metrics_properties_edit.setText(",".join(value for value in headers if value in selected))
        self.settings.setValue("metrics/selected_properties", self._selected_metrics_properties())

    def _open_metrics_dialog(self) -> None:
        dialog = CheckListDialog(
            title="Select metrics",
            items=METRIC_OPTIONS,
            selected_values=set(self._selected_metrics_metric_keys()),
            parent=self,
        )
        if dialog.exec() != CheckListDialog.DialogCode.Accepted:
            return
        selected = [value for _label, value in METRIC_OPTIONS if value in set(dialog.selected_values())]
        self._selected_metric_keys = selected or list(DEFAULT_METRIC_KEYS)
        self._update_metrics_metric_summary()
        self.settings.setValue("metrics/selected_metric_keys", self._selected_metric_keys)

    def _selected_metrics_metric_keys(self) -> list[str]:
        keys = [key for key in self._selected_metric_keys if key in set(DEFAULT_METRIC_KEYS)]
        return keys or list(DEFAULT_METRIC_KEYS)

    def _update_metrics_metric_summary(self) -> None:
        selected = set(self._selected_metrics_metric_keys())
        labels = [label for label, value in METRIC_OPTIONS if value in selected]
        if len(labels) == len(METRIC_OPTIONS):
            self.metrics_metric_keys_edit.setText("All metrics")
        else:
            self.metrics_metric_keys_edit.setText(", ".join(labels))

    @staticmethod
    def _table_headers(path: str) -> list[str]:
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            return read_csv_preview(path, max_rows=0).headers
        return read_xlsx_headers(path)

    @staticmethod
    def _select_combo_text(combo: QComboBox, text: str) -> None:
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _select_first_contains(combo: QComboBox, needles: tuple[str, ...]) -> None:
        if combo.currentText().strip():
            return
        for index in range(combo.count()):
            value = combo.itemText(index)
            lower = value.lower()
            if any(needle in lower for needle in needles):
                combo.setCurrentIndex(index)
                return

    @staticmethod
    def _empty_to_none(value: str) -> str | None:
        text = value.strip()
        return text or None

    @staticmethod
    def _combo_text_or_none(combo: QComboBox) -> str | None:
        text = combo.currentText().strip()
        return text or None

    @staticmethod
    def _split_csv_text(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        return table

    @staticmethod
    def _combo() -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItem("")
        return combo

    @staticmethod
    def _spinbox() -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setRange(-1_000_000_000.0, 1_000_000_000.0)
        spinbox.setDecimals(4)
        spinbox.setKeyboardTracking(False)
        return spinbox


def _unique_text_values(series: pd.Series) -> list[str]:
    values = [str(value) for value in series.dropna().tolist()]
    return list(dict.fromkeys(values))


def _numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _is_source_diagnostic_column(column_name: str) -> bool:
    return column_name.endswith(("_Model", "_I", "_J", "_K", "_TVD_center"))


def _range_with_padding(series: pd.Series, padding_fraction: float) -> tuple[float, float]:
    values = series.dropna()
    if values.empty:
        return 0.0, 1.0
    low = float(values.min())
    high = float(values.max())
    if low == high:
        padding = max(1.0, abs(low) * 0.05)
        return low - padding, high + padding
    padding = (high - low) * padding_fraction
    return low - padding, high + padding


def _settings_float(settings: QSettings, key: str, default: float) -> float:
    value = settings.value(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _main_for_manual_debug() -> None:
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    _main_for_manual_debug()
