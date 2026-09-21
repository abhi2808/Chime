"""WHOOP against fixture responses: OAuth, the v2 readers, sync, and body state.

Everything WHOOP-specific that would be a silent bug if assumed is pinned here: the
eight-character state, the client secret in the token body, ``limit`` capped at 25,
``score`` being absent unless ``score_state`` is ``SCORED``, and a cycle belonging to the
member's calendar day rather than the server's.
"""

from __future__ import annotations

import datetime as dt
from datetime import timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import settings
from app.core.cookies import dumps
from app.core.crypto import decrypt, encrypt
from app.db.session import SessionLocal
from app.integrations.whoop import api as whoop_api
from app.integrations.whoop import auth as whoop_auth
from app.integrations.whoop.client import API_BASE, WhoopClient
from app.integrations.whoop.errors import (
    WhoopAuthError,
    WhoopError,
    WhoopNotFoundError,
)
from app.integrations.whoop.schemas import Cycle, offset_timezone
from app.models import OAuthToken, User, WhoopDaily, WhoopWorkout
from app.services import body_state, whoop_sync

PROFILE_URL = f"{API_BASE}/v2/user/profile/basic"
CYCLE_URL = f"{API_BASE}/v2/cycle"
RECOVERY_URL = f"{API_BASE}/v2/recovery"
SLEEP_URL = f"{API_BASE}/v2/activity/sleep"
WORKOUT_URL = f"{API_BASE}/v2/activity/workout"


class FakeTokens:
    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        return "whoop-access"


# --------------------------------------------------------------------------- payloads


def cycle(
    cycle_id: int | str = 101,
    *,
    start: str = "2026-09-21T12:00:00+00:00",
    end: str | None = None,
    offset: str = "-05:00",
    strain: float | None = 9.4,
) -> dict[str, Any]:
    """A cycle. ``strain=None`` means WHOOP has not scored the day yet."""
    payload: dict[str, Any] = {
        "id": cycle_id,  # numeric on cycles, unlike the UUIDs on activities
        "user_id": 7,
        "start": start,
        "end": end,
        "timezone_offset": offset,
        "score_state": "SCORED" if strain is not None else "PENDING_SCORE",
    }
    if strain is not None:
        payload["score"] = {
            "strain": strain,
            "kilojoule": 8_400.0,
            "average_heart_rate": 74,
            "max_heart_rate": 158,
        }
    return payload


def recovery(
    *,
    cycle_id: int | str = 101,
    sleep_id: str = "sleep-uuid-1",
    score: float | None = 71.0,
    calibrating: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "cycle_id": cycle_id,
        "sleep_id": sleep_id,
        "score_state": "SCORED" if score is not None else "PENDING_SCORE",
    }
    if score is not None:
        payload["score"] = {
            "user_calibrating": calibrating,
            "recovery_score": score,
            "resting_heart_rate": 52.0,
            "hrv_rmssd_milli": 64.5,
            "spo2_percentage": 97.2,
            "skin_temp_celsius": 33.1,
        }
    return payload


def sleep(
    sleep_id: str = "sleep-uuid-1",
    *,
    cycle_id: int | str = 101,
    nap: bool = False,
    performance: float | None = 88.0,
    start: str = "2026-09-21T01:00:00+00:00",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": sleep_id,
        "cycle_id": cycle_id,
        "nap": nap,
        "start": start,
        "end": "2026-09-21T09:00:00+00:00",
        "score_state": "SCORED" if performance is not None else "PENDING_SCORE",
    }
    if performance is not None:
        payload["score"] = {
            "sleep_performance_percentage": performance,
            "sleep_efficiency_percentage": 93.0,
            "respiratory_rate": 14.2,
        }
    return payload


