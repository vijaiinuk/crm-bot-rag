"""Client-side request pacing, so bulk jobs stay under a provider's rate limit.

New OpenRouter accounts get 20 requests a minute per model; generating docs and
questions hit that (S1.2.1, S1.3.1), and eval runs will too. Pacing on our side
is cheaper and more predictable than failing and retrying.
"""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable


class RateLimiter:
    """At most `rpm` acquisitions in any rolling `window` seconds."""

    def __init__(
        self,
        rpm: int,
        *,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if rpm < 1:
            raise ValueError("rpm must be at least 1")
        self._rpm = rpm
        self._window = window
        self._clock = clock
        self._sleep = sleep
        self._times: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:  # waiters queue up in order
            while True:
                now = self._clock()
                while self._times and now - self._times[0] >= self._window:
                    self._times.popleft()
                if len(self._times) < self._rpm:
                    self._times.append(now)
                    return
                await self._sleep(self._window - (now - self._times[0]))
