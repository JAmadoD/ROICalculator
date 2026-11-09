"""Where the app keeps its data and where exports go by default.

Data lives in the per-user app data folder (never next to the program, so
the app also works when installed in a read-only place like Program Files).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths

APP_NAME = "ROI Calculator"


def data_dir() -> Path:
    """Per-user folder for projects.json. Requires the QApplication name to be set."""
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not location:
        location = str(Path.home() / ".roi-calculator")
    return Path(location)


def documents_dir() -> Path:
    """Default folder for CSV exports and imports."""
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(location) if location else Path.home()
