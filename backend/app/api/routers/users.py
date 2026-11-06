from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_roles, verify_csrf
from app.db.models import RefreshSession, User, UserRole
from app.schemas.models import (
    UserResponse,
    UserUpdateRoleRequest,
    UserUpdateStatusRequest,
)

router = APIRouter(prefix="/users", tags=["User Management"])


@router.get(
    "",
    response_model=List[UserResponse],
    summary="List all registered platform users (Admin only)",
)
def list_users(
    current_admin: User = Depends(require_roles([UserRole.ADMIN])),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return users


@router.patch(
    "/{user_id}/role",
    response_model=UserResponse,
    summary="Update user platform role (Admin only)",
)
def update_user_role(
    user_id: str,
    payload: UserUpdateRoleRequest,
    request: Request,
    current_admin: User = Depends(require_roles([UserRole.ADMIN])),
    db: Session = Depends(get_db),
):
    verify_csrf(request)

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested user account was not found.",
        )

    # Protection: Do not allow demoting the last active administrator
    if target_user.role == UserRole.ADMIN.value and payload.role != UserRole.ADMIN:
        active_admins_count = (
            db.query(User)
            .filter(User.role == UserRole.ADMIN.value, User.is_active == True)
            .count()
        )
        if active_admins_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last active system administrator. Promote another administrator first.",
            )

    target_user.role = payload.role.value
    db.commit()
    db.refresh(target_user)
    return target_user


@router.patch(
    "/{user_id}/status",
    response_model=UserResponse,
    summary="Activate or deactivate user account (Admin only)",
)
def update_user_status(
    user_id: str,
    payload: UserUpdateStatusRequest,
    request: Request,
    current_admin: User = Depends(require_roles([UserRole.ADMIN])),
    db: Session = Depends(get_db),
):
    verify_csrf(request)

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested user account was not found.",
        )

    # Protection: Do not allow deactivating the last active administrator
    if target_user.role == UserRole.ADMIN.value and not payload.is_active:
        active_admins_count = (
            db.query(User)
            .filter(User.role == UserRole.ADMIN.value, User.is_active == True)
            .count()
        )
        if active_admins_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate the last active system administrator.",
            )

    target_user.is_active = payload.is_active

    # If deactivating, immediately revoke all active refresh sessions
    if not payload.is_active:
        db.query(RefreshSession).filter(
            RefreshSession.user_id == target_user.id,
            RefreshSession.is_revoked == False,
        ).update({"is_revoked": True})

    db.commit()
    db.refresh(target_user)
    return target_user

