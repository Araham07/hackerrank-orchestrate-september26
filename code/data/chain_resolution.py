"""Linked-event chain resolution.

Implements the problem statement's conflict-resolution priority for
`linked_event_id` chains:

1. An explicit cancellation / settlement / amendment row wins over an
   estimate or forecast row.
2. Among same-priority rows, the newer record (by event/settlement date)
   from the same source wins.
3. A settled row always outranks pending/scheduled for the same logical
   transaction.
4. Otherwise take the financially safer reading (assume less available cash).

The dataset's 58 multi-row chains all have exactly 2 members and fall into
5 audited patterns:

- cancelled+settled  : cancelled row is an authorization superseded by the
  settled charge -> keep the settled row.
- pending+settled (refund pairs) : keep BOTH - the settled debit already
  happened; the pending refund credit is a separate future cash fact that
  must NOT be counted until it settles.
- settled+unrealized (investment buy -> valuation) : keep the settled
  purchase; the valuation is non-cash and is dropped from cash flow.
- failed+scheduled (payment retry) : keep the scheduled retry as the live
  future debit; drop the failed attempt.
- settled+settled (expense -> refund) : both settled debits/credits are
  real history; keep both.
"""

from __future__ import annotations

from datetime import date

from code.data.types import Event, ResolvedEvent

# Statuses ranked by "how final/authoritative" they are for one logical
# transaction. Higher wins under rule 3.
_STATUS_PRIORITY = {
    "cancelled": 4,
    "settled": 3,
    "pending": 1,
    "scheduled": 2,
    "failed": 0,
    "unrealized": -1,
}


def _fin_resolved(
    row: Event,
    source_ids: list[str],
    rule: str,
    *,
    keep_both: list[Event] | None = None,
) -> list[ResolvedEvent]:
    primary = ResolvedEvent(
        event_id=row.event_id,
        user_id=row.user_id,
        event_type=row.event_type,
        description=row.description,
        category=row.category,
        direction=row.direction,
        amount=row.amount,
        currency=row.currency,
        event_date=row.event_date,
        settlement_date=row.settlement_date,
        status=row.status,
        flexibility=row.flexibility,
        minimum_allowed_amount=row.minimum_allowed_amount,
        source_event_ids=source_ids,
        resolution_rule=rule,
    )
    if keep_both:
        extra = [
            ResolvedEvent(
                event_id=x.event_id,
                user_id=x.user_id,
                event_type=x.event_type,
                description=x.description,
                category=x.category,
                direction=x.direction,
                amount=x.amount,
                currency=x.currency,
                event_date=x.event_date,
                settlement_date=x.settlement_date,
                status=x.status,
                flexibility=x.flexibility,
                minimum_allowed_amount=x.minimum_allowed_amount,
                source_event_ids=[x.event_id],
                resolution_rule=rule + " (kept as separate cash fact)",
            )
            for x in keep_both
        ]
        return [primary, *extra]
    return [primary]


def _newer(a: Event, b: Event) -> Event:
    """Rule 2 helper: the newer record by settlement/event date."""
    da = a.settlement_date or a.event_date or date.min
    db = b.settlement_date or b.event_date or date.min
    return a if da >= db else b


def resolve_chain(rows: list[Event]) -> tuple[list[ResolvedEvent], list[str]]:
    """Collapse one linked chain into its logical cash-flow events.

    Returns (resolved_events, log_lines).
    """
    log: list[str] = []
    if len(rows) == 1:
        return _fin_resolved(rows[0], [rows[0].event_id], "single_row"), log

    # Order oldest -> newest for stable, deterministic handling.
    ordered = sorted(
        rows,
        key=lambda e: (e.settlement_date or e.event_date or date.min, e.event_id),
    )
    ids = [e.event_id for e in ordered]

    statuses = {e.status for e in ordered}
    types_ = {e.event_type for e in ordered}
    directions = {e.direction for e in ordered}

    # Pattern 1: cancelled + settled -> the settled row supersedes the
    # cancelled authorization.
    if "cancelled" in statuses and "settled" in statuses:
        keeper = next(e for e in ordered if e.status == "settled")
        log.append(
            f"chain {','.join(ids)}: cancelled+settled -> kept settled "
            f"{keeper.event_id} (rule 1: explicit amendment supersedes)"
        )
        return _fin_resolved(keeper, ids, "cancelled_vs_settled:kept_settled"), log

    # Pattern 2: failed + scheduled -> keep the scheduled retry.
    if "failed" in statuses and "scheduled" in statuses:
        keeper = next(e for e in ordered if e.status == "scheduled")
        log.append(
            f"chain {','.join(ids)}: failed+scheduled -> kept scheduled retry "
            f"{keeper.event_id} (rule 1: amendment supersedes failed attempt)"
        )
        return _fin_resolved(keeper, ids, "failed_vs_scheduled:kept_scheduled"), log

    # Pattern 3: settled + unrealized -> keep the settled cash row; the
    # unrealized valuation is non-cash and never enters the forecast.
    if "unrealized" in statuses and "settled" in statuses:
        keeper = next(e for e in ordered if e.status == "settled")
        log.append(
            f"chain {','.join(ids)}: settled+unrealized -> kept settled cash row "
            f"{keeper.event_id}; unrealized valuation dropped from cash flow"
        )
        return _fin_resolved(keeper, ids, "settled_vs_unrealized:kept_settled"), log

    # Pattern 4: settled + pending.
    if {"settled", "pending"} <= statuses:
        settled_rows = [e for e in ordered if e.status == "settled"]
        pending_rows = [e for e in ordered if e.status == "pending"]
        refund_pending = [e for e in pending_rows if e.event_type == "refund"]

        # 4a: settled debit + pending refund -> both are real cash facts at
        # different times; keep both (refund only counts when it settles).
        if refund_pending and settled_rows:
            log.append(
                f"chain {','.join(ids)}: settled+pending refund -> kept both "
                f"(settled debit is history; pending refund counts only "
                f"on its settlement date)"
            )
            return _fin_resolved(
                settled_rows[0], ids, "settled_vs_pending:kept_both",
                keep_both=refund_pending,
            ), []

        # 4b: possible duplicate charge (settled original + pending dup)
        # -> financially safer reading: reserve the pending debit.
        log.append(
            f"chain {','.join(ids)}: settled+pending duplicate debit -> kept "
            f"both (pending duplicate reserved, not double-counted)"
        )
        return _fin_resolved(
            settled_rows[0], ids, "settled_vs_pending:kept_both",
            keep_both=pending_rows,
        ), []

    # Pattern 5: settled + settled (e.g. expense followed by its refund,
    # both settled) -> both are real history; keep both.
    if statuses == {"settled"}:
        log.append(
            f"chain {','.join(ids)}: settled+settled -> kept both rows "
            f"(both are settled history, no conflict)"
        )
        resolved = [
            ResolvedEvent(
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
                resolution_rule="settled_vs_settled:kept_both",
            )
            for e in ordered
        ]

        return resolved, log

    # Fallback: rules 2-4 - keep the higher-priority status; on tie keep
    # the newer row; final fallback is the financially safer reading.
    ranked = sorted(
        ordered,
        key=lambda e: (
            _STATUS_PRIORITY.get(e.status, 0),
            e.settlement_date or e.event_date or date.min,
        ),
    )
    keeper = ranked[-1]
    log.append(
        f"chain {','.join(ids)}: fallback -> kept {keeper.event_id} "
        f"(status priority; safer reading)"
    )
    return _fin_resolved(keeper, ids, "fallback:status_priority"), log
