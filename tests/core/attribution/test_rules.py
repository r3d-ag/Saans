"""Tests for source attribution rules."""

from __future__ import annotations

from core.attribution.rules import (
    PollutionContext,
    attribute_causes,
)


class TestSmokeAttribution:
    def test_classic_stubble_smoke(self):
        """Stubble season + high PM ratio + fires + evening = smoke."""
        ctx = PollutionContext(
            pm25=250.0,
            pm10=300.0,
            hour_of_day=21,
            is_stubble_season=True,
            fire_count_24h=15,
            multi_station_rise=True,
        )
        results = attribute_causes(ctx)
        assert len(results) > 0
        assert "smoke" in results[0].label.lower()

    def test_no_smoke_without_signals(self):
        """Should not attribute smoke with low PM ratio and no fires."""
        ctx = PollutionContext(
            pm25=30.0,
            pm10=100.0,
            hour_of_day=12,
            is_stubble_season=False,
            fire_count_24h=0,
        )
        results = attribute_causes(ctx)
        labels = [r.label.lower() for r in results]
        assert not any("smoke" in label for label in labels)


class TestDustAttribution:
    def test_classic_dust(self):
        """Low PM ratio + PM10 dominant + strong wind + dry = dust."""
        ctx = PollutionContext(
            pm25=40.0,
            pm10=200.0,
            dominant_pollutant="PM10",
            hour_of_day=14,
            wind_speed_kmh=30.0,
            humidity_pct=25.0,
        )
        results = attribute_causes(ctx)
        assert len(results) > 0
        assert "dust" in results[0].label.lower()


class TestTrafficAttribution:
    def test_rush_hour_traffic(self):
        """Rush hour + elevated NO2 + CO + light wind = traffic."""
        ctx = PollutionContext(
            pm25=80.0,
            pm10=120.0,
            no2=120.0,
            co=3.5,
            hour_of_day=8,
            wind_speed_kmh=5.0,
        )
        results = attribute_causes(ctx)
        assert len(results) > 0
        assert "traffic" in results[0].label.lower()


class TestOzoneAttribution:
    def test_ozone_episode(self):
        """O3 dominant + afternoon + elevated O3 = ozone episode."""
        ctx = PollutionContext(
            pm25=30.0,
            pm10=50.0,
            o3=180.0,
            dominant_pollutant="O3",
            hour_of_day=15,
        )
        results = attribute_causes(ctx)
        assert len(results) > 0
        assert "ozone" in results[0].label.lower()


class TestStagnationAttribution:
    def test_stagnant_air(self):
        """Very light wind + night + high humidity = stagnant air."""
        ctx = PollutionContext(
            pm25=100.0,
            pm10=150.0,
            hour_of_day=3,
            wind_speed_kmh=2.0,
            humidity_pct=90.0,
        )
        results = attribute_causes(ctx)
        assert len(results) > 0
        assert "stagnant" in results[0].label.lower()


class TestTopN:
    def test_returns_at_most_top_n(self):
        """Should return at most top_n results."""
        ctx = PollutionContext(
            pm25=100.0,
            pm10=150.0,
            no2=100.0,
            co=3.0,
            hour_of_day=3,
            wind_speed_kmh=3.0,
            humidity_pct=85.0,
        )
        results = attribute_causes(ctx, top_n=1)
        assert len(results) <= 1

    def test_empty_when_no_signals(self):
        """No signals should return empty list."""
        ctx = PollutionContext(pm25=10.0, pm10=20.0)
        results = attribute_causes(ctx)
        assert len(results) == 0


class TestEvidencePresent:
    def test_all_results_have_evidence(self):
        """Every attribution must include evidence."""
        ctx = PollutionContext(
            pm25=250.0,
            pm10=300.0,
            hour_of_day=21,
            is_stubble_season=True,
            fire_count_24h=10,
        )
        results = attribute_causes(ctx)
        for r in results:
            assert len(r.evidence) > 0
            assert r.confidence > 0
            assert "likely" in r.label.lower() or "Likely" in r.label
