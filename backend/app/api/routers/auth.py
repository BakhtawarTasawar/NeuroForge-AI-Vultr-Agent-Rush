
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    clear_auth_cookies,
    get_current_user,
    get_db,
    set_auth_cookies,
    verify_csrf,
)
from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_csrf_token,
    generate_refresh_token,
    get_password_hash,
    hash_token,
    verify_password,
)
from app.db.models import RefreshSession, User, UserRole
from app.schemas.models import (
    ChangePasswordRequest,
    ProfileUpdateRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _utc_now() -> datetime:
    """Return timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def _session_expired(expires_at: datetime, now: datetime) -> bool:
    """Safely compare database timestamps with timezone-aware UTC."""
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return expires_at <= now


def _request_ip(request: Request) -> str | None:
    """Get the direct client IP without trusting forwarded headers."""
    return request.client.host if request.client else None


def _create_refresh_session(
    db: Session,
    user: User,
    request: Request,
    now: datetime,
) -> str:
    """
    Create a server-side refresh session.

    Only the hash of the refresh token is stored in the database.
    The raw token is returned so it can be placed in an HttpOnly cookie.
    """
    raw_refresh = generate_refresh_token()

    refresh_session = RefreshSession(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        user_agent=request.headers.get("User-Agent", "")[:512],
        ip_address=_request_ip(request),
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    db.add(refresh_session)
    return raw_refresh


def _issue_auth_cookies(
    response: Response,
    user: User,
    raw_refresh: str,
) -> None:
    """Issue a fresh access token, refresh token and CSRF token."""
    access_token = create_access_token(user.id, user.role)
    csrf_token = generate_csrf_token()

    set_auth_cookies(
        response,
        access_token,
        raw_refresh,
        csrf_token,
    )

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"


def _clear_session_and_raise(
    response: Response,
    detail: str,
) -> None:
    """Clear invalid authentication cookies and return a generic 401."""
    clear_auth_cookies(response)

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new researcher account",
)
def register(
    payload: UserRegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        existing_user = (
            db.query(User)
            .filter(User.email == payload.email)
            .first()
        )

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email address already exists.",
            )

        # Public registration must never assign an administrator role.
        new_user = User(
            email=payload.email,
            hashed_password=get_password_hash(payload.password),
            full_name=payload.full_name,
            role=UserRole.RESEARCHER.value,
            is_active=True,
        )

        db.add(new_user)
        db.flush()

        now = _utc_now()
        raw_refresh = _create_refresh_session(
            db=db,
            user=new_user,
            request=request,
            now=now,
        )

        db.commit()
        db.refresh(new_user)

        _issue_auth_cookies(response, new_user, raw_refresh)
        return new_user

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise


@router.post(
    "/login",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Sign in to researcher account",
)
def login(
    payload: UserLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.email == payload.email)
        .first()
    )

    if not user or not verify_password(
        payload.password,
        user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password. Please try again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is currently deactivated. Please contact an administrator.",
        )

    try:
        now = _utc_now()

        raw_refresh = _create_refresh_session(
            db=db,
            user=user,
            request=request,
            now=now,
        )

        db.commit()

        _issue_auth_cookies(response, user, raw_refresh)
        return user

    except Exception:
        db.rollback()
        raise


@router.post(
    "/refresh",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate refresh token and issue fresh access token",
)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    # Refresh uses an HttpOnly cookie, so CSRF protection is required.
    verify_csrf(request)

    raw_refresh = request.cookies.get("nf_refresh_token")

    if not raw_refresh:
        _clear_session_and_raise(
            response,
            "Your session has expired. Please sign in again.",
        )

    token_hash = hash_token(raw_refresh)

    try:
        # Lock the matching session row to reduce concurrent rotation races.
        session = (
            db.query(RefreshSession)
            .filter(RefreshSession.token_hash == token_hash)
            .with_for_update()
            .first()
        )

        now = _utc_now()

        if (
            not session
            or session.is_revoked
            or _session_expired(session.expires_at, now)
        ):
            db.rollback()
            _clear_session_and_raise(
                response,
                "Your session has expired. Please sign in again.",
            )

        user = (
            db.query(User)
            .filter(User.id == session.user_id)
            .first()
        )

        if not user or not user.is_active:
            db.rollback()
            _clear_session_and_raise(
                response,
                "Your account is unavailable. Please sign in again.",
            )

        # Revoke the old token and issue a new one in the same transaction.
        session.is_revoked = True
        session.last_used_at = now

        new_raw_refresh = _create_refresh_session(
            db=db,
            user=user,
            request=request,
            now=now,
        )

        db.commit()

        _issue_auth_cookies(response, user, new_raw_refresh)
        return user

    except HTTPException:
        raise

    except Exception:
        db.rollback()
        raise


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Sign out and revoke refresh session",
)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    # Logout is a cookie-authenticated state-changing operation.
    verify_csrf(request)

    raw_refresh = request.cookies.get("nf_refresh_token")

    try:
        if raw_refresh:
            token_hash = hash_token(raw_refresh)

            session = (
                db.query(RefreshSession)
                .filter(RefreshSession.token_hash == token_hash)
                .first()
            )

            if session and not session.is_revoked:
                session.is_revoked = True
                session.last_used_at = _utc_now()
                db.commit()

        clear_auth_cookies(response)

        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"

        return {"message": "You have been signed out safely."}

    except Exception:
        db.rollback()
        raise


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current researcher profile",
)
def get_me(
    response: Response,
    current_user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"

    return current_user


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Update account password securely",
)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_csrf(request)

    if not verify_password(
        payload.current_password,
        current_user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your current password was not entered correctly.",
        )

    try:
        current_user.hashed_password = get_password_hash(
            payload.new_password
        )
        current_user.updated_at = _utc_now()

        # Revoke all previous sessions.
        db.query(RefreshSession).filter(
            RefreshSession.user_id == current_user.id,
            RefreshSession.is_revoked.is_(False),
        ).update(
            {"is_revoked": True},
            synchronize_session=False,
        )

        now = _utc_now()

        # Issue a new session for the current device.
        raw_refresh = _create_refresh_session(
            db=db,
            user=current_user,
            request=request,
            now=now,
        )

        db.commit()
        db.refresh(current_user)

        _issue_auth_cookies(response, current_user, raw_refresh)

        return {
            "message": "Your password has been updated securely."
        }

    except Exception:
        db.rollback()
        raise


@router.patch(
    "/profile",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update profile details",
)
def update_profile(
    payload: ProfileUpdateRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_csrf(request)

    try:
        current_user.full_name = payload.full_name
        current_user.updated_at = _utc_now()

        db.commit()
        db.refresh(current_user)

        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"

        return current_user

    except Exception:
        db.rollback()
        raise
