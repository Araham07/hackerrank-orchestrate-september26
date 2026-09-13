"""Round 3 probes (last resort before declaring the model unidentifiable).

P1: D = calendar-month-anchored outflow sums (MTD, last month, MTD+last,
    last-2-months, W-full-months back) +- k*salary.
P2: trough-definition probe on OUR projection: is keep+exp equal to
    min over (daily | month-end | salary-day | week-end) balances?

Run:  python tests/model_probe3.py
"""
from __future__ import annotations

import calendar
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.normalizer import normalize_state
from code.finance.forecast import build_movements, balance_path
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image

TOL = 0.011


def prev_month(d: date) -> date:
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)


def main():
    ds = DataStore()
    fx = FxGraph(ds.rates)
    p1_wins = defaultdict(int)
    p2_hits = defaultdict(int)
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

        debits = [(ev["event_date"] or ev["settlement_date"], ev["amount"])
                  for ev in norm.events_home
                  if ev["status"] == "settled" and ev["amount"] and ev["direction"] == "debit"]
        salary = sorted(
            ((ev["event_date"] or ev["settlement_date"]), ev["amount"])
            for ev in norm.events_home
            if ev["class"] == "salary" and ev["status"] == "settled" and ev["amount"]
        )
        sal_amt = salary[-1][1] if salary else None

        # ---- P1: calendar-month-anchored sums ----
        months = defaultdict(float)
        for d0, a in debits:
            months[(d0.year, d0.month)] += a
        cur, last, last2, last3 = prev_month(start), prev_month(prev_month(start)), None, None
        mtd = months.get((cur.year, cur.month), 0.0)
        m_last = months.get((last.year, last.month), 0.0)
        if last2 is None:
            lp = prev_month(last)
            last2 = (lp.year, lp.month)
            m_last2 = months.get(last2, 0.0)
            lpp = prev_month(lp)
            m_last3 = months.get((lpp.year, lpp.month), 0.0)
        cands = {
            "mtd": mtd,
            "m_last": m_last,
            "mtd+m_last": mtd + m_last,
            "m_last2": m_last2,
            "m_last3": m_last3,
            "m_last+m_last2": m_last + m_last2,
        }
        for name, v in cands.items():
            for k in (0, 1, 2):
                base = v if (k == 0 or sal_amt is None) else v - k * sal_amt
                if abs(base - D) <= TOL:
                    p1_wins[f"{name}-{k}sal"] += 1

        # ---- P2: trough-definition probe on our projection ----
        mv = build_movements(norm, start, 90)
        daily, suff = balance_path(bal, keep, mv, start, 90)
        by_d = dict(daily)
        sal_info = norm.cadence.get("salary")
        sal_day = sal_info["day_hint"] if sal_info else 15
        sal_days = []
        d = start
        y, m = start.year, start.month
        dd = date(y, m, min(sal_day, calendar.monthrange(y, m)[1]))
        if dd < start:
            m += 1
            dd = date(dd.year + (1 if m > 12 else 0), 1 if m > 12 else m,
                      min(sal_day, calendar.monthrange(dd.year + (1 if m > 12 else 0), 1 if m > 12 else m)[1]))
        while dd <= start + timedelta(days=90):
            sal_days.append(dd)
            m2 = dd.month + 1
            y2 = dd.year + (1 if m2 > 12 else 0)
            m2 = 1 if m2 > 12 else m2
            dd = date(y2, m2, min(sal_day, calendar.monthrange(y2, m2)[1]))
        month_ends = []
        d = start
        while d <= start + timedelta(days=90):
            last_day = calendar.monthrange(d.year, d.month)[1]
            me = date(d.year, d.month, last_day)
            if me >= start:
                month_ends.append(me)
            d = date(d.year + (1 if d.month == 12 else 0), 1 if d.month == 12 else d.month + 1, 1)
        defs = {
            "daily_min": min(b for _, b in daily),
            "salaryday_min": min((by_d[dd] for dd in sal_days if dd in by_d), default=None),
            "monthend_min": min((by_d[me] for me in month_ends if me in by_d), default=None),
            "opening": bal,
        }
        for name, val in defs.items():
            if val is None:
                continue
            if abs((val - keep) - exp) <= TOL:
                p2_hits[name] += 1
        print(f"{rid}: D={D:.2f} p1_hits={[k for k in cands for k2 in (0,1,2) if abs((cands[k] - (0 if k2==0 or sal_amt is None else k2*sal_amt)) - D) <= TOL]}")
    print("\nP1 (calendar-month sums) family wins:", dict(p1_wins))
    print("P2 (trough definitions on OUR path) hits:", dict(p2_hits))


if __name__ == "__main__":
    main()
