"""Unit tests for Phases 4-7: currency, forecast, plans, ranking."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date

from code.finance.currency import FxGraph
from code.finance.forecast import build_movements, balance_path, forecast_finances
from code.validate.plan_ranker import rank_plans
from code.finance.payment_plans import CandidatePlan


# ---------------------------------------------------------------------------
# Phase 4: currency
# ---------------------------------------------------------------------------

def test_fx_directional_direct_pair():
    rates = {(date(2025, 1, 15), "USD", "INR"): 83.0}
    fx = FxGraph(rates)
    assert fx.convert(2.0, "USD", "INR", date(2025, 1, 15)) == 166.0


def test_fx_multi_hop_composition():
    rates = {
        (date(2025, 1, 15), "USD", "EUR"): 0.9,
        (date(2025, 1, 15), "EUR", "ZAR"): 20.0,
    }
    fx = FxGraph(rates)
    assert fx.convert(2.0, "USD", "ZAR", date(2025, 1, 15)) == 36.0


def test_fx_nearest_earlier_date_fallback_is_logged():
    rates = {(date(2025, 1, 15), "USD", "INR"): 83.0}
    fx = FxGraph(rates)
    log = []
    v = fx.convert(1.0, "USD", "INR", date(2025, 1, 20), log)
    assert v == 83.0
    assert any("nearest earlier" in x for x in log)


def test_fx_no_path_returns_none():
    rates = {(date(2025, 1, 15), "USD", "EUR"): 0.9}
    fx = FxGraph(rates)
    log = []
    assert fx.convert(1.0, "USD", "IDR", date(2025, 1, 15), log) is None
    assert any("NO conversion path" in x for x in log)


# ---------------------------------------------------------------------------
# Phase 5: forecast (hand-verified case)
# ---------------------------------------------------------------------------

def _movement_state(bal, keep, rent, salary_amt, salary_day, request_day, amount):
    """Hand-built FinancialState + NormalizationResult for forecast tests."""
    from code.data.types import Profile, Request, FinancialState
    from code.finance.normalizer import NormalizationResult

    profile = Profile(
        user_id="u1", home_currency="USD",
        current_available_balance=bal, minimum_balance_to_keep=keep,
        financial_priorities=[], expense_categories_to_protect=[],
        expense_categories_user_is_willing_to_reduce=[],
        expense_categories_user_is_willing_to_stop=[],
        payment_methods_user_will_consider=["full_payment"],
        max_installment_months=None,
    )
    request = Request(
        request_id="r1", user_id="u1", request_date=request_day,
        request_type="purchase", requested_amount=amount,
        desired_completion_date=request_day, allows_partial_payment=False,
        request_text="",
    )
    state = FinancialState(
        request=request, profile=profile, events=[], messages=[],
        image_links=[], payment_options=[], resolution_log=[],
    )
    cadence = {
        "salary": {"monthly_amount": salary_amt, "day_hint": salary_day,
                   "occurrences": 4, "months": 4, "strength": "fixed"},
        "rent": {"monthly_amount": rent, "day_hint": 1, "occurrences": 4,
                 "months": 4, "strength": "fixed"},
    }
    norm = NormalizationResult(events_home=[], cadence=cadence, log=[], fact_log=[])
    return state, norm


def test_forecast_safe_with_known_rent_and_salary():
    # Balance 3000, keep 500, rent 1000 on the 1st, salary 2000 on the 15th.
    # Request 800 on Jan 10 2025: pays 800; path dips only via rent.
    state, norm = _movement_state(
        3000, 500, 1000, 2000, 15, date(2025, 1, 10), 800
    )
    res = forecast_finances(state, norm, [(date(2025, 1, 10), 800)])
    # Jan 10: 3000-800=2200; Jan 15: +2000=4200; Feb 1: -1000=3200;
    # Feb 15: +2000; Mar 1: -1000; ... min is 2200 (or after later rents).
    assert res.safe is True
    assert res.min_balance >= 500
    assert res.max_safe_today >= 800


def test_forecast_unsafe_when_payment_breaks_minimum():
    state, norm = _movement_state(
        1200, 500, 1000, 2000, 15, date(2025, 1, 10), 800
    )
    res = forecast_finances(state, norm, [(date(2025, 1, 10), 800)])
    # After paying 800 on Jan 10, balance 400 < 500 minimum -> unsafe.
    assert res.safe is False
    assert res.first_breach_date == date(2025, 1, 10)


def test_max_safe_today_is_exact_headroom():
    state, norm = _movement_state(
        3000, 500, 1000, 2000, 15, date(2025, 1, 10), 1000
    )
    res = forecast_finances(state, norm, [])
    # No plan payment: min path = 3000 - 3 rents (Feb/Mar/Apr 1) + 3 salaries
    # (Jan 15, Feb 15, Mar 15) = 3000 + 6000 - 3000 = 6000 -> headroom 5500,
    # capped at requested 1000.
    assert res.max_safe_today == 1000.0


def test_max_safe_today_capped_by_window_minimum():
    state, norm = _movement_state(
        3000, 500, 1800, 2000, 15, date(2025, 1, 10), 5000
    )
    res = forecast_finances(state, norm, [])
    # Path: Jan 10: 3000 (opening, window minimum); Jan 15: +2000 = 5000;
    # Feb 1: -1800 = 3200; Feb 15: 5200; Mar 1: 3400; Mar 15: 5400;
    # Apr 1: 3600. Salary lands before the first in-window rent, so the
    # minimum is the opening 3000 -> headroom 2500.
    assert abs(res.max_safe_today - 2500.0) < 1e-6


def test_max_safe_today_dips_below_opening_when_rent_comes_first():
    # Rent on the 11th lands before any salary: the window minimum drops
    # below the opening balance, capping the safe amount.
    state, norm = _movement_state(
        3000, 500, 1800, 2000, 15, date(2025, 1, 10), 5000
    )
    # Shift the rent anchor to day 11 by overriding cadence.
    norm.cadence["rent"]["day_hint"] = 11
    res = forecast_finances(state, norm, [])
    # Path: Jan 10: 3000; Jan 11: 1200; Jan 15: 3200; Feb 11: 1400;
    # Feb 15: 3400; Mar 11: 1600; Mar 15: 3600; Apr 11: 1800.
    # Min 1200 -> headroom 700.
    assert abs(res.max_safe_today - 700.0) < 1e-6


# ---------------------------------------------------------------------------
# Phase 6/7: ranking order (synthetic candidates)
# ---------------------------------------------------------------------------

def _plan(**kw):
    base = dict(
        plan_type="full_payment",
        payments=[(date(2025, 1, 10), 100.0)],
        total_paid=100.0,
        completes_by_deadline=True,
        requires_spending_changes=False,
        eligible=True, safe=True,
        payment_option_id="",
    )
    base.update(kw)
    return CandidatePlan(**base)


def test_ranker_prefers_deadline_completion_first():
    on_time = _plan(total_paid=200.0)
    late = _plan(plan_type="wait", payments=[(date(2025, 2, 1), 100.0)],
                 completes_by_deadline=False, total_paid=100.0)
    ranked = rank_plans([late, on_time])
    assert ranked[0] is on_time


def test_ranker_prefers_no_spending_changes_second():
    clean = _plan(total_paid=200.0)
    with_changes = _plan(total_paid=100.0, requires_spending_changes=True)
    ranked = rank_plans([with_changes, clean])
    assert ranked[0] is clean


def test_ranker_prefers_cheaper_third():
    cheap = _plan(total_paid=100.0)
    pricey = _plan(total_paid=200.0)
    ranked = rank_plans([pricey, cheap])
    assert ranked[0] is cheap


def test_ranker_final_tiebreak_is_option_id():
    a = _plan(payment_option_id="payment_option_01", total_paid=100.0)
    b = _plan(payment_option_id="payment_option_02", total_paid=100.0)
    ranked = rank_plans([b, a])
    assert ranked[0] is a


def test_ranker_drops_ineligible_and_unsafe():
    good = _plan()
    bad = _plan(eligible=False)
    unsafe = _plan(safe=False)
    ranked = rank_plans([bad, unsafe, good])
    assert ranked == [good]