def workout(
    workout_id: str = "workout-uuid-1",
    *,
    start: str = "2026-09-21T17:00:00+00:00",
    end: str = "2026-09-21T18:00:00+00:00",
    sport_name: str | None = "Running",
    sport_id: int | None = 0,
    strain: float | None = 12.6,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": workout_id,
        "start": start,
        "end": end,
        "sport_id": sport_id,
        "sport_name": sport_name,
        "score_state": "SCORED" if strain is not None else "PENDING_SCORE",
    }
    if strain is not None:
        payload["score"] = {
            "strain": strain,
            "average_heart_rate": 148,
            "max_heart_rate": 179,
            "kilojoule": 2_100.0,
            "percent_recorded": 100.0,
        }
    return payload


def page(records: list[dict[str, Any]], next_token: str | None = None) -> dict[str, Any]:
    return {"records": records, "next_token": next_token}


def mock_whoop(
    *,
    cycles: list[dict[str, Any]] | None = None,
    recoveries: list[dict[str, Any]] | None = None,
    sleeps: list[dict[str, Any]] | None = None,
    workouts: list[dict[str, Any]] | None = None,
) -> None:
    """Route all four collections, so a refresh never hits an unmocked URL."""
    respx.get(CYCLE_URL).mock(return_value=httpx.Response(200, json=page(cycles or [])))
    respx.get(RECOVERY_URL).mock(return_value=httpx.Response(200, json=page(recoveries or [])))
    respx.get(SLEEP_URL).mock(return_value=httpx.Response(200, json=page(sleeps or [])))
    respx.get(WORKOUT_URL).mock(return_value=httpx.Response(200, json=page(workouts or [])))


@pytest.fixture
def whoop_token(db: Session, user: User) -> OAuthToken:
    record = OAuthToken(
        user_id=user.id,
        provider="whoop",
        access_token_enc=encrypt("whoop-access"),
        refresh_token_enc=encrypt("whoop-refresh"),
        expires_at=utcnow() + timedelta(hours=1),
        scopes=whoop_auth.SCOPE_STRING,
    )
    db.add(record)
    db.commit()
    return record


def sign_in(client: TestClient, user: User) -> None:
    client.cookies.set(settings.session_cookie_name, dumps("chime.session", {"uid": user.id}))


# ------------------------------------------------------------------------------ OAuth


def test_state_is_exactly_eight_characters() -> None:
    """WHOOP rejects any other length, unlike Spotify which takes anything."""
    states = {whoop_auth.new_state() for _ in range(50)}

    assert all(len(state) == whoop_auth.STATE_LENGTH == 8 for state in states)
    assert len(states) > 40  # fresh each time, not a constant


def test_authorize_url_asks_for_offline_and_nothing_invented() -> None:
    url = whoop_auth.build_authorize_url(
        client_id="cid", redirect_uri="https://example.test/cb", state="abcd1234"
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == whoop_auth.AUTHORIZE_URL
    assert query["response_type"] == ["code"]
    assert query["state"] == ["abcd1234"]
    scopes = query["scope"][0].split(" ")
    # offline is what buys us a refresh token; without it the connection dies in an hour.
    assert "offline" in scopes
    assert "read:cycles" in scopes and "read:recovery" in scopes
    # There is no stress or live heart-rate scope in the API; nothing may ask for one.
    assert not [scope for scope in scopes if "stress" in scope or "heart" in scope]


@respx.mock
async def test_exchange_code_sends_the_client_secret() -> None:
    """WHOOP is a confidential client: secret in the body, no PKCE verifier."""
    route = respx.post(whoop_auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "whoop-access",
                "token_type": "bearer",
                "expires_in": 3600,
                "refresh_token": "whoop-refresh",
                "scope": whoop_auth.SCOPE_STRING,
            },
        )
    )

    tokens = await whoop_auth.exchange_code(
        client_id="cid",
        client_secret="secret",
        redirect_uri="https://example.test/cb",
        code="auth-code",
    )

    assert tokens.access_token == "whoop-access"
    assert tokens.refresh_token == "whoop-refresh"
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["auth-code"]
    assert body["client_secret"] == ["secret"]
    assert "code_verifier" not in body


