"""OCR fact extraction helpers (deterministic).

Handles the number formats actually present in dataset receipts:
- western grouping:       1,234,567.89
- Indian grouping:        2,00,000.00
- dotted-Indian:          1.00.000.00  (OCR renders commas as dots)
- European decimal comma: 5.000,00     (rare OCR fallback)
- plain:                  1234.56
Amounts may or may not carry a currency prefix (IDR / INR / Rs / ...).

Selection logic:
1. Currency-prefixed amounts are preferred; among them, the one nearest a
   total marker (or the largest) wins.
2. Otherwise, bare amounts on/near lines carrying a total-strength marker:
   strength 3 = "total"/"net amount"/"grand total" lines,
   strength 2 = "amount due"/"balance due"/"jumlah"/"tagihan"/"netpay".
   Noise lines (tax, qty, invoice no, ...) are skipped unless the line also
   carries a strong total marker ("Total Amount Received" is a real total).
   Date fragments (years near date separators, day numbers) are dropped.
"""

from __future__ import annotations

import re
from typing import Any

_CURRENCY = r"(INR|IDR|USD|EUR|ZAR)"
_MONEY_RE = re.compile(
    _CURRENCY + r"\s*[:#]?\.?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.I
)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_NUMBER_TOKEN_RE = re.compile(r"(?<![0-9.])([0-9][0-9.,]*[0-9])(?![0-9])")

# Total-marker strengths.
_STRONG_TOTAL_RE = re.compile(r"(total|netamount|grandtotal|netpay|takehome)", re.I)
# "Balance due" outranks "total" for outstanding-balance events: a receipt
# can show Total (incl. already-received) AND Balance Due (actually owed).
_WEAK_TOTAL_RE = re.compile(
    r"(amountdue|balancedue|jumlah|tagihan|dueamount|outstanding)", re.I
)
_BALANCE_DUE_RE = re.compile(r"(balancedue|dueamount|outstanding|amountdue)", re.I)

# Noise markers disqualifying a line UNLESS a strong total marker is present.
_NOISE_LINE_RE = re.compile(
    r"(gst|tax|qty|mrp|unit|price|discount|received|paid|change|cash|"
    r"invoice\s*no|bill\s*no|receipt\s*no|phone|gstin|ref\s*no)",
    re.I,
)

# Date-like contexts used to drop year fragments from candidates.
_DATE_CONTEXT_RE = re.compile(
    r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})|(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})"
)


def parse_number_token(raw: str) -> float | None:
    """Convert a number-like token to float across all observed formats."""
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None

    dots = s.count(".")
    commas = s.count(",")

    # Only dots (no commas)
    if commas == 0:
        if dots == 0:
            try:
                return float(s)
            except ValueError:
                return None
        last_dot = s.rfind(".")
        frac = s[last_dot + 1:]
        if len(frac) == 2:
            if dots == 1:
                try:
                    return float(s)
                except ValueError:
                    return None
            # multiple dots, 2-digit tail: dotted-Indian "1.00.000.00"
            groups = s.split(".")
            if all(len(g) in (1, 2, 3) for g in groups[:-1]):
                whole = "".join(groups[:-1])
                try:
                    return float(whole + "." + frac)
                except ValueError:
                    return None
        # All dots are thousands separators ("5.000.000").
        whole = s.replace(".", "")
        try:
            return float(whole)
        except ValueError:
            return None

    if dots == 0:
        # Commas only.
        parts = s.split(",")
        last = parts[-1]
        if len(parts) == 2 and len(last) == 2 and len(parts[0]) <= 3:
            # "5,00" European-style decimal comma
            try:
                return float(parts[0] + "." + last)
            except ValueError:
                return None
        whole = "".join(parts)
        try:
            return float(whole)
        except ValueError:
            return None

    # Both separators: whichever comes LAST is the decimal point.
    last_dot = s.rfind(".")
    last_comma = s.rfind(",")
    if last_dot > last_comma:
        head, frac = s[:last_dot], s[last_dot + 1:]
    else:
        head, frac = s[:last_comma], s[last_comma + 1:]
    try:
        return float(head.replace(".", "").replace(",", "") + "." + frac)
    except ValueError:
        return None


def _year_like(token: str, val: float, context: str) -> bool:
    """True if the token is almost certainly a date fragment, not an amount."""
    int_part = token.split(".")[0].split(",")[0]
    if not (re.fullmatch(r"\d{4}", int_part) and 1900 <= val <= 2099):
        return False
    # Year tokens standing alone (Pay Slip Aug-2019) or beside date
    # separators (27/02/2026, 06-Feb-2026 handled by OCR guard) are dates.
    return True


