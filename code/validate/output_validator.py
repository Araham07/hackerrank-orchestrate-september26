"""Output validation (Phase 10).

Automated hard checks over every output row, exactly as the
implementation plan requires. Zero violations is the bar.
"""

from __future__ import annotations

import csv
from datetime import date

from code.config import AFFORDABILITY_STATUSES, PAYMENT_METHODS

FIELDS = [
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan",
    "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation",
]


def _num(s: str) -> float | None:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _is_date(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def validate_output_file(path, ds) -> list[str]:
    """Return a list of human-readable violations (empty = all good)."""
    v: list[str] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = list(reader)

    # Columns, exact required order.
    if header != FIELDS:
        v.append(f"columns {header} != required order {FIELDS}")

    req_by_id = {r.request_id: r for r in ds.requests}
    opts_by_request: dict[str, list] = {}
    for o in ds.options:
        opts_by_request.setdefault(o.request_id, []).append(o)

    seen: set[str] = set()
    for row in rows:
        rid = row.get("request_id", "")
        if rid in seen:
            v.append(f"{rid}: duplicate request_id row")
        seen.add(rid)

        req = req_by_id.get(rid)
        if req is None:
            v.append(f"{rid}: no matching input request row")
            continue

        # amount range: 0 <= amount <= requested_amount
        amt = _num(row.get("amount_safe_to_pay", ""))
        if amt is None or amt < 0:
            v.append(f"{rid}: amount_safe_to_pay {amt!r} not >= 0")
        elif amt > req.requested_amount + 1e-6:
            v.append(
                f"{rid}: amount {amt} > requested {req.requested_amount}"
            )

        # enum validity
        if row.get("affordability_status") not in AFFORDABILITY_STATUSES:
            v.append(f"{rid}: bad affordability_status "
                     f"{row.get('affordability_status')!r}")
        if row.get("recommended_payment_method") not in PAYMENT_METHODS:
            v.append(f"{rid}: bad recommended_payment_method "
                     f"{row.get('recommended_payment_method')!r}")

        # affordable_now => earliest == request_date
        if row.get("affordability_status") == "affordable_now":
            want = req.request_date.isoformat() if req.request_date else ""
            if row.get("earliest_date_for_full_payment", "") != want:
                v.append(
                    f"{rid}: affordable_now earliest "
                    f"{row.get('earliest_date_for_full_payment')!r} != "
                    f"request_date {want!r}"
                )

        # payment_plan structure
        plan = row.get("payment_plan", "none")
        entries: list[tuple[str, float]] = []
        if plan != "none" and plan:
            ok = True
            for part in plan.split("|"):
                bits = part.split(":")
                if len(bits) != 2 or not _is_date(bits[0]) or \
                        _num(bits[1]) is None:
                    v.append(f"{rid}: malformed plan entry {part!r}")
                    ok = False
                    continue
                entries.append((bits[0], _num(bits[1])))
            if ok:
                dates = [d for d, _ in entries]
                if dates != sorted(dates):
                    v.append(f"{rid}: plan entries not chronological")

        method = row.get("recommended_payment_method", "")
        if method == "partial_payment":
            if len(entries) != 2:
                v.append(f"{rid}: partial_payment must have exactly 2 "
                         f"payments (has {len(entries)})")
            elif abs(sum(a for _, a in entries)
                     - req.requested_amount) > 0.01:
                v.append(
                    f"{rid}: partial payments sum "
                    f"{sum(a for _, a in entries)} != requested "
                    f"{req.requested_amount}"
                )
        if method == "installments":
            options = opts_by_request.get(rid, [])
            matched = False
            for opt in options:
                if opt.payment_method != "installments":
                    continue
                if not opt.first_payment_date:
                    continue
                sched = []
                d0 = opt.first_payment_date
                for _ in range(opt.number_of_payments):
                    sched.append(
                        (d0.isoformat(), round(opt.payment_amount, 2))
                    )
                    d0 = date.fromordinal(
                        d0.toordinal() + (opt.payment_frequency_days or 30)
                    )
                ours = [(d, round(a, 2)) for d, a in entries]
                if ours == sched:
                    matched = True
                    break
            if not matched:
                v.append(f"{rid}: installments plan does not exactly match "
                         f"any supplied payment option schedule")

        # spending changes validity
        sc = row.get("spending_changes_needed", "none")
        if sc and sc != "none":
            targets: dict[str, set[str]] = {}
            for part in sc.split("|"):
                bits = part.split(":")
                if bits[0] not in ("stop", "reduce_to") or len(bits) < 2:
                    v.append(f"{rid}: malformed spending change {part!r}")
                    continue
                targets.setdefault(bits[1], set()).add(bits[0])
                if bits[0] == "reduce_to" and (
                    len(bits) != 3 or _num(bits[2]) is None
                ):
                    v.append(f"{rid}: malformed reduce_to {part!r}")
            for eid, modes in targets.items():
                if len(modes) > 1:
                    v.append(f"{rid}: stop and reduce_to both target {eid}")

    # One row per input row.
    missing = set(req_by_id) - seen
    for rid in sorted(missing)[:10]:
        v.append(f"{rid}: missing output row")
    return v
