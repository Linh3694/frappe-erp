"""26 rule mặc định — dùng offline (pytest) hoặc fallback khi chưa migrate DB."""

from __future__ import annotations

from .dto import Rule, RuleSet

# (rule_id, kind, verb, subject_type, subject_filter, params, weight, description)
DEFAULT_RULE_SPECS = [
	("class_no_overlap", "hard", "no_overlap", "class", {}, {}, 5, "Mỗi lớp tối đa 1 môn/slot"),
	("teacher_no_overlap", "hard", "no_overlap", "teacher", {}, {}, 5, "Mỗi GV tối đa 1 lớp/slot"),
	("room_no_overlap", "hard", "no_overlap", "room", {}, {}, 5, "Mỗi phòng tối đa 1 lớp/slot"),
	("curriculum_exact_periods", "hard", "exact_count_per_week", "assignment", {}, {}, 5, "Đúng số tiết/tuần (theo lớp)"),
	("subject_max_per_day", "hard", "at_most_per_scope", "assignment", {}, {"scope": "day", "source": "subject.max_per_day"}, 5, "Max tiết/ngày/môn (theo lớp)"),
	("teacher_unavailable", "hard", "forbidden_at_slots", "teacher", {}, {"source": "teacher.unavailability"}, 5, "GV slot bận"),
	("room_type_match", "hard", "attribute_match", "assignment", {"has_room_type_required": 1}, {"require": "room_type==required"}, 5, "Khớp loại phòng"),
	("teacher_max_periods_per_day", "hard", "at_most_per_scope", "teacher", {}, {"scope": "day", "source": "teacher.max_periods_per_day"}, 5, "Max tiết/ngày GV"),
	("teacher_max_periods_per_week", "hard", "at_most_per_scope", "teacher", {}, {"scope": "week", "source": "teacher.max_periods_per_week"}, 5, "Max tiết/tuần GV"),
	("avoid_teacher_gap", "soft", "avoid_gap", "teacher", {}, {}, 5, "Tránh gap GV"),
	("spread_subject_across_week", "soft", "spread_across_days", "assignment", {}, {}, 7, "Rải môn nhiều ngày"),
	("heavy_subjects_morning", "soft", "prefer_slot_range", "assignment", {"is_heavy": 1}, {"periods": [0, 1, 2, 3]}, 6, "Môn nặng sáng"),
	("limit_consecutive_teaching", "soft", "max_consecutive", "teacher", {}, {"max": 3, "global": True}, 4, "GV max liên tiếp global"),
	("avoid_single_period_visit", "soft", "avoid_single_visit", "teacher", {}, {}, 8, "Tránh 1 tiết/buổi"),
	("prefer_home_room", "soft", "attribute_match", "assignment", {}, {"require": "room==home_room"}, 3, "Phòng chủ nhiệm"),
	("balance_workload_across_week", "soft", "balance_workload", "teacher", {}, {}, 4, "Cân bằng tiết/tuần"),
	("subject_pair_periods", "hard", "consecutive_required", "subject", {}, {"size": 2, "no_break": True}, 5, "Cặp tiết bắt buộc"),
	("pinned_slot", "hard", "allow_only_at_slots", "subject", {}, {}, 5, "Môn chỉ ở slots chọn"),
	("teacher_not_at_slot", "hard", "forbidden_at_slots", "teacher", {}, {"source": "instances"}, 5, "GV không dạy slot"),
	("teacher_not_on_day", "hard", "forbidden_on_day", "teacher", {}, {"source": "instances"}, 5, "GV không dạy cả ngày"),
	("class_excluded_subject", "hard", "exclude_subject", "class", {}, {}, 5, "Lớp không học môn"),
	("pin_class_subject_slot", "hard", "pinned_to_slot", "assignment", {}, {}, 5, "Pin lớp+môn+slot"),
	("subject_max_n_per_day", "hard", "at_most_per_scope", "subject", {}, {"scope": "day"}, 5, "Override max/ngày"),
	("class_pair_simultaneous_subject", "hard", "sync_class_pair", "class", {}, {}, 5, "2 lớp cùng môn cùng slot"),
	("subject_before_subject", "hard", "order_before_same_day", "subject", {}, {}, 5, "Thứ tự môn trong ngày"),
	("subject_max_simultaneous_classes", "hard", "at_most_simultaneous", "subject", {}, {}, 5, "Max lớp đồng thời"),
	("teacher_max_consecutive", "soft", "max_consecutive", "teacher", {}, {"max": 3}, 4, "Max liên tiếp per-GV"),
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
			enabled=True,
			description=desc,
		))
	return RuleSet(name=name, rules=rules)