def _is_date_fragment(match: re.Match, text: str, val: float) -> bool:
    token = match.group(1)
    # Bare 1-2 digit numbers below 10 are day/qty fragments, not totals.
    if val < 10:
        return True
    start, end = match.start(), match.end()
    window = text[max(0, start - 14): end + 14]
    if _DATE_CONTEXT_RE.search(window):
        # Any 4-digit year-like token near date separators is a date part.
        int_part = token.split(".")[0].split(",")[0]
        if re.fullmatch(r"\d{4}", int_part) and 1900 <= val <= 2099:
            return True
    return False


def _infer_currency(text: str) -> str | None:
    """Best-effort currency for bare amounts: explicit code or rupee context."""
    m = re.search(r"\b(INR|IDR|USD|EUR|ZAR)\b", text, re.I)
    if m:
        return m.group(1).upper()
    if re.search(r"rupees|₹|\brs\.?\b", text, re.I):
        return "INR"
    if re.search(r"rupiah|\brp\.?\b", text, re.I):
        return "IDR"
    return None


def extract_facts(text: str) -> dict[str, Any]:
    """Deterministic amount/date extraction from OCR text."""
    squashed = text.replace(" ", "").replace("\n", " ")
    lines = text.splitlines()

    # --- Path 1: currency-prefixed amounts --------------------------------
    prefixed: list[tuple[str, float, bool]] = []
    for m in _MONEY_RE.finditer(text):
        val = parse_number_token(m.group(2))
        if val is None:
            continue
        window = squashed[max(0, m.start() - 40): m.end() + 10].replace(" ", "")
        prefixed.append((m.group(1).upper(), val, bool(_STRONG_TOTAL_RE.search(window))))

    if prefixed:
        best = max(prefixed, key=lambda a: (a[2], a[1]))
        confidence = 0.75 if best[2] else 0.55
        return _finish(best[1], best[0], text, confidence, "prefixed amount")

    # --- Path 2: bare amounts near total-marker lines ---------------------
    # (strength, value) candidates
    candidates: list[tuple[int, float]] = []
    for idx, line in enumerate(lines):
        squashed_line = line.replace(" ", "")
        strong = bool(_STRONG_TOTAL_RE.search(squashed_line))
        weak = bool(_WEAK_TOTAL_RE.search(squashed_line))
        balance_due = bool(_BALANCE_DUE_RE.search(squashed_line))
        if not (strong or weak):
            continue
        strength = 4 if balance_due else (3 if strong else 2)
        noisy = bool(_NOISE_LINE_RE.search(squashed_line))
        if noisy and not strong:
            continue  # noise line without a strong total marker: skip
        # Amount on the marker line itself...
        found = _collect_numbers(line, text, strength, candidates)
        # ...or walk forward: stop at the first line containing numbers
        # (collect them), skipping digit-less lines; stop dead at a
        # digit-bearing noise line.
        if not found:
            for nxt in lines[idx + 1: idx + 5]:
                squashed_next = nxt.replace(" ", "")
                has_digits = bool(re.search(r"\d", squashed_next))
                if not has_digits:
                    continue
                if _NOISE_LINE_RE.search(squashed_next) and not (
                    _STRONG_TOTAL_RE.search(squashed_next)
                ):
                    break
                found = _collect_numbers(nxt, text, strength, candidates)
                break

    if candidates:
        strength, amount = max(candidates, key=lambda c: (c[0], c[1]))
        confidence = 0.6 if strength >= 3 else 0.45
        return _finish(amount, _infer_currency(text), text, confidence,
                       f"bare amount (strength {strength})")

    return {
        "action": "none",
        "new_amount": None,
        "new_currency": None,
        "confidence": 0.2,
        "note": "no amount pattern found in OCR text",
    }


def _collect_numbers(line: str, full_text: str, strength: int,
                     candidates: list[tuple[int, float]]) -> bool:
    """Add number candidates from one line; return True if any were added."""
    found = False
    for m in _NUMBER_TOKEN_RE.finditer(line):
        val = parse_number_token(m.group(1))
        if val is None or val < 10:
            continue
        if _is_date_fragment(m, line, val):
            continue
        candidates.append((strength, val))
        found = True
    return found


def _finish(amount: float, currency: str | None, text: str,
            confidence: float, note: str) -> dict[str, Any]:
    dates = _DATE_RE.findall(text)
    return {
        "action": "amend_amount",
        "new_amount": amount,
        "new_currency": currency,
        "new_date": dates[0] if dates else None,
        "confidence": round(min(confidence + 0.05, 0.85), 2),
        "note": note,
    }
