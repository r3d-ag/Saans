"""Rule-based source attribution for air pollution.

Labels the likely cause of poor air quality (smoke, dust, traffic,
ozone episode, or stagnant air) based on observable signals.
All attributions are prefixed with "likely" and include the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class Attribution:
    """A likely cause of pollution with evidence."""

    label: str
    confidence: float  # 0.0 to 1.0
    evidence: list[str]  # Human-readable list of signals


@dataclass(frozen=True, slots=True)
class PollutionContext:
    """Observed signals for attribution."""

    pm25: float  # µg/m³
    pm10: float  # µg/m³
    no2: Optional[float] = None  # µg/m³
    co: Optional[float] = None  # mg/m³
    o3: Optional[float] = None  # µg/m³
    dominant_pollutant: Optional[str] = None
    hour_of_day: Optional[int] = None  # 0-23 IST
    wind_speed_kmh: Optional[float] = None
    humidity_pct: Optional[float] = None
    is_stubble_season: bool = False  # Sep 15 – Nov 30
    fire_count_24h: int = 0  # FIRMS detections upwind
    fire_count_72h: int = 0
    multi_station_rise: bool = False  # Rise seen across stations


def _pm_ratio(pm25: float, pm10: float) -> Optional[float]:
    """PM2.5 / PM10 ratio, or None if PM10 is zero."""
    return pm25 / pm10 if pm10 > 0 else None


def _check_smoke(ctx: PollutionContext) -> Optional[Attribution]:
    """Check for crop-residue smoke signature."""
    ratio = _pm_ratio(ctx.pm25, ctx.pm10)
    if ratio is None:
        return None

    signals: list[str] = []
    score = 0.0

    if ratio >= 0.6:
        signals.append(f"PM2.5/PM10 ratio is high ({ratio:.2f})")
        score += 0.25

    if ctx.is_stubble_season:
        signals.append("Within stubble-burning season (Sep 15 – Nov 30)")
        score += 0.2

    if ctx.hour_of_day is not None and (ctx.hour_of_day >= 18 or ctx.hour_of_day <= 6):
        signals.append(f"Evening/night reading (hour {ctx.hour_of_day})")
        score += 0.15

    if ctx.fire_count_24h > 0:
        signals.append(f"{ctx.fire_count_24h} fire detections upwind in last 24h")
        score += 0.2
    elif ctx.fire_count_72h > 0:
        signals.append(f"{ctx.fire_count_72h} fire detections upwind in last 72h")
        score += 0.1

    if ctx.multi_station_rise:
        signals.append("Rise observed across multiple nearby stations")
        score += 0.1

    if score >= 0.4 and signals:
        return Attribution(
            label="Likely crop-residue smoke",
            confidence=min(1.0, score),
            evidence=signals,
        )
    return None


def _check_dust(ctx: PollutionContext) -> Optional[Attribution]:
    """Check for dust signature."""
    ratio = _pm_ratio(ctx.pm25, ctx.pm10)
    if ratio is None:
        return None

    signals: list[str] = []
    score = 0.0

    if ratio <= 0.4:
        signals.append(
            f"PM2.5/PM10 ratio is low ({ratio:.2f}), indicating coarse particles"
        )
        score += 0.3

    if ctx.dominant_pollutant == "PM10":
        signals.append("PM10 is the dominant pollutant")
        score += 0.2

    if ctx.hour_of_day is not None and 8 <= ctx.hour_of_day <= 18:
        signals.append(f"Daytime reading (hour {ctx.hour_of_day})")
        score += 0.1

    if ctx.wind_speed_kmh is not None and ctx.wind_speed_kmh > 20:
        signals.append(f"Moderate to strong wind ({ctx.wind_speed_kmh:.0f} km/h)")
        score += 0.2

    if ctx.humidity_pct is not None and ctx.humidity_pct < 40:
        signals.append(f"Low humidity ({ctx.humidity_pct:.0f}%)")
        score += 0.1

    if score >= 0.4 and signals:
        return Attribution(
            label="Likely dust",
            confidence=min(1.0, score),
            evidence=signals,
        )
    return None


def _check_traffic(ctx: PollutionContext) -> Optional[Attribution]:
    """Check for traffic/combustion signature."""
    signals: list[str] = []
    score = 0.0

    if ctx.hour_of_day is not None and ctx.hour_of_day in (7, 8, 9, 17, 18, 19, 20):
        signals.append(f"Rush hour (hour {ctx.hour_of_day})")
        score += 0.25

    if ctx.no2 is not None and ctx.no2 > 80:
        signals.append(f"Elevated NO\u2082 ({ctx.no2:.0f} \u00b5g/m\u00b3)")
        score += 0.2
    if ctx.co is not None and ctx.co > 2.0:
        signals.append(f"Elevated CO ({ctx.co:.1f} mg/m\u00b3)")
        score += 0.15

    if ctx.wind_speed_kmh is not None and ctx.wind_speed_kmh < 10:
        signals.append(f"Light wind ({ctx.wind_speed_kmh:.0f} km/h)")
        score += 0.15

    if score >= 0.4 and signals:
        return Attribution(
            label="Likely traffic and combustion",
            confidence=min(1.0, score),
            evidence=signals,
        )
    return None


def _check_ozone(ctx: PollutionContext) -> Optional[Attribution]:
    """Check for ozone episode."""
    signals: list[str] = []
    score = 0.0

    if ctx.dominant_pollutant == "O3":
        signals.append("O\u2083 is the dominant pollutant")
        score += 0.35

    if ctx.o3 is not None and ctx.o3 > 100:
        signals.append(f"Elevated O\u2083 ({ctx.o3:.0f} \u00b5g/m\u00b3)")
        score += 0.25

    if ctx.hour_of_day is not None and 12 <= ctx.hour_of_day <= 17:
        signals.append(f"Afternoon peak (hour {ctx.hour_of_day})")
        score += 0.2

    if score >= 0.4 and signals:
        return Attribution(
            label="Likely ozone episode",
            confidence=min(1.0, score),
            evidence=signals,
        )
    return None


def _check_stagnation(ctx: PollutionContext) -> Optional[Attribution]:
    """Check for stagnant air conditions."""
    signals: list[str] = []
    score = 0.0

    if ctx.wind_speed_kmh is not None and ctx.wind_speed_kmh < 5:
        signals.append(f"Very light wind ({ctx.wind_speed_kmh:.0f} km/h)")
        score += 0.3

    if ctx.hour_of_day is not None and (ctx.hour_of_day >= 21 or ctx.hour_of_day <= 6):
        signals.append(f"Night/early morning (hour {ctx.hour_of_day})")
        score += 0.2

    if ctx.humidity_pct is not None and ctx.humidity_pct > 80:
        signals.append(f"High humidity ({ctx.humidity_pct:.0f}%)")
        score += 0.15

    if score >= 0.4 and signals:
        return Attribution(
            label="Likely stagnant air",
            confidence=min(1.0, score),
            evidence=signals,
        )
    return None


def attribute_causes(ctx: PollutionContext, top_n: int = 2) -> list[Attribution]:
    """Run all attribution rules and return the top N likely causes.

    Args:
        ctx: Observed signals for a station at a point in time.
        top_n: Maximum number of attributions to return.

    Returns:
        List of up to top_n Attribution results, sorted by confidence.
        Empty if no rule triggered.
    """
    checkers = [
        _check_smoke,
        _check_dust,
        _check_traffic,
        _check_ozone,
        _check_stagnation,
    ]

    results: list[Attribution] = []
    for checker in checkers:
        result = checker(ctx)
        if result is not None:
            results.append(result)

    results.sort(key=lambda a: a.confidence, reverse=True)
    return results[:top_n]
