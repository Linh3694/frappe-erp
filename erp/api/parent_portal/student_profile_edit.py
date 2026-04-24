"""
Parent Portal — Ghi hồ sơ CRM Lead theo dạng batch "commit_profile_changes".

Chỉ phụ huynh đang đăng nhập và là người liên hệ chính (primary contact) của
học sinh mới được phép commit thay đổi. Mọi field ngoài whitelist sẽ bị bỏ qua
âm thầm nhằm tránh leo quyền.

Endpoint duy nhất được expose: ``commit_profile_changes``. Endpoint nhận 1
payload gom toàn bộ thay đổi (lead fields, guardians, phones, learning
history, siblings, set_primary, reorder) và thực thi trong 1 transaction.
"""

from __future__ import annotations

import json
import re
from typing import Any

import frappe

from erp.api.crm.lead import (
    _ordered_guardian_names_for_lead,
    _recalculate_admission_profile_completion,
    build_lead_family_payload,
    enrich_lead_dict_with_sibling_lead_links,
)
from erp.api.crm.utils import get_request_data
from erp.api.parent_portal.student_profile import (
    LEAD_SUBSET_FIELDNAMES,
    _enrich_target_academic_year,
    _get_current_parent,
    _json_safe_value,
    _serialize_crm_student_min,
    _serialize_lead_subset,
)
from erp.utils.api_response import (
    error_response,
    success_response,
    validation_error_response,
)


# ---------------------------------------------------------------------------
# Whitelist field – chỉ các field đang hiển thị ở parent portal
# ---------------------------------------------------------------------------

# Lấy từ LEAD_SUBSET_FIELDNAMES nhưng loại bỏ các field không cho phép sửa ở
# parent portal (liên quan tuyển sinh / mã nghiệp vụ / lớp / năm học / campus).
_NON_EDITABLE_LEAD_FIELDS = {
    "name",
    "step",
    "student_code",
    "current_grade",
    "target_grade",
    "current_school",
    "target_academic_year",
    "target_academic_year_label",
    "target_semester",
    "campus_id",
    "tuition_fee_pct",
    "service_fee_pct",
    "dev_fee_pct",
    "ksdv_pct",
    "linked_student",
    "linked_family",
}

EDITABLE_LEAD_FIELDS: tuple[str, ...] = tuple(
    f for f in LEAD_SUBSET_FIELDNAMES if f not in _NON_EDITABLE_LEAD_FIELDS
)

EDITABLE_GUARDIAN_FIELDS: tuple[str, ...] = (
    "guardian_name",
    "dob",
    "email",
    "id_number",
    "occupation",
    "position",
    "workplace",
    "address",
    "nationality",
    "note",
)

EDITABLE_SIBLING_FIELDS: tuple[str, ...] = (
    "sibling_name",
    "student_code",
    "relationship_type",
    "dob",
    "school",
)

EDITABLE_LEARNING_FIELDS: tuple[str, ...] = (
    "school_name",
    "address",
    "start_month_year",
    "withdraw_month_year",
)

