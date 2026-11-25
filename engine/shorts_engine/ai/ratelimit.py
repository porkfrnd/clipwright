from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _duration(value: str | None) -> float | None:
    """Parse retry-after / reset values: seconds or an HTTP date."""
    if value is None:
        return None
    value = value.strip()
    num = _num(value)
    if num is not None:
        return max(0.0, num)
    # Groq-style compound durations such as "2m59.56s" or "1h2m3s".
    import re

    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", value)
    if match and any(part is not None for part in match.groups()):
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = float(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds
    try:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone

        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


@dataclass
class RateLimitSnapshot:
    """Groq convention: request headers are per-day, token headers are per-minute.

    Other providers may use different conventions; values are still treated as
    advisory upper bounds and are never used to hardcode a plan limit.
    """

    requests_limit: float | None = None
    requests_remaining: float | None = None
    requests_reset_s: float | None = None
    tokens_limit: float | None = None
    tokens_remaining: float | None = None
    tokens_reset_s: float | None = None
    retry_after_s: float | None = None
    at: float = field(default_factory=time.monotonic)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requestsLimit": self.requests_limit,
            "requestsRemaining": self.requests_remaining,
            "requestsResetSeconds": self.requests_reset_s,
            "tokensLimit": self.tokens_limit,
            "tokensRemaining": self.tokens_remaining,
            "tokensResetSeconds": self.tokens_reset_s,
            "retryAfterSeconds": self.retry_after_s,
        }


def parse_rate_limit_headers(headers: Any) -> RateLimitSnapshot:
    get = headers.get if hasattr(headers, "get") else (lambda k, d=None: None)
    return RateLimitSnapshot(
        requests_limit=_num(get("x-ratelimit-limit-requests")),
        requests_remaining=_num(get("x-ratelimit-remaining-requests")),
        requests_reset_s=_duration(get("x-ratelimit-reset-requests")),
        tokens_limit=_num(get("x-ratelimit-limit-tokens")),
        tokens_remaining=_num(get("x-ratelimit-remaining-tokens")),
        tokens_reset_s=_duration(get("x-ratelimit-reset-tokens")),
        retry_after_s=_duration(get("retry-after") or get("x-ratelimit-retry-after")),
    )


class TokenBudget:
    """Conservative per-minute token and per-day request accounting.

    Budgets are seeded from response headers; absent headers leave the budget
    unknown and calls proceed (the endpoint itself remains the authority).
    """

    def __init__(self, *, default_tpm: float | None = None, default_rpd: float | None = None) -> None:
        self.default_tpm = default_tpm
        self.default_rpd = default_rpd
        self.tpm: float | None = default_tpm
        self.rpd: float | None = default_rpd
        self.minute_used = 0.0
        self.minute_at = time.monotonic()
        self.day_used = 0.0
        self.day_at = time.monotonic()
        self.last_snapshot: RateLimitSnapshot | None = None

    def _roll(self, now: float) -> None:
        if now - self.minute_at >= 60:
            self.minute_used = 0.0
            self.minute_at = now
        if now - self.day_at >= 86400:
            self.day_used = 0.0
            self.day_at = now

    def reset(self) -> None:
        self.minute_used = 0.0
        self.day_used = 0.0
        self.minute_at = time.monotonic()
        self.day_at = time.monotonic()

    def update(self, snapshot: RateLimitSnapshot) -> None:
        self.last_snapshot = snapshot
        if snapshot.tokens_limit:
            self.tpm = snapshot.tokens_limit
        if snapshot.requests_limit:
            self.rpd = snapshot.requests_limit
        if snapshot.tokens_remaining is not None and snapshot.tokens_limit:
            # Trust the server's view of the current minute.
            self.minute_used = max(0.0, snapshot.tokens_limit - snapshot.tokens_remaining)
            self.minute_at = time.monotonic()
        if snapshot.requests_remaining is not None and snapshot.requests_limit:
            self.day_used = max(0.0, snapshot.requests_limit - snapshot.requests_remaining)

    def wait_seconds(self, estimated_tokens: int, now: float | None = None) -> float:
        now = now or time.monotonic()
        self._roll(now)
        wait = 0.0
        if self.tpm and self.minute_used + estimated_tokens > self.tpm:
            wait = max(wait, 60 - (now - self.minute_at) + 0.5)
        if self.rpd and self.day_used + 1 > self.rpd:
            wait = max(wait, 86400 - (now - self.day_at) + 1.0)
        return wait

    def record(self, estimated_tokens: int) -> None:
        now = time.monotonic()
        self._roll(now)
        self.minute_used += max(0, estimated_tokens)
        self.day_used += 1

    def record_usage(
        self,
        usage: dict[str, Any] | None,
        snapshot: RateLimitSnapshot | None = None,
        *,
        fallback_tokens: int = 0,
    ) -> int:
        """Account for a completed request without double-counting server headers.

        Responses often carry authoritative token headers. ``update(snapshot)``
        already sets the minute/day counters from those headers; adding the local
        estimate again made the next request wait unnecessarily. Only add local
        usage when the server did not provide the corresponding counter.
        """
        now = time.monotonic()
        self._roll(now)
        total = (usage or {}).get("total_tokens")
        try:
            total_int = int(total) if total is not None else 0
        except (TypeError, ValueError):
            total_int = 0
        if total_int <= 0:
            total_int = max(0, int(fallback_tokens))
        snapshot = snapshot or self.last_snapshot
        has_token_counter = bool(
            snapshot
            and snapshot.tokens_limit is not None
            and snapshot.tokens_remaining is not None
        )
        if not has_token_counter:
            self.minute_used += total_int
        has_request_counter = bool(
            snapshot
            and snapshot.requests_limit is not None
            and snapshot.requests_remaining is not None
        )
        if not has_request_counter:
            self.day_used += 1
        return total_int
