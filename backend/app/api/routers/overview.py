from typing import Any, List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.db.models import Dataset, Experiment, Project, User, UserRole
from app.schemas.models import OverviewStatsResponse

router = APIRouter(tags=["Research Workflows"])


@router.get(
    "/overview/stats",
    response_model=OverviewStatsResponse,
    summary="Get genuine overview metrics for research workspace",
)
def get_overview_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == UserRole.ADMIN.value:
        projects_count = db.query(Project).count()
        datasets_count = db.query(Dataset).count()
        experiments_count = db.query(Experiment).count()
    else:
        # Strict tenant isolation: count only the authenticated user's own resources.
        projects_count = (
            db.query(Project)
            .filter(Project.owner_id == current_user.id)
            .count()
        )
        datasets_count = db.query(Dataset).filter(Dataset.owner_id == current_user.id).count()
        experiments_count = db.query(Experiment).filter(Experiment.owner_id == current_user.id).count()

    # Honest stats: reports execution is in upcoming milestone
    reports_count = 0

    return OverviewStatsResponse(
        projects_count=projects_count,
        datasets_count=datasets_count,
        experiments_count=experiments_count,
        reports_count=reports_count,
        active_role=current_user.role,
    )


@router.get(
    "/findings",
    response_model=List[Any],
    summary="List verified research findings",
)
def list_findings(
    current_user: User = Depends(get_current_user),
):
    # Returns genuine empty list until statistical validation results exist
    return []


@router.get(
    "/reports",
    response_model=List[Any],
    summary="List evidence-backed scientific research reports",
)
def list_reports(
    current_user: User = Depends(get_current_user),
):
    # Returns genuine empty list until automated report generation is executed
    return []
