import pytest

from app.models.project import (
    KIND_BENEFIT,
    KIND_COST,
    TIMING_MONTHLY,
    TIMING_ONE_TIME,
    LineItem,
    Project,
)
from app.services.calculator import (
    annualized_roi_percent,
    calculate,
    describe_payback,
    item_months,
    monthly_cash_flows,
    monthly_discount_rate,
    payback_month,
    roi_percent,
)


def cost(amount, month=0, name="cost"):
    return LineItem(name=name, kind=KIND_COST, amount=amount, timing=TIMING_ONE_TIME,
                    start_month=month)


def benefit(amount, month=0, name="benefit"):
    return LineItem(name=name, kind=KIND_BENEFIT, amount=amount, timing=TIMING_ONE_TIME,
                    start_month=month)


def monthly(kind, amount, start=1, end=None, name="monthly"):
    return LineItem(name=name, kind=kind, amount=amount, timing=TIMING_MONTHLY,
                    start_month=start, end_month=end)


# ----- timing ------------------------------------------------------------


def test_one_time_item_lands_in_its_month():
    project = Project(horizon_months=6, line_items=[cost(100, month=2)])
    costs, benefits = monthly_cash_flows(project)
    assert costs == [0, 0, 100, 0, 0, 0, 0]
    assert benefits == [0] * 7


def test_one_time_defaults_to_month_zero():
    item = LineItem(kind=KIND_COST, amount=50)
    assert list(item_months(item, 12)) == [0]


def test_recurring_item_repeats_from_start_to_end_inclusive():
    project = Project(horizon_months=6, line_items=[monthly(KIND_BENEFIT, 10, start=2, end=4)])
    _, benefits = monthly_cash_flows(project)
    assert benefits == [0, 0, 10, 10, 10, 0, 0]


def test_recurring_without_end_runs_to_horizon():
    project = Project(horizon_months=12, line_items=[monthly(KIND_COST, 25)])
    results = calculate(project)
    assert results.total_cost == pytest.approx(25 * 12)


def test_recurring_end_beyond_horizon_is_truncated():
    project = Project(horizon_months=3, line_items=[monthly(KIND_COST, 10, start=1, end=99)])
    assert calculate(project).total_cost == pytest.approx(30)


def test_items_outside_horizon_are_ignored_with_warning():
    late = benefit(500, month=24, name="Late")
    project = Project(horizon_months=12, line_items=[cost(100), late])
    results = calculate(project)
    assert results.total_benefit == 0
    assert any('"Late"' in w and "outside" in w for w in results.warnings)


def test_end_before_start_adds_nothing_and_warns():
    project = Project(horizon_months=12,
                      line_items=[cost(10), monthly(KIND_BENEFIT, 5, start=6, end=3, name="Odd")])
    results = calculate(project)
    assert results.total_benefit == 0
    assert any('"Odd"' in w and "ends before" in w for w in results.warnings)


def test_rows_cover_month_zero_to_horizon():
    results = calculate(Project(horizon_months=12, line_items=[cost(1)]))
    assert [row.month for row in results.rows] == list(range(13))


# ----- totals and ROI ----------------------------------------------------


def test_basic_totals_and_roi():
    project = Project(horizon_months=12, line_items=[cost(1000), benefit(1500, month=6)])
    results = calculate(project)
    assert results.total_cost == 1000
    assert results.total_benefit == 1500
    assert results.net_gain == 500
    assert results.roi_percent == pytest.approx(50.0)


def test_negative_roi():
    results = calculate(Project(line_items=[cost(1000), benefit(400)]))
    assert results.roi_percent == pytest.approx(-60.0)
    assert results.net_gain == -600


def test_zero_cost_gives_no_roi_not_a_fake_number():
    results = calculate(Project(line_items=[benefit(500)]))
    assert results.roi_percent is None
    assert results.annualized_roi_percent is None
    assert results.payback_month is None
    assert describe_payback(results) == "N/A (no costs)"
    assert any("Total cost is 0" in w for w in results.warnings)


def test_small_cost_does_not_get_floored():
    # The old code divided by max(cost, 1), which hid real ratios for small numbers.
    assert roi_percent(0.25, 0.5) == pytest.approx(50.0)
    assert roi_percent(1, 0) is None


def test_empty_project():
    results = calculate(Project())
    assert results.total_cost == 0
    assert results.roi_percent is None
    assert any("Add at least one" in w for w in results.warnings)


