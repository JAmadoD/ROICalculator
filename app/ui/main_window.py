"""Main window: project list on the left, editor and comparison on the right."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.models.project import Project, Settings
from app.services import csv_io, templates
from app.services.storage import ProjectStore, StorageError
from app.ui.compare_view import CompareView
from app.ui.project_editor import ProjectEditor
from app.utils.paths import APP_NAME, documents_dir

PROJECT_ID_ROLE = Qt.ItemDataRole.UserRole
SAVE_DELAY_MS = 400

HOW_IT_WORKS = """<p><b>Timeline.</b> Month 0 is the start. A horizon of N months
covers months 0 to N. One-time items happen in one month. Monthly items repeat
every month from their start month to their end month (or the end of the horizon).</p>
<p><b>Net gain</b> = total benefit minus total cost, within the horizon.</p>
<p><b>ROI</b> = net gain divided by total cost, times 100. When total cost is 0
the ROI is shown as N/A.</p>
<p><b>Payback</b> = the first month from which the running total of
(benefits minus costs) stays at zero or above until the end of the horizon.</p>
<p><b>Annualized ROI</b> = (total benefit / total cost) to the power of
(12 / horizon months), minus 1, times 100. It turns the result into a yearly rate.</p>
<p><b>NPV</b> = the sum of each month's net divided by (1 + r) to the power of the
month, where r is the monthly rate that matches the yearly discount rate. With a
discount rate of 0, NPV equals net gain.</p>"""


def _safe_file_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().strip(".")
    return cleaned[:80] or "project"


class MainWindow(QMainWindow):
    def __init__(self, store: ProjectStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)

        loaded = store.load()
        self.projects: list[Project] = loaded.projects
        self.settings: Settings = loaded.settings
        self._load_warning = loaded.warning
        self._current_id: str | None = None
        self._dirty = False
        self._save_error_shown = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_now)

        self._build_ui()
        self._build_menus()
        self.editor.set_currency(self.settings.currency_symbol)
        self._refresh_project_list()
        if self.projects:
            self.select_project(self.projects[0].id)
        else:
            self._show_project(None)
        self.statusBar().showMessage(f"Data folder: {self.store.data_dir}")
        if self._load_warning:
            QTimer.singleShot(0, self._show_load_warning)

    # ----- construction -------------------------------------------------

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.addWidget(QLabel("Projects"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search projects")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._refresh_project_list)
        left_layout.addWidget(self.search_edit)
        self.project_list = QListWidget()
        self.project_list.currentItemChanged.connect(self._on_list_selection)
        left_layout.addWidget(self.project_list, 1)

        row = QHBoxLayout()
        self.new_button = QToolButton()
        self.new_button.setText("New")
        self.new_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.new_button.setMenu(self._template_menu(self))
        self.duplicate_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")
        self.duplicate_button.clicked.connect(self.duplicate_project)
        self.delete_button.clicked.connect(self.delete_project)
        row.addWidget(self.new_button)
        row.addWidget(self.duplicate_button)
        row.addWidget(self.delete_button)
        left_layout.addLayout(row)
        left.setMinimumWidth(180)
        splitter.addWidget(left)

        self.tabs = QTabWidget()
        self.project_stack = QStackedWidget()
        self.project_stack.addWidget(self._empty_page())
        self.editor = ProjectEditor()
        self.editor.changed.connect(self._on_project_changed)
        self.project_stack.addWidget(self._scrolling(self.editor))
        self.tabs.addTab(self.project_stack, "Project")

        self.compare_view = CompareView()
        self.compare_view.open_project.connect(self._open_from_compare)
        self.compare_view.export_requested.connect(self.export_comparison)
        self.tabs.addTab(self._scrolling(self.compare_view), "Compare")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1040])
        self.setCentralWidget(splitter)

    @staticmethod
    def _scrolling(widget: QWidget) -> QScrollArea:
        """Wrap a page so it scrolls instead of being squashed on small screens."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(widget)
        return area

    def _empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        title = QLabel("No project selected")
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 1.4)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel(
            "Start a new project from a template, or load sample data to see how it works."
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        buttons.addStretch()
        new_button = QToolButton()
        new_button.setText("New project")
        new_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        new_button.setMenu(self._template_menu(page))
        sample_button = QPushButton("Load sample data")
        sample_button.clicked.connect(self.load_sample_data)
        buttons.addWidget(new_button)
        buttons.addWidget(sample_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addStretch()
        return page

    def _template_menu(self, parent: QWidget) -> QMenu:
        menu = QMenu("New project", parent)
        for name in templates.TEMPLATES:
            action = menu.addAction(name)
            action.triggered.connect(lambda _checked=False, n=name: self.new_project(n))
        return menu

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addMenu(self._template_menu(self))
        self.duplicate_action = file_menu.addAction("Duplicate project", self.duplicate_project)
        self.delete_action = file_menu.addAction("Delete project...", self.delete_project)
        file_menu.addSeparator()
        self.import_action = file_menu.addAction(
            "Import line items from CSV...", self.import_line_items
        )
        self.export_action = file_menu.addAction("Export project to CSV...", self.export_project)
        file_menu.addAction("Export comparison to CSV...", self.export_comparison)
        file_menu.addSeparator()
        file_menu.addAction("Load sample data", self.load_sample_data)
        file_menu.addAction("Open data folder", self.open_data_folder)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        settings_menu = self.menuBar().addMenu("&Settings")
        settings_menu.addAction("Currency symbol...", self.change_currency)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("How results are calculated", self.show_how_it_works)
        help_menu.addAction("About", self.show_about)

    # ----- project list -------------------------------------------------

    def current_project(self) -> Project | None:
        return self.find_project(self._current_id) if self._current_id else None

    def find_project(self, project_id: str | None) -> Project | None:
        for project in self.projects:
            if project.id == project_id:
                return project
        return None

    def _matches(self, project: Project, query: str) -> bool:
        if not query:
            return True
        haystack = " ".join([project.name, project.notes] + [i.name for i in project.line_items])
        return query in haystack.lower()

    def _refresh_project_list(self) -> None:
        query = self.search_edit.text().strip().lower()
        self.project_list.blockSignals(True)
        try:
            self.project_list.clear()
            for project in self.projects:
                if not self._matches(project, query):
                    continue
                item = QListWidgetItem(project.name)
                item.setData(PROJECT_ID_ROLE, project.id)
                self.project_list.addItem(item)
                if project.id == self._current_id:
                    self.project_list.setCurrentItem(item)
        finally:
            self.project_list.blockSignals(False)
        self._update_actions()

    def _list_item_for(self, project_id: str) -> QListWidgetItem | None:
        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            if item.data(PROJECT_ID_ROLE) == project_id:
                return item
        return None

    def select_project(self, project_id: str | None) -> None:
        project = self.find_project(project_id)
        if project is None:
            self._show_project(None)
            return
        if self._list_item_for(project.id) is None and self.search_edit.text():
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
            self._current_id = project.id
            self._refresh_project_list()
        item = self._list_item_for(project.id)
        if item is not None:
            self.project_list.blockSignals(True)
            self.project_list.setCurrentItem(item)
            self.project_list.blockSignals(False)
        self._show_project(project)

    def _show_project(self, project: Project | None) -> None:
        self._current_id = project.id if project else None
        self.editor.set_project(project)
        self.project_stack.setCurrentIndex(1 if project else 0)
        self._update_actions()

    def _on_list_selection(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        project = self.find_project(current.data(PROJECT_ID_ROLE))
        if project is not None and project.id != self._current_id:
            self._show_project(project)
            self.tabs.setCurrentIndex(0)

    def _update_actions(self) -> None:
        has_project = self.current_project() is not None
        for widget in (self.duplicate_button, self.delete_button):
            widget.setEnabled(has_project)
        for action_name in ("duplicate_action", "delete_action", "import_action", "export_action"):
            action = getattr(self, action_name, None)
            if action is not None:
                action.setEnabled(has_project)

    def _on_project_changed(self) -> None:
        project = self.current_project()
        if project is not None:
            item = self._list_item_for(project.id)
            if item is not None and item.text() != project.name:
                item.setText(project.name)
        self.schedule_save()

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self.compare_view.set_projects(self.projects, self.settings.currency_symbol)

    def _open_from_compare(self, project_id: str) -> None:
        self.select_project(project_id)
        self.tabs.setCurrentIndex(0)

    def _after_list_change(self, select_id: str | None) -> None:
        self._current_id = select_id
        self._refresh_project_list()
        self.select_project(select_id)
        if self.tabs.currentIndex() == 1:
            self.compare_view.set_projects(self.projects, self.settings.currency_symbol)
        self.schedule_save()

    # ----- actions ------------------------------------------------------

    def new_project(self, template_name: str = "Blank") -> Project:
        project = templates.from_template(template_name)
        self.projects.append(project)
        self._after_list_change(project.id)
        self.tabs.setCurrentIndex(0)
        return project

    def duplicate_project(self) -> None:
        project = self.current_project()
        if project is None:
            return
        clone = project.copy(new_name=f"{project.name} (copy)")
        index = self.projects.index(project)
        self.projects.insert(index + 1, clone)
        self._after_list_change(clone.id)

    def delete_project(self) -> None:
        project = self.current_project()
        if project is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete project",
            f'Delete "{project.name}"? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        index = self.projects.index(project)
        self.projects.remove(project)
        next_id = None
        if self.projects:
            next_id = self.projects[min(index, len(self.projects) - 1)].id
        self._after_list_change(next_id)

    def load_sample_data(self) -> None:
        samples = templates.sample_projects()
        self.projects.extend(samples)
        self._after_list_change(samples[0].id)
        self.tabs.setCurrentIndex(0)
        self.statusBar().showMessage(f"Added {len(samples)} sample projects.", 5000)

    def change_currency(self) -> None:
        symbol, ok = QInputDialog.getText(
            self,
            "Currency symbol",
            "Symbol shown before amounts (for example $, EUR, or leave blank):",
            QLineEdit.EchoMode.Normal,
            self.settings.currency_symbol,
        )
        if not ok:
            return
        self.set_currency(symbol)

    def set_currency(self, symbol: str) -> None:
        self.settings.currency_symbol = symbol.strip()[:5]
        self.editor.set_currency(self.settings.currency_symbol)
        if self.tabs.currentIndex() == 1:
            self.compare_view.set_projects(self.projects, self.settings.currency_symbol)
        self.schedule_save()

    def _ask_save_path(self, title: str, suggested: str) -> Path | None:
        start = documents_dir() / suggested
        path, _filter = QFileDialog.getSaveFileName(
            self, title, str(start), "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return None
        result = Path(path)
        if not result.suffix:
            result = result.with_suffix(".csv")
        return result

    def export_project(self) -> None:
        project = self.current_project()
        if project is None:
            return
        path = self._ask_save_path("Export project", f"{_safe_file_name(project.name)}.csv")
        if path is None:
            return
        try:
            csv_io.export_project(path, project, self.settings.currency_symbol)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", f"Could not write {path}:\n{exc}")
            return
        self.statusBar().showMessage(f"Exported to {path}", 8000)

    def export_comparison(self) -> None:
        if not self.projects:
            QMessageBox.information(self, "Export comparison", "There are no projects yet.")
            return
        path = self._ask_save_path("Export comparison", "roi-comparison.csv")
        if path is None:
            return
        try:
            csv_io.write_rows(path, csv_io.comparison_rows(self.projects))
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", f"Could not write {path}:\n{exc}")
            return
        self.statusBar().showMessage(f"Exported to {path}", 8000)

    def import_line_items(self) -> None:
        project = self.current_project()
        if project is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import line items", str(documents_dir()), "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            result = csv_io.read_line_items(path)
        except (OSError, csv_io.CsvImportError) as exc:
            QMessageBox.critical(self, "Import failed", f"Could not import {path}:\n{exc}")
            return
        self.apply_import(project, result)

    def apply_import(self, project: Project, result: csv_io.ImportResult) -> None:
        project.line_items.extend(result.items)
        self.editor.reload()
        self.schedule_save()
        box = QMessageBox(self)
        box.setWindowTitle("Import finished")
        box.setIcon(QMessageBox.Icon.Information if not result.warnings
                    else QMessageBox.Icon.Warning)
        box.setText(f'Added {len(result.items)} line item(s) to "{project.name}".')
        if result.warnings:
            box.setInformativeText(f"{len(result.warnings)} note(s). See details.")
            box.setDetailedText("\n".join(result.warnings))
        box.exec()

    def open_data_folder(self) -> None:
        try:
            self.store.data_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.data_dir)))

    def show_how_it_works(self) -> None:
        QMessageBox.information(self, "How results are calculated", HOW_IT_WORKS)

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<p><b>{APP_NAME}</b> {__version__}</p>"
            "<p>Work out the return on any investment: events, ad campaigns, "
            "equipment, hires, software, side projects.</p>"
            "<p>Works fully offline. Nothing is sent anywhere.</p>"
            f"<p>Your data is stored in:<br>{self.store.data_dir}</p>"
            "<p>ROI Calculator by Joshua Amado. Free and source available under the "
            "AmadOpenSource License 1.0: free to use for anything, including at work, "
            "but the software itself may not be sold. "
            "See the LICENSE file.</p>",
        )

    def _show_load_warning(self) -> None:
        QMessageBox.warning(self, "Data file problem", self._load_warning or "")

    # ----- saving -------------------------------------------------------

    def schedule_save(self) -> None:
        self._dirty = True
        self._save_timer.start()

    def save_now(self) -> bool:
        self._save_timer.stop()
        try:
            self.store.save(self.projects, self.settings)
        except StorageError as exc:
            self.statusBar().showMessage("Not saved. See the error message.")
            if not self._save_error_shown:
                self._save_error_shown = True
                QMessageBox.critical(
                    self,
                    "Save failed",
                    f"Your changes could not be saved.\n\n{exc}\n\n"
                    "The app will keep trying as you make changes.",
                )
            return False
        self._dirty = False
        self._save_error_shown = False
        self.statusBar().showMessage("Saved", 2000)
        return True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API name)
        if self._dirty and not self.save_now():
            answer = QMessageBox.question(
                self,
                "Quit without saving?",
                "Your latest changes could not be saved. Quit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