@respx.mock
async def test_refresh_resends_the_scope() -> None:
    route = respx.post(whoop_auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "next-access", "expires_in": 3600}
        )
    )

    await whoop_auth.refresh_access_token(
        client_id="cid", client_secret="secret", refresh_token="whoop-refresh"
    )

    body = parse_qs(route.calls[0].request.content.decode())
    assert body["grant_type"] == ["refresh_token"]
    assert body["client_secret"] == ["secret"]
    # WHOOP's documented refresh payload includes scope; offline must stay in it.
    assert "offline" in body["scope"][0]


@respx.mock
async def test_a_dead_grant_becomes_a_whoop_auth_error() -> None:
    respx.post(whoop_auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Refresh token expired"}
        )
    )

    with pytest.raises(WhoopAuthError, match="Refresh token expired"):
        await whoop_auth.refresh_access_token(
            client_id="cid", client_secret="secret", refresh_token="stale"
        )


@respx.mock
async def test_the_token_store_refreshes_whoop_with_its_own_credentials(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    whoop_token.expires_at = utcnow() - timedelta(minutes=1)
    db.add(whoop_token)
    db.commit()
    route = respx.post(whoop_auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "rotated-access", "expires_in": 3600}
        )
    )

    from app.services.token_store import TokenStore

    token = await TokenStore(SessionLocal, user.id, "whoop").get_access_token()

    assert token == "rotated-access"
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["client_id"] == ["test-whoop-client-id"]
    assert body["client_secret"] == ["test-whoop-secret"]

    db.expire_all()
    stored = db.scalar(
        select(OAuthToken).where(OAuthToken.user_id == user.id, OAuthToken.provider == "whoop")
    )
    assert stored is not None
    assert decrypt(stored.access_token_enc) == "rotated-access"
    # WHOOP omitted a new refresh token, so the old one has to survive.
    assert decrypt(stored.refresh_token_enc or "") == "whoop-refresh"


# ----------------------------------------------------------------------------- client


@respx.mock
async def test_a_whoop_error_body_is_surfaced_to_the_caller() -> None:
    respx.get(CYCLE_URL).mock(
        return_value=httpx.Response(400, json={"message": "start must precede end"})
    )

    async with WhoopClient(FakeTokens()) as client:
        with pytest.raises(WhoopError, match="start must precede end"):
            await client.get_json("/v2/cycle")


@respx.mock
async def test_a_missing_record_is_a_not_found_error() -> None:
    respx.get(f"{API_BASE}/v2/cycle/999").mock(return_value=httpx.Response(404))

    async with WhoopClient(FakeTokens()) as client:
        with pytest.raises(WhoopNotFoundError):
            await client.get_json("/v2/cycle/999")


# ---------------------------------------------------------------------------- readers


@respx.mock
async def test_get_profile_proves_a_token_works() -> None:
    route = respx.get(PROFILE_URL).mock(
        return_value=httpx.Response(
            200, json={"user_id": 12345, "first_name": "Abhinav", "last_name": "B"}
        )
    )

    async with WhoopClient(FakeTokens()) as client:
        profile = await whoop_api.get_profile(client)

    assert profile.user_id == "12345"  # numeric id coerced to text
    assert route.calls[0].request.headers["Authorization"] == "Bearer whoop-access"


@respx.mock
async def test_reads_are_windowed_and_never_ask_for_more_than_25() -> None:
    respx.get(CYCLE_URL).mock(return_value=httpx.Response(200, json=page([cycle()])))
    since = dt.datetime(2026, 9, 19, 8, 0, tzinfo=timezone.utc)

    async with WhoopClient(FakeTokens()) as client:
        await whoop_api.get_cycles(client, start=since)

    params = respx.calls[0].request.url.params
    assert params["limit"] == "25"  # WHOOP's cap, not Spotify's 50
    assert params["start"] == since.isoformat()


