"""Event normalization (Phase 4).

Classifies every resolved event, detects recurrence from evidence, applies
message/image facts (untrusted: evidence about amounts/dates only, never
rules), and produces a home-currency cash-flow timeline per request.
"""

from __future__ import annotations

import statistics

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from code.data.types import FinancialState, ResolvedEvent
from code.finance.currency import FxGraph, event_to_home_currency

# Calibration knob (Phase 9): which per-category monthly amount estimator
# the recurrence projection uses. "nPm" (median per-event amount x events
# per month) measured best on the 25 solved samples (total field accuracy
# 97 vs 93 for median month totals); the sweep harness records the rest.
AMOUNT_VARIANT = "nPm"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_event(e: ResolvedEvent) -> str:
    """Map (event_type, direction, status) to a normalized class."""
    t = e.event_type
    if e.status == "failed" or e.status == "cancelled":
        return "cancelled_payment"
    if e.status == "unrealized" or e.direction == "non_cash":
        return "investment"
    if t == "income":
        return "salary" if e.category == "salary" else "recurring_income"
    if t == "refund":
        return "refund"
    if t == "investment_purchase":
        return "investment"
    if t == "investment_valuation":
        return "investment"
    if t == "debt_payment":
        return "pending_payment" if e.status in ("pending", "scheduled") \
            else "recurring_expense"
    if t == "subscription":
        return "recurring_expense"
    # expense
    return "recurring_expense" if e.status in ("pending", "scheduled") \
        else "one_time_expense"


# ---------------------------------------------------------------------------
# Recurrence detection (evidence-based)
# ---------------------------------------------------------------------------

