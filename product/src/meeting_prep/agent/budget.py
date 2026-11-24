"""The shared Groq token budget, and each user's message rate limit. Pure: no I/O.

All users share one Groq organization: 8,000 tokens per minute and 200,000 per day
for openai/gpt-oss-120b. We plan below that, at 7,000 and 180,000, and at one
scenario-1 run per minute (docs/assumption-groq-budget.md). Before a run starts, it
must fit three counts:

* the tokens runs used in the last 60 seconds and the last 24 hours, read from
  ``agent_runs`` so they survive a restart;
* the tokens reserved by runs still in flight (each reserves ``max_total_tokens``, the
  most a run can spend);
* Groq's own count from the last response (``x-ratelimit-remaining-tokens`` until
  ``x-ratelimit-reset-tokens``), less the headroom we keep under its limit.

A run that does not fit is refused before the model is called, with the seconds after
which it would fit.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import ceil

from meeting_prep.agent.model import RateLimit

MINUTE = timedelta(minutes=1)
DAY = timedelta(days=1)

Usage = Sequence[tuple[datetime, int]]  # (when a run ended, tokens it used)


@dataclass(frozen=True)
class BudgetLimits:
    tokens_per_minute: int = 7_000
    tokens_per_day: int = 180_000
    provider_tokens_per_minute: int = 8_000  # Groq's own limit; the gap is headroom
    tokens_per_run: int = 6_000  # reserved by each run in flight: its max_total_tokens


@dataclass
class TokenBudget:
    """In-flight reservations and the provider's last count, for one process."""

    limits: BudgetLimits = field(default_factory=BudgetLimits)
    _reserved: dict[str, int] = field(default_factory=dict)
    _provider: tuple[int, datetime] | None = None  # tokens left, until this time
    _blocked_until: datetime | None = None

    def retry_after(self, now: datetime, last_day: Usage) -> int | None:
        """Seconds until one more run fits, or None if it fits now.

        ``last_day`` is every run that ended in the last 24 hours.
        """
        need = self.limits.tokens_per_run + sum(self._reserved.values())
        waits: list[float] = []
        if self._blocked_until is not None and now < self._blocked_until:
            waits.append((self._blocked_until - now).total_seconds())
        minute = [(end, tokens) for end, tokens in last_day if now - end < MINUTE]
        waits.append(_wait(now, minute, need, self.limits.tokens_per_minute, MINUTE))
        waits.append(_wait(now, last_day, need, self.limits.tokens_per_day, DAY))
        if self._provider is not None and now < self._provider[1]:
            headroom = self.limits.provider_tokens_per_minute - self.limits.tokens_per_minute
            if self._provider[0] - headroom < need:
                waits.append((self._provider[1] - now).total_seconds())
        longest = max(waits)
        return max(1, ceil(longest)) if longest > 0 else None

    def reserve(self, run_id: str) -> None:
        self._reserved[run_id] = self.limits.tokens_per_run

    def release(self, run_id: str) -> None:
        self._reserved.pop(run_id, None)

    def observe(self, now: datetime, rate_limit: RateLimit | None) -> None:
        """Record Groq's count from a run's last response."""
        if rate_limit is not None:
            until = now + timedelta(seconds=rate_limit.reset_seconds)
            self._provider = (rate_limit.remaining_tokens, until)

    def block(self, now: datetime, seconds: float | None) -> None:
        """Groq answered 429: refuse runs until it says to retry (a minute if it did not)."""
        self._blocked_until = now + timedelta(seconds=60 if seconds is None else seconds)


def _wait(now: datetime, used: Usage, need: int, limit: int, window: timedelta) -> float:
    """Seconds until ``need`` more tokens fit under ``limit`` in a rolling ``window``."""
    total = sum(tokens for _, tokens in used)
    if total + need <= limit:
        return 0.0
    if need > limit:
        return window.total_seconds()  # in-flight runs alone fill it; they end within a run
    for end, tokens in sorted(used):
        total -= tokens
        if total + need <= limit:
            return (end + window - now).total_seconds()
    return window.total_seconds()


@dataclass(frozen=True)
class MessageLimits:
    per_minute: int = 5
    per_day: int = 50


def message_retry_after(
    now: datetime, sent: Sequence[datetime], in_flight: int, limits: MessageLimits
) -> int | None:
    """Seconds until a user may send one more message, or None if they may now.

    ``sent`` holds the times of the user's messages in the last 24 hours.
    """
    waits = []
    for window, limit in ((MINUTE, limits.per_minute), (DAY, limits.per_day)):
        recent = sorted(t for t in sent if now - t < window)
        over = len(recent) + in_flight + 1 - limit
        if over > 0:
            # The oldest ``over`` messages must leave the window first.
            index = min(over, len(recent)) - 1
            waits.append((recent[index] + window - now).total_seconds() if recent else 60.0)
    if not waits:
        return None
    return max(1, ceil(max(waits)))