# Giới hạn để tránh payload quá lớn / abuse
_MAX_OPS_PER_BATCH = 400


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_lead_for_current_parent(student_id: str):
    """Xác thực phụ huynh login là primary contact của học sinh.

    Trả về tuple ``(lead_doc, parent_guardian_name, family_payload)`` khi hợp
    lệ, ngược lại trả về ``error_response`` (caller tự kiểm tra).
    """

    if not student_id:
        return None, validation_error_response(
            "Thiếu student_id", {"student_id": ["Bắt buộc"]}
        )

    if not frappe.db.exists("CRM Student", student_id):
        return None, error_response(
            message="Không tìm thấy học sinh", code="STUDENT_NOT_FOUND"
        )

    parent_id = _get_current_parent()
    if not parent_id:
        return None, error_response(
            message="Không tìm thấy thông tin phụ huynh", code="PARENT_NOT_FOUND"
        )

    rel_ok = frappe.db.exists(
        "CRM Family Relationship",
        {"guardian": parent_id, "student": student_id, "access": 1},
    )
    if not rel_ok:
        return None, error_response(
            message="Bạn không có quyền sửa hồ sơ học sinh này",
            code="FORBIDDEN",
        )

    lr = frappe.db.sql(
        """
        SELECT name FROM `tabCRM Lead`
        WHERE linked_student = %s
        ORDER BY modified DESC
        LIMIT 1
        """,
        (student_id,),
    )
    if not lr:
        return None, error_response(
            message="Học sinh chưa có hồ sơ CRM Lead liên kết",
            code="LEAD_NOT_FOUND",
        )

    lead_doc = frappe.get_doc("CRM Lead", lr[0][0])
    family_payload = build_lead_family_payload(lead_doc)
    primary_guardian_name: str | None = None
    for m in family_payload.get("members") or []:
        if m.get("is_primary_contact"):
            primary_guardian_name = (m.get("guardian") or {}).get("name")
            break

    if not primary_guardian_name or primary_guardian_name != parent_id:
        return None, error_response(
            message=(
                "Chỉ người liên lạc chính mới được phép cập nhật hồ sơ."
            ),
            code="NOT_PRIMARY_CONTACT",
        )

    return (lead_doc, parent_id, family_payload), None


def _guardian_ids_of_lead(lead_doc, family_payload: dict) -> set[str]:
    ids: set[str] = set()
    for m in (family_payload.get("members") or []):
        gid = (m.get("guardian") or {}).get("name")
        if gid:
            ids.add(gid)
    for lg in (getattr(lead_doc, "lead_guardians", None) or []):
        gid = lg.get("guardian") if isinstance(lg, dict) else getattr(lg, "guardian", None)
        if gid:
            ids.add(gid)
    return ids


def _sibling_row_names(lead_doc) -> set[str]:
    return {
        r.get("name") if isinstance(r, dict) else getattr(r, "name", None)
        for r in (getattr(lead_doc, "lead_siblings", None) or [])
        if r
    }


def _learning_row_names(lead_doc) -> set[str]:
    return {
        r.get("name") if isinstance(r, dict) else getattr(r, "name", None)
        for r in (getattr(lead_doc, "lead_learning_history", None) or [])
        if r
    }


def _validate_phone_simple(phone: str) -> str | None:
    """Trả về số đã chuẩn hoá hoặc ``None`` nếu không hợp lệ."""
    if not phone:
        return None
    try:
        from erp.api.erp_sis.guardian import validate_vietnamese_phone_number

        return validate_vietnamese_phone_number(phone)
    except Exception:
        return None


_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


# ---------------------------------------------------------------------------
# Appliers – mỗi loại thay đổi có 1 hàm áp vào doc đang load sẵn
# ---------------------------------------------------------------------------


def _apply_lead_fields(
    lead_doc, fields: dict[str, Any], audit_log: list[str]
) -> None:
    if not isinstance(fields, dict):
        return
    changed = 0
    for k, v in fields.items():
        if k not in EDITABLE_LEAD_FIELDS:
            continue
        lead_doc.set(k, v)
        changed += 1
    if changed:
        audit_log.append(f"lead_fields:{changed}")


