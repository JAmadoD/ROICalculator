"""ROI calculations. Pure functions, no Qt, no I/O.

Timeline convention: month 0 is "now" (the start). A project with a horizon
of N months is evaluated over months 0, 1, ..., N.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.project import LineItem, Project

EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class MonthRow:
    month: int
    cost: float
    benefit: float
    net: float
    cumulative_net: float
    discounted_net: float


@dataclass(frozen=True, slots=True)
class ProjectResults:
    total_cost: float
    total_benefit: float
    net_gain: float
    roi_percent: float | None  # None when total cost is 0
    annualized_roi_percent: float | None
    payback_month: int | None  # None when there are no costs or no payback
    npv: float
    discount_rate: float
    horizon_months: int
    rows: list[MonthRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_costs(self) -> bool:
        return self.total_cost > EPSILON


def item_months(item: LineItem, horizon_months: int) -> range:
    """Months (within 0..horizon) in which the item has an amount."""
    if item.is_monthly:
        end = horizon_months if item.end_month is None else min(item.end_month, horizon_months)
        return range(max(item.start_month, 0), end + 1)
    if 0 <= item.start_month <= horizon_months:
        return range(item.start_month, item.start_month + 1)
    return range(0)


def monthly_cash_flows(project: Project) -> tuple[list[float], list[float]]:
    """Cost and benefit per month, as two lists of length horizon + 1."""
    horizon = project.horizon_months
    costs = [0.0] * (horizon + 1)
    benefits = [0.0] * (horizon + 1)
    for item in project.line_items:
        target = costs if item.is_cost else benefits
        for month in item_months(item, horizon):
            target[month] += item.amount
    return costs, benefits


def monthly_discount_rate(annual_percent: float) -> float:
    """Monthly rate equivalent to an annual percent rate (compounded)."""
    return (1.0 + annual_percent / 100.0) ** (1.0 / 12.0) - 1.0


def roi_percent(net_gain: float, total_cost: float) -> float | None:
    """Net gain divided by total cost, as a percent. None when cost is 0."""
    if total_cost <= EPSILON:
        return None
    return net_gain / total_cost * 100.0


def annualized_roi_percent(
    total_benefit: float, total_cost: float, horizon_months: int
) -> float | None:
    """Compound yearly rate that turns total cost into total benefit
    over the horizon: (benefit / cost) ** (12 / months) - 1.
    """
    if total_cost <= EPSILON or horizon_months <= 0:
        return None
    ratio = total_benefit / total_cost
    if ratio < 0:
        return None
    try:
        return (ratio ** (12.0 / horizon_months) - 1.0) * 100.0
    except OverflowError:
        return None


def payback_month(cumulative_net: list[float], has_costs: bool) -> int | None:
    """First month from which cumulative net stays at or above zero.

    Returns None when there are no costs (nothing to pay back) or when the
    project is still behind at the end of the horizon.
    """
    if not has_costs or not cumulative_net:
        return None
    candidate: int | None = None
    for month, value in enumerate(cumulative_net):
        if value >= -EPSILON:
            if candidate is None:
                candidate = month
        else:
            candidate = None
    return candidate


def _item_warnings(project: Project) -> list[str]:
    warnings: list[str] = []
    for item in project.line_items:
        label = item.name or "Unnamed item"
        if item.is_monthly and item.end_month is not None and item.end_month < item.start_month:
            warnings.append(f'"{label}" ends before it starts, so it adds nothing.')
        elif not item_months(item, project.horizon_months):
            warnings.append(
                f'"{label}" falls outside the {project.horizon_months} month horizon, '
                "so it is not counted."
            )
        elif item.amount <= EPSILON:
            warnings.append(f'"{label}" has an amount of 0.')
    return warnings


def calculate(project: Project) -> ProjectResults:
    """Compute every result shown for a project."""
    costs, benefits = monthly_cash_flows(project)
    monthly_rate = monthly_discount_rate(project.discount_rate)

    rows: list[MonthRow] = []
    cumulative = 0.0
    npv = 0.0
    for month, (cost, benefit) in enumerate(zip(costs, benefits, strict=True)):
        net = benefit - cost
        cumulative += net
        discounted = net / (1.0 + monthly_rate) ** month
        npv += discounted
        rows.append(MonthRow(month, cost, benefit, net, cumulative, discounted))

    total_cost = sum(costs)
    total_benefit = sum(benefits)
    net_gain = total_benefit - total_cost
    has_costs = total_cost > EPSILON

    warnings = _item_warnings(project)
    if not project.line_items:
        warnings.append("Add at least one cost and one benefit to see results.")
    elif not has_costs:
        warnings.append("Total cost is 0, so ROI and payback cannot be calculated.")

    return ProjectResults(
        total_cost=total_cost,
        total_benefit=total_benefit,
        net_gain=net_gain,
        roi_percent=roi_percent(net_gain, total_cost),
        annualized_roi_percent=annualized_roi_percent(
            total_benefit, total_cost, project.horizon_months
        ),
        payback_month=payback_month([row.cumulative_net for row in rows], has_costs),
        npv=npv,
        discount_rate=project.discount_rate,
        horizon_months=project.horizon_months,
        rows=rows,
        warnings=warnings,
    )


def describe_payback(results: ProjectResults) -> str:
    if not results.has_costs:
        return "N/A (no costs)"
    if results.payback_month is None:
        return "Not within horizon"
    if results.payback_month == 0:
        return "Month 0 (right away)"
    return f"Month {results.payback_month}"
