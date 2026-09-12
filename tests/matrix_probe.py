"""Combined probe: guard x single-month-coverage x estimator matrix.

Configs:
  A base                (guard ON,  months>=2, nPm)         = production
  B no-guard            (guard OFF, months>=2, nPm)
  C no-guard + 1mo-nPm  (guard OFF, months>=1, nPm everywhere)
  D no-guard + 1mo-min  (guard OFF, months>=1; nPm for >=2-month
                         categories, MIN month total for 1-month cats)

Also prints per-sample amount_safe_to_pay for the best config vs base,
so we can see exactly which samples move toward ground truth.

Pure measurement: changes nothing in production code.
"""

from __future__ import annotations

import calendar
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import code.finance.forecast as forecast_mod
import code.finance.normalizer as normalizer_mod
from code.finance.normalizer import next_occurrence
from tests.sample_scorecard import field_scores, run_sample
from tests.guard_probe import build_movements_no_guard


def make_detect_recurrence(min_months: int, one_month_rule: str):
    """one_month_rule applies only to categories with exactly 1 month:
    'skip' (never project), 'nPm', or 'min' (minimum month total)."""

    def detect_recurrence(events):
        by_cat = defaultdict(list)
        for e in events:
            if e.status != "settled" or e.amount is None:
                continue
            if e.direction == "debit" or e.category == "salary":
                by_cat[e.category].append(e)

        cadence = {}
        for cat, rows in by_cat.items():
            dated = [e for e in rows if (e.event_date or e.settlement_date)]
            if not dated:
                continue
            dated.sort(key=lambda e: e.event_date or e.settlement_date)
            months = defaultdict(float)
            days = []
            for e in dated:
                d = e.event_date or e.settlement_date
                months[(d.year, d.month)] += e.amount
                days.append(d.day)
            totals = list(months.values())
            days.sort()
            med_day = days[len(days) // 2]

            strength = "variable"
            if len(dated) >= 3:
                same_day = sum(1 for d in days if abs(d - med_day) <= 2)
                if same_day / len(days) >= 0.6:
                    strength = "fixed"

            per_event = [e.amount for e in dated]
            if cat == "salary":
                med_total = sorted(per_event)[len(per_event) // 2]
            elif len(months) < min_months:
                # below the coverage bar: use the 1-month rule
                if one_month_rule == "skip":
                    continue
                elif one_month_rule == "min":
                    med_total = min(totals)
                elif one_month_rule == "nPm":
                    med_total = statistics.median(per_event) * (
                        len(dated) / len(months)
                    )
                else:  # pragma: no cover
                    raise ValueError(one_month_rule)
            else:
                med_total = statistics.median(per_event) * (
                    len(dated) / len(months)
                )  # nPm for everything above the bar

            cadence[cat] = {
                "monthly_amount": med_total,
                "day_hint": med_day,
                "occurrences": len(dated),
                "months": len(months),
                "strength": strength,
            }
        return cadence

    return detect_recurrence


CONFIGS = [
    ("A base",               "guarded",        2, "skip"),
    ("B no-guard",           "no_guard",       2, "skip"),
    ("C no-guard+1mo-nPm",   "no_guard",       1, "nPm"),
    ("D no-guard+1mo-min",   "no_guard",       1, "min"),
]


def run_config(ds, fx, build_fn, detect_fn):
    forecast_mod.build_movements = build_fn
    normalizer_mod.detect_recurrence = detect_fn
    rows = []
    for sample in ds.samples:
        try:
            rows.append({
                "request_id": sample["request_id"],
                "ours": run_sample(ds, fx, sample),
                "exp": sample,
            })
        except Exception as exc:  # noqa: BLE001
            rows.append({"request_id": sample["request_id"],
                         "ours": None, "exp": sample})
            print(f"  [ERR] {sample['request_id']}: {exc}")
    return rows


def main():
    from code.data.state_builder import DataStore
    from code.finance.currency import FxGraph

    ds = DataStore()
    fx = FxGraph(ds.rates)
    orig_build = forecast_mod.build_movements
    orig_detect = normalizer_mod.detect_recurrence

    results = {}
    for label, guard, mm, rule in CONFIGS:
        build_fn = orig_build if guard == "guarded" else build_movements_no_guard
        detect_fn = make_detect_recurrence(mm, rule)
        rows = run_config(ds, fx, build_fn, detect_fn)
        s = field_scores(rows)
        n = s["_n"]
        total = sum(s[k] for k in s if k != "_n")
        results[label] = rows
        print(f"{label:22s} -> status={s['affordability_status']} "
              f"method={s['recommended_payment_method']} "
              f"amount={s['amount_safe_to_pay']} "
              f"plan={s['payment_plan']} "
              f"earliest={s['earliest_date_for_full_payment']} "
              f"changes={s['spending_changes_needed']} "
              f"total={total}/{6 * n}")

    forecast_mod.build_movements = orig_build
    normalizer_mod.detect_recurrence = orig_detect

    # Per-sample amount comparison: best challenger (D) vs base vs expected.
    print("\nper-sample amount (base -> D, expected):")
    by_id_base = {r["request_id"]: r for r in results["A base"]}
    by_id_d = {r["request_id"]: r for r in results["D no-guard+1mo-min"]}
    for rid in sorted(by_id_base):
        b = by_id_base[rid]["ours"]
        dd = by_id_d[rid]["ours"]
        exp = by_id_base[rid]["exp"]
        if b is None or dd is None:
            continue
        ba = float(b["amount_safe_to_pay"])
        da = float(dd["amount_safe_to_pay"])
        ea = float(exp["amount_safe_to_pay"])
        marker = ""
        if abs(da - ea) <= 0.05 and abs(ba - ea) > 0.05:
            marker = "  <-- D FIXED"
        elif abs(ba - ea) <= 0.05 and abs(da - ea) > 0.05:
            marker = "  <-- D BROKE"
        if abs(ba - ea) > 0.05 or abs(da - ea) > 0.05:
            print(f"  {rid}: base={ba:.2f} D={da:.2f} exp={ea:.2f}{marker}")


if __name__ == "__main__":
    main()
