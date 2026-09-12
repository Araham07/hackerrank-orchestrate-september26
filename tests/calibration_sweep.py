"""Phase-9 calibration sweep.

Runs the full pipeline on the 25 samples for every combination of
(code.finance.normalizer.AMOUNT_VARIANT, forecast salary-month cap) and
prints per-field accuracy for each. Pure measurement: changes nothing.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import code.finance.normalizer as normalizer_mod
import code.finance.forecast as forecast_mod
from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.normalizer import normalize_state
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image
from code.finance.payment_plans import generate_candidates
from code.validate.plan_ranker import decide


def run_once(ds, fx, variant, salary_k):
    normalizer_mod.AMOUNT_VARIANT = variant
    forecast_mod.SALARY_MONTHS_CAP = salary_k if salary_k > 0 else None

    out = []
    for sample in ds.samples:
        rid = sample["request_id"]
        try:
            req = ds.request_by_id(rid)
            state = ds.build_state(req)
            facts = [interpret_message(m, request_id=rid) for m in state.messages]
            facts += [interpret_image(i, request_id=rid) for i in state.image_links]
            norm = normalize_state(state, fx, facts)
            plans = generate_candidates(state, norm)
            d = decide(state, norm, plans)
            out.append(d)
        except Exception:
            out.append(None)
    return out


def score(results, ds):
    s = {"status": 0, "method": 0, "amount": 0, "plan": 0,
         "earliest": 0, "changes": 0}
    for d, sample in zip(results, ds.samples):
        if d is None:
            continue
        if d.affordability_status == sample["affordability_status"]:
            s["status"] += 1
        if d.recommended_payment_method == sample["recommended_payment_method"]:
            s["method"] += 1
        if abs(float(d.amount_safe_to_pay) - float(sample["amount_safe_to_pay"])) <= 0.05:
            s["amount"] += 1
        if d.payment_plan == sample["payment_plan"]:
            s["plan"] += 1
        if (d.earliest_date_for_full_payment or "") == (
            sample["earliest_date_for_full_payment"] or ""
        ):
            s["earliest"] += 1
        if set((d.spending_changes_needed or "none").split("|")) == set(
            (sample["spending_changes_needed"] or "none").split("|")
        ):
            s["changes"] += 1
    return s


def main():
    quiet = "--quiet" in sys.argv
    ds = DataStore()
    fx = FxGraph(ds.rates)
    best = None
    for variant in ("m", "mu", "mx", "mn", "pe", "peMu", "nPm"):
        for k in (0, 1, 2, 3, 4):
            results = run_once(ds, fx, variant, k)
            s = score(results, ds)
            total = sum(s.values())
            tag = f"{variant:5s} salcap={k}"
            print(f"{tag}: {s} total={total}")
            sys.stdout.flush()
            if best is None or total > best[0]:
                best = (total, variant, k, dict(s))
    print("BEST:", best)


if __name__ == "__main__":
    main()
