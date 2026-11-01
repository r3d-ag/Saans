"""Data quality checks for air quality readings.

Each check returns a QC flag string or None if the check passes.
Checks are run in order: unit, range, stuck, spike, freshness.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from core.aqi.breakpoints import STANDARD_UNITS


@dataclass(frozen=True, slots=True)
class Reading:
    """A single sensor reading."""

    station_id: str
    pollutant: str
    ts_utc: datetime
    value: float
    unit: str


@dataclass(frozen=True, slots=True)
class QCResult:
    """Result of quality-checking a reading."""

    reading: Reading
    value_std: float  # Value in standard units
    flag: Optional[str]  # None = passed, else the failing check name
    imputed: bool = False


# --- Unit conversion ---

# Conversion factors TO standard units
_UNIT_CONVERSIONS: dict[tuple[str, str], float] = {
    # (from_unit, pollutant) -> multiplier
    # CO: ppm -> mg/m³ at STP (approx 1.145)
    ("ppm", "CO"): 1.145,
    ("ppb", "CO"): 0.001145,
    # NO2: ppb -> µg/m³ at STP (approx 1.88)
    ("ppb", "NO2"): 1.88,
    ("ppm", "NO2"): 1880.0,
    # SO2: ppb -> µg/m³ at STP (approx 2.62)
    ("ppb", "SO2"): 2.62,
    ("ppm", "SO2"): 2620.0,
    # O3: ppb -> µg/m³ at STP (approx 1.96)
    ("ppb", "O3"): 1.96,
    ("ppm", "O3"): 1960.0,
    # NH3: ppb -> µg/m³ at STP (approx 0.696)
    ("ppb", "NH3"): 0.696,
    ("ppm", "NH3"): 696.0,
}


def convert_units(value: float, from_unit: str, pollutant: str) -> Optional[float]:
    """Convert a reading to the CPCB standard unit.

    Returns None if the unit is unrecognised.
    """
    std_unit = STANDARD_UNITS.get(pollutant)
    if std_unit is None:
        return None

    # Already in standard units
    normalised = from_unit.strip().lower()
    if normalised in ("µg/m³", "ug/m3", "µg/m3", "ug/m³") and std_unit == "µg/m³":
        return value
    if normalised in ("mg/m³", "mg/m3") and std_unit == "mg/m³":
        return value

    key = (normalised, pollutant)
    factor = _UNIT_CONVERSIONS.get(key)
    if factor is not None:
        return value * factor

    return None  # Unknown unit


# --- Range checks ---

# Reasonable upper bounds (well above any real reading)
_MAX_VALUES: dict[str, float] = {
    "PM2.5": 1500.0,
    "PM10": 2000.0,
    "NO2": 1000.0,
    "SO2": 3000.0,
    "CO": 100.0,
    "O3": 1200.0,
    "NH3": 5000.0,
    "Pb": 10.0,
}


def check_range(value: float, pollutant: str) -> Optional[str]:
    """Return a flag if the value is out of a plausible range."""
    if not math.isfinite(value):
        return "invalid_number"
    if value < 0:
        return "negative"
    max_val = _MAX_VALUES.get(pollutant)
    if max_val and value > max_val:
        return "extreme_high"
    return None


def check_stuck(
    values: Sequence[float],
    min_consecutive: int = 6,
) -> bool:
    """Return True if the sensor appears stuck (identical values for
    min_consecutive hours)."""
    if len(values) < min_consecutive:
        return False
    count = 1
    for i in range(1, len(values)):
        if values[i] == values[i - 1]:
            count += 1
            if count >= min_consecutive:
                return True
        else:
            count = 1
    return False


def check_spike(
    current: float,
    recent_median: float,
    threshold_factor: float = 5.0,
) -> bool:
    """Return True if current is a spike relative to the recent median.

    A reading is considered a spike if it exceeds threshold_factor
    times the recent 24-hour median. Real episodes (Diwali, stubble)
    should be confirmed by checking neighbouring stations.
    """
    if recent_median <= 0:
        return current > 0
    return current > recent_median * threshold_factor


def check_freshness(
    reading_time: datetime,
    now: Optional[datetime] = None,
    stale_hours: float = 3.0,
) -> bool:
    """Return True if the reading is stale (older than stale_hours)."""
    if now is None:
        now = datetime.now(timezone.utc)
    age = (now - reading_time).total_seconds() / 3600
    return age > stale_hours


def check_pm_ratio(pm25: float, pm10: float) -> Optional[str]:
    """Flag if PM2.5 exceeds PM10 beyond instrument error tolerance."""
    if pm10 <= 0:
        return None
    ratio = pm25 / pm10
    if ratio > 1.1:  # Allow 10% instrument error
        return "pm25_exceeds_pm10"
    return None
