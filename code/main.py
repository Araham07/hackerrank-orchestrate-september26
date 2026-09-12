"""Buy or Wait? — AI financial affordability agent.

Runnable entry point.

    python code/main.py            # full pipeline -> output.csv (repo root)
    python code/main.py --audit    # Phase 1 dataset audit only
    python code/main.py --limit N  # run only the first N requests (debug)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python code/main.py` from anywhere: put the repo root on sys.path
# so `code.*` package imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run_audit() -> None:
    """Phase 1: load all 8 dataset files and print the integrity audit."""
    from code.data.loader import dataset_summary

    s = dataset_summary()
    print("=" * 64)
    print("DATASET AUDIT — Buy or Wait?")
    print("=" * 64)
    print(f"  financial_profiles          {s['profiles']:>6} users")
    print(f"  financial_events            {s['events']:>6} events")
    print(f"  exchange_rates              {s['rates']:>6} dated rates")
    print(f"  requests                    {s['requests']:>6} requests")
    print(f"  sample_requests             {s['samples']:>6} solved samples")
    print(f"  request_payment_options     {s['payment_options']:>6} options")
    print(f"  messages                    {s['messages']:>6} messages")
    print(f"  images                      {s['image_links']:>6} links "
          f"({s['image_files_on_disk']} PNGs on disk)")
    print("-" * 64)
    print(f"  blank-amount events:        {s['blank_amount_events']}")
    print(f"    ... with image link:      "
          f"{s['blank_amount_events'] - s['blank_amount_without_image_link']}")
    print(f"    ... missing image link:   {s['blank_amount_without_image_link']}")
    print(f"    ... image file missing:   {s['blank_amount_image_file_missing']}")
    print(f"  blank-amount event ids:     {', '.join(s['blank_amount_event_ids']) or '(none)'}")
    print(f"  users w/ events, no profile:{s['users_with_events_missing_profile'] or 'none'}")
    print(f"  requests w/ unknown user:   {s['requests_missing_profile'] or 'none'}")
    print(f"  message languages (approx): {', '.join(s['message_languages'])}")
    print("=" * 64)

    ok = (
        not s["users_with_events_missing_profile"]
        and not s["requests_missing_profile"]
        and not s["blank_amount_without_image_link"]
        and not s["blank_amount_image_file_missing"]
    )
    print("INTEGRITY:", "OK" if ok else "REVIEW NEEDED (see flags above)")
    from code.evaluation.token_ledger import totals
    t = totals()
    print(f"token ledger wired: {t['calls']} calls recorded "
          f"({t['input_tokens']} in / {t['output_tokens']} out)")


def run_full(limit: int | None = None) -> None:
    """Phases 2-8 + 10: process every request and write output.csv."""
    import csv

    from code.config import OUTPUT_CSV
    from code.data.state_builder import DataStore
    from code.finance.currency import FxGraph
    from code.orchestrator import process_request
    from code.validate.output_validator import validate_output_file

    ds = DataStore()
    fx = FxGraph(ds.rates)
    requests = ds.requests
    if limit:
        requests = requests[:limit]

    print(f"processing {len(requests)} requests...")
    rows = []
    errors = 0
    for i, request in enumerate(requests, 1):
        try:
            result = process_request(ds, fx, request)
            rows.append(result.row)
        except Exception as exc:  # noqa: BLE001 - never abort the batch
            errors += 1
            print(f"  [ERROR] {request.request_id}: "
                  f"{type(exc).__name__}: {exc}")
            rows.append({
                "request_id": request.request_id,
                "amount_safe_to_pay": "0",
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": (
                    "Pipeline error; no safe recommendation available."
                ),
            })
        if i % 25 == 0 or i == len(requests):
            print(f"  {i}/{len(requests)} done ({errors} errors)")

    fields = [
        "request_id", "amount_safe_to_pay", "affordability_status",
        "recommended_payment_method", "payment_plan",
        "earliest_date_for_full_payment", "spending_changes_needed",
        "decision_explanation",
    ]
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUTPUT_CSV} ({len(rows)} rows, {errors} errors)")

    # Phase 10: automated validation pass.
    violations = validate_output_file(OUTPUT_CSV, ds)
    if violations:
        print(f"VALIDATION: {len(violations)} violation(s)")
        for v in violations[:20]:
            print(f"  - {v}")
    else:
        print("VALIDATION: zero violations")

    # Token usage report (evaluation/usage_report.md).
    from code.evaluation.token_ledger import write_usage_report
    p = write_usage_report()
    print(f"usage report: {p}")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--audit":
        run_audit()
        return
    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
    run_full(limit)


if __name__ == "__main__":
    main()
