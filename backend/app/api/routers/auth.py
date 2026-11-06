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
    # Enforce uniqueness
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    # Public registrations ALWAYS receive the RESEARCHER role.
    new_user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Create initial session
    raw_refresh = generate_refresh_token()
    refresh_hash = hash_token(raw_refresh)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    session = RefreshSession(
        user_id=new_user.id,
        token_hash=refresh_hash,
        user_agent=request.headers.get("User-Agent", "")[:512],
        ip_address=request.client.host if request.client else None,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()

    access_token = create_access_token(new_user.id, new_user.role)
    csrf_token = generate_csrf_token()

    set_auth_cookies(response, access_token, raw_refresh, csrf_token)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return new_user


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
    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password. Please try again.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise generic_error

    if not verify_password(payload.password, user.hashed_password):
        raise generic_error

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is currently deactivated. Please contact an administrator.",
        )

    # Generate session & tokens
    raw_refresh = generate_refresh_token()
    refresh_hash = hash_token(raw_refresh)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    session = RefreshSession(
        user_id=user.id,
        token_hash=refresh_hash,
        user_agent=request.headers.get("User-Agent", "")[:512],
        ip_address=request.client.host if request.client else None,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()

    access_token = create_access_token(user.id, user.role)
    csrf_token = generate_csrf_token()

    set_auth_cookies(response, access_token, raw_refresh, csrf_token)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return user


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
    raw_refresh = request.cookies.get("nf_refresh_token")
    if not raw_refresh:
        # Check authorization header or body if needed
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh session present. Please sign in again.",
        )

    token_hash = hash_token(raw_refresh)
    session = (
        db.query(RefreshSession)
        .filter(RefreshSession.token_hash == token_hash)
        .first()
    )

    now = datetime.now(timezone.utc)
    if not session or session.is_revoked or session.expires_at.replace(tzinfo=timezone.utc) < now:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or was revoked. Please sign in again.",
        )

    user = db.query(User).filter(User.id == session.user_id).first()
    if not user or not user.is_active:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account inactive or not found.",
        )

    # Refresh token rotation: Revoke existing session and create new one
    session.is_revoked = True
    session.last_used_at = now

    new_raw_refresh = generate_refresh_token()
    new_token_hash = hash_token(new_raw_refresh)
    new_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    new_session = RefreshSession(
        user_id=user.id,
        token_hash=new_token_hash,
        user_agent=request.headers.get("User-Agent", "")[:512],
        ip_address=request.client.host if request.client else None,
        expires_at=new_expires_at,
    )
    db.add(new_session)
    db.commit()

    access_token = create_access_token(user.id, user.role)
    csrf_token = generate_csrf_token()

    set_auth_cookies(response, access_token, new_raw_refresh, csrf_token)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return user


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
    raw_refresh = request.cookies.get("nf_refresh_token")
    if raw_refresh:
        token_hash = hash_token(raw_refresh)
        session = db.query(RefreshSession).filter(RefreshSession.token_hash == token_hash).first()
        if session:
            session.is_revoked = True
            db.commit()

    clear_auth_cookies(response)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return {"message": "You have been signed out safely."}


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
    # Verify CSRF on state change
    verify_csrf(request)

    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your current password was not entered correctly.",
        )

    # Hash new password with Argon2
    current_user.hashed_password = get_password_hash(payload.new_password)
    current_user.updated_at = datetime.now(timezone.utc)

    # Revoke all existing refresh sessions for this user for security
    db.query(RefreshSession).filter(
        RefreshSession.user_id == current_user.id,
        RefreshSession.is_revoked == False,
    ).update({"is_revoked": True})
    db.commit()

    # Issue a fresh new session for current device
    raw_refresh = generate_refresh_token()
    refresh_hash = hash_token(raw_refresh)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    session = RefreshSession(
        user_id=current_user.id,
        token_hash=refresh_hash,
        user_agent=request.headers.get("User-Agent", "")[:512],
        ip_address=request.client.host if request.client else None,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()

    access_token = create_access_token(current_user.id, current_user.role)
    csrf_token = generate_csrf_token()

    set_auth_cookies(response, access_token, raw_refresh, csrf_token)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return {"message": "Your password has been updated securely."}


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
    current_user.full_name = payload.full_name
    current_user.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(current_user)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return current_user

