from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout


class CheckListDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        items: list[tuple[str, str]],
        selected_values: set[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 640)
        self._list = QListWidget()
        for label, value in items:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if value in selected_values else Qt.CheckState.Unchecked)
            self._list.addItem(item)

        select_all = QPushButton("Select all")
        clear = QPushButton("Clear")
        buttons_row = QHBoxLayout()
        buttons_row.addWidget(select_all)
        buttons_row.addWidget(clear)
        buttons_row.addStretch(1)

        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout = QVBoxLayout(self)
        layout.addLayout(buttons_row)
        layout.addWidget(self._list, 1)
        layout.addWidget(dialog_buttons)

        select_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        clear.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)

    def selected_values(self) -> list[str]:
        values: list[str] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                values.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return values

    def _set_all(self, state: Qt.CheckState) -> None:
        for index in range(self._list.count()):
            self._list.item(index).setCheckState(state)
