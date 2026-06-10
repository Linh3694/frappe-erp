"""28 rule mặc định — dùng offline (pytest) hoặc fallback khi chưa migrate DB."""

from __future__ import annotations

from .dto import Rule, RuleSet

# Không còn rule phòng nào tắt mặc định: room_max_simultaneous + room_eligibility là
# ràng buộc phòng cốt lõi, luôn bật (room_eligibility chỉ ràng buộc môn đã khai phòng).
DISABLED_DEFAULT_RULE_IDS = frozenset()

# (rule_id, kind, verb, subject_type, subject_filter, params, weight, description)
DEFAULT_RULE_SPECS = [
	("class_no_overlap", "hard", "no_overlap", "class", {}, {}, 5, "Mỗi lớp tối đa 1 môn/slot"),
	("teacher_no_overlap", "hard", "no_overlap", "teacher", {}, {}, 5, "Mỗi GV tối đa 1 lớp/slot"),
	("room_max_simultaneous", "hard", "room_max_simultaneous", "room", {}, {"max": 1}, 5, "Max lớp dùng chung 1 phòng"),
	("curriculum_exact_periods", "hard", "exact_count_per_week", "assignment", {}, {}, 5, "Đúng số tiết/tuần (theo lớp)"),
	("subject_max_per_day", "hard", "at_most_per_scope", "assignment", {}, {"scope": "day", "source": "subject.max_per_day"}, 5, "Max tiết/ngày/môn (theo lớp)"),
	("teacher_unavailable", "hard", "forbidden_at_slots", "teacher", {}, {"source": "teacher.unavailability"}, 5, "GV slot bận"),
	("room_eligibility", "hard", "room_eligibility", "assignment", {}, {}, 5, "Ràng buộc phòng hợp lệ theo môn/lớp"),
	("teacher_max_periods_per_day", "hard", "at_most_per_scope", "teacher", {}, {"scope": "day", "source": "teacher.max_periods_per_day"}, 5, "Max tiết/ngày GV"),
	("teacher_max_periods_per_week", "hard", "at_most_per_scope", "teacher", {}, {"scope": "week", "source": "teacher.max_periods_per_week"}, 5, "Max tiết/tuần GV"),
	("avoid_teacher_gap", "soft", "avoid_gap", "teacher", {}, {}, 5, "Tránh gap GV"),
	("spread_subject_across_week", "soft", "spread_across_days", "assignment", {}, {}, 7, "Rải môn nhiều ngày"),
	("interleave_programs_within_day", "soft", "program_interleaving", "assignment", {}, {}, 5, "Xen kẽ chương trình trong ngày"),
	("subject_preferred_periods", "soft", "prefer_slot_range", "subject", {}, {"source": "instances"}, 6, "Tiết ưu tiên theo môn"),
	("balance_workload_across_week", "soft", "balance_workload", "teacher", {}, {}, 4, "Cân bằng tiết/tuần"),
	("subject_not_at_slot", "hard", "forbidden_at_slots", "subject", {}, {"source": "instances"}, 5, "Môn không xếp tại slot"),
	("teacher_not_at_slot", "hard", "forbidden_at_slots", "teacher", {}, {"source": "instances"}, 5, "GV không dạy slot"),
	("teacher_not_on_day", "hard", "forbidden_on_day", "teacher", {}, {"source": "instances"}, 5, "GV không dạy cả ngày"),
	("pin_class_subject_slot", "hard", "pinned_to_slot", "assignment", {}, {}, 5, "Pin lớp+môn+slot"),
	("assignment_not_at_slot", "hard", "forbidden_at_slots", "assignment", {}, {"source": "instances"}, 5, "Lớp+môn không xếp tại slot"),
	("class_group_simultaneous_subject", "hard", "sync_class_group", "class", {}, {}, 5, "Nhóm lớp cùng môn cùng slot"),
	("subject_before_subject", "hard", "order_before_same_day", "subject", {}, {}, 5, "Thứ tự môn trong ngày"),
	("subject_max_simultaneous_classes", "hard", "at_most_simultaneous", "subject", {}, {}, 5, "Max lớp đồng thời"),
	("teacher_max_consecutive", "soft", "max_consecutive", "teacher", {}, {"use_teacher_field": True}, 4, "Max liên tiếp per-GV"),
]


def build_default_rule_set(name: str = "default") -> RuleSet:
	rules = []
	for i, (rid, kind, verb, stype, sfilt, params, weight, desc) in enumerate(DEFAULT_RULE_SPECS):
		rules.append(Rule(
			rule_id=rid,
			kind=kind,  # type: ignore[arg-type]
			verb=verb,
			subject_type=stype,
			subject_filter=dict(sfilt),
			params=dict(params),
			weight=weight,
			enabled=rid not in DISABLED_DEFAULT_RULE_IDS,
			description=desc,
		))
	return RuleSet(name=name, rules=rules)
