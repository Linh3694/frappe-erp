"""Engine tính trạng thái mong muốn person × thiết bị từ các Access Group.

Mô hình: một person có thể thuộc nhiều nhóm (khối, xe bus, học thứ 7...).
Trên mỗi đầu đọc, khung giờ hiệu lực = HỢP các khung giờ của mọi nhóm chứa
person đó, lấy theo chiều của đầu đọc (checkin → shift_in, checkout → shift_out).
Hợp khung giờ đó được chuẩn hóa thành `signature`; mỗi signature trên một máy
chiếm một slot week plan (2-16), cấp phát động và thu hồi khi không còn ai dùng.
Ràng buộc phần cứng: Hikvision chỉ nhận 1 planTemplateNo/person/cửa.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict

import frappe
from frappe.utils import now, today

ALLDAY_SIGNATURE = "ALLDAY"
ALLDAY_SLOT = 1  # template mặc định 24/7 sẵn có trên máy — không cần đẩy week plan
MIN_DYNAMIC_SLOT = 2
MAX_SLOT = 16
MAX_SEGMENTS_PER_DAY = 8  # giới hạn firmware: 8 đoạn/ngày trong 1 week plan

SLOT_JOB_PRIORITY = 8  # chạy trước job person (order_by priority desc)
PERSON_JOB_PRIORITY = 5


# ---------------------------------------------------------------- thời gian


def hhmm(value) -> str:
    """Chuẩn hóa Time/timedelta/str của Frappe về 'HH:MM'.

    Time field trả về timedelta; str(timedelta(hours=6)) = '6:00:00' nên cách
    cắt chuỗi [:5] cho ra '6:00:' làm controller parse lỗi — phải quy về phút.
    """
    return _fmt(_to_minutes(value))


def _to_minutes(value) -> int:
    if value is None:
        return 0
    if hasattr(value, "total_seconds"):
        return int(value.total_seconds() // 60)
    if hasattr(value, "hour"):
        return int(value.hour) * 60 + int(value.minute)
    parts = str(value).strip().split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 and parts[1] != "" else 0
    except (ValueError, IndexError):
        return 0
    return h * 60 + m


def _fmt(minutes: int) -> str:
    minutes = max(0, min(int(minutes), 24 * 60))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def merge_periods(periods: list[dict]) -> list[dict]:
    """Hợp các khung giờ theo từng thứ, gộp đoạn chồng lấn/liền kề."""
    by_day: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for p in periods:
        weekday = int(p["weekday"])
        start = _to_minutes(p["start_time"])
        end = _to_minutes(p["end_time"])
        if end <= start:
            continue
        by_day[weekday].append((start, end))

    merged: list[dict] = []
    for weekday in sorted(by_day):
        intervals = sorted(by_day[weekday])
        current_start, current_end = intervals[0]
        collapsed: list[tuple[int, int]] = []
        for start, end in intervals[1:]:
            if start <= current_end:  # chồng lấn hoặc liền kề → gộp
                current_end = max(current_end, end)
            else:
                collapsed.append((current_start, current_end))
                current_start, current_end = start, end
        collapsed.append((current_start, current_end))
        for start, end in collapsed:
            merged.append(
                {"weekday": weekday, "start_time": _fmt(start), "end_time": _fmt(end)}
            )
    return merged


def signature_of(periods: list[dict]) -> str:
    """Chữ ký chuẩn hóa của một tập khung giờ. Rỗng = 24/7."""
    merged = merge_periods(periods)
    if not merged:
        return ALLDAY_SIGNATURE
    raw = json.dumps(merged, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _hash(*parts) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ context


class EngineContext:
    """Cache tra cứu dùng chung trong một lượt tính (nhóm/ca/máy đều ít)."""

    def __init__(self):
        self._shift_periods: dict[str, list[dict]] = {}
        self._groups: dict[str, dict] = {}
        self._devices: dict[str, dict] = {}

    def shift_periods(self, shift_name: str | None) -> list[dict]:
        if not shift_name:
            return []
        if shift_name not in self._shift_periods:
            doc = frappe.get_cached_doc("FaceID Work Shift", shift_name)
            self._shift_periods[shift_name] = [
                {
                    "weekday": int(row.weekday),
                    "start_time": hhmm(row.start_time),
                    "end_time": hhmm(row.end_time),
                }
                for row in doc.periods or []
                if row.weekday
            ]
        return self._shift_periods[shift_name]

    def group(self, group_name: str) -> dict:
        if group_name not in self._groups:
            doc = frappe.get_cached_doc("FaceID Access Group", group_name)
            self._groups[group_name] = {
                "name": doc.name,
                "group_name": doc.group_name,
                "is_active": int(doc.is_active or 0),
                "shift_in": doc.shift_in,
                "shift_out": doc.shift_out,
                "valid_from": str(doc.valid_from) if doc.valid_from else None,
                "valid_to": str(doc.valid_to) if doc.valid_to else None,
                "devices": [row.device for row in doc.devices or []],
            }
        return self._groups[group_name]

    def device(self, device_name: str) -> dict:
        if device_name not in self._devices:
            row = frappe.db.get_value(
                "FaceID Device",
                device_name,
                ["name", "ip", "device_name", "direction", "gate_no"],
                as_dict=True,
            )
            self._devices[device_name] = dict(row) if row else {}
        return self._devices[device_name]


# ------------------------------------------------------- desired state


def _intersect_from(a: str | None, b: str | None) -> str | None:
    """Giao cận dưới: None = không giới hạn."""
    if not a:
        return b
    if not b:
        return a
    return max(a, b)


def _intersect_to(a: str | None, b: str | None) -> str | None:
    if not a:
        return b
    if not b:
        return a
    return min(a, b)


def _union_from(a: str | None, b: str | None) -> str | None:
    """Hợp cận dưới: None (không giới hạn) nuốt mọi giá trị."""
    if a is None or b is None:
        return None
    return min(a, b)


def _union_to(a: str | None, b: str | None) -> str | None:
    if a is None or b is None:
        return None
    return max(a, b)


def person_groups(person_name: str, ctx: EngineContext) -> list[dict]:
    """Các nhóm còn hiệu lực chứa person (đã bỏ nhóm tắt / đã hết hạn)."""
    rows = frappe.get_all(
        "FaceID Access Group Member",
        filters={"person": person_name},
        fields=["group", "valid_from", "valid_to"],
        limit=500,
    )
    day = today()
    out: list[dict] = []
    for row in rows:
        if not frappe.db.exists("FaceID Access Group", row.group):
            continue
        group = dict(ctx.group(row.group))
        if not group["is_active"]:
            continue
        # Hiệu lực riêng của thành viên đè lên hiệu lực nhóm
        if row.valid_from:
            group["valid_from"] = str(row.valid_from)
        if row.valid_to:
            group["valid_to"] = str(row.valid_to)
        if group["valid_to"] and group["valid_to"] < day:
            continue  # nhóm đã hết hạn
        out.append(group)
    return out


def compute_person_desired(person_name: str, ctx: EngineContext | None = None) -> dict:
    """Trả về {device_name: {...}} — trạng thái mong muốn của person trên từng máy."""
    ctx = ctx or EngineContext()
    person = frappe.db.get_value(
        "FaceID Person",
        person_name,
        ["name", "external_code", "display_name", "is_active", "valid_from", "valid_to"],
        as_dict=True,
    )
    if not person or not int(person.is_active or 0):
        return {}

    person_from = str(person.valid_from) if person.valid_from else None
    person_to = str(person.valid_to) if person.valid_to else None

    desired: dict[str, dict] = {}
    for group in person_groups(person_name, ctx):
        for device_name in group["devices"]:
            device = ctx.device(device_name)
            if not device:
                continue
            direction = device.get("direction") or "checkin"
            shift = group["shift_in"] if direction == "checkin" else group["shift_out"]
            periods = ctx.shift_periods(shift)

            entry = desired.setdefault(
                device_name,
                {
                    "device": device_name,
                    "device_ip": device.get("ip"),
                    "periods": [],
                    "groups": [],
                    "valid_from": group["valid_from"],
                    "valid_to": group["valid_to"],
                    "unrestricted": False,
                },
            )
            entry["groups"].append(group["name"])
            entry["valid_from"] = _union_from(entry["valid_from"], group["valid_from"])
            entry["valid_to"] = _union_to(entry["valid_to"], group["valid_to"])
            if not periods:
                # Nhóm không khai ca cho chiều này → không giới hạn giờ (24/7)
                entry["unrestricted"] = True
            else:
                entry["periods"].extend(periods)

    for entry in desired.values():
        if entry["unrestricted"]:
            entry["periods"] = []
            entry["signature"] = ALLDAY_SIGNATURE
        else:
            entry["periods"] = merge_periods(entry["periods"])
            entry["signature"] = signature_of(entry["periods"])
        entry["valid_from"] = _intersect_from(entry["valid_from"], person_from)
        entry["valid_to"] = _intersect_to(entry["valid_to"], person_to)
    return desired


class AccessConfigError(Exception):
    """Cấu hình nhóm không đẩy được xuống máy — dừng đúng person đó, không cả lô."""


def validate_periods_fit(periods: list[dict], where: str = ""):
    """Chặn cấu hình nhóm vượt 8 đoạn/ngày (firmware không nhận)."""
    per_day: dict[int, int] = defaultdict(int)
    for p in periods:
        per_day[int(p["weekday"])] += 1
    for weekday, count in per_day.items():
        if count > MAX_SEGMENTS_PER_DAY:
            raise AccessConfigError(
                f"{where}Thứ {weekday} có {count} khung giờ sau khi gộp các nhóm, "
                f"vượt giới hạn {MAX_SEGMENTS_PER_DAY} đoạn/ngày của thiết bị"
            )


# --------------------------------------------------------- cấp phát slot


def allocate_slot(device_name: str, signature: str, periods: list[dict], label: str = "") -> int:
    """Cấp (hoặc tra lại) slot week plan cho một signature trên một máy."""
    if signature == ALLDAY_SIGNATURE:
        return ALLDAY_SLOT

    existing = frappe.db.get_value(
        "FaceID Device Slot",
        {"device": device_name, "schedule_signature": signature},
        ["name", "slot", "periods_json", "desired_hash", "applied_hash"],
        as_dict=True,
    )
    periods_json = json.dumps(periods, ensure_ascii=False)
    desired_hash = _hash(signature, periods_json)

    if existing:
        if existing.desired_hash != desired_hash or existing.periods_json != periods_json:
            frappe.db.set_value(
                "FaceID Device Slot",
                existing.name,
                {
                    "periods_json": periods_json,
                    "desired_hash": desired_hash,
                    "sync_status": "pending",
                },
                update_modified=True,
            )
        return int(existing.slot)

    used = {
        int(row.slot)
        for row in frappe.get_all(
            "FaceID Device Slot", filters={"device": device_name}, fields=["slot"]
        )
    }
    used.add(ALLDAY_SLOT)
    free = next((s for s in range(MIN_DYNAMIC_SLOT, MAX_SLOT + 1) if s not in used), None)
    if free is None:
        device_label = frappe.db.get_value("FaceID Device", device_name, "device_name")
        raise AccessConfigError(
            f"Máy {device_label or device_name} đã dùng hết {MAX_SLOT - 1} slot ca. "
            "Gộp bớt nhóm dùng chung khung giờ trước khi thêm nhóm mới."
        )

    doc = frappe.get_doc(
        {
            "doctype": "FaceID Device Slot",
            "device": device_name,
            "slot": free,
            "schedule_signature": signature,
            "label": label[:140],
            "periods_json": periods_json,
            "desired_hash": desired_hash,
            "sync_status": "pending",
        }
    )
    doc.insert(ignore_permissions=True)
    return free


def pending_slot_jobs() -> int:
    """Xếp job đẩy week plan cho các slot chưa khớp máy."""
    from erp.api.faceid.sync_worker import create_device_sync_job

    rows = frappe.get_all(
        "FaceID Device Slot",
        filters={"sync_status": ["!=", "synced"]},
        fields=["name"],
        limit=500,
    )
    for row in rows:
        create_device_sync_job(
            "sync_device_slot",
            "FaceID Device Slot",
            row.name,
            priority=SLOT_JOB_PRIORITY,
        )
    return len(rows)


def gc_device_slots(device_name: str | None = None) -> int:
    """Thu hồi slot không còn assignment nào tham chiếu."""
    filters = {"device": device_name} if device_name else {}
    removed = 0
    for row in frappe.get_all("FaceID Device Slot", filters=filters, fields=["name", "device", "schedule_signature"]):
        in_use = frappe.db.exists(
            "FaceID Person Device Assignment",
            {
                "device": row.device,
                "schedule_signature": row.schedule_signature,
                "state": ["!=", "deleting"],
            },
        )
        if not in_use:
            frappe.delete_doc("FaceID Device Slot", row.name, ignore_permissions=True, force=True)
            removed += 1
    return removed


# ------------------------------------------------------------- đồng bộ


def _person_revision(person_name: str) -> str:
    row = frappe.db.get_value(
        "FaceID Person",
        person_name,
        ["display_name", "external_code", "photo_file", "photo_url", "is_active"],
        as_dict=True,
    )
    if not row:
        return ""
    return _hash(
        row.display_name, row.external_code, row.photo_file, row.photo_url, row.is_active
    )


def sync_person_assignments(person_name: str, ctx: EngineContext | None = None) -> dict:
    """Tính lại desired state của 1 person và cập nhật bảng Assignment."""
    ctx = ctx or EngineContext()
    desired = compute_person_desired(person_name, ctx)
    revision = _person_revision(person_name)

    existing = {
        row.device: row
        for row in frappe.get_all(
            "FaceID Person Device Assignment",
            filters={"person": person_name},
            fields=[
                "name",
                "device",
                "slot",
                "schedule_signature",
                "state",
                "desired_hash",
                "applied_hash",
            ],
        )
    }

    added = updated = removed = unchanged = 0

    for device_name, entry in desired.items():
        validate_periods_fit(
            entry["periods"],
            where=f"Máy {ctx.device(device_name).get('device_name') or device_name}: ",
        )
        label = ", ".join(entry["groups"][:3])
        slot = allocate_slot(device_name, entry["signature"], entry["periods"], label)
        desired_hash = _hash(
            revision,
            entry["signature"],
            slot,
            entry["valid_from"],
            entry["valid_to"],
        )
        values = {
            "slot": slot,
            "schedule_signature": entry["signature"],
            "valid_from": entry["valid_from"],
            "valid_to": entry["valid_to"],
            "source_groups": ", ".join(entry["groups"])[:500],
            "desired_hash": desired_hash,
        }
        row = existing.pop(device_name, None)
        if row is None:
            doc = frappe.get_doc(
                {
                    "doctype": "FaceID Person Device Assignment",
                    "person": person_name,
                    "device": device_name,
                    "state": "pending",
                    **values,
                }
            )
            doc.insert(ignore_permissions=True)
            added += 1
        elif row.desired_hash != desired_hash or row.state in ("deleting", "error"):
            values["state"] = "pending"
            frappe.db.set_value(
                "FaceID Person Device Assignment", row.name, values, update_modified=True
            )
            updated += 1
        else:
            unchanged += 1

    # Máy không còn trong desired
    for row in existing.values():
        if not row.applied_hash:
            # Chưa từng đẩy xuống máy → xóa thẳng, không cần job gỡ
            frappe.delete_doc(
                "FaceID Person Device Assignment", row.name, ignore_permissions=True, force=True
            )
        elif row.state != "deleting":
            frappe.db.set_value(
                "FaceID Person Device Assignment",
                row.name,
                {"state": "deleting"},
                update_modified=True,
            )
        removed += 1

    return {
        "person": person_name,
        "added": added,
        "updated": updated,
        "removed": removed,
        "unchanged": unchanged,
        "dirty": added + updated + removed,
    }


def enqueue_person_apply(person_name: str) -> str | None:
    """Xếp job áp trạng thái xuống máy nếu person có dòng chưa khớp."""
    from erp.api.faceid.sync_worker import create_device_sync_job

    dirty = frappe.db.exists(
        "FaceID Person Device Assignment",
        {"person": person_name, "state": ["in", ["pending", "deleting", "error"]]},
    )
    if not dirty:
        return None
    return create_device_sync_job(
        "apply_person_access",
        "FaceID Person",
        person_name,
        priority=PERSON_JOB_PRIORITY,
    )


def refresh_persons(person_names: list[str]) -> dict:
    """Tính lại + xếp job cho một tập person.

    Lỗi cấu hình của một person (hết slot, quá 8 đoạn/ngày) chỉ dừng person đó —
    ghi vào `last_error` để operator thấy, phần còn lại của lô vẫn chạy.
    """
    ctx = EngineContext()
    summary = {
        "persons": 0,
        "added": 0,
        "updated": 0,
        "removed": 0,
        "queued": 0,
        "errors": 0,
        "error_samples": [],
    }
    for name in person_names:
        if not frappe.db.exists("FaceID Person", name):
            continue
        try:
            result = sync_person_assignments(name, ctx)
        except AccessConfigError as e:
            summary["errors"] += 1
            if len(summary["error_samples"]) < 10:
                summary["error_samples"].append({"person": name, "error": str(e)[:200]})
            frappe.db.set_value(
                "FaceID Person",
                name,
                {"sync_status": "error", "last_error": str(e)[:500]},
                update_modified=False,
            )
            continue
        summary["persons"] += 1
        summary["added"] += result["added"]
        summary["updated"] += result["updated"]
        summary["removed"] += result["removed"]
        if enqueue_person_apply(name):
            summary["queued"] += 1
    pending_slot_jobs()
    frappe.db.commit()
    return summary


def group_member_names(group_name: str) -> list[str]:
    return frappe.get_all(
        "FaceID Access Group Member",
        filters={"group": group_name},
        pluck="person",
        limit=100000,
    )


def refresh_group(group_name: str, background_threshold: int = 200) -> dict:
    """Tính lại toàn bộ thành viên của một nhóm."""
    members = group_member_names(group_name)
    if len(members) > background_threshold:
        frappe.enqueue(
            "erp.api.faceid.access_engine.refresh_persons",
            queue="long",
            timeout=3600,
            enqueue_after_commit=True,
            person_names=members,
        )
        frappe.db.set_value(
            "FaceID Access Group", group_name, "member_count", len(members), update_modified=False
        )
        return {"queued_background": len(members)}

    result = refresh_persons(members)
    frappe.db.set_value(
        "FaceID Access Group",
        group_name,
        {"member_count": len(members), "last_applied_at": now()},
        update_modified=False,
    )
    return result


def deactivate_person(person_name: str, reason: str = "") -> dict:
    """Tắt person + gỡ khỏi mọi máy ngay (HS nghỉ học, NV nghỉ việc)."""
    if not frappe.db.exists("FaceID Person", person_name):
        return {"skipped": "not_found"}
    frappe.db.set_value(
        "FaceID Person",
        person_name,
        {"is_active": 0, "last_error": reason[:140] if reason else None},
        update_modified=True,
    )
    result = sync_person_assignments(person_name)
    enqueue_person_apply(person_name)
    frappe.db.commit()
    return result


def preview_group(group_name: str, limit_persons: int = 5000) -> dict:
    """Diff dự kiến trước khi áp — chỉ tính, không ghi Assignment/Slot."""
    ctx = EngineContext()
    members = group_member_names(group_name)[:limit_persons]
    add_by_device: dict[str, int] = defaultdict(int)
    remove_by_device: dict[str, int] = defaultdict(int)
    change_by_device: dict[str, int] = defaultdict(int)
    new_signatures: set[tuple[str, str]] = set()
    warnings: list[str] = []

    # Nạp sẵn slot đang có + số slot trống mỗi máy: tránh query trong vòng lặp person
    slots_by_device: dict[str, set[str]] = defaultdict(set)
    slot_count: dict[str, int] = defaultdict(int)
    for row in frappe.get_all(
        "FaceID Device Slot", fields=["device", "schedule_signature"], limit=5000
    ):
        slots_by_device[row.device].add(row.schedule_signature)
        slot_count[row.device] += 1

    for person_name in members:
        desired = compute_person_desired(person_name, ctx)
        existing = {
            row.device: row
            for row in frappe.get_all(
                "FaceID Person Device Assignment",
                filters={"person": person_name},
                fields=["device", "schedule_signature", "state"],
            )
        }
        for device_name, entry in desired.items():
            signature = entry["signature"]
            if signature != ALLDAY_SIGNATURE and signature not in slots_by_device[device_name]:
                if (device_name, signature) not in new_signatures:
                    new_signatures.add((device_name, signature))
                    slot_count[device_name] += 1
            row = existing.pop(device_name, None)
            if row is None:
                add_by_device[device_name] += 1
            elif row.schedule_signature != signature or row.state != "applied":
                change_by_device[device_name] += 1
            try:
                validate_periods_fit(entry["periods"])
            except AccessConfigError as e:
                message = f"{_device_label(ctx, device_name)}: {e}"
                if message not in warnings:
                    warnings.append(message)
        for device_name in existing:
            remove_by_device[device_name] += 1

    for device_name, count in slot_count.items():
        if count > MAX_SLOT - 1:
            warnings.append(
                f"{_device_label(ctx, device_name)}: cần {count} slot ca, "
                f"vượt giới hạn {MAX_SLOT - 1} của thiết bị"
            )

    return {
        "members": len(members),
        "add": [{"device": _device_label(ctx, d), "count": c} for d, c in add_by_device.items()],
        "update": [
            {"device": _device_label(ctx, d), "count": c} for d, c in change_by_device.items()
        ],
        "remove": [
            {"device": _device_label(ctx, d), "count": c} for d, c in remove_by_device.items()
        ],
        "new_slots": [{"device": _device_label(ctx, d), "signature": s} for d, s in new_signatures],
        "warnings": warnings,
    }


def _device_label(ctx: EngineContext, device_name: str) -> str:
    return ctx.device(device_name).get("device_name") or device_name


def reconcile_all(limit: int = 20000) -> dict:
    """Cron đêm: đẩy việc quét toàn bộ sang queue long (worker scheduler hay timeout)."""
    frappe.enqueue(
        "erp.api.faceid.access_engine.reconcile_all_now",
        queue="long",
        timeout=7200,
        limit=limit,
    )
    return {"queued": True}


def reconcile_all_now(limit: int = 20000) -> dict:
    """Quét lại toàn bộ person active + thu hồi slot mồ côi."""
    persons = frappe.get_all(
        "FaceID Person", filters={"is_active": 1}, pluck="name", limit=limit
    )
    summary = refresh_persons(persons)
    summary["slots_reclaimed"] = gc_device_slots()
    frappe.db.commit()
    return summary
