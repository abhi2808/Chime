"""What does WHOOP actually update during the day, and when?

    cd backend && uv run python -m scripts.whoop_freshness            # every 30 min for 12 h
    cd backend && uv run python -m scripts.whoop_freshness --every 15 --hours 16

The open Phase 2 item in docs/PLAN.md. The engine treats recovery and sleep as scored once a
day and day strain as creeping up through it, and the live loop polls WHOOP every 15 minutes
on that assumption (``WHOOP_POLL_SECONDS``). This measures it rather than trusting it: on an
interval it forces the same refresh the poller runs, then prints only the fields that moved
since the last reading, with the time. At the end (or on Ctrl+C) it prints how often each
field changed.

Each tick is the four requests a normal refresh makes, so the default run spends about a
hundred of WHOOP's 10,000 daily requests. Every line is also appended to
``data/whoop_freshness.log`` so a day's run can be read afterwards.

Figures only: the derived numbers Chime stores, never a raw WHOOP payload.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from collections import Counter
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select

from app.core.clock import utcnow
from app.core.config import PROJECT_ROOT
from app.db.session import SessionLocal
from app.integrations.whoop.errors import WhoopAuthError
from app.models import User, WhoopWorkout
from app.services import whoop_sync

FIELDS = (
    "date",
    "cycle_open",
    "recovery",
    "hrv_ms",
    "rhr",
    "sleep_performance",
    "day_strain",
    "spo2",
    "skin_temp_c",
    "calibrating",
)

LOG = PROJECT_ROOT / "data" / "whoop_freshness.log"


def snapshot(user_id: int) -> dict[str, Any]:
    """The stored WHOOP day as the engine sees it, plus how many workouts are stored."""
    with SessionLocal() as db:
        day = whoop_sync.latest_day(db, user_id)
        workouts = db.scalar(
            select(func.count()).select_from(WhoopWorkout).where(WhoopWorkout.user_id == user_id)
        )
    values: dict[str, Any] = {field: getattr(day, field, None) for field in FIELDS}
    values["workouts"] = workouts or 0
    return values


def changes(before: Mapping[str, Any] | None, after: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Fields whose value differs, as ``{field: (old, new)}``. Everything, on the first read."""
    if before is None:
        return {field: (None, value) for field, value in after.items()}
    return {
        field: (before.get(field), value)
        for field, value in after.items()
        if before.get(field) != value
    }


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.1f}"
    return "-" if value is None else str(value)


def _emit(line: str) -> None:
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _pick_user(user_id: int | None) -> int | None:
    with SessionLocal() as db:
        ids = [user_id] if user_id is not None else list(db.scalars(select(User.id)))
        for candidate in ids:
            if whoop_sync.is_connected(db, candidate):
                return candidate
    return None


async def run(user_id: int, every_minutes: float, hours: float) -> int:
    deadline = utcnow() + dt.timedelta(hours=hours)
    previous: dict[str, Any] | None = None
    moved: Counter[str] = Counter()
    ticks = 0

    _emit(f"# {utcnow():%Y-%m-%d %H:%M} UTC  user={user_id}  every {every_minutes:g} min for {hours:g} h")
    try:
        while True:
            stamp = dt.datetime.now().strftime("%H:%M")
            try:
                result = await whoop_sync.refresh_body_data(user_id, force=True)
            except WhoopAuthError:
                _emit(f"{stamp}  WHOOP needs reconnecting; stopping.")
                return 1
            if result.error:
                _emit(f"{stamp}  refresh failed ({result.error}); keeping the last reading")
            else:
                current = snapshot(user_id)
                diff = changes(previous, current)
                ticks += 1
                if previous is not None:
                    moved.update(diff.keys())
                if diff:
                    parts = (
                        f"{field} {_fmt(new)}"
                        if previous is None
                        else f"{field} {_fmt(old)} -> {_fmt(new)}"
                        for field, (old, new) in diff.items()
                    )
                    _emit(f"{stamp}  " + ", ".join(parts))
                else:
                    _emit(f"{stamp}  no change")
                previous = current

            if utcnow() + dt.timedelta(minutes=every_minutes) > deadline:
                break
            await asyncio.sleep(every_minutes * 60)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass

    _emit(f"# {ticks} readings. Changes per field after the first:")
    for field in (*FIELDS, "workouts"):
        _emit(f"#   {field:<18} {moved.get(field, 0)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--every", type=float, default=30, help="minutes between reads (default 30)")
    parser.add_argument("--hours", type=float, default=12, help="how long to run (default 12)")
    parser.add_argument("--user", type=int, default=None, help="user id (default: the one with WHOOP)")
    args = parser.parse_args(argv)

    if args.every < 5:
        parser.error("--every below 5 minutes measures nothing WHOOP updates that fast")

    user_id = _pick_user(args.user)
    if user_id is None:
        print("No user with WHOOP connected. Connect it from Settings first.")
        return 1
    try:
        return asyncio.run(run(user_id, args.every, args.hours))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
