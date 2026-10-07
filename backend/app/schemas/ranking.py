from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.body import BodyStateResponse


class ScoreBreakdown(BaseModel):
    """Why a track is where it is. Stored on ``session_tracks.score_breakdown`` too."""

    energy_fit: float
    affinity: float
    behavior: float
    freshness: float
    score: float
    energy: float
    confidence: float
    #: Target energy at this position, for comparing the curve against what it got.
    target: float
    #: The source's own tags, strongest first, so a wrong energy can be traced to a tag.
    tags: list[str] = Field(default_factory=list)


class RankedTrack(BaseModel):
    position: int
    track_id: int
    spotify_track_id: str
    name: str
    artists: list[str] = Field(default_factory=list)
    score: float
    breakdown: ScoreBreakdown


class PoolSummary(BaseModel):
    """How much the engine had to work with, which is the first thing to check when a
    ranking looks wrong."""

    size: int
    tagged: int
    untagged: int
    mean_confidence: float = 0.0


class RankResponse(BaseModel):
    """A development view of one ranking, without creating a session or playing anything."""

    body: BodyStateResponse
    #: ``TargetProfile.as_dict()``: type, intent, mood, curve, ceiling, affinities, notes.
    profile: dict
    pool: PoolSummary
    tracks: list[RankedTrack] = Field(default_factory=list)
