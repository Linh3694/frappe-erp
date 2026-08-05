"""Chuyển mô hình FaceID sang Access Group mà không đổi hành vi đang chạy.

Mô hình cũ: mỗi person gắn 1 `work_shift`, khi operator bấm sync thì đẩy xuống
TẤT CẢ máy với planTemplateNo = shift.device_slot.

Patch này dựng lại đúng bức tranh đó bằng nhóm:
  - mỗi ca hiện có → 1 nhóm "[Chuyển đổi] <tên ca>" (shift_in = shift_out = ca đó,
    máy = toàn bộ máy đang khai) chứa các person đang gắn ca đó;
  - person không gắn ca → nhóm "[Chuyển đổi] Mặc định 24/7".

Đồng thời seed sẵn Device Slot + Assignment ở trạng thái ĐÃ ÁP cho những person
`on_device = 1` (đã thực sự nằm trên máy), để engine không coi cả trường là lệch
và đẩy lại hàng nghìn person trong lần reconcile đầu tiên. Person chưa từng được
đẩy thì không seed — họ sẽ lên máy khi operator bấm áp dụng nhóm.

Idempotent: chạy lại là no-op.
"""

import json

import frappe

from erp.api.faceid.access_engine import (
    ALLDAY_SIGNATURE,
    ALLDAY_SLOT,
    _hash,
    _person_revision,
    hhmm,
    signature_of,
)

CONVERTED_PREFIX = "[Chuyển đổi] "
DEFAULT_GROUP = f"{CONVERTED_PREFIX}Mặc định 24/7"


def execute():
    for doctype in (
        "FaceID Device",
        "FaceID Person",
        "FaceID Access Group",
        "FaceID Access Group Member",
        "FaceID Device Slot",
        "FaceID Person Device Assignment",
    ):
        if not frappe.db.table_exists(doctype):
            return

    # 1) Máy cũ chưa khai chiều → mặc định là đầu check-in
    frappe.db.sql(
        """
        UPDATE `tabFaceID Device`
        SET direction = 'checkin'
        WHERE direction IS NULL OR direction = ''
        """
    )

    devices = frappe.get_all("FaceID Device", pluck="name")
    if not devices:
        return

    shifts = _shift_index()
    groups = _ensure_groups(shifts, devices)
    _ensure_members(groups)
    _seed_applied_state(shifts, groups, devices)
    frappe.db.commit()


def _shift_index() -> dict:
    """{shift_name: {slot, periods, signature}} — periods đã chuẩn hóa."""
    index = {}
    for name in frappe.get_all("FaceID Work Shift", pluck="name"):
        doc = frappe.get_doc("FaceID Work Shift", name)
        periods = [
            {
                "weekday": int(row.weekday),
                "start_time": hhmm(row.start_time),
                "end_time": hhmm(row.end_time),
            }
            for row in doc.periods or []
            if row.weekday
        ]
        index[name] = {
            "slot": int(doc.device_slot or ALLDAY_SLOT),
            "periods": periods,
            "signature": signature_of(periods),
        }
    return index


def _ensure_groups(shifts: dict, devices: list[str]) -> dict:
    """{shift_name|None: group_name}"""
    groups: dict = {}
    wanted = {None: DEFAULT_GROUP}
    for shift_name in shifts:
        label = frappe.db.get_value("FaceID Work Shift", shift_name, "shift_name") or shift_name
        wanted[shift_name] = f"{CONVERTED_PREFIX}{label}"[:140]

    for shift_name, group_label in wanted.items():
        existing = frappe.db.get_value(
            "FaceID Access Group", {"group_name": group_label}, "name"
        )
        if existing:
            groups[shift_name] = existing
            continue

        doc = frappe.new_doc("FaceID Access Group")
        doc.group_name = group_label
        doc.is_active = 1
        doc.managed_by = "admin"
        doc.note = (
            "Nhóm sinh tự động khi chuyển sang mô hình Access Group — giữ nguyên "
            "hành vi cũ (mọi máy, ca gắn trực tiếp trên person). Rà lại danh sách "
            "máy và tách chiều vào/ra khi cấu hình lại theo cổng."
        )
        if shift_name:
            doc.shift_in = shift_name
            doc.shift_out = shift_name
        for device in devices:
            doc.append("devices", {"device": device})
        doc.flags.faceid_skip_refresh = True
        doc.insert(ignore_permissions=True)
        groups[shift_name] = doc.name

    return groups


