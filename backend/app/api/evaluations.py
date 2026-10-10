from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.models import EvaluationRun, User
from app.schemas import EvaluationOverviewOut, EvaluationRunOut
from app.services.evaluation import run_evaluation, user_satisfaction

router = APIRouter(prefix="/evaluations", tags=["自动评测"])


@router.get("", response_model=EvaluationOverviewOut)
def evaluation_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("service", "admin")),
) -> EvaluationOverviewOut:
    history = list(
        db.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(20))
    )
    satisfaction, positive, negative = user_satisfaction(db)
    return EvaluationOverviewOut(
        latest=history[0] if history else None,
        history=history,
        user_satisfaction=satisfaction,
        positive_feedback=positive,
        negative_feedback=negative,
    )


@router.post("/run", response_model=EvaluationRunOut)
def start_evaluation(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("service", "admin")),
) -> EvaluationRun:
    return run_evaluation(db, user)
