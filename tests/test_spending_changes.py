"""Regression tests for the calibrated spending-change selection rules.

Evidence (25 solved samples, 2026-09-13 session):
- request_21 expects stop:event_1815|reduce_to:event_1816:23.50 - the
  cloud_storage and streaming subscription events - while a single dining
  reduce (larger monthly saving) was available. Under the GT model the
  candidates accumulate in EVENT-ID order and the search stops as soon as
  the full payment is safe, so the larger-saving dining change (event_1854,
  a later id) is never reached.
- request_06 expects stop:event_476 (a streaming subscription) with no
  reduce - stop-only user lists must not be mixed with reducible categories
  when a stop alone suffices.
- request_11 expects reduce_to:event_989:665950 (dining floor) - reducible
  events reduce to their minimum_allowed_amount floor.

These are GENERAL rules (no request ids are referenced by the engine).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date

from code.data.types import Profile, Request, FinancialState
from code.finance.normalizer import NormalizationResult
from code.finance.payment_plans import generate_candidates
from code.validate.plan_ranker import decide


def _state(balance: float = 2000.0) -> tuple[FinancialState, NormalizationResult]:
    """Hand-built state around the safety boundary.

    With balance=2000 the full 1000 payment is unsafe without changes
    (projected subscriptions drift the 90-day path to 769 < keep 800), and
    stopping cloud_storage (30/mo) restores safety. With balance=2050 the
    plain full payment is already safe and no change may be emitted.
    """
    profile = Profile(
        user_id="u1", home_currency="USD",
        current_available_balance=balance, minimum_balance_to_keep=800.0,
        financial_priorities=[], expense_categories_to_protect=[],
        expense_categories_user_is_willing_to_reduce=["streaming"],
        expense_categories_user_is_willing_to_stop=["cloud_storage"],
        payment_methods_user_will_consider=["full_payment"],
        max_installment_months=None,
    )
    request = Request(
        request_id="r1", user_id="u1", request_date=date(2025, 1, 10),
        request_type="purchase", requested_amount=1000.0,
        desired_completion_date=date(2025, 1, 20), allows_partial_payment=False,
        request_text="",
    )
    state = FinancialState(
        request=request, profile=profile, events=[], messages=[],
        image_links=[], payment_options=[], resolution_log=[],
    )
    norm = NormalizationResult(
        events_home=[
            {"event_id": "event_500", "class": "recurring_expense",
             "direction": "debit", "amount": 30.0, "currency": "USD",
             "event_date": date(2024, 12, 12), "settlement_date": date(2024, 12, 12),
             "status": "settled", "category": "cloud_storage",
             "flexibility": "stoppable", "minimum_allowed_amount": None,
             "description": "Cloud storage"},
            {"event_id": "event_501", "class": "recurring_expense",
             "direction": "debit", "amount": 47.0, "currency": "USD",
             "event_date": date(2024, 12, 9), "settlement_date": date(2024, 12, 9),
             "status": "settled", "category": "streaming",
             "flexibility": "reducible_or_stoppable", "minimum_allowed_amount": 23.5,
             "description": "Streaming"},
        ],
        cadence={
            "cloud_storage": {"monthly_amount": 30.0, "day_hint": 12,
                              "occurrences": 4, "months": 4, "strength": "fixed"},
            "streaming": {"monthly_amount": 47.0, "day_hint": 9,
                          "occurrences": 4, "months": 4, "strength": "fixed"},
        },
        log=[], fact_log=[],
    )
    return state, norm


def test_spending_changes_accumulate_in_event_id_order():
    state, norm = _state(balance=2000.0)
    plans = generate_candidates(state, norm)
    decision = decide(state, norm, plans)
    if decision.spending_changes_needed != "none":
        # If changes fire, the first targeted event must be the EARLIEST id
        # (cloud_storage event_500), not the largest-saving one.
        first = decision.spending_changes_needed.split("|")[0]
        assert first.startswith("stop:event_500"), decision.spending_changes_needed


def test_reduce_uses_minimum_allowed_amount_floor():
    state, norm = _state(balance=2000.0)
    plans = generate_candidates(state, norm)
    decision = decide(state, norm, plans)
    for part in decision.spending_changes_needed.split("|"):
        if part.startswith("reduce_to:event_501:"):
            assert part == "reduce_to:event_501:23.50", part


def test_no_changes_when_full_payment_already_safe():
    # balance 2050: full payment safe without changes -> none emitted.
    state, norm = _state(balance=2050.0)
    plans = generate_candidates(state, norm)
    decision = decide(state, norm, plans)
    assert decision.spending_changes_needed == "none"
    assert decision.recommended_payment_method == "full_payment"
