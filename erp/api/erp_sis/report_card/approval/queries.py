# -*- coding: utf-8 -*-
"""
Pending Approvals Queries APIs
==============================

APIs cho việc lấy danh sách báo cáo đang chờ phê duyệt.
Hỗ trợ cả flat list và grouped view.

Functions:
- get_pending_approvals: Lấy danh sách flat (từng report)
- get_pending_approvals_grouped: Lấy danh sách grouped by class/subject

Tối ưu hiệu năng:
- Bulk-load templates, subjects, teachers, configs trong 1 lần đầu function (tránh N+1).
- Enrich student_name / class_title bằng 2 query IN duy nhất cuối cùng.
- _get_pending_subjects_detail dùng batch version: 1 query lấy data_json cho mọi report,
  1 query lấy title cho mọi subject.
- Approvers resolve theo (config, template, subject) — không resolve per-report.
"""

import frappe
from frappe import _
import json
from typing import Optional, Dict, List, Set, Any, Tuple

from erp.utils.api_response import (
    success_response,
    error_response,
)

from ..utils import get_current_campus_id

# Import helpers
from ..approval_helpers.helpers import (
    get_subject_approval_from_data_json,
)


# =============================================================================
# CONSTANTS
# =============================================================================

# Các status được coi là "đã pass L2" (đã duyệt cấp 2)
_L2_PASSED_STATUSES = ["level_2_approved", "reviewed", "published"]


# =============================================================================
# CORE HELPERS (single-record, dùng cho legacy / batch helpers)
# =============================================================================

def _parse_reviewer_list(json_str):
    """
    Parse JSON string thành list teacher IDs.
    Dùng cho homeroom_reviewer_level_1/2 multi-select.
    """
    if not json_str:
        return []
    try:
        result = json.loads(json_str)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _teacher_in_reviewers(teacher_id, json_str):
    """Check teacher có trong danh sách reviewers không."""
    return teacher_id in _parse_reviewer_list(json_str)


def _is_manager_role(user):
    """
    Check if user has SIS Manager, SIS BOD, or System Manager role.
    Những roles này có quyền xem TẤT CẢ báo cáo chờ duyệt (nhưng không có quyền duyệt).
    """
    user_roles = frappe.get_roles(user)
    return any(role in user_roles for role in ["SIS Manager", "SIS BOD", "System Manager"])


# =============================================================================
# BULK LOADERS (giảm N+1 query)
# =============================================================================

def _bulk_load_templates(campus_id: str) -> Dict[str, Dict[str, Any]]:
    """
    Load TẤT CẢ templates của campus trong 1 query duy nhất với đủ fields cần thiết.
    Sau đó các nhánh L1/L2/L3/L4 sẽ dùng chung dict này thay vì query lại.

    Returns:
        Dict {template_name: dict(name, title, education_stage, homeroom_reviewer_level_1,
              homeroom_reviewer_level_2, homeroom_enabled, scores_enabled,
              subject_eval_enabled, program_type)}
    """
    rows = frappe.get_all(
        "SIS Report Card Template",
        filters={"campus_id": campus_id},
        fields=[
            "name", "title", "education_stage",
            "homeroom_reviewer_level_1", "homeroom_reviewer_level_2",
            "homeroom_enabled", "scores_enabled", "subject_eval_enabled",
            "program_type",
        ],
    )
    return {r.name: r for r in rows}


def _bulk_load_template_subjects(template_ids: List[str]) -> Dict[str, Set[str]]:
    """
    Load Score Config + Subject Config cho tất cả templates trong 2 queries thay vì 2N.

    Returns:
        Dict {template_id: set(subject_ids)}
    """
    if not template_ids:
        return {}

    template_ids = list(set(template_ids))
    result: Dict[str, Set[str]] = {tid: set() for tid in template_ids}

    for child_dt in ["SIS Report Card Score Config", "SIS Report Card Subject Config"]:
        rows = frappe.get_all(
            child_dt,
            filters={
                "parent": ["in", template_ids],
                "parenttype": "SIS Report Card Template",
            },
            fields=["parent", "subject_id"],
        )
        for r in rows:
            result.setdefault(r.parent, set()).add(r.subject_id)
    return result


