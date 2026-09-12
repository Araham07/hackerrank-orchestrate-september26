"""Probe: does the double-count guard explain the trough gap?

Our pipeline skips cadence projection for (category, month) pairs that
already have an explicit scheduled/pending debit row. If ground truth does
NOT skip (double-counts), its projected outflow is strictly higher and its
troughs lower - the observed direction on most mismatched samples.

Monkeypatches forecast.build_movements with the guard disabled and measures
the full pipeline. Pure measurement: changes nothing.
"""

from __future__ import annotations

import calendar
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import code.finance.forecast as forecast_mod
from code.finance.normalizer import next_occurrence
from tests.sample_scorecard import field_scores, run_sample


def build_movements_no_guard(
    norm, start_date, days, spending_changes=None, log=None, salary_months=None
):
    """Copy of build_movements with scheduled_debit_months guard removed."""
    log = log if log is not None else []
    end_date = start_date + __import__("datetime").timedelta(days=days)
    movements = {}

    def add(d, amount, what):
        if d is None or not (start_date <= d <= end_date):
            return
        movements[d] = movements.get(d, 0.0) + amount
        log.append(f"movement {d}: {amount:+.2f} ({what})")

    last_scheduled_salary = None
    for ev in norm.events_home:
        cls = ev["class"]
        status = ev["status"]
        settle = ev["settlement_date"] or ev["event_date"]
        amt = ev["amount"]
        if amt is None:
            continue
        if cls in ("cancelled_payment", "investment"):
            continue
        if cls in ("salary", "recurring_income", "refund"):
            if cls == "salary" and status == "scheduled":
                add(settle, amt, f"salary credit {ev['event_id']}")
                if settle and (
                    last_scheduled_salary is None
                    or settle >= last_scheduled_salary[0]
                ):
                    last_scheduled_salary = (settle, amt)
            elif status == "pending":
                pass
            elif status == "scheduled" and settle and start_date <= settle <= end_date:
                add(settle, amt, f"confirmed credit {ev['event_id']}")
            continue
        if status in ("pending", "scheduled"):
            add(settle, -amt, f"reserved {cls} {ev['event_id']}")
            # NOTE: no scheduled_debit_months bookkeeping -> cadence will
            # ALSO project this category every month (double-count).

    stop_cats = {t for (m, t, _) in (spending_changes or []) if m == "stop"}
    reduce_map = {
        t: a for (m, t, a) in (spending_changes or [])
        if m == "reduce_to" and a is not None
    }
    for cat, info in norm.cadence.items():
        if cat == "salary":
            continue
        if cat in stop_cats:
            continue
        amount = reduce_map.get(cat, info["monthly_amount"])
        if cat in reduce_map:
            floors = [
                ev["minimum_allowed_amount"] for ev in norm.events_home
                if ev["category"] == cat and ev["minimum_allowed_amount"]
            ]
            if floors:
                amount = max(amount, max(floors))
        d = next_occurrence(info["day_hint"], start_date)
        while d <= end_date:
            add(d, -amount, f"recurring {cat} (cadence, no guard)")
            y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
            d = __import__("datetime").date(
                y, m, min(info["day_hint"], calendar.monthrange(y, m)[1])
            )

    sal = norm.cadence.get("salary")
    credits_left = salary_months
    if sal and last_scheduled_salary:
        anchor_date, anchor_amt = last_scheduled_salary
        y, m = anchor_date.year, anchor_date.month
        while True:
            if credits_left is not None and credits_left <= 0:
                break
            m += 1
            if m > 12:
                m, y = 1, y + 1
            d = __import__("datetime").date(
                y, m, min(anchor_date.day, calendar.monthrange(y, m)[1])
            )
            if d > end_date:
                break
            add(d, anchor_amt, "salary cadence continuation")
            if credits_left is not None:
                credits_left -= 1
    elif sal:
        last_settled = None
        for ev in norm.events_home:
            if ev["class"] == "salary" and ev["status"] == "settled":
                d0 = ev["settlement_date"] or ev["event_date"]
                if d0 and (last_settled is None or d0 > last_settled):
                    last_settled = d0
        day_hint = sal["day_hint"]
        amt = sal["monthly_amount"]
        if last_settled is not None:
            y, m = last_settled.year, last_settled.month
            m += 1
            if m > 12:
                m, y = 1, y + 1
            d = __import__("datetime").date(
                y, m, min(day_hint, calendar.monthrange(y, m)[1])
            )
        else:
            d = next_occurrence(day_hint, start_date)
        while d <= end_date:
            if credits_left is not None and credits_left <= 0:
                break
            add(d, amt, "salary cadence projection")
            if credits_left is not None:
                credits_left -= 1
            m2 = d.month + 1
            y2 = d.year + (1 if m2 > 12 else 0)
            m2 = 1 if m2 > 12 else m2
            d = __import__("datetime").date(
                y2, m2, min(day_hint, calendar.monthrange(y2, m2)[1])
            )
    return movements


def main():
    from code.data.state_builder import DataStore
    from code.finance.currency import FxGraph

    ds = DataStore()
    fx = FxGraph(ds.rates)
    original = forecast_mod.build_movements

    for label, fn in (("guard=ON (base)", original),
                      ("guard=OFF (double-count)", build_movements_no_guard)):
        forecast_mod.build_movements = fn
        rows = []
        for sample in ds.samples:
            try:
                rows.append({
                    "request_id": sample["request_id"],
                    "ours": run_sample(ds, fx, sample),
                    "exp": sample,
                })
            except Exception as exc:  # noqa: BLE001
                rows.append({
                    "request_id": sample["request_id"],
                    "ours": None, "exp": sample,
                })
                print(f"  [ERR] {sample['request_id']}: {exc}")
        s = field_scores(rows)
        n = s["_n"]
        total = sum(s[k] for k in s if k != "_n")
        print(f"{label:28s} -> status={s['affordability_status']} "
              f"method={s['recommended_payment_method']} "
              f"amount={s['amount_safe_to_pay']} "
              f"plan={s['payment_plan']} "
              f"earliest={s['earliest_date_for_full_payment']} "
              f"changes={s['spending_changes_needed']} "
              f"total={total}/{6 * n}")

    forecast_mod.build_movements = original


if __name__ == "__main__":
    main()
