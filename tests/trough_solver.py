"""Reverse-engineer the ground-truth forecast trough.

For every sample where amount < requested (exact trough constraint:
min(path) == keep + expected_amount), enumerate include/exclude over
projected categories and salary-credit variants, and report the smallest
category sets that reproduce the implied trough exactly.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.normalizer import normalize_state
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image


def per_category_movements(norm, start: date, days: int):
    """category -> {date: signed amount} using our projection model."""
    end = start + timedelta(days=days)
    out: dict[str, dict[date, float]] = {}

    def add(cat: str, d: date, amt: float):
        if start <= d <= end:
            out.setdefault(cat, {})
            out[cat][d] = out[cat].get(d, 0.0) + amt

    # explicit scheduled/pending rows
    for ev in norm.events_home:
        d = ev["settlement_date"] or ev["event_date"]
        if d and start <= d <= end and ev["status"] in ("pending", "scheduled"):
            sign = -1.0 if ev["direction"] == "debit" else 1.0
            add("sched_" + ev["category"], d, sign * (ev["amount"] or 0.0))

    # cadence projection (skip salary here; handled separately)
    import calendar
    for cat, info in norm.cadence.items():
        if cat == "salary":
            continue
        amt = info["monthly_amount"]
        d = None
        y, m = start.year, start.month
        last = calendar.monthrange(y, m)[1]
        d = date(y, m, min(info["day_hint"], last))
        if d < start:
            m += 1
            if m > 12:
                m, y = 1, y + 1
            last = calendar.monthrange(y, m)[1]
            d = date(y, m, min(info["day_hint"], last))
        while d <= end:
            add(cat, d, -amt)
            m2 = d.month + 1
            y2 = d.year + (1 if m2 > 12 else 0)
            m2 = 1 if m2 > 12 else m2
            d = date(y2, m2, min(info["day_hint"], calendar.monthrange(y2, m2)[1]))
    return out


def salary_variants(norm, start: date, days: int):
    """List of (label, {date: amount}) credit variants."""
    import calendar
    sal = norm.cadence.get("salary")
    variants = [("nosalary", {})]
    if not sal:
        return variants
    amt = sal["monthly_amount"]
    day = sal["day_hint"]
    dates = []
    y, m = start.year, start.month
    d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
    if d < start:
        m += 1
        if m > 12:
            m, y = 1, y + 1
        d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
    end = start + timedelta(days=days)
    while d <= end:
        dates.append(d)
        m2 = d.month + 1
        y2 = d.year + (1 if m2 > 12 else 0)
        m2 = 1 if m2 > 12 else m2
        d = date(y2, m2, min(day, calendar.monthrange(y2, m2)[1]))
    for k in range(1, len(dates) + 1):
        mv = {dd: amt for dd in dates[:k]}
        variants.append((f"salary_x{k}", mv))
    return variants


def trough(opening: float, movements: dict[date, float], start: date, days: int):
    bal = opening
    mn = opening
    d = start
    for _ in range(days + 1):
        mv = movements.get(d)
        if mv:
            bal += mv
        mn = min(mn, bal)
        d += timedelta(days=1)
    return mn


def main():
    ds = DataStore()
    fx = FxGraph(ds.rates)
    n_exact = 0
    for sample in ds.samples:
        rid = sample["request_id"]
        req = ds.request_by_id(rid)
        exp = float(sample["amount_safe_to_pay"])
        if exp >= req.requested_amount - 0.005:
            continue  # capped -> only a lower bound
        n_exact += 1
        state = ds.build_state(req)
        facts = [interpret_message(m, request_id=rid) for m in state.messages]
        facts += [interpret_image(i, request_id=rid) for i in state.image_links]
        norm = normalize_state(state, fx, facts)
        p = state.profile
        target_trough = p.minimum_balance_to_keep + exp

        cat_mv = per_category_movements(norm, req.request_date, 90)
        cats = sorted(cat_mv.keys())
        sal_vars = salary_variants(norm, req.request_date, 90)

        hits = []
        # enumerate subsets (10 categories -> 1024) x salary variants
        for r in range(len(cats) + 1):
            for combo in combinations(cats, r):
                mv: dict[date, float] = {}
                for c in combo:
                    for d, a in cat_mv[c].items():
                        mv[d] = mv.get(d, 0.0) + a
                for slabel, smv in sal_vars:
                    if smv:
                        mv2 = dict(mv)
                        for d, a in smv.items():
                            mv2[d] = mv2.get(d, 0.0) + a
                    else:
                        mv2 = mv
                    t = trough(p.current_available_balance, mv2,
                               req.request_date, 90)
                    if abs(t - target_trough) <= 1.0:
                        hits.append((set(combo), slabel))
        print(f"=== {rid} target_trough={target_trough:.2f} "
              f"(exp {exp}, keep {p.minimum_balance_to_keep})")
        if not hits:
            print("   NO COMBINATION MATCHES")
            continue
        # smallest sets first
        hits.sort(key=lambda h: (len(h[0]), h[1]))
        for cats_hit, slabel in hits[:6]:
            print(f"   [{slabel}] {'+'.join(sorted(cats_hit)) or '(nothing)'}")
    print(f"\nsolved {n_exact} exact-trough samples")


if __name__ == "__main__":
    main()
