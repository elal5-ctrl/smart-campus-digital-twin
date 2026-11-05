# Backend

FastAPI backend for Team A's Smart Campus platform. The backend imports people-count measurements, reads and writes PostgreSQL data, exposes API responses for the dashboard, fetches weather data, and publishes selected updates to Team B's physical model via MQTT.

## Requirements

- Python 3.12 or newer
- uv
- PostgreSQL access through `DATABASE_URL`

## Configuration

Backend configuration is loaded from environment variables in `app/core/config.py`.
For local development, create a `.env` file from the example configuration:

```bash
cd backend
cp .env.example .env
```

Important configuration groups:

- `DATABASE_URL`: PostgreSQL connection URL.
- `BACKEND_CORS_ORIGINS`: frontend origins allowed to call the backend from a browser.
- `GOOGLE_SHEET_ID`, `GOOGLE_SHEET_GID`: Google Sheet import source.
- `WEATHER_*`: Open-Meteo weather location, timezone, and refresh interval.
- `SYNTHETIC_*`, `PREDICTIONS_*`: quarter-hour synthetic generation and Fourier
  forecasting settings.
- `MQTT_*`: MQTT broker, people-count, and thermal-image settings for Team B integration.
- `THERMAL_IMAGE_*`: maximum accepted frame size and live-frame freshness.
- `PEOPLE_DISPLAY_*`: K3 people-display publishing settings.

Do not commit the real `.env` file. Use `.env.example` for safe defaults and documentation.

## Run Locally

```bash
cd backend
uv sync
uv run fastapi dev app/main.py
```

The backend is available at:

```text
http://127.0.0.1:8000
```

OpenAPI documentation is available locally at:

```text
http://127.0.0.1:8000/docs
```

## Project Structure

```text
backend/
├── app/
│   ├── core/
│   │   └── config.py          # settings loaded from .env
│   ├── db/
│   │   └── session.py         # SQLModel engine and session dependency
│   ├── routers/               # FastAPI route modules
│   │   ├── api.py             # versioned API router composition
│   │   ├── dashboard.py       # dashboard API routes
│   │   ├── environment.py     # weather/environment routes
│   │   ├── health.py          # health checks
│   │   ├── model.py           # model/MQTT test routes
│   │   └── routerimport.py    # manual import route
│   ├── schemas/               # Pydantic response and message contracts
│   ├── services/              # business logic and integrations
│   │   ├── dashboard.py       # dashboard data assembly
│   │   ├── excel_parser.py    # Google Sheet import
│   │   ├── mqtt.py            # shared MQTT publishing helpers
│   │   ├── people_display.py  # K3 people-display payloads
│   │   └── weather.py         # weather fetch/store/publish flow
│   ├── main.py                # FastAPI app setup and scheduled jobs
│   └── models.py              # SQLModel database tables
├── .env.example               # safe example configuration
├── pyproject.toml             # dependencies and Ruff config
└── uv.lock                    # locked Python dependencies
```

## Runtime Jobs

The backend starts scheduled jobs from `app/main.py`:

- Google Sheet people-count import every 30 minutes.
- Weather refresh and MQTT publish when `WEATHER_ENABLED=true`.
- K3 people-display MQTT publish when `PEOPLE_DISPLAY_ENABLED=true`.
- Team B people-count and latest thermal-image subscriptions when enabled.

The thermal-image integration keeps only the newest valid JPEG or PNG frame in
backend memory. It exposes metadata at `/api/v1/thermal-image/status` and the
raw frame at `/api/v1/thermal-image/latest`. Frames are not written to
PostgreSQL and disappear when the backend restarts.

The scheduler runs only while the backend process is running.

## Deployment

Backend deployment on the Raspberry Pi is documented in the GitLab Wiki. The deployed backend is normally started behind Nginx on:

```text
127.0.0.1:8000
```

Nginx serves the public website and proxies backend requests to FastAPI.

## Code Quality

Ruff is used for backend linting and formatting.

Check linting:

```bash
cd backend
uv run ruff check .
```

Check formatting:

```bash
cd backend
uv run ruff format . --check
```

Compile-check imports:

```bash
cd backend
uv run python -m compileall app
```
