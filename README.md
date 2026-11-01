# Saans

Saans is a deployable air-quality dashboard for Ambala, Haryana, Panchkula and Chandigarh. It recalculates station AQI using CPCB National AQI breakpoints, shows the available pollutant data and quality level, and makes the limits of source labels and forecasts visible.

## What is included

- FastAPI API and responsive, installable web app served from the same origin.
- PostgreSQL database, with automatic schema creation on first start. SQLite also works for local Python runs.
- Keyless illustrative sample data for first start. The UI marks it as sample data; it is not a measurement or validation record.
- OpenAQ latest-reading ingestion, Open-Meteo weather forecast ingestion, and NASA FIRMS VIIRS fire ingestion.
- CPCB calculation, station history, 24/48-hour persistence-baseline outlook, heuristic source evidence, CSV export, and proximity estimate.
- Optional Telegram and Web Push alert delivery with quiet hours and a six-hour duplicate guard.
- Docker Compose, Render Blueprint, hourly GitHub Actions ingestion, CI, offline shell cache, and API docs at `/docs`.

The first released forecast is the persistence baseline. It does not claim a trained model has beaten persistence. AQI is shown only when there are at least three pollutant sub-indices, including PM2.5 or PM10, with sufficient hourly data. The AQI calculation method is `cpcb-naqi-2014-v1`. Versioned breakpoints and method metadata live in `core/aqi/data/cpcb-naqi-2014-v1.json` and are returned by `/v1/method`.

## Run locally with Docker

1. Install Docker Desktop with Docker Compose v2.
2. Copy `.env.example` to `.env`. The values work for a keyless sample-data run.
3. Start Saans:

   ```powershell
   docker compose up --build
   ```

