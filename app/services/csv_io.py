"""CSV export and import. Pure Python, no Qt.

Files are written as UTF-8 with a byte order mark (utf-8-sig) so Excel opens
them correctly. Text cells that start with = + - @ (or a tab or carriage
return) get a leading single quote so spreadsheet programs do not run them
as formulas.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.models.project import (
    KIND_BENEFIT,
    KIND_COST,
    KIND_LABELS,
    MAX_AMOUNT,
    MAX_MONTH,
    TIMING_LABELS,
    TIMING_MONTHLY,
    TIMING_ONE_TIME,
    LineItem,
    Project,
)
from app.services.calculator import ProjectResults, calculate, describe_payback
from app.utils.numbers import NumberParseError, parse_int, parse_number

LINE_ITEM_HEADER = ["Name", "Type", "Amount", "Timing", "Start month", "End month"]
MONTH_HEADER = ["Month", "Cost", "Benefit", "Net", "Cumulative net", "Discounted net"]
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_KIND_WORDS = {
    "cost": KIND_COST,
    "costs": KIND_COST,
    "expense": KIND_COST,
    "benefit": KIND_BENEFIT,
    "benefits": KIND_BENEFIT,
    "income": KIND_BENEFIT,
    "revenue": KIND_BENEFIT,
    "saving": KIND_BENEFIT,
    "savings": KIND_BENEFIT,
}
_TIMING_WORDS = {
    "one-time": TIMING_ONE_TIME,
    "one time": TIMING_ONE_TIME,
    "one_time": TIMING_ONE_TIME,
    "onetime": TIMING_ONE_TIME,
    "once": TIMING_ONE_TIME,
    "monthly": TIMING_MONTHLY,
    "recurring": TIMING_MONTHLY,
    "per month": TIMING_MONTHLY,
}


class CsvImportError(Exception):
    """Raised when a CSV file cannot be used at all."""


@dataclass(slots=True)
class ImportResult:
    items: list[LineItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def safe_cell(value: Any) -> Any:
    """Neutralize text that a spreadsheet would treat as a formula.

    Numbers are left alone: a plain negative number is not a formula.
    """
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _unsafe_cell(text: str) -> str:
    """Undo safe_cell when reading our own files back."""
    if len(text) > 1 and text[0] == "'" and text[1:].startswith(FORMULA_PREFIXES):
        return text[1:]
    return text


def _num(value: float) -> Decimal:
    """A number with two decimals. Not a str, so safe_cell leaves it alone."""
    if abs(value) < 0.005:
        value = 0.0
    return Decimal(f"{value:.2f}")


def project_to_rows(project: Project, results: ProjectResults | None = None,
                    currency_symbol: str = "") -> list[list[Any]]:
    """All rows of a project export: line items, results, then month table."""
    results = results or calculate(project)
    rows: list[list[Any]] = [list(LINE_ITEM_HEADER)]
    for item in project.line_items:
        end = ""
        if item.is_monthly:
            end = "" if item.end_month is None else item.end_month
        rows.append([
            item.name,
            KIND_LABELS[item.kind],
            _num(item.amount),
            TIMING_LABELS[item.timing],
            item.start_month,
            end,
        ])
    rows.append([])
    rows.append(["Result", "Value"])
    rows.append(["Project", project.name])
    rows.append(["Currency", currency_symbol])
    rows.append(["Horizon (months)", project.horizon_months])
    rows.append(["Discount rate (% per year)", Decimal(f"{project.discount_rate:g}")])
    rows.append(["Total cost", _num(results.total_cost)])
    rows.append(["Total benefit", _num(results.total_benefit)])
    rows.append(["Net gain", _num(results.net_gain)])
    rows.append(["ROI (%)", "N/A" if results.roi_percent is None else _num(results.roi_percent)])
    rows.append([
        "Annualized ROI (%)",
        "N/A" if results.annualized_roi_percent is None else _num(results.annualized_roi_percent),
    ])
    rows.append(["Payback", describe_payback(results)])
    rows.append(["NPV", _num(results.npv)])
    rows.append([])
    rows.append(list(MONTH_HEADER))
    for row in results.rows:
        rows.append([
            row.month,
            _num(row.cost),
            _num(row.benefit),
            _num(row.net),
            _num(row.cumulative_net),
            _num(row.discounted_net),
        ])
    return rows


def write_rows(path: Path | str, rows: list[list[Any]]) -> None:
    """Write rows as an Excel friendly CSV file."""
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow([safe_cell(cell) for cell in row])


def export_project(path: Path | str, project: Project, currency_symbol: str = "") -> None:
    write_rows(path, project_to_rows(project, currency_symbol=currency_symbol))


def comparison_rows(projects: list[Project]) -> list[list[Any]]:
    rows: list[list[Any]] = [[
        "Project", "Horizon (months)", "Total cost", "Total benefit", "Net gain",
        "ROI (%)", "Annualized ROI (%)", "Payback", "NPV",
    ]]
    for project in projects:
        r = calculate(project)
        rows.append([
            project.name,
            project.horizon_months,
            _num(r.total_cost),
            _num(r.total_benefit),
            _num(r.net_gain),
            "N/A" if r.roi_percent is None else _num(r.roi_percent),
            "N/A" if r.annualized_roi_percent is None else _num(r.annualized_roi_percent),
            describe_payback(r),
            _num(r.npv),
        ])
    return rows


def read_line_items(path: Path | str) -> ImportResult:
    """Read line items from a CSV file.

    The first non-empty row must be a header with at least Name and Amount.
    Reading stops at the first fully blank row, so a full project export can
    be imported directly (its results section is ignored).
    """
    try:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            text = handle.read()
    except UnicodeDecodeError as exc:
        raise CsvImportError(
            "The file is not UTF-8 text. Save it as CSV UTF-8 and try again."
        ) from exc
    return parse_line_items(text)


def _header_index(header: list[str]) -> dict[str, int]:
    aliases = {
        "name": "name", "item": "name", "description": "name",
        "type": "kind", "kind": "kind", "cost or benefit": "kind",
        "amount": "amount", "value": "amount",
        "timing": "timing", "frequency": "timing",
        "start month": "start", "start_month": "start", "month": "start", "start": "start",
        "end month": "end", "end_month": "end", "end": "end",
    }
    index: dict[str, int] = {}
    for position, title in enumerate(header):
        key = aliases.get(_unsafe_cell(title).strip().lower())
        if key and key not in index:
            index[key] = position
    return index


def parse_line_items(text: str) -> ImportResult:
    result = ImportResult()
    reader = csv.reader(io.StringIO(text))
    header: list[str] | None = None
    columns: dict[str, int] = {}
    row_number = 0
    for row in reader:
        row_number += 1
        is_blank = not any(cell.strip() for cell in row)
        if header is None:
            if is_blank:
                continue
            header = row
            columns = _header_index(header)
            if "name" not in columns or "amount" not in columns:
                raise CsvImportError(
                    "The first row must be a header with at least Name and Amount columns. "
                    "Expected columns: " + ", ".join(LINE_ITEM_HEADER) + "."
                )
            continue
        if is_blank:
            break
        try:
            item, warnings = _row_to_item(row, columns, row_number)
        except ValueError as exc:
            result.warnings.append(f"Row {row_number} skipped: {exc}")
            continue
        result.items.append(item)
        result.warnings.extend(warnings)
    if header is None:
        raise CsvImportError("The file is empty.")
    return result


def _cell(row: list[str], columns: dict[str, int], key: str) -> str:
    position = columns.get(key)
    if position is None or position >= len(row):
        return ""
    return _unsafe_cell(row[position].strip())


def _row_to_item(row: list[str], columns: dict[str, int],
                 row_number: int) -> tuple[LineItem, list[str]]:
    warnings: list[str] = []
    name = _cell(row, columns, "name") or f"Item from row {row_number}"

    kind_text = _cell(row, columns, "kind").lower()
    if not kind_text:
        kind = KIND_COST
        warnings.append(f"Row {row_number}: Type was blank, so Cost was used.")
    elif kind_text in _KIND_WORDS:
        kind = _KIND_WORDS[kind_text]
    else:
        raise ValueError(f'Type "{kind_text}" should be Cost or Benefit.')

    try:
        parsed = parse_number(_cell(row, columns, "amount"), "Amount")
    except NumberParseError as exc:
        raise ValueError(str(exc)) from exc
    if parsed.warning:
        warnings.append(f"Row {row_number}: {parsed.warning}")
    amount = parsed.value
    if amount < 0:
        amount = -amount
        warnings.append(
            f"Row {row_number}: negative amount made positive. Use the Type column for direction."
        )
    if amount > MAX_AMOUNT:
        raise ValueError("Amount is too large.")

    timing_text = _cell(row, columns, "timing").lower()
    if not timing_text:
        timing = TIMING_ONE_TIME
    elif timing_text in _TIMING_WORDS:
        timing = _TIMING_WORDS[timing_text]
    else:
        raise ValueError(f'Timing "{timing_text}" should be One-time or Monthly.')

    default_start = 1 if timing == TIMING_MONTHLY else 0
    start = _month(_cell(row, columns, "start"), "Start month", default_start)
    end_text = _cell(row, columns, "end")
    end = None
    if timing == TIMING_MONTHLY and end_text:
        end = _month(end_text, "End month", 0)
        if end < start:
            raise ValueError("End month is before start month.")
    return LineItem(name=name, kind=kind, amount=amount, timing=timing,
                    start_month=start, end_month=end), warnings


def _month(text: str, label: str, default: int) -> int:
    if not text:
        return default
    try:
        value = int(parse_int(text, label).value)
    except NumberParseError as exc:
        raise ValueError(str(exc)) from exc
    if value < 0 or value > MAX_MONTH:
        raise ValueError(f"{label} must be between 0 and {MAX_MONTH}.")
    return value
