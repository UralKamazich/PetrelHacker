from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)


FIELD_LABELS = {
    "Well": "Well",
    "Port": "Port",
    "X": "X",
    "Y": "Y",
    "TVDSS_PORT": "TVDSS_PORT",
}
REQUIRED_FIELDS = ("Well", "Port", "X", "Y")
OPTIONAL_FIELDS = ("TVDSS_PORT",)


class ColumnMappingDialog(QDialog):
    def __init__(
        self,
        *,
        columns: list[str],
        initial_mapping: dict[str, str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Соответствие колонок")
        self.resize(520, 260)
        self._combos: dict[str, QComboBox] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Укажите соответствие колонок фрак-листа обязательным полям."))

        form = QFormLayout()
        for field in (*REQUIRED_FIELDS, *OPTIONAL_FIELDS):
            combo = QComboBox()
            combo.addItem("", "")
            for column in columns:
                combo.addItem(column, column)
            initial = initial_mapping.get(field, "")
            if initial:
                index = combo.findData(initial)
                if index >= 0:
                    combo.setCurrentIndex(index)
            self._combos[field] = combo
            label = FIELD_LABELS[field] + ("" if field in REQUIRED_FIELDS else " (optional)")
            form.addRow(label, combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def mapping(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for field, combo in self._combos.items():
            value = str(combo.currentData() or "")
            if value:
                result[field] = value
        return result

    def _accept_if_valid(self) -> None:
        mapping = self.mapping()
        missing = [field for field in REQUIRED_FIELDS if not mapping.get(field)]
        if missing:
            QMessageBox.warning(self, "Не выбраны колонки", "Выберите колонки для: " + ", ".join(missing))
            return
        selected = list(mapping.values())
        if len(selected) != len(set(selected)):
            QMessageBox.warning(self, "Дубли колонок", "Для каждого поля нужна отдельная исходная колонка.")
            return
        self.accept()
