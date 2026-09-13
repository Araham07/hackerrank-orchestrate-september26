"""Exact decomposition v2: whole-unit bitset subset-sum over rich blocks.

D = (balance - keep) - expected_amount is the GT net deduction.

Blocks (whole units, + = outflow, - = inflow):
  per category x variant x k months (incl. ceil/floor/round variants)
  per settled raw event amount (single occurrence toggles)
  per-category recent 30/60-day actual totals
  global recent 30/60/90-day outflow totals
  salary credits (negative), pending credits (negative)

Run:  python tests/deduction_solver.py
"""
from __future__ import annotations

import calendar
import math
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


def add_month(d: date, day_hint: int) -> date:
    m2 = d.month + 1
    y2 = d.year + (1 if m2 > 12 else 0)
    m2 = 1 if m2 > 12 else m2
    return date(y2, m2, min(day_hint, calendar.monthrange(y2, m2)[1]))


def occurrences(day_hint: int, start: date, end: date) -> list[date]:
    y, m = start.year, start.month
    d = date(y, m, min(day_hint, calendar.monthrange(y, m)[1]))
    if d < start:
        d = add_month(d, day_hint)
    out = []
    while d <= end:
        out.append(d)
        d = add_month(d, day_hint)
    return out


def month_stats(rows):
    months = defaultdict(list)
    for d, a in rows:
        months[(d.year, d.month)].append(a)
    keys = sorted(months)
    totals = [sum(months[k]) for k in keys]
    flat = [a for _, a in rows]
    last_month = months[keys[-1]]
    last_total = totals[-1]
    last2 = totals[-2:]
    n = len(totals)
    return {
        "medTot": sorted(totals)[n // 2],
        "meanTot": sum(totals) / n,
        "minTot": min(totals),
        "maxTot": max(totals),
        "lastTot": last_total,
        "med2": (min(last2) + max(last2)) / 2,
        "peMed": sorted(flat)[len(flat) // 2],
        "peMean": sum(flat) / len(flat),
        "peLast": sorted(last_month)[len(last_month) // 2],
        "months": n,
    }


def main():
    ds = DataStore()
    fx = FxGraph(ds.rates)
    for s in ds.samples:
        rid = s["request_id"]
        req = ds.request_by_id(rid)
        exp = float(s["amount_safe_to_pay"])
        if exp >= req.requested_amount - 0.005:
            print(f"{rid}: capped -> no exact info")
            continue
        state = ds.build_state(req)
        facts = [interpret_message(m, request_id=rid) for m in state.messages]
        facts += [interpret_image(i, request_id=rid) for i in state.image_links]
        norm = normalize_state(state, fx, facts)
        p = state.profile
        start = req.request_date
        end = start + timedelta(days=90)
        keep, bal = p.minimum_balance_to_keep, p.current_available_balance
        D = (bal - keep) - exp
        if D < 0:
            print(f"{rid}: D<0 ({D:.2f}) - GT projects net INFLOW; skip")
            continue
        Dint = int(round(D))
        frac = D - Dint

        hist = defaultdict(list)
        for ev in norm.events_home:
            if ev["status"] == "settled" and ev["amount"] and ev["direction"] == "debit":
                d = ev["event_date"] or ev["settlement_date"]
                if d:
                    hist[ev["category"]].append((d, ev["amount"]))
        stats = {c: month_stats(r) for c, r in hist.items() if len(r) >= 2}

        sal_sched = [
            (ev["settlement_date"] or ev["event_date"], ev["amount"])
            for ev in norm.events_home
            if ev["class"] == "salary" and ev["status"] == "scheduled" and ev["amount"]
        ]
        sal_info = norm.cadence.get("salary")

        blocks = []  # (label, value); value>0 outflow, <0 inflow
        for c, st in stats.items():
            days_list = sorted((d.day for d, _ in hist[c]))
            med_day = days_list[len(days_list) // 2]
            n_occ = len(occurrences(med_day, start, end))
            for v in ("medTot", "meanTot", "minTot", "maxTot", "lastTot",
                      "med2", "peMed", "peMean", "peLast"):
                A = st[v]
                for k in set(range(0, min(4, n_occ) + 1)) | {n_occ}:
                    val = k * A
                    for fn, lab in ((int, "i"), (math.ceil, "c"), (round, "r")):
                        blocks.append((f"{c}:{v}x{k}{lab}", fn(val)))
        evs_sorted = sorted(
            ((ev["event_date"] or ev["settlement_date"], ev["amount"], ev["event_id"])
             for ev in norm.events_home
             if ev["status"] == "settled" and ev["amount"] and ev["direction"] == "debit"),
            reverse=True,
        )
        for d0, a, eid in evs_sorted[:40]:
            blocks.append((f"ev:{eid}", int(round(a))))
        for w, lab in ((30, "30d"), (60, "60d"), (90, "90d")):
            tot = sum(a for d0, a, _e in evs_sorted if start - timedelta(days=w) <= d0 < start)
            blocks.append((f"recent{lab}", int(round(tot))))
        for i, (d0, a) in enumerate(sal_sched):
            if start <= d0 <= end:
                blocks.append((f"schedSal{i}", -int(round(a))))
        if sal_info:
            for k in range(0, 4):
                blocks.append((f"salProj{k}", -k * int(round(sal_info["monthly_amount"]))))
        for ev in norm.events_home:
            if ev["status"] == "pending" and ev["direction"] == "credit" and ev["amount"]:
                blocks.append((f"pendCred:{ev['event_id']}", -int(round(ev["amount"]))))

        best = {}
        for lab, v in blocks:
            if v == 0:
                continue
            if v > Dint and v > 0:
                continue
            if v not in best or len(lab) < len(best[v]):
                best[v] = lab
        vals = list(best.keys())
        negs = [v for v in vals if v < 0]
        poss = [v for v in vals if v > 0]
        maxneg = sum(-v for v in negs)
        LIMIT2 = Dint + maxneg + 1
        OFF = maxneg
        mask = 1 << OFF
        for v in poss:
            if v <= Dint:
                mask |= mask << v
                mask &= (1 << LIMIT2) - 1
        for v in negs:
            mask |= mask >> (-v)
            mask &= (1 << LIMIT2) - 1
        idx = Dint + OFF
        hit = (mask >> idx) & 1
        if hit:
            print(f"{rid}: D={D:.2f} (frac {frac:.2f}) REACHABLE (blocks={len(vals)})")
        else:
            print(f"{rid}: D={D:.2f} (frac {frac:.2f}) NOT reachable (blocks={len(vals)})")


if __name__ == "__main__":
    main()
