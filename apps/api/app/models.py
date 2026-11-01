"""Persisted product data. Timestamps are stored in UTC."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Station(Base):
    __tablename__ = "stations"
    station_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(250))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(100), default="Haryana")
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(40), default="demo")


class Reading(Base):
    __tablename__ = "clean_readings"
    __table_args__ = (
        UniqueConstraint("station_id", "pollutant", "ts_utc", name="uq_reading_station_pollutant_ts"),
        Index("ix_reading_station_time", "station_id", "ts_utc"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.station_id", ondelete="CASCADE"))
    pollutant: Mapped[str] = mapped_column(String(20))
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    value_std: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(30))
    qc_flag: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="demo")
    imputed: Mapped[bool] = mapped_column(Boolean, default=False)


class AQISnapshot(Base):
    __tablename__ = "aqi_hourly"
    __table_args__ = (UniqueConstraint("station_id", "ts_utc", name="uq_aqi_station_ts"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.station_id", ondelete="CASCADE"))
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    aqi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    dominant: Mapped[str | None] = mapped_column(String(20), nullable=True)
    subindices: Mapped[str] = mapped_column(Text, default="{}")
    n_pollutants: Mapped[int] = mapped_column(Integer, default=0)
    trust: Mapped[float] = mapped_column(Float, default=0.0)
    trust_level: Mapped[str] = mapped_column(String(20), default="Low")
    source: Mapped[str] = mapped_column(String(40), default="demo")
    aqi_method_version: Mapped[str] = mapped_column(String(40), default="cpcb-naqi-2014-v1")


class Weather(Base):
    __tablename__ = "weather_hourly"
    __table_args__ = (UniqueConstraint("station_id", "ts_utc", name="uq_weather_station_ts"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.station_id", ondelete="CASCADE"))
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_dir: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    rain: Mapped[float | None] = mapped_column(Float, nullable=True)


class FireEvent(Base):
    __tablename__ = "fire_events"
    __table_args__ = (UniqueConstraint("lat", "lon", "acq_ts_utc", "satellite", name="uq_fire_event"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    acq_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    frp: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    satellite: Mapped[str] = mapped_column(String(40), default="unknown")


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (UniqueConstraint("station_id", "issued_at", "horizon_h", name="uq_forecast_run"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.station_id", ondelete="CASCADE"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon_h: Mapped[int] = mapped_column(Integer)
    aqi_p10: Mapped[float] = mapped_column(Float)
    aqi_p50: Mapped[float] = mapped_column(Float)
    aqi_p90: Mapped[float] = mapped_column(Float)
    category_probs: Mapped[str] = mapped_column(Text, default="{}")
    model_version: Mapped[str] = mapped_column(String(80), default="baseline-persistence-v1")


class AlertSubscription(Base):
    __tablename__ = "alert_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(20))
    destination: Mapped[str] = mapped_column(Text)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.station_id", ondelete="CASCADE"))
    threshold: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AlertLog(Base):
    __tablename__ = "alert_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("alert_subscriptions.id", ondelete="CASCADE"))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)


class AttributionRow(Base):
    __tablename__ = "attributions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.station_id", ondelete="CASCADE"))
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    label: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(Text, default="[]")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.station_id", ondelete="CASCADE"))
    threshold: Mapped[int] = mapped_column(Integer, default=201)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(80), unique=True)
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    evaluation: Mapped[str] = mapped_column(Text, default="{}")
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
