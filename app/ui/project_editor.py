"""Editor for one project: details, line items, and live results."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.project import (
    KIND_LABELS,
    KINDS,
    MAX_AMOUNT,
    MAX_DISCOUNT_RATE,
    MAX_HORIZON,
    MAX_MONTH,
    MIN_HORIZON,
    TIMING_LABELS,
    TIMING_MONTHLY,
    TIMINGS,
    LineItem,
    Project,
)
from app.services.calculator import ProjectResults, calculate, describe_payback
from app.ui.cumulative_chart import CumulativeChart
from app.utils.numbers import NumberParseError, format_money, format_percent, parse_number

ITEM_ID_ROLE = Qt.ItemDataRole.UserRole
END_OF_HORIZON = -1


def _readonly_item(text: str, align_right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


class ProjectEditor(QWidget):
    """Edits a Project object in place and emits ``changed`` after each edit."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project: Project | None = None
        self._currency = "$"
        self._loading = False
        self._editing_item_id: str | None = None
        self.results: ProjectResults | None = None
        self._build()
        self.set_project(None)

    # ----- construction -------------------------------------------------

    def _build(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        right = QVBoxLayout()
        root.addLayout(left, 3)
        root.addLayout(right, 2)

        # Project details
        details = QGroupBox("Project")
        form = QFormLayout(details)
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(200)
        self.horizon_spin = QSpinBox()
        self.horizon_spin.setRange(MIN_HORIZON, MAX_HORIZON)
        self.horizon_spin.setSuffix(" months")
        self.horizon_spin.setToolTip("How many months to look ahead. Month 0 is the start.")
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.0, MAX_DISCOUNT_RATE)
        self.rate_spin.setDecimals(2)
        self.rate_spin.setSingleStep(0.5)
        self.rate_spin.setSuffix(" % per year")
        self.rate_spin.setToolTip(
            "Optional. Used for NPV: money later is worth less than money now. "
            "Leave at 0 to skip discounting."
        )
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Notes, assumptions, sources")
        self.notes_edit.setFixedHeight(64)
        form.addRow("Name", self.name_edit)
        form.addRow("Time horizon", self.horizon_spin)
        form.addRow("Discount rate", self.rate_spin)
        form.addRow("Notes", self.notes_edit)
        left.addWidget(details)

        # Line items
        items_box = QGroupBox("Costs and benefits")
        items_layout = QVBoxLayout(items_box)
        self.items_table = QTableWidget(0, 6)
        self.items_table.setHorizontalHeaderLabels(
            ["Name", "Type", "Amount", "Timing", "Start month", "End month"]
        )
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.items_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.items_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.items_table.verticalHeader().setVisible(False)
        header = self.items_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.items_table.setMinimumHeight(160)
        self.items_table.itemSelectionChanged.connect(self._on_item_selected)
        items_layout.addWidget(self.items_table)

        grid = QGridLayout()
        self.item_name = QLineEdit()
        self.item_name.setPlaceholderText("For example: Venue rental")
        self.item_kind = QComboBox()
        for kind in KINDS:
            self.item_kind.addItem(KIND_LABELS[kind], kind)
        self.item_amount = QLineEdit()
        self.item_amount.setPlaceholderText("0.00")
        self.item_timing = QComboBox()
        for timing in TIMINGS:
            self.item_timing.addItem(TIMING_LABELS[timing], timing)
        self.item_start = QSpinBox()
        self.item_start.setRange(0, MAX_MONTH)
        self.item_end = QSpinBox()
        self.item_end.setRange(END_OF_HORIZON, MAX_MONTH)
        self.item_end.setSpecialValueText("End of horizon")
        self.start_label = QLabel("Month")
        self.end_label = QLabel("End month")
        grid.addWidget(QLabel("Item"), 0, 0)
        grid.addWidget(self.item_name, 0, 1, 1, 3)
        grid.addWidget(QLabel("Type"), 1, 0)
        grid.addWidget(self.item_kind, 1, 1)
        grid.addWidget(QLabel("Amount"), 1, 2)
        grid.addWidget(self.item_amount, 1, 3)
        grid.addWidget(QLabel("Timing"), 2, 0)
        grid.addWidget(self.item_timing, 2, 1)
        grid.addWidget(self.start_label, 2, 2)
        grid.addWidget(self.item_start, 2, 3)
        grid.addWidget(self.end_label, 3, 2)
        grid.addWidget(self.item_end, 3, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        items_layout.addLayout(grid)
        self.item_timing.currentIndexChanged.connect(self._update_timing_fields)

        buttons = QHBoxLayout()
        self.add_item_button = QPushButton("Add item")
        self.save_item_button = QPushButton("Save changes")
        self.remove_item_button = QPushButton("Remove item")
        self.clear_item_button = QPushButton("Clear form")
        for button in (self.add_item_button, self.save_item_button,
                       self.remove_item_button, self.clear_item_button):
            buttons.addWidget(button)
        buttons.addStretch()
        items_layout.addLayout(buttons)
        self.add_item_button.clicked.connect(self._add_item)
        self.save_item_button.clicked.connect(self._save_item)
        self.remove_item_button.clicked.connect(self._remove_item)
        self.clear_item_button.clicked.connect(self._clear_item_form)
        self.item_amount.returnPressed.connect(self._submit_on_enter)
        self.item_name.returnPressed.connect(self._submit_on_enter)

        self.item_message = QLabel("")
        self.item_message.setWordWrap(True)
        items_layout.addWidget(self.item_message)
        left.addWidget(items_box, 1)

        # Results
        results_box = QGroupBox("Results")
        results_form = QFormLayout(results_box)
        bold = QFont()
        bold.setBold(True)
        self.result_labels: dict[str, QLabel] = {}
        for key, title in (
            ("total_cost", "Total cost"),
            ("total_benefit", "Total benefit"),
            ("net_gain", "Net gain"),
            ("roi", "ROI"),
            ("annualized", "Annualized ROI"),
            ("payback", "Payback"),
            ("npv", "NPV"),
        ):
            label = QLabel("")
            label.setFont(bold)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.result_labels[key] = label
            results_form.addRow(title, label)
        self.npv_title = results_form.labelForField(self.result_labels["npv"])
        self.warnings_label = QLabel("")
        self.warnings_label.setWordWrap(True)
        results_form.addRow(self.warnings_label)
        right.addWidget(results_box)

        self.chart = CumulativeChart()
        right.addWidget(self.chart, 1)

        self.month_table = QTableWidget(0, 5)
        self.month_table.setHorizontalHeaderLabels(
            ["Month", "Cost", "Benefit", "Net", "Cumulative net"]
        )
        self.month_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.month_table.verticalHeader().setVisible(False)
        self.month_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.month_table.horizontalHeader().setMinimumSectionSize(60)
        self.month_table.setMinimumHeight(180)
        right.addWidget(self.month_table, 1)

        self.name_edit.textEdited.connect(self._on_name_edited)
        self.horizon_spin.valueChanged.connect(self._on_horizon_changed)
        self.rate_spin.valueChanged.connect(self._on_rate_changed)
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        self._update_timing_fields()

    # ----- public API ---------------------------------------------------

    @property
    def project(self) -> Project | None:
        return self._project

    def set_currency(self, symbol: str) -> None:
        self._currency = symbol
        if self._project is not None:
            self._refresh_items_table()
            self.refresh_results()

    def set_project(self, project: Project | None) -> None:
        self._project = project
        self._loading = True
        try:
            enabled = project is not None
            for widget in self.findChildren(QWidget):
                widget.setEnabled(enabled)
            self.name_edit.setText(project.name if project else "")
            self.horizon_spin.setValue(project.horizon_months if project else 12)
            self.rate_spin.setValue(project.discount_rate if project else 0.0)
            self.notes_edit.setPlainText(project.notes if project else "")
        finally:
            self._loading = False
        self._clear_item_form()
        self._refresh_items_table()
        self.refresh_results()

    def reload(self) -> None:
        """Re-read the current project, for example after a CSV import."""
        self.set_project(self._project)

    def refresh_results(self) -> None:
        if self._project is None:
            self.results = None
            for label in self.result_labels.values():
                label.setText("")
            self.warnings_label.setText("")
            self.month_table.setRowCount(0)
            self.chart.set_results(None)
            return
        results = calculate(self._project)
        self.results = results
        money = self._money
        self.result_labels["total_cost"].setText(money(results.total_cost))
        self.result_labels["total_benefit"].setText(money(results.total_benefit))
        self.result_labels["net_gain"].setText(money(results.net_gain))
        self.result_labels["roi"].setText(format_percent(results.roi_percent))
        self.result_labels["annualized"].setText(format_percent(results.annualized_roi_percent))
        self.result_labels["payback"].setText(describe_payback(results))
        self.result_labels["npv"].setText(money(results.npv))
        if self.npv_title is not None:
            if results.discount_rate:
                self.npv_title.setText(f"NPV at {results.discount_rate:g}%")
            else:
                self.npv_title.setText("NPV (no discount)")
        self.warnings_label.setText(
            "\n".join(f"Note: {text}" for text in results.warnings)
        )

        self.month_table.setRowCount(len(results.rows))
        for row_index, row in enumerate(results.rows):
            self.month_table.setItem(row_index, 0, _readonly_item(str(row.month), True))
            for column, value in enumerate(
                (row.cost, row.benefit, row.net, row.cumulative_net), start=1
            ):
                self.month_table.setItem(row_index, column, _readonly_item(money(value), True))
        self.chart.set_results(results)

    # ----- helpers ------------------------------------------------------

    def _money(self, value: float) -> str:
        return format_money(value, self._currency)

    def _emit_changed(self) -> None:
        self.refresh_results()
        self.changed.emit()

    def _on_name_edited(self, text: str) -> None:
        if self._loading or self._project is None:
            return
        self._project.name = text.strip() or "Untitled project"
        self.changed.emit()

    def _on_horizon_changed(self, value: int) -> None:
        if self._loading or self._project is None:
            return
        self._project.horizon_months = value
        self._emit_changed()

    def _on_rate_changed(self, value: float) -> None:
        if self._loading or self._project is None:
            return
        self._project.discount_rate = value
        self._emit_changed()

    def _on_notes_changed(self) -> None:
        if self._loading or self._project is None:
            return
        self._project.notes = self.notes_edit.toPlainText()
        self.changed.emit()

    def _update_timing_fields(self) -> None:
        monthly = self.item_timing.currentData() == TIMING_MONTHLY
        self.start_label.setText("Start month" if monthly else "Month")
        self.end_label.setVisible(monthly)
        self.item_end.setVisible(monthly)

    def _refresh_items_table(self) -> None:
        table = self.items_table
        table.blockSignals(True)
        try:
            items = self._project.line_items if self._project else []
            table.setRowCount(len(items))
            selected_row = -1
            for row, item in enumerate(items):
                name_cell = _readonly_item(item.name or "(unnamed)")
                name_cell.setData(ITEM_ID_ROLE, item.id)
                table.setItem(row, 0, name_cell)
                table.setItem(row, 1, _readonly_item(KIND_LABELS[item.kind]))
                table.setItem(row, 2, _readonly_item(self._money(item.amount), True))
                timing = TIMING_LABELS[item.timing]
                table.setItem(row, 3, _readonly_item(timing))
                table.setItem(row, 4, _readonly_item(str(item.start_month), True))
                if item.is_monthly:
                    end = "End" if item.end_month is None else str(item.end_month)
                else:
                    end = ""
                table.setItem(row, 5, _readonly_item(end, True))
                if item.id == self._editing_item_id:
                    selected_row = row
            if selected_row >= 0:
                table.selectRow(selected_row)
            else:
                table.clearSelection()
        finally:
            table.blockSignals(False)
        self._update_item_buttons()

    def _selected_item(self) -> LineItem | None:
        """The real LineItem for the selected row, found by id."""
        if self._project is None:
            return None
        rows = self.items_table.selectionModel().selectedRows()
        if not rows:
            return None
        cell = self.items_table.item(rows[0].row(), 0)
        if cell is None:
            return None
        return self._project.find_item(cell.data(ITEM_ID_ROLE))

    def _on_item_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            self._editing_item_id = None
            self._update_item_buttons()
            return
        self._editing_item_id = item.id
        self.item_name.setText(item.name)
        self.item_kind.setCurrentIndex(self.item_kind.findData(item.kind))
        self.item_amount.setText(f"{item.amount:.2f}")
        self.item_timing.setCurrentIndex(self.item_timing.findData(item.timing))
        self.item_start.setValue(item.start_month)
        self.item_end.setValue(END_OF_HORIZON if item.end_month is None else item.end_month)
        self.item_message.setText("")
        self._update_item_buttons()

    def _update_item_buttons(self) -> None:
        has_project = self._project is not None
        editing = has_project and self._editing_item_id is not None
        self.add_item_button.setEnabled(has_project)
        self.save_item_button.setEnabled(editing)
        self.remove_item_button.setEnabled(editing)

    def _clear_item_form(self) -> None:
        self._editing_item_id = None
        self.items_table.clearSelection()
        self.item_name.clear()
        self.item_kind.setCurrentIndex(0)
        self.item_amount.clear()
        self.item_timing.setCurrentIndex(0)
        self.item_start.setValue(0)
        self.item_end.setValue(END_OF_HORIZON)
        self.item_message.setText("")
        self._update_item_buttons()

    def _read_item_form(self) -> tuple[dict, str | None] | None:
        """Validate the item form. Returns (fields, warning) or None on error."""
        try:
            parsed = parse_number(self.item_amount.text(), "Amount")
        except NumberParseError as exc:
            self.item_message.setText(f"Not saved: {exc}")
            return None
        if parsed.value < 0:
            self.item_message.setText(
                "Not saved: amount cannot be negative. Choose Cost or Benefit instead."
            )
            return None
        if parsed.value > MAX_AMOUNT:
            self.item_message.setText("Not saved: amount is too large.")
            return None
        timing = self.item_timing.currentData()
        start = self.item_start.value()
        end = None
        if timing == TIMING_MONTHLY and self.item_end.value() != END_OF_HORIZON:
            end = self.item_end.value()
            if end < start:
                self.item_message.setText("Not saved: end month is before start month.")
                return None
        fields = {
            "name": self.item_name.text().strip(),
            "kind": self.item_kind.currentData(),
            "amount": parsed.value,
            "timing": timing,
            "start_month": start,
            "end_month": end,
        }
        return fields, parsed.warning

    def _show_saved_message(self, verb: str, warning: str | None) -> None:
        text = f"{verb}."
        if warning:
            text += f" Warning: {warning}"
        self.item_message.setText(text)

    def _submit_on_enter(self) -> None:
        if self._editing_item_id is not None:
            self._save_item()
        else:
            self._add_item()

    def _add_item(self) -> None:
        if self._project is None:
            return
        result = self._read_item_form()
        if result is None:
            return
        fields, warning = result
        if not fields["name"]:
            fields["name"] = f"Item {len(self._project.line_items) + 1}"
        item = LineItem(**fields)
        self._project.line_items.append(item)
        self._editing_item_id = None
        self._refresh_items_table()
        self._clear_item_form()
        self._show_saved_message(f'Added "{item.name}"', warning)
        self.item_name.setFocus()
        self._emit_changed()

    def _save_item(self) -> None:
        if self._project is None or self._editing_item_id is None:
            return
        item = self._project.find_item(self._editing_item_id)
        if item is None:
            self._clear_item_form()
            return
        result = self._read_item_form()
        if result is None:
            return
        fields, warning = result
        for key, value in fields.items():
            if key == "name" and not value:
                continue
            setattr(item, key, value)
        self._refresh_items_table()
        self._show_saved_message(f'Saved "{item.name}"', warning)
        self._emit_changed()

    def _remove_item(self) -> None:
        if self._project is None or self._editing_item_id is None:
            return
        item = self._project.find_item(self._editing_item_id)
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove item",
            f'Remove "{item.name}" from this project?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._project.line_items = [i for i in self._project.line_items if i.id != item.id]
        self._clear_item_form()
        self._refresh_items_table()
        self.item_message.setText(f'Removed "{item.name}".')
        self._emit_changed()
