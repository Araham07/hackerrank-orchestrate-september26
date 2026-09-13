"""Per-sample diagnostic for amount_safe_to_pay (task: root-cause analysis).

For every solved sample, dumps:
  request/amount/keep/balance context
  ours vs expected amount + difference
  our forecast trough vs the trough implied by the expected amount
  projected cadence table (category / monthly amount / day / strength / months)
  scheduled & pending events inside the 90-day window
  simple model hypotheses vs the expected amount (H0..H6)

Run:  python tests/amount_diagnostic.py
"""
from __future__ import annotations

import calendar
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.forecast import build_movements, balance_path
from code.finance.normalizer import normalize_state
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image


def month_agg(norm, kind: str):
    """cat -> {stats} over settled history (kind: 'total' | 'event')."""
    from collections import defaultdict
    by_cat = defaultdict(lambda: defaultdict(list))
    for ev in norm.events_home:
        if ev["status"] != "settled" or ev["amount"] is None:
            continue
        if not (ev["direction"] == "debit" or ev["category"] == "salary"):
            continue
        d = ev["event_date"] or ev["settlement_date"]
        by_cat[ev["category"]][(d.year, d.month)].append(ev["amount"])
    out = {}
    for cat, months in by_cat.items():
        if len(months) < 2:
            continue
        if kind == "total":
            vals = [sum(v) for v in months.values()]
        else:
            vals = [x for v in months.values() for x in v]
        vals.sort()
        out[cat] = {
            "med": vals[len(vals) // 2],
            "mean": sum(vals) / len(vals),
            "min": vals[0],
            "max": vals[-1],
            "n": len(vals),
        }
    return out


def project_months(norm, start, days, amount_for_cat):
    """cat -> list of (date, -amount) using per-category monthly amount."""
    end = start + timedelta(days=days)
    out = {}
    for cat, info in norm.cadence.items():
        if cat == "salary":
            continue
        amt = amount_for_cat(cat)
        if amt is None:
            continue
        day = info["day_hint"]
        y, m = start.year, start.month
        d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        if d < start:
            m += 1
            if m > 12:
                m, y = 1, y + 1
            d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        rows = []
        while d <= end:
            rows.append((d, -amt))
            m2 = d.month + 1
            y2 = d.year + (1 if m2 > 12 else 0)
            m2 = 1 if m2 > 12 else m2
            d = date(y2, m2, min(day, calendar.monthrange(y2, m2)[1]))
        out[cat] = rows
    return out


def salary_dates(norm, start, days):
    """List of projected salary credit dates (cadence day), amount."""
    sal = norm.cadence.get("salary")
    if not sal:
        return []
    end = start + timedelta(days=days)
    day, amt = sal["day_hint"], sal["monthly_amount"]
    y, m = start.year, start.month
    d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
    if d < start:
        m += 1
        if m > 12:
            m, y = 1, y + 1
        d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
    rows = []
    while d <= end:
        rows.append((d, amt))
        m2 = d.month + 1
        y2 = d.year + (1 if m2 > 12 else 0)
        m2 = 1 if m2 > 12 else m2
        d = date(y2, m2, min(day, calendar.monthrange(y2, m2)[1]))
    return rows


def trough_of(opening, mv, start, days):
    bal, mn = opening, opening
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
    for sample in ds.samples:
        rid = sample["request_id"]
        req = ds.request_by_id(rid)
        exp = float(sample["amount_safe_to_pay"])
        state = ds.build_state(req)
        facts = [interpret_message(m, request_id=rid) for m in state.messages]
        facts += [interpret_image(i, request_id=rid) for i in state.image_links]
        norm = normalize_state(state, fx, facts)
        p = state.profile
        start, days = req.request_date, 90
        keep, bal = p.minimum_balance_to_keep, p.current_available_balance

        # Our engine's base movements and trough
        ours_mv = build_movements(norm, start, days)
        ours_trough = trough_of(bal, ours_mv, start, days)
        implied = keep + exp  # trough the ground truth implies

        tot = month_agg(norm, "total")
        pe = month_agg(norm, "event")

        print("=" * 100)
        print(f"{rid}  type={req.request_type}  requested={req.requested_amount}  "
              f"date={start}  deadline={req.desired_completion_date}  "
              f"partial={req.allows_partial_payment}")
        print(f"  balance={bal:.2f}  keep={keep:.2f}  naive_headroom={bal - keep:.2f}")
        print(f"  ours={min(req.requested_amount, max(0.0, ours_trough - keep)):.2f}  "
              f"expected={exp}  diff={min(req.requested_amount, max(0.0, ours_trough - keep)) - exp:+.2f}")
        print(f"  ours_trough={ours_trough:.2f}  implied_trough={implied:.2f}  "
              f"ours-implied={ours_trough - implied:+.2f}")

        # Scheduled/pending rows in window
        sched = [(ev["settlement_date"] or ev["event_date"], ev["direction"],
                  ev["amount"], ev["category"], ev["status"])
                 for ev in norm.events_home
                 if ev["status"] in ("pending", "scheduled") and ev["amount"]
                 and start <= (ev["settlement_date"] or ev["event_date"]) <= start + timedelta(days=days)]
        for d, dr, a, c, st in sorted(sched):
            sign = "-" if dr == "debit" else "+"
            print(f"  sched {d} {sign}{a:>12.2f} {c} [{st}]")

        # Cadence table + hypotheses
        proj = project_months(norm, start, days, lambda c: tot.get(c, {}).get("med"))
        sal = salary_dates(norm, start, days)
        if norm.cadence.get("salary"):
            s = norm.cadence["salary"]
            print(f"  salary cadence: monthly={s['monthly_amount']:.2f} day={s['day_hint']} "
                  f"strength={s['strength']} months={s['months']} "
                  f"credits_in_window={len(sal)}")
        print("  cadence table (cat | monthTotal med/mean | perEvent med/mean | day | strength | events):")
        for cat in sorted(norm.cadence):
            if cat == "salary":
                continue
            info = norm.cadence[cat]
            t = tot.get(cat, {})
            e = pe.get(cat, {})
            print(f"    {cat:22s} {t.get('med', 0):>12.2f} {t.get('mean', 0):>12.2f} "
                  f"{e.get('med', 0):>10.2f} {e.get('mean', 0):>10.2f} "
                  f"d{info['day_hint']:>2} {info['strength']:9s} "
                  f"{t.get('n', 0)}m/{t.get('n', 0)}")

        # H1: monthly-total medians + all salary credits
        mv1 = {}
        for rows in proj.values():
            for d, a in rows:
                mv1[d] = mv1.get(d, 0.0) + a
        for d, a in sal:
            mv1[d] = mv1.get(d, 0.0) + a
        t1 = trough_of(bal, mv1, start, days)
        # H2: per-event medians x events/month (our current nPm) + salary
        mv2 = {}
        proj2 = project_months(norm, start, days,
                               lambda c: pe.get(c, {}).get("med") * (tot.get(c, {}).get("n", 1) / max(1, len({(ev['event_date'] or ev['settlement_date']).month for ev in norm.events_home if ev['category'] == c and ev['status'] == 'settled'} or [1]))))
        for rows in proj2.values():
            for d, a in rows:
                mv2[d] = mv2.get(d, 0.0) + a
        for d, a in sal:
            mv2[d] = mv2.get(d, 0.0) + a
        t2 = trough_of(bal, mv2, start, days)
        # H3: monthly-total means + salary
        mv3 = {}
        proj3 = project_months(norm, start, days, lambda c: tot.get(c, {}).get("mean"))
        for rows in proj3.values():
            for d, a in rows:
                mv3[d] = mv3.get(d, 0.0) + a
        for d, a in sal:
            mv3[d] = mv3.get(d, 0.0) + a
        t3 = trough_of(bal, mv3, start, days)
        # H4: H1 minus salary (salary ignored entirely)
        t4 = trough_of(bal, {d: a for d, a in mv1.items()}, start, days)  # same as H1
        # H5: naive headroom (no forecast at all)
        h5 = bal - keep
        print(f"  hypotheses: H1(medTot+sal)={t1 - keep:.2f}  "
              f"H2(perEvent)={t2 - keep:.2f}  H3(meanTot+sal)={t3 - keep:.2f}  "
              f"H5(naive)={h5:.2f}  |  expected={exp:.2f}")


if __name__ == "__main__":
    main()