def _apply_guardian_updates(
    lead_doc,
    guardian_updates: list[dict[str, Any]],
    allowed_guardian_ids: set[str],
    audit_log: list[str],
) -> tuple[bool, dict | None]:
    """Cập nhật thông tin CRM Guardian (và relationship_type nếu có).

    Trả về ``(ok, error_response_dict)``.
    """

    if not isinstance(guardian_updates, list):
        return True, None

    for entry in guardian_updates:
        if not isinstance(entry, dict):
            continue
        gid = (entry.get("guardian_name") or entry.get("guardian") or "").strip()
        if not gid or gid not in allowed_guardian_ids:
            continue
        if not frappe.db.exists("CRM Guardian", gid):
            continue
        fields = entry.get("fields") or {}
        if not isinstance(fields, dict):
            continue

        g_doc = frappe.get_doc("CRM Guardian", gid)
        email_from_request: str | None = None
        touched = False
        for k, v in fields.items():
            if k not in EDITABLE_GUARDIAN_FIELDS:
                continue
            if k == "email":
                email_from_request = str(v or "").strip()
                continue
            g_doc.set(k, v)
            touched = True
        if touched:
            g_doc.flags.ignore_validate = True
            g_doc.save(ignore_permissions=True)
        if email_from_request is not None:
            # Tránh fieldtype Email bị bỏ qua khi save
            frappe.db.set_value("CRM Guardian", gid, "email", email_from_request)

        # Cập nhật relationship_type (cả child table lead_guardians và CRM
        # Family Relationship nếu có linked_family)
        if "relationship_type" in fields:
            relationship_type = fields.get("relationship_type")
            for lg in (getattr(lead_doc, "lead_guardians", None) or []):
                if lg.get("guardian") == gid:
                    lg.relationship_type = relationship_type
            if getattr(lead_doc, "linked_family", None):
                rels = frappe.get_all(
                    "CRM Family Relationship",
                    filters={
                        "parent": lead_doc.linked_family,
                        "guardian": gid,
                    },
                    fields=["name"],
                )
                for r in rels:
                    frappe.db.set_value(
                        "CRM Family Relationship",
                        r["name"],
                        "relationship_type",
                        relationship_type or "",
                    )
        audit_log.append(f"guardian:{gid}")
    return True, None


def _apply_phone_ops(
    lead_doc,
    phones_ops: list[dict[str, Any]],
    allowed_guardian_ids: set[str],
    audit_log: list[str],
) -> tuple[bool, dict | None]:
    if not isinstance(phones_ops, list):
        return True, None

    # Gom theo guardian để tải doc 1 lần cho nhiều thao tác
    by_guardian: dict[str, list[dict[str, Any]]] = {}
    for op in phones_ops:
        if not isinstance(op, dict):
            continue
        gid = (op.get("guardian_name") or op.get("guardian") or "").strip()
        if not gid or gid not in allowed_guardian_ids:
            continue
        by_guardian.setdefault(gid, []).append(op)

    for gid, ops in by_guardian.items():
        if not frappe.db.exists("CRM Guardian", gid):
            continue
        g_doc = frappe.get_doc("CRM Guardian", gid)

        # Migration: nếu phone_numbers rỗng nhưng phone_number cũ còn → nạp
        if (not (getattr(g_doc, "phone_numbers", None) or [])) and getattr(
            g_doc, "phone_number", None
        ):
            g_doc.append(
                "phone_numbers",
                {"phone_number": g_doc.phone_number, "is_primary": 1},
            )

        for op in ops:
            action = (op.get("action") or "").lower()

            if action == "add":
                formatted = _validate_phone_simple(op.get("phone_number"))
                if not formatted:
                    return False, validation_error_response(
                        "Số điện thoại không hợp lệ",
                        {"phone_number": ["Không hợp lệ"]},
                    )
                rows = getattr(g_doc, "phone_numbers", None) or []
                dup_in = any(
                    (r.get("phone_number") or "").replace(" ", "")
                    == formatted.replace(" ", "")
                    for r in rows
                )
                if dup_in:
                    return False, validation_error_response(
                        f"Số '{formatted}' đã tồn tại",
                        {"phone_number": ["Trùng"]},
                    )
                dup_other = frappe.db.sql(
                    "SELECT 1 FROM `tabCRM Guardian Phone` "
                    "WHERE phone_number=%s AND parent!=%s LIMIT 1",
                    (formatted, gid),
                )
                if dup_other:
                    return False, validation_error_response(
                        f"Số '{formatted}' đã được dùng bởi phụ huynh khác",
                        {"phone_number": ["Trùng"]},
                    )
                is_first = len(rows) == 0
                g_doc.append(
                    "phone_numbers",
                    {
                        "phone_number": formatted,
                        "is_primary": 1 if is_first else 0,
                    },
                )
                audit_log.append(f"phone_add:{gid}")

            elif action == "remove":
                row_name = (
                    op.get("phone_row")
                    or op.get("phone_row_name")
                    or op.get("name")
                )
                if not row_name:
                    continue
                rows = list(getattr(g_doc, "phone_numbers", None) or [])
                target = next(
                    (r for r in rows if r.get("name") == row_name), None
                )
                if target is None:
                    continue
                was_primary = target.get("is_primary")
                g_doc.remove(target)
                if was_primary and g_doc.phone_numbers:
                    g_doc.phone_numbers[0].is_primary = 1
                audit_log.append(f"phone_remove:{gid}")

            elif action in ("set_primary", "set_primary_phone"):
                row_name = (
                    op.get("phone_row")
                    or op.get("phone_row_name")
                    or op.get("name")
                )
                if not row_name:
                    continue
                for r in (getattr(g_doc, "phone_numbers", None) or []):
                    r.is_primary = 1 if r.get("name") == row_name else 0
                audit_log.append(f"phone_primary:{gid}")

        g_doc.flags.ignore_validate = True
        g_doc.save(ignore_permissions=True)

    return True, None


