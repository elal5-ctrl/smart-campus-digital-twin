# Team A / Team B Data Contracts

This document describes the MQTT and REST contracts used by the Smart Campus
demo. Team A publishes aggregate model state to Team B and receives anonymous
people-count measurements from Team B.

## MQTT Broker

- Host: configured by `MQTT_HOST`
- Port: configured by `MQTT_PORT`, default `1883`
- Topic prefix: configured by `MQTT_TOPIC_PREFIX`, default `team-b/model`

## Team B to Team A

Topic: `team-b/thermal/people_count`

```json
{
  "version": 1,
  "action": "measurement_update",
  "source": "team-b",
  "timestamp": 1782205200,
  "sensor": {
    "id": "k2-area-01",
    "type": "area",
    "zone_id": "k2",
    "floor_level": 1
  },
  "measurement": {
    "people_count": 16,
    "count_type": "snapshot",
    "interval_seconds": null
  }
}
```

Supported sensor types are `light_barrier` and `area`. Team A stores the raw
payload and exposes the latest values through `/api/v1/measurements/latest` and
`/api/v1/measurements/history`.

Team A treats a sensor value as live for 15 minutes after receipt by default.
Older measurements remain in history but no longer override the current
synthetic location estimate.

### Thermal Image

Topic: `team-b/thermal/image/web`

The MQTT payload is one complete raw JPEG or PNG image. It has no JSON envelope
and no source timestamp. Team A detects the media type from the JPEG or PNG file
signature, records its own receipt timestamp, and keeps only the latest valid
frame in memory.

The default maximum payload size is 5 MiB and the default live freshness window
is 15 seconds. Invalid, empty, unsupported, and oversized payloads are ignored.

Team A exposes:

- `/api/v1/thermal-image/status` for availability, freshness, receipt time,
  media type, size, revision, and topic
- `/api/v1/thermal-image/latest` for the raw latest frame

No image history is stored in PostgreSQL. The current frame is discarded when
the backend restarts.

## Team A to Team B

### People Display

Topic: `team-b/model/people-display`

```json
{
  "action": "update_people_display",
  "payload": {
    "time": "18:00",
    "current_count": 194,
    "forecast_1h": 164,
    "confidence": null
  },
  "timestamp": 1782205200
}
```

### Weather

Topic: `team-b/model/weather`

```json
{
  "action": "update_weather",
  "payload": {
    "condition": "cloudy",
    "current_temp": 22.5,
    "temp_high": 25.0,
    "temp_low": 18.0,
    "rain_chance_pct": 30
  },
  "timestamp": 1782205200
}
```

### All Locations

Topic: `team-b/model/locations`

```json
{
  "action": "update_model_state",
  "type": "locations",
  "source": "simulated",
  "timestamp": 1782205200,
  "payload": [
    {
      "id": "library-b-entrance",
      "name": "Library Building B first floor entrance",
      "current_count": 16,
      "forecast_count": 14,
      "source": "simulated",
      "status": "simulated",
      "latitude": 34.81008,
      "longitude": 135.561957,
      "timestamp": 1782205200
    }
  ]
}
```

`source` is `real`, `mixed`, or `simulated` at the message level. Per-location
`source` is `live` when a Team B measurement anchors that location, otherwise
`simulated`.

Current location values follow actual Japanese time (`Asia/Tokyo`).
`forecast_count` represents the prediction closest to one hour after the
current Japanese time.

### Node State

Topic: `team-b/model/nodes`

```json
{
  "action": "update_model_state",
  "type": "nodes",
  "source": "mixed",
  "timestamp": 1782205200,
  "payload": [
    {
      "id": "k1",
      "type": "light_barrier",
      "status": "waiting",
      "value": 0,
      "unit": "people",
      "source": "waiting",
      "updated_at": null
    },
    {
      "id": "k3",
      "type": "people_display",
      "status": "active",
      "value": 194,
      "unit": "people",
      "source": "simulated",
      "updated_at": "2026-06-23T18:00:00"
    }
  ]
}
```

## Status and Verification

Team A exposes `/api/v1/model/status` for demo checks. It reports:

- MQTT configuration summary
- latest Team B measurement received
- thermal-image subscription topic and enabled state
- latest publish attempts for people display, weather, locations, and nodes
- last publish error, if any
- current data mode: `real`, `mixed`, or `simulated`

Successful MQTT publish means Team A reached the broker. It does not prove that
Team B displayed the payload unless Team B adds an acknowledgment topic.
