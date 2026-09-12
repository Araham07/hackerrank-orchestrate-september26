"""Build a FinancialState per request (Phase 2).

Joins profiles, events, messages, images, and payment options on user_id /
request_id, collapses linked_event_id chains via chain_resolution, and
exposes one trustworthy state object per request.
"""

from __future__ import annotations

from collections import defaultdict

from code.data.chain_resolution import resolve_chain
from code.data.loader import (
    load_events,
    load_sample_requests_typed,
    load_exchange_rates,
    load_image_links,
    load_messages,
    load_payment_options,
    load_profiles,
    load_requests,
    load_sample_requests,
)
from code.data.types import Event, FinancialState, ResolvedEvent


class DataStore:
    """Pre-indexed dataset: build once, query per request."""

    def __init__(self) -> None:
        self.profiles = load_profiles()
        self.events = load_events()
        self.rates = load_exchange_rates()
        self.requests = load_requests()
        self.samples = load_sample_requests()
        self.sample_requests_typed = {
            r.request_id: r for r in load_sample_requests_typed()
        }
        self.options = load_payment_options()
        self.messages = load_messages()
        self.image_links = load_image_links()

        self._events_by_user: dict[str, list[Event]] = defaultdict(list)
        for e in self.events:
            self._events_by_user[e.user_id].append(e)

        self._messages_by_user: dict[str, list] = defaultdict(list)
        for m in self.messages:
            self._messages_by_user[m.user_id].append(m)

        self._images_by_user: dict[str, list] = defaultdict(list)
        for i in self.image_links:
            self._images_by_user[i.user_id].append(i)

        self._options_by_request: dict[str, list] = defaultdict(list)
        for o in self.options:
            self._options_by_request[o.request_id].append(o)

        # Resolve every chain once, up front.
        self._resolved_by_user: dict[str, list[ResolvedEvent]] = {}
        self.resolution_logs: dict[str, list[str]] = {}
        for user_id, user_events in self._events_by_user.items():
            resolved, logs = _resolve_user_events(user_events)
            self._resolved_by_user[user_id] = resolved
            self.resolution_logs[user_id] = logs

    def request_by_id(self, request_id: str):
        for r in self.requests:
            if r.request_id == request_id:
                return r
        return self.sample_requests_typed.get(request_id)

    def build_state(self, request) -> FinancialState:
        """One FinancialState for one request."""
        user_id = request.user_id
        profile = self.profiles.get(user_id)
        if profile is None:
            raise KeyError(f"no financial profile for {user_id}")
        user_msgs = [
            m for m in self._messages_by_user.get(user_id, [])
            if m.request_id in (None, request.request_id)
        ]
        user_imgs = [
            i for i in self._images_by_user.get(user_id, [])
            if i.request_id in (None, request.request_id)
        ]
        return FinancialState(
            request=request,
            profile=profile,
            events=self._resolved_by_user.get(user_id, []),
            messages=user_msgs,
            image_links=user_imgs,
            payment_options=self._options_by_request.get(request.request_id, []),
            resolution_log=self.resolution_logs.get(user_id, []),
        )


def _resolve_user_events(user_events: list[Event]):
    """Group one user's events into chains, resolve each chain.

    Returns (resolved_events, log_lines).
    """
    by_id = {e.event_id: e for e in user_events}
    # Union rows into chains: parent event_id <- children (linked_event_id).
    children: dict[str, list[str]] = defaultdict(list)
    has_parent: set[str] = set()
    for e in user_events:
        if e.linked_event_id and e.linked_event_id in by_id:
            children[e.linked_event_id].append(e.event_id)
            has_parent.add(e.event_id)

    log: list[str] = []
    resolved: list[ResolvedEvent] = []
    visited: set[str] = set()

    for e in user_events:
        if e.event_id in visited or e.event_id in has_parent:
            continue
        # Collect the chain: root + all descendants (dataset chains are 2 deep).
        chain = [e]
        visited.add(e.event_id)
        stack = list(children.get(e.event_id, []))
        while stack:
            cid = stack.pop()
            if cid in visited:
                continue
            visited.add(cid)
            chain.append(by_id[cid])
            stack.extend(children.get(cid, []))
        if len(chain) == 1:
            resolved.append(ResolvedEvent(
                event_id=e.event_id,
                user_id=e.user_id,
                event_type=e.event_type,
                description=e.description,
                category=e.category,
                direction=e.direction,
                amount=e.amount,
                currency=e.currency,
                event_date=e.event_date,
                settlement_date=e.settlement_date,
                status=e.status,
                flexibility=e.flexibility,
                minimum_allowed_amount=e.minimum_allowed_amount,
                source_event_ids=[e.event_id],
                resolution_rule="single_row",
            ))
        else:
            part, logs = resolve_chain(chain)
            resolved.extend(part)
            log.extend(logs)

    # Deterministic order.
    resolved.sort(key=lambda r: r.event_id)
    return resolved, log
