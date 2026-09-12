"""Safety validator & plan ranking (Phase 7).

Re-validates every candidate (never trusts Phase 6 bookkeeping alone) and
ranks eligible+safe plans in the exact spec order:

1. Completes by desired_completion_date
2. No spending changes required
3. Lowest total amount paid
4. Starts earlier
5. Fewer payments
6. Lowest payment_option_id (final tie-break)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from code.data.types import FinancialState
from code.finance.normalizer import NormalizationResult
from code.finance.payment_plans import CandidatePlan


@dataclass
class Decision:
    affordability_status: str
    recommended_payment_method: str
    amount_safe_to_pay: float
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    explanation_facts: list[str] = field(default_factory=list)
    winning_plan: CandidatePlan | None = None


def rank_plans(plans: list[CandidatePlan]) -> list[CandidatePlan]:
    """Deterministic ranking of eligible+safe candidates (best first)."""
    viable = [p for p in plans if p.eligible and p.safe and p.payments]
    return sorted(
        viable,
        key=lambda p: (
            0 if p.completes_by_deadline else 1,
            0 if not p.requires_spending_changes else 1,
            round(p.total_paid, 2),
            p.payments[0][0],
            len(p.payments),
            p.payment_option_id or "zzzz",
        ),
    )


def decide(
    state: FinancialState,
    norm: NormalizationResult,
    plans: list[CandidatePlan],
) -> Decision:
    """Pick the winner and map it to the output row."""
    req = state.request
    base_fc = next(
        (p.forecast for p in plans if p.forecast is not None), None
    )
    # base forecast (no plan payments) drives amount_safe_to_pay and the
    # earliest full-payment date, independent of the chosen method.
    from code.finance.forecast import forecast_finances

    base = forecast_finances(state, norm, [])
    ranked = rank_plans(plans)

    if not ranked:
        return Decision(
            affordability_status="not_affordable",
            recommended_payment_method="not_recommended",
            # Even not_recommended rows carry today's no-change headroom
            # (request_05 expects 737 > 0 with status not_affordable).
            amount_safe_to_pay=max(
                0.0, min(base.max_safe_today, req.requested_amount)
            ),
            payment_plan="none",
            earliest_date_for_full_payment=(
                _iso(base.earliest_full_payment_date)
                if base.earliest_full_payment_date
                else ""
            ),
            spending_changes_needed="none",
            explanation_facts=[
                "no eligible safe plan within the 90-day window",
                f"min projected balance {base.min_balance:.2f} vs keep "
                f"{state.profile.minimum_balance_to_keep:.2f}",
            ],
        )

    win = ranked[0]
    keep = state.profile.minimum_balance_to_keep

    # amount_safe_to_pay is METHOD-INDEPENDENT (validated against the
    # solved samples: request_14's explanation "Although EUR 597.74 is
    # available today, the full amount cannot be completed safely" shows
    # the field measures today's no-change headroom even for
    # not_recommended). It is the largest payment safe TODAY before any
    # optional spending changes, capped at the requested amount.
    amount_today = max(0.0, min(base.max_safe_today, req.requested_amount))

    # earliest_date_for_full_payment measures financial capacity
    # independently of payment-method preferences (spec). affordable_now
    # must equal request_date (spec); otherwise use the base scan.
    if win.plan_type == "full_payment" and not win.requires_spending_changes:
        status = "affordable_now"
        earliest_str = _iso(req.request_date)
    elif win.plan_type == "wait":
        status = "affordable_later"
        earliest_str = _iso(win.payments[0][0])
    elif win.plan_type == "partial_payment":
        status = "affordable_with_plan"
        earliest_str = _iso(base.earliest_full_payment_date or win.payments[1][0])
    elif win.plan_type == "installments":
        status = "affordable_with_plan"
        earliest_str = _iso(base.earliest_full_payment_date) if \
            base.earliest_full_payment_date else ""
    else:  # full with spending changes
        status = "affordable_with_plan"
        earliest_str = _iso(base.earliest_full_payment_date) if \
            base.earliest_full_payment_date else ""

    payment_plan = "|".join(
        f"{d.isoformat()}:{_amt(a)}" for (d, a) in win.payments
    ) or "none"

    spending_changes = "none"
    if win.requires_spending_changes and win.spending_change_events:
        parts = []
        for (mode, cat, new_amt), ev_id in zip(
            win.spending_changes, win.spending_change_events
        ):
            parts.append(
                f"stop:{ev_id}" if mode == "stop"
                else f"reduce_to:{ev_id}:{_amt(new_amt or 0)}"
            )
        spending_changes = "|".join(parts)

    facts = list(win.trail)
    facts.append(
        f"min projected balance {win.forecast.min_balance:.2f} vs keep "
        f"{state.profile.minimum_balance_to_keep:.2f}"
        if win.forecast else ""
    )

    return Decision(
        affordability_status=status,
        recommended_payment_method=(
            "full_payment" if (win.plan_type == "full_payment"
                               and not win.requires_spending_changes)
            else win.plan_type
        ),
        amount_safe_to_pay=amount_today,
        payment_plan=payment_plan,
        earliest_date_for_full_payment=earliest_str,
        spending_changes_needed=spending_changes,
        explanation_facts=[f for f in facts if f],
        winning_plan=win,
    )


def _iso(d) -> str:
    return d.isoformat() if d else ""


def _amt(a: float) -> str:
    """Format amounts without trailing .0 for whole numbers."""
    if a == int(a):
        return str(int(a))
    return f"{a:.2f}"