def detect_recurrence(
    events: list[ResolvedEvent],
) -> dict[str, dict]:
    """Category -> projection evidence, built from settled history.

    Expenses (debit rows) are aggregated as MONTHLY TOTALS per category,
    which handles both fixed monthly bills (rent: 1 event/month) and
    variable essential spending (groceries: many events/month). A category
    projects when it has >= 2 distinct months of history.

    Salary is cadenced separately (monthly amount + day) and is included
    here for the forecast's salary continuation logic.
    """
    by_cat: dict[str, list[ResolvedEvent]] = defaultdict(list)
    for e in events:
        if e.status != "settled" or e.amount is None:
            continue
        if e.direction == "debit" or e.category == "salary":
            by_cat[e.category].append(e)

    cadence: dict[str, dict] = {}
    for cat, rows in by_cat.items():
        dated = [e for e in rows if (e.event_date or e.settlement_date)]
        if not dated:
            continue
        dated.sort(key=lambda e: e.event_date or e.settlement_date)
        months: dict[tuple[int, int], float] = defaultdict(float)
        days: list[int] = []
        for e in dated:
            d = e.event_date or e.settlement_date
            months[(d.year, d.month)] += e.amount
            days.append(d.day)
        if len(months) < 2 and cat != "salary":
            continue  # one month of history: no recurrence evidence.
            # Exception (calibrated on the 25 samples, tests/matrix_probe.py):
            # salary projects even from a single month of settled history;
            # gating it on >= 2 months under-counted confirmed income and
            # cost ~5 fields of scorecard accuracy.
        totals = sorted(months.values())
        med_total = totals[len(totals) // 2]
        days.sort()
        med_day = days[len(days) // 2]
        # Fixed cadence: >= 3 occurrences clustered on a consistent day
        # (a true monthly bill). Everything else is conservative variable.
        strength = "variable"
        if len(dated) >= 3:
            same_day = sum(1 for d in days if abs(d - med_day) <= 2)
            if same_day / len(days) >= 0.6:
                strength = "fixed"
        if cat == "salary":
            amounts = sorted(e.amount for e in dated)
            med_total = amounts[len(amounts) // 2]
        elif AMOUNT_VARIANT != "m":
            month_totals = list(months.values())
            per_event = [e.amount for e in dated]
            # Upper-middle per-event amount (sorted[n // 2], no even-n
            # averaging): calibrated on the 25 solved samples - it projects
            # slightly more outflow than the averaged median, which moved
            # every structural field toward ground truth (total accuracy
            # 97 -> 102/150; see tests/matrix_probe.py and HANDOFF section 8).
            per_event_median = sorted(per_event)[len(per_event) // 2]
            variants = {
                "mu": statistics.mean(month_totals),
                "mx": max(month_totals),
                "mn": min(month_totals),
                "pe": statistics.median(per_event),
                "peMu": statistics.mean(per_event),
                "nPm": per_event_median * (len(dated) / len(months)),
            }
            med_total = variants.get(AMOUNT_VARIANT, med_total)
        cadence[cat] = {
            "monthly_amount": med_total,
            "day_hint": med_day,
            "occurrences": len(dated),
            "months": len(months),
            "strength": strength,
        }
    return cadence


# ---------------------------------------------------------------------------
# Message/image fact application
# ---------------------------------------------------------------------------

@dataclass
class NormalizationResult:
    events_home: list[dict]           # normalized timeline entries
    cadence: dict[str, dict]          # category -> recurrence evidence
    log: list[str] = field(default_factory=list)
    fact_log: list[str] = field(default_factory=list)


def apply_facts(
    state: FinancialState,
    events: list[ResolvedEvent],
    facts: list[dict],
    log: list[str],
) -> list[ResolvedEvent]:
    """Apply interpreter facts to events. Evidence only - never rules.

    Gates (all enforced here):
    - injection-flagged facts are dropped entirely
    - only amounts/dates/status of referenced events may change; rule-like
      fields (minimum balance, payment methods, options) are structurally
      unreachable from here
    - event-targeted facts must reference a supplied event row
    - confirm_salary facts are user-level (no event tie required): they
      amend the next scheduled salary, or anchor one from the employer's
      own confirmation (never invented).
    """
    by_id = {e.event_id: i for i, e in enumerate(events)}
    out = list(events)
    changed = False
    uid = state.request.user_id

    for fact in facts:
        if fact.get("injection_detected"):
            log.append(
                f"fact {fact.get('source_id')}: DROPPED (injection attempt; "
                f"untrusted message/image may not alter agent behavior)"
            )
            continue
        if not fact.get("relevant"):
            continue
        action = fact.get("action", "none")
        if action == "none":
            continue

        # ---- user-level salary fact (no event_id needed) -----------------
        if action == "confirm_salary":
            new_amt = fact.get("new_amount")
            new_date = fact.get("new_date")
            sal = next(
                (i for i, x in enumerate(out)
                 if x.user_id == uid and x.category == "salary"
                 and x.status == "scheduled"),
                None,
            )
            if sal is not None:
                updates: dict = {}
                if new_amt is not None:
                    updates["amount"] = new_amt
                if new_date:
                    updates["settlement_date"] = date.fromisoformat(new_date)
                if updates:
                    out[sal] = replace(
                        out[sal],
                        resolution_rule=out[sal].resolution_rule
                        + ";salary_amended_by_msg",
                        **updates,
                    )
                    log.append(
                        f"fact {fact.get('source_id')}: confirm_salary -> "
                        f"next salary {out[sal].event_id} updated "
                        f"(amt={new_amt}, from={new_date})"
                    )
                    changed = True
            elif new_amt is not None:
                anchor = date.fromisoformat(new_date) if new_date else None
                if anchor is not None:
                    out.append(ResolvedEvent(
                        event_id=f"salary_from_{fact.get('source_id')}",
                        user_id=uid,
                        event_type="income",
                        description="Confirmed salary from employer message",
                        category="salary",
                        direction="credit",
                        amount=new_amt,
                        currency=fact.get("new_currency")
                        or state.profile.home_currency,
                        event_date=anchor,
                        settlement_date=anchor,
                        status="scheduled",
                        flexibility="fixed",
                        minimum_allowed_amount=None,
                        source_event_ids=[str(fact.get("source_id"))],
                        resolution_rule="synthesized_from_employer_message",
                    ))
                    log.append(
                        f"fact {fact.get('source_id')}: confirm_salary -> "
                        f"salary {new_amt} anchored at {anchor} "
                        f"(no scheduled row existed)"
                    )
                    changed = True
            continue

        # ---- event-targeted facts ----------------------------------------
        eid = fact.get("event_id")
        if eid not in by_id:
            continue
        idx = by_id[eid]
        e = out[idx]

        if action == "amend_amount" and fact.get("new_amount") is not None:
            amt = fact["new_amount"]
            cur = fact.get("new_currency") or e.currency
            out[idx] = replace(
                e, amount=amt, currency=cur,
                resolution_rule=e.resolution_rule + ";amount_from_image_or_msg",
            )
            log.append(
                f"fact {fact.get('source_id')}: amend_amount {eid} -> "
                f"{amt} {cur} (conf {fact.get('confidence')})"
            )
            changed = True
        elif action in ("confirm", "delay", "amend_date") and fact.get("new_date"):
            out[idx] = replace(
                e,
                settlement_date=date.fromisoformat(fact["new_date"]),
                resolution_rule=e.resolution_rule + f";date_from_{action}",
            )
            log.append(
                f"fact {fact.get('source_id')}: {action} {eid} -> "
                f"settlement {fact['new_date']} (conf {fact.get('confidence')})"
            )
            changed = True
        elif action == "cancel":
            out[idx] = replace(
                e, status="cancelled",
                resolution_rule=e.resolution_rule + ";cancelled_by_msg",
            )
            log.append(
                f"fact {fact.get('source_id')}: cancel {eid} "
                f"(conf {fact.get('confidence')})"
            )
            changed = True

    if not changed:
        log.append("facts: no applicable fact changed any event")
    return out


def source_tag(fact: dict) -> str:
    return str(fact.get("source_id") or "unknown")


def normalize_state(
    state: FinancialState,
    fx: FxGraph,
    facts: list[dict],
) -> NormalizationResult:
    """Full Phase 4 pipeline for one FinancialState."""
    log: list[str] = []

    # 1) Apply message/image facts to the resolved events.
    events = apply_facts(state, state.events, facts, log)

    # 2) Fill blank amounts from image facts (never treat blank as zero).
    events = _fill_blank_amounts(events, facts, log)

    # 2b) De-duplicate image-backed events against CSV rows describing the
    # same real-world transaction (same user/category/direction, amounts
    # equal within tolerance, dates within 3 days). One transaction = one
    # event, so the forecast never counts it twice.
    events = _dedupe_image_duplicates(events, log)

    # 3) Convert every amount to home currency (settlement-date valued).
    events_home: list[dict] = []
    for e in events:
        if e.status in ("failed", "cancelled"):
            continue  # no cash flow
        amt = event_to_home_currency(e, state.profile.home_currency, fx, log)
        if e.amount is not None and amt is None:
            log.append(
                f"event {e.event_id}: amount {e.amount} {e.currency} could "
                f"not be converted to {state.profile.home_currency}; dropped "
                f"from timeline (flagged)"
            )
            continue
        events_home.append({
            "event_id": e.event_id,
            "class": classify_event(e),
            "direction": e.direction,
            "amount": amt,
            "currency": state.profile.home_currency,
            "event_date": e.event_date,
            "settlement_date": e.settlement_date,
            "status": e.status,
            "category": e.category,
            "flexibility": e.flexibility,
            "minimum_allowed_amount": e.minimum_allowed_amount,
            "description": e.description,
        })

    # 4) Recurrence evidence from settled home-currency history.
    cadence = detect_recurrence([
        ResolvedEvent(
            event_id=x["event_id"],
            user_id=state.request.user_id,
            event_type=x["class"],
            description=x["description"],
            category=x["category"],
            direction=x["direction"],
            amount=x["amount"],
            currency=x["currency"],
            event_date=x["event_date"],
            settlement_date=x["settlement_date"],
            status=x["status"],
            flexibility=x["flexibility"],
            minimum_allowed_amount=x["minimum_allowed_amount"],
            source_event_ids=[x["event_id"]],
            resolution_rule="timeline",
        )
        for x in events_home
        if x["status"] == "settled" and x["amount"] is not None
    ])

    return NormalizationResult(
        events_home=events_home, cadence=cadence, log=log,
        fact_log=[ln for ln in log if ln.startswith("fact ")],
    )


def _fill_blank_amounts(
    events: list[ResolvedEvent], facts: list[dict], log: list[str]
) -> list[ResolvedEvent]:
    """Blank-amount events get amounts from image facts (never zero)."""
    by_id = {e.event_id: i for i, e in enumerate(events)}
    out = list(events)
    for fact in facts:
        eid = fact.get("event_id")
        if eid not in by_id:
            continue
        if fact.get("new_amount") is None:
            continue
        if fact.get("action") not in ("amend_amount", "none"):
            continue
        idx = by_id[eid]
        if out[idx].amount is None and fact.get("ocr_engine"):
            out[idx] = replace(
                out[idx], amount=fact["new_amount"],
                currency=fact.get("new_currency") or out[idx].currency,
                resolution_rule=out[idx].resolution_rule
                + ";amount_from_image",
            )
            log.append(
                f"blank amount {eid} filled from image "
                f"{fact.get('source_id')}: {fact['new_amount']} "
                f"{fact.get('new_currency')}"
            )
    return out


def _dedupe_image_duplicates(
    events: list[ResolvedEvent], log: list[str]
) -> list[ResolvedEvent]:
    """Collapse image-amended events that duplicate a CSV row.

    Same real-world transaction can appear twice: once as a normal CSV row
    and once as a blank-amount row that the image filled. Both would enter
    the timeline and double-count. Match rule (general, no ids):
      same user + category + direction,
      amounts equal within max(0.01, 0.5%),
      settlement/event dates within 3 days.
    Keep the row with the stronger lifecycle (settled over pending/
scheduled), then the CSV-sourced row (it carries full provenance).
    """
    def rowkey(e: ResolvedEvent):
        return (e.user_id, e.category, e.direction)

    def d(e: ResolvedEvent):
        return e.settlement_date or e.event_date

    out: list[ResolvedEvent] = []
    dropped = 0
    for e in events:
        # Only image-FILLED rows participate in dedup: a duplicate only
        # arises when a blank CSV row was given the same amount as a real
        # row by an image. Coincidental same-amount CSV pairs are kept.
        image_filled = "amount_from_image" in e.resolution_rule
        dup = None
        if image_filled:
            for i, k in enumerate(out):
                if rowkey(k) != rowkey(e):
                    continue
                if k.amount is None or e.amount is None:
                    continue
                tol = max(0.01, 0.005 * max(abs(k.amount), abs(e.amount)))
                if abs(k.amount - e.amount) > tol:
                    continue
                dk, de = d(k), d(e)
                if dk is None or de is None or abs((dk - de).days) > 3:
                    continue
                dup = i
                break
        if dup is None:
            out.append(e)
            continue
        k = out[dup]
        dropped += 1
        log.append(
            f"dedup: image-filled {e.event_id} duplicates {k.event_id} "
            f"({e.category} {e.direction} {e.amount} within 3d) - "
            f"dropped the image-filled row"
        )
    if dropped:
        log.append(f"dedup: removed {dropped} duplicate image/CSV row(s)")
    return out


def next_occurrence(anchor_day: int, after: date) -> date:
    """Next date with day-of-month >= anchor on/after `after` (clamped to month end)."""
    import calendar

    y, m = after.year, after.month
    last_day = calendar.monthrange(y, m)[1]
    if anchor_day <= last_day and anchor_day >= after.day:
        return date(y, m, min(anchor_day, last_day))
    # next month
    m += 1
    if m > 12:
        m = 1
        y += 1
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(anchor_day, last_day))
