"""Fit a general projection model to the ground-truth implied troughs.

For every solved sample the ground truth implies:
    min(balance path) == minimum_balance_to_keep + amount_safe_to_pay
(on 21/25 samples per HANDOFF section 8; the other 4 are capped at
requested_amount, giving LOWER-BOUND constraints: trough - keep >= requested).

This harness enumerates a wide grid of GENERAL projection models (no
per-sample rules) and reports, per model, how many samples it reproduces
exactly. Timing x amount x scope x salary axes are composable.

Run:  python tests/model_fitter.py
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

TOL = 0.02  # exact-match tolerance in home-currency units


# ---------------------------------------------------------------------------
# Model space
# ---------------------------------------------------------------------------

AMOUNTS = ("medTot", "meanTot", "minTot", "maxTot", "peMed", "peMean", "peUp")
TIMINGS = ("dayhint", "day1", "weekend_dh", "wk_dayhint", "daily_dim", "daily_30")
SCOPES = ("all", "fixedOnly", "varOnly")


def month_stats(rows):
    """rows: list of (date, amount) settled history -> stats dict."""
    months = defaultdict(list)
    for d, a in rows:
        months[(d.year, d.month)].append(a)
    totals = sorted(sum(v) for v in months.values())
    flat = sorted(a for _, a in rows)
    n_m = len(totals)
    return {
        "medTot": totals[len(totals) // 2],
        "meanTot": sum(totals) / n_m,
        "minTot": totals[0],
        "maxTot": totals[-1],
        "peMed": flat[len(flat) // 2],
        "peMean": sum(flat) / len(flat),
        "peUp": flat[len(flat) // 2],
        "months": n_m,
        "rate": len(rows) / n_m,
    }


def add_month(d: date, day_hint: int) -> date:
    m2 = d.month + 1
    y2 = d.year + (1 if m2 > 12 else 0)
    m2 = 1 if m2 > 12 else m2
    return date(y2, m2, min(day_hint, calendar.monthrange(y2, m2)[1]))


def schedule_for(cat_rows, amount, timing, start, days):
    """[(date, -amount)] occurrences for one category under a model."""
    if not cat_rows or amount is None or amount <= 0:
        return []
    end = start + timedelta(days=days)
    out = []
    dmin = min(d for d, _ in cat_rows)
    dmax = max(d for d, _ in cat_rows)
    med_day = sorted(d.day for d, _ in cat_rows)[len(cat_rows) // 2]
    if timing == "dayhint":
        y, m = start.year, start.month
        d = date(y, m, min(med_day, calendar.monthrange(y, m)[1]))
        if d < start:
            d = add_month(d, med_day)
        while d <= end:
            out.append((d, -amount))
            d = add_month(d, med_day)
    elif timing == "day1":
        y, m = start.year, start.month
        d = date(y, m, 1)
        if d < start:
            m += 1
            if m > 12:
                m, y = 1, y + 1
            d = date(y, m, 1)
        while d <= end:
            out.append((d, -amount))
            m += 1
            if m > 12:
                m, y = 1, y + 1
            d = date(y, m, 1)
    elif timing == "weekend_dh":  # weekly on the median weekday
        wd = sorted(d.weekday() for d, _ in cat_rows)[len(cat_rows) // 2]
        d = start + timedelta(days=(wd - start.weekday()) % 7)
        while d <= end:
            out.append((d, -amount))
            d += timedelta(days=7)
    elif timing == "wk_dayhint":  # weekly from the median day-of-month
        d = start
        first = date(start.year, start.month, min(med_day, calendar.monthrange(start.year, start.month)[1]))
        if first < start:
            first = add_month(first, med_day) - timedelta(days=7)
            if first < start:
                first += timedelta(days=7)
        d = first
        while d <= end:
            if d >= start:
                out.append((d, -amount))
            d += timedelta(days=7)
    elif timing == "daily_dim":
        days_map = defaultdict(float)
        d = start
        while d <= end:
            days_map[d] = -amount / calendar.monthrange(d.year, d.month)[1]
            d += timedelta(days=1)
        out = list(days_map.items())
    elif timing == "daily_30":
        days_map = defaultdict(float)
        d = start
        while d <= end:
            days_map[d] = -amount / 30.0
            d += timedelta(days=1)
        out = list(days_map.items())
    return out


def trough_walk(opening, movements, start, days):
    bal, mn = opening, opening
    d = start
    for _ in range(days + 1):
        a = movements.get(d)
        if a:
            bal += a
        mn = min(mn, bal)
        d += timedelta(days=1)
    return mn


def main():
    ds = DataStore()
    fx = FxGraph(ds.rates)

    # Pre-compute per-sample data
    samples = []
    for s in ds.samples:
        rid = s["request_id"]
        req = ds.request_by_id(rid)
        state = ds.build_state(req)
        facts = [interpret_message(m, request_id=rid) for m in state.messages]
        facts += [interpret_image(i, request_id=rid) for i in state.image_links]
        norm = normalize_state(state, fx, facts)
        p = state.profile
        exp = float(s["amount_safe_to_pay"])
        capped = exp >= req.requested_amount - 0.005
        samples.append({
            "rid": rid, "req": req, "state": state, "norm": norm,
            "bal": p.current_available_balance, "keep": p.minimum_balance_to_keep,
            "exp": exp, "capped": capped,
            "target_trough": p.minimum_balance_to_keep + exp,
        })

    per_sample_cache = {}
    for s in samples:
        norm = s["norm"]
        start, days = s["req"].request_date, 90
        # settled debit history per category
        hist = defaultdict(list)
        for ev in norm.events_home:
            if ev["status"] == "settled" and ev["amount"] and ev["direction"] == "debit":
                d = ev["event_date"] or ev["settlement_date"]
                if d:
                    hist[ev["category"]].append((d, ev["amount"]))
        stats = {c: month_stats(r) for c, r in hist.items()}
        # scheduled/pending rows (always included)
        sched = defaultdict(float)
        for ev in norm.events_home:
            if ev["status"] in ("pending", "scheduled") and ev["amount"]:
                d = ev["settlement_date"] or ev["event_date"]
                if d and start <= d <= start + timedelta(days=days):
                    sched[d] += (-1.0 if ev["direction"] == "debit" else 1.0) * ev["amount"]
        # scheduled salary rows for salary handling
        sal_sched = [
            (ev["settlement_date"] or ev["event_date"], ev["amount"])
            for ev in norm.events_home
            if ev["class"] == "salary" and ev["status"] == "scheduled" and ev["amount"]
            and start <= (ev["settlement_date"] or ev["event_date"]) <= start + timedelta(days=days)
        ]
        sal_info = norm.cadence.get("salary")
        per_sample_cache[s["rid"]] = (hist, stats, sched, sal_sched, sal_info, start)

    results = []
    for amount, timing, scope in product(AMOUNTS, TIMINGS, SCOPES):
        n_exact = 0
        n_lb_ok = 0
        misses = []
        for s in samples:
            hist, stats, sched, sal_sched, sal_info, start = per_sample_cache[s["rid"]]
            days = 90
            mv = dict(sched)
            for cat, rows in hist.items():
                if scope == "fixedOnly" and cat in ("groceries", "transport", "dining", "shopping", "entertainment"):
                    continue
                if scope == "varOnly" and cat not in ("groceries", "transport", "dining", "shopping", "entertainment"):
                    continue
                st = stats[cat]
                amt = st[amount]
                if timing in ("daily_dim", "daily_30") and st["months"] < 2:
                    continue
                for d, a in schedule_for(rows, amt, timing, start, days):
                    mv[d] = mv.get(d, 0.0) + a
            # salary: scheduled rows + k cadence credits, k in {0,1,2,3} -> try best
            best_k_err = None
            for k in (0, 1, 2, 3):
                mv2 = dict(mv)
                for d, a in sal_sched:
                    mv2[d] = mv2.get(d, 0.0) + a
                if sal_info and k:
                    amt = sal_info["monthly_amount"]
                    day = sal_info["day_hint"]
                    y, m = start.year, start.month
                    d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
                    if d < start:
                        d = add_month(d, day)
                    end = start + timedelta(days=days)
                    cnt = 0
                    while d <= end and cnt < k:
                        mv2[d] = mv2.get(d, 0.0) + amt
                        cnt += 1
                        d = add_month(d, day)
                t = trough_walk(s["bal"], mv2, start, days)
                if s["capped"]:
                    ok = t - s["keep"] >= s["exp"] - TOL
                else:
                    ok = abs(t - s["target_trough"]) <= TOL
                if best_k_err is None or ok:
                    if ok:
                        best_k_err = 0.0
                        break
                    err = abs(t - s["target_trough"])
                    if best_k_err is None or err < best_k_err:
                        best_k_err = err
            if best_k_err == 0.0:
                if s["capped"]:
                    n_lb_ok += 1
                else:
                    n_exact += 1
            else:
                misses.append((s["rid"], round(best_k_err, 2)))
        label = f"{amount:8s} {timing:11s} {scope:9s}"
        results.append((n_exact, n_lb_ok, label, misses[:6]))
        print(f"{label} exact={n_exact:2d}/21 lb_ok={n_lb_ok}/4 "
              f"score={n_exact + n_lb_ok} misses={misses}")

    results.sort(key=lambda r: (-(r[0] + r[1]), r[2]))
    print("\nTOP 10:")
    for n_exact, n_lb_ok, label, _ in results[:10]:
        print(f"  {label} exact={n_exact}/21 lb_ok={n_lb_ok}/4")


if __name__ == "__main__":
    main()
