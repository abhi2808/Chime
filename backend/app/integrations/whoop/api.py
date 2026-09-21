"""The WHOOP v2 reads Chime needs.

Only what the docs actually offer appears here. There is no stress score and no live
heart-rate endpoint on WHOOP, so nothing here pretends otherwise: the signals are the
day's cycle strain, the morning's recovery, last night's sleep, and workouts that have
already finished.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import ValidationError

from app.integrations.whoop.client import WhoopClient
from app.integrations.whoop.errors import WhoopError
from app.integrations.whoop.schemas import (
    Cycle,
    Recovery,
    Sleep,
    WhoopModel,
    WhoopPage,
    WhoopProfile,
    Workout,
    utc,
)

logger = logging.getLogger(__name__)

#: WHOOP caps ``limit`` at 25, unlike Spotify's 50.
MAX_PAGE_LIMIT = 25

#: A day's refresh reads a handful of records; this is a runaway guard, not a target.
MAX_PAGES = 8

RecordT = TypeVar("RecordT", bound=WhoopModel)


def _parse(model: type[RecordT], payload: Any, what: str) -> RecordT:
    """Turn an unusable body into a typed WHOOP error.

    A pydantic error escaping here would look like a bug rather than a bad response, and
    callers already handle ``WhoopError``.
    """
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise WhoopError(f"WHOOP returned a {what} we could not read") from exc


def _stamp(moment: datetime | None) -> str | None:
    """WHOOP wants RFC 3339. ``isoformat`` on an aware datetime already is."""
    return moment.isoformat() if moment else None


async def _collect(
    client: WhoopClient,
    path: str,
    model: type[RecordT],
    *,
    what: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = MAX_PAGE_LIMIT,
    max_pages: int = MAX_PAGES,
) -> list[RecordT]:
    """Walk a collection endpoint's pages and return every record."""
    page_model = WhoopPage[model]  # type: ignore[valid-type]
    params: dict[str, Any] = {"limit": max(1, min(limit, MAX_PAGE_LIMIT))}
    if (value := _stamp(start)) is not None:
        params["start"] = value
    if (value := _stamp(end)) is not None:
        params["end"] = value

    records: list[RecordT] = []
    token: str | None = None
    for page_number in range(max_pages):
        if token:
            params["nextToken"] = token
        payload = await client.get_json(path, params=params)
        page = _parse(page_model, payload or {}, what)
        records.extend(page.records)
        token = page.next_token
        if not token:
            break
        if page_number == max_pages - 1:
            logger.warning(
                "whoop collection truncated at the page cap",
                extra={"path": path, "pages": max_pages, "records": len(records)},
            )
    return records


async def get_profile(client: WhoopClient) -> WhoopProfile:
    """Cheapest authenticated call, used to prove a fresh token works."""
    return _parse(WhoopProfile, await client.get_json("/v2/user/profile/basic"), "profile")


async def get_cycles(
    client: WhoopClient, *, start: datetime | None = None, end: datetime | None = None
) -> list[Cycle]:
    """Physiological days, newest first.

    WHOOP's own ordering is not documented as guaranteed, so the sort is ours. The record
    with no ``end`` is the cycle currently in progress.
    """
    cycles = await _collect(client, "/v2/cycle", Cycle, what="cycle", start=start, end=end)
    return _newest_first(cycles)


async def get_recoveries(
    client: WhoopClient, *, start: datetime | None = None, end: datetime | None = None
) -> list[Recovery]:
    return await _collect(
        client, "/v2/recovery", Recovery, what="recovery", start=start, end=end
    )


async def get_sleeps(
    client: WhoopClient, *, start: datetime | None = None, end: datetime | None = None
) -> list[Sleep]:
    """Sleeps including naps; callers decide whether a nap counts."""
    sleeps = await _collect(
        client, "/v2/activity/sleep", Sleep, what="sleep", start=start, end=end
    )
    return _newest_first(sleeps)


async def get_workouts(
    client: WhoopClient, *, start: datetime | None = None, end: datetime | None = None
) -> list[Workout]:
    """Finished workouts only. A session in progress is not visible to the API."""
    workouts = await _collect(
        client, "/v2/activity/workout", Workout, what="workout", start=start, end=end
    )
    return _newest_first(workouts)


def _newest_first(records: Sequence[RecordT]) -> list[RecordT]:
    """Sort by ``start`` descending, tolerating records that have none.

    Every key is forced to aware UTC first: comparing an aware datetime with a naive one
    raises, and WHOOP sending one of each in the same page is not worth risking.
    """
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(
        records,
        key=lambda record: utc(getattr(record, "start", None)) or floor,
        reverse=True,
    )
