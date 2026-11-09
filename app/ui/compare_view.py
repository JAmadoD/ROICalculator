"""Side by side comparison of all projects."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.project import Project
from app.services.calculator import calculate, describe_payback
from app.utils.numbers import format_money, format_percent

PROJECT_ID_ROLE = Qt.ItemDataRole.UserRole
COLUMNS = [
    "Project", "Horizon", "Total cost", "Total benefit", "Net gain",
    "ROI", "Annualized ROI", "Payback", "NPV",
]


class SortableItem(QTableWidgetItem):
    """Table cell that sorts by a number, with N/A values sorted last."""

    def __init__(self, text: str, key: float | None) -> None:
        super().__init__(text)
        self.sort_key = key
        self.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if not isinstance(other, SortableItem):
            return super().__lt__(other)
        if self.sort_key is None:
            return False
        if other.sort_key is None:
            return True
        return self.sort_key < other.sort_key


class CompareView(QWidget):
    open_project = Signal(str)
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Every project side by side. Click a column title to sort. "
            "Double-click a row to open that project."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.export_button = QPushButton("Export comparison to CSV...")
        self.export_button.clicked.connect(self.export_requested)
        buttons.addWidget(self.export_button)
        buttons.addStretch()
        layout.addLayout(buttons)

    def set_projects(self, projects: list[Project], currency: str) -> None:
        table = self.table
        sort_column = table.horizontalHeader().sortIndicatorSection()
        sort_order = table.horizontalHeader().sortIndicatorOrder()
        table.setSortingEnabled(False)
        table.setRowCount(len(projects))
        for row, project in enumerate(projects):
            results = calculate(project)
            name = QTableWidgetItem(project.name)
            name.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            name.setData(PROJECT_ID_ROLE, project.id)
            table.setItem(row, 0, name)
            payback_key = None
            if results.payback_month is not None:
                payback_key = float(results.payback_month)
            cells = [
                (f"{project.horizon_months} mo", float(project.horizon_months)),
                (format_money(results.total_cost, currency), results.total_cost),
                (format_money(results.total_benefit, currency), results.total_benefit),
                (format_money(results.net_gain, currency), results.net_gain),
                (format_percent(results.roi_percent), results.roi_percent),
                (format_percent(results.annualized_roi_percent), results.annualized_roi_percent),
                (describe_payback(results), payback_key),
                (format_money(results.npv, currency), results.npv),
            ]
            for column, (text, key) in enumerate(cells, start=1):
                table.setItem(row, column, SortableItem(text, key))
        table.setSortingEnabled(True)
        if sort_column >= 0:
            table.sortItems(sort_column, sort_order)

    def _on_double_click(self, row: int, _column: int) -> None:
        cell = self.table.item(row, 0)
        if cell is not None:
            self.open_project.emit(cell.data(PROJECT_ID_ROLE))
