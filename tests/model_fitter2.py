"""Constraint-guided model fitter (round 2).

Scoring uses TWO constraints per uncapped sample:
  C1  trough == keep + expected_amount            (scalar, tol 0.02)
  C2  earliest date where suffix-min >= keep + requested equals the GT
      earliest_date_for_full_payment (date equality when GT supplies one)

Model space (axes the round-1 fitter did not combine):
  amount:  medTot meanTot minTot lastTot med2 peMed peMean peUp peLast
  timing:  dayhint day1 wk_dh daily_dim daily_30 salday
  scope:   all fixedOnly varOnly strength:fixed strength:variable
  salary:  proj (cadence) sched (scheduled rows only) both none
  pending credits: never / in-window

Run:  python tests/model_fitter2.py
"""
from __future__ import annotations

import calendar
import sys
from collections import defaultdict
from datetime import date, timedelta
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.normalizer import normalize_state
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image

TOL = 0.02

AMOUNTS = ("medTot", "meanTot", "minTot", "lastTot", "med2",
           "peMed", "peMean", "peUp", "peLast")
TIMINGS = ("dayhint", "day1", "wk_dh", "daily_dim", "daily_30", "salday")
SCOPES = ("all", "fixedOnly", "varOnly", "sFixed", "sVar")
SALARY = ("proj", "sched", "both", "none")
PENDC = ("no", "yes")

VARIABLE_CATS = {"groceries", "transport", "dining", "shopping", "entertainment"}


def add_month(d: date, day_hint: int) -> date:
    m2 = d.month + 1
    y2 = d.year + (1 if m2 > 12 else 0)
    m2 = 1 if m2 > 12 else m2
    return date(y2, m2, min(day_hint, calendar.monthrange(y2, m2)[1]))


