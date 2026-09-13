"""Image-to-decision integration tests (all 16 dataset images).

Verifies the full required chain for each image:

    image -> OCR -> candidate extraction (semantic types, confidence tiers)
          -> linked-event-context selection -> fact
          -> normalized event amount (never zero, never silently dropped)
          -> downstream state / forecast / decision consumption.

Verified semantic ground truth per image (from the OCR text itself, not
from any expected regression answer):

    image_01  pay slip          -> NET pay 4,365,000 IDR (not gross 4,780,800)
    image_02  rent receipt      -> BALANCE DUE 1,00,000 (not total 2,00,000)
    image_03  grocery bill      -> Net Amount 41,272.00
    image_04  delivery order    -> Item Bill 2,854.00
    image_05  telecom bill      -> Amount due 704.05 (NOT the year "2026",
                                   NOT the after-due-date 822.05)
    image_06  grocery invoice   -> Grand total 1,995.00 (via amount-in-words;
                                   310.00 is an MRP column value)
    image_07  restaurant bill   -> Total 8,528.10
    image_08  maintenance rcpt  -> Total Amount Received 15,339.00
    image_09  water bill rcpt   -> Total Amount Received 723.00
    image_10  grocery invoice   -> Total / Balance Due 79,679.26
    image_11  hospital bill     -> Amount Payable 3,550.00
    image_12  taxi receipt      -> Total 33.50 USD (currency from "$")
    image_13  shopping order    -> Total paid 2,298
    image_14  handwritten phcy  -> UNRESOLVED (OCR garbage "4s43o"; must not
                                   fabricate an amount)
    image_15  airline invoice   -> Grand Total 9,968.00 INR
    image_16  EV charging bill  -> Total 393.22 INR (verified in words)

Causality: dedicated tests prove image data CHANGES amount_safe_to_pay
(request_20) and the recurring-income cadence (request_03 net vs gross).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.data.state_builder import DataStore
from code.data.types import ResolvedEvent
from code.finance.currency import FxGraph
from code.finance.normalizer import normalize_state
from code.finance.payment_plans import generate_candidates
from code.interpret.image_interpreter import interpret_image
from code.interpret.ocr_extract import (
    _is_garbage_token,
    _is_id_like,
    _words_total,
    parse_number_token,
    select_candidate,
    build_candidates,
)
from code.validate.plan_ranker import decide

# Expected semantic extraction per image (module docstring ground truth).
EXPECTED = {
    "image_01": (4365000.0, "IDR", "net_income"),
    "image_02": (100000.0, "INR", "balance_due"),
    "image_03": (41272.0, None, "net_income"),
    "image_04": (2854.0, None, "purchase_total"),
    "image_05": (704.05, "INR", "purchase_total"),
    "image_06": (1995.0, "INR", "purchase_total"),
    "image_07": (8528.1, "INR", "purchase_total"),
    "image_08": (15339.0, "INR", "amount_paid"),
    "image_09": (723.0, "INR", "amount_paid"),
    "image_10": (79679.26, None, "purchase_total"),
    "image_11": (3550.0, None, "purchase_total"),
    "image_12": (33.5, "USD", "purchase_total"),
    "image_13": (2298.0, None, "amount_paid"),
    "image_14": (None, None, None),          # garbage rejected, not guessed
    "image_15": (9968.0, "INR", "purchase_total"),
    "image_16": (393.22, "INR", "purchase_total"),
}


def _link(image_id: str):
    """Fetch the real ImageLink row for one dataset image id."""
    ds = DataStore()
    for link in ds.image_links:
        if link.image_id == image_id:
            return link
    raise AssertionError(f"{image_id} not found in dataset/images.csv")


def _facts_by_image() -> dict:
    ds = DataStore()
    out = {}
    for link in ds.image_links:
        out[link.image_id] = (link, interpret_image(link))
    return out


# ---------------------------------------------------------------------------
# Unit level: number parsing guards
# ---------------------------------------------------------------------------


def test_parse_number_token_formats():
    assert parse_number_token("1,234,567.89") == 1234567.89
    assert parse_number_token("2,00,000.00") == 200000.0
    assert parse_number_token("1.00.000.00") == 100000.0   # dotted-Indian
    assert parse_number_token("5.000.000") == 5000000.0    # thousands dots
    assert parse_number_token("1234.56") == 1234.56


def test_garbage_and_id_tokens_rejected():
    assert _is_garbage_token("4s43o")           # handwritten OCR soup
    assert not _is_garbage_token("8528.10")
    assert _is_id_like("9999999000")            # phone number
    assert _is_id_like("0ec470dedc1c455ab42f58e9c7729305"[:12])
    assert not _is_id_like("9968")              # real ticket amount
    assert not _is_id_like("28,499,994")        # separated amounts fine


def test_year_fragment_never_an_amount():
    from code.interpret.ocr_extract import _is_date_fragment, _NUMBER_TOKEN_RE

    matches = list(_NUMBER_TOKEN_RE.finditer("Amount due till 06-Feb-2026"))
    year_m = next(m for m in matches if m.group(1) == "2026")
    assert _is_date_fragment(year_m, "Amount due till 06-Feb-2026", 2026.0)
    # The day fragment is rejected as sub-10 anyway.
    day_m = matches[0]
    assert _is_date_fragment(day_m, "Amount due till 06-Feb-2026", 6.0)


def test_words_total_parses_indian_and_camelcase():
    assert _words_total("Amount in Words: One Thousand And Nine Hundred "
                        "And Ninety-Five Rupees And Zero Paisa Only") == 1995.0
    assert _words_total("Total In Words Indian Rupee Seventy-Nine Thousand "
                        "Six Hundred Seventy-Nine and Twenty-Six Paise Only"
                        ) == 79679.26
    assert _words_total("Amount in : INR only") is None      # no parse -> None
    assert _words_total("no words marker here 12345") is None


def test_select_candidate_prefers_net_for_salary_events():
    cands = build_candidates(
        "Subtotal Earnings : IDR 4,780,800\n"
        "Total Deductions : IDR 415,800\n"
        "Net Pay : IDR 4,365,000\n"
        "Transferred to : Bank : IDR 4,365,000"
    )
    best = select_candidate(cands, "August 2019 net salary", "salary")
    assert best.amount == 4365000.0 and best.semantic_type == "net_income"


def test_select_candidate_prefers_balance_due_for_outstanding_events():
    cands = build_candidates(
        "Rent&Maintanance 2,00,000.00\n"
        "TotalAmounttobeReceiv 2,00,000.00\n"
        "Balance Due: 1.00.000.00"
    )
    best = select_candidate(cands, "Outstanding rent balance", "rent")
    assert best.amount == 100000.0 and best.semantic_type == "balance_due"


# ---------------------------------------------------------------------------
# Per-image extraction: all 16
# ---------------------------------------------------------------------------


def test_all_16_images_extract_semantic_amount():
    got = _facts_by_image()
    assert len(got) == 16, f"expected 16 dataset images, found {len(got)}"
    for image_id, (exp_amt, exp_cur, exp_stype) in EXPECTED.items():
        link, fact = got[image_id]
        assert fact["new_amount"] == exp_amt, (
            f"{image_id}: amount {fact['new_amount']} != {exp_amt} "
            f"({fact.get('note', '')})"
        )
        assert fact.get("new_currency") == exp_cur, (
            f"{image_id}: currency {fact.get('new_currency')} != {exp_cur}"
        )
        assert fact.get("semantic_type") == exp_stype, (
            f"{image_id}: semantic_type {fact.get('semantic_type')} != {exp_stype}"
        )


def test_every_fact_carries_candidate_audit_trail():
    """Each fact must expose its candidate list with the required fields."""
    for image_id, (link, fact) in _facts_by_image().items():
        cands = fact.get("candidates", [])
        assert isinstance(cands, list), image_id
        for c in cands:
            for field in ("amount", "currency", "label", "semantic_type",
                          "confidence"):
                assert field in c, f"{image_id}: candidate missing {field}"


def test_confidence_tiers_present_and_sane():
    for image_id, (link, fact) in _facts_by_image().items():
        conf = fact.get("confidence", 0.0)
        tier = fact.get("confidence_tier")
        if fact.get("new_amount") is not None:
            assert tier in ("HIGH", "MEDIUM", "LOW"), image_id
            if tier == "HIGH":
                assert conf >= 0.75, image_id
            elif tier == "MEDIUM":
                assert 0.5 <= conf < 0.75, image_id


def test_handwritten_garbage_is_not_fabricated():
    """image_14's OCR is digit-letter soup; the amount must stay unresolved."""
    link, fact = _facts_by_image()["image_14"]
    assert fact["new_amount"] is None
    assert "unresolved" in (fact.get("note") or "").lower() or \
        fact.get("action") == "none"


