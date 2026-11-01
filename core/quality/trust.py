"""Trust score for AQI readings.

Combines freshness, completeness, quality flags, and agreement with
neighbours into a single score: High (>=0.8), Medium (0.5-0.8), Low (<0.5).

Formula:
    trust = 0.35*F + 0.35*K + 0.15*Q + 0.15*A

Where:
    F = freshness (1 for <1h old, linearly falling to 0 at 6h)
    K = completeness (hours present in last 24, divided by 24)
    Q = 1 minus a penalty for QC flags
    A = agreement with neighbour stations
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

TRUST_HIGH: float = 0.8
TRUST_MEDIUM: float = 0.5

WEIGHT_FRESHNESS: float = 0.35
WEIGHT_COMPLETENESS: float = 0.35
WEIGHT_QUALITY: float = 0.15
WEIGHT_AGREEMENT: float = 0.15


@dataclass(frozen=True, slots=True)
class TrustScore:
    """Trust assessment for an AQI reading."""

    score: float
    level: str  # "High", "Medium", or "Low"
    freshness: float
    completeness: float
    quality: float
    agreement: float


def freshness_score(
    reading_time: datetime,
    now: Optional[datetime] = None,
) -> float:
    """Score from 1.0 (fresh) to 0.0 (stale).

    1.0 for readings under 1 hour old, linearly falling to 0.0 at 6 hours.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    age_hours = (now - reading_time).total_seconds() / 3600
    if age_hours <= 1.0:
        return 1.0
    if age_hours >= 6.0:
        return 0.0
    return 1.0 - (age_hours - 1.0) / 5.0


def completeness_score(hours_present: int, window: int = 24) -> float:
    """Fraction of hours with data in the averaging window."""
    if window <= 0:
        return 0.0
    return min(1.0, max(0.0, hours_present / window))


def quality_score(n_flags: int, n_readings: int) -> float:
    """1 minus the fraction of flagged readings."""
    if n_readings <= 0:
        return 0.0
    return max(0.0, 1.0 - n_flags / n_readings)


def agreement_score(
    station_aqi: float,
    neighbour_aqis: list[float],
    tolerance: float = 50.0,
) -> float:
    """Score based on how close this station is to its neighbours.

    Uses the distance-weighted median approach. Returns 1.0 if the
    reading is within tolerance of the median, falling linearly to
    0.0 at 3x tolerance.
    """
    if not neighbour_aqis:
        return 0.5  # No neighbours -> neutral

    median = sorted(neighbour_aqis)[len(neighbour_aqis) // 2]
    diff = abs(station_aqi - median)

    if diff <= tolerance:
        return 1.0
    if diff >= tolerance * 3:
        return 0.0
    return 1.0 - (diff - tolerance) / (tolerance * 2)


def compute_trust(
    freshness: float,
    completeness: float,
    quality: float,
    agreement: float,
) -> TrustScore:
    """Compute the overall trust score."""
    score = (
        WEIGHT_FRESHNESS * freshness
        + WEIGHT_COMPLETENESS * completeness
        + WEIGHT_QUALITY * quality
        + WEIGHT_AGREEMENT * agreement
    )
    score = max(0.0, min(1.0, score))

    if score >= TRUST_HIGH:
        level = "High"
    elif score >= TRUST_MEDIUM:
        level = "Medium"
    else:
        level = "Low"

    return TrustScore(
        score=round(score, 3),
        level=level,
        freshness=round(freshness, 3),
        completeness=round(completeness, 3),
        quality=round(quality, 3),
        agreement=round(agreement, 3),
    )