def _apply_learning_ops(
    lead_doc,
    learning_ops: list[dict[str, Any]],
    audit_log: list[str],
) -> tuple[bool, dict | None]:
    if not isinstance(learning_ops, list):
        return True, None
    existing_rows = _learning_row_names(lead_doc)
    for op in learning_ops:
        if not isinstance(op, dict):
            continue
        action = (op.get("action") or "").lower()
        if action == "add":
            data = op.get("data") or {}
            lead_doc.append(
                "lead_learning_history",
                {
                    k: data.get(k, "")
                    for k in EDITABLE_LEARNING_FIELDS
                },
            )
            audit_log.append("learning_add")
        elif action == "update":
            row_name = op.get("row") or op.get("row_name") or op.get("name")
            if not row_name or row_name not in existing_rows:
                continue
            fields = op.get("fields") or {}
            for r in (getattr(lead_doc, "lead_learning_history", None) or []):
                if r.get("name") == row_name:
                    for k, v in fields.items():
                        if k in EDITABLE_LEARNING_FIELDS:
                            r.set(k, v or "")
                    break
            audit_log.append(f"learning_update:{row_name}")
        elif action == "remove":
            row_name = op.get("row") or op.get("row_name") or op.get("name")
            if not row_name:
                continue
            new_items = [
                r
                for r in (getattr(lead_doc, "lead_learning_history", None) or [])
                if r.get("name") != row_name
            ]
            lead_doc.set("lead_learning_history", new_items)
            audit_log.append(f"learning_remove:{row_name}")
    return True, None


def _apply_sibling_ops(
    lead_doc,
    sibling_ops: list[dict[str, Any]],
    audit_log: list[str],
) -> tuple[bool, dict | None]:
    if not isinstance(sibling_ops, list):
        return True, None
    existing_rows = _sibling_row_names(lead_doc)
    for op in sibling_ops:
        if not isinstance(op, dict):
            continue
        action = (op.get("action") or "").lower()
        if action == "add":
            data = op.get("data") or {}
            sibling_name = (data.get("sibling_name") or "").strip()
            if not sibling_name:
                return False, validation_error_response(
                    "Thiếu họ tên anh/chị/em",
                    {"sibling_name": ["Bắt buộc"]},
                )
            lead_doc.append(
                "lead_siblings",
                {
                    k: data.get(k, "") if k != "dob" else data.get("dob")
                    for k in EDITABLE_SIBLING_FIELDS
                },
            )
            audit_log.append("sibling_add")
        elif action == "update":
            row_name = op.get("row") or op.get("row_name") or op.get("name")
            if not row_name or row_name not in existing_rows:
                continue
            fields = op.get("fields") or {}
            for r in (getattr(lead_doc, "lead_siblings", None) or []):
                if r.get("name") == row_name:
                    for k, v in fields.items():
                        if k in EDITABLE_SIBLING_FIELDS:
                            r.set(k, v)
                    break
            audit_log.append(f"sibling_update:{row_name}")
        elif action == "remove":
            row_name = op.get("row") or op.get("row_name") or op.get("name")
            if not row_name:
                continue
            new_items = [
                r
                for r in (getattr(lead_doc, "lead_siblings", None) or [])
                if r.get("name") != row_name
            ]
            lead_doc.set("lead_siblings", new_items)
            audit_log.append(f"sibling_remove:{row_name}")
    return True, None


