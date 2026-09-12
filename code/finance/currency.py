"""Currency conversion (Phase 4).

Uses the supplied dated exchange rates only. Direction matters: rows are
directional (USD->IDR is NOT the inverse of IDR->USD unless explicitly
inverted in the data). Multi-hop conversions compose through the graph
(e.g. USD->ZAR via USD->EUR + EUR->ZAR).

Policy when the exact settlement date has no rate for a needed pair:
use the nearest earlier rate for that pair and LOG the substitution.
Never silently guess, never use a later rate, never use live rates.
"""

from __future__ import annotations

from collections import deque
from datetime import date

from code.data.types import ResolvedEvent


class FxGraph:
    """Directional, dated FX graph built from exchange_rates.csv."""

    def __init__(self, rates: dict[tuple[date, str, str], float]) -> None:
        self.rates = rates
        # pair -> sorted list of dates having a row
        self._dates_by_pair: dict[tuple[str, str], list[date]] = {}
        for (d, f, t) in rates:
            self._dates_by_pair.setdefault((f, t), []).append(d)
        for pair in self._dates_by_pair:
            self._dates_by_pair[pair].sort()
        # pair set for BFS over currencies
        self._pairs: set[tuple[str, str]] = set(self._dates_by_pair)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def _rate_on(self, pair: tuple[str, str], d: date) -> float | None:
        return self.rates.get((d, pair[0], pair[1]))

    def _nearest_rate_on_or_before(
        self, pair: tuple[str, str], d: date
    ) -> tuple[date, float] | None:
        dates = self._dates_by_pair.get(pair)
        if not dates:
            return None
        # binary search: latest date <= d
        lo, hi = 0, len(dates) - 1
        best: date | None = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if dates[mid] <= d:
                best = dates[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        if best is None:
            return None
        return best, self.rates[(best, pair[0], pair[1])]

    def _hop_rate(
        self, pair: tuple[str, str], d: date, log: list[str] | None
    ) -> float | None:
        """Rate for one hop on date d (nearest-earlier fallback, logged)."""
        exact = self._rate_on(pair, d)
        if exact is not None:
            return exact
        near = self._nearest_rate_on_or_before(pair, d)
        if near is None:
            return None
        used_date, rate = near
        if log is not None:
            log.append(
                f"fx: no {pair[0]}->{pair[1]} rate on {d}; using {used_date} "
                f"rate {rate} (nearest earlier, logged substitution)"
            )
        return rate

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def currencies_reachable(self, start: str) -> list[str]:
        seen = {start}
        q = deque([start])
        while q:
            cur = q.popleft()
            for (f, t) in self._pairs:
                if f == cur and t not in seen:
                    seen.add(t)
                    q.append(t)
        return sorted(seen)

    def convert(
        self,
        amount: float,
        from_cur: str,
        to_cur: str,
        on_date: date,
        log: list[str] | None = None,
    ) -> float | None:
        """Convert amount with a dated, direction-correct, possibly multi-hop path."""
        if from_cur == to_cur:
            return amount
        # BFS over currency graph, fewest hops first; deterministic order.
        visited: set[str] = {from_cur}
        queue: deque[tuple[str, list[tuple[str, str]]]] = deque()
        queue.append((from_cur, []))
        while queue:
            cur, path = queue.popleft()
            for (f, t) in sorted(self._pairs):
                if f != cur or t in visited:
                    continue
                visited.add(t)
                new_path = path + [(f, t)]
                if t == to_cur:
                    return self._apply_path(amount, new_path, on_date, log)
                queue.append((t, new_path))
        if log is not None:
            log.append(
                f"fx: NO conversion path {from_cur}->{to_cur} on {on_date}; "
                f"amount left unconverted (flagged)"
            )
        return None

    def _apply_path(
        self,
        amount: float,
        path: list[tuple[str, str]],
        on_date: date,
        log: list[str] | None,
    ) -> float:
        value = amount
        for pair in path:
            rate = self._hop_rate(pair, on_date, log)
            if rate is None:
                if log is not None:
                    log.append(
                        f"fx: missing rate for {pair[0]}->{pair[1]} on "
                        f"{on_date}; conversion failed (flagged)"
                    )
                return None  # caller must treat as unconvertible
            value = value * rate
        return value


def event_to_home_currency(
    event: ResolvedEvent,
    home_currency: str,
    fx: FxGraph,
    log: list[str] | None = None,
) -> float | None:
    """Event amount in the user's home currency, valued on its settlement date.

    Returns None when the amount is blank (image extraction pending) or no
    conversion path exists. The settlement date governs, per the dataset
    contract; event_date is the fallback.
    """
    if event.amount is None:
        return None
    d = event.settlement_date or event.event_date
    if d is None:
        return None
    return fx.convert(event.amount, event.currency, home_currency, d, log)