def _ensure_members(groups: dict):
    persons = frappe.get_all(
        "FaceID Person",
        filters={"is_active": 1},
        fields=["name", "work_shift"],
        limit=100000,
    )
    for person in persons:
        group = groups.get(person.work_shift) or groups.get(None)
        if not group:
            continue
        if frappe.db.exists(
            "FaceID Access Group Member", {"group": group, "person": person.name}
        ):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "FaceID Access Group Member",
                "group": group,
                "person": person.name,
                "origin": "manual",
            }
        )
        doc.flags.faceid_skip_refresh = True
        doc.insert(ignore_permissions=True)

    for group in set(groups.values()):
        frappe.db.set_value(
            "FaceID Access Group",
            group,
            "member_count",
            frappe.db.count("FaceID Access Group Member", {"group": group}),
            update_modified=False,
        )


def _seed_applied_state(shifts: dict, groups: dict, devices: list[str]):
    """Ghi nhận trạng thái ĐANG có trên máy để engine không đẩy lại toàn trường."""
    # Device Slot: week plan của các ca cũ đã nằm sẵn trên máy ở đúng device_slot
    for shift_name, info in shifts.items():
        if info["signature"] == ALLDAY_SIGNATURE:
            continue
        periods_json = json.dumps(info["periods"], ensure_ascii=False)
        desired_hash = _hash(info["signature"], periods_json)
        label = frappe.db.get_value("FaceID Work Shift", shift_name, "shift_name") or shift_name
        for device in devices:
            if frappe.db.exists(
                "FaceID Device Slot",
                {"device": device, "schedule_signature": info["signature"]},
            ):
                continue
            if frappe.db.exists("FaceID Device Slot", {"device": device, "slot": info["slot"]}):
                # Slot đã bị ca khác chiếm trên máy này — để engine tự cấp slot mới
                continue
            doc = frappe.get_doc(
                {
                    "doctype": "FaceID Device Slot",
                    "device": device,
                    "slot": info["slot"],
                    "schedule_signature": info["signature"],
                    "label": label[:140],
                    "periods_json": periods_json,
                    "desired_hash": desired_hash,
                    "applied_hash": desired_hash,
                    "sync_status": "synced",
                }
            )
            doc.insert(ignore_permissions=True)

    # Assignment: chỉ seed person đã thực sự nằm trên máy
    persons = frappe.get_all(
        "FaceID Person",
        filters={"is_active": 1, "on_device": 1},
        fields=["name", "work_shift", "valid_from", "valid_to"],
        limit=100000,
    )
    for person in persons:
        info = shifts.get(person.work_shift)
        signature = info["signature"] if info else ALLDAY_SIGNATURE
        slot = info["slot"] if info else ALLDAY_SLOT
        revision = _person_revision(person.name)
        valid_from = str(person.valid_from) if person.valid_from else None
        valid_to = str(person.valid_to) if person.valid_to else None
        desired_hash = _hash(revision, signature, slot, valid_from, valid_to)

        for device in devices:
            if frappe.db.exists(
                "FaceID Person Device Assignment",
                {"person": person.name, "device": device},
            ):
                continue
            doc = frappe.get_doc(
                {
                    "doctype": "FaceID Person Device Assignment",
                    "person": person.name,
                    "device": device,
                    "slot": slot,
                    "schedule_signature": signature,
                    "state": "applied",
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                    "source_groups": groups.get(person.work_shift) or groups.get(None) or "",
                    "desired_hash": desired_hash,
                    "applied_hash": desired_hash,
                    "last_applied_at": frappe.utils.now(),
                }
            )
            doc.insert(ignore_permissions=True)
