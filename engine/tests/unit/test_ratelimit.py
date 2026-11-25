import time
from email.utils import formatdate

from shorts_engine.ai.ratelimit import RateLimitSnapshot, TokenBudget, parse_rate_limit_headers


def test_parse_groq_style_headers():
    headers = {
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": "999",
        "x-ratelimit-reset-requests": "2m59.56s",
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "7900",
        "x-ratelimit-reset-tokens": "7.66s",
        "retry-after": "12",
    }
    snapshot = parse_rate_limit_headers(headers)
    assert snapshot.requests_limit == 1000
    assert snapshot.requests_remaining == 999
    assert snapshot.tokens_remaining == 7900
    assert snapshot.retry_after_s == 12


def test_parse_retry_after_http_date():
    when = formatdate(time.time() + 30, usegmt=True)
    snapshot = parse_rate_limit_headers({"retry-after": when})
    assert snapshot.retry_after_s is not None
    assert 20 <= snapshot.retry_after_s <= 31


def test_parse_missing_and_garbage_headers_is_lenient():
    snapshot = parse_rate_limit_headers({})
    assert snapshot.requests_limit is None
    assert snapshot.tokens_limit is None
    assert snapshot.retry_after_s is None
    assert parse_rate_limit_headers({"retry-after": "soon"}).retry_after_s is None


def test_token_budget_waits_for_minute_window():
    budget = TokenBudget(default_tpm=1000, default_rpd=100)
    budget.record(900)
    assert budget.wait_seconds(50) == 0
    budget.record(150)
    wait = budget.wait_seconds(1)
    assert 0 < wait <= 61


def test_token_budget_waits_for_day_window():
    budget = TokenBudget(default_tpm=1_000_000, default_rpd=2)
    budget.record(1)
    budget.record(1)
    wait = budget.wait_seconds(1)
    assert wait > 80000


def test_token_budget_updates_from_server_snapshot():
    budget = TokenBudget()
    snapshot = RateLimitSnapshot(
        requests_limit=500,
        requests_remaining=400,
        tokens_limit=10000,
        tokens_remaining=9000,
    )
    budget.update(snapshot)
    assert budget.rpd == 500
    assert budget.tpm == 10000
    assert budget.minute_used == 1000
    assert budget.day_used == 100
    budget.reset()
    assert budget.minute_used == 0 and budget.day_used == 0


def test_record_usage_does_not_double_count_server_headers():
    budget = TokenBudget()
    snapshot = RateLimitSnapshot(
        requests_limit=1000,
        requests_remaining=999,
        tokens_limit=8000,
        tokens_remaining=7000,
    )
    budget.update(snapshot)
    assert budget.minute_used == 1000
    assert budget.day_used == 1
    total = budget.record_usage({"total_tokens": 1000}, snapshot)
    assert total == 1000
    assert budget.minute_used == 1000
    assert budget.day_used == 1
    assert budget.wait_seconds(1000) == 0


def test_record_usage_accounts_locally_without_headers():
    budget = TokenBudget()
    total = budget.record_usage({"total_tokens": 120}, None)
    assert total == 120
    assert budget.minute_used == 120
    assert budget.day_used == 1