# ---------------------------------------------------------------------------
# Pipeline level: image events enter the shared normalized timeline
# ---------------------------------------------------------------------------


def test_image_amounts_land_in_normalized_timeline():
    """Every filled fact's amount must appear in events_home for its user."""
    ds = DataStore()
    fx = FxGraph(ds.rates)
    checked = 0
    for link in ds.image_links:
        req = ds.request_by_id(link.request_id)
        if req is None:
            continue
        state = ds.build_state(req)
        fact = interpret_image(link)
        norm = normalize_state(state, fx, [fact])
        row = next(
            (e for e in norm.events_home if e["event_id"] == link.related_event_id),
            None,
        )
        if fact["new_amount"] is None or row is None:
            continue  # unresolved image (image_14): event stays amount-less
        assert row["amount"] is not None, (
            f"{link.image_id}: timeline row must not be blank/zero after fill"
        )
        cur = fact.get("new_currency")
        if cur is not None and state.profile.home_currency == cur:
            assert abs(row["amount"] - fact["new_amount"]) < 0.01, (
                f"{link.image_id}: timeline {row['amount']} != fact "
                f"{fact['new_amount']}"
            )
            checked += 1
    # Exactly 9 of the 15 resolved images carry an explicit currency equal
    # to their user's home currency (identity check); the rest fill from
    # the event's own currency or convert (image_12: USD -> INR). image_14
    # stays unresolved by design.
    assert checked >= 9, (
        f"only {checked} image amounts verified end-to-end in home currency"
    )


