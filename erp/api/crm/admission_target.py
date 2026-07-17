# -*- coding: utf-8 -*-
"""
API Mục tiêu nhập học (KPI) — CRM Admission Target.
Cấu hình target theo Campus × Năm học: khối lớp + thành viên (PIC).
"""

from typing import Any, Dict, List, Optional

import frappe
from erp.utils.api_response import (
    error_response,
    single_item_response,
    success_response,
    validation_error_response,
)
from erp.api.crm.utils import check_crm_permission, get_request_data

# Doi cua thanh vien target — khop options field `team` cua CRM Admission Target Member
# va tham so `team` cua get_kpi_overview.
_TARGET_TEAMS = ("sales", "care")

# Vai trò được phép cấu hình mục tiêu
CONFIG_ROLES = [
    "System Manager",
    "SIS Manager",
    "SIS Sales Admin",
]

VALID_GRADES = [str(i) for i in range(1, 13)]


def _check_target_config_permission():
    """Chỉ admin tuyển sinh mới được lưu cấu hình mục tiêu."""
    user_roles = frappe.get_roles(frappe.session.user)
    if not any(r in user_roles for r in CONFIG_ROLES):
        frappe.throw("Không có quyền cấu hình mục tiêu nhập học", frappe.PermissionError)


def _find_target_name(campus_id: str, target_academic_year: str) -> Optional[str]:
    """Tìm bản ghi CRM Admission Target theo cặp campus + năm học."""
    rows = frappe.get_all(
        "CRM Admission Target",
        filters={
            "campus_id": campus_id,
            "target_academic_year": target_academic_year,
        },
        pluck="name",
        limit=1,
    )
    return rows[0] if rows else None


def _normalize_grade_rows(rows: Any) -> List[Dict[str, Any]]:
    """Chuẩn hóa dòng target theo khối từ payload JSON."""
    if not rows or not isinstance(rows, (list, tuple)):
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        grade = str(r.get("target_grade") or "").strip()
        if grade not in VALID_GRADES:
            continue
        target = int(r.get("enrollment_target") or 0)
        if target < 0:
            target = 0
        row: Dict[str, Any] = {"target_grade": grade, "enrollment_target": target}
        if r.get("name"):
            row["name"] = r["name"]
        out.append(row)
    return out


def _resolve_pic_user(pic_hint: str) -> Optional[str]:
    """Map email / username / User.name → User.name (Link field PIC)."""
    key = (pic_hint or "").strip()
    if not key:
        return None
    if frappe.db.exists("User", key):
        return key
    for field in ("email", "username", "full_name"):
        uid = frappe.db.get_value("User", {field: key}, "name")
        if uid:
            return uid
    return None


def _non_negative_int(value: Any) -> int:
    """Ép về Int không âm — dùng chung cho mọi chỉ tiêu KPI."""
    n = int(value or 0)
    return n if n > 0 else 0


def _normalize_member_rows(rows: Any) -> List[Dict[str, Any]]:
    """Chuẩn hóa dòng target theo PIC từ payload JSON — 3 chỉ tiêu: Lead / Tiềm năng / Chính thức."""
    if not rows or not isinstance(rows, (list, tuple)):
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        pic = _resolve_pic_user(r.get("pic") or "")
        if not pic:
            continue
        team = (r.get("team") or "").strip().lower()
        row: Dict[str, Any] = {
            "pic": pic,
            # Doi cua thanh vien — quyet dinh moi chi tieu thuoc bang KPI nao (1.3).
            "team": team if team in _TARGET_TEAMS else "sales",
            "enrollment_target": _non_negative_int(r.get("enrollment_target")),
            "lead_target": _non_negative_int(r.get("lead_target")),
            "qlead_target": _non_negative_int(r.get("qlead_target")),
        }
        if r.get("name"):
            row["name"] = r["name"]
        out.append(row)
    return out


def _serialize_target_doc(doc) -> Dict[str, Any]:
    """Chuyển doc CRM Admission Target sang dict cho frontend."""
    d = doc.as_dict()
    pic_emails = [r.pic for r in doc.member_targets or [] if r.pic]
    user_map = {}
    if pic_emails:
        for u in frappe.get_all(
            "User",
            filters={"name": ["in", pic_emails]},
            fields=["name", "full_name"],
        ):
            user_map[u.name] = u.full_name or u.name

    grade_targets = [
        {
            "name": r.name,
            "target_grade": r.target_grade,
            "enrollment_target": int(r.enrollment_target or 0),
        }
        for r in doc.grade_targets or []
    ]
    member_targets = [
        {
            "name": r.name,
            "pic": r.pic,
            "pic_name": user_map.get(r.pic, r.pic),
            "team": r.team or "sales",
            "enrollment_target": int(r.enrollment_target or 0),
            "lead_target": int(r.lead_target or 0),
            "qlead_target": int(r.qlead_target or 0),
        }
        for r in doc.member_targets or []
    ]
    return {
        "name": d.get("name"),
        "campus_id": d.get("campus_id"),
        "target_academic_year": d.get("target_academic_year"),
        "total_enrollment_target": int(d.get("total_enrollment_target") or 0),
        "total_profile_target": int(d.get("total_profile_target") or 0),
        "total_lead_target": int(d.get("total_lead_target") or 0),
        "total_qlead_target": int(d.get("total_qlead_target") or 0),
        "total_lost_target": int(d.get("total_lost_target") or 0),
        "total_existing_target": int(d.get("total_existing_target") or 0),
        "notes": d.get("notes") or "",
        "grade_targets": grade_targets,
        "member_targets": member_targets,
    }


