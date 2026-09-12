"""Load all dataset CSVs into typed records.

Pure stdlib implementation (no pandas dependency) using csv.DictReader.
A blank amount parses to None - never zero.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any

from code.config import (
    CSV_EVENTS, CSV_IMAGES, CSV_MESSAGES, CSV_OPTIONS, CSV_PROFILES,
    CSV_RATES, CSV_REQUESTS, CSV_SAMPLES, IMAGES_DIR,
)
from code.data.types import (
    Event, ImageLink, Message, PaymentOption, Profile, Request,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset file: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

def parse_float(value):
    """Parse a decimal amount; blank/None -> None (NOT zero)."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    try:
        return float(v.replace(",", ""))
    except ValueError:
        return None


def parse_int(value):
    f = parse_float(value)
    return None if f is None else int(round(f))


def parse_date(value):
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def parse_datetime(value):
    """Parse ISO-8601 timestamps like 2025-07-29T09:30:00Z."""
    if not value or not value.strip():
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def parse_split(value):
    """Parse a pipe-separated list field; blank -> []."""
    if not value:
        return []
    return [p.strip() for p in value.split("|") if p.strip()]


# ---------------------------------------------------------------------------
# Loaders (one per dataset file)
# ---------------------------------------------------------------------------

def load_profiles():
    rows = _read_csv(CSV_PROFILES)
    out = {}
    for r in rows:
        out[r["user_id"].strip()] = Profile(
            user_id=r["user_id"].strip(),
            home_currency=r["home_currency"].strip(),
            current_available_balance=parse_float(r["current_available_balance"]) or 0.0,
            minimum_balance_to_keep=parse_float(r["minimum_balance_to_keep"]) or 0.0,
            financial_priorities=parse_split(r.get("financial_priorities")),
            expense_categories_to_protect=parse_split(r.get("expense_categories_to_protect")),
            expense_categories_user_is_willing_to_reduce=parse_split(
                r.get("expense_categories_user_is_willing_to_reduce")
            ),
            expense_categories_user_is_willing_to_stop=parse_split(
                r["expense_categories_user_is_willing_to_stop"]
            ),
            payment_methods_user_will_consider=parse_split(
                r.get("payment_methods_user_will_consider")
            ),
            max_installment_months=parse_int(r.get("max_installment_months")),
        )
    return out


def load_events():
    out = []
    for r in _read_csv(CSV_EVENTS):
        out.append(Event(
            event_id=r["event_id"].strip(),
            user_id=r["user_id"].strip(),
            event_type=r["event_type"].strip().lower(),
            description=r.get("description", "").strip(),
            category=r.get("category", "").strip().lower(),
            direction=r.get("direction", "").strip().lower(),
            amount=parse_float(r.get("amount")),
            currency=r.get("currency", "").strip().upper(),
            event_date=parse_date(r.get("event_date")),
            settlement_date=parse_date(r.get("settlement_date")),
            status=r.get("status", "").strip().lower(),
            linked_event_id=(r.get("linked_event_id") or "").strip() or None,
            flexibility=r.get("flexibility", "").strip().lower(),
            minimum_allowed_amount=parse_float(r.get("minimum_allowed_amount")),
        ))
    return out


def load_exchange_rates():
    """Return {(rate_date, from_currency, to_currency): rate}."""
    rates = {}
    for r in _read_csv(CSV_RATES):
        d = parse_date(r["rate_date"])
        if d is None:
            continue
        key = (d, r["from_currency"].strip().upper(), r["to_currency"].strip().upper())
        rates[key] = float(r["rate"])
    return rates


def load_requests():
    out = []
    for r in _read_csv(CSV_REQUESTS):
        out.append(Request(
            request_id=r["request_id"].strip(),
            user_id=r["user_id"].strip(),
            request_date=parse_date(r.get("request_date")),
            request_type=r.get("request_type", "").strip().lower(),
            requested_amount=parse_float(r.get("requested_amount")) or 0.0,
            desired_completion_date=parse_date(r.get("desired_completion_date")),
            allows_partial_payment=(
                r.get("allows_partial_payment", "").strip().lower() == "true"
            ),
            request_text=r.get("request_text", ""),
        ))
    return out


