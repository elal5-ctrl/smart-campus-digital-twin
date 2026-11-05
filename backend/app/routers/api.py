from fastapi import APIRouter

from app.routers.dashboard import router as dashboard_router
from app.routers.environment import router as environment_router
from app.routers.measurements import router as measurements_router
from app.routers.model import router as physical_model_router
from app.routers.predictions import router as predictions_router
from app.routers.routerimport import router as import_router
from app.routers.thermal_image import router as thermal_image_router

router = APIRouter()


@router.get("")
def api_root():
    return {
        "status": "ok",
        "dashboard": "/dashboard",
        "environment": "/environment",
        "import": "/import/",
        "measurements": "/measurements",
        "model": "/model",
        "predictions": "/predictions",
        "thermal_image": "/thermal-image",
    }


router.include_router(dashboard_router)
router.include_router(environment_router)
router.include_router(measurements_router)
router.include_router(predictions_router)
router.include_router(import_router)
router.include_router(physical_model_router)
router.include_router(thermal_image_router)