def _empty_config(campus_id: str, target_academic_year: str) -> Dict[str, Any]:
    """Cấu hình rỗng khi chưa có bản ghi."""
    return {
        "name": None,
        "campus_id": campus_id,
        "target_academic_year": target_academic_year,
        "total_enrollment_target": 0,
        "total_profile_target": 0,
        "total_lead_target": 0,
        "total_qlead_target": 0,
        "total_lost_target": 0,
        "total_existing_target": 0,
        "notes": "",
        "grade_targets": [],
        "member_targets": [],
    }


@frappe.whitelist()
def get_target_config():
    """Lấy cấu hình mục tiêu theo campus + năm học."""
    check_crm_permission()
    args = frappe.request.args or {}
    campus_id = (args.get("campus_id") or "").strip()
    target_academic_year = (args.get("target_academic_year") or "").strip()

    if not campus_id or not target_academic_year:
        return validation_error_response(
            "Thiếu campus_id hoặc target_academic_year",
            {"campus_id": ["Bắt buộc"], "target_academic_year": ["Bắt buộc"]},
        )

    name = _find_target_name(campus_id, target_academic_year)
    if not name:
        return single_item_response(_empty_config(campus_id, target_academic_year))

    doc = frappe.get_doc("CRM Admission Target", name)
    return single_item_response(_serialize_target_doc(doc))


@frappe.whitelist(methods=["POST"])
def save_target_config():
    """Lưu (upsert) cấu hình mục tiêu theo campus + năm học."""
    _check_target_config_permission()
    data = get_request_data()

    campus_id = (data.get("campus_id") or "").strip()
    target_academic_year = (data.get("target_academic_year") or "").strip()
    if not campus_id or not target_academic_year:
        return validation_error_response(
            "Thiếu campus_id hoặc target_academic_year",
            {"campus_id": ["Bắt buộc"], "target_academic_year": ["Bắt buộc"]},
        )

    if not frappe.db.exists("SIS Campus", campus_id):
        return validation_error_response("Campus không hợp lệ", {"campus_id": ["Không tồn tại"]})
    if not frappe.db.exists("SIS School Year", target_academic_year):
        return validation_error_response(
            "Năm học không hợp lệ", {"target_academic_year": ["Không tồn tại"]}
        )

    grade_rows = _normalize_grade_rows(data.get("grade_targets"))
    member_rows = _normalize_member_rows(data.get("member_targets"))
    notes = data.get("notes")

    try:
        name = _find_target_name(campus_id, target_academic_year)
        if name:
            doc = frappe.get_doc("CRM Admission Target", name)
        else:
            doc = frappe.new_doc("CRM Admission Target")
            doc.campus_id = campus_id
            doc.target_academic_year = target_academic_year

        doc.notes = notes if notes is not None else doc.notes
        # Mục tiêu tổng theo chỉ số — nhập tay ở cấp phòng ban (không chia theo khối)
        for field in ("total_profile_target", "total_lead_target", "total_qlead_target", "total_lost_target", "total_existing_target"):
            if field in data:
                doc.set(field, _non_negative_int(data.get(field)))
        # doc.set() để Frappe ghi đè child table đúng khi cập nhật bản ghi cũ
        doc.set("grade_targets", [])
        for row in grade_rows:
            doc.append("grade_targets", row)
        doc.set("member_targets", [])
        for row in member_rows:
            doc.append("member_targets", row)

        if name:
            doc.save(ignore_permissions=True)
        else:
            doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_serialize_target_doc(doc), "Lưu mục tiêu thành công")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return validation_error_response(str(e))
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi lưu mục tiêu: {str(e)}")


@frappe.whitelist()
def list_target_years():
    """Danh sách năm học đã có cấu hình mục tiêu theo campus."""
    check_crm_permission()
    campus_id = (frappe.request.args.get("campus_id") or "").strip()
    filters = {}
    if campus_id:
        filters["campus_id"] = campus_id

    rows = frappe.get_all(
        "CRM Admission Target",
        filters=filters or None,
        fields=["name", "campus_id", "target_academic_year", "total_enrollment_target", "modified"],
        order_by="modified desc",
    )
    return success_response(rows)