def test_zero_amount_item_warns():
    results = calculate(Project(line_items=[cost(100), benefit(0, name="Nothing")]))
    assert any('"Nothing"' in w and "amount of 0" in w for w in results.warnings)


# ----- payback -----------------------------------------------------------


def test_payback_month_with_recurring_benefit():
    project = Project(horizon_months=12,
                      line_items=[cost(1000), monthly(KIND_BENEFIT, 300)])
    # Cumulative: -1000, -700, -400, -100, 200
    results = calculate(project)
    assert results.payback_month == 4
    assert describe_payback(results) == "Month 4"


def test_exact_break_even_counts_as_paid_back():
    project = Project(horizon_months=12, line_items=[cost(1200), monthly(KIND_BENEFIT, 100)])
    results = calculate(project)
    assert results.net_gain == pytest.approx(0)
    assert results.payback_month == 12


def test_no_payback_within_horizon():
    project = Project(horizon_months=6, line_items=[cost(1000), monthly(KIND_BENEFIT, 100)])
    results = calculate(project)
    assert results.payback_month is None
    assert describe_payback(results) == "Not within horizon"


def test_payback_right_away():
    results = calculate(Project(line_items=[cost(100), benefit(150)]))
    assert results.payback_month == 0
    assert describe_payback(results) == "Month 0 (right away)"


def test_payback_ignores_early_positive_that_turns_negative():
    # Benefit first, then a big cost, then recovery.
    project = Project(horizon_months=6,
                      line_items=[benefit(100, 0), cost(500, 2), monthly(KIND_BENEFIT, 200, 3)])
    # Cumulative: 100, 100, -400, -200, 0, 200, 400
    assert calculate(project).payback_month == 4


def test_payback_helper_edges():
    assert payback_month([], True) is None
    assert payback_month([5, 6], False) is None
    assert payback_month([-1, 1, -1], True) is None


# ----- annualized ROI ----------------------------------------------------


def test_annualized_equals_roi_for_twelve_months():
    assert annualized_roi_percent(1500, 1000, 12) == pytest.approx(50.0)


def test_annualized_compounds_over_two_years():
    # Doubling over 24 months is about 41.42% a year.
    assert annualized_roi_percent(2000, 1000, 24) == pytest.approx(41.421356, rel=1e-6)


def test_annualized_for_short_horizon():
    # 10% over 6 months is 21% a year.
    assert annualized_roi_percent(1100, 1000, 6) == pytest.approx(21.0)


def test_annualized_total_loss_and_edges():
    assert annualized_roi_percent(0, 1000, 12) == pytest.approx(-100.0)
    assert annualized_roi_percent(100, 0, 12) is None
    assert annualized_roi_percent(100, 10, 0) is None
    assert annualized_roi_percent(1e300, 1e-300, 1) is None  # overflow is handled


# ----- NPV ---------------------------------------------------------------


def test_npv_without_discount_equals_net_gain():
    project = Project(horizon_months=12, line_items=[cost(1000), monthly(KIND_BENEFIT, 120)])
    results = calculate(project)
    assert results.npv == pytest.approx(results.net_gain)


def test_monthly_discount_rate_compounds_to_annual():
    rate = monthly_discount_rate(12.0)
    assert (1 + rate) ** 12 == pytest.approx(1.12)
    assert monthly_discount_rate(0) == 0


def test_npv_discounts_future_money():
    project = Project(horizon_months=12, discount_rate=10.0,
                      line_items=[cost(1000), benefit(1100, month=12)])
    results = calculate(project)
    # 1100 received in one year at 10% a year is worth exactly 1000 today.
    assert results.npv == pytest.approx(0.0, abs=1e-6)
    assert results.net_gain == pytest.approx(100)


def test_npv_with_recurring_benefit_matches_manual_sum():
    project = Project(horizon_months=3, discount_rate=12.0,
                      line_items=[cost(500), monthly(KIND_BENEFIT, 200)])
    r = monthly_discount_rate(12.0)
    expected = -500 + sum(200 / (1 + r) ** m for m in (1, 2, 3))
    assert calculate(project).npv == pytest.approx(expected)


def test_cumulative_rows_add_up():
    project = Project(horizon_months=4,
                      line_items=[cost(100), monthly(KIND_COST, 10), monthly(KIND_BENEFIT, 60)])
    rows = calculate(project).rows
    assert [row.net for row in rows] == [-100, 50, 50, 50, 50]
    assert [row.cumulative_net for row in rows] == [-100, -50, 0, 50, 100]
