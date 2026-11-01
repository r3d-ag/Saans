"""Geographic utilities for station distance and interpolation.

Uses the Haversine formula for distances and inverse-distance
weighting for hyperlocal AQI estimation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

EARTH_RADIUS_KM: float = 6371.0


@dataclass(frozen=True, slots=True)
class Point:
    """A geographic point."""

    lat: float
    lon: float


def haversine(a: Point, b: Point) -> float:
    """Great-circle distance between two points in kilometres."""
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def bearing(origin: Point, destination: Point) -> float:
    """Initial bearing from origin to destination, in degrees (0-360)."""
    lat1, lon1 = math.radians(origin.lat), math.radians(origin.lon)
    lat2, lon2 = math.radians(destination.lat), math.radians(destination.lon)

    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )

    bearing_rad = math.atan2(x, y)
    return (math.degrees(bearing_rad) + 360) % 360


@dataclass(frozen=True, slots=True)
class StationValue:
    """A station with its location and AQI value."""

    location: Point
    aqi: float
    station_id: str


def idw_estimate(
    target: Point,
    stations: Sequence[StationValue],
    power: float = 2.0,
    max_distance_km: float = 100.0,
) -> tuple[float | None, list[tuple[str, float]]]:
    """Inverse-distance-weighted AQI estimate for a target point.

    Args:
        target: The point to estimate AQI for.
        stations: Nearby stations with AQI values.
        power: IDW exponent (higher = more local).
        max_distance_km: Ignore stations beyond this distance.

    Returns:
        Tuple of (estimated AQI or None, list of (station_id, distance_km)).
    """
    weights: list[tuple[float, float, str, float]] = []  # (weight, aqi, id, dist)

    for s in stations:
        dist = haversine(target, s.location)
        if dist > max_distance_km:
            continue
        if dist < 0.01:  # Essentially at the station
            return s.aqi, [(s.station_id, dist)]
        w = 1.0 / dist**power
        weights.append((w, s.aqi, s.station_id, dist))

    if not weights:
        return None, []

    total_w = sum(w for w, _, _, _ in weights)
    estimate = sum(w * aqi for w, aqi, _, _ in weights) / total_w
    used = [(sid, dist) for _, _, sid, dist in weights]

    return round(estimate, 1), used
