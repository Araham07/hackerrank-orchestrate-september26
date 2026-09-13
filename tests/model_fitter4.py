"""Round-4 model fitter: fixed/variable split + volatility risk buffer.

The structurally NEW hypothesis (never tested in rounds 1-3): the ground-truth
deduction D = naive_headroom - expected decomposes as

    projected fixed recurring outflow        (high-confidence cadence cats)
  + projected variable spending forecast     (conservative historical stat)
  + volatility-scaled risk buffer            (k * volatility metric)
  - confirmed salary credits in horizon

Model axes (all GENERAL, no per-sample fitting):
  est_f   fixed-cat monthly amount: med | mean
  est_v   variable-cat amount: med | mean | recent3 | recent1 | pe_med_x_freq
  vol     volatility metric: std_var | std_all | mad_var | range_var | percat_std
  k       buffer multiplier: 0 .25 .5 .75 1 1.5 2
  sal     salary mode: all | strong_only (strength == 'fixed')
  hor     horizon days: 30 | 60 | 90

Match: |safe - expected| <= 0.02 on the 21 uncapped samples.

Run:  python tests/model_fitter4.py
"""
from __future__ import annotations

import calendar
import itertools
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
import statistics

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.forecast import build_movements
from code.finance.normalizer import normalize_state
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image

# General financial taxonomy (Phase 3): fixed vs variable recurring expense.
FIXED_CATS = {
    "rent", "housing", "mortgage", "insurance", "utilities", "education",
    "healthcare", "loan", "debt_repayment", "emi", "cloud_storage",
    "streaming", "music_subscription", "delivery_membership", "gym",
    "subscription", "internet", "phone", "cable", "childcare", "tuition",
}


def classify(cat: str, data_strength: str | None, mode: str) -> str:
    if mode == "taxonomy":
        return "fixed" if cat in FIXED_CATS else "variable"
    # data-driven: use cadence strength computed by the normalizer
    if data_strength == "fixed":
        return "fixed"
    return "variable"


def month_key(d: date) -> tuple[int, int]:
    return (d.year, d.month)


def future_monthly_dates(start: date, day: int, horizon_end: date) -> list[date]:
    rows = []
    y, m = start.year, start.month
    d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
    if d < start:
        m += 1
        if m > 12:
            m, y = 1, y + 1
        d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
    while d <= horizon_end:
        rows.append(d)
        m2 = d.month + 1
        y2 = d.year + (1 if m2 > 12 else 0)
        m2 = 1 if m2 > 12 else m2
        d = date(y2, m2, min(day, calendar.monthrange(y2, m2)[1]))
    return rows


def build_context():
    """Per-sample static context reused by every model evaluation."""
    ds = DataStore()
    fx = FxGraph(ds.rates)
    ctxs = []
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
        requested = req.requested_amount

        capped = exp >= requested - 0.01
        if capped:
            continue  # only uncapped samples constrain the model

        end = start + timedelta(days=days)

        # Historical monthly totals per category (settled history before start).
        by_cat = defaultdict(lambda: defaultdict(list))
        for ev in norm.events_home:
            if ev["status"] != "settled" or ev["amount"] is None:
                continue
            if not (ev["direction"] == "debit" or ev["category"] == "salary"):
                continue
            d = ev["event_date"] or ev["settlement_date"]
            if d is None or d >= start:
                continue
            by_cat[ev["category"]][month_key(d)].append(ev["amount"])

        cats = {}
        for cat, months in by_cat.items():
            if cat == "salary" or len(months) < 2:
                continue
            keys = sorted(months)
            totals = [sum(v) for v in months.values()]
            per_event = sorted(x for v in months.values() for x in v)
            info = norm.cadence.get(cat, {})
            n_events_per_month = sum(len(v) for v in months.values()) / len(keys)
            cats[cat] = {
                "strength": info.get("strength"),
                "day": info.get("day_hint", 15),
                "med": statistics.median(totals),
                "mean": sum(totals) / len(totals),
                "recent3": sum(totals[-3:]) / min(3, len(totals)),
                "recent1": totals[-1],
                "pe_med_freq": statistics.median(per_event) * n_events_per_month,
                "totals": totals,
                "events_per_month": n_events_per_month,
            }

        # Scheduled / pending rows inside the full window.
        sched = []
        for ev in norm.events_home:
            if ev["status"] not in ("pending", "scheduled") or not ev["amount"]:
                continue
            d = ev["settlement_date"] or ev["event_date"]
            if d and start <= d <= end:
                sched.append((d, -ev["amount"] if ev["direction"] == "debit" else ev["amount"]))

        # Salary cadence + projected credits.
        sal = norm.cadence.get("salary")
        credits = []
        if sal:
            for d in future_monthly_dates(start, sal["day_hint"], end):
                credits.append((d, sal["monthly_amount"]))

        ctxs.append({
            "rid": rid, "bal": bal, "keep": keep, "start": start,
            "requested": requested, "exp": exp, "cats": cats,
            "sched": sorted(sched), "sal": sal, "credits": credits,
            "strength": sal["strength"] if sal else None,
        })
    return ctxs


