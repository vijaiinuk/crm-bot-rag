import asyncio

import pytest

from chatbot.adapters.rate_limit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_requests_beyond_the_limit_wait_for_the_window() -> None:
    clock = FakeClock()
    limiter = RateLimiter(2, clock=clock, sleep=clock.sleep)
    await limiter.acquire()
    clock.now = 10.0
    await limiter.acquire()
    assert clock.slept == []
    await limiter.acquire()  # third in the window: waits until the first ages out
    assert clock.slept == [50.0] and clock.now == 60.0


async def test_old_requests_age_out() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1, clock=clock, sleep=clock.sleep)
    await limiter.acquire()
    clock.now = 61.0
    await limiter.acquire()
    assert clock.slept == []


async def test_concurrent_callers_are_all_paced() -> None:
    clock = FakeClock()
    limiter = RateLimiter(2, clock=clock, sleep=clock.sleep)
    await asyncio.gather(*(limiter.acquire() for _ in range(5)))
    assert clock.now == 120.0, "5 requests at 2 a minute need two full waits"


def test_rpm_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        RateLimiter(0)
