import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from rate_limiter import RateLimiter


def test_allows_within_per_second_then_blocks():
    now = [1000.0]
    rl = RateLimiter(2, 100, 1000, now_fn=lambda: now[0])
    assert rl.allow("u1") is True
    assert rl.allow("u1") is True
    assert rl.allow("u1") is False


def test_allows_again_after_advancing_more_than_one_second():
    now = [1000.0]
    rl = RateLimiter(1, 100, 1000, now_fn=lambda: now[0])
    assert rl.allow("u1") is True
    assert rl.allow("u1") is False
    now[0] += 1.01
    assert rl.allow("u1") is True


def test_separate_keys_are_independent():
    now = [1000.0]
    rl = RateLimiter(1, 100, 1000, now_fn=lambda: now[0])
    assert rl.allow("a") is True
    assert rl.allow("a") is False
    assert rl.allow("b") is True


def test_hour_limit_blocks():
    now = [1000.0]
    rl = RateLimiter(10, 2, 1000, now_fn=lambda: now[0])
    assert rl.allow("u1") is True
    now[0] += 2.0
    assert rl.allow("u1") is True
    now[0] += 2.0
    assert rl.allow("u1") is False
