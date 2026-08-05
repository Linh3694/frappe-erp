"""API quản trị Nhóm quyền vào FaceID (Access Group) cho admin web."""

from __future__ import annotations

import json

import frappe
from frappe.utils import cint, now

from erp.api.faceid.access_engine import (
    ALLDAY_SIGNATURE,
    EngineContext,
    compute_person_desired,
    gc_device_slots,
    group_member_names,
    preview_group,
    refresh_group,
    refresh_persons,
)

PICKUP_GROUP_KEY = "pickup_guardians"


def _ok(data=None, message="OK"):
    return {"success": True, "message": message, "data": data}


def _err(message, data=None):
    return {"success": False, "message": message, "data": data}


def _payload(data) -> dict:
    if isinstance(data, str):
        return json.loads(data)
    return data or {}


# ------------------------------------------------------------------ nhóm


@frappe.whitelist()
def list_access_groups(campus_id=None, include_system=1):
    filters = {}
    if campus_id:
        filters["campus_id"] = campus_id
    if not cint(include_system):
        filters["managed_by"] = "admin"

    rows = frappe.get_all(
        "FaceID Access Group",
        filters=filters,
        fields=[
            "name",
            "group_name",
            "campus_id",
            "is_active",
            "managed_by",
            "system_key",
            "shift_in",
            "shift_out",
            "valid_from",
            "valid_to",
            "member_count",
            "last_applied_at",
        ],
        order_by="managed_by asc, group_name asc",
        limit=500,
    )
    for row in rows:
        row["devices"] = frappe.get_all(
            "FaceID Access Group Device",
            filters={"parent": row["name"], "parenttype": "FaceID Access Group"},
            pluck="device",
        )
        row["actual_member_count"] = frappe.db.count(
            "FaceID Access Group Member", {"group": row["name"]}
        )
    return _ok(rows)


@frappe.whitelist()
def get_access_group(name):
    doc = frappe.get_doc("FaceID Access Group", name)
    data = doc.as_dict()
    data["devices"] = [row.device for row in doc.devices or []]
    data["actual_member_count"] = frappe.db.count(
        "FaceID Access Group Member", {"group": doc.name}
    )
    return _ok(data)


@frappe.whitelist()
def save_access_group(data):
    payload = _payload(data)
    name = payload.get("name")
    if name and frappe.db.exists("FaceID Access Group", name):
        doc = frappe.get_doc("FaceID Access Group", name)
    else:
        doc = frappe.new_doc("FaceID Access Group")

    if doc.get("managed_by") == "system":
        # Nhóm hệ thống: chỉ cho sửa ca và hiệu lực, máy/thành viên do engine dựng
        for field in ("shift_in", "shift_out", "valid_from", "valid_to", "is_active"):
            if field in payload:
                doc.set(field, payload.get(field))
    else:
        for field in (
            "group_name",
            "campus_id",
            "is_active",
            "shift_in",
            "shift_out",
            "valid_from",
            "valid_to",
            "note",
        ):
            if field in payload:
                doc.set(field, payload.get(field))
        doc.set("devices", [])
        for device in payload.get("devices") or []:
            doc.append("devices", {"device": device})

    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return _ok({"name": doc.name}, "Đã lưu nhóm")


@frappe.whitelist()
def delete_access_group(name):
    doc = frappe.get_doc("FaceID Access Group", name)
    if doc.managed_by == "system":
        return _err("Không xóa được nhóm hệ thống")
    members = group_member_names(name)
    frappe.delete_doc("FaceID Access Group", name, ignore_permissions=True)
    frappe.db.commit()
    # Thành viên cũ mất nhóm → tính lại để gỡ khỏi máy nếu không còn nhóm nào
    if members:
        frappe.enqueue(
            "erp.api.faceid.access_engine.refresh_persons",
            queue="long",
            timeout=3600,
            person_names=members,
        )
    return _ok({"members_affected": len(members)}, "Đã xóa nhóm")


# ------------------------------------------------------------- thành viên


