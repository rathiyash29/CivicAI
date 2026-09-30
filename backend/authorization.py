"""
Request-level authorization for the CivicAI API.

This module exists so that authentication dependencies do not have to live in
`backend/main.py`. `backend/router.py` (the intelligence router) needs to
require an officer, and importing `main` from `router` would be circular:
`main` mounts `router` at import time. Importing only `backend.auth` here keeps
the dependency graph one-directional.

Nothing about the JWT itself is re-implemented or changed: tokens are still
issued by `auth.create_access_token` and validated by
`auth.decode_access_token`, and `/auth/*` responses are untouched.
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend import auth as auth_module
from backend.auth import UserResponse, UserRole, decode_access_token
from database.db import get_db

# auto_error=False so a missing Authorization header reaches the dependency
# below and becomes a clean 401 instead of FastAPI's own error shape.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

OFFICER_ROLE = UserRole.OFFICER


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    The authenticated user, or 401.

    The account is re-read from PostgreSQL on every request rather than trusted
    from the token. That costs one indexed lookup and buys the property that a
    token is only proof of *which* account: a role that changed, or an account
    that was deleted, takes effect immediately instead of at token expiry.

    A validly signed token with no matching account is still a 401. That happens
    when the account was deleted, and treating it as anonymous would silently
    drop the identity instead of failing.
    """
    # With auto_error=False a request with no Authorization header arrives here
    # with token=None. Passing None into jose raises AttributeError, which
    # surfaced as a 500 instead of a 401.
    if not token:
        raise _unauthorized()
    token_data = decode_access_token(token)
    if token_data is None:
        raise _unauthorized()

    # `sub` is the account email. A purely numeric subject is still accepted so
    # a token minted by an older build that used the row id keeps working.
    subject = token_data.email or ""
    row = (
        auth_module.get_user_by_id(db, int(subject))
        if subject.isdigit()
        else auth_module.get_user_by_email(db, subject)
    )
    if row is None:
        raise _unauthorized()
    return auth_module.to_response(row)


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[UserResponse]:
    """
    The authenticated user, or None.

    Used by endpoints with a legacy anonymous path that must keep working. A
    bad or absent token is None here rather than 401, which is the whole point
    of the optional variant.

    `get_current_user` is invoked directly rather than through `Depends`, so
    both of its parameters have to be passed explicitly. Getting this wrong
    silently passed the token string in as the database session.
    """
    if not token:
        return None
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None


async def require_officer(
    current_user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    """
    Require the `officer` role. 401 without a usable token, 403 for a citizen.

    Applied as a router-level dependency on the intelligence router so that
    every endpoint under it -- including the mutating ones -- is protected by
    default and a newly added endpoint cannot accidentally be public.
    """
    if (current_user.role or "").strip().lower() != OFFICER_ROLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is restricted to officers",
        )
    return current_user
