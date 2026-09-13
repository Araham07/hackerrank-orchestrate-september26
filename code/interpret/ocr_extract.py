"""OCR fact extraction helpers (deterministic).

Handles the number formats actually present in dataset receipts:
- western grouping:       1,234,567.89
- Indian grouping:        2,00,000.00
- dotted-Indian:          1.00.000.00  (OCR renders commas as dots)
- European decimal comma: 5.000,00     (rare OCR fallback)
- plain:                  1234.56
Amounts may or may not carry a currency prefix (IDR / INR / Rs / $ ...).

Selection model (v2 - semantic, candidate-based):

1. Every number in the document becomes a CANDIDATE with:
     amount, currency, label (nearest text), semantic_type, confidence.
   Semantic types: gross_income | net_income | amount_due | balance_due |
   amount_paid | purchase_total | subtotal | tax | refund | fee | other.

2. Garbage guard: tokens mixing digits and letters that are not a known
   currency prefix ("4s43o" from a handwritten receipt) are rejected.
   Date fragments (years, day numbers) never become amounts.

3. The LINKED EVENT supplies context (description/category). Net-income
   markers outrank gross markers when the event mentions "net"; for
   outstanding-balance events, balance-due/amount-due markers outrank
   invoice totals; plain purchases prefer grand total / total paid.

4. Output: the best candidate under the context-aware scorer, plus the
   full candidate list for debugging/audit.

Confidence tiers:  HIGH >= 0.75, MEDIUM 0.5-0.74, LOW < 0.5.
LOW candidates are only used when nothing better exists and are flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_CURRENCY = r"(INR|IDR|USD|EUR|ZAR)"
_MONEY_RE = re.compile(
    _CURRENCY + r"\s*[:#]?\.?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.I
)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_NUMBER_TOKEN_RE = re.compile(r"(?<![0-9.])([0-9][0-9.,]*[0-9])(?![0-9])")

# Total-marker strengths. (?<!sub) keeps "SubTotal" out of the strong gate
# (subtotals are line aggregates, not the payable total).
_STRONG_TOTAL_RE = re.compile(r"(?<!sub)total(?:amount|amt|bill|due|payable)?|amountdue|balancedue|jumlah|tagihan|grandtotal|netpay|takehome|netamount", re.I)
_WEAK_TOTAL_RE = re.compile(r"(amountdue|balancedue|jumlah|tagihan|dueamount|outstanding)", re.I)
_BALANCE_DUE_RE = re.compile(r"(balancedue|dueamount|outstanding|amountdue)", re.I)

# Semantic marker sets (context-aware selection, spec section 4).
_NET_RE = re.compile(r"(netpay|netamount|netsalary|takehome|transferredto)", re.I)
_GROSS_RE = re.compile(r"(grossexp|grossearning|subtotal.?earnings|totalearnings|grosssalary|subtotalearnings|totaldeduction)", re.I)
_PAID_RE = re.compile(r"(cashpaid|amountpaid|amountreceived|totalamountreceived|paid|transferredto)", re.I)
_TAX_RE = re.compile(r"(gst|sgst|cgst|igst|cess|tax\b|taxes)", re.I)
_SUBTOTAL_RE = re.compile(r"(subtotal|itemtotal|taxablevalue)", re.I)
_FEE_RE = re.compile(r"(fee|surcharge|charge)", re.I)

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

# Garbage guard: OCR noise like "4s43o" (digit-letter soup). A token whose
# characters are not all digits/separators after prefix stripping is rejected.
_CLEAN_TOKEN_RE = re.compile(r"^[0-9][0-9.,]*$")

# Amount-in-words cross-check: "Four Million ... SixtyFive Thousand Rupiahs"
_WORDS_TOTAL_RE = re.compile(
    r"(amountinwords|inwords|amount words)", re.I
)


@dataclass
class Candidate:
    """One monetary value found in the document."""

    amount: float
    currency: str | None
    label: str            # the line text the number was found on
    semantic_type: str    # see module docstring
    confidence: float
    line_no: int
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "currency": self.currency,
            "label": self.label,
            "semantic_type": self.semantic_type,
            "confidence": self.confidence,
            "line_no": self.line_no,
            "reason": self.reason,
        }


# Address/institutional lines whose numbers are never amounts (pincodes,
# street numbers, phone heads). Matched against the VALUE line during walk.
_ADDRESS_LINE_RE = re.compile(
    r"(bangalore|bengaluru|pune|mumbai|delhi|chennai|hyderabad|karnataka|"
    r"tamilnadu|tnagar|sector|layout|stage|cross|block|floor|road|\brd\b|"
    r"suite|pincode|\bpin\b|address)",
    re.I,
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


def _is_garbage_token(token: str) -> bool:
    """Reject OCR letter-digit soup that slipped into a number position.

    "4s43o", "00'0", "6E-861" style tokens are not amounts. A valid token
    contains only digits and , . separators (checked after stripping).
    """
    return not _CLEAN_TOKEN_RE.fullmatch(token)


def _is_id_like(token: str) -> bool:
    """Reject long unseparated digit runs: phone numbers, transaction IDs.

    Real monetary amounts in these documents are either formatted with
    separators ("28,499,994") or short ("9968"). A bare run of >= 7 digits
    with no separators is a phone/account/transaction identifier.
    """
    if "." in token or "," in token:
        return False
    return len(token) >= 7


def _is_date_fragment(match: re.Match, text: str, val: float) -> bool:
    token = match.group(1)
    # Bare 1-2 digit numbers below 10 are day/qty fragments, not totals.
    if val < 10:
        return True
    # 4-digit year-like tokens are NEVER amounts ("2026" from 06-Feb-2026).
    int_part = token.split(".")[0].split(",")[0]
    if re.fullmatch(r"\d{4}", int_part) and 1900 <= val <= 2099:
        return True
    # Other tokens near date separators: only year-like tokens are dates.
    # (Dotted-Indian amounts like 1.00.000.00 match the date-context shape
    # themselves - they must NOT be rejected as dates.)
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
    if re.search(r"\$\s*[0-9]", text):
        return "USD"
    return None


# ---------------------------------------------------------------------------
# Candidate building
# ---------------------------------------------------------------------------


def _semantic_type(line: str) -> tuple[str, float]:
    """Classify one line -> (semantic_type, confidence_delta)."""
    squashed = line.replace(" ", "")
    if _NET_RE.search(squashed):
        return "net_income", 0.15
    if _GROSS_RE.search(squashed):
        return "gross_income", 0.0
    if _BALANCE_DUE_RE.search(squashed):
        return "balance_due", 0.15
    if _PAID_RE.search(squashed) and _STRONG_TOTAL_RE.search(squashed):
        return "amount_paid", 0.1
    if _TAX_RE.search(squashed):
        return "tax", 0.0
    if _SUBTOTAL_RE.search(squashed):
        return "subtotal", 0.05
    if _FEE_RE.search(squashed):
        return "fee", 0.0
    if _WEAK_TOTAL_RE.search(squashed):
        return "amount_due", 0.12
    if _STRONG_TOTAL_RE.search(squashed):
        return "purchase_total", 0.1
    return "other", 0.0


def build_candidates(text: str) -> list[Candidate]:
    """Every defensible monetary value in the document, with semantics."""
    lines = text.splitlines()
    out: list[Candidate] = []
    default_cur = _infer_currency(text)

    # Currency-prefixed candidates first (highest structural confidence).
    for m in _MONEY_RE.finditer(text):
        val = parse_number_token(m.group(2))
        if val is None or val < 10:
            continue
        if _is_id_like(m.group(2)):
            continue
        if _is_date_fragment(m, text, val):
            continue
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start: line_end if line_end != -1 else len(text)]
        line_no = text.count("\n", 0, m.start())
        stype, delta = _semantic_type(line)
        out.append(Candidate(
            amount=val, currency=m.group(1).upper(), label=line.strip()[:80],
            semantic_type=stype,
            confidence=round(min(0.55 + delta + (0.15 if stype != "other" else 0.0), 0.9), 2),
            line_no=line_no,
            reason=f"currency-prefixed ({stype})",
        ))

    # Bare candidates from marker lines (and the amount line the marker
    # points at). The MARKER's semantic type is propagated to the amount:
    # receipts commonly put the value one or more lines below its label
    # ("Balance Due:\n1.00.000.00"), and the value line itself carries no
    # semantics of its own.
    for idx, line in enumerate(lines):
        squashed_line = line.replace(" ", "")
        strong = bool(_STRONG_TOTAL_RE.search(squashed_line))
        weak = bool(_WEAK_TOTAL_RE.search(squashed_line))
        netmarker = bool(_NET_RE.search(squashed_line))
        if not (strong or weak or netmarker):
            continue
        marker_type, marker_delta = _semantic_type(line)
        if netmarker and marker_type == "other":
            marker_type, marker_delta = "net_income", 0.15
        # "Amount due after <date>" is the CONDITIONAL late amount (only
        # owed if the user misses the due date); it is not yet payable.
        if "dueafter" in squashed_line:
            marker_type, marker_delta = "conditional_due", 0.10

        def _emit(ln: str, walk_pos: int) -> None:
            for m in _NUMBER_TOKEN_RE.finditer(ln):
                token = m.group(1)
                if _is_garbage_token(token):
                    continue
                if _is_id_like(token):
                    continue
                val = parse_number_token(token)
                if val is None or val < 10:
                    continue
                if _is_date_fragment(m, ln, val):
                    continue
                out.append(Candidate(
                    amount=val,
                    currency=_infer_currency(ln) or default_cur,
                    label=f"{line.strip()[:40]} >> {ln.strip()[:40]}".strip(),
                    semantic_type=marker_type,
                    # Closer value lines are more likely the marker's own
                    # amount (receipts put the value directly beneath it).
                    confidence=round(min(0.45 + marker_delta + 0.04 * (4 - walk_pos), 0.85), 2),
                    line_no=idx,
                    reason=f"amount under '{line.strip()[:30]}' marker",
                ))

        # 1) Numbers on the marker line itself ("Total: 8528.10").
        _emit(line, 0)
        # 2) Walk forward: values commonly sit on the next line(s). Stop at
        #    an intermediate line carrying its own semantic label (Taxes /
        #    Subtotal / Paid / ...) - the numbers after it belong to THAT
        #    label, not to our marker. Skip digit-less non-semantic filler;
        #    stop dead at digit-bearing noise lines (invoice no, phone...).
        #    Address lines (pincodes, street numbers) are never amount
        #    carriers and are skipped, not walk-stoppers.
        collected = 0
        for offset, nxt in enumerate(lines[idx + 1: idx + 8], start=1):
            sq_next = nxt.replace(" ", "")
            if re.search(r"\d", sq_next):
                if _ADDRESS_LINE_RE.search(sq_next):
                    continue
                if _NOISE_LINE_RE.search(sq_next) and not _STRONG_TOTAL_RE.search(sq_next):
                    break
                _emit(nxt, offset)
                collected += 1
                if collected >= 3:
                    break
                continue
            # digit-less line: stop if it redirects semantics
            if (_TAX_RE.search(sq_next) or _SUBTOTAL_RE.search(sq_next)
                    or _GROSS_RE.search(sq_next) or _PAID_RE.search(sq_next)
                    or _FEE_RE.search(sq_next)):
                break

    # De-duplicate identical (amount, semantic_type) pairs.
    seen: set[tuple[float, str]] = set()
    uniq: list[Candidate] = []
    for c in out:
        key = (c.amount, c.semantic_type)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


# ---------------------------------------------------------------------------
# Event-context-aware selection
# ---------------------------------------------------------------------------

# Event-description hints (general, not per-request).
_EVENT_NET_RE = re.compile(r"\bnet\b", re.I)
_EVENT_OUTSTANDING_RE = re.compile(r"outstanding|due|payable|balance", re.I)
_EVENT_ORDER_RE = re.compile(r"order|purchase|bought|fare|payment", re.I)


def select_candidate(
    candidates: list[Candidate],
    event_description: str = "",
    event_category: str = "",
) -> Candidate | None:
    """Pick the best candidate given the linked event's semantics.

    Rules (general):
    - income/salary documents: net_income > amount_paid > purchase_total >
      gross_income (net reaches the bank; gross does not).
    - outstanding/due events: balance_due > amount_due > purchase_total.
    - plain purchases: purchase_total > amount_paid > balance_due; subtotals,
      tax lines and 'other' are demoted.
    """
    if not candidates:
        return None
    desc = f"{event_description} {event_category}".lower()
    wants_net = bool(_EVENT_NET_RE.search(desc))
    wants_due = bool(_EVENT_OUTSTANDING_RE.search(desc)) and not _EVENT_ORDER_RE.search(desc)

    def score(c: Candidate) -> float:
        s = c.confidence
        if "salary" in desc or "income" in desc or wants_net:
            rank = {"net_income": 0.5, "amount_paid": 0.25, "purchase_total": 0.1,
                    "gross_income": -0.5, "subtotal": -0.2, "tax": -0.3,
                    "conditional_due": -0.25}
        elif wants_due:
            rank = {"balance_due": 0.5, "amount_due": 0.35, "amount_paid": 0.05,
                    "purchase_total": 0.0, "subtotal": -0.2, "tax": -0.3,
                    "conditional_due": -0.25}
        else:
            rank = {"purchase_total": 0.5, "amount_paid": 0.3, "amount_due": 0.15,
                    "balance_due": 0.1, "net_income": 0.1,
                    "subtotal": -0.4, "tax": -0.5, "fee": -0.3,
                    "conditional_due": -0.25}
        s += rank.get(c.semantic_type, 0.0)
        # Cross-doc tiebreak inside a type: larger value is the doc total
        # (line-item MRPs carry no marker and land in 'other' anyway).
        return s

    best = max(
        candidates,
        key=lambda c: (score(c), c.amount),  # type: ignore[return-value]
    )
    return best


def _words_total(text: str) -> float | None:
    """Parse the document's printed amount-in-words (disambiguation aid).

    Invoices print the total in words precisely so the numeric total can be
    verified; OCR rarely corrupts words as easily as digit groups. Best
    effort: recognizes hundred/thousand/lakh/million plus 0-90 word terms,
    CamelCase-glued words ("NinetyFive"), an optional paise tail, and
    rupee/rupiah boundaries. Returns None when the phrase is absent or the
    parse is incomplete (unknown words) - a partial parse never overrides.
    """
    flat = re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " "))
    if not re.search(r"amount\s*in\s*words|in\s*words|amount\s*in\b", flat, re.I):
        return None
    # OCR sometimes drops the literal word "words" ("Amount in One
    # Thousand..."). The strict words-parse below guards the loose marker:
    # garbage captures ("Amount in INR", "Amount in figures") fail the
    # parse and yield None, never an override.
    m = re.search(
        r"(?:amount\s*in\s*words|in\s*words|amount\s*in)\s*:?\s*"
        r"([A-Za-z][A-Za-z\- ]{10,160})",
        flat, re.I,
    )
    if not m:
        return None
    segment = re.sub(r"([a-z])([A-Z])", r"\1 \2", m.group(1))
    # Currency words appear BEFORE the numbers ("Indian Rupee Seventy-Nine
    # Thousand") or after them ("... Rupees And Zero Paise"); strip them
    # anywhere, then treat a trailing paise tail separately.
    segment = re.sub(r"\b(indian\s+)?rupees?\b|\brupiahs?\b", " ",
                     segment, flags=re.I)
    head = segment.lower()
    words = re.findall(r"[a-z]+", head)
    units = {
        "hundred": 100,
        "thousand": 1_000,
        "lakh": 100_000,
        "lac": 100_000,
        "million": 1_000_000,
    }
    ones = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
        "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    }
    # Split rupee words from paise words at the LAST 'and' before a
    # paise/paisa word ("... Seventy-Nine and Twenty-Six Paise Only").
    paise_val = 0.0
    if "pais" in head:
        if " and " in head:
            head, paise_head = head.rsplit(" and ", 1)
        else:
            paise_head = ""
        for w in re.findall(r"[a-z]+", paise_head):
            if w.startswith("pais"):
                break
            if w in ones:
                paise_val += ones[w]
            elif w in ("and", "only"):
                continue
            else:
                break
    total = 0
    current = 0
    matched = 0
    for w in re.findall(r"[a-z]+", head):
        if w in ones:
            current += ones[w]
            matched += 1
        elif w in units:
            total += (current or 1) * units[w]
            current = 0
            matched += 1
        elif w in ("and", "only"):
            continue
        else:
            break  # unknown word: stop (conservative)
    value = total + current + paise_val / 100.0
    if matched == 0 or value <= 0:
        return None
    return float(value)


def select_candidate_key(c: Candidate) -> float:
    """Standalone ranker used to re-rank typed candidates for words-check."""
    return c.confidence + {"purchase_total": 0.5, "amount_paid": 0.3,
                           "balance_due": 0.3, "amount_due": 0.3,
                           "net_income": 0.5}.get(c.semantic_type, 0.0)


def extract_facts_v2(
    text: str,
    event_description: str = "",
    event_category: str = "",
) -> dict[str, Any]:
    """Full v2 extraction: candidates + context-aware selection."""
    candidates = build_candidates(text)
    best = select_candidate(candidates, event_description, event_category)
    dates = _DATE_RE.findall(text)
    if best is None:
        return {
            "action": "none",
            "new_amount": None,
            "new_currency": None,
            "confidence": 0.2,
            "confidence_tier": None,
            "semantic_type": None,
            "candidates": [c.as_dict() for c in candidates],
            "note": "no defensible amount candidate in OCR text",
        }

    # Amount-in-words cross-check: if the words parse cleanly and disagree
    # with the selected number, the words win (they are printed precisely
    # to disambiguate the total; e.g. grand total vs an MRP column value).
    words_val = _words_total(text)
    words_note = ""
    if words_val is not None and abs(words_val - best.amount) > max(0.01, 0.002 * words_val):
        typed = [c for c in candidates
                 if abs(c.amount - words_val) <= max(0.01, 0.002 * words_val)
                 and c.semantic_type not in ("tax", "subtotal")]
        repl = max(typed, key=select_candidate_key, default=None) if typed else None
        if repl is not None:
            best = repl
            words_note = "; corrected by amount-in-words"
        else:
            synth = Candidate(
                amount=words_val,
                currency=best.currency,
                label="amount in words",
                semantic_type="purchase_total"
                if best.semantic_type not in ("net_income", "balance_due", "amount_due")
                else best.semantic_type,
                confidence=0.8,
                line_no=-1,
                reason="parsed from the document's printed amount-in-words",
            )
            best = synth
            words_note = "; taken from amount-in-words"
    elif words_val is not None:
        words_note = "; verified against amount-in-words"
    conf = best.confidence
    # Handwritten / low-OCR-quality documents: cap confidence.
    if re.search(r"handwritten|manual", text, re.I):
        conf = min(conf, 0.45)
    tier = "HIGH" if conf >= 0.75 else ("MEDIUM" if conf >= 0.5 else "LOW")
    # Never fabricate: a LOW-confidence candidate with no meaningful
    # semantic marker (garbage OCR on a handwritten slip) is rejected.
    if tier == "LOW" and best.semantic_type in ("other", "tax", "subtotal",
                                                 "gross_income", "fee"):
        return {
            "action": "none",
            "new_amount": None,
            "new_currency": None,
            "confidence": round(conf, 2),
            "confidence_tier": tier,
            "semantic_type": best.semantic_type,
            "candidates": [c.as_dict() for c in candidates],
            "note": (f"only LOW-confidence '{best.semantic_type}' candidate "
                     f"({best.amount}); amount left unresolved rather than "
                     f"guessed"),
        }
    return {
        "action": "amend_amount",
        "new_amount": best.amount,
        "new_currency": best.currency,
        "new_date": dates[0] if dates else None,
        "confidence": round(conf, 2),
        "confidence_tier": tier,
        "semantic_type": best.semantic_type,
        "candidates": [c.as_dict() for c in candidates],
        "note": f"{best.reason}{words_note}; tier={tier}",
    }


def extract_facts(text: str) -> dict[str, Any]:
    """Back-compat wrapper (no event context)."""
    return extract_facts_v2(text)
