"""CPCB AQI calculation engine.

Computes sub-indices for individual pollutants and an overall AQI
following India's CPCB National Air Quality Index methodology.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .breakpoints import (
    MIN_POLLUTANTS,
    POLLUTANT_BANDS,
    REQUIRED_POLLUTANTS,
    Breakpoint,
    get_category,
)


@dataclass(frozen=True, slots=True)
class SubIndexResult:
    """Result of computing a single pollutant's sub-index."""

    pollutant: str
    concentration: float
    sub_index: float
    band_lo: Breakpoint
    category: str


@dataclass(frozen=True, slots=True)
class AQIResult:
    """Result of computing the overall AQI."""

    aqi: Optional[int]
    category: Optional[str]
    dominant_pollutant: Optional[str]
    sub_indices: dict[str, SubIndexResult]
    n_pollutants: int
    valid: bool
    reason: Optional[str] = None


def compute_sub_index(pollutant: str, concentration: float) -> SubIndexResult:
    """Compute the CPCB sub-index for a pollutant at a given concentration.

    Uses the formula:
        I_p = I_lo + (C_p - BP_lo) * (I_hi - I_lo) / (BP_hi - BP_lo)

    For concentrations above the last band, the slope of the last band
    is extended, capped at 500.

    Args:
        pollutant: Pollutant name (e.g. "PM2.5", "CO").
        concentration: Averaged concentration in standard units.

    Returns:
        SubIndexResult with the computed sub-index.

    Raises:
        ValueError: If the pollutant is unknown or concentration is negative.
    """
    if not math.isfinite(concentration) or concentration < 0:
        raise ValueError(f"Negative concentration: {concentration}")

    bands = POLLUTANT_BANDS.get(pollutant)
    if bands is None:
        raise ValueError(f"Unknown pollutant: {pollutant}")

    # Find the matching band
    for band in bands:
        if concentration <= band.c_hi:
            si = band.i_lo + (concentration - band.c_lo) * (
                band.i_hi - band.i_lo
            ) / (band.c_hi - band.c_lo)
            return SubIndexResult(
                pollutant=pollutant,
                concentration=concentration,
                sub_index=round(si, 1),
                band_lo=band,
                category=get_category(si),
            )

    # Above the last band: extend the slope, cap at 500
    last = bands[-1]
    slope = (last.i_hi - last.i_lo) / (last.c_hi - last.c_lo)
    si = min(500.0, last.i_hi + (concentration - last.c_hi) * slope)
    return SubIndexResult(
        pollutant=pollutant,
        concentration=concentration,
        sub_index=round(si, 1),
        band_lo=last,
        category=get_category(si),
    )


def compute_aqi(concentrations: dict[str, float]) -> AQIResult:
    """Compute the overall CPCB AQI from pollutant concentrations.

    Rules enforced:
    - At least 3 pollutants must have valid sub-indices.
    - At least one of PM2.5 or PM10 must be present.
    - AQI is the maximum sub-index; that pollutant is the dominant.

    Args:
        concentrations: Mapping of pollutant name to averaged concentration
                       in standard units (µg/m³ for most, mg/m³ for CO).

    Returns:
        AQIResult with the overall AQI or an explanation of why it's invalid.
    """
    # Compute sub-indices for all provided pollutants
    sub_indices: dict[str, SubIndexResult] = {}
    for pollutant, conc in concentrations.items():
        if pollutant not in POLLUTANT_BANDS:
            continue
        try:
            sub_indices[pollutant] = compute_sub_index(pollutant, conc)
        except ValueError:
            continue

    n_pollutants = len(sub_indices)

    # Validity check: at least 3 pollutants
    if n_pollutants < MIN_POLLUTANTS:
        return AQIResult(
            aqi=None,
            category=None,
            dominant_pollutant=None,
            sub_indices=sub_indices,
            n_pollutants=n_pollutants,
            valid=False,
            reason=f"Insufficient pollutants: {n_pollutants} < {MIN_POLLUTANTS}",
        )

    # Validity check: at least one of PM2.5 or PM10
    if not (REQUIRED_POLLUTANTS & sub_indices.keys()):
        return AQIResult(
            aqi=None,
            category=None,
            dominant_pollutant=None,
            sub_indices=sub_indices,
            n_pollutants=n_pollutants,
            valid=False,
            reason="Neither PM2.5 nor PM10 is present",
        )

    # AQI = max sub-index
    dominant = max(sub_indices, key=lambda p: sub_indices[p].sub_index)
    aqi_value = round(sub_indices[dominant].sub_index)

    return AQIResult(
        aqi=aqi_value,
        category=get_category(aqi_value),
        dominant_pollutant=dominant,
        sub_indices=sub_indices,
        n_pollutants=n_pollutants,
        valid=True,
    )
