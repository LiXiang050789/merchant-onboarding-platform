from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import User
from .security import decode_token


bearer = HTTPBearer(auto_error=False)


async def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    trace_id = getattr(request.state, "trace_id", "")
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized", "trace_id": trace_id})
    try:
        payload = decode_token(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized", "trace_id": trace_id})
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized", "trace_id": trace_id})
    user = await session.scalar(select(User).where(User.id == payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized", "trace_id": trace_id})
    request.state.tenant_id = user.tenant_id
    request.state.user_id = user.id
    return user
