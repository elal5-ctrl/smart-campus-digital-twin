from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from app.schemas.thermal_image import ThermalImageStatusResponse
from app.services.thermal_image import (
    build_thermal_image_status,
    thermal_image_store,
)

router = APIRouter(prefix="/thermal-image", tags=["thermal-image"])


@router.get("/status", response_model=ThermalImageStatusResponse)
def thermal_image_status() -> ThermalImageStatusResponse:
    return build_thermal_image_status()


@router.get("/latest", response_class=Response)
def latest_thermal_image() -> Response:
    frame = thermal_image_store.get()
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No thermal image has been received",
        )

    return Response(
        content=frame.data,
        media_type=frame.media_type,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "ETag": f'"{frame.revision}"',
            "X-Thermal-Image-Received-At": frame.received_at.isoformat(),
        },
    )