def month_stats(rows):
    months = defaultdict(list)
    for d, a in rows:
        months[(d.year, d.month)].append(a)
    keys = sorted(months)
    totals = [sum(months[k]) for k in keys]
    flat = [a for _, a in rows]
    n = len(totals)
    last2 = totals[-2:]
    return {
        "medTot": sorted(totals)[n // 2],
        "meanTot": sum(totals) / n,
        "minTot": min(totals),
        "maxTot": max(totals),
        "lastTot": totals[-1],
        "med2": (min(last2) + max(last2)) / 2,
        "peMed": sorted(flat)[len(flat) // 2],
        "peMean": sum(flat) / len(flat),
        "peUp": flat[len(flat) // 2],
        "peLast": sorted(months[keys[-1]])[len(months[keys[-1]]) // 2],
        "months": n,
        "strength": "fixed" if not (set(c for _, c in rows) & VARIABLE_CATS) else "variable",
    }


def main():
    ds = DataStore()
    fx = FxGraph(ds.rates)

    cache = []
    for s in ds.samples:
        rid = s["request_id"]
        req = ds.request_by_id(rid)
        exp = float(s["amount_safe_to_pay"])
        gt_earliest = s.get("earliest_date_for_full_payment") or None
        state = ds.build_state(req)
        facts = [interpret_message(m, request_id=rid) for m in state.messages]
        facts += [interpret_image(i, request_id=rid) for i in state.image_links]
        norm = normalize_state(state, fx, facts)
        p = state.profile
        start = req.request_date
        end = start + timedelta(days=90)

        hist = defaultdict(list)
        for ev in norm.events_home:
            if ev["status"] == "settled" and ev["amount"] and ev["direction"] == "debit":
                d = ev["event_date"] or ev["settlement_date"]
                if d:
                    hist[ev["category"]].append((d, ev["amount"], ev["category"]))
        stats = {}
        for c, rows in hist.items():
            if len(rows) >= 2:
                stats[c] = month_stats([(d, a) for d, a, _c in rows])
                stats[c]["cat"] = c

        deb_days = defaultdict(float)
        for c, rows in hist.items():
            for d, a, _c in rows:
                deb_days[d] += a
            if c in stats:
                days = sorted(d.day for d, _a, _c in rows)
                stats[c]["med_day"] = days[len(days) // 2]

        sched_rows = defaultdict(float)   # non-salary scheduled/pending debits
        sal_sched = []                    # scheduled salary credits in window
        pend_cred = defaultdict(float)
        for ev in norm.events_home:
            d0 = ev["settlement_date"] or ev["event_date"]
            if not d0 or not (start <= d0 <= end) or not ev["amount"]:
                continue
            if ev["class"] == "salary" and ev["status"] == "scheduled":
                sal_sched.append((d0, ev["amount"]))
            elif ev["direction"] == "debit" and ev["status"] in ("pending", "scheduled"):
                sched_rows[d0] += ev["amount"]
            elif ev["direction"] == "credit" and ev["status"] == "pending":
                pend_cred[d0] += ev["amount"]

        sal_info = norm.cadence.get("salary")
        sal_proj_dates = []
        if sal_info:
            d = start
            day = sal_info["day_hint"]
            y, m = start.year, start.month
            d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
            if d < start:
                d = add_month(d, day)
            while d <= end:
                sal_proj_dates.append(d)
                d = add_month(d, day)
        sal_day = sal_info["day_hint"] if sal_info else None

        cache.append({
            "rid": rid, "exp": exp, "capped": exp >= req.requested_amount - 0.005,
            "bal": p.current_available_balance, "keep": p.minimum_balance_to_keep,
            "requested": req.requested_amount, "gt_earliest": gt_earliest,
            "start": start, "end": end, "stats": stats,
            "sched_rows": sched_rows, "sal_sched": sal_sched,
            "pend_cred": pend_cred, "sal_proj_dates": sal_proj_dates,
            "sal_amt": sal_info["monthly_amount"] if sal_info else None,
            "sal_day": sal_day,
        })

    results = []
    for amount, timing, scope, salm, pc in product(AMOUNTS, TIMINGS, SCOPES, SALARY, PENDC):
        n_c1 = n_c2 = n_both = 0
        n_unc = 0
        for smp in cache:
            if smp["capped"]:
                continue
            n_unc += 1
            start, end, keep = smp["start"], smp["end"], smp["keep"]
            mv = defaultdict(float)
            for d0, a in smp["sched_rows"].items():
                mv[d0] -= a
            for d0, a in smp["sal_sched"].items() if False else smp["sal_sched"]:
                mv[d0] += a
            if pc == "yes":
                for d0, a in smp["pend_cred"].items():
                    mv[d0] += a
            # salary projection credits
            if salm in ("proj", "both") and smp["sal_amt"]:
                for d0 in smp["sal_proj_dates"]:
                    mv[d0] += smp["sal_amt"]
            # expense occurrences
            for c, st in smp["stats"].items():
                if scope == "fixedOnly" and c in VARIABLE_CATS:
                    continue
                if scope == "varOnly" and c not in VARIABLE_CATS:
                    continue
                if scope == "sFixed" and st["strength"] != "fixed":
                    continue
                if scope == "sVar" and st["strength"] != "variable":
                    continue
                amt = st[amount]
                day = st["med_day"]
                if timing == "dayhint":
                    y, m = start.year, start.month
                    d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
                    if d < start:
                        d = add_month(d, day)
                    while d <= end:
                        mv[d] -= amt
                        d = add_month(d, day)
                elif timing == "day1":
                    y, m = start.year, start.month
                    d = date(y, m, 1)
                    if d < start:
                        m += 1
                        if m > 12:
                            m, y = 1, y + 1
                        d = date(y, m, 1)
                    while d <= end:
                        mv[d] -= amt
                        m += 1
                        if m > 12:
                            m, y = 1, y + 1
                        d = date(y, m, 1)
                elif timing == "wk_dh":
                    first = date(start.year, start.month, min(day, calendar.monthrange(start.year, start.month)[1]))
                    d = first - timedelta(days=7 * ((first - start).days // 7 + 1))
                    if d > start:
                        d = start
                    while d <= end:
                        if d >= start:
                            mv[d] -= amt
                        d += timedelta(days=7)
                elif timing in ("daily_dim", "daily_30"):
                    d = start
                    while d <= end:
                        dim = calendar.monthrange(d.year, d.month)[1]
                        mv[d] -= amt / (dim if timing == "daily_dim" else 30.0)
                        d += timedelta(days=1)
                elif timing == "salday":
                    if smp["sal_day"] is None:
                        continue
                    y, m = start.year, start.month
                    d = date(y, m, min(smp["sal_day"], calendar.monthrange(y, m)[1]))
                    if d < start:
                        d = add_month(d, smp["sal_day"])
                    while d <= end:
                        mv[d] -= amt
                        d = add_month(d, smp["sal_day"])
            # evaluate
            bal = smp["bal"]
            mn = bal
            daily = []
            d = start
            while d <= end:
                a = mv.get(d)
                if a:
                    bal += a
                daily.append((d, bal))
                mn = min(mn, bal)
                d += timedelta(days=1)
            c1 = abs(mn - (keep + smp["exp"])) <= TOL
            # earliest full-payment date (suffix-min scan)
            need = keep + smp["requested"]
            run = float("inf")
            suff = {}
            for d, b in reversed(daily):
                run = min(run, b)
                suff[d] = run
            gt_e = smp["gt_earliest"]
            if gt_e:
                try:
                    gt_d = date.fromisoformat(gt_e)
                except ValueError:
                    gt_d = None
                c2 = gt_d is not None and any(
                    abs((suff[dd]) - need) <= 1e-6 and dd == gt_d
                    for dd in (gt_d,) if dd in suff and suff[dd] >= need - 1e-6
                ) and all(suff[date.fromisoformat(gt_e) - timedelta(days=k)] < need - 1e-6
                          for k in range(1, 40)
                          if date.fromisoformat(gt_e) - timedelta(days=k) in suff)
            else:
                c2 = True  # unconstrained
            n_c1 += c1
            n_c2 += c2
            n_both += c1 and c2
        label = f"{amount:7s} {timing:9s} {scope:9s} sal={salm:5s} pc={pc:3s}"
        results.append((n_both, n_c1, n_c2, label))
        if n_both >= 3 or n_c1 >= 8:
            print(f"{label} both={n_both}/{n_unc} c1={n_c1} c2={n_c2}")

    results.sort(reverse=True)
    print("\nTOP 15 by joint constraint satisfaction:")
    for n_both, n_c1, n_c2, label in results[:15]:
        print(f"  {label} both={n_both} c1(trough)={n_c1} c2(earliest)={n_c2}")


if __name__ == "__main__":
    main()