def _apply_set_primary_contact(
    lead_doc,
    guardian_name: str,
    allowed_guardian_ids: set[str],
    audit_log: list[str],
) -> tuple[bool, dict | None]:
    if not guardian_name or guardian_name not in allowed_guardian_ids:
        return True, None
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return True, None

    for lg in (getattr(lead_doc, "lead_guardians", None) or []):
        lg.is_primary_contact = 1 if lg.get("guardian") == guardian_name else 0

    if getattr(lead_doc, "linked_family", None):
        frappe.db.sql(
            "UPDATE `tabCRM Family Relationship` SET key_person=0 WHERE parent=%s",
            (lead_doc.linked_family,),
        )
        frappe.db.sql(
            "UPDATE `tabCRM Family Relationship` SET key_person=1 "
            "WHERE parent=%s AND guardian=%s",
            (lead_doc.linked_family, guardian_name),
        )
        # Sync CRM Student.family_relationships
        if lead_doc.linked_student:
            student_doc = frappe.get_doc("CRM Student", lead_doc.linked_student)
            student_doc.set("family_relationships", [])
            for rel in frappe.get_all(
                "CRM Family Relationship",
                filters={
                    "parent": lead_doc.linked_family,
                    "student": lead_doc.linked_student,
                },
                fields=[
                    "student",
                    "guardian",
                    "relationship_type",
                    "key_person",
                    "access",
                ],
            ):
                student_doc.append("family_relationships", rel)
            student_doc.flags.ignore_validate = True
            student_doc.save(ignore_permissions=True)

    # Sync flat fields về Lead
    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    lead_doc.guardian_name = g_doc.guardian_name
    lead_doc.guardian_email = g_doc.email or ""
    lead_doc.guardian_id_number = getattr(g_doc, "id_number", None) or ""
    lead_doc.relationship = ""
    for lg in (getattr(lead_doc, "lead_guardians", None) or []):
        if lg.get("guardian") == guardian_name:
            lead_doc.relationship = lg.get("relationship_type", "")
            break
    if getattr(lead_doc, "linked_family", None):
        rel = frappe.db.get_value(
            "CRM Family Relationship",
            {"parent": lead_doc.linked_family, "guardian": guardian_name},
            "relationship_type",
        )
        if rel:
            lead_doc.relationship = rel
    lead_doc.guardian_occupation = getattr(g_doc, "occupation", None) or ""
    lead_doc.guardian_position = getattr(g_doc, "position", None) or ""
    lead_doc.guardian_workplace = getattr(g_doc, "workplace", None) or ""
    lead_doc.guardian_address = getattr(g_doc, "address", None) or ""
    lead_doc.guardian_nationality = getattr(g_doc, "nationality", None) or ""
    lead_doc.guardian_note = getattr(g_doc, "note", None) or ""
    lead_doc.guardian_dob = getattr(g_doc, "dob", None)
    audit_log.append(f"primary_contact:{guardian_name}")
    return True, None


def _apply_reorder_guardians(
    lead_doc,
    order: list[str],
    audit_log: list[str],
) -> tuple[bool, dict | None]:
    if not isinstance(order, list) or not order:
        return True, None

    expected = _ordered_guardian_names_for_lead(lead_doc)
    if expected is None or len(expected) < 2:
        # Không hỗ trợ ở chế độ thông tin phẳng / chỉ có 1 guardian
        return True, None

    order = [str(x) for x in order]
    if set(order) != set(expected) or len(order) != len(expected):
        return False, validation_error_response(
            "Danh sách thứ tự không khớp với phụ huynh trong hồ sơ",
            {"order": ["Không hợp lệ"]},
        )
    if order[0] != expected[0]:
        return False, validation_error_response(
            "Người liên lạc chính phải ở vị trí đầu tiên",
            {"order": ["Primary phải đứng đầu"]},
        )

    if getattr(lead_doc, "linked_family", None):
        stud = getattr(lead_doc, "linked_student", None)
        if not stud:
            return False, validation_error_response(
                "Cần linked_student để sắp xếp thứ tự",
                {"linked_student": ["Bắt buộc"]},
            )
        for i, gid in enumerate(order):
            row_name = frappe.db.get_value(
                "CRM Family Relationship",
                {
                    "parent": lead_doc.linked_family,
                    "student": stud,
                    "guardian": gid,
                },
                "name",
            )
            if not row_name:
                return False, validation_error_response(
                    f"Không tìm thấy quan hệ gia đình cho phụ huynh {gid}",
                    {"order": ["Thiếu relationship"]},
                )
            frappe.db.set_value(
                "CRM Family Relationship", row_name, "display_order", i
            )
    else:
        for i, gid in enumerate(order):
            for lg in lead_doc.lead_guardians:
                if lg.get("guardian") == gid:
                    lg.display_order = i
    audit_log.append(f"reorder:{len(order)}")
    return True, None


