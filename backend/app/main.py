import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers.api import router as api_router
from app.routers.health import router as health_router
from app.routers.root import router as root_router
from app.services.excel_parser import parse_excel_and_save
from app.services.fixedlocations import create_fixed_locations_table
from app.services.measurement_mqtt import (
    start_measurement_subscriber,
    stop_measurement_subscriber,
)
from app.services.measurements import create_measurements_table
from app.services.model_state import publish_model_state_update
from app.services.mqtt_status import create_mqtt_publish_status_table
from app.services.people_display import publish_people_display_update
from app.services.predictions import (
    create_predictions_table,
    refresh_traffic_predictions,
)
from app.services.retention import run_retention_cleanup
from app.services.synthetic_data import create_synthetic_measurements_table
from app.services.thermal_image import thermal_image_store
from app.services.weather import create_weather_table, refresh_weather_reading

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    thermal_image_store.clear()
    create_weather_table()
    create_fixed_locations_table()
    create_measurements_table()
    create_mqtt_publish_status_table()
    create_synthetic_measurements_table()
    create_predictions_table()
    scheduler = BackgroundScheduler()
    measurement_subscriber = None
    scheduler.add_job(parse_excel_and_save, trigger="interval", minutes=30)
    if settings.weather_enabled:
        scheduler.add_job(
            refresh_weather_reading,
            trigger="interval",
            minutes=settings.weather_poll_minutes,
        )
    if settings.people_display_enabled:
        scheduler.add_job(
            publish_people_display_update,
            trigger="interval",
            minutes=settings.people_display_poll_minutes,
        )
        scheduler.add_job(
            publish_model_state_update,
            trigger="interval",
            minutes=settings.people_display_poll_minutes,
        )
    if settings.predictions_enabled:
        try:
            refresh_traffic_predictions()
        except Exception as exc:
            logger.warning("Initial traffic prediction refresh failed: %s", exc)
        scheduler.add_job(
            refresh_traffic_predictions,
            trigger="interval",
            minutes=settings.predictions_poll_minutes,
        )
    try:
        run_retention_cleanup()
    except Exception as exc:
        logger.warning("Initial retention cleanup failed: %s", exc)
    scheduler.add_job(run_retention_cleanup, trigger="interval", hours=6)
    if settings.mqtt_subscribe_measurements or settings.mqtt_subscribe_thermal_image:
        try:
            measurement_subscriber = start_measurement_subscriber()
        except OSError as exc:
            logger.warning("Team B measurement MQTT subscriber did not start: %s", exc)
            measurement_subscriber = None
    scheduler.start()

    try:
        yield
    finally:
        stop_measurement_subscriber(measurement_subscriber)
        scheduler.shutdown()


app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    lifespan=lifespan,
)
if settings.backend_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(root_router)
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_prefix)
