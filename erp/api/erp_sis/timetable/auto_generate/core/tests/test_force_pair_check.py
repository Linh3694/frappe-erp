"""Unit test kiểm tra force_pair post-hoc."""

from erp.api.erp_sis.timetable.auto_generate.core.force_pair_check import check_force_pair_violations


def test_even_pair_in_same_session_passes():
	# 8 tiết, sáng 0-3 chiều 4-7; Thứ 2 xếp tiết 3+4 (idx 2,3)
	by_day = {"mon": [2, 3]}
	assert check_force_pair_violations(8, ["mon"], by_day, 4) == []


def test_even_single_in_session_fails():
	# Chỉ tiết 5 (idx 4) cuối buổi sáng, không có tiết 3
	by_day = {"mon": [4]}
	v = check_force_pair_violations(8, ["mon"], by_day, 4)
	assert ("mon", 4) in v


def test_even_cross_session_not_paired():
	# idx 3 (cuối sáng) và idx 4 (đầu chiều) — khác buổi, không ghép cặp
	by_day = {"mon": [3, 4]}
	v = check_force_pair_violations(8, ["mon"], by_day, 4)
	assert ("mon", 3) in v
	assert ("mon", 4) in v


def test_odd_one_singleton_week_passes():
	# Tuần lẻ 5: 1 singleton toàn tuần
	by_day = {"mon": [2, 3], "wed": [6]}
	assert check_force_pair_violations(8, ["mon", "wed"], by_day, 5) == []


def test_odd_two_singletons_fails():
	by_day = {"mon": [4], "thu": [6]}
	v = check_force_pair_violations(8, ["mon", "thu"], by_day, 5)
	assert len(v) == 2
