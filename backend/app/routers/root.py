from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/")
async def root():
    settings = get_settings()

    return {
        "name": settings.project_name,
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "database_health": "/health/db",
    }