def trough_of(opening: float, mv: dict, start: date, days: int) -> float:
    bal, mn = opening, opening
    d = start
    for _ in range(days + 1):
        a = mv.get(d)
        if a:
            bal += a
        if bal < mn:
            mn = bal
        d += timedelta(days=1)
    return mn


def volatility(ctx, vol: str) -> float:
    var_totals = [c["totals"] for c in ctx["cats"].values()]
    fixed_mask = None
    if vol in ("std_all",):
        series = [c["totals"] for c in ctx["cats"].values()]
        vals = [x for s in series for x in s]
        return statistics.pstdev(vals) if len(vals) > 1 else 0.0
    # variable-only metrics: use all cats not in FIXED_CATS (taxonomy class)
    var_series = [c["totals"] for c, in []]  # placeholder; computed by caller
    return 0.0


def volatility_var(ctx, cat_vol_series: list[list[float]], vol: str) -> float:
    if not cat_vol_series:
        return 0.0
    if vol == "percat_std":
        stds = [statistics.pstdev(s) for s in cat_vol_series if len(s) > 1]
        return statistics.median(stds) if stds else 0.0
    # monthly variable totals across all variable cats
    n = max(len(s) for s in cat_vol_series)
    monthly = []
    for i in range(n):
        monthly.append(sum(s[i] for s in cat_vol_series if len(s) > i))
    if len(monthly) < 2:
        return 0.0
    if vol == "std_var":
        return statistics.pstdev(monthly)
    if vol == "mad_var":
        med = statistics.median(monthly)
        return statistics.median([abs(x - med) for x in monthly])
    if vol == "range_var":
        return max(monthly) - statistics.median(monthly)
    return 0.0


def evaluate(ctxs, est_f, est_v, vol, k, sal_mode, hor):
    hits = 0
    residuals = []
    for ctx in ctxs:
        start, end = ctx["start"], ctx["start"] + timedelta(days=hor)
        mv = {}
        var_series = []
        for cat, info in ctx["cats"].items():
            cls = classify(cat, info["strength"], "taxonomy")
            if cls == "fixed":
                amt = info[est_f]
            else:
                amt = info[est_v]
                var_series.append(info["totals"])
            if not amt:
                continue
            for d in future_monthly_dates(start, info["day"], end):
                mv[d] = mv.get(d, 0.0) - amt
        for d, a in ctx["sched"]:
            if d <= end:
                mv[d] = mv.get(d, 0.0) + a
        if ctx["sal"] and (sal_mode == "all" or ctx["strength"] == "fixed"):
            for d, a in ctx["credits"]:
                if d <= end:
                    mv[d] = mv.get(d, 0.0) + a
        t = trough_of(ctx["bal"], mv, start, hor)
        buf = k * volatility_var(ctx, var_series, vol)
        safe = min(ctx["requested"], max(0.0, t - ctx["keep"] - buf))
        residuals.append(safe - ctx["exp"])
        if abs(safe - ctx["exp"]) <= 0.02:
            hits += 1
    return hits, residuals


def main() -> None:
    ctxs = build_context()
    print(f"uncapped samples: {len(ctxs)}")
    grid = list(itertools.product(
        ("med", "mean"),                       # est_f
        ("med", "mean", "recent3", "recent1", "pe_med_freq"),  # est_v
        ("std_var", "mad_var", "range_var", "percat_std"),     # vol
        (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0), # k
        ("all", "strong_only"),                # sal
        (30, 60, 90),                          # hor
    ))
    results = []
    for combo in grid:
        hits, res = evaluate(ctxs, *combo)
        results.append((hits, combo, res))
    results.sort(key=lambda r: (-r[0], sum(abs(x) for x in r[2])))
    print(f"models evaluated: {len(results)}")
    print("\nTOP 15 BY EXACT HITS:")
    for hits, combo, res in results[:15]:
        sae = sum(abs(x) for x in res)
        print(f"  hits={hits:2d}/21 sae={sae:>14.2f}  est_f={combo[0]} est_v={combo[1]} "
              f"vol={combo[2]} k={combo[3]} sal={combo[4]} hor={combo[5]}")
    best = results[0]
    print(f"\nBEST residuals (hits={best[0]}, {best[1]}):")
    for ctx, r in zip(ctxs, best[2]):
        flag = "OK " if abs(r) <= 0.02 else "X  "
        print(f"  {flag}{ctx['rid']}: resid={r:+.2f}  (exp={ctx['exp']:.2f})")
    zero_k = [r for r in results if r[1][3] == 0.0]
    print(f"\nbest k=0 (no buffer) hits: {max(r[0] for r in zero_k)}")
    with open(Path(__file__).parent / "model_fitter4_out.txt", "w") as f:
        f.write(f"models={len(results)}\n")
        for hits, combo, res in results[:60]:
            f.write(f"hits={hits} sae={sum(abs(x) for x in res):.2f} {combo}\n")


if __name__ == "__main__":
    main()
