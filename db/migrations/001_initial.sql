-- Initial PostgreSQL schema. The application creates this schema with
-- SQLAlchemy Base.metadata.create_all() at startup for a fresh deployment.
CREATE TABLE stations (
  station_id VARCHAR(100) PRIMARY KEY, name VARCHAR(250) NOT NULL,
  city VARCHAR(100) NOT NULL, state VARCHAR(100) NOT NULL,
  lat DOUBLE PRECISION NOT NULL, lon DOUBLE PRECISION NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE, source VARCHAR(40) NOT NULL DEFAULT 'demo'
);
CREATE TABLE clean_readings (
  id SERIAL PRIMARY KEY, station_id VARCHAR(100) NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
  pollutant VARCHAR(20) NOT NULL, ts_utc TIMESTAMPTZ NOT NULL,
  value_std DOUBLE PRECISION NOT NULL, unit VARCHAR(30) NOT NULL,
  qc_flag VARCHAR(40), source VARCHAR(40) NOT NULL DEFAULT 'demo', imputed BOOLEAN NOT NULL DEFAULT FALSE,
  CONSTRAINT uq_reading_station_pollutant_ts UNIQUE(station_id, pollutant, ts_utc)
);
CREATE INDEX ix_reading_station_time ON clean_readings(station_id, ts_utc);
CREATE TABLE aqi_hourly (
  id SERIAL PRIMARY KEY, station_id VARCHAR(100) NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
  ts_utc TIMESTAMPTZ NOT NULL, aqi INTEGER, category VARCHAR(40), dominant VARCHAR(20),
  subindices TEXT NOT NULL DEFAULT '{}', n_pollutants INTEGER NOT NULL DEFAULT 0,
  trust DOUBLE PRECISION NOT NULL DEFAULT 0, trust_level VARCHAR(20) NOT NULL DEFAULT 'Low',
  source VARCHAR(40) NOT NULL DEFAULT 'demo', aqi_method_version VARCHAR(40) NOT NULL DEFAULT 'cpcb-naqi-2014-v1',
  CONSTRAINT uq_aqi_station_ts UNIQUE(station_id, ts_utc)
);
CREATE TABLE weather_hourly (
  id SERIAL PRIMARY KEY, station_id VARCHAR(100) NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
  ts_utc TIMESTAMPTZ NOT NULL, temp DOUBLE PRECISION, humidity DOUBLE PRECISION,
  wind_speed DOUBLE PRECISION, wind_dir DOUBLE PRECISION, pressure DOUBLE PRECISION, rain DOUBLE PRECISION,
  CONSTRAINT uq_weather_station_ts UNIQUE(station_id, ts_utc)
);
CREATE TABLE fire_events (
  id SERIAL PRIMARY KEY, lat DOUBLE PRECISION NOT NULL, lon DOUBLE PRECISION NOT NULL,
  acq_ts_utc TIMESTAMPTZ NOT NULL, frp DOUBLE PRECISION, confidence VARCHAR(20), satellite VARCHAR(40) NOT NULL,
  CONSTRAINT uq_fire_event UNIQUE(lat, lon, acq_ts_utc, satellite)
);
CREATE TABLE forecasts (
  id SERIAL PRIMARY KEY, station_id VARCHAR(100) NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
  issued_at TIMESTAMPTZ NOT NULL, target_ts TIMESTAMPTZ NOT NULL, horizon_h INTEGER NOT NULL,
  aqi_p10 DOUBLE PRECISION NOT NULL, aqi_p50 DOUBLE PRECISION NOT NULL, aqi_p90 DOUBLE PRECISION NOT NULL,
  category_probs TEXT NOT NULL DEFAULT '{}', model_version VARCHAR(80) NOT NULL DEFAULT 'baseline-persistence-v1',
  CONSTRAINT uq_forecast_run UNIQUE(station_id, issued_at, horizon_h)
);
CREATE TABLE alert_subscriptions (
  id SERIAL PRIMARY KEY, channel VARCHAR(20) NOT NULL, destination TEXT NOT NULL,
  station_id VARCHAR(100) NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
  threshold INTEGER NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE alert_log (
  id SERIAL PRIMARY KEY, subscription_id INTEGER NOT NULL REFERENCES alert_subscriptions(id) ON DELETE CASCADE,
  sent_at TIMESTAMPTZ NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE attributions (
  id SERIAL PRIMARY KEY, station_id VARCHAR(100) NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
  ts_utc TIMESTAMPTZ NOT NULL, label VARCHAR(100) NOT NULL,
  confidence DOUBLE PRECISION NOT NULL, evidence TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE push_subscriptions (
  id SERIAL PRIMARY KEY, endpoint TEXT NOT NULL UNIQUE, p256dh TEXT NOT NULL, auth TEXT NOT NULL,
  station_id VARCHAR(100) NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
  threshold INTEGER NOT NULL DEFAULT 201, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE model_artifacts (
  id SERIAL PRIMARY KEY, version VARCHAR(80) NOT NULL UNIQUE,
  payload BYTEA NOT NULL, evaluation TEXT NOT NULL DEFAULT '{}', trained_at TIMESTAMPTZ NOT NULL
);
