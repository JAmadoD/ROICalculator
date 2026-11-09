"""Render docs/screenshot.png from sample data, without showing a window.

Usage (from the project folder):
    python scripts/make_screenshot.py

Uses a temporary data folder, so your own projects are never touched.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32" and "QT_QPA_FONTDIR" not in os.environ:
    # The offscreen platform does not find Windows fonts by itself.
    os.environ["QT_QPA_FONTDIR"] = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.storage import ProjectStore  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    for family in ("Segoe UI", "Noto Sans", "DejaVu Sans", "Helvetica"):
        if family in QFontDatabase.families():
            app.setFont(QFont(family, 9))
            break
    with tempfile.TemporaryDirectory() as folder:
        window = MainWindow(ProjectStore(folder))
        window.load_sample_data()
        target = next(p for p in window.projects if p.name == "Software subscription"
                      or p.name == "Scheduling software")
        window.select_project(target.id)
        window.statusBar().clearMessage()
        window.resize(1360, 860)
        window.show()
        for _ in range(5):
            app.processEvents()
        out = ROOT / "docs" / "screenshot.png"
        out.parent.mkdir(exist_ok=True)
        if not window.grab().save(str(out)):
            print("Could not save", out)
            return 1
        window._dirty = False
        window.close()
    print("Saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
