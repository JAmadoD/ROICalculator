import csv

import pytest

from app.models.project import (
    KIND_BENEFIT,
    KIND_COST,
    TIMING_MONTHLY,
    TIMING_ONE_TIME,
    LineItem,
    Project,
)
from app.services import csv_io
from app.services.csv_io import (
    CsvImportError,
    comparison_rows,
    export_project,
    parse_line_items,
    read_line_items,
    safe_cell,
)


def project():
    return Project(
        name="=Sneaky project",
        horizon_months=12,
        line_items=[
            LineItem(name="Setup, with comma", kind=KIND_COST, amount=1000),
            LineItem(name="=HYPERLINK(\"http://example.com\")", kind=KIND_COST, amount=50.25,
                     timing=TIMING_ONE_TIME, start_month=3),
            LineItem(name="Monthly sales", kind=KIND_BENEFIT, amount=150,
                     timing=TIMING_MONTHLY, start_month=1, end_month=None),
            LineItem(name="+Short promo", kind=KIND_BENEFIT, amount=75.5,
                     timing=TIMING_MONTHLY, start_month=2, end_month=4),
            LineItem(name="Café résumé", kind=KIND_COST, amount=10),
        ],
    )


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def comparable(items):
    return [
        (i.name, i.kind, round(i.amount, 2), i.timing, i.start_month,
         i.end_month if i.timing == TIMING_MONTHLY else None)
        for i in items
    ]


def test_round_trip_line_items(tmp_path):
    path = tmp_path / "export.csv"
    original = project()
    export_project(path, original, "$")
    result = read_line_items(path)
    assert comparable(result.items) == comparable(original.line_items)
    assert result.warnings == []


def test_export_is_utf8_with_bom_and_has_header(tmp_path):
    path = tmp_path / "export.csv"
    export_project(path, project(), "$")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = read_csv(path)
    assert rows[0] == csv_io.LINE_ITEM_HEADER
    assert "Café résumé" in raw.decode("utf-8-sig")


def test_header_written_even_without_items(tmp_path):
    path = tmp_path / "empty.csv"
    export_project(path, Project(name="Empty"))
    rows = read_csv(path)
    assert rows[0] == csv_io.LINE_ITEM_HEADER
    assert rows[1] == []


def test_injection_guard_on_text_cells(tmp_path):
    path = tmp_path / "export.csv"
    export_project(path, project(), "$")
    cells = [cell for row in read_csv(path) for cell in row]
    assert "'=HYPERLINK(\"http://example.com\")" in cells
    assert "'+Short promo" in cells
    assert "'=Sneaky project" in cells
    for cell in cells:
        if cell and cell[0] in "=+@":
            pytest.fail(f"unguarded cell: {cell!r}")


def test_negative_numbers_stay_numeric(tmp_path):
    path = tmp_path / "export.csv"
    loss = Project(name="Loss", horizon_months=1, line_items=[LineItem(amount=500)])
    export_project(path, loss, "$")
    rows = read_csv(path)
    net_row = next(row for row in rows if row and row[0] == "Net gain")
    assert net_row[1] == "-500.00"
    assert ["0", "500.00", "0.00", "-500.00", "-500.00", "-500.00"] in rows


@pytest.mark.parametrize("value", ["=1+1", "+1", "-cmd", "@SUM(A1)", "\tx", "\rx"])
def test_safe_cell_prefixes(value):
    assert safe_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["plain", "", "1-2", 5, -5.0, None])
def test_safe_cell_leaves_others(value):
    assert safe_cell(value) == value


def test_results_section_present(tmp_path):
    path = tmp_path / "export.csv"
    export_project(path, project(), "$")
    first_column = [row[0] for row in read_csv(path) if row]
    for label in ("Total cost", "Total benefit", "Net gain", "ROI (%)", "Payback", "NPV",
                  "Month"):
        assert label in first_column


def test_zero_cost_roi_is_na_in_export(tmp_path):
    path = tmp_path / "export.csv"
    free = Project(name="Free", line_items=[LineItem(kind=KIND_BENEFIT, amount=10)])
    export_project(path, free)
    rows = read_csv(path)
    assert ["ROI (%)", "N/A"] in rows


def test_import_hand_made_file_with_aliases_and_defaults():
    text = (
        "Item,Kind,Amount,Frequency,Start,End\n"
        "Rent,Expense,\"$1,200.00\",Monthly,,6\n"
        "Grant,Income,5000,once,2,\n"
        "Misc,,,,,\n"
    )
    result = parse_line_items(text)
    rent, grant, misc = result.items
    assert (rent.kind, rent.amount, rent.timing, rent.start_month, rent.end_month) == (
        KIND_COST, 1200.0, TIMING_MONTHLY, 1, 6)
    assert (grant.kind, grant.amount, grant.timing, grant.start_month) == (
        KIND_BENEFIT, 5000.0, TIMING_ONE_TIME, 2)
    assert misc.amount == 0 and misc.kind == KIND_COST
    joined = " ".join(result.warnings)
    assert "Row 4: Amount was blank, so 0 was used." in joined
    assert "Row 4: Type was blank" in joined


def test_import_skips_bad_rows_with_reasons():
    text = (
        "Name,Type,Amount,Timing,Start month,End month\n"
        "Good,Cost,10,One-time,0,\n"
        "Bad amount,Cost,abc,One-time,0,\n"
        "Bad type,Gift,10,One-time,0,\n"
        "Bad timing,Cost,10,Weekly,0,\n"
        "Bad end,Cost,10,Monthly,5,2\n"
        "Bad month,Cost,10,One-time,-1,\n"
        "Negative,Benefit,-20,One-time,0,\n"
    )
    result = parse_line_items(text)
    assert [i.name for i in result.items] == ["Good", "Negative"]
    assert result.items[1].amount == 20
    assert sum("skipped" in w for w in result.warnings) == 5
    assert any("negative amount made positive" in w for w in result.warnings)


def test_import_stops_at_blank_row():
    text = "Name,Amount\nA,1\n\nResult,Value\nTotal cost,1\n"
    assert [i.name for i in parse_line_items(text).items] == ["A"]


def test_import_requires_header():
    with pytest.raises(CsvImportError):
        parse_line_items("Rent,100\n")
    with pytest.raises(CsvImportError):
        parse_line_items("")


def test_import_rejects_non_utf8(tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes("Name,Amount\nCafé,1\n".encode("latin-1"))
    with pytest.raises(CsvImportError):
        read_line_items(path)


def test_comparison_rows():
    rows = comparison_rows([project(), Project(name="Empty")])
    assert rows[0][0] == "Project"
    assert len(rows) == 3
    assert rows[2][5] == "N/A"
