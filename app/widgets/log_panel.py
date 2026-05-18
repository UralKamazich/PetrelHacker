from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit


class LogPanel(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)

    def append_message(self, message: str) -> None:
        self.appendPlainText(message)