@respx.mock
async def test_paging_follows_next_token_and_sorts_newest_first() -> None:
    route = respx.get(CYCLE_URL).mock(
        side_effect=[
            httpx.Response(
                200,
                json=page(
                    [cycle(101, start="2026-09-20T11:00:00+00:00", end="2026-09-21T10:00:00+00:00")],
                    next_token="page-2",
                ),
            ),
            httpx.Response(
                200, json=page([cycle(102, start="2026-09-21T11:00:00+00:00")])
            ),
        ]
    )

    async with WhoopClient(FakeTokens()) as client:
        cycles = await whoop_api.get_cycles(client)

    assert route.call_count == 2
    assert "nextToken" not in route.calls[0].request.url.params
    assert route.calls[1].request.url.params["nextToken"] == "page-2"
    assert [record.id for record in cycles] == ["102", "101"]
    assert cycles[0].is_open is True  # the cycle with no end is today's
    assert cycles[1].is_open is False


@respx.mock
async def test_paging_stops_at_the_cap_instead_of_looping_forever() -> None:
    """A server that always returns a token must not spin the refresh."""
    route = respx.get(CYCLE_URL).mock(
        return_value=httpx.Response(200, json=page([cycle()], next_token="always-more"))
    )

    async with WhoopClient(FakeTokens()) as client:
        records = await whoop_api._collect(
            client, "/v2/cycle", Cycle, what="cycle", max_pages=3
        )

    assert route.call_count == 3
    assert len(records) == 3


@respx.mock
async def test_an_unscored_record_has_no_figures_instead_of_zeroes() -> None:
    """``score`` is absent until ``score_state`` is SCORED; that must not read as 0."""
    respx.get(CYCLE_URL).mock(return_value=httpx.Response(200, json=page([cycle(strain=None)])))
    respx.get(RECOVERY_URL).mock(
        return_value=httpx.Response(200, json=page([recovery(score=None)]))
    )
    respx.get(SLEEP_URL).mock(
        return_value=httpx.Response(200, json=page([sleep(performance=None)]))
    )

    async with WhoopClient(FakeTokens()) as client:
        pending_cycle = (await whoop_api.get_cycles(client))[0]
        pending_recovery = (await whoop_api.get_recoveries(client))[0]
        pending_sleep = (await whoop_api.get_sleeps(client))[0]

    assert pending_cycle.is_scored is False
    assert pending_cycle.strain is None
    assert pending_recovery.scored_values is None
    assert pending_sleep.performance is None


@respx.mock
async def test_workouts_report_a_sport_name_or_fall_back_to_the_id() -> None:
    respx.get(WORKOUT_URL).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [
                    workout("w-1", sport_name="Running"),
                    workout(
                        "w-2",
                        sport_name=None,
                        sport_id=45,
                        start="2026-09-21T19:00:00+00:00",
                        end="2026-09-21T19:30:00+00:00",
                    ),
                ]
            ),
        )
    )

    async with WhoopClient(FakeTokens()) as client:
        workouts = await whoop_api.get_workouts(client)

    assert [record.id for record in workouts] == ["w-2", "w-1"]  # newest first
    assert workouts[0].sport == "sport 45"
    assert workouts[1].sport == "Running"


@respx.mock
async def test_a_body_we_cannot_read_becomes_a_whoop_error() -> None:
    respx.get(CYCLE_URL).mock(return_value=httpx.Response(200, json={"records": "nonsense"}))

    async with WhoopClient(FakeTokens()) as client:
        with pytest.raises(WhoopError, match="could not read"):
            await whoop_api.get_cycles(client)


