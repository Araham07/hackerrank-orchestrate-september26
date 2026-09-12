"""Probe: recurrence-coverage x amount-estimator matrix on the scorecard.

Hypotheses not covered by earlier sweeps (see HANDOFF section 8):
1. min_months: current detect_recurrence needs >= 2 distinct months of
   history before a category projects at all. Ground truth's troughs are
   LOWER than ours (more outflow) - maybe 1-month categories project too.
2. strength-aware hybrid: fixed cadence -> median month total, variable
   cadence -> mean or max month total (conservative), instead of one
   estimator for every category.

Monkeypatches code.finance.normalizer.detect_recurrence; measures the
full pipeline per config. Pure measurement: changes nothing.
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import code.finance.normalizer as normalizer_mod
from tests.sample_scorecard import field_scores, run_sample


def make_detect_recurrence(min_months: int, amount_rule: str):
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
            if len(months) < min_months:
                continue  # hypothesis-1 knob
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
            elif amount_rule == "m":
                med_total = sorted(totals)[len(totals) // 2]
            elif amount_rule == "nPm":
                med_total = statistics.median(per_event) * (
                    len(dated) / len(months)
                )
            else:  # strength-aware hybrid
                if strength == "fixed":
                    med_total = sorted(totals)[len(totals) // 2]
                elif amount_rule == "hybrid_mu":
                    med_total = statistics.mean(totals)
                elif amount_rule == "hybrid_mx":
                    med_total = max(totals)
                else:  # pragma: no cover
                    raise ValueError(amount_rule)

            cadence[cat] = {
                "monthly_amount": med_total,
                "day_hint": med_day,
                "occurrences": len(dated),
                "months": len(months),
                "strength": strength,
            }
        return cadence

    return detect_recurrence


def main():
    from code.data.state_builder import DataStore
    from code.finance.currency import FxGraph

    ds = DataStore()
    fx = FxGraph(ds.rates)
    original = normalizer_mod.detect_recurrence

    for min_months in (2, 1):
        for rule in ("nPm", "m", "hybrid_mu", "hybrid_mx"):
            normalizer_mod.detect_recurrence = make_detect_recurrence(
                min_months, rule
            )
            rows = []
            for sample in ds.samples:
                try:
                    rows.append({
                        "request_id": sample["request_id"],
                        "ours": run_sample(ds, fx, sample),
                        "exp": sample,
                    })
                except Exception as exc:  # noqa: BLE001
                    rows.append({
                        "request_id": sample["request_id"],
                        "ours": None, "exp": sample,
                    })
                    print(f"  [ERR] {sample['request_id']}: {exc}")
            s = field_scores(rows)
            n = s["_n"]
            total = sum(s[k] for k in s if k != "_n")
            print(f"months>={min_months} rule={rule:9s} -> "
                  f"status={s['affordability_status']} "
                  f"method={s['recommended_payment_method']} "
                  f"amount={s['amount_safe_to_pay']} "
                  f"plan={s['payment_plan']} "
                  f"earliest={s['earliest_date_for_full_payment']} "
                  f"changes={s['spending_changes_needed']} "
                  f"total={total}/{6 * n}")

    normalizer_mod.detect_recurrence = original


if __name__ == "__main__":
    main()