@frappe.whitelist()
def list_group_members(group, search=None, limit=200, offset=0):
    conditions = ["m.group = %(group)s"]
    params = {"group": group, "limit": cint(limit), "offset": cint(offset)}
    if search:
        conditions.append("(p.display_name LIKE %(search)s OR p.external_code LIKE %(search)s)")
        params["search"] = f"%{search}%"

    where = " AND ".join(conditions)
    rows = frappe.db.sql(
        f"""
        SELECT m.name, m.person, m.origin, m.valid_from, m.valid_to,
               p.display_name, p.external_code, p.person_type, p.is_active
        FROM `tabFaceID Access Group Member` m
        INNER JOIN `tabFaceID Person` p ON p.name = m.person
        WHERE {where}
        ORDER BY p.display_name
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        params,
        as_dict=True,
    )
    total = frappe.db.count("FaceID Access Group Member", {"group": group})
    return _ok({"members": rows, "total": total})


@frappe.whitelist()
def add_group_members(group, persons, origin="manual"):
    """Thêm hàng loạt person vào nhóm rồi tính lại desired state cho họ."""
    if not frappe.db.exists("FaceID Access Group", group):
        return _err("Nhóm không tồn tại")
    names = _payload(persons) if isinstance(persons, str) else persons
    if not isinstance(names, list):
        return _err("Danh sách person không hợp lệ")

    existing = set(
        frappe.get_all(
            "FaceID Access Group Member", filters={"group": group}, pluck="person"
        )
    )
    added: list[str] = []
    for person in names:
        if person in existing or not frappe.db.exists("FaceID Person", person):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "FaceID Access Group Member",
                "group": group,
                "person": person,
                "origin": origin,
            }
        )
        doc.flags.faceid_skip_refresh = True  # gom lại refresh 1 lượt bên dưới
        doc.insert(ignore_permissions=True)
        added.append(person)

    frappe.db.set_value(
        "FaceID Access Group",
        group,
        "member_count",
        frappe.db.count("FaceID Access Group Member", {"group": group}),
        update_modified=False,
    )
    frappe.db.commit()

    if added:
        frappe.enqueue(
            "erp.api.faceid.access_engine.refresh_persons",
            queue="long",
            timeout=3600,
            person_names=added,
        )
    return _ok({"added": len(added), "skipped": len(names) - len(added)}, "Đã thêm thành viên")


@frappe.whitelist()
def remove_group_members(group, persons):
    names = _payload(persons) if isinstance(persons, str) else persons
    if not isinstance(names, list):
        return _err("Danh sách person không hợp lệ")

    removed: list[str] = []
    for person in names:
        member = frappe.db.get_value(
            "FaceID Access Group Member", {"group": group, "person": person}, "name"
        )
        if not member:
            continue
        doc = frappe.get_doc("FaceID Access Group Member", member)
        doc.flags.faceid_skip_refresh = True
        doc.delete(ignore_permissions=True)
        removed.append(person)

    frappe.db.set_value(
        "FaceID Access Group",
        group,
        "member_count",
        frappe.db.count("FaceID Access Group Member", {"group": group}),
        update_modified=False,
    )
    frappe.db.commit()

    if removed:
        frappe.enqueue(
            "erp.api.faceid.access_engine.refresh_persons",
            queue="long",
            timeout=3600,
            person_names=removed,
        )
    return _ok({"removed": len(removed)}, "Đã gỡ thành viên")


# ------------------------------------------------------------ áp dụng


@frappe.whitelist()
def preview_group_apply(group):
    """Diff dự kiến trước khi áp — không ghi gì xuống DB/máy."""
    return _ok(preview_group(group))


@frappe.whitelist()
def apply_group(group):
    result = refresh_group(group)
    frappe.db.commit()
    return _ok(result, "Đã xếp hàng đồng bộ nhóm")


@frappe.whitelist()
def apply_persons(persons):
    names = _payload(persons) if isinstance(persons, str) else persons
    if not isinstance(names, list):
        return _err("Danh sách person không hợp lệ")
    return _ok(refresh_persons(names), "Đã xếp hàng đồng bộ")


@frappe.whitelist()
def reclaim_device_slots(device=None):
    return _ok({"removed": gc_device_slots(device)}, "Đã thu hồi slot không dùng")


# ------------------------------------------------- ma trận person × máy


@frappe.whitelist()
def list_person_assignments(person=None, device=None, state=None, limit=200, offset=0):
    conditions = []
    params = {"limit": cint(limit), "offset": cint(offset)}
    if person:
        conditions.append("a.person = %(person)s")
        params["person"] = person
    if device:
        conditions.append("a.device = %(device)s")
        params["device"] = device
    if state:
        conditions.append("a.state = %(state)s")
        params["state"] = state
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = frappe.db.sql(
        f"""
        SELECT a.name, a.person, a.device, a.slot, a.schedule_signature, a.state,
               a.valid_from, a.valid_to, a.source_groups, a.last_applied_at, a.last_error,
               p.display_name, p.external_code, p.person_type,
               d.device_name, d.ip, d.direction, d.gate_no
        FROM `tabFaceID Person Device Assignment` a
        INNER JOIN `tabFaceID Person` p ON p.name = a.person
        INNER JOIN `tabFaceID Device` d ON d.name = a.device
        {where}
        ORDER BY p.display_name, d.device_name
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        params,
        as_dict=True,
    )
    total = frappe.db.count(
        "FaceID Person Device Assignment",
        {k: v for k, v in {"person": person, "device": device, "state": state}.items() if v},
    )
    return _ok({"assignments": rows, "total": total})