# ---------------------------------------------------------------------------
# Public endpoint
# ---------------------------------------------------------------------------


def _count_ops(changes: dict[str, Any]) -> int:
    """Đếm sơ bộ số thao tác trong batch để kiểm soát kích thước payload."""

    n = 0
    n += len((changes.get("lead") or {}) if isinstance(changes.get("lead"), dict) else {})
    for key in ("guardians", "phones", "learning_history", "siblings"):
        val = changes.get(key)
        if isinstance(val, list):
            n += len(val)
    if changes.get("set_primary_contact"):
        n += 1
    order = changes.get("guardians_order")
    if isinstance(order, list) and order:
        n += 1
    return n


def _build_refresh_payload(student_id: str) -> dict[str, Any]:
    """Dựng lại payload giống ``student_profile.get_student_profile``.

    Tránh phụ thuộc HTTP handler, dùng sau khi commit xong để trả cho FE.
    """

    lr = frappe.db.sql(
        """
        SELECT name FROM `tabCRM Lead`
        WHERE linked_student = %s
        ORDER BY modified DESC
        LIMIT 1
        """,
        (student_id,),
    )
    if not lr:
        return {
            "has_lead": False,
            "lead": None,
            "family": None,
            "siblings": [],
            "learning_history": [],
            "promotions": [],
            "student": _serialize_crm_student_min(student_id),
        }

    lead_name = lr[0][0]
    doc = frappe.get_doc("CRM Lead", lead_name)
    lead_dict = _serialize_lead_subset(doc)
    _enrich_target_academic_year(lead_dict)

    learning_history = []
    for r in doc.get("lead_learning_history") or []:
        learning_history.append(
            {
                "name": r.get("name"),
                "school_name": r.get("school_name"),
                "address": r.get("address"),
                "start_month_year": r.get("start_month_year"),
                "withdraw_month_year": r.get("withdraw_month_year"),
            }
        )

    lead_for_siblings = doc.as_dict()
    enrich_lead_dict_with_sibling_lead_links(lead_for_siblings)
    siblings = lead_for_siblings.get("lead_siblings") or []
    for s in siblings:
        if not isinstance(s, dict):
            continue
        for k, v in list(s.items()):
            s[k] = _json_safe_value(v)

    fam_payload = build_lead_family_payload(doc)

    return {
        "has_lead": True,
        "lead": lead_dict,
        "family": {
            "members": fam_payload.get("members") or [],
            "family_code": fam_payload.get("family_code"),
            "linked_family": fam_payload.get("linked_family"),
        },
        "siblings": siblings,
        "learning_history": learning_history,
        "promotions": [],
        "student": _serialize_crm_student_min(student_id),
    }


