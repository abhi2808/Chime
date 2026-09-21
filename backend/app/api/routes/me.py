from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import OAuthToken
from app.schemas.me import Connections, MeResponse

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
def read_me(user: CurrentUser, db: DbSession) -> MeResponse:
    providers = set(
        db.scalars(select(OAuthToken.provider).where(OAuthToken.user_id == user.id)).all()
    )
    return MeResponse(
        id=user.id,
        display_name=user.display_name,
        spotify_user_id=user.spotify_user_id,
        created_at=user.created_at,
        connections=Connections(
            spotify="spotify" in providers,
            whoop="whoop" in providers,
        ),
    )
