from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QThread
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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

from app.widgets.log_panel import LogPanel
from app.workers.extraction_worker import ExtractionRequest, ExtractionResult, ExtractionWorker
from app.workers.load_model_worker import LoadModelWorker, ModelLoadResult
from app.workers.metrics_worker import MetricsRequest, MetricsResult, MetricsWorker
from core.csv_preview import read_csv_preview
from core.exporter import default_extraction_output_path
from core.property_presets import normalize_property_title, should_select_property
from core.sleeves_loader import load_sleeves_table, validate_sleeves_table
from core.xlsx_preview import read_xlsx_headers, read_xlsx_preview


class MainWindow(QMainWindow):
    SETTINGS_ORG = "PetrelHacker"
    SETTINGS_APP = "SleeveExtractor"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PetrelHacker - RESQML Sleeve Property Extractor")
        self.settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self._load_thread: QThread | None = None
        self._load_worker: LoadModelWorker | None = None
        self._extraction_thread: QThread | None = None
        self._extraction_worker: ExtractionWorker | None = None
        self._metrics_thread: QThread | None = None
        self._metrics_worker: MetricsWorker | None = None
        self._model_result: ModelLoadResult | None = None
        self._sleeves_loaded = False
        self._last_extracted_headers: list[str] = []

        self.epc_path_edit = QLineEdit()
        self.epc_path_edit.setPlaceholderText("Select .epc file")
        self.h5_path_label = QLabel("-")
        self.backend_label = QLabel("-")
        self.load_button = QPushButton("Load model")
        self.browse_epc_button = QPushButton("Browse")
        self.grids_table = self._table(["Title", "UUID", "NI", "NJ", "NK", "Type"])
        self.properties_table = self._table(["Use", "Title", "UUID", "Indexable", "UOM", "Kind", "Type"])
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
        self.metrics_property_combo = self._combo()
        self.metrics_add_property_button = QPushButton("Add")
        self.metrics_properties_edit = QLineEdit()
        self.metrics_properties_edit.setPlaceholderText("Example: NTG,PORO,Perm_1A")
        self.metrics_run_button = QPushButton("Calculate metrics")
        self.metrics_run_button.setEnabled(False)
        self.metrics_progress_bar = QProgressBar()
        self.metrics_status_label = QLabel("No metrics calculated yet.")
        self.metrics_preview_table = self._table(["Well", "Port"])

        tabs = QTabWidget()
        tabs.addTab(self._model_tab(), "Model")
        tabs.addTab(self._sleeves_tab(), "Sleeves")
        tabs.addTab(self._properties_tab(), "Properties")
        tabs.addTab(self._run_tab(), "Run")
        tabs.addTab(self._preview_tab(), "Preview / QC")
        tabs.addTab(self._metrics_tab(), "Metrics")
        self.setCentralWidget(tabs)

        self.browse_epc_button.clicked.connect(self._browse_epc)
        self.load_button.clicked.connect(self._load_model)
        self.output_path_edit.textChanged.connect(self._update_run_enabled)
        self.run_button.clicked.connect(self._run_extraction)
        self.cancel_button.clicked.connect(self._cancel_extraction)
        self.metrics_extracted_path_edit.textChanged.connect(self._on_metrics_extracted_path_changed)
        self.metrics_intervals_path_edit.textChanged.connect(self._update_metrics_enabled)
        self.metrics_output_path_edit.textChanged.connect(self._update_metrics_enabled)
        self.metrics_run_button.clicked.connect(self._run_metrics)
        self._restore_last_paths()

    def _model_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        file_row = QHBoxLayout()
        file_row.addWidget(self.epc_path_edit, 1)
        file_row.addWidget(self.browse_epc_button)
        file_row.addWidget(self.load_button)
        layout.addLayout(file_row)

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
        property_row.addWidget(self.metrics_property_combo, 1)
        property_row.addWidget(self.metrics_add_property_button)
        form.addRow("Add property", property_row)
        form.addRow("Properties", self.metrics_properties_edit)
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
        self.metrics_add_property_button.clicked.connect(self._add_metrics_property)
        return tab

    def _browse_epc(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select RESQML EPC", "", "RESQML EPC (*.epc);;All files (*)")
        if path:
            self.epc_path_edit.setText(path)
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
        epc_path = self.epc_path_edit.text().strip()
        if not epc_path:
            QMessageBox.warning(self, "Missing EPC", "Select an EPC file first.")
            return

        self._save_last_paths()
        self.load_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.log_panel.append_message("Starting model load...")

        self._load_thread = QThread(self)
        self._load_worker = LoadModelWorker(epc_path)
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

    def _on_model_loaded(self, result: ModelLoadResult) -> None:
        self._model_result = result
        self.backend_label.setText(result.backend)
        self.h5_path_label.setText(result.h5_path or "-")
        self._fill_grids(result)
        self._fill_properties(result)
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

    def _fill_grids(self, result: ModelLoadResult) -> None:
        self.grids_table.setRowCount(len(result.grids))
        for row, grid in enumerate(result.grids):
            values = [
                grid.title,
                grid.uuid,
                "" if grid.ni is None else str(grid.ni),
                "" if grid.nj is None else str(grid.nj),
                "" if grid.nk is None else str(grid.nk),
                grid.grid_type or "",
            ]
            for col, value in enumerate(values):
                self.grids_table.setItem(row, col, QTableWidgetItem(value))
        self.grids_table.resizeColumnsToContents()

    def _fill_properties(self, result: ModelLoadResult) -> None:
        saved_uuids = self._saved_property_uuids()
        saved_titles = self._saved_property_titles()
        use_defaults = not saved_uuids and not saved_titles
        self.properties_table.setRowCount(len(result.properties))
        for row, prop in enumerate(result.properties):
            check = QCheckBox()
            check.setChecked(should_select_property(prop, saved_uuids, saved_titles, use_defaults))
            check.stateChanged.connect(self._update_run_enabled)
            check.stateChanged.connect(self._save_selected_properties)
            self.properties_table.setCellWidget(row, 0, check)
            values = [
                prop.title,
                prop.uuid,
                prop.indexable_element or "",
                prop.uom or "",
                prop.property_kind or "",
                prop.property_type or "",
            ]
            for offset, value in enumerate(values, start=1):
                self.properties_table.setItem(row, offset, QTableWidgetItem(value))
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
            uuid_item = self.properties_table.item(row, 2)
            if isinstance(widget, QCheckBox) and widget.isChecked() and uuid_item is not None:
                uuids.append(uuid_item.text())
        return uuids

    def _selected_property_titles(self) -> list[str]:
        titles: list[str] = []
        for row in range(self.properties_table.rowCount()):
            widget = self.properties_table.cellWidget(row, 0)
            title_item = self.properties_table.item(row, 1)
            if isinstance(widget, QCheckBox) and widget.isChecked() and title_item is not None:
                titles.append(title_item.text())
        return titles

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
        intervals_path = self.settings.value("paths/metrics_intervals", "", type=str)
        metrics_output_path = self.settings.value("paths/metrics_output", "", type=str)
        if epc_path:
            self.epc_path_edit.setText(epc_path)
        if sleeves_path:
            self.sleeves_path_edit.setText(sleeves_path)
            if Path(sleeves_path).exists():
                self._load_sleeves_preview(sleeves_path)
        if extracted_path:
            self.metrics_extracted_path_edit.setText(extracted_path)
            if Path(extracted_path).exists():
                self._load_metrics_channel_options(extracted_path)
        if intervals_path:
            self.metrics_intervals_path_edit.setText(intervals_path)
        if metrics_output_path:
            self.metrics_output_path_edit.setText(metrics_output_path)

    def _save_last_paths(self) -> None:
        self.settings.setValue("paths/epc", self.epc_path_edit.text().strip())
        self.settings.setValue("paths/sleeves", self.sleeves_path_edit.text().strip())
        self.settings.setValue("paths/metrics_extracted", self.metrics_extracted_path_edit.text().strip())
        self.settings.setValue("paths/metrics_intervals", self.metrics_intervals_path_edit.text().strip())
        self.settings.setValue("paths/metrics_output", self.metrics_output_path_edit.text().strip())

    def _update_run_enabled(self, *args) -> None:
        can_run = (
            self._model_result is not None
            and self._sleeves_loaded
            and bool(self.output_path_edit.text().strip())
            and bool(self._selected_property_uuids())
            and self._extraction_thread is None
        )
        self.run_button.setEnabled(can_run)

    def _run_extraction(self) -> None:
        if self._model_result is None:
            QMessageBox.warning(self, "Missing model", "Load a RESQML model first.")
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

        request = ExtractionRequest(
            epc_path=self.epc_path_edit.text().strip(),
            sleeves_path=self.sleeves_path_edit.text().strip(),
            output_path=output_path,
            selected_property_uuids=selected_uuids,
            skip_inactive=self.skip_inactive_checkbox.isChecked(),
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
        self._set_default_metrics_output(result.output_path)
        self._load_metrics_channel_options(result.output_path)
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
            property_columns=self._split_csv_text(self.metrics_properties_edit.text()),
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
        selected_properties = self._metrics_allowed_property_titles()
        if selected_properties:
            headers = [header for header in self._last_extracted_headers if header in selected_properties]
        else:
            headers = []
        for combo in (
            self.metrics_ntg_combo,
            self.metrics_poro_combo,
            self.metrics_perm_combo,
            self.metrics_lithology_combo,
            self.metrics_property_combo,
        ):
            current = combo.currentText().strip()
            combo.clear()
            combo.addItem("")
            combo.addItems(headers)
            if current:
                self._select_combo_text(combo, current)
        self._select_combo_text(self.metrics_ntg_combo, "NTG")
        self._select_combo_text(self.metrics_poro_combo, "PORO")
        self._select_first_contains(self.metrics_perm_combo, ("perm",))
        self._select_first_contains(self.metrics_lithology_combo, ("lito", "lith", "layer"))

    def _property_titles_from_model(self) -> list[str]:
        if self._model_result is None:
            return []
        return [prop.title for prop in self._model_result.properties]

    def _metrics_allowed_property_titles(self) -> list[str]:
        selected = self._selected_property_titles()
        if selected:
            return selected
        saved = self._settings_list("properties/selected_titles")
        if saved:
            return saved
        return self._property_titles_from_model()

    def _add_metrics_property(self) -> None:
        value = self.metrics_property_combo.currentText().strip()
        if not value:
            return
        values = self._split_csv_text(self.metrics_properties_edit.text())
        if value not in values:
            values.append(value)
            self.metrics_properties_edit.setText(",".join(values))

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


def _main_for_manual_debug() -> None:
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    _main_for_manual_debug()
