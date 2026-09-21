from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.schemas.body import BodyStateResponse
from app.services import body_state

router = APIRouter(tags=["body"])


@router.get("/body-state", response_model=BodyStateResponse)
async def read_body_state(
    user: CurrentUser,
    refresh: bool = Query(
        False, description="Read WHOOP now instead of serving the cached day."
    ),
) -> BodyStateResponse:
    """Today's body context.

    Always answers 200. A missing or failing WHOOP is described in ``note`` rather than
    raised, because Chime in has to work on mood and time of day alone.
    """
    state = await body_state.read(user.id, force=refresh)
    return BodyStateResponse.model_validate(state)
