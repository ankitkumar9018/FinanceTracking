"""Shared bounded-concurrency helpers.

Generalizes the semaphore pattern used by ``app.services.screener_service``:
run many independent units of work with a concurrency cap, a per-item
timeout, and best-effort semantics (failures become ``None`` instead of
failing the whole batch), preserving input order.

The critical detail: ``asyncio.wait_for`` is applied *inside* the semaphore,
so the timeout clock starts only after a slot is acquired.  The naive
pattern (``wait_for`` around the whole acquire-and-run) counts queue time
against the timeout, spuriously timing out items that merely waited their
turn behind a full pool.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

__all__ = ["bounded_thread_map", "gather_bounded"]


async def bounded_thread_map[T, R](
    fn: Callable[[T], R],
    items: Iterable[T],
    *,
    limit: int = 8,
    timeout: float = 10.0,
) -> list[R | None]:
    """Run the sync callable ``fn`` over ``items`` in worker threads.

    At most ``limit`` items run concurrently (via ``asyncio.to_thread``
    under an ``asyncio.Semaphore``).  Each item gets ``timeout`` seconds of
    *run* time — the timer starts after the semaphore slot is acquired, so
    time spent queued does not count.

    Returns results in input order; any item that raises or times out
    contributes ``None``.  Note that a timed-out thread cannot be
    interrupted — it keeps running in the background while its slot is
    released, same as the pre-existing screener pattern.
    """
    semaphore = asyncio.Semaphore(limit)

    async def _run(item: T) -> R | None:
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(fn, item), timeout=timeout
                )
            except Exception:
                return None

    return list(await asyncio.gather(*(_run(item) for item in items)))


async def gather_bounded[R](
    coro_factories: Iterable[Callable[[], Awaitable[R]]],
    *,
    limit: int = 8,
    timeout: float | None = None,
) -> list[R | None]:
    """Async twin of :func:`bounded_thread_map`.

    ``coro_factories`` is an iterable of zero-argument async callables
    (factories, not live coroutines, so nothing is created before its
    semaphore slot is acquired).  At most ``limit`` run concurrently; when
    ``timeout`` is given it is applied per task *inside* the semaphore.

    Returns results in input order; any task that raises or times out
    contributes ``None``.
    """
    semaphore = asyncio.Semaphore(limit)

    async def _run(factory: Callable[[], Awaitable[R]]) -> R | None:
        async with semaphore:
            try:
                if timeout is None:
                    return await factory()
                return await asyncio.wait_for(factory(), timeout=timeout)
            except Exception:
                return None

    return list(await asyncio.gather(*(_run(f) for f in coro_factories)))
