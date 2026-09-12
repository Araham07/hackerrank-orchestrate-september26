"""Typed records for every dataset entity.

Dataclasses keep the rest of the pipeline honest about field names and
None-vs-zero semantics (a blank amount is None, never 0.0).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    financial_priorities: list[str]
    expense_categories_to_protect: list[str]
    expense_categories_user_is_willing_to_reduce: list[str]
    expense_categories_user_is_willing_to_stop: list[str]
    payment_methods_user_will_consider: list[str]
    max_installment_months: int | None  # blank => user won't consider installments


@dataclass
class Event:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str  # debit | credit
    amount: float | None  # None => blank in CSV, must come from image
    currency: str
    event_date: date | None
    settlement_date: date | None
    status: str  # settled | pending | scheduled | failed | cancelled | unrealized
    linked_event_id: str | None
    flexibility: str  # fixed | flexible | reducible | stoppable ...
    minimum_allowed_amount: float | None


@dataclass
class Request:
    request_id: str
    user_id: str
    request_date: date | None
    request_type: str
    requested_amount: float
    desired_completion_date: date | None
    allows_partial_payment: bool
    request_text: str


@dataclass
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str  # full_payment | installments | ...
    payment_amount: float
    number_of_payments: int
    first_payment_date: date | None
    payment_frequency_days: int | None
    financing_fee: float
    total_payable_amount: float


@dataclass
class Message:
    message_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    sent_at: datetime | None
    source_type: str
    message_text: str


@dataclass
class ImageLink:
    image_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None


@dataclass
class ResolvedEvent:
    """One logical cash-flow event after chain resolution.

    `source_event_ids` records which raw rows collapsed into this logical
    event; `resolution_rule` records which conflict rule fired (for the
    decision_explanation grounding and debugging).
    """

    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: float | None  # None => blank in CSV, image extraction pending
    currency: str
    event_date: date | None
    settlement_date: date | None
    status: str
    flexibility: str
    minimum_allowed_amount: float | None
    source_event_ids: list[str]
    resolution_rule: str


@dataclass
class FinancialState:
    """Everything the decision engine needs for one request."""

    request: Request
    profile: Profile
    events: list[ResolvedEvent]  # all resolved events for this user
    messages: list[Message]  # messages tied to this user/request
    image_links: list[ImageLink]  # image links tied to this user/request
    payment_options: list[PaymentOption]  # options for this request
    resolution_log: list[str]  # human-readable chain resolution notes
