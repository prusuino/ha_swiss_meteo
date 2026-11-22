"""Counting what the small feeds cost.

The forecast reader and the radar count their own reads. The station, the
rain gauge, the pollen station, the warnings and Open-Meteo are read through
plain requests in other modules; so that the traffic sensor shows the whole
of what an entry transfers, the coordinator that starts such a read names
the counter for the duration of the read, and the place that does the
request reports to it. Outside such a read (config flow, forecast, history)
nothing is counted here, so no read is counted twice.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

Account = Callable[[int, int], None]

_METER: ContextVar[Account | None] = ContextVar("swiss_meteo_traffic_meter", default=None)


@contextmanager
def metered(account: Account | None) -> Iterator[None]:
    """Count the requests made inside the block on `account`."""
    token = _METER.set(account)
    try:
        yield
    finally:
        _METER.reset(token)


def note(requests: int, nbytes: int) -> None:
    """Report requests and transferred bytes to the counter in force, if any."""
    account = _METER.get()
    if account is not None:
        account(requests, nbytes)


def transferred(headers, body: bytes) -> int:
    """Bytes on the wire: the Content-Length when the server states it (the
    body may have been sent compressed), else the length of the body."""
    stated = str(headers.get("Content-Length", "")) if headers is not None else ""
    return int(stated) if stated.isdigit() else len(body)