@respx.mock
async def test_records_without_a_start_do_not_break_the_sort() -> None:
    """Mixing an aware timestamp with a missing one used to raise on comparison."""
    respx.get(CYCLE_URL).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [
                    {"id": 1, "score_state": "PENDING_SCORE"},
                    cycle(2, start="2026-09-21T06:00:00+00:00"),
                ]
            ),
        )
    )

    async with WhoopClient(FakeTokens()) as client:
        cycles = await whoop_api.get_cycles(client)

    assert [record.id for record in cycles] == ["2", "1"]


# ------------------------------------------------------------------- member's clock


def test_a_cycle_belongs_to_the_members_day_not_ours() -> None:
    """21:30 on the 20th in New York is already the 21st in UTC. WHOOP's day wins."""
    late = Cycle.model_validate(cycle(start="2026-09-21T02:30:00+00:00", offset="-05:00"))
    early = Cycle.model_validate(cycle(start="2026-09-20T22:00:00+00:00", offset="+05:30"))

    assert late.local_date == dt.date(2026, 9, 20)
    assert early.local_date == dt.date(2026, 9, 21)


def test_a_missing_or_broken_offset_falls_back_to_utc() -> None:
    assert offset_timezone(None) is timezone.utc
    assert offset_timezone("") is timezone.utc
    assert offset_timezone("nonsense") is timezone.utc
    assert offset_timezone("-0530") == timezone(-timedelta(hours=5, minutes=30))
    assert offset_timezone("+01:00") == timezone(timedelta(hours=1))


@pytest.mark.parametrize(
    ("hour", "offset", "expected"),
    [
        (2, None, "late_night"),
        (4, None, "late_night"),
        (5, None, "early_morning"),
        (7, None, "early_morning"),
        (8, None, "morning"),
        (11, None, "morning"),
        (12, None, "afternoon"),
        (16, None, "afternoon"),
        (17, None, "evening"),
        (21, None, "evening"),
        (22, None, "late_night"),
        (23, None, "late_night"),
        # Same instant, read on the member's clock rather than the server's.
        (13, "-05:00", "morning"),
        (13, "+05:30", "evening"),
    ],
)
def test_day_part_is_computed_in_the_members_timezone(
    hour: int, offset: str | None, expected: str
) -> None:
    moment = dt.datetime(2026, 9, 21, hour, 0, tzinfo=timezone.utc)

    assert body_state.day_part_for(moment, offset) == expected


@pytest.mark.parametrize(
    ("recovery_score", "expected"),
    [(None, None), (0.0, "low"), (33.9, "low"), (34.0, "medium"), (66.0, "medium"), (66.1, "high")],
)
def test_readiness_uses_whoops_own_bands(recovery_score: float | None, expected: str | None) -> None:
    assert body_state.readiness_for(recovery_score) == expected


# -------------------------------------------------------------------------------- sync


@respx.mock
async def test_a_refresh_stores_the_day_and_the_workout(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    mock_whoop(
        cycles=[cycle()],
        recoveries=[recovery()],
        sleeps=[sleep()],
        workouts=[workout()],
    )

    result = await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)

    assert result.ok and result.days == 1 and result.workouts == 1
    day = db.scalar(select(WhoopDaily).where(WhoopDaily.user_id == user.id))
    assert day is not None
    assert day.date == dt.date(2026, 9, 21)
    assert day.cycle_id == "101"
    assert day.timezone_offset == "-05:00"
    assert day.cycle_open is True
    assert day.day_strain == pytest.approx(9.4)
    assert day.recovery == pytest.approx(71.0)
    assert day.hrv_ms == pytest.approx(64.5)
    assert day.rhr == pytest.approx(52.0)
    assert day.sleep_performance == pytest.approx(88.0)
    assert day.calibrating is False

    stored_workout = db.scalar(select(WhoopWorkout).where(WhoopWorkout.user_id == user.id))
    assert stored_workout is not None
    assert stored_workout.whoop_id == "workout-uuid-1"
    assert stored_workout.sport == "Running"
    assert stored_workout.strain == pytest.approx(12.6)
    assert stored_workout.avg_hr == 148