def _bulk_teacher_user_maps(teacher_ids: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Map {teacher_id → user_id} và {teacher_id → full_name} bằng 2 query thay vì 2N.

    Returns:
        (teacher_user_map, teacher_name_map)
        teacher_user_map: {teacher_id: user_id}
        teacher_name_map: {teacher_id: full_name (fallback teacher_id)}
    """
    if not teacher_ids:
        return {}, {}

    teacher_ids = list({tid for tid in teacher_ids if tid})
    if not teacher_ids:
        return {}, {}

    teachers = frappe.get_all(
        "SIS Teacher",
        filters={"name": ["in", teacher_ids]},
        fields=["name", "user_id"],
    )

    user_ids = list({t.user_id for t in teachers if t.user_id})
    user_name_map: Dict[str, str] = {}
    if user_ids:
        users = frappe.get_all(
            "User",
            filters={"name": ["in", user_ids]},
            fields=["name", "full_name"],
        )
        user_name_map = {u.name: (u.full_name or u.name) for u in users}

    teacher_user_map: Dict[str, str] = {}
    teacher_name_map: Dict[str, str] = {}
    for t in teachers:
        if t.user_id:
            teacher_user_map[t.name] = t.user_id
            teacher_name_map[t.name] = user_name_map.get(t.user_id, t.name)
        else:
            teacher_name_map[t.name] = t.name

    # Fallback cho các teacher không tồn tại
    for tid in teacher_ids:
        if tid not in teacher_name_map:
            teacher_name_map[tid] = tid

    return teacher_user_map, teacher_name_map


def _bulk_subject_titles(subject_ids: List[str]) -> Dict[str, str]:
    """Map {subject_id → display_title} từ 1 query."""
    if not subject_ids:
        return {}
    subject_ids = list({sid for sid in subject_ids if sid})
    if not subject_ids:
        return {}
    rows = frappe.get_all(
        "SIS Actual Subject",
        filters={"name": ["in", subject_ids]},
        fields=["name", "title_vn", "title_en"],
    )
    return {r.name: (r.title_vn or r.title_en or r.name) for r in rows}


def _bulk_subject_managers(subject_ids: List[str]) -> Dict[str, List[str]]:
    """Map {subject_id → list of teacher_ids (managers)} từ 1 query."""
    if not subject_ids:
        return {}
    subject_ids = list({sid for sid in subject_ids if sid})
    if not subject_ids:
        return {}
    rows = frappe.get_all(
        "SIS Actual Subject Manager",
        filters={"parent": ["in", subject_ids]},
        fields=["parent", "teacher_id"],
    )
    result: Dict[str, List[str]] = {}
    for r in rows:
        result.setdefault(r.parent, []).append(r.teacher_id)
    return result


def _bulk_subjects_managed_by(teacher_id: str) -> List[str]:
    """Lấy list subject_ids mà teacher đang là manager (1 query)."""
    if not teacher_id:
        return []
    rows = frappe.get_all(
        "SIS Actual Subject Manager",
        filters={"teacher_id": teacher_id},
        fields=["parent"],
    )
    return [r.parent for r in rows]


def _bulk_load_approval_configs(campus_id: str) -> Dict[str, Dict[str, Any]]:
    """
    Load tất cả approval configs + child tables (level_3_reviewers, level_4_approvers)
    trong 2 query thay vì 2 × N (N = số config).

    Returns:
        Dict {config_name: {
            "name", "education_stage_id",
            "l3_user_set": set(user_ids),   # user_ids resolved (đã merge teacher.user_id)
            "l4_user_set": set(user_ids),
            "l3_teacher_ids": list(teacher_ids),  # gốc, dùng để build approver names
            "l4_teacher_ids": list(teacher_ids),
        }}
    """
    configs = frappe.get_all(
        "SIS Report Card Approval Config",
        filters={"campus_id": campus_id, "is_active": 1},
        fields=["name", "education_stage_id"],
    )
    if not configs:
        return {}

    config_names = [c.name for c in configs]
    config_map: Dict[str, Dict[str, Any]] = {
        c.name: {
            "name": c.name,
            "education_stage_id": c.education_stage_id,
            "l3_user_set": set(),
            "l4_user_set": set(),
            "l3_teacher_ids": [],
            "l4_teacher_ids": [],
        }
        for c in configs
    }

    approvers = frappe.get_all(
        "SIS Report Card Approver",
        filters={
            "parent": ["in", config_names],
            "parentfield": ["in", ["level_3_reviewers", "level_4_approvers"]],
        },
        fields=["parent", "parentfield", "teacher_id", "user_id"],
    )

    # Gom tất cả teacher_id để resolve user_id 1 lần
    all_teacher_ids = list({a.teacher_id for a in approvers if a.teacher_id})
    teacher_user_map, _ = _bulk_teacher_user_maps(all_teacher_ids)

    for a in approvers:
        cm = config_map.get(a.parent)
        if not cm:
            continue
        resolved_user = a.user_id or teacher_user_map.get(a.teacher_id)
        if a.parentfield == "level_3_reviewers":
            if a.teacher_id:
                cm["l3_teacher_ids"].append(a.teacher_id)
            if resolved_user:
                cm["l3_user_set"].add(resolved_user)
        else:  # level_4_approvers
            if a.teacher_id:
                cm["l4_teacher_ids"].append(a.teacher_id)
            if resolved_user:
                cm["l4_user_set"].add(resolved_user)

    return config_map


def _bulk_enrich_students_classes(reports: List[Dict[str, Any]]) -> None:
    """
    Enrich student_name, student_code, class_title cho danh sách reports IN-PLACE.
    Trước đây: 2N queries. Sau: 2 queries cố định.
    """
    if not reports:
        return

    student_ids = list({r["student_id"] for r in reports if r.get("student_id")})
    class_ids = list({r["class_id"] for r in reports if r.get("class_id")})

    student_map: Dict[str, Any] = {}
    if student_ids:
        students = frappe.get_all(
            "CRM Student",
            filters={"name": ["in", student_ids]},
            fields=["name", "student_name", "student_code"],
        )
        student_map = {s.name: s for s in students}

    class_map: Dict[str, Any] = {}
    if class_ids:
        classes = frappe.get_all(
            "SIS Class",
            filters={"name": ["in", class_ids]},
            fields=["name", "title", "short_title"],
        )
        class_map = {c.name: c for c in classes}

    for r in reports:
        s = student_map.get(r.get("student_id"))
        if s:
            r["student_name"] = s.student_name
            r["student_code"] = s.student_code
        c = class_map.get(r.get("class_id"))
        if c:
            # Logic gốc: get_pending_approvals dùng (title or short_title)
            # còn get_pending_approvals_grouped dùng (short_title or title).
            # Set cả 2 vào để caller chọn — caller sẽ tự pick.
            r["class_title"] = c.title or c.short_title
            r["_class_title_short_first"] = c.short_title or c.title


def _bulk_pending_subjects_detail(
    report_names: List[str],
    sections: List[str],
) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """
    Batch version của `_get_pending_subjects_detail`.

    Trước: N reports × M sections × subject_count → N×M×k queries.
    Sau: 2 queries (data_json + subject titles).

    Args:
        report_names: List of report IDs
        sections: List of section types cần lấy (e.g. ["scores", "subject_eval", "intl_scores"])

    Returns:
        Dict {(report_name, section): [{"subject_id", "subject_name", "status", "is_approved"}, ...]}
    """
    if not report_names or not sections:
        return {}

    report_names = list(set(report_names))

    # Bước 1: batch fetch data_json
    rows = frappe.get_all(
        "SIS Student Report Card",
        filters={"name": ["in", report_names]},
        fields=["name", "data_json"],
    )

    # Bước 2: parse + collect subject_ids
    parsed_map: Dict[str, Dict[str, Any]] = {}
    all_subject_ids: Set[str] = set()
    for r in rows:
        try:
            dj = json.loads(r.data_json) if r.data_json else {}
        except (json.JSONDecodeError, TypeError):
            dj = {}
        parsed_map[r.name] = dj
        for section in sections:
            section_data = dj.get(section, {}) or {}
            if isinstance(section_data, dict):
                for sid in section_data.keys():
                    if sid:
                        all_subject_ids.add(sid)

    # Bước 3: batch fetch subject titles
    subject_title_map = _bulk_subject_titles(list(all_subject_ids))

    # Bước 4: build result
    result: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r_name, dj in parsed_map.items():
        for section in sections:
            section_data = dj.get(section, {}) or {}
            if not isinstance(section_data, dict):
                result[(r_name, section)] = []
                continue
            details = []
            for sid, subject_data in section_data.items():
                if not isinstance(subject_data, dict):
                    continue
                approval = subject_data.get("approval", {}) or {}
                status = approval.get("status", "draft")
                is_approved = status in _L2_PASSED_STATUSES
                details.append({
                    "subject_id": sid,
                    "subject_name": subject_title_map.get(sid, sid),
                    "status": status,
                    "is_approved": is_approved,
                })
            details.sort(key=lambda x: (x["is_approved"], x["subject_name"]))
            result[(r_name, section)] = details
    return result


# =============================================================================
# LEGACY HELPERS (giữ để backward compatible, không dùng trong path tối ưu)
# =============================================================================

def _get_pending_subjects_detail(report_name: str, section_type: str = "subject_eval") -> list:
    """
    DEPRECATED: dùng `_bulk_pending_subjects_detail` cho hiệu năng tốt hơn.
    Giữ lại function này để backward compatible nếu có module khác gọi tới.
    """
    result = _bulk_pending_subjects_detail([report_name], [section_type])
    return result.get((report_name, section_type), [])


def _get_teacher_name(teacher_id):
    """DEPRECATED: dùng `_bulk_teacher_user_maps` để batch."""
    if not teacher_id:
        return None
    _, name_map = _bulk_teacher_user_maps([teacher_id])
    return name_map.get(teacher_id)


# =============================================================================
# APPROVERS RESOLUTION (dựa trên cache)
# =============================================================================

def _resolve_approver_names(teacher_ids: List[str], teacher_name_map: Dict[str, str]) -> List[str]:
    """Convert list teacher_ids → list display names (dedupe, giữ thứ tự)."""
    out: List[str] = []
    seen: Set[str] = set()
    for tid in teacher_ids:
        name = teacher_name_map.get(tid) or tid
        if name and name not in seen:
            out.append(name)
            seen.add(name)
    return out


def _get_approvers_for_level_cached(
    level: str,
    template: Optional[Dict[str, Any]] = None,
    config_data: Optional[Dict[str, Any]] = None,
    subject_id: Optional[str] = None,
    teacher_name_map: Optional[Dict[str, str]] = None,
    subject_manager_map: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """
    Phiên bản cached của `_get_approvers_for_level`.
    Nhận sẵn các map (teacher_name_map, subject_manager_map, config_data) thay vì query.
    """
    teacher_name_map = teacher_name_map or {}
    subject_manager_map = subject_manager_map or {}
    approvers: List[str] = []

    if level == "level_1" and template:
        ids = _parse_reviewer_list(template.get("homeroom_reviewer_level_1"))
        approvers.extend(_resolve_approver_names(ids, teacher_name_map))

    elif level == "level_2":
        seen: Set[str] = set()

        def _extend(names: List[str]):
            for n in names:
                if n and n not in seen:
                    approvers.append(n)
                    seen.add(n)

        if template:
            ids = _parse_reviewer_list(template.get("homeroom_reviewer_level_2"))
            _extend(_resolve_approver_names(ids, teacher_name_map))

        if subject_id:
            manager_teachers = subject_manager_map.get(subject_id, [])
            _extend(_resolve_approver_names(manager_teachers, teacher_name_map))

    elif level == "review" and config_data:
        approvers.extend(_resolve_approver_names(config_data.get("l3_teacher_ids", []), teacher_name_map))

    elif level == "publish" and config_data:
        approvers.extend(_resolve_approver_names(config_data.get("l4_teacher_ids", []), teacher_name_map))

    return approvers


# Legacy wrapper - giữ để không break nếu có nơi khác gọi (hiện không có)
def _get_approvers_for_level(level, template=None, config=None, subject_id=None, campus_id=None):
    """
    DEPRECATED: dùng `_get_approvers_for_level_cached`.
    Wrapper tự build cache để duy trì interface cũ.
    """
    teacher_ids: List[str] = []
    if level == "level_1" and template:
        teacher_ids.extend(_parse_reviewer_list(template.get("homeroom_reviewer_level_1")))
    elif level == "level_2":
        if template:
            teacher_ids.extend(_parse_reviewer_list(template.get("homeroom_reviewer_level_2")))
        if subject_id:
            for m in frappe.get_all(
                "SIS Actual Subject Manager",
                filters={"parent": subject_id},
                fields=["teacher_id"],
            ):
                teacher_ids.append(m.teacher_id)
    elif level == "review" and config:
        rows = frappe.get_all(
            "SIS Report Card Approver",
            filters={"parent": config.name, "parentfield": "level_3_reviewers"},
            fields=["teacher_id"],
        )
        teacher_ids.extend(r.teacher_id for r in rows if r.teacher_id)
    elif level == "publish" and config:
        rows = frappe.get_all(
            "SIS Report Card Approver",
            filters={"parent": config.name, "parentfield": "level_4_approvers"},
            fields=["teacher_id"],
        )
        teacher_ids.extend(r.teacher_id for r in rows if r.teacher_id)

    _, name_map = _bulk_teacher_user_maps(teacher_ids)
    return _resolve_approver_names(teacher_ids, name_map)


# =============================================================================
# PENDING APPROVALS - FLAT LIST (TỐI ƯU)
# =============================================================================

@frappe.whitelist(allow_guest=False)
def get_pending_approvals(level: Optional[str] = None):
    """
    Lấy danh sách báo cáo đang chờ duyệt cho user hiện tại.

    Args:
        level: Filter theo level (level_1, level_2, review, publish)
    """
    try:
        # Lấy params từ nhiều nguồn cho GET requests
        if not level:
            level = frappe.form_dict.get("level")
        if not level and hasattr(frappe.request, "args"):
            level = frappe.request.args.get("level")

        user = frappe.session.user
        campus_id = get_current_campus_id()
        is_manager = _is_manager_role(user)

        # Lấy teacher của user
        teacher = frappe.get_all(
            "SIS Teacher",
            filters={"user_id": user, "campus_id": campus_id},
            fields=["name"],
            limit=1,
        )
        teacher_id = teacher[0].name if teacher else None

        # =========================================================
        # BULK LOAD METADATA 1 LẦN
        # =========================================================
        all_templates_map = _bulk_load_templates(campus_id)  # {tmpl_id: row}
        all_template_ids = list(all_templates_map.keys())
        template_subjects_map = _bulk_load_template_subjects(all_template_ids)  # {tmpl_id: set(sid)}

        # =========================================================
        # PHASE 1: COLLECT pending reports
        # =========================================================
        results: List[Dict[str, Any]] = []
        seen_names: Set[str] = set()

        def _add_unique(report: Dict[str, Any]):
            """Thêm report nếu chưa có (theo name)."""
            if report["name"] in seen_names:
                return
            seen_names.add(report["name"])
            results.append(report)

        # ---------------- Level 1 ----------------
        if not level or level == "level_1":
            # Templates teacher có quyền duyệt L1 (filter Python vì field là JSON)
            l1_for_teacher_ids: List[str] = []
            if teacher_id:
                l1_for_teacher_ids = [
                    tid for tid, t in all_templates_map.items()
                    if _teacher_in_reviewers(teacher_id, t.get("homeroom_reviewer_level_1"))
                ]

            # Manager xem hết → lấy templates CÓ ÍT NHẤT 1 reviewer
            l1_for_manager_ids: List[str] = []
            if is_manager:
                l1_for_manager_ids = [
                    tid for tid, t in all_templates_map.items()
                    if _parse_reviewer_list(t.get("homeroom_reviewer_level_1"))
                ]

            l1_filter_ids = list(set(l1_for_teacher_ids) | set(l1_for_manager_ids))
            if l1_filter_ids:
                reports_l1 = frappe.get_all(
                    "SIS Student Report Card",
                    filters={
                        "template_id": ["in", l1_filter_ids],
                        "approval_status": "submitted",
                        "campus_id": campus_id,
                    },
                    fields=["name", "title", "student_id", "class_id", "approval_status",
                            "submitted_at", "template_id"],
                )
                teacher_set = set(l1_for_teacher_ids)
                for r in reports_l1:
                    r["pending_level"] = "level_1"
                    # Nếu user không phải reviewer thực sự thì viewer_only
                    if r["template_id"] not in teacher_set:
                        r["is_viewer_only"] = True
                    _add_unique(r)

        # ---------------- Level 2 ----------------
        if not level or level == "level_2":
            # 1. Tổ trưởng (homeroom_reviewer_level_2)
            l2_homeroom_for_teacher_ids: List[str] = []
            if teacher_id:
                l2_homeroom_for_teacher_ids = [
                    tid for tid, t in all_templates_map.items()
                    if _teacher_in_reviewers(teacher_id, t.get("homeroom_reviewer_level_2"))
                ]

            l2_homeroom_for_manager_ids: List[str] = []
            if is_manager:
                l2_homeroom_for_manager_ids = [
                    tid for tid, t in all_templates_map.items()
                    if _parse_reviewer_list(t.get("homeroom_reviewer_level_2"))
                ]

            l2_homeroom_filter = list(set(l2_homeroom_for_teacher_ids) | set(l2_homeroom_for_manager_ids))
            if l2_homeroom_filter:
                reports_l2 = frappe.get_all(
                    "SIS Student Report Card",
                    filters={
                        "template_id": ["in", l2_homeroom_filter],
                        "approval_status": ["in", ["submitted", "level_1_approved"]],
                        "campus_id": campus_id,
                    },
                    fields=["name", "title", "student_id", "class_id", "approval_status",
                            "submitted_at", "template_id"],
                )
                teacher_set = set(l2_homeroom_for_teacher_ids)
                for r in reports_l2:
                    r["pending_level"] = "level_2"
                    if r["template_id"] not in teacher_set:
                        r["is_viewer_only"] = True
                    _add_unique(r)

            # 2. Subject Manager
            l2_subject_template_ids_for_teacher: Set[str] = set()
            if teacher_id:
                managed_subjects = _bulk_subjects_managed_by(teacher_id)
                if managed_subjects:
                    managed_set = set(managed_subjects)
                    for tid, subjects in template_subjects_map.items():
                        if subjects & managed_set:
                            l2_subject_template_ids_for_teacher.add(tid)

            # Manager xem tất cả templates có subject (level_1_approved)
            l2_subject_template_ids_for_manager: Set[str] = set()
            if is_manager:
                for tid, subjects in template_subjects_map.items():
                    if subjects:
                        l2_subject_template_ids_for_manager.add(tid)

            l2_subject_filter = list(l2_subject_template_ids_for_teacher | l2_subject_template_ids_for_manager)
            if l2_subject_filter:
                reports_sm = frappe.get_all(
                    "SIS Student Report Card",
                    filters={
                        "template_id": ["in", l2_subject_filter],
                        "approval_status": "level_1_approved",
                        "campus_id": campus_id,
                    },
                    fields=["name", "title", "student_id", "class_id", "approval_status",
                            "submitted_at", "template_id"],
                )
                for r in reports_sm:
                    r["pending_level"] = "level_2"
                    if r["template_id"] not in l2_subject_template_ids_for_teacher:
                        r["is_viewer_only"] = True
                    _add_unique(r)

        # ---------------- Level 3 & 4 ----------------
        l3_l4_configs_map: Dict[str, Dict[str, Any]] = {}
        if not level or level in ["review", "publish"]:
            l3_l4_configs_map = _bulk_load_approval_configs(campus_id)

            # Pre-compute education_stage → list of template_ids
            stage_template_map: Dict[str, List[Dict[str, Any]]] = {}
            for tid, t in all_templates_map.items():
                stage = t.get("education_stage")
                if stage:
                    stage_template_map.setdefault(stage, []).append(t)

            l3_reports_to_enrich: List[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]] = []

            for cfg_name, cfg in l3_l4_configs_map.items():
                # --- L3 ---
                if not level or level == "review":
                    is_l3 = user in cfg["l3_user_set"]
                    if is_l3 or is_manager:
                        templates = stage_template_map.get(cfg["education_stage_id"], [])
                        for tmpl in templates:
                            homeroom_enabled = tmpl.get("homeroom_enabled")
                            scores_enabled = tmpl.get("scores_enabled")
                            subject_eval_enabled = tmpl.get("subject_eval_enabled")
                            is_intl = tmpl.get("program_type") == "intl"

                            if not homeroom_enabled and not scores_enabled and not subject_eval_enabled and not is_intl:
                                continue

                            or_filters = []
                            if homeroom_enabled:
                                or_filters.append(["homeroom_l2_approved", "=", 1])
                            if scores_enabled and not is_intl:
                                or_filters.append(["scores_l2_approved_count", ">", 0])
                            if subject_eval_enabled:
                                or_filters.append(["subject_eval_l2_approved_count", ">", 0])
                            if is_intl:
                                or_filters.append(["intl_l2_approved_count", ">", 0])

                            if not or_filters:
                                continue

                            reports_l3 = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": tmpl["name"],
                                    "campus_id": campus_id,
                                    "approval_status": ["not in", ["reviewed", "published"]],
                                },
                                or_filters=or_filters,
                                fields=[
                                    "name", "title", "student_id", "class_id", "approval_status",
                                    "template_id",
                                    "homeroom_approval_status", "scores_approval_status",
                                    "homeroom_l2_approved", "all_sections_l2_approved",
                                    "scores_submitted_count", "scores_l2_approved_count", "scores_total_count",
                                    "subject_eval_submitted_count", "subject_eval_l2_approved_count", "subject_eval_total_count",
                                    "intl_submitted_count", "intl_l2_approved_count", "intl_total_count",
                                ],
                            )
                            for r in reports_l3:
                                r["pending_level"] = "review"
                                r["is_complete"] = bool(r.get("all_sections_l2_approved"))
                                if is_manager and not is_l3:
                                    r["is_viewer_only"] = True
                                # Lưu reference để enrich sau (cần biết template + cfg để build progress + approvers)
                                l3_reports_to_enrich.append((r, tmpl, cfg))
                                _add_unique(r)

                # --- L4 ---
                if not level or level == "publish":
                    is_l4 = user in cfg["l4_user_set"]
                    if is_l4 or is_manager:
                        templates = stage_template_map.get(cfg["education_stage_id"], [])
                        if templates:
                            template_program_type = {
                                t["name"]: t.get("program_type") for t in templates
                            }
                            reports_l4 = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": ["in", [t["name"] for t in templates]],
                                    "approval_status": ["in", ["reviewed", "published"]],
                                    "campus_id": campus_id,
                                },
                                fields=[
                                    "name", "title", "student_id", "class_id", "approval_status",
                                    "template_id",
                                ],
                            )
                            for r in reports_l4:
                                r["pending_level"] = "publish"
                                tmpl_pt = template_program_type.get(r.get("template_id")) or "vn"
                                r["progress"] = {
                                    "program_type": "intl" if tmpl_pt == "intl" else "vn",
                                }
                                if is_manager and not is_l4:
                                    r["is_viewer_only"] = True
                                # Lưu cfg để enrich approvers sau
                                r["_cfg_for_approvers"] = cfg
                                _add_unique(r)

        # =========================================================
        # PHASE 2: VALIDATE orphan records (template không tồn tại)
        # =========================================================
        # Vì all_templates_map đã chứa toàn bộ template hợp lệ của campus,
        # ta chỉ cần check template_id ∈ all_templates_map.
        if results:
            # Lấy template_id của các report đã thu thập (đa số đã có sẵn từ fields ở trên)
            missing_template_names = [r["name"] for r in results if not r.get("template_id")]
            if missing_template_names:
                # Một số report (L3/L4 trên path cũ) có thể thiếu template_id — fallback fetch.
                tmpl_lookups = frappe.get_all(
                    "SIS Student Report Card",
                    filters={"name": ["in", missing_template_names]},
                    fields=["name", "template_id"],
                )
                lookup_map = {x.name: x.template_id for x in tmpl_lookups}
                for r in results:
                    if not r.get("template_id"):
                        r["template_id"] = lookup_map.get(r["name"])

            results = [r for r in results if r.get("template_id") and r["template_id"] in all_templates_map]

        # =========================================================
        # PHASE 3: ENRICH (batch)
        # =========================================================

        # 3.1: enrich student + class trong 2 query duy nhất
        _bulk_enrich_students_classes(results)

        # 3.2: enrich progress + approvers cho L3
        # Trước: mỗi L3 report đọc data_json + load subject titles riêng → batch hết
        l3_report_names = [r["name"] for r in results if r.get("pending_level") == "review"]
        l3_subject_detail_map: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        if l3_report_names:
            # Lấy detail cho tất cả 3 sections trong 1 lần
            l3_subject_detail_map = _bulk_pending_subjects_detail(
                l3_report_names, ["scores", "subject_eval", "intl_scores"]
            )

        # Tổng hợp teacher_ids cần resolve names (chỉ những level/template thực sự xuất hiện trong results)
        all_teacher_ids_for_approvers: Set[str] = set()
        for r in results:
            tmpl = all_templates_map.get(r.get("template_id"))
            if not tmpl:
                continue
            pl = r.get("pending_level")
            if pl == "level_1":
                all_teacher_ids_for_approvers.update(
                    _parse_reviewer_list(tmpl.get("homeroom_reviewer_level_1"))
                )
            elif pl == "level_2":
                all_teacher_ids_for_approvers.update(
                    _parse_reviewer_list(tmpl.get("homeroom_reviewer_level_2"))
                )

        # Subject managers cho L2: cần cho frontend? — get_pending_approvals (flat) hiện không trả approvers cho L1/L2.
        # Chỉ L3, L4 trả approvers (xem code gốc lines 533, 591). Vẫn cần teacher_name_map cho L3, L4.
        for cfg in l3_l4_configs_map.values():
            all_teacher_ids_for_approvers.update(cfg.get("l3_teacher_ids", []))
            all_teacher_ids_for_approvers.update(cfg.get("l4_teacher_ids", []))

        _, teacher_name_map = _bulk_teacher_user_maps(list(all_teacher_ids_for_approvers))

        for r in results:
            if r.get("pending_level") == "review":
                tmpl = all_templates_map.get(r.get("template_id")) or {}
                homeroom_enabled = tmpl.get("homeroom_enabled")
                scores_enabled = tmpl.get("scores_enabled")
                subject_eval_enabled = tmpl.get("subject_eval_enabled")
                is_intl = tmpl.get("program_type") == "intl"

                progress_obj: Dict[str, Any] = {
                    "program_type": tmpl.get("program_type", "vn"),
                }
                if not is_intl:
                    if homeroom_enabled:
                        progress_obj["homeroom_l2_approved"] = r.get("homeroom_l2_approved")
                    if scores_enabled:
                        progress_obj["scores"] = f"{r.get('scores_l2_approved_count', 0)}/{r.get('scores_total_count', 0)}"
                        if not r["is_complete"]:
                            detail = l3_subject_detail_map.get((r["name"], "scores"), [])
                            if detail:
                                progress_obj["scores_detail"] = detail
                    if subject_eval_enabled:
                        progress_obj["subject_eval"] = f"{r.get('subject_eval_l2_approved_count', 0)}/{r.get('subject_eval_total_count', 0)}"
                        if not r["is_complete"]:
                            detail = l3_subject_detail_map.get((r["name"], "subject_eval"), [])
                            if detail:
                                progress_obj["subject_eval_detail"] = detail
                else:
                    progress_obj["intl"] = f"{r.get('intl_l2_approved_count', 0)}/{r.get('intl_total_count', 0)}"
                    if not r["is_complete"]:
                        detail = l3_subject_detail_map.get((r["name"], "intl_scores"), [])
                        if detail:
                            progress_obj["intl_detail"] = detail
                r["progress"] = progress_obj

                # approvers cho L3: cần map từ template → config (qua education_stage)
                cfg_data = None
                stage = tmpl.get("education_stage")
                if stage:
                    for cfg in l3_l4_configs_map.values():
                        if cfg["education_stage_id"] == stage:
                            cfg_data = cfg
                            break
                r["approvers"] = _get_approvers_for_level_cached(
                    "review",
                    template=tmpl,
                    config_data=cfg_data,
                    teacher_name_map=teacher_name_map,
                )

            elif r.get("pending_level") == "publish":
                cfg_data = r.pop("_cfg_for_approvers", None)
                tmpl = all_templates_map.get(r.get("template_id")) or {}
                r["approvers"] = _get_approvers_for_level_cached(
                    "publish",
                    template=tmpl,
                    config_data=cfg_data,
                    teacher_name_map=teacher_name_map,
                )

        # Cleanup temp fields không nên expose
        for r in results:
            r.pop("_class_title_short_first", None)

        return success_response(
            data={
                "reports": results,
                "total": len(results),
            },
            message=f"Tìm thấy {len(results)} báo cáo đang chờ duyệt",
        )

    except Exception as e:
        frappe.logger().error(f"Error in get_pending_approvals: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        return error_response(f"Lỗi khi lấy danh sách chờ duyệt: {str(e)}")


# =============================================================================
# PENDING APPROVALS - GROUPED BY CLASS/SUBJECT (TỐI ƯU)
# =============================================================================

@frappe.whitelist(allow_guest=False)
def get_pending_approvals_grouped(level: Optional[str] = None):
    """
    Lấy danh sách báo cáo đang chờ duyệt, grouped by (template, class, subject).
    Trả về dạng aggregated để hiển thị theo Lớp + Môn.

    Args:
        level: Filter theo level (level_1, level_2, review, publish)
    """
    try:
        if not level:
            level = frappe.form_dict.get("level")
        if not level and hasattr(frappe.request, "args"):
            level = frappe.request.args.get("level")

        user = frappe.session.user
        campus_id = get_current_campus_id()
        is_manager = _is_manager_role(user)

        teacher = frappe.get_all(
            "SIS Teacher",
            filters={"user_id": user, "campus_id": campus_id},
            fields=["name"],
            limit=1,
        )
        teacher_id = teacher[0].name if teacher else None

        # =========================================================
        # BULK LOAD METADATA 1 LẦN
        # =========================================================
        all_templates_map = _bulk_load_templates(campus_id)
        all_template_ids = list(all_templates_map.keys())
        template_subjects_map = _bulk_load_template_subjects(all_template_ids)

        all_reports: List[Dict[str, Any]] = []

        # =========================================================
        # LEVEL 1
        # =========================================================
        if not level or level == "level_1":
            l1_teacher_template_ids: List[str] = []
            if teacher_id:
                l1_teacher_template_ids = [
                    tid for tid, t in all_templates_map.items()
                    if _teacher_in_reviewers(teacher_id, t.get("homeroom_reviewer_level_1"))
                ]

            l1_manager_template_ids: List[str] = []
            if is_manager:
                l1_manager_template_ids = [
                    tid for tid, t in all_templates_map.items()
                    if _parse_reviewer_list(t.get("homeroom_reviewer_level_1"))
                ]

            l1_filter = list(set(l1_teacher_template_ids) | set(l1_manager_template_ids))
            if l1_filter:
                reports = frappe.get_all(
                    "SIS Student Report Card",
                    filters={
                        "template_id": ["in", l1_filter],
                        "homeroom_approval_status": "submitted",
                        "campus_id": campus_id,
                    },
                    fields=[
                        "name", "class_id", "template_id",
                        "homeroom_submitted_at", "homeroom_submitted_by",
                        "homeroom_rejection_reason", "homeroom_rejected_by", "homeroom_rejected_at",
                        "rejected_from_level", "rejected_section",
                    ],
                )
                teacher_set = set(l1_teacher_template_ids)
                seen_l1: Set[str] = set()
                for r in reports:
                    if r["name"] in seen_l1:
                        continue
                    seen_l1.add(r["name"])
                    tmpl = all_templates_map.get(r["template_id"]) or {}
                    r["template_title"] = tmpl.get("title")
                    r["pending_level"] = "level_1"
                    r["subject_id"] = None
                    r["subject_title"] = "Nhận xét chủ nhiệm"
                    r["submitted_at"] = r.get("homeroom_submitted_at")
                    r["submitted_by"] = r.get("homeroom_submitted_by")
                    if r.get("homeroom_rejection_reason") and r.get("rejected_from_level") == 2:
                        r["was_rejected"] = True
                        r["rejection_reason"] = r.get("homeroom_rejection_reason")
                    if r["template_id"] not in teacher_set:
                        r["is_viewer_only"] = True
                    all_reports.append(r)

        # =========================================================
        # LEVEL 2
        # =========================================================
        if not level or level == "level_2":
            # ---- L2 Homeroom (Tổ trưởng) ----
            l2_homeroom_teacher_ids: List[str] = []
            if teacher_id:
                l2_homeroom_teacher_ids = [
                    tid for tid, t in all_templates_map.items()
                    if _teacher_in_reviewers(teacher_id, t.get("homeroom_reviewer_level_2"))
                ]

            l2_homeroom_manager_ids: List[str] = []
            if is_manager:
                l2_homeroom_manager_ids = [
                    tid for tid, t in all_templates_map.items()
                    if _parse_reviewer_list(t.get("homeroom_reviewer_level_2"))
                ]

            l2_homeroom_filter = list(set(l2_homeroom_teacher_ids) | set(l2_homeroom_manager_ids))
            if l2_homeroom_filter:
                reports = frappe.get_all(
                    "SIS Student Report Card",
                    filters={
                        "template_id": ["in", l2_homeroom_filter],
                        "homeroom_approval_status": "level_1_approved",
                        "campus_id": campus_id,
                    },
                    fields=[
                        "name", "class_id", "template_id",
                        "homeroom_submitted_at", "homeroom_submitted_by",
                        "homeroom_rejection_reason", "homeroom_rejected_by", "homeroom_rejected_at",
                        "rejected_from_level", "rejected_section",
                    ],
                )
                teacher_set = set(l2_homeroom_teacher_ids)
                seen_l2h: Set[Tuple[str, Any]] = set()
                for r in reports:
                    key = (r["name"], None)
                    if key in seen_l2h:
                        continue
                    seen_l2h.add(key)
                    tmpl = all_templates_map.get(r["template_id"]) or {}
                    r["template_title"] = tmpl.get("title")
                    r["pending_level"] = "level_2"
                    r["subject_id"] = None
                    r["subject_title"] = "Nhận xét chủ nhiệm"
                    r["submitted_at"] = r.get("homeroom_submitted_at")
                    r["submitted_by"] = r.get("homeroom_submitted_by")
                    if r.get("homeroom_rejection_reason") and r.get("rejected_from_level") == 3:
                        r["was_rejected"] = True
                        r["rejection_reason"] = r.get("homeroom_rejection_reason")
                    elif r.get("rejected_from_level") == 3 and r.get("rejected_section") in ["homeroom", "both"]:
                        r["was_rejected"] = True
                    if r["template_id"] not in teacher_set:
                        r["is_viewer_only"] = True
                    all_reports.append(r)

            # ---- L2 Subject (Subject Manager) ----
            # Teacher's managed subjects
            teacher_subject_ids: Set[str] = set()
            if teacher_id:
                teacher_subject_ids = set(_bulk_subjects_managed_by(teacher_id))

            # Manager xem ALL subjects → để biết "tất cả subjects của campus"
            all_campus_subject_ids: Set[str] = set()
            if is_manager:
                for sids in template_subjects_map.values():
                    all_campus_subject_ids.update(sids)

            # Tất cả subjects relevant cho L2 subject
            relevant_subject_ids = teacher_subject_ids | all_campus_subject_ids

            if relevant_subject_ids:
                # Pre-fetch subject titles
                subject_title_map = _bulk_subject_titles(list(relevant_subject_ids))

                # Templates có ít nhất 1 subject relevant
                relevant_template_to_subjects: Dict[str, Set[str]] = {}
                for tid, subs in template_subjects_map.items():
                    intersect = subs & relevant_subject_ids
                    if intersect:
                        relevant_template_to_subjects[tid] = intersect

                if relevant_template_to_subjects:
                    # 1 query lấy tất cả reports relevant
                    reports = frappe.get_all(
                        "SIS Student Report Card",
                        filters={
                            "template_id": ["in", list(relevant_template_to_subjects.keys())],
                            "campus_id": campus_id,
                        },
                        fields=[
                            "name", "class_id", "template_id", "data_json",
                            "scores_submitted_at", "scores_submitted_by",
                            "scores_rejection_reason", "scores_rejected_by", "scores_rejected_at",
                            "rejected_from_level", "rejected_section",
                        ],
                    )

                    seen_l2s: Set[Tuple[str, str]] = set()
                    for r in reports:
                        tmpl_id = r["template_id"]
                        tmpl = all_templates_map.get(tmpl_id) or {}
                        candidate_subjects = relevant_template_to_subjects.get(tmpl_id, set())

                        try:
                            report_data_json = json.loads(r.get("data_json") or "{}")
                        except (json.JSONDecodeError, TypeError):
                            report_data_json = {}

                        for sid in candidate_subjects:
                            key = (r["name"], sid)
                            if key in seen_l2s:
                                continue

                            # Detect section: scores → subject_eval → intl(main_scores, ielts, comments)
                            subject_approval: Dict[str, Any] = {}
                            found_board_type: Optional[str] = None
                            found_section: Optional[str] = None

                            for board_type_key in ["scores", "subject_eval"]:
                                section_approval = get_subject_approval_from_data_json(
                                    report_data_json, board_type_key, sid
                                )
                                if section_approval.get("status") in ["submitted", "level_1_approved"]:
                                    subject_approval = section_approval
                                    found_board_type = board_type_key
                                    found_section = board_type_key
                                    break

                            if not found_board_type:
                                for intl_board_type in ["main_scores", "ielts", "comments"]:
                                    intl_approval = get_subject_approval_from_data_json(
                                        report_data_json, intl_board_type, sid
                                    )
                                    if intl_approval.get("status") in ["submitted", "level_1_approved"]:
                                        subject_approval = intl_approval
                                        found_board_type = intl_approval.get("board_type", intl_board_type)
                                        found_section = "intl"
                                        break

                            subject_status = subject_approval.get("status", "draft")
                            if subject_status not in ["submitted", "level_1_approved"]:
                                continue

                            seen_l2s.add(key)
                            r_copy = {k: v for k, v in r.items() if k != "data_json"}
                            r_copy["template_title"] = tmpl.get("title")
                            r_copy["pending_level"] = "level_2"
                            r_copy["subject_id"] = sid
                            r_copy["subject_title"] = subject_title_map.get(sid, sid)
                            r_copy["section_type"] = found_section
                            r_copy["board_type"] = found_board_type
                            r_copy["submitted_at"] = (
                                subject_approval.get("submitted_at") or r.get("scores_submitted_at")
                            )
                            r_copy["submitted_by"] = (
                                subject_approval.get("submitted_by") or r.get("scores_submitted_by")
                            )
                            if subject_approval.get("rejection_reason"):
                                r_copy["was_rejected"] = True
                                r_copy["rejection_reason"] = subject_approval.get("rejection_reason")
                                r_copy["rejected_from_level"] = subject_approval.get("rejected_from_level")
                            # Viewer-only nếu subject không thuộc managed của teacher
                            if sid not in teacher_subject_ids:
                                r_copy["is_viewer_only"] = True
                            all_reports.append(r_copy)

        # =========================================================
        # LEVEL 3 & 4
        # =========================================================
        l3_l4_configs_map: Dict[str, Dict[str, Any]] = {}
        if not level or level in ["review", "publish"]:
            l3_l4_configs_map = _bulk_load_approval_configs(campus_id)

            stage_template_map: Dict[str, List[Dict[str, Any]]] = {}
            for tid, t in all_templates_map.items():
                stage = t.get("education_stage")
                if stage:
                    stage_template_map.setdefault(stage, []).append(t)

            for cfg_name, cfg in l3_l4_configs_map.items():
                # ---- L3 ----
                if not level or level == "review":
                    is_l3 = user in cfg["l3_user_set"]
                    if is_l3 or is_manager:
                        templates = stage_template_map.get(cfg["education_stage_id"], [])
                        for tmpl in templates:
                            homeroom_enabled = tmpl.get("homeroom_enabled")
                            scores_enabled = tmpl.get("scores_enabled")
                            subject_eval_enabled = tmpl.get("subject_eval_enabled")

                            if not homeroom_enabled and not scores_enabled and not subject_eval_enabled:
                                continue

                            or_filters = []
                            if homeroom_enabled:
                                or_filters.append(["homeroom_approval_status", "=", "level_2_approved"])
                            if scores_enabled:
                                or_filters.append(["scores_approval_status", "=", "level_2_approved"])
                            if subject_eval_enabled:
                                or_filters.append(["homeroom_l2_approved", "=", 1])

                            if not or_filters:
                                continue

                            reports = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": tmpl["name"],
                                    "campus_id": campus_id,
                                },
                                or_filters=or_filters,
                                fields=[
                                    "name", "class_id", "template_id",
                                    "homeroom_submitted_at", "scores_submitted_at",
                                    "rejection_reason", "rejected_from_level", "rejected_at", "rejected_section",
                                    "homeroom_l2_approved", "all_sections_l2_approved",
                                ],
                            )
                            for r in reports:
                                r["template_title"] = tmpl.get("title")
                                r["pending_level"] = "review"
                                r["subject_id"] = None
                                r["subject_title"] = "Toàn bộ báo cáo"
                                r["submitted_at"] = max(
                                    r.get("homeroom_submitted_at") or "",
                                    r.get("scores_submitted_at") or "",
                                ) or None
                                if r.get("rejected_from_level") == 4:
                                    r["was_rejected"] = True
                                if is_manager and not is_l3:
                                    r["is_viewer_only"] = True
                                r["_config_name"] = cfg["name"]
                                all_reports.append(r)

                # ---- L4 ----
                if not level or level == "publish":
                    is_l4 = user in cfg["l4_user_set"]
                    if is_l4 or is_manager:
                        templates = stage_template_map.get(cfg["education_stage_id"], [])
                        if templates:
                            reports = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": ["in", [t["name"] for t in templates]],
                                    "approval_status": "reviewed",
                                    "campus_id": campus_id,
                                },
                                fields=["name", "class_id", "template_id", "submitted_at", "submitted_by"],
                            )
                            for r in reports:
                                tmpl = all_templates_map.get(r["template_id"]) or {}
                                r["template_title"] = tmpl.get("title")
                                r["pending_level"] = "publish"
                                r["subject_id"] = None
                                r["subject_title"] = "Toàn bộ báo cáo"
                                if is_manager and not is_l4:
                                    r["is_viewer_only"] = True
                                r["_config_name"] = cfg["name"]
                                all_reports.append(r)

        # =========================================================
        # GROUP by (template_id, class_id, subject_id, pending_level)
        # =========================================================
        grouped: Dict[Tuple[str, str, Optional[str], str], Dict[str, Any]] = {}
        for r in all_reports:
            key = (r["template_id"], r["class_id"], r.get("subject_id"), r["pending_level"])
            if key not in grouped:
                grouped[key] = {
                    "template_id": r["template_id"],
                    "template_title": r.get("template_title", ""),
                    "class_id": r["class_id"],
                    "subject_id": r.get("subject_id"),
                    "subject_title": r.get("subject_title", ""),
                    "pending_level": r["pending_level"],
                    "student_count": 0,
                    "submitted_at": r.get("submitted_at"),
                    "submitted_by": r.get("submitted_by"),
                    "rejection_reason": r.get("rejection_reason"),
                    "was_rejected": r.get("was_rejected", False),
                    "rejected_from_level": r.get("rejected_from_level"),
                    "rejected_section": r.get("rejected_section"),
                    "report_ids": set(),
                    "is_viewer_only": r.get("is_viewer_only", False),
                    "_config_name": r.get("_config_name"),
                }
            g = grouped[key]
            if r["name"] not in g["report_ids"]:
                g["report_ids"].add(r["name"])
                g["student_count"] += 1
                if r.get("submitted_at") and (
                    not g["submitted_at"] or r["submitted_at"] > g["submitted_at"]
                ):
                    g["submitted_at"] = r["submitted_at"]
                    g["submitted_by"] = r.get("submitted_by")
                if r.get("rejection_reason"):
                    g["rejection_reason"] = r["rejection_reason"]
                    g["was_rejected"] = True
                    g["rejected_from_level"] = r.get("rejected_from_level")
                    g["rejected_section"] = r.get("rejected_section")
                # Nếu BẤT KỲ report nào KHÔNG phải viewer_only thì group cũng không phải viewer_only
                if not r.get("is_viewer_only", False):
                    g["is_viewer_only"] = False

        # =========================================================
        # VALIDATE orphan (template không tồn tại)
        # =========================================================
        valid_template_ids = set(all_templates_map.keys())
        groups_filtered = [
            g for g in grouped.values()
            if g["template_id"] in valid_template_ids
        ]

        # =========================================================
        # ENRICH (batch)
        # =========================================================

        # Class titles - chỉ cần class_id của các group hợp lệ
        class_ids = list({g["class_id"] for g in groups_filtered if g.get("class_id")})
        class_map: Dict[str, Any] = {}
        if class_ids:
            classes = frappe.get_all(
                "SIS Class",
                filters={"name": ["in", class_ids]},
                fields=["name", "title", "short_title"],
            )
            class_map = {c.name: c for c in classes}

        # Subject managers (cho L2 subject approvers) — chỉ lấy subjects xuất hiện trong groups
        l2_subject_ids = [
            g["subject_id"] for g in groups_filtered
            if g["pending_level"] == "level_2" and g.get("subject_id")
        ]
        subject_manager_map = _bulk_subject_managers(l2_subject_ids) if l2_subject_ids else {}

        # Gom teacher_ids cần resolve names (cho mọi level)
        all_teacher_ids: Set[str] = set()
        for g in groups_filtered:
            tmpl = all_templates_map.get(g["template_id"]) or {}
            pl = g["pending_level"]
            if pl == "level_1":
                all_teacher_ids.update(_parse_reviewer_list(tmpl.get("homeroom_reviewer_level_1")))
            elif pl == "level_2":
                all_teacher_ids.update(_parse_reviewer_list(tmpl.get("homeroom_reviewer_level_2")))
                sid = g.get("subject_id")
                if sid:
                    all_teacher_ids.update(subject_manager_map.get(sid, []))

        for cfg in l3_l4_configs_map.values():
            all_teacher_ids.update(cfg.get("l3_teacher_ids", []))
            all_teacher_ids.update(cfg.get("l4_teacher_ids", []))

        _, teacher_name_map = _bulk_teacher_user_maps(list(all_teacher_ids))

        # Pre-build: stage → config (để map template không có _config_name về config)
        stage_to_cfg: Dict[str, Dict[str, Any]] = {}
        for cfg in l3_l4_configs_map.values():
            stage = cfg.get("education_stage_id")
            if stage and stage not in stage_to_cfg:
                stage_to_cfg[stage] = cfg

        results: List[Dict[str, Any]] = []
        for g in groups_filtered:
            del g["report_ids"]

            c = class_map.get(g["class_id"])
            if c:
                # Logic gốc cho grouped: short_title or title
                g["class_title"] = c.short_title or c.title

            tmpl = all_templates_map.get(g["template_id"]) or {}

            # Resolve config nếu cần
            cfg_data: Optional[Dict[str, Any]] = None
            cfg_name = g.get("_config_name")
            if cfg_name:
                cfg_data = l3_l4_configs_map.get(cfg_name)
            elif g["pending_level"] in ["review", "publish"]:
                stage = tmpl.get("education_stage")
                if stage:
                    cfg_data = stage_to_cfg.get(stage)

            g["approvers"] = _get_approvers_for_level_cached(
                level=g["pending_level"],
                template=tmpl,
                config_data=cfg_data,
                subject_id=g.get("subject_id"),
                teacher_name_map=teacher_name_map,
                subject_manager_map=subject_manager_map,
            )

            if "_config_name" in g:
                del g["_config_name"]

            results.append(g)

        results.sort(key=lambda x: x.get("submitted_at") or "", reverse=True)

        return success_response(
            data={
                "reports": results,
                "total": len(results),
            },
            message=f"Tìm thấy {len(results)} nhóm báo cáo đang chờ duyệt",
        )

    except Exception as e:
        frappe.logger().error(f"Error in get_pending_approvals_grouped: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        return error_response(f"Lỗi khi lấy danh sách chờ duyệt: {str(e)}")
