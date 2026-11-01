"""Tests for trust score computation."""

from __future__ import annotations

from datetime import datetime, timezone

from core.quality.trust import (
    agreement_score,
    completeness_score,
    compute_trust,
    freshness_score,
    quality_score,
)


class TestFreshnessScore:
    def test_very_fresh(self):
        now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        reading = datetime(2026, 11, 1, 11, 30, tzinfo=timezone.utc)
        assert freshness_score(reading, now) == 1.0

    def test_3_hours_old(self):
        now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        reading = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
        score = freshness_score(reading, now)
        assert 0 < score < 1

    def test_very_stale(self):
        now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        reading = datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc)
        assert freshness_score(reading, now) == 0.0

    def test_exactly_1_hour(self):
        now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        reading = datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc)
        assert freshness_score(reading, now) == 1.0


class TestCompletenessScore:
    def test_full(self):
        assert completeness_score(24) == 1.0

    def test_half(self):
        assert completeness_score(12) == 0.5

    def test_zero(self):
        assert completeness_score(0) == 0.0

    def test_over_window(self):
        assert completeness_score(30) == 1.0

    def test_zero_window(self):
        assert completeness_score(10, 0) == 0.0


class TestQualityScore:
    def test_no_flags(self):
        assert quality_score(0, 24) == 1.0

    def test_all_flagged(self):
        assert quality_score(24, 24) == 0.0

    def test_half_flagged(self):
        assert quality_score(12, 24) == 0.5

    def test_no_readings(self):
        assert quality_score(0, 0) == 0.0


class TestAgreementScore:
    def test_matches_neighbours(self):
        assert agreement_score(100.0, [95.0, 105.0, 110.0]) == 1.0

    def test_no_neighbours(self):
        assert agreement_score(100.0, []) == 0.5

    def test_far_from_neighbours(self):
        score = agreement_score(300.0, [50.0, 60.0, 70.0])
        assert score < 0.5


class TestComputeTrust:
    def test_all_perfect(self):
        result = compute_trust(1.0, 1.0, 1.0, 1.0)
        assert result.level == "High"
        assert result.score == 1.0

    def test_all_zero(self):
        result = compute_trust(0.0, 0.0, 0.0, 0.0)
        assert result.level == "Low"
        assert result.score == 0.0

    def test_medium_trust(self):
        result = compute_trust(0.6, 0.7, 0.5, 0.5)
        assert result.level == "Medium"

    def test_score_bounds(self):
        result = compute_trust(0.5, 0.5, 0.5, 0.5)
        assert 0.0 <= result.score <= 1.0
