"""Dump ALL resolved events + messages + facts for given sample ids.

Run:  python tests/event_dump.py request_14 request_08
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.data.state_builder import DataStore
from code.finance.currency import FxGraph
from code.finance.normalizer import normalize_state
from code.interpret.message_interpreter import interpret_message
from code.interpret.image_interpreter import interpret_image


def main():
    ds = DataStore()
    fx = FxGraph(ds.rates)
    rids = sys.argv[1:] or ["request_14"]
    for rid in rids:
        req = ds.request_by_id(rid)
        state = ds.build_state(req)
        facts = [interpret_message(m, request_id=rid) for m in state.messages]
        facts += [interpret_image(i, request_id=rid) for i in state.image_links]
        norm = normalize_state(state, fx, facts)
        p = state.profile
        print("=" * 110)
        print(f"{rid} user={req.user_id} date={req.request_date} "
              f"bal={p.current_available_balance} keep={p.minimum_balance_to_keep} "
              f"cur={p.home_currency}")
        print(f"  methods={p.payment_methods_user_will_consider} "
              f"reduce={p.expense_categories_user_is_willing_to_reduce} "
              f"stop={p.expense_categories_user_is_willing_to_stop} "
              f"protect={p.expense_categories_to_protect}")
        print(f"  -- resolved events ({len(norm.events_home)}) --")
        for ev in sorted(norm.events_home,
                         key=lambda x: (x["event_date"] or x["settlement_date"] or req.request_date)):
            d = ev["settlement_date"] or ev["event_date"]
            sign = "-" if ev["direction"] == "debit" else "+"
            print(f"  {ev['event_id']:>12} {d} {sign}{(ev['amount'] or 0):>14.2f} "
                  f"{ev['category']:<20} {ev['class']:<18} {ev['status']:<10} "
                  f"flex={ev['flexibility']:<10} min={ev['minimum_allowed_amount']} "
                  f"{(ev['description'] or '')[:38]}")
        print(f"  -- messages ({len(state.messages)}) --")
        for m, f in zip(state.messages, facts):
            print(f"  {m.message_id} ev={m.related_event_id} req={m.request_id} "
                  f"src={m.source_type} :: {m.message_text[:110]}")
            if f.get("action", "none") != "none" or f.get("injection_detected"):
                print(f"      -> fact: {f}")
        if state.image_links:
            print(f"  -- image links --")
            for i in state.image_links:
                print(f"  {i.image_id} ev={i.related_event_id} req={i.request_id}")
        print(f"  -- resolution log --")
        for ln in state.resolution_log:
            print(f"  {ln}")
        print(f"  -- normalize log --")
        for ln in norm.log:
            print(f"  {ln}")


if __name__ == "__main__":
    main()
