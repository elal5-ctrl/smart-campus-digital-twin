from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import func
from sqlmodel import Session, select

from app.db.session import engine
from app.models import Entry, Locations

LOCATION_RADIUS_METERS = 60


@dataclass(frozen=True)
class FixedLocationDefinition:
    id: str
    name: str
    latitude: float
    longitude: float


FIXED_LOCATIONS: tuple[FixedLocationDefinition, ...] = (
    FixedLocationDefinition(
        "building-a-north-gate", "North Gate of Building A", 34.811658, 135.561230
    ),
    FixedLocationDefinition(
        "building-g-entrance", "Building G 1st floor entrance", 34.809713, 135.560992
    ),
    FixedLocationDefinition(
        "gym-building-b-entrance",
        "Gym Building B 1st floor entrance",
        34.810186,
        135.560870,
    ),
    FixedLocationDefinition(
        "iwakura-north-entrance", "North Entrance Iwakura Gate", 34.812094, 135.561207
    ),
    FixedLocationDefinition(
        "library-b-entrance",
        "Library Building B first floor entrance",
        34.810080,
        135.561957,
    ),
    FixedLocationDefinition(
        "jr-tokaido-line-entrance", "JR Tokaido line entrance", 34.811925, 135.560730
    ),
    FixedLocationDefinition(
        "nara-south-entrance", "South Entrance Nara Gate", 34.807513, 135.561915
    ),
    FixedLocationDefinition(
        "gym-north-gate", "North Gate of the Gym", 34.810248, 135.560754
    ),
    FixedLocationDefinition(
        "building-a-east-gate", "East Gate of Building A", 34.810376, 135.561904
    ),
    FixedLocationDefinition(
        "cafeteria-south-gate", "South Gate of the Cafeteria", 34.810203, 135.561573
    ),
    FixedLocationDefinition(
        "g-building-east-gate", "East Gate of G-Building", 34.809540, 135.561048
    ),
    FixedLocationDefinition(
        "building-a-south-gate", "South Gate of Building A", 34.810388, 135.561588
    ),
    FixedLocationDefinition(
        "west-sports-field-entrance",
        "West Sports Field entrance",
        34.809750,
        135.560250,
    ),
    FixedLocationDefinition(
        "east-campus-aeon-side-entrance",
        "East Campus AEON-side entrance",
        34.810700,
        135.562650,
    ),
    FixedLocationDefinition(
        "k1-south-west-campus-entrance",
        "K1 South-West campus sensor entrance",
        34.8089451,
        135.5598084,
    ),
    FixedLocationDefinition(
        "k2-library-b-sensor-entrance",
        "K2 Library B sensor entrance",
        34.8099864,
        135.5620731,
    ),
)
FIXED_LOCATIONS_BY_ID = {location.id: location for location in FIXED_LOCATIONS}
EXTERNAL_SENSOR_LOCATION_IDS = {
    "k1-south-west-campus-entrance",
    "k2-library-b-sensor-entrance",
}
PHYSICAL_MODEL_LOCATIONS = tuple(
    location
    for location in FIXED_LOCATIONS
    if location.id not in EXTERNAL_SENSOR_LOCATION_IDS
)
SENSOR_FIXED_LOCATION_MAP: dict[str, str] = {
    "k1": "k1-south-west-campus-entrance",
    "k1-light-barrier": "k1-south-west-campus-entrance",
    "k1-light-barrier-01": "k1-south-west-campus-entrance",
    "k2": "k2-library-b-sensor-entrance",
    "k2-area": "k2-library-b-sensor-entrance",
    "k2-area-01": "k2-library-b-sensor-entrance",
}


def create_fixed_locations_table() -> None:
    Locations.__table__.create(engine, checkfirst=True)


def refresh_fixed_location_readings() -> list[Locations]:
    counts = {location.name: 0 for location in FIXED_LOCATIONS}
    with Session(engine) as session:
        entries = session.exec(
            select(
                func.ST_Y(Entry.coordinates).label("latitude"),
                func.ST_X(Entry.coordinates).label("longitude"),
            )
        )
        for latitude, longitude in entries:
            location = _nearest_fixed_location(latitude, longitude)
            if location is not None:
                counts[location.name] += 1
        fixed_locations: list[Locations] = []
        for location in FIXED_LOCATIONS:
            fixed_location = session.exec(
                select(Locations).where(Locations.tracking_spots == location.name)
            ).first()
            if fixed_location is None:
                fixed_location = Locations(
                    tracking_spots=location.name,
                    readings=counts[location.name],
                )
            else:
                fixed_location.readings = counts[location.name]
            session.add(fixed_location)
            fixed_locations.append(fixed_location)
        session.commit()
        for fixed_location in fixed_locations:
            session.refresh(fixed_location)
        return fixed_locations


def _nearest_fixed_location(
    latitude: float,
    longitude: float,
) -> FixedLocationDefinition | None:
    return nearest_fixed_location(latitude, longitude)


def nearest_fixed_location(
    latitude: float,
    longitude: float,
    radius_meters: float = LOCATION_RADIUS_METERS,
) -> FixedLocationDefinition | None:
    nearest_location: FixedLocationDefinition | None = None
    nearest_distance = radius_meters
    for location in FIXED_LOCATIONS:
        distance = _distance_meters(
            latitude,
            longitude,
            location.latitude,
            location.longitude,
        )
        if distance <= nearest_distance:
            nearest_location = location
            nearest_distance = distance
    return nearest_location


def _distance_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    earth_radius_meters = 6_371_000
    lat_a = radians(latitude_a)
    lat_b = radians(latitude_b)
    delta_lat = radians(latitude_b - latitude_a)
    delta_lon = radians(longitude_b - longitude_a)
    haversine = (
        sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    )
    return 2 * earth_radius_meters * asin(sqrt(haversine))