def load_sample_requests_typed():
    """Sample rows as Request objects (input columns only)."""
    out = []
    for r in _read_csv(CSV_SAMPLES):
        out.append(Request(
            request_id=r["request_id"].strip(),
            user_id=r["user_id"].strip(),
            request_date=parse_date(r.get("request_date")),
            request_type=r.get("request_type", "").strip().lower(),
            requested_amount=parse_float(r.get("requested_amount")) or 0.0,
            desired_completion_date=parse_date(r.get("desired_completion_date")),
            allows_partial_payment=(
                r.get("allows_partial_payment", "").strip().lower() == "true"
            ),
            request_text=r.get("request_text", ""),
        ))
    return out


def load_sample_requests():
    return _read_csv(CSV_SAMPLES)


def load_payment_options():
    out = []
    for r in _read_csv(CSV_OPTIONS):
        out.append(PaymentOption(
            payment_option_id=r["payment_option_id"].strip(),
            request_id=r["request_id"].strip(),
            payment_method=r.get("payment_method", "").strip().lower(),
            payment_amount=parse_float(r.get("payment_amount")) or 0.0,
            number_of_payments=parse_int(r.get("number_of_payments")) or 1,
            first_payment_date=parse_date(r.get("first_payment_date")),
            payment_frequency_days=parse_int(r.get("payment_frequency_days")),
            financing_fee=parse_float(r.get("financing_fee")) or 0.0,
            total_payable_amount=parse_float(r.get("total_payable_amount")) or 0.0,
        ))
    return out


def load_messages():
    out = []
    for r in _read_csv(CSV_MESSAGES):
        out.append(Message(
            message_id=r["message_id"].strip(),
            user_id=r["user_id"].strip(),
            request_id=(r.get("request_id") or "").strip() or None,
            related_event_id=(r.get("related_event_id") or "").strip() or None,
            sent_at=parse_datetime(r.get("sent_at")),
            source_type=r.get("source_type", "").strip().lower(),
            message_text=r.get("message_text", ""),
        ))
    return out


def load_image_links():
    out = []
    for r in _read_csv(CSV_IMAGES):
        out.append(ImageLink(
            image_id=r["image_id"].strip(),
            user_id=r["user_id"].strip(),
            request_id=(r.get("request_id") or "").strip() or None,
            related_event_id=(r.get("related_event_id") or "").strip() or None,
        ))
    return out


# ---------------------------------------------------------------------------
# Phase 1 audit
# ---------------------------------------------------------------------------

def dataset_summary():
    """Load everything; return row counts + integrity flags (Phase 1 audit)."""
    profiles = load_profiles()
    events = load_events()
    rates = load_exchange_rates()
    requests = load_requests()
    samples = load_sample_requests()
    options = load_payment_options()
    messages = load_messages()
    image_links = load_image_links()

    image_by_event = {i.related_event_id: i for i in image_links if i.related_event_id}
    blank_amount_events = [e for e in events if e.amount is None]
    blank_without_image = [
        e for e in blank_amount_events if e.event_id not in image_by_event
    ]
    missing_files = []
    for e in blank_amount_events:
        link = image_by_event.get(e.event_id)
        if link and not (IMAGES_DIR / (link.image_id + ".png")).exists():
            missing_files.append((e.event_id, link.image_id))

    return {
        "profiles": len(profiles),
        "events": len(events),
        "rates": len(rates),
        "requests": len(requests),
        "samples": len(samples),
        "payment_options": len(options),
        "messages": len(messages),
        "image_links": len(image_links),
        "image_files_on_disk": len(list(IMAGES_DIR.glob("*.png"))),
        "blank_amount_events": len(blank_amount_events),
        "blank_amount_without_image_link": len(blank_without_image),
        "blank_amount_image_file_missing": len(missing_files),
        "blank_amount_event_ids": [e.event_id for e in blank_amount_events],
        "users_with_events_missing_profile": sorted(
            {e.user_id for e in events} - set(profiles)
        ),
        "requests_missing_profile": sorted(
            {r.user_id for r in requests} - set(profiles)
        ),
        "message_languages": sorted({_guess_language(m.message_text) for m in messages}),
    }


def _guess_language(text):
    """Very rough heuristic for the audit log only (id vs en)."""
    markers_id = (" yang ", " dengan ", " untuk ", "gaji", "sudah", "akan", " dan ")
    t = " " + text.lower() + " "
    return "id" if any(m in t for m in markers_id) else "en"
