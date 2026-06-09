"""Unit test ngoại lệ rule rải môn."""

from erp.api.erp_sis.timetable.auto_generate.core.spread_eligibility import cannot_spread_across_days


def test_th1_one_period_per_week():
	assert cannot_spread_across_days(1, False) is True
	assert cannot_spread_across_days(1, True) is True


def test_th2_two_periods_with_force_pair():
	assert cannot_spread_across_days(2, True) is True


def test_two_periods_without_force_pair_can_spread():
	assert cannot_spread_across_days(2, False) is False


def test_four_periods_force_pair_can_still_spread():
	assert cannot_spread_across_days(4, True) is False
