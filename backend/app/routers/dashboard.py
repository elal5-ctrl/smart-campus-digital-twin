from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard import build_dashboard_data

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def get_dashboard_data(
    session: Annotated[Session, Depends(get_session)],
) -> DashboardResponse:
    return DashboardResponse.model_validate(build_dashboard_data(session))
