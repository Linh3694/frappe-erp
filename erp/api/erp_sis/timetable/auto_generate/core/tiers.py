"""Thang phân tầng ràng buộc (constraint hierarchy) dùng chung toàn solver.

4 nấc theo độ ép buộc giảm dần:
  - MANDATORY: cứng tuyệt đối — luôn emit hard constraint, không bao giờ nới.
  - RELAXABLE: gần-cứng — chỉ nới khi không còn cách khác (pha 1 hybrid, phạt cực nặng).
  - STRONG:    mềm khó thương lượng — preference ưu tiên cao.
  - WEAK:      mềm dễ thương lượng — preference ưu tiên thấp.

`weight` (trên Rule / trên từng dòng dữ liệu) chỉ tinh chỉnh TRONG một tầng, default 1.

Cơ chế thực thi (xem runner.build_and_solve): Hybrid 2 pha.
  Pha 1 tối đa coverage + giảm vi phạm RELAXABLE rồi pin lại.
  Pha 2 tối ưu STRONG/WEAK bằng band trong cùng một objective.

LƯU Ý NHÓM A: các ràng buộc vật lý (no_overlap lớp/GV, room_max_simultaneous,
sync_class_*) KHÔNG bao giờ nhận tier — luôn cứng. Nới chúng làm TKB vô nghĩa
(GV dạy 2 lớp cùng lúc để "đạt 100%").
"""

from __future__ import annotations

MANDATORY = "mandatory"
RELAXABLE = "relaxable"
STRONG = "strong"
WEAK = "weak"

# Tầng mềm (preference) — gom objective theo các tầng này ở pha 2.
SOFT_TIERS = (STRONG, WEAK)

# Hệ số band cho pha 2 (strong áp đảo weak). Số nguyên — CP-SAT chạy nguyên thuần,
# không lo sai số float. 1e6 đủ để 1 term strong áp đảo tổng các term weak kể cả
# model lớn (weight weak ~4-7, tới hàng chục nghìn term vẫn < 1e6 đơn vị).
STRONG_FACTOR = 1_000_000
WEAK_FACTOR = 1

# Phạt vi phạm tầng relaxable (pha 1). Tách short/over để ưu tiên đủ tiết hơn tránh thừa.
RELAX_SHORT_PENALTY = 1000
RELAX_OVER_PENALTY = 50
RELAX_FORBIDDEN_PENALTY = 100  # phạt khi phá 1 ràng buộc relaxable kiểu cấm/giới hạn slot

_VALID_TIERS = {MANDATORY, RELAXABLE, STRONG, WEAK}
_VALID_ENFORCEMENT = {MANDATORY, RELAXABLE}


def normalize_tier(value, default: str = WEAK) -> str:
	"""Chuẩn hoá tier cấp rule; giá trị lạ → default."""
	v = value.strip().lower() if isinstance(value, str) else ""
	return v if v in _VALID_TIERS else default


def normalize_enforcement(value, default: str = MANDATORY) -> str:
	"""Cờ enforcement ở cấp dòng dữ liệu chỉ có 2 trạng thái: cứng / nới được.

	Mặc định MANDATORY để dữ liệu cũ (chưa có cột) giữ nguyên hành vi cứng.
	"""
	v = value.strip().lower() if isinstance(value, str) else ""
	return v if v in _VALID_ENFORCEMENT else default


def band_factor(tier: str) -> int:
	"""Hệ số nhân cho 1 term thuộc tầng mềm ở pha 2."""
	return STRONG_FACTOR if tier == STRONG else WEAK_FACTOR
