"""Unit tests for the alert service — determine_action_needed logic.

These tests exercise the core zone-classification function directly,
without going through the API layer.  They use a simple stub object to
simulate a Holding's range-level attributes.

Zone layout (ascending price):

    base_level
      |
    lower_mid_range_2   <=  Y_DARK_RED   (at or below)
      |
    lower_mid_range_1   <=  Y_LOWER_MID  (between lmr2 and lmr1)
      |
    (neutral)           =>  N
      |
    upper_mid_range_1   >=  Y_UPPER_MID  (between umr1 and umr2)
      |
    upper_mid_range_2   >=  Y_DARK_GREEN (at or above)
      |
    top_level
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.services.alert_service import determine_action_needed


# ---------------------------------------------------------------------------
# Stub that mimics the relevant attributes of a Holding / WatchlistItem
# ---------------------------------------------------------------------------

@dataclass
class FakeHolding:
    lower_mid_range_1: float | None = None
    lower_mid_range_2: float | None = None
    upper_mid_range_1: float | None = None
    upper_mid_range_2: float | None = None
    base_level: float | None = None
    top_level: float | None = None


def _make_holding(
    lmr1: float | None = None,
    lmr2: float | None = None,
    umr1: float | None = None,
    umr2: float | None = None,
    base: float | None = None,
    top: float | None = None,
) -> FakeHolding:
    return FakeHolding(
        lower_mid_range_1=lmr1,
        lower_mid_range_2=lmr2,
        upper_mid_range_1=umr1,
        upper_mid_range_2=umr2,
        base_level=base,
        top_level=top,
    )


# Standard range fixture for most tests:
#   base=700, lmr2=800, lmr1=900, (neutral 900-1100), umr1=1100, umr2=1200, top=1300
STANDARD = _make_holding(lmr1=900, lmr2=800, umr1=1100, umr2=1200, base=700, top=1300)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDetermineActionNeeded:
    """Tests for determine_action_needed()."""

    # -- No action cases ----------------------------------------------------

    def test_no_ranges_defined(self):
        """Returns 'N' when all range levels are None."""
        h = _make_holding()  # all None
        assert determine_action_needed(1000.0, h) == "N"

    def test_current_price_is_none(self):
        """Returns 'N' when current_price is None, regardless of ranges."""
        assert determine_action_needed(None, STANDARD) == "N"

    def test_neutral_zone(self):
        """Price between lmr1 and umr1 yields 'N' (no action)."""
        # 1000 is between 900 (lmr1) and 1100 (umr1)
        assert determine_action_needed(1000.0, STANDARD) == "N"

    def test_price_exactly_between_ranges(self):
        """Price at 950 (firmly in neutral zone) returns 'N'."""
        assert determine_action_needed(950.0, STANDARD) == "N"

    # -- Lower zones (buying opportunity) -----------------------------------

    def test_y_lower_mid(self):
        """Price between lmr2 and lmr1 returns 'Y_LOWER_MID'."""
        # 850 is between 800 (lmr2) and 900 (lmr1)
        assert determine_action_needed(850.0, STANDARD) == "Y_LOWER_MID"

    def test_y_lower_mid_at_lmr1_boundary(self):
        """Price exactly at lmr1 (900) returns 'Y_LOWER_MID' (lmr2 < price <= lmr1)."""
        assert determine_action_needed(900.0, STANDARD) == "Y_LOWER_MID"

    def test_y_dark_red(self):
        """Price at or below lmr2 returns 'Y_DARK_RED'."""
        assert determine_action_needed(800.0, STANDARD) == "Y_DARK_RED"

    def test_y_dark_red_below_lmr2(self):
        """Price well below lmr2 returns 'Y_DARK_RED'."""
        assert determine_action_needed(650.0, STANDARD) == "Y_DARK_RED"

    # -- Upper zones (selling opportunity) ----------------------------------

    def test_y_upper_mid(self):
        """Price between umr1 and umr2 returns 'Y_UPPER_MID'."""
        # 1150 is between 1100 (umr1) and 1200 (umr2)
        assert determine_action_needed(1150.0, STANDARD) == "Y_UPPER_MID"

    def test_y_upper_mid_at_umr1_boundary(self):
        """Price exactly at umr1 (1100) returns 'Y_UPPER_MID' (umr1 <= price < umr2)."""
        assert determine_action_needed(1100.0, STANDARD) == "Y_UPPER_MID"

    def test_y_dark_green(self):
        """Price at or above umr2 returns 'Y_DARK_GREEN'."""
        assert determine_action_needed(1200.0, STANDARD) == "Y_DARK_GREEN"

    def test_y_dark_green_above_umr2(self):
        """Price well above umr2 returns 'Y_DARK_GREEN'."""
        assert determine_action_needed(1500.0, STANDARD) == "Y_DARK_GREEN"

    # -- Partial range definitions ------------------------------------------

    def test_only_lower_ranges_defined(self):
        """With only lower ranges, price below lmr2 returns 'Y_DARK_RED'."""
        h = _make_holding(lmr1=900, lmr2=800)
        assert determine_action_needed(750.0, h) == "Y_DARK_RED"
        assert determine_action_needed(850.0, h) == "Y_LOWER_MID"
        assert determine_action_needed(1000.0, h) == "N"

    def test_only_upper_ranges_defined(self):
        """With only upper ranges, price above umr2 returns 'Y_DARK_GREEN'."""
        h = _make_holding(umr1=1100, umr2=1200)
        assert determine_action_needed(1300.0, h) == "Y_DARK_GREEN"
        assert determine_action_needed(1150.0, h) == "Y_UPPER_MID"
        assert determine_action_needed(1000.0, h) == "N"

    def test_only_lmr2_defined(self):
        """With only lmr2, price at or below it returns 'Y_DARK_RED', above returns 'N'."""
        h = _make_holding(lmr2=800)
        assert determine_action_needed(800.0, h) == "Y_DARK_RED"
        assert determine_action_needed(750.0, h) == "Y_DARK_RED"
        # Above lmr2 but lmr1 is None, so Y_LOWER_MID cannot trigger
        assert determine_action_needed(850.0, h) == "N"

    def test_only_umr2_defined(self):
        """With only umr2, price at or above it returns 'Y_DARK_GREEN', below returns 'N'."""
        h = _make_holding(umr2=1200)
        assert determine_action_needed(1200.0, h) == "Y_DARK_GREEN"
        assert determine_action_needed(1300.0, h) == "Y_DARK_GREEN"
        # Below umr2 but umr1 is None, so Y_UPPER_MID cannot trigger
        assert determine_action_needed(1100.0, h) == "N"

    # -- Edge cases ---------------------------------------------------------

    def test_price_just_above_lmr2(self):
        """Price at 800.01 (just above lmr2=800) falls into Y_LOWER_MID."""
        assert determine_action_needed(800.01, STANDARD) == "Y_LOWER_MID"

    def test_price_just_below_umr2(self):
        """Price at 1199.99 (just below umr2=1200) falls into Y_UPPER_MID."""
        assert determine_action_needed(1199.99, STANDARD) == "Y_UPPER_MID"
