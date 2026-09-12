"""Sample validation harness (Phase 9 pulled forward).

Runs the full pipeline (Phases 2-7) on every sample_requests.csv row,
ignoring the answer columns as input, and diffs field-by-field against the
solved examples. Produces tests/sample_scorecard.md.

Usage:
    python -m tests.sample_scorecard        # or:
    python tests/sample_scorecard.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.normalizer import normalize_state
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image
from code.finance.payment_plans import generate_candidates
from code.validate.plan_ranker import decide


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _amt_close(a, b, tol=0.05):
    fa, fb = _num(a), _num(b)
    if fa is None or fb is None:
        return fa == fb
    return abs(fa - fb) <= tol


def _plan_match(ours, expected):
    if ours == expected:
        return True
    op = [p.split(":") for p in ours.split("|")] if ours != "none" else []
    ep = [p.split(":") for p in expected.split("|")] if expected != "none" else []
    if len(op) != len(ep):
        return False
    for (od, oa), (ed, ea) in zip(op, ep):
        if od != ed or not _amt_close(oa, ea, 1.0):
            return False
    return True


def _changes_match(ours, expected):
    if ours == expected:
        return True
    return set(ours.split("|")) == set(expected.split("|"))


def run_sample(ds, fx, sample_row):
    rid = sample_row["request_id"]
    req = ds.request_by_id(rid)
    if req is None:
        return None
    state = ds.build_state(req)
    facts = [interpret_message(m, request_id=rid) for m in state.messages]
    facts += [interpret_image(i, request_id=rid) for i in state.image_links]
    norm = normalize_state(state, fx, facts)
    plans = generate_candidates(state, norm)
    d = decide(state, norm, plans)
    return {
        "request_id": rid,
        "affordability_status": d.affordability_status,
        "recommended_payment_method": d.recommended_payment_method,
        "amount_safe_to_pay": d.amount_safe_to_pay,
        "payment_plan": d.payment_plan,
        "earliest_date_for_full_payment": d.earliest_date_for_full_payment,
        "spending_changes_needed": d.spending_changes_needed,
        "decision": d,
    }


def field_scores(rows):
    n = len(rows)
    return {
        "affordability_status": sum(
            1 for r in rows if r["ours"] and r["ours"]["affordability_status"] == r["exp"]["affordability_status"]
        ),
        "recommended_payment_method": sum(
            1 for r in rows if r["ours"] and r["ours"]["recommended_payment_method"] == r["exp"]["recommended_payment_method"]
        ),
        "amount_safe_to_pay": sum(
            1 for r in rows if r["ours"] and _amt_close(r["ours"]["amount_safe_to_pay"], r["exp"]["amount_safe_to_pay"])
        ),
        "payment_plan": sum(
            1 for r in rows if r["ours"] and _plan_match(r["ours"]["payment_plan"], r["exp"]["payment_plan"])
        ),
        "earliest_date_for_full_payment": sum(
            1 for r in rows if r["ours"]
            and (r["ours"]["earliest_date_for_full_payment"] or "") == (r["exp"]["earliest_date_for_full_payment"] or "")
        ),
        "spending_changes_needed": sum(
            1 for r in rows if r["ours"] and _changes_match(
                r["ours"]["spending_changes_needed"], r["exp"]["spending_changes_needed"]
            )
        ),
        "_n": n,
    }


def main():
    ds = DataStore()
    fx = FxGraph(ds.rates)
    out_rows = []
    for sample in ds.samples:
        rid = sample["request_id"]
        try:
            ours = run_sample(ds, fx, sample)
        except Exception as exc:  # noqa: BLE001
            ours = None
            print(f"[ERROR] {rid}: {type(exc).__name__}: {exc}")
        out_rows.append({"request_id": rid, "ours": ours, "exp": sample})

    scores = field_scores(out_rows)
    n = scores["_n"]

    lines = [
        "# Sample Scorecard (25 solved examples)",
        "",
        f"Requests scored: {n}",
        "",
        "| Field | Accuracy |",
        "|---|---|",
    ]
    for field_name in (
        "affordability_status", "recommended_payment_method",
        "amount_safe_to_pay", "payment_plan",
        "earliest_date_for_full_payment", "spending_changes_needed",
    ):
        lines.append(f"| {field_name} | {scores[field_name]}/{n} |")

    lines += ["", "## Mismatch details", ""]
    for r in out_rows:
        if r["ours"] is None:
            lines.append(f"### {r['request_id']} — PIPELINE ERROR")
            continue
        o, e = r["ours"], r["exp"]
        diffs = []
        if o["affordability_status"] != e["affordability_status"]:
            diffs.append(
                f"status: ours={o['affordability_status']} exp={e['affordability_status']}"
            )
        if o["recommended_payment_method"] != e["recommended_payment_method"]:
            diffs.append(
                f"method: ours={o['recommended_payment_method']} exp={e['recommended_payment_method']}"
            )
        if not _amt_close(o["amount_safe_to_pay"], e["amount_safe_to_pay"]):
            diffs.append(
                f"amount: ours={o['amount_safe_to_pay']} exp={e['amount_safe_to_pay']}"
            )
        if not _plan_match(o["payment_plan"], e["payment_plan"]):
            diffs.append(
                f"plan: ours={o['payment_plan']} exp={e['payment_plan']}"
            )
        if (o["earliest_date_for_full_payment"] or "") != (e["earliest_date_for_full_payment"] or ""):
            diffs.append(
                f"earliest: ours={o['earliest_date_for_full_payment']} exp={e['earliest_date_for_full_payment']}"
            )
        if not _changes_match(o["spending_changes_needed"], e["spending_changes_needed"]):
            diffs.append(
                f"changes: ours={o['spending_changes_needed']} exp={e['spending_changes_needed']}"
            )
        if diffs:
            lines.append(f"### {r['request_id']}")
            for d in diffs:
                lines.append(f"- {d}")
            lines.append("")

    out_path = Path(__file__).parent / "sample_scorecard.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"scorecard written: {out_path}")
    for field_name in (
        "affordability_status", "recommended_payment_method",
        "amount_safe_to_pay", "payment_plan",
        "earliest_date_for_full_payment", "spending_changes_needed",
    ):
        print(f"  {field_name}: {scores[field_name]}/{n}")


if __name__ == "__main__":
    main()