@frappe.whitelist(methods=["POST"])
def commit_profile_changes():
    """Nhận 1 batch thay đổi từ parent portal và apply trong 1 transaction.

    Payload:
        ``student_id``: tên document CRM Student.
        ``changes``: dict/JSON string theo schema mô tả trong plan.

    Thành công trả lại payload giống ``get_student_profile`` để FE swap cache.
    """

    data = get_request_data() or {}
    student_id = (data.get("student_id") or "").strip()

    raw_changes = data.get("changes")
    if isinstance(raw_changes, str):
        try:
            changes = json.loads(raw_changes)
        except Exception:
            return validation_error_response(
                "Payload changes không hợp lệ", {"changes": ["JSON không hợp lệ"]}
            )
    else:
        changes = raw_changes or {}

    if not isinstance(changes, dict):
        return validation_error_response(
            "Payload changes không hợp lệ", {"changes": ["Phải là object"]}
        )

    if _count_ops(changes) == 0:
        return validation_error_response(
            "Không có thay đổi nào để lưu", {"changes": ["Rỗng"]}
        )
    if _count_ops(changes) > _MAX_OPS_PER_BATCH:
        return validation_error_response(
            "Batch quá lớn, vui lòng chia nhỏ",
            {"changes": [f"Vượt quá {_MAX_OPS_PER_BATCH} thao tác"]},
        )

    resolved, err = _resolve_lead_for_current_parent(student_id)
    if err:
        return err
    lead_doc, parent_id, family_payload = resolved

    audit_log: list[str] = []
    allowed_guardian_ids = _guardian_ids_of_lead(lead_doc, family_payload)

    try:
        # 1. Cập nhật field trên chính CRM Lead
        if isinstance(changes.get("lead"), dict):
            _apply_lead_fields(lead_doc, changes["lead"], audit_log)

        # 2. Cập nhật guardian (và relationship_type)
        ok, err = _apply_guardian_updates(
            lead_doc,
            changes.get("guardians") or [],
            allowed_guardian_ids,
            audit_log,
        )
        if not ok:
            raise _CommitFailure(err)

        # 3. Thao tác số điện thoại
        ok, err = _apply_phone_ops(
            lead_doc,
            changes.get("phones") or [],
            allowed_guardian_ids,
            audit_log,
        )
        if not ok:
            raise _CommitFailure(err)

        # 4. Learning history
        ok, err = _apply_learning_ops(
            lead_doc, changes.get("learning_history") or [], audit_log
        )
        if not ok:
            raise _CommitFailure(err)

        # 5. Siblings
        ok, err = _apply_sibling_ops(
            lead_doc, changes.get("siblings") or [], audit_log
        )
        if not ok:
            raise _CommitFailure(err)

        # 6. Primary contact (làm trước reorder để expected order khớp)
        primary_target = (changes.get("set_primary_contact") or "").strip()
        if primary_target:
            ok, err = _apply_set_primary_contact(
                lead_doc, primary_target, allowed_guardian_ids, audit_log
            )
            if not ok:
                raise _CommitFailure(err)

        # 7. Reorder guardians
        order = changes.get("guardians_order")
        if order:
            ok, err = _apply_reorder_guardians(lead_doc, order, audit_log)
            if not ok:
                raise _CommitFailure(err)

        # 8. Hoàn tất: tính completion + save doc lead
        _recalculate_admission_profile_completion(lead_doc)
        lead_doc.flags.ignore_validate = True
        lead_doc.save(ignore_permissions=True)

        frappe.db.commit()

    except _CommitFailure as f:
        frappe.db.rollback()
        return f.payload
    except Exception as e:  # pragma: no cover - log + trả lỗi chung
        frappe.db.rollback()
        frappe.log_error(
            title="parent_portal.commit_profile_changes",
            message=f"student_id={student_id} parent={parent_id} err={e}",
        )
        return error_response(
            message="Không thể lưu thay đổi, vui lòng thử lại",
            code="COMMIT_FAILED",
        )

    # Audit log (info). Không dùng log_error để không spam console lỗi.
    try:
        frappe.logger("parent_portal_profile_edit").info(
            {
                "event": "commit_profile_changes",
                "student_id": student_id,
                "parent_guardian": parent_id,
                "lead": lead_doc.name,
                "ops": audit_log,
            }
        )
    except Exception:
        pass

    payload = _build_refresh_payload(student_id)
    return success_response(data=payload, message="Cập nhật hồ sơ thành công")


class _CommitFailure(Exception):
    """Thoát sớm khỏi transaction, mang theo response đã chuẩn bị."""

    def __init__(self, payload: dict | None):
        super().__init__("commit_failure")
        self.payload = payload or error_response(
            message="Lỗi không xác định", code="COMMIT_FAILED"
        )
