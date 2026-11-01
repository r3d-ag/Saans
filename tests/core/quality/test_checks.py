"""Tests for quality check functions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.quality.checks import (
    check_freshness,
    check_pm_ratio,
    check_range,
    check_spike,
    check_stuck,
    convert_units,
)


class TestConvertUnits:
    def test_already_standard_pm25(self):
        assert convert_units(100.0, "µg/m³", "PM2.5") == 100.0

    def test_ug_m3_variant(self):
        assert convert_units(100.0, "ug/m3", "PM2.5") == 100.0

    def test_co_ppm_to_mgm3(self):
        result = convert_units(1.0, "ppm", "CO")
        assert result is not None
        assert result == pytest.approx(1.145, abs=0.01)

    def test_unknown_unit_returns_none(self):
        assert convert_units(100.0, "bananas", "PM2.5") is None

    def test_unknown_pollutant_returns_none(self):
        assert convert_units(100.0, "µg/m³", "FAKE") is None


class TestCheckRange:
    def test_negative_returns_flag(self):
        assert check_range(-1.0, "PM2.5") == "negative"

    def test_normal_value_passes(self):
        assert check_range(45.0, "PM2.5") is None

    def test_extreme_high_flagged(self):
        assert check_range(2000.0, "PM2.5") == "extreme_high"

    def test_zero_passes(self):
        assert check_range(0.0, "PM2.5") is None


class TestCheckStuck:
    def test_stuck_sensor(self):
        values = [42.0] * 8
        assert check_stuck(values) is True

    def test_not_stuck(self):
        values = [42.0, 43.0, 42.0, 41.0, 44.0, 42.0, 45.0, 43.0]
        assert check_stuck(values) is False

    def test_short_sequence(self):
        values = [42.0, 42.0]
        assert check_stuck(values) is False

    def test_stuck_at_end(self):
        values = [10.0, 20.0, 30.0, 42.0, 42.0, 42.0, 42.0, 42.0, 42.0]
        assert check_stuck(values) is True

    def test_exactly_threshold(self):
        values = [42.0] * 6
        assert check_stuck(values) is True

    def test_one_below_threshold(self):
        values = [42.0] * 5
        assert check_stuck(values) is False


class TestCheckSpike:
    def test_spike_detected(self):
        assert check_spike(600.0, 50.0) is True

    def test_normal_variation(self):
        assert check_spike(100.0, 80.0) is False

    def test_zero_median(self):
        assert check_spike(10.0, 0.0) is True

    def test_zero_current_zero_median(self):
        assert check_spike(0.0, 0.0) is False


class TestCheckFreshness:
    def test_fresh_reading(self):
        now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        reading = datetime(2026, 11, 1, 11, 30, tzinfo=timezone.utc)
        assert check_freshness(reading, now) is False

    def test_stale_reading(self):
        now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        reading = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)
        assert check_freshness(reading, now) is True

    def test_exactly_at_boundary(self):
        now = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)
        reading = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        assert check_freshness(reading, now) is False  # exactly 3h = not stale


class TestCheckPMRatio:
    def test_normal_ratio(self):
        assert check_pm_ratio(30.0, 50.0) is None

    def test_pm25_exceeds_pm10(self):
        assert check_pm_ratio(60.0, 50.0) == "pm25_exceeds_pm10"

    def test_zero_pm10(self):
        assert check_pm_ratio(30.0, 0.0) is None

    def test_within_tolerance(self):
        # 1.05 ratio should pass (within 10% tolerance)
        assert check_pm_ratio(52.5, 50.0) is None
