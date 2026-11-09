"""Entry point: python -m app.main"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app import __version__
from app.services.storage import ProjectStore
from app.ui.main_window import MainWindow
from app.utils.paths import APP_NAME, data_dir


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    # No organization name, so data goes straight into ".../ROI Calculator".
    app.setOrganizationName("")
    window = MainWindow(ProjectStore(data_dir()))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
