"""Starter templates and sample data. Pure Python, no Qt.

All amounts are made-up round numbers meant as a starting point.
"""

from __future__ import annotations

from collections.abc import Callable

from app.models.project import (
    KIND_BENEFIT,
    KIND_COST,
    TIMING_MONTHLY,
    TIMING_ONE_TIME,
    LineItem,
    Project,
)


def _cost(name: str, amount: float, month: int = 0) -> LineItem:
    return LineItem(name=name, kind=KIND_COST, amount=amount, timing=TIMING_ONE_TIME,
                    start_month=month)


def _benefit(name: str, amount: float, month: int = 0) -> LineItem:
    return LineItem(name=name, kind=KIND_BENEFIT, amount=amount, timing=TIMING_ONE_TIME,
                    start_month=month)


def _monthly_cost(name: str, amount: float, start: int = 1, end: int | None = None) -> LineItem:
    return LineItem(name=name, kind=KIND_COST, amount=amount, timing=TIMING_MONTHLY,
                    start_month=start, end_month=end)


def _monthly_benefit(name: str, amount: float, start: int = 1,
                     end: int | None = None) -> LineItem:
    return LineItem(name=name, kind=KIND_BENEFIT, amount=amount, timing=TIMING_MONTHLY,
                    start_month=start, end_month=end)


def blank() -> Project:
    return Project(name="New project", horizon_months=12)


def event() -> Project:
    return Project(
        name="Event",
        notes="A one-day event. Costs are paid up front, ticket sales come in month 1, "
              "and some new customers keep buying for a few months.",
        horizon_months=6,
        line_items=[
            _cost("Venue rental", 2000),
            _cost("Supplies and printing", 600),
            _cost("Staff hours", 900),
            _benefit("Ticket sales", 3000, month=1),
            _monthly_benefit("Repeat purchases from new customers", 250, start=2, end=6),
        ],
    )


def marketing_campaign() -> Project:
    return Project(
        name="Marketing campaign",
        notes="Three months of paid ads. Extra sales continue for a while after the ads stop.",
        horizon_months=12,
        line_items=[
            _cost("Creative and setup", 1000),
            _monthly_cost("Ad spend", 1500, start=1, end=3),
            _monthly_benefit("Extra gross profit from new sales", 900, start=1, end=12),
        ],
    )


def equipment_purchase() -> Project:
    return Project(
        name="Equipment purchase",
        notes="A machine that saves labor. Includes upkeep and a resale value at the end.",
        horizon_months=60,
        discount_rate=8.0,
        line_items=[
            _cost("Purchase price", 25000),
            _cost("Installation", 1500),
            _monthly_cost("Maintenance", 150),
            _monthly_benefit("Labor savings", 700),
            _benefit("Resale value", 4000, month=60),
        ],
    )


def new_hire() -> Project:
    return Project(
        name="New hire",
        notes="A new team member. Output ramps up after training.",
        horizon_months=24,
        line_items=[
            _cost("Recruiting", 4000),
            _cost("Equipment and onboarding", 2500),
            _monthly_cost("Salary and benefits", 6000),
            _monthly_benefit("Value of added output (ramping up)", 4000, start=1, end=3),
            _monthly_benefit("Value of added output (full speed)", 8000, start=4),
        ],
    )


def software_subscription() -> Project:
    return Project(
        name="Software subscription",
        notes="A tool that saves staff time. Setup and training in the first month.",
        horizon_months=36,
        line_items=[
            _cost("Setup and training", 1200),
            _monthly_cost("Subscription", 200),
            _monthly_benefit("Staff time saved", 650, start=2),
        ],
    )


TEMPLATES: dict[str, Callable[[], Project]] = {
    "Blank": blank,
    "Event": event,
    "Marketing campaign": marketing_campaign,
    "Equipment purchase": equipment_purchase,
    "New hire": new_hire,
    "Software subscription": software_subscription,
}


def from_template(name: str) -> Project:
    try:
        factory = TEMPLATES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown template: {name}") from exc
    return factory()


def sample_projects() -> list[Project]:
    """A handful of example projects for trying the app out."""
    workshop = event()
    workshop.name = "Spring workshop"

    ads = marketing_campaign()
    ads.name = "Search ads test"

    machine = equipment_purchase()
    machine.name = "Packaging machine"

    hire = new_hire()
    hire.name = "Support specialist"

    tool = software_subscription()
    tool.name = "Scheduling software"

    stall = Project(
        name="Weekend market stall",
        notes="A side project selling handmade goods at a weekend market.",
        horizon_months=12,
        line_items=[
            _cost("Tent, table and display", 450),
            _cost("Starting materials", 300),
            _monthly_cost("Stall fee", 120),
            _monthly_cost("Materials", 180),
            _monthly_benefit("Sales", 420),
        ],
    )
    return [workshop, ads, machine, hire, tool, stall]
