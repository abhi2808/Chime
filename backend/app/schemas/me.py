from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Connections(BaseModel):
    spotify: bool
    whoop: bool


class MeResponse(BaseModel):
    id: int
    display_name: str | None
    spotify_user_id: str | None
    created_at: datetime
    connections: Connections
