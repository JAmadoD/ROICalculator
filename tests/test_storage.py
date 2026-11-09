import json
import os

import pytest

from app.models.project import KIND_BENEFIT, TIMING_MONTHLY, LineItem, Project, Settings
from app.services import storage as storage_module
from app.services.storage import ProjectStore, StorageError


def sample():
    return [
        Project(
            name="Shop fitting",
            notes="Line one\nLine two",
            horizon_months=24,
            discount_rate=5.5,
            line_items=[
                LineItem(name="Shelves", amount=1200.5),
                LineItem(name="Sales", kind=KIND_BENEFIT, amount=300, timing=TIMING_MONTHLY,
                         start_month=1, end_month=18),
            ],
        )
    ]


def test_missing_file_loads_empty(tmp_path):
    result = ProjectStore(tmp_path / "not-there-yet").load()
    assert result.projects == []
    assert result.warning is None


def test_round_trip(tmp_path):
    store = ProjectStore(tmp_path / "data")
    projects = sample()
    store.save(projects, Settings(currency_symbol="EUR"))
    loaded = store.load()
    assert loaded.warning is None
    assert loaded.settings.currency_symbol == "EUR"
    assert [p.to_dict() for p in loaded.projects] == [p.to_dict() for p in projects]


def test_save_keeps_backup_of_previous_file(tmp_path):
    store = ProjectStore(tmp_path)
    first = sample()
    store.save(first, Settings())
    second = sample()
    second[0].name = "Changed"
    store.save(second, Settings())
    backup = json.loads(store.backup_path.read_text(encoding="utf-8"))
    current = json.loads(store.path.read_text(encoding="utf-8"))
    assert backup["projects"][0]["name"] == "Shop fitting"
    assert current["projects"][0]["name"] == "Changed"


def test_save_is_atomic_when_write_fails(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    store.save(sample(), Settings())
    before = store.path.read_bytes()

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(storage_module.os, "replace", broken_replace)
    changed = sample()
    changed[0].name = "Never written"
    with pytest.raises(StorageError, match="disk full"):
        store.save(changed, Settings())
    assert store.path.read_bytes() == before
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_save_error_when_folder_cannot_be_created(tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder", encoding="utf-8")
    store = ProjectStore(blocker / "sub")
    with pytest.raises(StorageError):
        store.save(sample(), Settings())


def test_corrupt_file_is_renamed_aside_not_replaced(tmp_path):
    store = ProjectStore(tmp_path)
    store.path.write_text("{ this is not json", encoding="utf-8")
    result = store.load()
    assert result.projects == []
    assert result.warning is not None and "renamed" in result.warning
    assert not store.path.exists()
    damaged = list(tmp_path.glob("projects.damaged-*.json"))
    assert len(damaged) == 1
    assert damaged[0].read_text(encoding="utf-8") == "{ this is not json"

    # Saving afterwards writes a fresh file and keeps the damaged copy.
    store.save(sample(), Settings())
    assert store.load().projects[0].name == "Shop fitting"
    assert damaged[0].exists()


def test_wrong_structure_is_treated_as_damaged(tmp_path):
    store = ProjectStore(tmp_path)
    store.path.write_text('"just a string"', encoding="utf-8")
    result = store.load()
    assert result.warning is not None
    assert list(tmp_path.glob("projects.damaged-*.json"))


def test_damaged_file_that_cannot_be_moved_blocks_saving(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    store.path.write_text("garbage", encoding="utf-8")

    def broken_replace(src, dst):
        raise OSError("locked")

    monkeypatch.setattr(storage_module.os, "replace", broken_replace)
    result = store.load()
    assert "Saving is turned off" in result.warning
    monkeypatch.undo()
    with pytest.raises(StorageError, match="Saving is turned off"):
        store.save(sample(), Settings())
    assert store.path.read_text(encoding="utf-8") == "garbage"


def test_unreadable_entries_are_skipped_with_warning_and_copy(tmp_path):
    store = ProjectStore(tmp_path)
    good = sample()[0].to_dict()
    store.path.write_text(json.dumps({"projects": [good, 42, "bad"]}), encoding="utf-8")
    result = store.load()
    assert len(result.projects) == 1
    assert "2 unreadable entries" in result.warning
    assert list(tmp_path.glob("projects.damaged-*.json"))


def test_bare_list_is_accepted(tmp_path):
    store = ProjectStore(tmp_path)
    store.path.write_text(json.dumps([sample()[0].to_dict()]), encoding="utf-8")
    result = store.load()
    assert result.warning is None
    assert result.projects[0].name == "Shop fitting"


def test_values_are_sanitized_on_load(tmp_path):
    store = ProjectStore(tmp_path)
    raw = {
        "projects": [{
            "name": "",
            "horizon_months": 99999,
            "discount_rate": 500,
            "line_items": [
                {"name": "x", "kind": "weird", "amount": "-50", "timing": "??",
                 "start_month": -3, "end_month": ""},
            ],
        }],
        "settings": {"currency_symbol": 7},
    }
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    result = store.load()
    project = result.projects[0]
    assert project.name == "Untitled project"
    assert project.horizon_months == 600
    assert project.discount_rate == 100.0
    item = project.line_items[0]
    assert item.kind == "cost"
    assert item.amount == 50
    assert item.timing == "one_time"
    assert item.start_month == 0
    assert item.end_month is None
    assert result.settings.currency_symbol == "$"


def test_no_temp_files_left_after_save(tmp_path):
    store = ProjectStore(tmp_path)
    store.save(sample(), Settings())
    names = sorted(os.listdir(tmp_path))
    assert names == ["projects.json"]
