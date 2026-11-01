"""Versioned CPCB National AQI method data and accessors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final


@dataclass(frozen=True, slots=True)
class Breakpoint:
    """One concentration/AQI interpolation band."""

    c_lo: float
    c_hi: float
    i_lo: float
    i_hi: float


_DATA_PATH = Path(__file__).with_name("data") / "cpcb-naqi-2014-v1.json"
with _DATA_PATH.open(encoding="utf-8") as _handle:
    METHOD_DATA: Final[dict] = json.load(_handle)

METHOD_VERSION: Final[str] = METHOD_DATA["method_version"]
CATEGORIES: Final[list[tuple[int, int, str]]] = [
    (int(item["min"]), int(item["max"]), str(item["name"])) for item in METHOD_DATA["categories"]
]
CATEGORY_COLOURS: Final[dict[str, str]] = {
    str(item["name"]): str(item["colour"]) for item in METHOD_DATA["categories"]
}
POLLUTANT_BANDS: Final[dict[str, tuple[Breakpoint, ...]]] = {
    pollutant: tuple(Breakpoint(*map(float, band)) for band in details["bands"])
    for pollutant, details in METHOD_DATA["pollutants"].items()
}
AVERAGING_HOURS: Final[dict[str, int]] = {
    pollutant: int(details["averaging_hours"]) for pollutant, details in METHOD_DATA["pollutants"].items()
}
STANDARD_UNITS: Final[dict[str, str]] = {
    pollutant: str(details["unit"]) for pollutant, details in METHOD_DATA["pollutants"].items()
}
MIN_POLLUTANTS: Final[int] = int(METHOD_DATA["validity"]["minimum_pollutants"])
REQUIRED_POLLUTANTS: Final[frozenset[str]] = frozenset(METHOD_DATA["validity"]["requires_one_of"])
MIN_HOURS_24H: Final[int] = int(METHOD_DATA["validity"]["minimum_hours_24h"])
MIN_HOURS_8H: Final[int] = int(METHOD_DATA["validity"]["project_minimum_hours_8h"])


def get_category(aqi: float) -> str:
    """Return the CPCB category name for an AQI value."""
    for low, high, name in CATEGORIES:
        if low <= aqi <= high:
            return name
    return "Severe" if aqi > 500 else "Unknown"
