"""Qt smoke tests. They run without a display (QT_QPA_PLATFORM=offscreen)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.models.project import KIND_BENEFIT, TIMING_MONTHLY  # noqa: E402
from app.services import csv_io  # noqa: E402
from app.services.storage import ProjectStore  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    # Never block on a dialog during tests.
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    win = MainWindow(ProjectStore(tmp_path))
    yield win
    win._dirty = False
    win.close()
    win.deleteLater()


def answer(monkeypatch, button):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: button))


def test_starts_empty_and_loads_samples(window):
    assert window.projects == []
    assert window.project_stack.currentIndex() == 0
    window.load_sample_data()
    assert window.project_list.count() == len(window.projects) >= 5
    assert window.project_stack.currentIndex() == 1
    assert window.editor.results is not None
    assert window.editor.month_table.rowCount() == window.projects[0].horizon_months + 1


def test_new_project_from_template_and_save(window, tmp_path):
    project = window.new_project("Software subscription")
    assert window.current_project() is project
    assert window.editor.items_table.rowCount() == len(project.line_items)
    assert window.editor.result_labels["roi"].text().endswith("%")
    assert window.save_now()
    reloaded = ProjectStore(tmp_path).load()
    assert reloaded.projects[0].name == "Software subscription"


def test_add_edit_and_remove_line_item(window, monkeypatch):
    project = window.new_project("Blank")
    editor = window.editor
    editor.item_name.setText("Machine")
    editor.item_amount.setText("1,000")
    editor.add_item_button.click()
    editor.item_name.setText("Savings")
    editor.item_kind.setCurrentIndex(editor.item_kind.findData(KIND_BENEFIT))
    editor.item_timing.setCurrentIndex(editor.item_timing.findData(TIMING_MONTHLY))
    editor.item_start.setValue(1)
    editor.item_amount.setText("250")
    editor.add_item_button.click()
    assert [i.name for i in project.line_items] == ["Machine", "Savings"]
    assert editor.result_labels["payback"].text() == "Month 4"
    assert editor.result_labels["roi"].text() == "200.0%"

    # Selecting a row edits the real record, found by id.
    editor.items_table.selectRow(1)
    assert editor.item_name.text() == "Savings"
    editor.item_amount.setText("500")
    editor.save_item_button.click()
    assert project.line_items[1].amount == 500

    # Blank amount saves 0 with a visible warning.
    editor.items_table.selectRow(0)
    editor.item_amount.setText("")
    editor.save_item_button.click()
    assert project.line_items[0].amount == 0
    assert "blank" in editor.item_message.text()
    assert editor.result_labels["roi"].text() == "N/A"

    # Invalid amount is refused and nothing changes.
    editor.items_table.selectRow(0)
    editor.item_amount.setText("lots")
    editor.save_item_button.click()
    assert project.line_items[0].amount == 0
    assert editor.item_message.text().startswith("Not saved")

    # Remove asks first; "No" keeps the item.
    editor.items_table.selectRow(0)
    answer(monkeypatch, QMessageBox.StandardButton.No)
    editor.remove_item_button.click()
    assert len(project.line_items) == 2
    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    editor.items_table.selectRow(0)
    editor.remove_item_button.click()
    assert [i.name for i in project.line_items] == ["Savings"]


def test_delete_project_asks_for_confirmation(window, monkeypatch):
    window.load_sample_data()
    count = len(window.projects)
    target = window.projects[2]
    window.select_project(target.id)
    answer(monkeypatch, QMessageBox.StandardButton.No)
    window.delete_project()
    assert len(window.projects) == count
    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    window.delete_project()
    assert target not in window.projects
    assert window.current_project() is window.projects[2]


def test_search_filters_list_and_selection_maps_to_record(window):
    window.load_sample_data()
    window.search_edit.setText("machine")
    assert window.project_list.count() == 1
    item = window.project_list.item(0)
    window.project_list.setCurrentItem(item)
    assert window.current_project().name == "Packaging machine"
    window.search_edit.setText("")
    assert window.project_list.count() == len(window.projects)


def test_duplicate_and_rename(window):
    window.new_project("Event")
    window.duplicate_project()
    assert [p.name for p in window.projects] == ["Event", "Event (copy)"]
    window.editor.name_edit.setText("Renamed")
    window.editor.name_edit.textEdited.emit("Renamed")
    assert window.current_project().name == "Renamed"
    assert window.project_list.currentItem().text() == "Renamed"


def test_compare_view_and_currency(window):
    window.load_sample_data()
    window.set_currency("EUR ")
    window.tabs.setCurrentIndex(1)
    table = window.compare_view.table
    assert table.rowCount() == len(window.projects)
    texts = [table.item(r, 2).text() for r in range(table.rowCount())]
    assert all(t.startswith("EUR") for t in texts)


def test_import_appends_items(window, tmp_path):
    project = window.new_project("Blank")
    path = tmp_path / "items.csv"
    path.write_text("Name,Type,Amount\nLaptop,Cost,900\nTime saved,Benefit,\n", encoding="utf-8")
    window.apply_import(project, csv_io.read_line_items(path))
    assert [i.name for i in project.line_items] == ["Laptop", "Time saved"]
    assert window.editor.items_table.rowCount() == 2


def test_damaged_data_file_warns_and_keeps_file(qapp, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a)))
    (tmp_path / "projects.json").write_text("not json", encoding="utf-8")
    win = MainWindow(ProjectStore(tmp_path))
    win._show_load_warning()
    assert shown and "renamed" in shown[0][2]
    assert list(tmp_path.glob("projects.damaged-*.json"))
    win._dirty = False
    win.close()


def test_window_scrolls_on_small_screens(window):
    window.load_sample_data()
    window.resize(640, 480)
    window.show()
    QApplication.processEvents()
    area = window.project_stack.widget(1)
    assert area.verticalScrollBar().maximum() > 0 or area.horizontalScrollBar().maximum() > 0
