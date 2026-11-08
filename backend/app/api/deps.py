from datetime import datetime, timezone
from typing import Generator, Optional, List
import secrets
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.database import get_db
from app.db.models import User, UserRole


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Retrieve current user from cookie or Authorization header, or None if unauthenticated."""
    token = request.cookies.get("nf_access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

    if not token:
        return None

    try:
        payload = decode_access_token(token)
        user_id: str = payload.get("sub")
        if not user_id:
            return None
    except Exception:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        return None
    return user


def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """Enforce authentication; return active user or raise 401."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your research session has expired or is invalid. Please sign in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(allowed_roles: List[UserRole]):
    """Enforce role-based access control."""
    allowed_values = [r.value for r in allowed_roles]

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have sufficient permissions to access this scientific resource.",
            )
        return current_user

    return role_checker


def verify_csrf(request: Request) -> None:
    """
    Validate CSRF tokens on state-changing cookie-authenticated requests.
    Applies to both access-token and refresh-token sessions.
    """
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return

    uses_cookie_auth = (
        "nf_access_token" in request.cookies
        or "nf_refresh_token" in request.cookies
    )

    if not uses_cookie_auth:
        return

    csrf_cookie = request.cookies.get("nf_csrf_token")
    csrf_header = request.headers.get("X-CSRF-Token")

    if (
        not csrf_cookie
        or not csrf_header
        or not secrets.compare_digest(csrf_cookie, csrf_header)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Security verification failed. Please refresh and try again.",
        )

def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
) -> None:
    """Set secure authentication and CSRF cookies."""
    # Access token cookie (HttpOnly)
    response.set_cookie(
        key="nf_access_token",
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    # Refresh token cookie (HttpOnly)
    response.set_cookie(
        key="nf_refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/",
    )
    # CSRF cookie (Readable by JS for setting X-CSRF-Token header)
    response.set_cookie(
        key="nf_csrf_token",
        value=csrf_token,
        httponly=False,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    """Clear all authentication and CSRF cookies."""
    response.delete_cookie(key="nf_access_token", path="/", secure=settings.COOKIE_SECURE, samesite=settings.COOKIE_SAMESITE)
    response.delete_cookie(key="nf_refresh_token", path="/", secure=settings.COOKIE_SECURE, samesite=settings.COOKIE_SAMESITE)
    response.delete_cookie(key="nf_csrf_token", path="/", secure=settings.COOKIE_SECURE, samesite=settings.COOKIE_SAMESITE)

