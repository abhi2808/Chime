from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

# ``datetime`` is aliased because this model has a field called ``date``, which would
# otherwise shadow the type when pydantic resolves the annotation.


class BodyStateResponse(BaseModel):
    """Today's body context, as SPEC section 2 defines it.

    Everything is optional because WHOOP fills a day in over time and may not be
    connected at all. ``mood`` is absent by design: the user supplies it at Chime in.

    ``note`` is the one field meant to be shown verbatim — it explains a gap (not
    connected, no data yet, still calibrating, a refresh that failed) in the user's own
    terms so the screen does not have to guess why a figure is missing.
    """

    model_config = ConfigDict(from_attributes=True)

    connected: bool
    has_data: bool
    day_part: str
    recovery: float | None = None
    hrv_ms: float | None = None
    rhr: float | None = None
    sleep_performance: float | None = None
    day_strain: float | None = None
    minutes_since_last_workout: int | None = None
    #: WHOOP's own bands: low <34, medium 34-66, high >66.
    readiness: str | None = None
    calibrating: bool = False
    date: dt.date | None = None
    fetched_at: dt.datetime | None = None
    note: str | None = None
    #: True when the stored grant is dead: the screen should offer Reconnect, not Refresh.
    needs_reconnect: bool = False
