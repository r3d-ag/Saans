"""Tests for the CPCB AQI engine.

Includes CPCB worked examples, edge cases, and property-based tests.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.aqi.engine import compute_aqi, compute_sub_index

# ===== CPCB Worked Examples =====


class TestSubIndex:
    """Test individual sub-index calculations against CPCB worked examples."""

    def test_pm25_150_gives_323(self):
        """CPCB worked example: PM2.5 = 150 µg/m³ -> 323."""
        result = compute_sub_index("PM2.5", 150.0)
        assert result.sub_index == pytest.approx(323.1, abs=1)

    def test_pm25_45_gives_75(self):
        """CPCB states PM2.5 = 45 µg/m³ -> 75."""
        result = compute_sub_index("PM2.5", 45.0)
        assert result.sub_index == pytest.approx(75.0, abs=1)

    def test_pm25_60_gives_100(self):
        """Top of Satisfactory band: PM2.5 = 60 -> 100."""
        result = compute_sub_index("PM2.5", 60.0)
        assert result.sub_index == pytest.approx(100.0, abs=1)

    def test_pm25_31_gives_about_52(self):
        """CPCB quotes ~51; allow +/-1 at boundaries."""
        result = compute_sub_index("PM2.5", 31.0)
        assert result.sub_index == pytest.approx(51.7, abs=1)

    def test_pm25_0_gives_0(self):
        """Bottom of Good band."""
        result = compute_sub_index("PM2.5", 0.0)
        assert result.sub_index == pytest.approx(0.0, abs=0.1)

    def test_pm25_30_gives_50(self):
        """Top of Good band."""
        result = compute_sub_index("PM2.5", 30.0)
        assert result.sub_index == pytest.approx(50.0, abs=0.1)

    def test_pm10_100_gives_100(self):
        """Top of Satisfactory for PM10."""
        result = compute_sub_index("PM10", 100.0)
        assert result.sub_index == pytest.approx(100.0, abs=1)

    def test_co_5_gives_137_5(self):
        """CO = 5 mg/m³ -> within Moderately Polluted."""
        result = compute_sub_index("CO", 5.0)
        expected = 100 + (5.0 - 2.0) * (200 - 100) / (10.0 - 2.0)
        assert result.sub_index == pytest.approx(expected, abs=1)

    def test_negative_concentration_raises(self):
        """Negative concentrations must raise ValueError."""
        with pytest.raises(ValueError, match="Negative"):
            compute_sub_index("PM2.5", -1.0)

    def test_unknown_pollutant_raises(self):
        """Unknown pollutant must raise ValueError."""
        with pytest.raises(ValueError, match="Unknown"):
            compute_sub_index("FAKE", 100.0)

    def test_above_last_band_capped_at_500(self):
        """Values above the last band should extrapolate but cap at 500."""
        result = compute_sub_index("PM2.5", 1000.0)
        assert result.sub_index <= 500.0

    def test_every_band_edge_pm25(self):
        """Sub-index at every PM2.5 band boundary."""
        edges = [(0, 0), (30, 50), (60, 100), (90, 200), (120, 300), (250, 400)]
        for conc, expected_aqi in edges:
            result = compute_sub_index("PM2.5", float(conc))
            assert result.sub_index == pytest.approx(expected_aqi, abs=0.1), (
                f"PM2.5={conc}: expected {expected_aqi}, got {result.sub_index}"
            )


class TestOverallAQI:
    """Test the overall AQI computation."""

    def test_cpcb_example_three_pollutants(self):
        """CPCB worked example: PM2.5=45, SO2=60, NO2=30 -> AQI 75,
        dominant PM2.5."""
        result = compute_aqi({"PM2.5": 45.0, "SO2": 60.0, "NO2": 30.0})
        assert result.valid
        assert result.aqi == 75
        assert result.dominant_pollutant == "PM2.5"

    def test_insufficient_pollutants(self):
        """AQI with only 2 pollutants should be invalid."""
        result = compute_aqi({"PM2.5": 45.0, "SO2": 60.0})
        assert not result.valid
        assert result.aqi is None
        assert "Insufficient" in (result.reason or "")

    def test_no_pm_pollutants(self):
        """AQI without PM2.5 or PM10 should be invalid."""
        result = compute_aqi({"SO2": 60.0, "NO2": 30.0, "CO": 1.0})
        assert not result.valid
        assert result.aqi is None
        assert "PM" in (result.reason or "")

    def test_dominant_is_highest(self):
        """Dominant pollutant should have the highest sub-index."""
        result = compute_aqi({"PM2.5": 200.0, "PM10": 50.0, "NO2": 30.0})
        assert result.valid
        assert result.dominant_pollutant == "PM2.5"

    def test_all_pollutants(self):
        """AQI with all 8 pollutants."""
        concentrations = {
            "PM2.5": 45.0,
            "PM10": 80.0,
            "NO2": 60.0,
            "SO2": 50.0,
            "CO": 1.5,
            "O3": 40.0,
            "NH3": 100.0,
            "Pb": 0.3,
        }
        result = compute_aqi(concentrations)
        assert result.valid
        assert result.aqi is not None
        assert result.n_pollutants == 8

    def test_empty_concentrations(self):
        """Empty input should be invalid."""
        result = compute_aqi({})
        assert not result.valid

    def test_category_assignment(self):
        """Category should match the AQI value."""
        result = compute_aqi({"PM2.5": 150.0, "PM10": 200.0, "NO2": 100.0})
        assert result.valid
        assert result.category is not None


# ===== Property-Based Tests =====


class TestProperties:
    """Property-based tests for AQI monotonicity and bounds."""

    @given(conc=st.floats(min_value=0, max_value=2000, allow_nan=False))
    def test_sub_index_non_negative(self, conc: float):
        """Sub-index should never be negative."""
        result = compute_sub_index("PM2.5", conc)
        assert result.sub_index >= 0

    @given(conc=st.floats(min_value=0, max_value=2000, allow_nan=False))
    def test_sub_index_capped_at_500(self, conc: float):
        """Sub-index should never exceed 500."""
        result = compute_sub_index("PM2.5", conc)
        assert result.sub_index <= 500.0

    @given(
        c1=st.floats(min_value=0, max_value=500, allow_nan=False),
        c2=st.floats(min_value=0, max_value=500, allow_nan=False),
    )
    def test_monotonicity(self, c1: float, c2: float):
        """AQI should never decrease when concentration rises."""
        r1 = compute_sub_index("PM2.5", c1)
        r2 = compute_sub_index("PM2.5", c2)
        if c2 >= c1:
            assert r2.sub_index >= r1.sub_index

    @given(conc=st.floats(min_value=0, max_value=500, allow_nan=False))
    def test_category_always_valid(self, conc: float):
        """Every sub-index should produce a valid category."""
        result = compute_sub_index("PM2.5", conc)
        assert result.category in {
            "Good",
            "Satisfactory",
            "Moderately Polluted",
            "Poor",
            "Very Poor",
            "Severe",
        }
