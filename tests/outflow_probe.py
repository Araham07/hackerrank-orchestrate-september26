"""Probe D against whole-outflow formulas (not per-category paths).

D = (balance - keep) - expected_amount, per uncapped sample.

Candidate formulas:
  F1  D = total outflow of some single historical month M (all months tried)
  F2  D = trailing-W-day actual outflow (W in 7..90)
  F3  D = trailing-W outflow - k * salary
  F4  D = med/mean month total - k * salary
  F5  D = sum of category medTot/meanTot - k * salary
  F6  D = trailing-W outflow - k * salary  (W up to 90, k 0..3)

Reports, per formula family, how many samples match exactly (cent tolerance).
Run:  python tests/outflow_probe.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.normalizer import normalize_state
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image

TOL = 0.011


def main():
    ds = DataStore()
    fx = FxGraph(ds.rates)
    wins = defaultdict(list)
    for s in ds.samples:
        rid = s["request_id"]
        req = ds.request_by_id(rid)
        exp = float(s["amount_safe_to_pay"])
        if exp >= req.requested_amount - 0.005:
            continue
        state = ds.build_state(req)
        facts = [interpret_message(m, request_id=rid) for m in state.messages]
        facts += [interpret_image(i, request_id=rid) for i in state.image_links]
        norm = normalize_state(state, fx, facts)
        p = state.profile
        start = req.request_date
        keep, bal = p.minimum_balance_to_keep, p.current_available_balance
        D = (bal - keep) - exp

        # settled debits and credits with dates
        debits = [(ev["event_date"] or ev["settlement_date"], ev["amount"])
                  for ev in norm.events_home
                  if ev["status"] == "settled" and ev["amount"] and ev["direction"] == "debit"]
        salary_hist = [a for (d0, a) in
                       [(ev["event_date"] or ev["settlement_date"], ev["amount"])
                        for ev in norm.events_home
                        if ev["class"] == "salary" and ev["status"] == "settled" and ev["amount"]]]
        sal = salary_hist[-1] if salary_hist else None

        # month totals
        months = defaultdict(float)
        for d0, a in debits:
            months[(d0.year, d0.month)] += a
        month_totals = sorted(months.values())

        hits = []
        # F1: any single historical month total
        for k, (mk, tot) in enumerate(sorted(months.items())):
            if abs(tot - D) <= TOL:
                hits.append(f"F1:month#{k}({mk})")
        # F2: trailing W days (W = 1..120), no salary offset
        for W in range(1, 121):
            tot = sum(a for d0, a in debits if start - timedelta(days=W) <= d0 < start)
            if abs(tot - D) <= TOL:
                hits.append(f"F2:trail{W}")
        # F3/F6: trailing W minus k*salary
        if sal:
            for W in range(1, 121):
                tot = sum(a for d0, a in debits if start - timedelta(days=W) <= d0 < start)
                for k in (1, 2, 3):
                    if abs(tot - k * sal - D) <= TOL:
                        hits.append(f"F3:trail{W}-{k}sal")
        # F4: med/mean/min/max month total - k*salary
        if month_totals:
            n = len(month_totals)
            stats = {
                "med": sorted(month_totals)[n // 2],
                "mean": sum(month_totals) / n,
                "min": min(month_totals),
                "max": max(month_totals),
            }
            for name, v in stats.items():
                for k in (0, 1, 2, 3):
                    base = v if k == 0 or not sal else v - k * sal
                    if abs(base - D) <= TOL:
                        hits.append(f"F4:{name}-{k}sal")
        # F5: last-month total - k*sal
        if months:
            last = sorted(months.values())[-1]
            for k in (0, 1, 2):
                base = last if k == 0 or not sal else last - k * sal
                if abs(base - D) <= TOL:
                    hits.append(f"F5:last-{k}sal")
        print(f"{rid}: D={D:.2f} hits={hits if hits else 'NONE'}")
        for h in hits:
            wins[h.split(":")[0]] += 1
    print("\nfamily win counts:", dict(wins))


if __name__ == "__main__":
    main()
