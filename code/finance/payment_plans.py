"""Payment plan generator (Phase 6).

Generates every valid candidate plan for one request, each tagged with the
eligibility rules it passed/failed (the "trail" needed for ranking and
decision_explanation). Never invents schedules: installments come only
from request_payment_options.csv rows for this request_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from code.config import FORECAST_DAYS
from code.data.types import FinancialState
from code.finance.forecast import ForecastResult, forecast_finances
from code.finance.normalizer import NormalizationResult


@dataclass
class CandidatePlan:
    plan_type: str                      # full_payment | partial_payment | installments | wait | not_recommended
    payments: list[tuple[date, float]]  # chronological (date, amount)
    total_paid: float
    completes_by_deadline: bool
    requires_spending_changes: bool
    spending_changes: list[tuple[str, str, float | None]] = field(default_factory=list)
    spending_change_events: list[str] = field(default_factory=list)
    eligible: bool = True
    safe: bool = False
    forecast: ForecastResult | None = None
    trail: list[str] = field(default_factory=list)
    payment_option_id: str = ""


def _rep_event_ids_by_category(norm: NormalizationResult) -> dict[str, str]:
    """category -> representative event id (most recent settled debit).

    Includes every debit category with cadence evidence, not just
    class==recurring_expense: spending changes may target any recurring
    projected category (validated against request_06/11/21).
    """
    best: dict[str, tuple[date, str]] = {}
    for ev in norm.events_home:
        if ev["direction"] != "debit" or ev["category"] not in norm.cadence:
            continue
        if ev["status"] != "settled" or ev["amount"] is None:
            continue
        d = ev["event_date"] or ev["settlement_date"] or date.min
        cur = best.get(ev["category"])
        if cur is None or d > cur[0]:
            best[ev["category"]] = (d, ev["event_id"])
    return {cat: eid for cat, (d, eid) in best.items()}


def _flexibility_by_category(norm: NormalizationResult) -> dict[str, str]:
    """category -> the flexibility value of its settled debit rows."""
    flex: dict[str, str] = {}
    for ev in norm.events_home:
        if ev["direction"] != "debit" or ev["status"] != "settled":
            continue
        flex.setdefault(ev["category"], ev["flexibility"])
    return flex


def _min_allowed_for_category(norm: NormalizationResult) -> dict[str, float]:
    """category -> binding minimum_allowed_amount floor (max of its rows)."""
    floors: dict[str, float] = {}
    for ev in norm.events_home:
        if ev["direction"] != "debit" or ev["minimum_allowed_amount"] is None:
            continue
        cur = floors.get(ev["category"])
        if cur is None or ev["minimum_allowed_amount"] > cur:
            floors[ev["category"]] = ev["minimum_allowed_amount"]
    return floors


def generate_candidates(
    state: FinancialState,
    norm: NormalizationResult,
) -> list[CandidatePlan]:
    """All candidate plans for one request, with eligibility trails."""
    req = state.request
    profile = state.profile
    methods = profile.payment_methods_user_will_consider
    deadline = req.desired_completion_date
    plans: list[CandidatePlan] = []

    # ---------------- full_payment ----------------
    if "full_payment" in methods:
        fp = CandidatePlan(
            plan_type="full_payment",
            payments=[(req.request_date, req.requested_amount)],
            total_paid=req.requested_amount,
            completes_by_deadline=True,  # single payment on request date
            requires_spending_changes=False,
        )
        fp.trail.append("full_payment: method accepted by user")
        fc = forecast_finances(state, norm, fp.payments)
        fp.forecast = fc
        fp.safe = fc.safe
        fp.trail.append(
            f"forecast: min balance {fc.min_balance:.2f} vs keep "
            f"{profile.minimum_balance_to_keep:.2f} -> "
            f"{'SAFE' if fc.safe else 'UNSAFE (breach ' + str(fc.first_breach_date) + ')'}"
        )
        plans.append(fp)
    else:
        plans.append(_rejected("full_payment", "user does not consider full_payment"))

    # ---------------- partial_payment ----------------
    if req.allows_partial_payment and "partial_payment" in methods:
        base = forecast_finances(state, norm, [])
        cap = min(base.max_safe_today, req.requested_amount)
        # Need strict 0 < pay < requested and completion by deadline.
        if cap > 0 and cap < req.requested_amount:
            rest_date = base.earliest_full_payment_date
            rest = req.requested_amount - cap
            if rest_date is not None and deadline and rest_date <= deadline:
                pp = CandidatePlan(
                    plan_type="partial_payment",
                    payments=[(req.request_date, cap), (rest_date, rest)],
                    total_paid=req.requested_amount,
                    completes_by_deadline=True,
                    requires_spending_changes=False,
                )
                fc = forecast_finances(state, norm, pp.payments)
                pp.forecast = fc
                pp.safe = fc.safe
                pp.trail.append(
                    f"partial_payment: pay {cap:.2f} today, {rest:.2f} on "
                    f"{rest_date} (first safe full date)"
                )
                pp.trail.append(
                    f"forecast: {'SAFE' if fc.safe else 'UNSAFE'}"
                )
                plans.append(pp)
            else:
                bad = CandidatePlan(
                    plan_type="partial_payment", payments=[],
                    total_paid=req.requested_amount,
                    completes_by_deadline=False,
                    requires_spending_changes=False,
                )
                bad.eligible = False
                bad.trail.append(
                    "partial_payment rejected: earliest safe remainder date "
                    f"({rest_date}) after deadline ({deadline})"
                )
                plans.append(bad)
        else:
            bad = CandidatePlan(
                plan_type="partial_payment", payments=[],
                total_paid=req.requested_amount,
                completes_by_deadline=False, requires_spending_changes=False,
            )
            bad.eligible = False
            bad.trail.append(
                f"partial_payment rejected: safe amount today = {cap:.2f} "
                "(must be strictly between 0 and requested)"
            )
            plans.append(bad)
    else:
        plans.append(_rejected(
            "partial_payment",
            "request does not allow partial or user does not consider it",
        ))

    # ---------------- installments ----------------
    options = [o for o in state.payment_options if o.payment_method == "installments"]
    max_months = profile.max_installment_months
    if "installments" in methods and options and max_months:
        for opt in sorted(options, key=lambda o: o.payment_option_id):
            months = max(1, round(opt.number_of_payments * (opt.payment_frequency_days or 30) / 30.0))
            trail = [f"option {opt.payment_option_id}: "
                     f"{opt.number_of_payments} x {opt.payment_amount:.2f} "
                     f"from {opt.first_payment_date} every {opt.payment_frequency_days}d"]
            if months > max_months:
                trail.append(
                    f"rejected: implied {months} months > max_installment_months {max_months}"
                )
                bad = CandidatePlan(
                    plan_type="installments", payments=[], total_paid=opt.total_payable_amount,
                    completes_by_deadline=False, requires_spending_changes=False,
                    eligible=False, trail=trail, payment_option_id=opt.payment_option_id,
                )
                plans.append(bad)
                continue
            # Build the exact schedule from the option (never invented).
            schedule: list[tuple[date, float]] = []
            d = opt.first_payment_date
            for _ in range(opt.number_of_payments):
                schedule.append((d, opt.payment_amount))
                d = d + timedelta(days=opt.payment_frequency_days or 30)
            last = schedule[-1][0]
            completes = (deadline is None) or (last <= deadline)
            plan = CandidatePlan(
                plan_type="installments", payments=schedule,
                total_paid=opt.total_payable_amount,
                completes_by_deadline=completes,
                requires_spending_changes=False,
                trail=trail, payment_option_id=opt.payment_option_id,
            )
            if not completes:
                plan.eligible = False
                plan.trail.append(
                    f"rejected: last installment {last} after deadline {deadline}"
                )
            fc = forecast_finances(state, norm, schedule)
            plan.forecast = fc
            plan.safe = fc.safe
            plan.trail.append(f"forecast: {'SAFE' if fc.safe else 'UNSAFE'}")
            plans.append(plan)
    else:
        why = []
        if "installments" not in methods:
            why.append("user does not consider installments")
        if not options:
            why.append("no installment options supplied for this request")
        if not max_months:
            why.append("max_installment_months blank (user will not consider installments)")
        plans.append(_rejected("installments", "; ".join(why)))

    # ---------------- spending-change plan (full today with changes) ------
    # Ground-truth semantics (validated on request_06/11/21):
    # - reduce_to target = the event's minimum_allowed_amount (its floor),
    #   not an arbitrary percentage.
    # - action type follows the event rows' flexibility: 'stoppable' ->
    #   stop, 'reducible'/'reducible_or_stoppable' -> reduce_to floor.
    # - Multiple changes combine (max 3) until the full payment is safe;
    #   candidates are added greedily by largest monthly saving.
    reducible = set(profile.expense_categories_user_is_willing_to_reduce)
    stoppable = set(profile.expense_categories_user_is_willing_to_stop)
    protected = set(profile.expense_categories_to_protect)
    if (reducible or stoppable) and not _already_safe_full(plans):
        rep_ids = _rep_event_ids_by_category(norm)
        flex = _flexibility_by_category(norm)
        floors = _min_allowed_for_category(norm)
        actions: list[tuple[str, str, float | None, float]] = []
        for cat, eid in rep_ids.items():
            if cat in protected:
                continue
            cur = norm.cadence.get(cat, {}).get("monthly_amount")
            if cur is None or cur <= 0:
                continue
            f = flex.get(cat, "fixed")
            floor = floors.get(cat)
            if cat in stoppable and f == "stoppable":
                actions.append(("stop", cat, None, cur))
            elif (cat in reducible and f in ("reducible", "reducible_or_stoppable")
                  and floor is not None and floor < cur):
                actions.append(("reduce_to", cat, floor, cur - floor))
            elif (cat in stoppable and f == "reducible_or_stoppable"
                  and (floor is None or floor >= cur)):
                actions.append(("stop", cat, None, cur))
        # Greedy by monthly saving, descending.
        actions.sort(key=lambda a: (-a[3], a[1]))
        chosen: list[tuple[str, str, float | None, float]] = []
        best_plan: CandidatePlan | None = None
        for act in actions:
            if len(chosen) >= 3:
                break
            chosen.append(act)
            changes = [(m, c, a) for (m, c, a, _s) in chosen]
            fc = forecast_finances(
                state, norm, [(req.request_date, req.requested_amount)], changes
            )
            if fc.safe:
                ev_ids = [rep_ids.get(c, c) for (_, c, _) in changes]
                best_plan = CandidatePlan(
                    plan_type="full_payment",
                    payments=[(req.request_date, req.requested_amount)],
                    total_paid=req.requested_amount,
                    completes_by_deadline=True,
                    requires_spending_changes=True,
                    spending_changes=changes,
                    spending_change_events=ev_ids,
                )
                best_plan.forecast = fc
                best_plan.safe = True
                best_plan.trail.append(
                    "full today with spending changes: "
                    + "; ".join(f"{m}:{c}" for (m, c, _) in changes)
                )
                break
        if best_plan is not None:
            plans.append(best_plan)
        else:
            plans.append(_rejected(
                "spending_changes",
                "no permitted change combination makes full payment safe",
            ))
    else:
        plans.append(_rejected(
            "spending_changes",
            "user offers no reducible/stoppable categories or full payment already safe",
        ))

    # ---------------- wait ----------------
    if "full_payment" in methods:
        base = forecast_finances(state, norm, [])
        wait_date = base.earliest_full_payment_date
        if wait_date is not None:
            w = CandidatePlan(
                plan_type="wait",
                payments=[(wait_date, req.requested_amount)],
                total_paid=req.requested_amount,
                completes_by_deadline=(deadline is None) or (wait_date <= deadline),
                requires_spending_changes=False,
            )
            w.forecast = base
            w.safe = True
            w.trail.append(
                f"wait: full payment first safe on {wait_date} "
                f"(window {FORECAST_DAYS}d)"
            )
            if not w.completes_by_deadline:
                w.trail.append(f"note: after deadline {deadline}")
            plans.append(w)
        else:
            plans.append(_rejected(
                "wait", "full payment never becomes safe within the 90-day window",
            ))
    else:
        plans.append(_rejected(
            "wait", "user does not consider full_payment, so waiting is not valid",
        ))

    return plans


def _already_safe_full(plans: list[CandidatePlan]) -> bool:
    return any(
        p.plan_type == "full_payment" and p.eligible and p.safe
        for p in plans
    )


def _rejected(plan_type: str, why: str) -> CandidatePlan:
    p = CandidatePlan(
        plan_type=plan_type, payments=[], total_paid=0.0,
        completes_by_deadline=False, requires_spending_changes=False,
        eligible=False,
    )
    p.trail.append(f"{plan_type} rejected: {why}")
    return p
