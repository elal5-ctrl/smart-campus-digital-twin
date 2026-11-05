from datetime import UTC, datetime

from sqlmodel import Session, select

from app.db.session import engine
from app.models import MqttPublishStatus


def create_mqtt_publish_status_table() -> None:
    MqttPublishStatus.__table__.create(engine, checkfirst=True)


def record_publish_attempt(
    *,
    channel: str,
    topic: str,
    success: bool,
    payload_source: str,
    error: str | None = None,
) -> MqttPublishStatus:
    with Session(engine) as session:
        status = session.get(MqttPublishStatus, channel)
        attempted_at = datetime.now(UTC).replace(tzinfo=None)
        if status is None:
            status = MqttPublishStatus(
                channel=channel,
                topic=topic,
                attempted_at=attempted_at,
                success=success,
                error=error,
                payload_source=payload_source,
            )
        else:
            status.topic = topic
            status.attempted_at = attempted_at
            status.success = success
            status.error = error
            status.payload_source = payload_source
        session.add(status)
        session.commit()
        session.refresh(status)
        return status


def get_publish_statuses(session: Session) -> dict[str, MqttPublishStatus]:
    statement = select(MqttPublishStatus).order_by(MqttPublishStatus.channel)
    return {status.channel: status for status in session.exec(statement)}
