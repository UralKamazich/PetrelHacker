from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class CurveSpec:
    depth: pd.Series
    values: pd.Series
    name: str
    value_range: tuple[float, float]
    depth_shift: float = 0.0


@dataclass(frozen=True)
class CurvePlotData:
    curves: tuple[CurveSpec, ...]
    depth_range: tuple[float, float]


class CurvePlotWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(720, 520)
        self._data: CurvePlotData | None = None
        self._message = "Load extracted table and select two channels."

    def set_message(self, message: str) -> None:
        self._data = None
        self._message = message
        self.update()

    def set_plot_data(self, data: CurvePlotData) -> None:
        self._data = data
        self._message = ""
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f7f8fa"))
        if self._data is None:
            painter.setPen(QColor("#666666"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            return

        plot_rect = QRectF(96, 118, max(100, self.width() - 164), max(100, self.height() - 246))
        painter.fillRect(plot_rect, QColor("#ffffff"))
        self._draw_frame(painter, plot_rect)
        self._draw_grid(painter, plot_rect, self._data.depth_range)
        for index, curve in enumerate(self._data.curves):
            self._draw_curve(
                painter,
                plot_rect,
                curve.depth,
                curve.values,
                self._data.depth_range,
                curve.value_range,
                _curve_color(index),
            )
        self._draw_axes(painter, plot_rect, self._data)

    def _draw_frame(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor("#1f2933"), 1))
        painter.drawRect(rect)

    def _draw_grid(self, painter: QPainter, rect: QRectF, depth_range: tuple[float, float]) -> None:
        painter.setPen(QPen(QColor("#e5e7eb"), 1))
        for index in range(1, 5):
            x = rect.left() + rect.width() * index / 5
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for tick in _ticks(depth_range, 6):
            y = _map_value(tick, depth_range, rect.top(), rect.bottom())
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    def _draw_axes(self, painter: QPainter, rect: QRectF, data: CurvePlotData) -> None:
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor("#334155"))
        painter.drawText(QRectF(4, rect.top(), 84, rect.height()), Qt.AlignmentFlag.AlignVCenter, "TVD top")
        for tick in _ticks(data.depth_range, 6):
            y = _map_value(tick, data.depth_range, rect.top(), rect.bottom())
            painter.drawText(QRectF(8, y - 8, 80, 16), Qt.AlignmentFlag.AlignRight, _fmt(tick))

        for index, curve in enumerate(data.curves):
            title = curve.name
            if curve.depth_shift:
                title = f"{title} | shift {_fmt(curve.depth_shift)} m"
            self._draw_x_axis(
                painter,
                rect,
                curve.value_range,
                title,
                _curve_color(index),
                top=index in {1, 3},
                lane=0 if index < 2 else 1,
            )

    def _draw_x_axis(
        self,
        painter: QPainter,
        rect: QRectF,
        value_range: tuple[float, float],
        title: str,
        color: QColor,
        *,
        top: bool,
        lane: int,
    ) -> None:
        offset = lane * 54
        y = rect.top() - 22 - offset if top else rect.bottom() + 12 + offset
        tick_label_y = y - 24 if top else y + 6
        title_y = y - 46 if top else y + 28
        painter.setPen(QPen(color, 1))
        for tick in _ticks(value_range, 5):
            x = _map_value(tick, value_range, rect.left(), rect.right())
            painter.drawLine(QPointF(x, y), QPointF(x, y + (6 if top else -6)))
            painter.drawText(QRectF(x - 35, tick_label_y, 70, 18), Qt.AlignmentFlag.AlignCenter, _fmt(tick))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(rect.left(), title_y, rect.width(), 20), Qt.AlignmentFlag.AlignCenter, title)
        font.setBold(False)
        painter.setFont(font)

    def _draw_curve(
        self,
        painter: QPainter,
        rect: QRectF,
        depth: pd.Series,
        values: pd.Series,
        depth_range: tuple[float, float],
        value_range: tuple[float, float],
        color: QColor,
    ) -> None:
        rows = pd.DataFrame({"depth": depth, "value": values}).sort_values("depth")
        low_depth, high_depth = min(depth_range), max(depth_range)
        low_value, high_value = min(value_range), max(value_range)
        painter.setPen(QPen(color, 2.0))
        segment: list[QPointF] = []
        for row in rows.itertuples(index=False):
            if pd.isna(row.depth) or pd.isna(row.value):
                self._draw_segment(painter, segment)
                segment = []
                continue

            depth_value = float(row.depth)
            curve_value = float(row.value)
            in_range = (
                low_depth <= depth_value <= high_depth
                and low_value <= curve_value <= high_value
            )
            if not in_range:
                self._draw_segment(painter, segment)
                segment = []
                continue

            x = _map_value(curve_value, value_range, rect.left(), rect.right())
            y = _map_value(depth_value, depth_range, rect.top(), rect.bottom())
            segment.append(QPointF(x, y))
        self._draw_segment(painter, segment)

    def _draw_segment(self, painter: QPainter, points: list[QPointF]) -> None:
        if len(points) == 1:
            painter.drawEllipse(points[0], 2.2, 2.2)
            return
        if len(points) < 2:
            return
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        painter.drawPath(path)


def _map_value(value: float, source_range: tuple[float, float], target_min: float, target_max: float) -> float:
    low, high = source_range
    if high == low:
        return (target_min + target_max) / 2.0
    return target_min + (float(value) - low) / (high - low) * (target_max - target_min)


def _ticks(value_range: tuple[float, float], count: int) -> list[float]:
    low, high = value_range
    if count <= 1 or high == low:
        return [low]
    return [low + (high - low) * index / (count - 1) for index in range(count)]


def _fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.3g}"


def _curve_color(index: int) -> QColor:
    colors = ("#1f77b4", "#d95f02", "#2ca02c", "#7b3f98")
    return QColor(colors[index % len(colors)])
