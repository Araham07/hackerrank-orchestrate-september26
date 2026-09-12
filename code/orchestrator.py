"""Orchestrator (Phase 8) + decision explanation.

Wires Phases 2-7 into one flow per request:

    request -> FinancialState (P2) -> interpret messages/images (P3)
    -> normalize (P4) -> generate candidates (P6, which forecasts via P5)
    -> validate + rank (P7) -> output row -> explanation

Hard LLM/Python boundary: the explanation is a deterministic template over
the ALREADY-DECIDED numbers (ForecastResult, Decision, plan trail). It may
only cite figures that exist in the row or in the resolved financial state
(minimum balance, projected minimum, blocking expense, chosen date). No
LLM call can alter any number, and no number appears without a
deterministic origin (per IMPLEMENTATION_PLAN_V2 Phase 8).
"""

from __future__ import annotations

from dataclasses import dataclass

from code.data.state_builder import DataStore
from code.data.types import FinancialState
from code.finance.currency import FxGraph
from code.finance.normalizer import NormalizationResult, normalize_state
from code.finance.payment_plans import CandidatePlan, generate_candidates
from code.interpret.image_interpreter import interpret_image
from code.interpret.message_interpreter import interpret_message
from code.validate.plan_ranker import Decision, decide


@dataclass
class RequestResult:
    """Everything produced for one request (row + trace)."""

    request_id: str
    row: dict[str, str]
    decision: Decision
    state: FinancialState
    norm: NormalizationResult
    plans: list[CandidatePlan]
    trace: list[str]  # deterministic provenance per output number


def process_request(ds: DataStore, fx: FxGraph, request) -> RequestResult:
    """Full Phase 2-7 flow for one request."""
    rid = request.request_id
    trace: list[str] = []

    # P2: financial state (chain resolution happened at store build).
    state = ds.build_state(request)
    trace.append(
        f"state: {len(state.events)} resolved events, "
        f"{len(state.messages)} messages, {len(state.image_links)} image links, "
        f"{len(state.payment_options)} payment options"
    )

    # P3: untrusted-data interpreters -> fixed-shape facts.
    facts = [interpret_message(m, request_id=rid) for m in state.messages]
    facts += [interpret_image(i, request_id=rid) for i in state.image_links]
    trace.append(f"facts: {len(facts)} extracted (messages+images)")

    # P4: currency + classification + fact application.
    norm = normalize_state(state, fx, facts)
    trace.append(f"normalize: {len(norm.events_home)} home-currency timeline events")

    # P5/P6: candidate plans, each validated by the deterministic forecast.
    plans = generate_candidates(state, norm)
    eligible = sum(1 for p in plans if p.eligible and p.safe)
    trace.append(f"plans: {len(plans)} candidates, {eligible} eligible+safe")

    # P7: rank + map to the output fields.
    d = decide(state, norm, plans)
    trace.append(
        f"decision: {d.affordability_status}/{d.recommended_payment_method} "
        f"amount={d.amount_safe_to_pay}"
    )

    row = format_row(request, d, state, norm)
    trace.append("row: formatted (8 columns, spec order)")
    return RequestResult(rid, row, d, state, norm, plans, trace)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _fmt_amount(x: float) -> str:
    """Whole numbers without decimals; otherwise 2dp; no negative zeros."""
    v = round(float(x) + 0.0, 2)
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"


def format_row(
    request,
    d: Decision,
    state: FinancialState,
    norm: NormalizationResult,
) -> dict[str, str]:
    """Map a Decision to the exact required output row."""
    return {
        "request_id": request.request_id,
        "amount_safe_to_pay": _fmt_amount(d.amount_safe_to_pay),
        "affordability_status": d.affordability_status,
        "recommended_payment_method": d.recommended_payment_method,
        "payment_plan": d.payment_plan,
        "earliest_date_for_full_payment": d.earliest_date_for_full_payment or "",
        "spending_changes_needed": d.spending_changes_needed or "none",
        "decision_explanation": explain(request, d, state, norm),
    }


# ---------------------------------------------------------------------------
# Explanation (deterministic template, grounded figures only)
# ---------------------------------------------------------------------------

def _money(x: float, currency: str) -> str:
    return f"{currency} {_fmt_amount(x)}"


def explain(
    request,
    d: Decision,
    state: FinancialState,
    norm: NormalizationResult,
) -> str:
    """1-3 sentences citing only figures that appear in the row/state.

    Every clause is chosen from the already-decided Decision + the
    deterministic forecast; no generative model is involved (the plan's
    LLM/Python boundary - the LLM may phrase, never compute).
    """
    cur = state.profile.home_currency
    keep = state.profile.minimum_balance_to_keep
    parts: list[str] = []

    amt = float(d.amount_safe_to_pay)
    req_amt = float(request.requested_amount)

    if d.recommended_payment_method == "full_payment" and (
        d.affordability_status == "affordable_now"
    ):
        parts.append(f"Pay {_money(req_amt, cur)} today")
    elif d.recommended_payment_method == "partial_payment":
        first = d.winning_plan.payments[0]
        rest = req_amt - float(d.amount_safe_to_pay)
        parts.append(
            f"Pay {_money(first[1], cur)} today and the remaining "
            f"{_money(rest, cur)} on {d.earliest_date_for_full_payment}"
        )
    elif d.recommended_payment_method == "installments":
        n = len(d.winning_plan.payments)
        per = d.winning_plan.payments[0][1]
        parts.append(
            f"Pay in {n} installments of {_money(per, cur)} "
            f"(option {d.winning_plan.payment_option_id})"
        )
    elif d.recommended_payment_method == "wait":
        parts.append(
            f"Wait until {d.earliest_date_for_full_payment}, then pay "
            f"{_money(req_amt, cur)} in full"
        )
    elif d.recommended_payment_method == "not_recommended":
        parts.append(
            f"Do not proceed with this {_money(req_amt, cur)} request"
        )

    # Grounded fact clauses - each cites a real computed figure.
    if d.winning_plan is not None and d.winning_plan.forecast is not None:
        fc = d.winning_plan.forecast
        parts.append(
            f"the projected balance stays above the {_money(keep, cur)} "
            f"minimum (lowest point {_money(fc.min_balance, cur)})"
            if fc.safe
            else f"the balance would fall below the {_money(keep, cur)} "
                 f"minimum on {fc.first_breach_date}"
        )
    elif d.recommended_payment_method == "not_recommended" and amt > 0:
        parts.append(
            f"although {_money(amt, cur)} is available today, the full "
            f"amount cannot be completed safely within 90 days while "
            f"keeping {_money(keep, cur)}"
        )

    if d.spending_changes_needed and d.spending_changes_needed != "none":
        changes = d.spending_changes_needed.split("|")
        described = []
        for ch in changes:
            if ch.startswith("stop:"):
                described.append(f"stop {ch[5:]}")
            elif ch.startswith("reduce_to:"):
                bits = ch.split(":")
                described.append(f"reduce {bits[1]} to {_money(float(bits[2]), cur)}")
        parts.append("requires " + " and ".join(described))

    text = ". ".join(p[0].upper() + p[1:] if p else p for p in parts)
    if not text.endswith("."):
        text += "."
    return text