@respx.mock
async def test_sleep_is_attached_through_the_recovery_link(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    """``recovery.sleep_id`` is authoritative, even when another sleep scores higher."""
    mock_whoop(
        cycles=[cycle()],
        recoveries=[recovery(sleep_id="sleep-uuid-1")],
        sleeps=[
            sleep("sleep-uuid-1", performance=72.0),
            sleep("sleep-uuid-2", performance=99.0, start="2026-09-21T14:00:00+00:00"),
        ],
    )

    await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)

    day = db.scalar(select(WhoopDaily).where(WhoopDaily.user_id == user.id))
    assert day is not None
    assert day.sleep_performance == pytest.approx(72.0)


@respx.mock
async def test_without_a_scored_recovery_the_longest_night_is_used(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    """Before recovery lands, naps must not be mistaken for last night."""
    mock_whoop(
        cycles=[cycle()],
        recoveries=[recovery(score=None)],
        sleeps=[
            sleep("nap-uuid", nap=True, performance=100.0),
            sleep("night-uuid", nap=False, performance=64.0),
        ],
    )

    await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)

    day = db.scalar(select(WhoopDaily).where(WhoopDaily.user_id == user.id))
    assert day is not None
    assert day.sleep_performance == pytest.approx(64.0)
    assert day.recovery is None  # a pending recovery stays unknown, not zero


@respx.mock
async def test_a_pending_rescore_does_not_erase_a_scored_day(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    mock_whoop(cycles=[cycle()], recoveries=[recovery()], sleeps=[sleep()])
    await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)

    # The same day re-read while WHOOP happens to be re-scoring it.
    respx.get(CYCLE_URL).mock(
        return_value=httpx.Response(200, json=page([cycle(strain=None)]))
    )
    respx.get(RECOVERY_URL).mock(
        return_value=httpx.Response(200, json=page([recovery(score=None)]))
    )
    await whoop_sync.refresh_body_data(user.id, force=True, session_factory=SessionLocal)

    db.expire_all()
    days = db.scalars(select(WhoopDaily).where(WhoopDaily.user_id == user.id)).all()
    assert len(days) == 1  # updated, not duplicated
    assert days[0].recovery == pytest.approx(71.0)
    assert days[0].day_strain == pytest.approx(9.4)
    assert days[0].sleep_performance == pytest.approx(88.0)


@respx.mock
async def test_a_fresh_day_is_served_from_the_database(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    """The rate limit is 100/min; a screen refresh must not spend four calls on it."""
    mock_whoop(cycles=[cycle()])
    await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)
    calls_after_first = len(respx.calls)

    second = await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)

    assert second.skipped is True
    assert len(respx.calls) == calls_after_first

    forced = await whoop_sync.refresh_body_data(
        user.id, force=True, session_factory=SessionLocal
    )
    assert forced.skipped is False
    assert len(respx.calls) > calls_after_first


@respx.mock
async def test_an_expired_ttl_reads_whoop_again(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    mock_whoop(cycles=[cycle()])
    await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)

    day = whoop_sync.latest_day(db, user.id)
    assert day is not None
    day.fetched_at = utcnow() - timedelta(seconds=settings.body_state_ttl_seconds + 60)
    db.add(day)
    db.commit()
    assert whoop_sync.is_fresh(day) is False

    result = await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)

    assert result.skipped is False


@respx.mock
async def test_a_whoop_failure_is_reported_not_raised(
    user: User, whoop_token: OAuthToken
) -> None:
    respx.get(CYCLE_URL).mock(
        return_value=httpx.Response(400, json={"message": "WHOOP is having a bad morning"})
    )

    result = await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)

    assert result.ok is False
    assert result.error == "WHOOP is having a bad morning"