def test_image_backed_public_samples_integrate():
    """r03/r16/r17/r19/r20 timelines must contain their image-filled rows."""
    ds = DataStore()
    fx = FxGraph(ds.rates)
    for rid in ("request_03", "request_16", "request_17", "request_19",
                "request_20"):
        req = ds.request_by_id(rid)
        state = ds.build_state(req)
        facts = [interpret_image(i) for i in state.image_links]
        norm = normalize_state(state, fx, facts)
        for link in state.image_links:
            row = next((e for e in norm.events_home
                        if e["event_id"] == link.related_event_id), None)
            assert row is not None and row["amount"] is not None, (
                f"{rid}/{link.image_id}: image-backed event missing amount "
                f"in the normalized timeline"
            )


def test_dedup_collapses_image_filled_duplicate_only():
    """An image-filled row equal to a real row is dropped; CSV pairs stay."""
    from code.data.types import FinancialState, Profile, Request
    from code.finance.normalizer import _dedupe_image_duplicates

    def ev(eid, rule, amt=100.0, status="settled"):
        return ResolvedEvent(
            event_id=eid, user_id="u1", event_type="expense",
            description="groceries", category="groceries", direction="debit",
            amount=amt, currency="INR", event_date=date(2025, 1, 5),
            settlement_date=date(2025, 1, 5 + (0 if eid == "a" else 1)),
            status=status, flexibility="fixed", minimum_allowed_amount=None,
            source_event_ids=[eid], resolution_rule=rule,
        )

    log: list[str] = []
    # image-filled duplicate of a real CSV row -> collapsed
    out = _dedupe_image_duplicates(
        [ev("a", "timeline"), ev("b", "timeline;amount_from_image")], log
    )
    assert [e.event_id for e in out] == ["a"], "image duplicate must be dropped"
    # two plain CSV rows with equal amounts -> BOTH kept (no image fill)
    out2 = _dedupe_image_duplicates([ev("a", "timeline"), ev("b", "timeline")], log)
    assert len(out2) == 2, "plain CSV duplicates must never be merged"


# ---------------------------------------------------------------------------
# Causality: image data must MOVE the decision, not just parse
# ---------------------------------------------------------------------------


def _decision_for(state, fx, facts):
    norm = normalize_state(state, fx, facts)
    plans = generate_candidates(state, norm)
    return decide(state, norm, plans), norm


def test_image_data_changes_amount_safe_to_pay_request_20():
    """request_20: dropping the image-filled utility bill raises the safe
    amount (the 704.05 pending debit genuinely constrains the user)."""
    ds = DataStore()
    fx = FxGraph(ds.rates)
    req = ds.request_by_id("request_20")
    state = ds.build_state(req)
    links = state.image_links
    assert links, "request_20 must have an image link"

    d_with, _ = _decision_for(state, fx, [interpret_image(i) for i in links])
    d_without, _ = _decision_for(state, fx, [])

    assert d_with.amount_safe_to_pay != d_without.amount_safe_to_pay, (
        "image data did not affect amount_safe_to_pay (pipeline discards it)"
    )
    # The image adds a real pending debit -> paying safely means paying LESS.
    assert d_with.amount_safe_to_pay < d_without.amount_safe_to_pay


