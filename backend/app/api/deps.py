from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.cookies import read_session
from app.db.session import get_db
from app.models import User

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DbSession) -> User:
    payload = read_session(request)
    user = db.get(User, payload["uid"]) if payload and "uid" in payload else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in with Spotify to continue."
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