@respx.mock
async def test_a_revoked_grant_is_raised_because_only_the_user_can_fix_it(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    whoop_token.expires_at = utcnow() - timedelta(minutes=1)
    db.add(whoop_token)
    db.commit()
    respx.post(whoop_auth.TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    with pytest.raises(WhoopAuthError):
        await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)


# -------------------------------------------------------------------------- body state


def test_body_state_without_whoop_says_so_instead_of_failing(db: Session, user: User) -> None:
    state = body_state.build(db, user.id)

    assert state.connected is False
    assert state.has_data is False
    assert state.recovery is None
    assert state.note == body_state.NOT_CONNECTED
    assert state.day_part  # mood and time of day are enough to chime in


def test_a_connected_whoop_with_no_data_yet_explains_the_wait(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    state = body_state.build(db, user.id)

    assert state.connected is True
    assert state.has_data is False
    assert state.note == body_state.NO_DATA


@respx.mock
async def test_calibration_is_flagged_as_a_caveat(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    mock_whoop(cycles=[cycle()], recoveries=[recovery(calibrating=True)], sleeps=[sleep()])
    await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)

    state = body_state.build(db, user.id)

    assert state.calibrating is True
    assert state.note == body_state.CALIBRATING


@respx.mock
async def test_body_state_reports_readiness_and_time_since_a_workout(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    finished = utcnow() - timedelta(minutes=90)
    mock_whoop(
        cycles=[cycle()],
        recoveries=[recovery(score=28.0)],
        sleeps=[sleep()],
        workouts=[
            workout(
                start=(finished - timedelta(minutes=45)).isoformat(),
                end=finished.isoformat(),
            )
        ],
    )
    await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)

    state = body_state.build(db, user.id)

    assert state.readiness == "low"
    assert state.minutes_since_last_workout == pytest.approx(90, abs=1)


@respx.mock
async def test_a_failed_refresh_shows_stored_figures_with_a_caveat(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    mock_whoop(cycles=[cycle()], recoveries=[recovery()], sleeps=[sleep()])
    await whoop_sync.refresh_body_data(user.id, session_factory=SessionLocal)
    stored = whoop_sync.latest_day(db, user.id)
    assert stored is not None
    stored.fetched_at = utcnow() - timedelta(seconds=settings.body_state_ttl_seconds + 60)
    db.add(stored)
    db.commit()

    respx.get(CYCLE_URL).mock(return_value=httpx.Response(400, json={"message": "nope"}))

    state = await body_state.read(user.id, session_factory=SessionLocal)

    assert state.has_data is True
    assert state.recovery == pytest.approx(71.0)  # yesterday's figures, not an error
    assert state.note == body_state.STALE


@respx.mock
async def test_a_revoked_grant_asks_the_user_to_reconnect(
    db: Session, user: User, whoop_token: OAuthToken
) -> None:
    whoop_token.expires_at = utcnow() - timedelta(minutes=1)
    db.add(whoop_token)
    db.commit()
    respx.post(whoop_auth.TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    state = await body_state.read(user.id, session_factory=SessionLocal)

    assert state.note == body_state.RECONNECT
    # Still "connected" as far as the stored row goes, so the flag is what the UI reads.
    assert state.connected is True
    assert state.needs_reconnect is True


@respx.mock
async def test_a_disconnected_whoop_never_calls_the_api(user: User) -> None:
    """No routes are registered on purpose: any outbound call fails the test."""
    state = await body_state.read(user.id, session_factory=SessionLocal)

    assert state.connected is False
    assert state.note == body_state.NOT_CONNECTED


# ----------------------------------------------------------------------------- routes


def test_body_state_needs_a_session(client: TestClient) -> None:
    assert client.get("/api/body-state").status_code == 401


def test_body_state_endpoint_answers_even_without_whoop(client: TestClient, user: User) -> None:
    sign_in(client, user)

    response = client.get("/api/body-state")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["has_data"] is False
    assert body["recovery"] is None
    assert body["note"] == body_state.NOT_CONNECTED
    assert body["day_part"] in {
        "late_night",
        "early_morning",
        "morning",
        "afternoon",
        "evening",
    }


def test_whoop_connect_needs_a_session(client: TestClient) -> None:
    assert client.get("/auth/whoop/login", follow_redirects=False).status_code == 401


def begin_whoop_connect(client: TestClient) -> str:
    response = client.get("/auth/whoop/login", follow_redirects=False)
    assert response.status_code == 307
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert len(query["state"][0]) == 8
    return query["state"][0]


def mock_connect(*, refresh_token: str | None = "whoop-refresh") -> None:
    tokens: dict[str, Any] = {
        "access_token": "whoop-access",
        "token_type": "bearer",
        "expires_in": 3600,
        "scope": whoop_auth.SCOPE_STRING,
    }
    if refresh_token:
        tokens["refresh_token"] = refresh_token
    respx.post(whoop_auth.TOKEN_URL).mock(return_value=httpx.Response(200, json=tokens))
    respx.get(PROFILE_URL).mock(
        return_value=httpx.Response(200, json={"user_id": 12345, "first_name": "Abhinav"})
    )


@respx.mock
def test_whoop_connect_stores_tokens_and_pulls_the_first_day(
    client: TestClient, db: Session, user: User
) -> None:
    sign_in(client, user)
    mock_connect()
    mock_whoop(cycles=[cycle()], recoveries=[recovery()], sleeps=[sleep()])
    state = begin_whoop_connect(client)

    response = client.get(
        f"/auth/whoop/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "http://127.0.0.1:5173/"

    token = db.scalar(
        select(OAuthToken).where(OAuthToken.user_id == user.id, OAuthToken.provider == "whoop")
    )
    assert token is not None
    assert decrypt(token.access_token_enc) == "whoop-access"
    assert "whoop-refresh" not in (token.refresh_token_enc or "")
    assert decrypt(token.refresh_token_enc or "") == "whoop-refresh"

    # The first day should already be in, so Home has figures on the way back.
    assert db.scalar(select(WhoopDaily).where(WhoopDaily.user_id == user.id)) is not None
    assert client.get("/api/me").json()["connections"] == {"spotify": False, "whoop": True}


@respx.mock
def test_whoop_connect_fails_loudly_without_a_refresh_token(
    client: TestClient, db: Session, user: User
) -> None:
    """A connection that dies in an hour is worse than one that never appeared."""
    sign_in(client, user)
    mock_connect(refresh_token=None)
    state = begin_whoop_connect(client)

    response = client.get(
        f"/auth/whoop/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 502
    assert "offline" in response.json()["detail"]
    assert (
        db.scalar(
            select(OAuthToken).where(
                OAuthToken.user_id == user.id, OAuthToken.provider == "whoop"
            )
        )
        is None
    )


@respx.mock
def test_whoop_callback_rejects_a_forged_state(client: TestClient, db: Session, user: User) -> None:
    sign_in(client, user)
    mock_connect()
    begin_whoop_connect(client)

    response = client.get(
        "/auth/whoop/callback?code=auth-code&state=deadbeef", follow_redirects=False
    )

    assert response.status_code == 400
    assert "stale" in response.json()["detail"]
    assert not respx.calls  # the code was never exchanged


@respx.mock
def test_whoop_callback_rejects_a_spotify_handshake(
    client: TestClient, db: Session, user: User
) -> None:
    """The two providers share one cookie, so the provider has to be checked too."""
    sign_in(client, user)
    respx.post(whoop_auth.TOKEN_URL)
    login = client.get("/auth/spotify/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/whoop/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 400
    assert not respx.calls


@respx.mock
def test_whoop_callback_reports_a_refused_consent_screen(client: TestClient, user: User) -> None:
    sign_in(client, user)
    state = begin_whoop_connect(client)

    response = client.get(
        f"/auth/whoop/callback?error=access_denied&state={state}", follow_redirects=False
    )

    assert response.status_code == 400
    assert "did not grant access" in response.json()["detail"]
