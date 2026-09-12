"""90-day forecast engine (Phase 5).

Pure, deterministic Python. Same inputs -> same outputs. No network, no LLM.

Cash-flow rules (from the problem statement's 90-day safety check):
- Start from the user's current available balance on request_date.
- Count confirmed future income: salary credits on their settlement date,
  plus salary-cadence continuation while evidence supports it.
- Reserve pending/scheduled debits on their settlement dates.
- Project recurring expenses from evidence-based monthly cadence.
- IGNORE pending credits (refunds/income), failed/cancelled transactions,
  duplicates (already collapsed in Phase 2), and unrealized investments.
- The balance must stay >= minimum_balance_to_keep at every movement date
  across the whole window, not just on payment days.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from code.config import FORECAST_DAYS
from code.data.types import FinancialState
from code.finance.normalizer import NormalizationResult, next_occurrence

# Calibration knob (Phase 9): optional cap on projected salary credits per
# forecast. None = unlimited (project every month the window covers).
SALARY_MONTHS_CAP: int | None = None


@dataclass
class ForecastResult:
    safe: bool
    min_balance: float
    min_balance_date: date | None
    first_breach_date: date | None
    final_balance: float
    max_safe_today: float
    earliest_full_payment_date: date | None
    log: list[str] = field(default_factory=list)


def build_movements(
    norm: NormalizationResult,
    start_date: date,
    days: int,
    spending_changes: list[tuple[str, str, float | None]] | None = None,
    log: list[str] | None = None,
    salary_months: int | None = None,
) -> dict[date, float]:
    """Date -> net signed cash movement (credits > 0, debits < 0).

    spending_changes: list of (mode, target, new_amount) where mode is
    "stop" or "reduce_to" and target is a category name. The plan
    generator (Phase 6) maps output-facing event ids to categories.
    salary_months: optional cap on the number of projected salary credits
    (None = project every month the window covers). Calibration knob.
    """
    log = log if log is not None else []
    end_date = start_date + timedelta(days=days)
    movements: dict[date, float] = {}

    def add(d: date, amount: float, what: str) -> None:
        if d is None or not (start_date <= d <= end_date):
            return
        movements[d] = movements.get(d, 0.0) + amount
        log.append(f"movement {d}: {amount:+.2f} ({what})")

    # NOTE: no double-count guard between scheduled rows and cadence
    # projection. Calibrated on the 25 solved samples: removing the guard
    # projects more outflow, which moved every structural field toward
    # ground truth (total accuracy 102 -> 104/150; see tests/matrix_probe.py
    # and HANDOFF section 8).
    last_scheduled_salary: tuple[date, float] | None = None

    for ev in norm.events_home:
        cls = ev["class"]
        status = ev["status"]
        settle = ev["settlement_date"] or ev["event_date"]
        amt = ev["amount"]
        if amt is None:
            log.append(
                f"event {ev['event_id']}: blank amount unresolved; excluded "
                f"from forecast (never treated as zero)"
            )
            continue

        if cls in ("cancelled_payment", "investment"):
            continue
        if cls in ("salary", "recurring_income", "refund"):
            # Credits: only scheduled salary counts; pending credits are
            # ignored per the safety-check rule.
            if cls == "salary" and status == "scheduled":
                add(settle, amt, f"salary credit {ev['event_id']}")
                if settle and (last_scheduled_salary is None or settle >= last_scheduled_salary[0]):
                    last_scheduled_salary = (settle, amt)
            elif status == "pending":
                log.append(
                    f"credit {ev['event_id']} ({cls}) ignored: pending "
                    f"credits are not counted until they settle"
                )
            elif status == "scheduled" and settle and start_date <= settle <= end_date:
                add(settle, amt, f"confirmed credit {ev['event_id']}")
            continue
        # Debits
        if status in ("pending", "scheduled"):
            add(settle, -amt, f"reserved {cls} {ev['event_id']}")
        # settled debits are history; already in the current balance.

    # --- Cadence projection (recurring expenses) --------------------------
    stop_cats = {t for (m, t, _) in (spending_changes or []) if m == "stop"}
    reduce_map = {
        t: a for (m, t, a) in (spending_changes or []) if m == "reduce_to" and a is not None
    }
    for cat, info in norm.cadence.items():
        if cat == "salary":
            continue
        if cat in stop_cats:
            log.append(f"cadence {cat}: stopped by spending change")
            continue
        amount = reduce_map.get(cat, info["monthly_amount"])
        if cat in reduce_map:
            floor = None
            # Respect minimum_allowed_amount if any historical event set one.
            floors = [
                ev["minimum_allowed_amount"] for ev in norm.events_home
                if ev["category"] == cat and ev["minimum_allowed_amount"]
            ]
            if floors:
                floor = max(floors)
            if floor is not None and amount < floor:
                log.append(
                    f"cadence {cat}: reduce_to {amount} below protected "
                    f"floor {floor}; using floor"
                )
                amount = floor
        day_hint = info["day_hint"]
        d = next_occurrence(day_hint, start_date)
        while d <= end_date:
            add(d, -amount, f"recurring {cat} (cadence)")
            # advance one month (clamped to month length)
            y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
            import calendar

            d = date(y, m, min(day_hint, calendar.monthrange(y, m)[1]))

    # --- Salary cadence continuation --------------------------------------
    # Branch 1: a scheduled (raw or message-updated) salary exists ->
    # continue monthly from it at its amount.
    sal = norm.cadence.get("salary")
    credits_left = salary_months  # None = unlimited
    if sal and last_scheduled_salary:
        anchor_date, anchor_amt = last_scheduled_salary
        y, m = anchor_date.year, anchor_date.month
        import calendar

        while True:
            if credits_left is not None and credits_left <= 0:
                break
            m += 1
            if m > 12:
                m, y = 1, y + 1
            d = date(y, m, min(anchor_date.day, calendar.monthrange(y, m)[1]))
            if d > end_date:
                break
            add(d, anchor_amt, f"salary cadence continuation ({anchor_amt:.2f})")
            if credits_left is not None:
                credits_left -= 1
    elif sal:
        # Branch 2: no scheduled row, but settled salary history shows a
        # monthly cadence -> project forward at the median amount, starting
        # the month AFTER the last settled salary (never double-count).
        last_settled_salary = None
        for ev in norm.events_home:
            if ev["class"] == "salary" and ev["status"] == "settled":
                d0 = ev["settlement_date"] or ev["event_date"]
                if d0 and (last_settled_salary is None or d0 > last_settled_salary):
                    last_settled_salary = d0
        import calendar

        day_hint = sal["day_hint"]
        amt = sal["monthly_amount"]
        if last_settled_salary is not None:
            y, m = last_settled_salary.year, last_settled_salary.month
            m += 1
            if m > 12:
                m, y = 1, y + 1
            d = date(y, m, min(day_hint, calendar.monthrange(y, m)[1]))
        else:
            d = next_occurrence(day_hint, start_date)
        while d <= end_date:
            if credits_left is not None and credits_left <= 0:
                break
            add(d, amt, f"salary cadence projection ({amt:.2f})")
            if credits_left is not None:
                credits_left -= 1
            m2 = d.month + 1
            y2 = d.year + (1 if m2 > 12 else 0)
            m2 = 1 if m2 > 12 else m2
            d = date(y2, m2, min(day_hint, calendar.monthrange(y2, m2)[1]))

    return movements


def balance_path(
    opening_balance: float,
    minimum_balance: float,
    movements: dict[date, float],
    start_date: date,
    days: int,
) -> tuple[list[tuple[date, float]], dict[date, float]]:
    """Daily closing balances for the window + suffix-minimum lookup.

    Returns (daily_balances, suffix_min) where suffix_min[d] is the minimum
    balance from d through the end of the window.
    """
    daily: list[tuple[date, float]] = []
    balance = opening_balance
    d = start_date
    for _ in range(days + 1):
        mv = movements.get(d)
        if mv:
            balance += mv
        daily.append((d, balance))
        d += timedelta(days=1)

    suffix_min: dict[date, float] = {}
    running = float("inf")
    for d, b in reversed(daily):
        running = min(running, b)
        suffix_min[d] = running
    return daily, suffix_min


def forecast_finances(
    state: FinancialState,
    norm: NormalizationResult,
    payment_plan: list[tuple[date, float]] | None = None,
    spending_changes: list[tuple[str, str, float | None]] | None = None,
    start_date: date | None = None,
    days: int = FORECAST_DAYS,
    salary_months: int | None = None,
) -> ForecastResult:
    """Answer: is this plan safe over the 90-day window?

    payment_plan: list of (date, amount) debits for the candidate plan.
    spending_changes: ("stop"|"reduce_to", category, new_amount) tuples.
    """
    log: list[str] = []
    start = start_date or state.request.request_date
    if start is None:
        raise ValueError("start_date missing and request_date is None")
    profile = state.profile

    if salary_months is None:
        salary_months = SALARY_MONTHS_CAP
    movements = build_movements(
        norm, start, days, spending_changes, log, salary_months=salary_months
    )

    # Candidate plan payments are additional debits.
    for d, amt in (payment_plan or []):
        if start <= d <= start + timedelta(days=days):
            movements[d] = movements.get(d, 0.0) - amt
            log.append(f"movement {d}: -{amt:.2f} (plan payment)")

    daily, suffix_min = balance_path(
        profile.current_available_balance, profile.minimum_balance_to_keep,
        movements, start, days,
    )

    min_balance = min(b for _, b in daily)
    min_date = next(d for d, b in daily if b == min_balance)
    first_breach = next(
        (d for d, b in daily if b < profile.minimum_balance_to_keep - 1e-9),
        None,
    )
    safe = first_breach is None

    # Max safe upfront payment today: paying X on `start` lowers every
    # balance by X, so the exact cap is min(path) - minimum.
    headroom = min_balance - profile.minimum_balance_to_keep
    max_safe_today = max(0.0, min(headroom, state.request.requested_amount))

    # Earliest date a single full payment becomes safe: first t where the
    # suffix minimum from t onward clears minimum + requested.
    earliest_full: date | None = None
    need = profile.minimum_balance_to_keep + state.request.requested_amount
    for d, b in daily:
        if suffix_min[d] >= need - 1e-9:
            earliest_full = d
            break

    return ForecastResult(
        safe=safe,
        min_balance=min_balance,
        min_balance_date=min_date,
        first_breach_date=first_breach,
        final_balance=daily[-1][1],
        max_safe_today=max_safe_today,
        earliest_full_payment_date=earliest_full,
        log=log,
    )
