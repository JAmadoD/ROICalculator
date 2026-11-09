"""Small line chart of cumulative net by month.

Uses QtCharts when it is available. Colors come from the widget palette so
the chart is readable in both light and dark mode.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QMargins, Qt
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.services.calculator import ProjectResults

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis

    HAVE_CHARTS = True
except ImportError:  # pragma: no cover - depends on the PySide6 build
    HAVE_CHARTS = False


class CumulativeChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._results: ProjectResults | None = None
        self.setMinimumHeight(200)
        if not HAVE_CHARTS:
            layout.addWidget(QLabel("Chart not available in this Qt build."))
            self._view = None
            return

        self._chart = QChart()
        self._chart.legend().hide()
        self._chart.setBackgroundVisible(False)
        self._chart.setMargins(QMargins(4, 4, 4, 4))
        self._chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)

        self._series = QLineSeries()
        self._series.setName("Cumulative net")
        self._zero = QLineSeries()
        self._zero.setName("Break even")
        self._chart.addSeries(self._series)
        self._chart.addSeries(self._zero)

        self._axis_x = QValueAxis()
        self._axis_x.setTitleText("Month")
        self._axis_x.setLabelFormat("%d")
        self._axis_x.setTickType(QValueAxis.TickType.TicksDynamic)
        self._axis_x.setTickAnchor(0)
        self._axis_x.setTickInterval(1)
        self._axis_y = QValueAxis()
        self._axis_y.setTitleText("Cumulative net")
        self._axis_y.setLabelFormat("%.0f")
        self._chart.addAxis(self._axis_x, Qt.AlignmentFlag.AlignBottom)
        self._chart.addAxis(self._axis_y, Qt.AlignmentFlag.AlignLeft)
        for series in (self._series, self._zero):
            series.attachAxis(self._axis_x)
            series.attachAxis(self._axis_y)

        self._view = QChartView(self._chart)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setStyleSheet("background: transparent")
        layout.addWidget(self._view)
        self._apply_palette()

    def set_results(self, results: ProjectResults | None) -> None:
        self._results = results
        if self._view is None:
            return
        self._series.clear()
        self._zero.clear()
        if results is None or not results.rows:
            self._axis_x.setRange(0, 1)
            self._axis_y.setRange(-1, 1)
            return
        values = [row.cumulative_net for row in results.rows]
        for row in results.rows:
            self._series.append(row.month, row.cumulative_net)
        last = results.rows[-1].month
        self._zero.append(0, 0)
        self._zero.append(last, 0)
        low = min(min(values), 0.0)
        high = max(max(values), 0.0)
        pad = (high - low) * 0.08 or 1.0
        self._axis_x.setRange(0, max(last, 1))
        step = next((s for s in (1, 2, 3, 6, 12, 24, 60, 120) if last / s <= 12), 120)
        self._axis_x.setTickInterval(step)
        self._axis_y.setRange(low - pad, high + pad)
        self._axis_y.applyNiceNumbers()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt API name)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self._apply_palette()
        super().changeEvent(event)

    def _apply_palette(self) -> None:
        if self._view is None:
            return
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.WindowText)
        grid = palette.color(QPalette.ColorRole.Mid)
        accent = palette.color(QPalette.ColorRole.Highlight)
        for axis in (self._axis_x, self._axis_y):
            axis.setLabelsColor(text)
            axis.setTitleBrush(text)
            axis.setGridLineColor(grid)
            axis.setLinePenColor(grid)
        line = QPen(accent)
        line.setWidth(2)
        self._series.setPen(line)
        zero = QPen(text)
        zero.setStyle(Qt.PenStyle.DashLine)
        zero.setWidth(1)
        self._zero.setPen(zero)
