"""Development-only views into the engine.

Phase 3 builds the ranking before there is any session or playback to hang it on, so
there has to be a way to look at it. These routes read; they never create a session,
touch a playlist or start playback.

Mounted only when ``ENABLE_DEV_API`` is true.
"""

from __future__ import annotations

import statistics

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.ranking import PoolSummary, RankedTrack, RankResponse, ScoreBreakdown
from app.schemas.body import BodyStateResponse
from app.services import body_state, ranking
from app.services.profile_rules import DEFAULT_INTENT, DEFAULT_TYPE, build_profile

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/rank", response_model=RankResponse)
async def rank_preview(
    user: CurrentUser,
    db: DbSession,
    mood: str | None = Query(None, description="wired | drained | flat | steady | fired_up"),
    type: str = Query(DEFAULT_TYPE, description="auto | workout | focus | wind_down | wake_up"),
    intent: str = Query(DEFAULT_INTENT, description="match | shift"),
    count: int = Query(25, ge=1, le=100),
    refresh: bool = Query(False, description="Read WHOOP now instead of the cached day."),
) -> RankResponse:
    """What Chime in would queue right now, and why."""
    state = await body_state.read(user.id, force=refresh)
    try:
        profile = build_profile(state, mood=mood, session_type=type, intent=intent)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    pool = ranking.candidates_for(db, user.id)
    confidences = [item.effective_confidence for item in pool]
    tagged = sum(1 for value in confidences if value > 0)
    summary = PoolSummary(
        size=len(pool),
        tagged=tagged,
        untagged=len(pool) - tagged,
        mean_confidence=round(statistics.fmean(confidences), 3) if confidences else 0.0,
    )

    return RankResponse(
        body=BodyStateResponse.model_validate(state),
        profile=profile.as_dict(positions=count),
        pool=summary,
        tracks=[
            RankedTrack(
                position=item.position,
                track_id=item.candidate.track_id,
                spotify_track_id=item.candidate.spotify_track_id,
                name=item.candidate.name,
                artists=list(item.candidate.artist_names),
                score=item.score,
                breakdown=ScoreBreakdown.model_validate(item.breakdown),
            )
            for item in ranking.rank(pool, profile, count=count)
        ],
    )