4. Open [http://localhost:8000](http://localhost:8000). API documentation is at [http://localhost:8000/docs](http://localhost:8000/docs), and health status is at `/health`.

The app creates its tables and sample stations/readings on the first run if `OPENAQ_API_KEY` is absent. PostgreSQL data persists in the `pgdata` Docker volume. Stop with `Ctrl+C`; `docker compose down` preserves the volume. To erase the local database, run `docker compose down -v`.

## Run without Docker

Requires Python 3.12 and a running PostgreSQL database, or use the default SQLite file for a quick local preview.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///./saans.db"
uvicorn apps.api.app.main:app --reload --port 8000
```

Then open `http://localhost:8000`. Do not use the SQLite file for a public deployment; Render's local filesystem is ephemeral.

## Connect live data

Add keys to the host secret store or `.env` (never commit them):

| Variable | Needed for |
| --- | --- |
| `OPENAQ_API_KEY` | Poll latest air readings for locations in the Haryana/Punjab/Chandigarh region |
| `FIRMS_MAP_KEY` | Load recent VIIRS active-fire detections |
| `DATABASE_URL` | Persistent PostgreSQL database; include the `postgresql+psycopg://` scheme |
| `INGEST_TOKEN` | Protect manual `/internal/ingest` and `/internal/alerts/run` calls |
| `TELEGRAM_BOT_TOKEN` | Send Telegram alerts after a recipient starts the bot |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Optional browser push alerts; use HTTPS in deployment |

When an OpenAQ key is set, Saans does not seed sample data. Live locations appear after ingestion; failed provider calls are reported in the ingestion result and do not turn sample data into “live” data.

Run ingestion from a workstation or scheduled runner:

```powershell
python -m ingest.run
```

The bundled GitHub Actions workflow runs at minute 17 each hour. Add repository secrets named `DATABASE_URL`, `OPENAQ_API_KEY`, and optionally `FIRMS_MAP_KEY`. The hosted API does not need to be awake for that workflow. The schedule can run late; data is keyed by source timestamps.

### OpenAQ and source attribution

OpenAQ reports its source attribution and license metadata. Check the underlying provider's terms before redistributing or selling cleaned exports. Open-Meteo data must be attributed as required by its CC BY 4.0 license; its free API is for non-commercial use. FIRMS hotspots are sparse satellite observations: missing detections do not prove that no fire occurred.

## Deploy to Render

1. Push this repository to GitHub and connect it to Render using `render.yaml`.
2. Create a persistent PostgreSQL database with a provider such as Supabase. For Render, copy the Supabase shared pooler **session mode** connection string (IPv4-compatible), add `sslmode=require`, and use the `postgresql+psycopg://...` scheme for `DATABASE_URL`. Supabase direct connections are IPv6-only unless the IPv4 add-on is enabled.
3. Add OpenAQ/FIRMS keys in the Render environment if live data is wanted. Set the same `DATABASE_URL`, OpenAQ key and FIRMS key as GitHub Actions repository secrets so the hourly worker writes to the same database.
4. After the service has deployed, open `/health`, then `/docs`. The free web service can sleep while idle; first page load may take about a minute. The separate GitHub Actions worker continues ingestion.

The Render template deliberately leaves `DATABASE_URL` and provider keys as secret prompts. Do not deploy a public instance with the example credentials in `.env.example`. A public service also needs HTTPS, a long random `INGEST_TOKEN`, and an origin allow-list set to its real URL.

## API

| Route | Purpose |
| --- | --- |
| `GET /v1/stations?lat=&lon=&radius_km=` | Nearby stations with latest AQI and trust |
| `GET /v1/stations/{id}/now` | Current AQI, sub-indices, causes and 24/48-hour forecast |
| `GET /v1/stations/{id}/history?from=&to=&step=` | Hourly or daily snapshots, max 31 days |
| `GET /v1/stations/{id}/forecast` | Persistence baseline forecast and indicative band |
| `GET /v1/estimate?lat=&lon=` | Inverse-distance estimate, separately labelled |
| `GET /v1/fires?hours=&west=&south=&east=&north=` | FIRMS detections within a bounded area |
| `GET /v1/export.csv?station=&from=&to=` | Cleaned readings, max 31 days |
| `GET /v1/method` | Method version, breakpoints, categories, data sources and disclaimer |
| `POST /v1/subscriptions` | Save a Telegram station/threshold subscription |
| `POST /v1/push-subscriptions` | Save a browser Web Push subscription |
| `POST /internal/ingest` | Run ingestion; `Authorization: Bearer $INGEST_TOKEN` |
| `POST /internal/alerts/run` | Dispatch due alerts; same bearer token |
| `GET /health` | Liveness, database, station count and mode |

All time fields are UTC ISO 8601; the interface displays local time in Asia/Kolkata. CSV exports are source data derivatives and retain source and quality columns.

## Browser notifications

Web Push requires an HTTPS origin and VAPID keypair. The browser asks for permission only after the user chooses Browser push. On iOS/iPadOS, users need a supported OS and must add the site to the Home Screen. The service worker handles offline shell caching and notification clicks. Telegram delivery sends messages only to a chat that has first started the bot.

To create VAPID keys, install the `web-push` CLI in a separate environment and run `web-push generate-vapid-keys`. Put its public/private pair in deployment secrets. Set `VAPID_SUBJECT` to a real contact URI.

## Project map

```text
apps/api/app/       FastAPI routes, database models and response services
apps/web/           Responsive dashboard, PWA manifest and service worker
core/aqi/           CPCB breakpoints and pure calculation engine
core/quality/       Units, range/spike checks and trust score
core/attribution/   Evidence-based heuristic source labels
core/geo/           Distance and inverse-distance estimate
ingest/             OpenAQ, Open-Meteo and NASA FIRMS source jobs
db/migrations/      Initial SQL reference schema
docs/               Method and deployment notes
.github/workflows/  CI and hourly ingestion jobs
```

## Limits and privacy

Forecasts use a persistence baseline until archived forecast inputs and enough station history support a leakage-safe trained model. The displayed probability-like category distribution is an indicative band derived from recent variation, not a calibrated forecast probability. Cause labels are heuristics, not source apportionment. Optical low-cost sensor correction is not implemented in this release.

The app does not ask for a health profile or save browser geolocation. Alert subscriptions store a Telegram chat ID or browser push endpoint/keys, station and threshold. Restrict database access and delete subscriptions when no longer needed. The project is educational and is not medical advice.

## License

Application code is licensed under MIT. Third-party air-quality data may have separate terms; the MIT license does not override those terms.
