"""Probe: trough under estimator variants vs implied ground-truth trough.

Variants per category: median month total (m), mean month total (mu),
max month total (mx), min month total (mn).
Salary: 0..3 credits.
Prints |trough - target| for each (variant, salary_k) combo, best first.
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.normalizer import normalize_state
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image


def month_totals(rows):
    months = defaultdict(list)
    for ev in rows:
        d = ev["event_date"] or ev["settlement_date"]
        months[(d.year, d.month)].append(ev["amount"])
    totals = {k: sum(v) for k, v in months.items()}
    return totals


def estimator_amounts(norm, start):
    """cat -> dict of variant -> monthly amount."""
    import csv
    from code.data.types import ResolvedEvent

    # Rebuild per-category event lists from the resolved rows (home currency).
    by_cat = defaultdict(list)
    for ev in norm.events_home:
        if ev["status"] == "settled" and ev["amount"] is not None and (
            ev["direction"] == "debit" or ev["category"] == "salary"
        ):
            by_cat[ev["category"]].append(ev)

    out = {}
    for cat, rows in by_cat.items():
        totals = month_totals(rows)
        if len(totals) < 2:
            continue
        vals = list(totals.values())
        per_event = [e["amount"] for e in rows]
        out[cat] = {
            "m": statistics.median(vals),
            "mu": statistics.mean(vals),
            "mx": max(vals),
            "mn": min(vals),
            "pe": statistics.median(per_event),
            "peMu": statistics.mean(per_event),
            "nPm": statistics.median(per_event) * (len(rows) / len(totals)),
        }
    return out


def project(norm, est, variant_map, start, days, salary_k):
    """Return movement dict using given per-category variant."""
    import calendar
    mv = {}

    def add(d, a):
        if start <= d <= start + timedelta(days=days):
            mv[d] = mv.get(d, 0.0) + a

    for ev in norm.events_home:
        d = ev["settlement_date"] or ev["event_date"]
        if d and start <= d <= start + timedelta(days=days) and ev["status"] in ("pending", "scheduled"):
            sign = -1.0 if ev["direction"] == "debit" else 1.0
            add(d, sign * (ev["amount"] or 0.0))

    for cat, variants in est.items():
        if cat == "salary":
            continue
        amt = variants[variant_map]
        # day hint: median day
        days_list = sorted(
            (ev["event_date"] or ev["settlement_date"]).day
            for ev in norm.events_home
            if ev["category"] == cat and ev["status"] == "settled"
        )
        day = days_list[len(days_list) // 2]
        y, m = start.year, start.month
        d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        if d < start:
            m += 1
            if m > 12:
                m, y = 1, y + 1
            d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        end = start + timedelta(days=days)
        while d <= end:
            add(d, -amt)
            m2 = d.month + 1
            y2 = d.year + (1 if m2 > 12 else 0)
            m2 = 1 if m2 > 12 else m2
            d = date(y2, m2, min(day, calendar.monthrange(y2, m2)[1]))

    sal = est.get("salary")
    if sal and salary_k:
        amt = sal["m"]
        days_list = sorted(
            (ev["event_date"] or ev["settlement_date"]).day
            for ev in norm.events_home
            if ev["category"] == "salary" and ev["status"] == "settled"
        )
        day = days_list[len(days_list) // 2]
        y, m = start.year, start.month
        d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        if d < start:
            m += 1
            if m > 12:
                m, y = 1, y + 1
            d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        end = start + timedelta(days=days)
        for _ in range(salary_k):
            if d > end:
                break
            add(d, amt)
            m2 = d.month + 1
            y2 = d.year + (1 if m2 > 12 else 0)
            m2 = 1 if m2 > 12 else m2
            d = date(y2, m2, min(day, calendar.monthrange(y2, m2)[1]))
    return mv


def trough(opening, mv, start, days):
    bal = opening
    mn = opening
    d = start
    for _ in range(days + 1):
        a = mv.get(d)
        if a:
            bal += a
        mn = min(mn, bal)
        d += timedelta(days=1)
    return mn


def main():
    ds = DataStore()
    fx = FxGraph(ds.rates)
    summary = defaultdict(int)
    for sample in ds.samples:
        rid = sample["request_id"]
        req = ds.request_by_id(rid)
        exp = float(sample["amount_safe_to_pay"])
        if exp >= req.requested_amount - 0.005:
            continue
        state = ds.build_state(req)
        facts = [interpret_message(m, request_id=rid) for m in state.messages]
        facts += [interpret_image(i, request_id=rid) for i in state.image_links]
        norm = normalize_state(state, fx, facts)
        p = state.profile
        target = p.minimum_balance_to_keep + exp
        est = estimator_amounts(norm, req.request_date)
        results = []
        for variant in ("m", "mu", "mx", "mn", "pe", "peMu", "nPm"):
            for k in range(0, 4):
                mv = project(norm, est, variant, req.request_date, 90, k)
                t = trough(p.current_available_balance, mv, req.request_date, 90)
                results.append((abs(t - target), variant, k, t))
        results.sort()
        best = results[0]
        print(f"{rid}: target {target:12.2f} | best {best[3]:12.2f} "
              f"variant={best[1]} salary_x{best[2]} err={best[0]:10.2f}")
        for err, variant, k, t in results[1:4]:
            print(f"      next: {variant} x{k} -> {t:.2f} (err {err:.2f})")
        summary[best[1]] += 1
    print("\nvariant wins:", dict(summary))


if __name__ == "__main__":
    main()
