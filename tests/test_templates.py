import pytest

from app.models.project import Project
from app.services.calculator import calculate
from app.services.templates import TEMPLATES, from_template, sample_projects

EXPECTED = {"Blank", "Event", "Marketing campaign", "Equipment purchase", "New hire",
            "Software subscription"}


def test_all_requested_templates_exist():
    assert set(TEMPLATES) == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED - {"Blank"}))
def test_templates_have_costs_and_benefits_and_no_warnings(name):
    project = from_template(name)
    results = calculate(project)
    assert results.total_cost > 0
    assert results.total_benefit > 0
    assert results.warnings == []


def test_templates_return_fresh_objects():
    a = from_template("Event")
    b = from_template("Event")
    assert a.id != b.id
    assert a.line_items[0].id != b.line_items[0].id
    a.line_items.clear()
    assert b.line_items


def test_unknown_template():
    with pytest.raises(ValueError):
        from_template("Nope")


def test_sample_projects_are_distinct_and_valid():
    samples = sample_projects()
    assert len(samples) >= 5
    assert len({p.id for p in samples}) == len(samples)
    assert len({p.name for p in samples}) == len(samples)
    for project in samples:
        assert calculate(project).warnings == []
        assert Project.from_dict(project.to_dict()).to_dict() == project.to_dict()


def test_project_copy_gets_new_ids():
    original = from_template("New hire")
    clone = original.copy("Copy")
    assert clone.name == "Copy"
    assert clone.id != original.id
    assert {i.id for i in clone.line_items}.isdisjoint({i.id for i in original.line_items})
    assert [i.amount for i in clone.line_items] == [i.amount for i in original.line_items]
