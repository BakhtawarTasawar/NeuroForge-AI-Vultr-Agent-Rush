from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles, verify_csrf
from app.db.models import Project, User, UserRole
from app.schemas.models import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
)

router = APIRouter(prefix="/projects", tags=["Research Projects"])


@router.get(
    "",
    response_model=List[ProjectResponse],
    summary="List accessible scientific research projects",
)
def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == UserRole.ADMIN.value:
        projects = db.query(Project).order_by(Project.created_at.desc()).all()
    else:
        # Researchers and Viewers see owned or platform research projects
        projects = (
            db.query(Project)
            .filter(
                (Project.owner_id == current_user.id) | (Project.status != "Archived")
            )
            .order_by(Project.created_at.desc())
            .all()
        )

    results = []
    for p in projects:
        owner_name = p.owner.full_name if p.owner else "Unknown Researcher"
        res = ProjectResponse(
            id=p.id,
            title=p.title,
            description=p.description,
            domain=p.domain,
            status=p.status,
            owner_id=p.owner_id,
            owner_name=owner_name,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        results.append(res)
    return results


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new research project (Researchers and Admins only)",
)
def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.RESEARCHER])),
    db: Session = Depends(get_db),
):
    verify_csrf(request)

    project = Project(
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        domain=payload.domain,
        status="Active",
        owner_id=current_user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return ProjectResponse(
        id=project.id,
        title=project.title,
        description=project.description,
        domain=project.domain,
        status=project.status,
        owner_id=project.owner_id,
        owner_name=current_user.full_name,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project details",
)
def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested scientific research project was not found.",
        )

    return ProjectResponse(
        id=project.id,
        title=project.title,
        description=project.description,
        domain=project.domain,
        status=project.status,
        owner_id=project.owner_id,
        owner_name=project.owner.full_name if project.owner else "Unknown Researcher",
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.put(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update research project details",
)
def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_csrf(request)

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested research project was not found.",
        )

    # Permission check: Only project owner or ADMIN may modify
    if current_user.role != UserRole.ADMIN.value and project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the project creator or an administrator can update this research project.",
        )

    if payload.title is not None:
        project.title = payload.title.strip()
    if payload.description is not None:
        project.description = payload.description.strip()
    if payload.domain is not None:
        project.domain = payload.domain.strip()
    if payload.status is not None:
        project.status = payload.status.strip()

    project.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)

    return ProjectResponse(
        id=project.id,
        title=project.title,
        description=project.description,
        domain=project.domain,
        status=project.status,
        owner_id=project.owner_id,
        owner_name=project.owner.full_name if project.owner else "Unknown Researcher",
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete research project",
)
def delete_project(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_csrf(request)

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested research project was not found.",
        )

    # Permission check: Only project owner or ADMIN may delete
    if current_user.role != UserRole.ADMIN.value and project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the project creator or an administrator can delete this research project.",
        )

    db.delete(project)
    db.commit()
    return {"message": "Research project has been safely removed."}

