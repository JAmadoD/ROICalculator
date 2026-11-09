"""Load and save projects as JSON. Pure Python, no Qt.

Saves are atomic: data is written to a temporary file in the same folder and
then moved over the real file with os.replace. The previous file is kept as
projects.json.bak. A damaged file is never silently replaced: it is renamed
aside and the caller gets a warning to show.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.models.project import Project, Settings

DATA_FILE_NAME = "projects.json"
FORMAT_VERSION = 1


class StorageError(Exception):
    """Raised when data cannot be saved."""


@dataclass(slots=True)
class LoadResult:
    projects: list[Project] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)
    warning: str | None = None


class ProjectStore:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / DATA_FILE_NAME
        self.backup_path = self.data_dir / (DATA_FILE_NAME + ".bak")
        self._save_blocked_reason: str | None = None

    def load(self) -> LoadResult:
        if not self.path.exists():
            return LoadResult()
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return self._handle_damaged(f"it could not be read ({exc})")
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            return self._handle_damaged(f"it is not valid JSON ({exc.msg}, line {exc.lineno})")

        if isinstance(payload, list):  # tolerate a bare list of projects
            payload = {"projects": payload}
        if not isinstance(payload, dict) or not isinstance(payload.get("projects", []), list):
            return self._handle_damaged("it does not have the expected structure")

        raw_projects = payload.get("projects", [])
        projects = [Project.from_dict(p) for p in raw_projects if isinstance(p, dict)]
        settings = Settings.from_dict(payload.get("settings"))
        skipped = len(raw_projects) - len(projects)
        warning = None
        if skipped:
            copy_path = self._aside_path()
            try:
                shutil.copy2(self.path, copy_path)
                where = f"A copy of the original file was saved as {copy_path.name}."
            except OSError:
                where = "A copy of the original file could not be made."
            what = f"{skipped} unreadable entries were"
            if skipped == 1:
                what = "1 unreadable entry was"
            warning = f"{what} skipped. {where}"
        return LoadResult(projects=projects, settings=settings, warning=warning)

    def save(self, projects: list[Project], settings: Settings) -> None:
        if self._save_blocked_reason:
            raise StorageError(self._save_blocked_reason)
        payload = {
            "version": FORMAT_VERSION,
            "settings": settings.to_dict(),
            "projects": [project.to_dict() for project in projects],
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        tmp_name: str | None = None
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=".projects-", suffix=".tmp", dir=str(self.data_dir)
            )
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.exists():
                shutil.copy2(self.path, self.backup_path)
            os.replace(tmp_name, self.path)
            tmp_name = None
        except OSError as exc:
            raise StorageError(f"Could not save to {self.path}: {exc}") from exc
        finally:
            if tmp_name is not None:
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass

    def _aside_path(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = self.data_dir / f"projects.damaged-{stamp}.json"
        counter = 1
        while candidate.exists():
            candidate = self.data_dir / f"projects.damaged-{stamp}-{counter}.json"
            counter += 1
        return candidate

    def _handle_damaged(self, reason: str) -> LoadResult:
        aside = self._aside_path()
        try:
            os.replace(self.path, aside)
        except OSError as exc:
            self._save_blocked_reason = (
                f"The data file {self.path} is damaged and could not be moved aside ({exc}). "
                "Saving is turned off so the file is not overwritten. "
                "Move or repair the file, then restart the app."
            )
            return LoadResult(warning=self._save_blocked_reason)
        backup_note = ""
        if self.backup_path.exists():
            backup_note = f" The previous save is still available as {self.backup_path.name}."
        return LoadResult(
            warning=(
                f"Your data file could not be loaded because {reason}. "
                f"It was renamed to {aside.name} in {self.data_dir} so nothing is lost."
                f"{backup_note} The app started with an empty project list."
            )
        )