@frappe.whitelist()
def get_person_access_debug(person):
    """Vì sao person này lên/không lên máy X — dùng khi cổng báo không quét được."""
    ctx = EngineContext()
    desired = compute_person_desired(person, ctx)
    for entry in desired.values():
        entry["is_allday"] = entry["signature"] == ALLDAY_SIGNATURE
    applied = frappe.get_all(
        "FaceID Person Device Assignment",
        filters={"person": person},
        fields=["device", "slot", "schedule_signature", "state", "last_error", "last_applied_at"],
    )
    groups = frappe.get_all(
        "FaceID Access Group Member",
        filters={"person": person},
        fields=["group", "origin", "valid_from", "valid_to"],
    )
    for row in groups:
        row["group_name"] = frappe.db.get_value("FaceID Access Group", row.group, "group_name")
    return _ok({"desired": list(desired.values()), "applied": applied, "groups": groups})


@frappe.whitelist()
def list_device_slots(device=None):
    filters = {"device": device} if device else {}
    rows = frappe.get_all(
        "FaceID Device Slot",
        filters=filters,
        fields=[
            "name",
            "device",
            "slot",
            "schedule_signature",
            "label",
            "periods_json",
            "sync_status",
            "last_synced_at",
            "last_error",
        ],
        order_by="device, slot",
        limit=500,
    )
    for row in rows:
        row["periods"] = json.loads(row.get("periods_json") or "[]")
        row["in_use"] = frappe.db.count(
            "FaceID Person Device Assignment",
            {"device": row["device"], "schedule_signature": row["schedule_signature"]},
        )
    return _ok(rows)


# ----------------------------------------- nhóm hệ thống: PH cổng đón


@frappe.whitelist()
def ensure_pickup_guardian_group(shift_out=None):
    """Dựng/cập nhật nhóm hệ thống 'PH cổng đón' — máy = các đầu checkout cổng đón."""
    name = frappe.db.get_value("FaceID Access Group", {"system_key": PICKUP_GROUP_KEY}, "name")
    doc = (
        frappe.get_doc("FaceID Access Group", name)
        if name
        else frappe.new_doc("FaceID Access Group")
    )
    if not name:
        doc.group_name = "PH cổng đón (hệ thống)"
        doc.system_key = PICKUP_GROUP_KEY
        doc.managed_by = "system"
        doc.is_active = 1
        doc.note = (
            "Nhóm do engine quản lý: thành viên là PH đang có ủy quyền đón còn hiệu lực. "
            "Chỉ chỉnh được ca 'Giờ đón' và hiệu lực."
        )
    if shift_out:
        doc.shift_out = shift_out

    devices = frappe.get_all(
        "FaceID Device",
        filters={"direction": "checkout", "gate_type": ["in", ["pickup", "both"]]},
        pluck="name",
    )
    doc.set("devices", [])
    for device in devices:
        doc.append("devices", {"device": device})

    doc.flags.faceid_system_write = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return _ok({"name": doc.name, "devices": len(devices)}, "Đã cập nhật nhóm PH cổng đón")


@frappe.whitelist()
def sync_pickup_guardian_members():
    """Đồng bộ thành viên nhóm PH cổng đón theo ủy quyền đón còn hiệu lực."""
    group = frappe.db.get_value("FaceID Access Group", {"system_key": PICKUP_GROUP_KEY}, "name")
    if not group:
        return _err("Chưa dựng nhóm PH cổng đón — chạy ensure_pickup_guardian_group trước")

    day = frappe.utils.today()
    should_be = set(
        frappe.get_all(
            "FaceID Pickup Authorization",
            filters={
                "revoked": 0,
                "valid_from": ["<=", day],
                "valid_to": [">=", day],
            },
            pluck="guardian",
        )
    )
    should_be.discard(None)

    current = set(
        frappe.get_all("FaceID Access Group Member", filters={"group": group}, pluck="person")
    )

    touched: list[str] = []
    for person in should_be - current:
        if not frappe.db.exists("FaceID Person", person):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "FaceID Access Group Member",
                "group": group,
                "person": person,
                "origin": "system",
            }
        )
        doc.flags.faceid_skip_refresh = True
        doc.insert(ignore_permissions=True)
        touched.append(person)

    for person in current - should_be:
        member = frappe.db.get_value(
            "FaceID Access Group Member", {"group": group, "person": person}, "name"
        )
        if member:
            doc = frappe.get_doc("FaceID Access Group Member", member)
            doc.flags.faceid_skip_refresh = True
            doc.delete(ignore_permissions=True)
            touched.append(person)

    frappe.db.set_value(
        "FaceID Access Group", group, "member_count", len(should_be), update_modified=False
    )
    frappe.db.set_value(
        "FaceID Access Group", group, "last_applied_at", now(), update_modified=False
    )
    frappe.db.commit()

    if touched:
        frappe.enqueue(
            "erp.api.faceid.access_engine.refresh_persons",
            queue="long",
            timeout=3600,
            person_names=touched,
        )
    return _ok(
        {"guardians": len(should_be), "changed": len(touched)},
        "Đã đồng bộ thành viên nhóm PH cổng đón",
    )