def test_net_vs_gross_salary_changes_forecast_single_slip():
    """Salary-slip causality: when the image is the ONLY salary evidence
    (blank CSV row + pay slip), the net-vs-gross pick sets the projected
    income and therefore the safe amount.

    (On request_03 itself the CSV carries 5 settled salary months, so the
    median cadence robustly absorbs the one image-filled month - by design.
    The single-slip case is where the image pick is decisive, and it must
    be the NET amount that reaches the bank.)"""
    from code.data.types import FinancialState, Profile, Request
    from code.finance.normalizer import NormalizationResult

    profile = Profile(
        user_id="u9", home_currency="IDR",
        # Tight headroom (balance - keep = 1.5M) plus a 6M scheduled rent
        # before the next salary: the projected salary credit must pull the
        # mid-path balance back above keep, so the image's net-vs-gross pick
        # is EXACTLY the difference between safe and unsafe forecasts.
        current_available_balance=6_500_000.0, minimum_balance_to_keep=5_000_000.0,
        financial_priorities=[], expense_categories_to_protect=[],
        expense_categories_user_is_willing_to_reduce=[],
        expense_categories_user_is_willing_to_stop=[],
        payment_methods_user_will_consider=["full_payment"],
        max_installment_months=None,
    )
    request = Request(
        request_id="r9", user_id="u9", request_date=date(2019, 9, 10),
        request_type="purchase", requested_amount=6_000_000.0,
        desired_completion_date=date(2019, 11, 15), allows_partial_payment=False,
        request_text="",
    )
    blank_salary = ResolvedEvent(
        event_id="event_253", user_id="u9", event_type="income",
        description="August 2019 net salary", category="salary",
        direction="credit", amount=None, currency="IDR",
        event_date=date(2019, 8, 15), settlement_date=date(2019, 8, 15),
        status="settled", flexibility="fixed", minimum_allowed_amount=None,
        source_event_ids=["event_253"], resolution_rule="timeline",
    )
    big_rent = ResolvedEvent(
        event_id="event_999", user_id="u9", event_type="expense",
        description="Outstanding rent balance", category="rent",
        direction="debit", amount=6_000_000.0, currency="IDR",
        event_date=date(2019, 9, 20), settlement_date=date(2019, 9, 20),
        status="scheduled", flexibility="fixed", minimum_allowed_amount=None,
        source_event_ids=["event_999"], resolution_rule="timeline",
    )
    state = FinancialState(
        request=request, profile=profile, events=[blank_salary, big_rent],
        messages=[], image_links=[], payment_options=[], resolution_log=[],
    )
    fact = interpret_image(_link("image_01"))
    assert fact["new_amount"] == 4365000.0  # net, not gross 4,780,800

    d_net, norm_net = _decision_for(state, FxGraph({}), [fact])
    sal_net = norm_net.cadence.get("salary", {}).get("monthly_amount")
    assert sal_net == 4365000.0, f"cadence must come from the image slip: {sal_net}"

    # Gross mispick would project more income -> larger safe amount
    # (verified: net -> 0 safe, gross -> 280,800 safe on this fixture).
    gross_fact = dict(fact, new_amount=4780800.0)
    d_gross, norm_gross = _decision_for(state, FxGraph({}), [gross_fact])
    sal_gross = norm_gross.cadence.get("salary", {}).get("monthly_amount")
    assert sal_gross == 4780800.0
    assert d_gross.amount_safe_to_pay > d_net.amount_safe_to_pay, (
        "net-vs-gross image pick did not propagate to amount_safe_to_pay"
    )


def test_image_fact_balances_survive_into_final_state_for_public_samples():
    """The orchestrator path (with event context) must keep image amounts."""
    from code.orchestrator import process_request

    ds = DataStore()
    fx = FxGraph(ds.rates)
    for rid, image_id, amount in (
        ("request_03", "image_01", 4365000.0),
        ("request_16", "image_02", 100000.0),
        ("request_20", "image_05", 704.05),
    ):
        req = ds.request_by_id(rid)
        res = process_request(ds, fx, req)
        row = next((e for e in res.norm.events_home
                    if e["event_id"] == next(
                        l.related_event_id for l in
                        ds.build_state(req).image_links
                        if l.image_id == image_id)), None)
        assert row is not None and row["amount"] is not None, rid
        # event_253 is IDR and user_03's home currency is IDR: identity.
        if res.state.profile.home_currency == "IDR" and rid == "request_03":
            assert abs(row["amount"] - amount) < 0.01
