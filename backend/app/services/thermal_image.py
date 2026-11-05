from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from threading import Lock

from app.core.config import get_settings
from app.schemas.thermal_image import ThermalImageStatusResponse
from app.services.campus_time import utc_now_naive

JPEG_SIGNATURE = b"\xff\xd8\xff"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class ThermalImageFrame:
    data: bytes
    media_type: str
    received_at: datetime
    revision: str

    @property
    def size_bytes(self) -> int:
        return len(self.data)


class ThermalImageStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._frame: ThermalImageFrame | None = None

    def replace(
        self,
        payload: bytes,
        *,
        max_bytes: int,
        received_at: datetime | None = None,
    ) -> ThermalImageFrame:
        if not payload:
            raise ValueError("Thermal image payload is empty")
        if len(payload) > max(1, max_bytes):
            raise ValueError("Thermal image payload exceeds configured size limit")

        media_type = detect_image_media_type(payload)
        if media_type is None:
            raise ValueError("Thermal image payload is not a supported JPEG or PNG")

        timestamp = received_at or utc_now_naive()
        revision = sha256(payload + timestamp.isoformat().encode("ascii")).hexdigest()[
            :20
        ]
        frame = ThermalImageFrame(
            data=bytes(payload),
            media_type=media_type,
            received_at=timestamp,
            revision=revision,
        )
        with self._lock:
            self._frame = frame
        return frame

    def get(self) -> ThermalImageFrame | None:
        with self._lock:
            return self._frame

    def clear(self) -> None:
        with self._lock:
            self._frame = None


def detect_image_media_type(payload: bytes) -> str | None:
    if payload.startswith(JPEG_SIGNATURE):
        return "image/jpeg"
    if payload.startswith(PNG_SIGNATURE):
        return "image/png"
    return None


def build_thermal_image_status(
    *,
    now: datetime | None = None,
) -> ThermalImageStatusResponse:
    settings = get_settings()
    frame = thermal_image_store.get()
    if frame is None:
        return ThermalImageStatusResponse(
            available=False,
            state="waiting",
            received_at=None,
            media_type=None,
            size_bytes=None,
            revision=None,
            topic=settings.mqtt_thermal_image_topic,
        )

    freshness_seconds = max(1, settings.thermal_image_freshness_seconds)
    cutoff = (now or utc_now_naive()) - timedelta(seconds=freshness_seconds)
    return ThermalImageStatusResponse(
        available=True,
        state="live" if frame.received_at >= cutoff else "stale",
        received_at=frame.received_at,
        media_type=frame.media_type,
        size_bytes=frame.size_bytes,
        revision=frame.revision,
        topic=settings.mqtt_thermal_image_topic,
    )


thermal_image_store = ThermalImageStore()
