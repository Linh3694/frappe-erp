"""Xác định môn không thể / không cần rải nhiều ngày — ngoại lệ rule spread."""


def cannot_spread_across_days(periods_per_week: int, force_pair: bool) -> bool:
	"""
	TH1: định biên 1 tiết/tuần — không đủ tiết để rải.
	TH2: 2 tiết/tuần + cặp tiết — bắt buộc 1 cặp trên 1 ngày.
	"""
	if periods_per_week < 2:
		return True
	if periods_per_week == 2 and force_pair:
		return True
	return False
