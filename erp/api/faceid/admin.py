"""API quản trị FaceID cho frappe-sis-frontend."""

from __future__ import annotations

import json
from datetime import date, datetime
from urllib.parse import urlencode

import frappe
from frappe.utils import cint

from erp.api.faceid.sync_worker import (
    create_device_sync_job,
    person_sync_job_stats,
)
from erp.utils.faceid_gateway import (
    gateway_delete,
    gateway_get,
    gateway_healthz,
    gateway_post,
    gateway_post_file,
    get_gateway_config,
)


def _ok(data=None, message="OK"):
    return {"success": True, "message": message, "data": data}


def _err(message, data=None):
    return {"success": False, "message": message, "data": data}


def _person_is_active(row) -> bool:
    """Bản ghi cũ có thể chưa có is_active — mặc định doctype là bật."""
    val = row.get("is_active") if isinstance(row, dict) else getattr(row, "is_active", None)
    if val is None or val == "":
        return True
    return cint(val) == 1


def _apply_person_campus_filter(filters: dict, person_type: str | None, campus_id: str | None):
    """
    Lọc campus cho FaceID Person.
    NV (staff) theo user_management — User không gắn campus_id, bỏ qua filter campus.
    HS/PH lấy từ CRM Student/Guardian có campus_id.
    """
    if not campus_id:
        return
    if person_type == "staff":
        return
    filters["campus_id"] = campus_id


# ---- Persons ----


@frappe.whitelist()
def list_persons(
    person_type=None,
    campus_id=None,
    sync_status=None,
    is_active=None,
    search=None,
    limit=100,
    offset=0,
):
    filters = {}
    if person_type:
        filters["person_type"] = person_type
    _apply_person_campus_filter(filters, person_type, campus_id)
    if sync_status:
        filters["sync_status"] = sync_status
    if is_active is not None and str(is_active) != "":
        filters["is_active"] = int(is_active)

    or_filters = None
    if search:
        q = f"%{search.strip()}%"
        or_filters = [
            ["display_name", "like", q],
            ["external_code", "like", q],
            ["position", "like", q],
            ["department", "like", q],
        ]

    rows = frappe.get_all(
        "FaceID Person",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "person_type",
            "external_code",
            "display_name",
            "position",
            "department",
            "photo_url",
            "campus_id",
            "is_active",
            "on_device",
            "face_status",
            "sync_status",
            "last_synced_at",
            "last_error",
            "valid_from",
            "valid_to",
            "source_synced_at",
        ],
        order_by="modified desc",
        limit=int(limit),
        start=int(offset),
    )
    total = frappe.db.count("FaceID Person", filters=filters)
    if or_filters:
        total = len(
            frappe.get_all(
                "FaceID Person",
                filters=filters,
                or_filters=or_filters,
                pluck="name",
                limit=0,
            )
        )
    return _ok({"items": rows, "total": total})


# Trên ngưỡng này thì kéo nguồn ở background — request web (timeout 60s phía
# frontend) không kham nổi hàng nghìn bản upsert trong một lần bấm.
SOURCE_REFRESH_INLINE_MAX = 300


def _count_source_candidates(person_type, campus_id=None):
    if person_type == "student":
        filters = {"campus_id": campus_id} if campus_id else {}
        return frappe.db.count("CRM Student", filters)
    if person_type == "guardian":
        filters = {"campus_id": campus_id} if campus_id else {}
        return frappe.db.count("CRM Guardian", filters)
    if person_type == "staff":
        return frappe.db.sql(
            """
            SELECT COUNT(*) FROM `tabUser` u
            WHERE u.user_type = 'System User'
              AND u.name NOT IN ('Guest', 'Administrator')
              AND u.email NOT LIKE %s
            """,
            ("%@parent.wellspring.edu.vn",),
        )[0][0]
    return 0


@frappe.whitelist()
def refresh_persons_from_source(person_type, campus_id=None, class_id=None, background=None):
    """Lấy dữ liệu từ nguồn CRM/SIS/User và upsert vào FaceID Person.

    Lô lớn tự chuyển sang queue long (trả về ngay `async=True`);
    truyền background=0/1 để ép chạy inline/nền.
    """
    from erp.api.faceid.person_source import refresh_persons_from_source as _refresh

    total = _count_source_candidates(person_type, campus_id)
    run_background = (
        total > SOURCE_REFRESH_INLINE_MAX if background is None else bool(cint(background))
    )
    if run_background:
        frappe.enqueue(
            "erp.api.faceid.person_source.refresh_persons_from_source",
            queue="long",
            timeout=3600,
            job_id=f"faceid_refresh_source_{person_type}",  # bấm liên tiếp không chồng job
            deduplicate=True,
            person_type=person_type,
            campus_id=campus_id,
            class_id=class_id,
        )
        return _ok(
            {"async": True, "total_candidates": total},
            message=f"Đang kéo {total} bản ghi {person_type} ở nền — tải lại danh sách sau ít phút",
        )

    stats = _refresh(person_type, campus_id, class_id)
    msg = f"Đã lấy dữ liệu: {stats.get('created', 0)} mới, {stats.get('updated', 0)} cập nhật"
    if stats.get("conflicts"):
        msg += f", {stats['conflicts']} bỏ qua (trùng mã loại khác)"
    if stats.get("skipped"):
        msg += f", {stats['skipped']} bỏ qua (không đọc được user)"
    return _ok(stats, message=msg)


@frappe.whitelist()
def set_person_active(name, active=1):
    """Bật/tắt kích hoạt person (staged — chưa đẩy xuống máy)."""
    doc = frappe.get_doc("FaceID Person", name)
    doc.is_active = int(active)
    doc.sync_status = "pending"
    doc.flags.faceid_refresh = 1
    doc.save(ignore_permissions=True)
    return _ok(doc.as_dict())


@frappe.whitelist()
def set_persons_active(names, active=1):
    """Bật/tắt hàng loạt."""
    name_list = frappe.parse_json(names) if isinstance(names, str) else names
    updated = 0
    for n in name_list or []:
        if not frappe.db.exists("FaceID Person", n):
            continue
        doc = frappe.get_doc("FaceID Person", n)
        doc.is_active = int(active)
        doc.sync_status = "pending"
        doc.flags.faceid_refresh = 1
        doc.save(ignore_permissions=True)
        updated += 1
    return _ok({"updated": updated})


@frappe.whitelist()
def sync_persons(person_type=None, campus_id=None, force=0):
    """Tính lại quyền vào của person theo nhóm rồi đẩy phần lệch xuống máy.

    Máy đích KHÔNG chọn ở đây nữa: nó là hệ quả của các Access Group mà person
    thuộc về (xem `access_engine.compute_person_desired`). `force` chỉ còn nghĩa
    là đẩy lại cả những dòng engine coi là đã khớp.
    """
    from erp.api.faceid.access_engine import refresh_persons

    filters = {}
    if person_type:
        filters["person_type"] = person_type
    _apply_person_campus_filter(filters, person_type, campus_id)

    names = frappe.get_all("FaceID Person", filters=filters, pluck="name", limit=20000)
    if not names:
        return _ok(
            {"persons": 0},
            message="Không có person nào (kiểm tra tab loại và bộ lọc campus)",
        )

    if cint(force):
        # Xóa dấu "đã đẩy" để mọi dòng bị coi là lệch và đẩy lại
        frappe.db.sql(
            """
            UPDATE `tabFaceID Person Device Assignment`
            SET applied_hash = NULL, state = 'pending'
            WHERE person IN %(names)s
            """,
            {"names": tuple(names)},
        )

    if len(names) > 200:
        frappe.enqueue(
            "erp.api.faceid.access_engine.refresh_persons",
            queue="long",
            timeout=7200,
            enqueue_after_commit=True,
            person_names=names,
        )
        return _ok(
            {"persons": len(names), "async": True},
            message=f"Đã xếp hàng đồng bộ {len(names)} person — chạy nền",
        )

    result = refresh_persons(names)
    return _ok(
        {**result, **person_sync_job_stats(person_type)},
        message=(
            f"Đã tính lại {result['persons']} person: "
            f"+{result['added']} lên máy, ~{result['updated']} cập nhật, "
            f"-{result['removed']} gỡ khỏi máy"
        ),
    )


@frappe.whitelist()
def get_person(name):
    doc = frappe.get_doc("FaceID Person", name)
    data = doc.as_dict()
    data["groups"] = frappe.get_all(
        "FaceID Access Group Member", filters={"person": name}, pluck="group"
    )
    data["assignments"] = frappe.get_all(
        "FaceID Person Device Assignment",
        filters={"person": name},
        fields=["device", "slot", "state", "last_error"],
    )
    return _ok(data)


@frappe.whitelist()
def save_person(data):
    payload = frappe.parse_json(data) if isinstance(data, str) else data
    name = payload.get("name")
    if name and frappe.db.exists("FaceID Person", name):
        doc = frappe.get_doc("FaceID Person", name)
        doc.update(payload)
    else:
        doc = frappe.get_doc({"doctype": "FaceID Person", **payload})
    doc.save(ignore_permissions=True)
    # Ảnh/tên/hiệu lực đổi → desired_hash đổi → đẩy lại xuống các máy đang giữ
    _refresh_person_access([doc.name])
    return _ok(doc.as_dict())


def _refresh_person_access(names: list[str]):
    """Lô nhỏ chạy inline cho phản hồi tức thì; lô lớn đẩy nền tránh timeout FE."""
    from erp.api.faceid.access_engine import refresh_persons

    if len(names) > 20:
        frappe.enqueue(
            "erp.api.faceid.access_engine.refresh_persons",
            queue="short",
            enqueue_after_commit=True,
            person_names=names,
        )
    else:
        refresh_persons(names)


@frappe.whitelist()
def delete_person(name):
    frappe.delete_doc("FaceID Person", name, ignore_permissions=True)
    return _ok()


@frappe.whitelist()
def resync_person(name):
    from erp.api.faceid.access_engine import refresh_persons

    result = refresh_persons([name])
    if result.get("errors"):
        return _err(result["error_samples"][0]["error"], result)
    return _ok(result, message="Đã tính lại và xếp hàng đồng bộ person")


# Giữ alias bulk_enroll_* cho tương thích ngược — gọi refresh
@frappe.whitelist()
def bulk_enroll_students(campus_id=None, class_id=None):
    return refresh_persons_from_source("student", campus_id, class_id)


@frappe.whitelist()
def bulk_enroll_staff():
    return refresh_persons_from_source("staff")


@frappe.whitelist()
def bulk_enroll_guardians(campus_id=None):
    return refresh_persons_from_source("guardian", campus_id)


# ---- Work Shifts ----


@frappe.whitelist()
def list_work_shifts():
    """Ca chỉ là khung giờ; slot trên máy do engine cấp phát theo từng máy."""
    rows = frappe.get_all(
        "FaceID Work Shift",
        fields=["name", "shift_name", "note"],
        order_by="shift_name asc",
    )
    for row in rows:
        row["used_by_groups"] = frappe.db.count(
            "FaceID Access Group", {"shift_in": row["name"]}
        ) + frappe.db.count("FaceID Access Group", {"shift_out": row["name"]})
    return _ok(rows)


@frappe.whitelist()
def get_work_shift(name):
    doc = frappe.get_doc("FaceID Work Shift", name)
    return _ok(doc.as_dict())


@frappe.whitelist()
def save_work_shift(data):
    payload = frappe.parse_json(data) if isinstance(data, str) else data
    name = payload.get("name")
    periods = payload.pop("periods", [])
    if name and frappe.db.exists("FaceID Work Shift", name):
        doc = frappe.get_doc("FaceID Work Shift", name)
        doc.update(payload)
    else:
        doc = frappe.get_doc({"doctype": "FaceID Work Shift", **payload})
    doc.set("periods", [])
    for p in periods:
        doc.append(
            "periods",
            {
                "weekday": p.get("weekday"),
                "start_time": p.get("start_time"),
                "end_time": p.get("end_time"),
            },
        )
    doc.save(ignore_permissions=True)
    return _ok(doc.as_dict())


@frappe.whitelist()
def delete_work_shift(name):
    used = frappe.get_all(
        "FaceID Access Group",
        filters={"shift_in": name},
        pluck="group_name",
    ) + frappe.get_all(
        "FaceID Access Group", filters={"shift_out": name}, pluck="group_name"
    )
    if used:
        return _err(
            "Ca đang được dùng bởi nhóm: " + ", ".join(sorted(set(used))[:5])
        )
    frappe.delete_doc("FaceID Work Shift", name, ignore_permissions=True)
    return _ok()


# ---- Pickup Authorization ----


@frappe.whitelist()
def list_pickup_auth(active_only=0):
    filters = {}
    if int(active_only):
        today = date.today()
        rows = frappe.get_all(
            "FaceID Pickup Authorization",
            filters={"revoked": 0, "valid_from": ["<=", today], "valid_to": [">=", today]},
            fields=[
                "name",
                "guardian",
                "student",
                "valid_from",
                "valid_to",
                "method",
                "revoked",
                "sync_status",
                "controller_auth_id",
            ],
            order_by="modified desc",
        )
        return _ok(_enrich_pickup(rows))
    rows = frappe.get_all(
        "FaceID Pickup Authorization",
        fields=[
            "name",
            "guardian",
            "student",
            "valid_from",
            "valid_to",
            "method",
            "revoked",
            "sync_status",
            "controller_auth_id",
        ],
        order_by="modified desc",
        limit=500,
    )
    return _ok(_enrich_pickup(rows))


def _enrich_pickup(rows):
    for r in rows:
        r["guardian_code"] = frappe.db.get_value("FaceID Person", r.guardian, "external_code")
        r["guardian_name"] = frappe.db.get_value("FaceID Person", r.guardian, "display_name")
        r["student_code"] = frappe.db.get_value("FaceID Person", r.student, "external_code")
        r["student_name"] = frappe.db.get_value("FaceID Person", r.student, "display_name")
    return rows


@frappe.whitelist()
def save_pickup_auth(data):
    payload = frappe.parse_json(data) if isinstance(data, str) else data
    name = payload.get("name")
    if name and frappe.db.exists("FaceID Pickup Authorization", name):
        doc = frappe.get_doc("FaceID Pickup Authorization", name)
        doc.update(payload)
    else:
        doc = frappe.get_doc({"doctype": "FaceID Pickup Authorization", **payload})
    doc.save(ignore_permissions=True)
    return _ok(doc.as_dict())


@frappe.whitelist()
def revoke_pickup_auth(name):
    doc = frappe.get_doc("FaceID Pickup Authorization", name)
    doc.revoked = 1
    doc.save(ignore_permissions=True)
    create_device_sync_job("revoke_pickup", doc.doctype, doc.name, priority=9)
    return _ok(message="Đã thu hồi — sync xuống controller local")


@frappe.whitelist()
def reapply_pickup_auth(name):
    doc = frappe.get_doc("FaceID Pickup Authorization", name)
    doc.revoked = 0
    today = date.today()
    if doc.valid_to and doc.valid_to < today:
        doc.valid_from = today
        doc.valid_to = today
    doc.save(ignore_permissions=True)
    create_device_sync_job("reapply_pickup", doc.doctype, doc.name, priority=9)
    return _ok(message="Đã áp dụng lại — sync xuống controller local")


@frappe.whitelist()
def delete_pickup_auth(name):
    frappe.delete_doc("FaceID Pickup Authorization", name, ignore_permissions=True)
    return _ok()


def _pickup_default_validity() -> tuple[date, date]:
    """Hiệu lực mặc định = năm học đang bật (fallback hôm nay)."""
    school_year = frappe.db.get_value(
        "SIS School Year", {"is_enable": 1}, ["start_date", "end_date"], as_dict=True
    )
    today = date.today()
    if school_year and school_year.start_date and school_year.end_date:
        return school_year.start_date, school_year.end_date
    return today, today


@frappe.whitelist()
def suggest_guardians_for_student(student):
    """Gợi ý guardian cho màn thêm ủy quyền TAY: quan hệ gia đình chuẩn của học sinh.

    `student` = FaceID Person (loại student). Trả về mọi guardian trong CRM Family
    của HS kèm cờ đã-map-person và đã-có-ủy-quyền-sống — UI chỉ cho chọn guardian
    đã tồn tại trong danh sách Person (yêu cầu nghiệp vụ), phần còn lại hiển thị
    để biết vì sao chưa chọn được.
    """
    crm_student = frappe.db.get_value("FaceID Person", student, "crm_student")
    if not crm_student:
        return _err("Person không phải học sinh hoặc chưa liên kết CRM Student")

    can_pickup_expr = (
        "IFNULL(fr.can_pickup, 1)" if _relationship_has_can_pickup() else "1"
    )
    rows = frappe.db.sql(
        f"""
        SELECT
            fr.guardian AS crm_guardian,
            fr.relationship_type,
            {can_pickup_expr} AS can_pickup,
            gp.name AS person,
            gp.display_name,
            gp.external_code,
            gp.photo_url
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON fr.parent = f.name
        LEFT JOIN `tabFaceID Person` gp
            ON gp.crm_guardian = fr.guardian AND gp.person_type = 'guardian'
        WHERE fr.parentfield = 'relationships'
          AND f.docstatus < 2
          AND fr.student = %(student)s
          AND IFNULL(fr.guardian, '') != ''
        ORDER BY fr.display_order, fr.idx
        """,
        {"student": crm_student},
        as_dict=True,
    )

    live_guardians = set(
        frappe.get_all(
            "FaceID Pickup Authorization",
            filters={"student": student, "revoked": 0},
            pluck="guardian",
        )
    )
    seen = set()
    items = []
    for r in rows:
        if r.crm_guardian in seen:
            continue
        seen.add(r.crm_guardian)
        guardian_name = r.display_name or frappe.db.get_value(
            "CRM Guardian", r.crm_guardian, "guardian_name"
        )
        items.append(
            {
                "crm_guardian": r.crm_guardian,
                "relationship_type": r.relationship_type,
                "can_pickup": cint(r.can_pickup),
                "person": r.person,
                "display_name": guardian_name,
                "external_code": r.external_code,
                "photo_url": r.photo_url,
                "has_person": bool(r.person),
                "has_active_auth": r.person in live_guardians if r.person else False,
            }
        )
    return _ok(items)


@frappe.whitelist()
def create_pickup_auths(student, guardians, valid_from=None, valid_to=None):
    """Thêm ủy quyền đón BẰNG TAY: 1 học sinh + nhiều guardian.

    Cả student lẫn guardians đều là FaceID Person (guardian bắt buộc đã có trong
    danh sách Person — validate của doctype chặn loại sai). Cặp đang có ủy quyền
    sống → bỏ qua; cặp đã revoked → áp dụng lại với hạn mới (giữ version trail).
    """
    guardian_list = (
        frappe.parse_json(guardians) if isinstance(guardians, str) else (guardians or [])
    )
    if not guardian_list:
        return _err("Chưa chọn guardian nào")
    if frappe.db.get_value("FaceID Person", student, "person_type") != "student":
        return _err("Student phải là FaceID Person loại student")

    default_from, default_to = _pickup_default_validity()
    vf = frappe.utils.getdate(valid_from) if valid_from else default_from
    vt = frappe.utils.getdate(valid_to) if valid_to else default_to
    if vf > vt:
        return _err("Từ ngày phải <= Đến ngày")

    created = reapplied = skipped_active = 0
    errors = []
    for g in guardian_list:
        existing = frappe.get_all(
            "FaceID Pickup Authorization",
            filters={"guardian": g, "student": student},
            fields=["name", "revoked"],
        )
        if any(not cint(a.revoked) for a in existing):
            skipped_active += 1
            continue
        try:
            if existing:
                doc = frappe.get_doc("FaceID Pickup Authorization", existing[0].name)
                doc.revoked = 0
                doc.valid_from = vf
                doc.valid_to = vt
                doc.save(ignore_permissions=True)
                create_device_sync_job("reapply_pickup", doc.doctype, doc.name, priority=9)
                reapplied += 1
            else:
                frappe.get_doc(
                    {
                        "doctype": "FaceID Pickup Authorization",
                        "guardian": g,
                        "student": student,
                        "valid_from": vf,
                        "valid_to": vt,
                        "method": "face",
                        "revoked": 0,
                    }
                ).insert(ignore_permissions=True)
                created += 1
        except Exception as e:
            errors.append(f"{g}: {e}")
            frappe.log_error(
                title=f"FaceID create_pickup_auths {g}->{student}",
                message=frappe.get_traceback(),
            )

    return _ok(
        {
            "created": created,
            "reapplied": reapplied,
            "skipped_active": skipped_active,
            "errors": errors,
        },
        message=f"Tạo {created}, áp dụng lại {reapplied}, bỏ qua {skipped_active} đang hiệu lực",
    )


def _relationship_has_can_pickup() -> bool:
    """
    `can_pickup` là field MỚI của CRM Family Relationship — chỉ tồn tại sau `bench migrate`.
    Chưa migrate thì giữ hành vi cũ (mọi quan hệ đều được đón) thay vì làm chết endpoint.
    """
    try:
        return bool(frappe.db.has_column("CRM Family Relationship", "can_pickup"))
    except Exception:
        return False


def _canonical_family_pickup_rows(campus_id=None):
    """
    Quan hệ gia đình CHUẨN đã map sang FaceID Person, kèm cờ `can_pickup`.

    BẢN CHUẨN = dòng dưới `CRM Family.relationships` (parentfield = 'relationships') của
    family còn sống (docstatus < 2). Hai bản mirror — `CRM Student.family_relationships`
    và `CRM Guardian.student_relationships` — CÓ THỂ CŨ. Bản cũ của hàm này quét cả ba
    bản nên guardian đã bị gỡ khỏi gia đình VẪN được cấp uỷ quyền đón ở cổng: đây là
    an ninh vật lý, không chỉ là lỗi dữ liệu.

    Predicate giống hệt `canonical_relationship_rows()` trong
    erp/utils/family_relationship.py. Không gọi lại được helper đó vì nó bắt buộc scope
    theo một guardian/student (để khỏi quét cả bảng), còn đây là sweep toàn hệ thống;
    hai cột `guardian`/`student` của child table chưa có index nên chạy N query rời sẽ
    thành N lần full scan — một câu JOIN là đúng cho lô lớn.

    KHÔNG giới hạn số dòng: bản cũ hardcode `limit=10000` nên vượt ngưỡng là cắt IM LẶNG,
    một phần gia đình không bao giờ được cấp uỷ quyền mà không ai biết.
    """
    # NULL chỉ xảy ra với dòng ghi trước khi có field; theo default của doctype = 1.
    can_pickup_expr = (
        "IFNULL(fr.can_pickup, 1)" if _relationship_has_can_pickup() else "1"
    )
    conds = [
        "fr.parentfield = 'relationships'",
        "f.docstatus < 2",
        "IFNULL(fr.guardian, '') != ''",
        "IFNULL(fr.student, '') != ''",
    ]
    params = {}
    if campus_id:
        # Campus của HỌC SINH quyết định cổng đón. Giữ lại dòng chưa map FaceID Person
        # để còn đếm/log được (không cấp uỷ quyền cho chúng).
        conds.append("(sp.name IS NULL OR sp.campus_id = %(campus_id)s)")
        params["campus_id"] = campus_id
    return frappe.db.sql(
        """
        SELECT
            fr.guardian AS crm_guardian,
            fr.student AS crm_student,
            {can_pickup} AS can_pickup,
            gp.name AS guardian_person,
            sp.name AS student_person
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON fr.parent = f.name
        LEFT JOIN `tabFaceID Person` gp
            ON gp.crm_guardian = fr.guardian AND gp.person_type = 'guardian'
        LEFT JOIN `tabFaceID Person` sp
            ON sp.crm_student = fr.student AND sp.person_type = 'student'
        WHERE {conds}
        """.format(can_pickup=can_pickup_expr, conds=" AND ".join(conds)),
        params,
        as_dict=True,
    )


def _revoke_pickup_doc(name):
    """
    Thu hồi một uỷ quyền. `on_update` của doctype tự enqueue job `revoke_pickup`
    (create_device_sync_job dedup theo ref_name nên không sợ trùng job).
    Dùng doc.save() chứ không db.set_value để giữ version trail — bản ghi này là
    chứng từ an ninh, phải biết ai thu hồi lúc nào.
    """
    doc = frappe.get_doc("FaceID Pickup Authorization", name)
    doc.revoked = 1
    doc.save(ignore_permissions=True)


@frappe.whitelist()
def sync_family_pickup(campus_id=None, revoke_missing=0):
    """
    Cấp / thu hồi uỷ quyền đón ĐỨNG theo quan hệ gia đình.

    Nguồn: BẢN CHUẨN của CRM Family Relationship + cờ `can_pickup` — quyền VẬN HÀNH
    (đón ở cổng), độc lập với `access` là quyền XEM thông tin. Người đưa đón được thuê
    có can_pickup = 1 / access = 0; bố mẹ bị hạn chế thông tin thì ngược lại.

    CẤP: cặp (guardian, student) có ít nhất một dòng chuẩn can_pickup = 1 và chưa có
    bản ghi uỷ quyền nào -> tạo mới.

    THU HỒI (luôn chạy): cặp CÒN quan hệ chuẩn nhưng KHÔNG dòng nào cho đón — tức có
    người bỏ tick can_pickup. Đây là ý chí rõ ràng của nhà trường nên thu hồi ngay.

    THU HỒI cặp KHÔNG CÒN quan hệ chuẩn nào: chỉ khi truyền revoke_missing = 1. Mặc định
    TẮT vì `FaceID Pickup Authorization` không ghi nguồn tạo: uỷ quyền do văn phòng thêm
    tay (người đón đột xuất, người ngoài gia đình) cũng "không có quan hệ chuẩn" và sẽ bị
    thu hồi oan. Khi tắt, hàm vẫn TRẢ VỀ danh sách ứng viên để vận hành rà tay.

    KHÔNG tự bỏ thu hồi (un-revoke): bản ghi đã revoked có thể do người thật thu hồi vì
    lý do an ninh mà can_pickup chưa kịp cập nhật -> fail closed; mở lại bằng
    reapply_pickup_auth.
    """
    today = date.today()
    school_year = frappe.db.get_value("SIS School Year", {"is_enable": 1}, ["start_date", "end_date"], as_dict=True)
    valid_from = school_year.start_date if school_year else today
    valid_to = school_year.end_date if school_year else today
    revoke_missing = cint(revoke_missing)
    logger = frappe.logger("faceid")

    rows = _canonical_family_pickup_rows(campus_id)
    missing_person = 0
    allowed_pairs = set()
    known_pairs = set()
    for r in rows:
        if not r.get("guardian_person") or not r.get("student_person"):
            # Chưa đồng bộ FaceID Person cho guardian/student -> chưa cấp được.
            missing_person += 1
            continue
        pair = (r["guardian_person"], r["student_person"])
        known_pairs.add(pair)
        if cint(r.get("can_pickup")) == 1:
            # Gộp theo cặp với quy ước OR — một dòng cho đón là được đón — giống
            # accessible_relationship_rows() ở erp/utils/family_access.py. Nhánh cấp và
            # nhánh thu hồi PHẢI dùng cùng vị từ, lệch nhau là mỗi lần chạy lại
            # tạo–thu hồi qua lại (flapping).
            allowed_pairs.add(pair)

    if not rows:
        # Không đọc được dòng chuẩn nào -> coi là lỗi đọc/dữ liệu, KHÔNG thu hồi hàng loạt.
        logger.warning(
            f"[sync_family_pickup] campus={campus_id}: 0 dòng quan hệ chuẩn — bỏ qua, không cấp/thu hồi"
        )
        return _ok(
            {"created": 0, "scanned_relationships": 0},
            message="Không tìm thấy quan hệ gia đình chuẩn nào — không cấp/thu hồi gì",
        )

    existing_by_pair = {}
    for a in frappe.get_all(
        "FaceID Pickup Authorization",
        fields=["name", "guardian", "student", "revoked"],
        limit_page_length=0,
    ):
        existing_by_pair.setdefault((a.guardian, a.student), []).append(a)

    # Lọc campus cho nhánh thu hồi: chỉ chạm uỷ quyền của học sinh thuộc campus đang xét.
    campus_students = None
    if campus_id:
        campus_students = set(
            frappe.get_all(
                "FaceID Person",
                filters={"person_type": "student", "campus_id": campus_id},
                pluck="name",
                limit_page_length=0,
            )
        )

    created = 0
    skipped_existing = 0
    errors = []
    for g_person, s_person in sorted(allowed_pairs):
        if (g_person, s_person) in existing_by_pair:
            skipped_existing += 1
            continue
        try:
            frappe.get_doc(
                {
                    "doctype": "FaceID Pickup Authorization",
                    "guardian": g_person,
                    "student": s_person,
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                    "method": "face",
                    "revoked": 0,
                }
            ).insert(ignore_permissions=True)
            created += 1
        except Exception:
            # Một cặp lỗi không được làm chết cả lô.
            errors.append(f"create {g_person}->{s_person}")
            frappe.log_error(
                title=f"FaceID sync_family_pickup create {g_person}->{s_person}",
                message=frappe.get_traceback(),
            )

    revoked_no_permission = 0
    revoked_no_relationship = 0
    revoke_candidates = []
    for (g_person, s_person), auths in existing_by_pair.items():
        if campus_students is not None and s_person not in campus_students:
            continue
        if (g_person, s_person) in allowed_pairs:
            continue
        live = [a for a in auths if not cint(a.revoked)]
        if not live:
            continue
        # Còn quan hệ chuẩn mà không được đón = có người bỏ tick can_pickup (ý chí rõ ràng).
        explicit_deny = (g_person, s_person) in known_pairs
        if not explicit_deny and not revoke_missing:
            revoke_candidates.extend(
                {"authorization": a.name, "guardian": g_person, "student": s_person}
                for a in live
            )
            continue
        for a in live:
            try:
                _revoke_pickup_doc(a.name)
                if explicit_deny:
                    revoked_no_permission += 1
                else:
                    revoked_no_relationship += 1
            except Exception:
                errors.append(f"revoke {a.name}")
                frappe.log_error(
                    title=f"FaceID sync_family_pickup revoke {a.name}",
                    message=frappe.get_traceback(),
                )

    if created or revoked_no_permission or revoked_no_relationship:
        # Lớp 2: đẩy snapshot toàn bộ uỷ quyền còn hiệu lực xuống controller local, để
        # cache ở cổng vẫn hội tụ nếu một job lẻ nào thất bại.
        create_device_sync_job(
            "reconcile_pickup", "FaceID Pickup Authorization", "__bulk__", priority=10
        )

    data = {
        "created": created,
        "skipped_existing": skipped_existing,
        "revoked_no_permission": revoked_no_permission,
        "revoked_no_relationship": revoked_no_relationship,
        "revoke_candidate_count": len(revoke_candidates),
        "revoke_candidates": revoke_candidates[:50],
        "missing_faceid_person": missing_person,
        "scanned_relationships": len(rows),
        "allowed_pairs": len(allowed_pairs),
        "can_pickup_column": _relationship_has_can_pickup(),
        "errors": errors[:50],
    }
    logger.info(
        f"[sync_family_pickup] campus={campus_id} revoke_missing={revoke_missing} "
        f"scanned={len(rows)} pairs={len(known_pairs)} allowed={len(allowed_pairs)} "
        f"created={created} existing={skipped_existing} "
        f"revoked_no_permission={revoked_no_permission} "
        f"revoked_no_relationship={revoked_no_relationship} "
        f"candidates={len(revoke_candidates)} missing_person={missing_person} "
        f"can_pickup_column={data['can_pickup_column']} errors={len(errors)}"
    )
    message = f"Đã cấp {created} uỷ quyền, thu hồi {revoked_no_permission + revoked_no_relationship}"
    if revoke_candidates:
        message += f", {len(revoke_candidates)} uỷ quyền không còn quan hệ gia đình cần rà tay"
    return _ok(data, message=message)


# ---- Gate Events ----


@frappe.whitelist()
def list_gate_events(
    limit=50,
    event_type=None,
    external_code=None,
    from_date=None,
    to_date=None,
):
    filters = {}
    if event_type:
        filters["event_type"] = event_type
    if external_code:
        filters["external_code"] = external_code
    if from_date:
        filters["occurred_at"] = [">=", from_date]
    rows = frappe.get_all(
        "FaceID Gate Event",
        filters=filters,
        fields=[
            "name",
            "serial_key",
            "device",
            "event_type",
            "external_code",
            "occurred_at",
            "bridged_attendance",
        ],
        order_by="occurred_at desc",
        limit=int(limit),
    )
    return _ok(rows)


def _fmt_event_time(value):
    """ISO UTC từ controller → giờ hệ thống (site timezone)."""
    if not value:
        return value
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo:
        try:
            from zoneinfo import ZoneInfo

            from frappe.utils import get_system_timezone

            dt = dt.astimezone(ZoneInfo(get_system_timezone()))
        except Exception:
            pass
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@frappe.whitelist()
def list_gate_events_live(limit=100, event_type=None, external_code=None):
    """Đọc event trực tiếp từ controller local qua tunnel — không đụng DB Frappe."""
    query = {"limit": cint(limit) or 100}
    if event_type:
        query["event_type"] = event_type
    if external_code:
        query["employee_no"] = external_code
    try:
        res = gateway_get(f"/api/events?{urlencode(query)}")
    except Exception as e:
        return _err(f"Không nối được controller local: {e}")
    rows = []
    for e in (res or {}).get("events") or []:
        payload = e.get("payload") or {}
        rows.append(
            {
                "name": f"live-{e.get('id')}",
                "serial_key": str(e.get("serial_no") or ""),
                "device": e.get("device_name")
                or e.get("device_ip")
                or payload.get("remoteHostAddr")
                or payload.get("_source_ip"),
                "event_type": e.get("event_type"),
                "external_code": e.get("employee_no"),
                "person_name": payload.get("name"),
                "occurred_at": _fmt_event_time(e.get("occurred_at")),
                "bridged_attendance": 0,
            }
        )
    return _ok(rows)


# ---- Devices ----


def _device_ip(name: str) -> str:
    ip = frappe.db.get_value("FaceID Device", name, "ip")
    if not ip:
        frappe.throw(f"Không tìm thấy thiết bị {name}")
    return str(ip).split("/")[0]


@frappe.whitelist()
def list_devices():
    rows = frappe.get_all(
        "FaceID Device",
        fields=[
            "name",
            "device_name",
            "ip",
            "gate_type",
            "direction",
            "gate_no",
            "is_pickup_gate",
            "status",
            "last_seen",
            "username",
            "https",
            "auth_mode",
            "controller_device_id",
            "campus_id",
            "model",
            "device_group",
            "enable_remote_check",
            "auto_provision",
            "note",
            "person_count",
            "face_count",
            "device_time",
            "last_status_at",
            "push_status",
            "last_error",
        ],
        order_by="device_name asc",
    )
    return _ok(rows)


@frappe.whitelist()
def save_device(data):
    payload = frappe.parse_json(data) if isinstance(data, str) else data
    name = payload.get("name")
    new_password = payload.pop("password", None)
    if name and frappe.db.exists("FaceID Device", name):
        doc = frappe.get_doc("FaceID Device", name)
        doc.update(payload)
        if new_password:
            doc.password = new_password
    else:
        doc = frappe.get_doc({"doctype": "FaceID Device", **payload})
        if new_password:
            doc.password = new_password
    doc.save(ignore_permissions=True)
    return _ok(doc.as_dict())


@frappe.whitelist()
def delete_device(name):
    doc = frappe.get_doc("FaceID Device", name)
    if doc.controller_device_id:
        try:
            gateway_delete(f"/api/devices/{doc.controller_device_id}")
        except Exception:
            frappe.log_error(title=f"FaceID delete device {name}", message=frappe.get_traceback())
    frappe.delete_doc("FaceID Device", name, ignore_permissions=True)
    return _ok(message="Đã xóa thiết bị")


@frappe.whitelist()
def get_device_status(name):
    """Đọc giờ máy + số person/face + ảnh standby từ controller, cache vào doc."""
    from erp.api.faceid.device_gateway import fetch_device_status

    doc = frappe.get_doc("FaceID Device", name)
    return _ok(fetch_device_status(doc))


@frappe.whitelist()
def probe_device(name):
    """Bắt tay ISAPI với terminal — kiểm tra IP + credential có đúng không."""
    from erp.api.faceid.device_gateway import mark_device_offline

    ip = _device_ip(name)
    try:
        res = gateway_post(f"/api/devices/{ip}/probe", {})
    except Exception as e:
        mark_device_offline(name, e)
        return _err(f"Không kết nối được tới máy {ip}: {e}")
    frappe.db.set_value(
        "FaceID Device",
        name,
        {
            "status": "online",
            "last_seen": frappe.utils.now(),
            "last_status_at": frappe.utils.now(),
            "last_error": None,
        },
        update_modified=False,
    )
    return _ok(res, message=f"Kết nối tới {ip} OK")


@frappe.whitelist()
def list_device_screen_images(name):
    ip = _device_ip(name)
    res = gateway_get(f"/api/devices/{ip}/screen-images")
    return _ok(res)


@frappe.whitelist()
def upload_device_screen_image(name):
    ip = _device_ip(name)
    upload = frappe.request.files.get("file")
    if not upload:
        frappe.throw("Thiếu file ảnh (field `file`)")
    res = gateway_post_file(
        f"/api/devices/{ip}/screen-image",
        upload.stream.read(),
        filename=upload.filename or "screen.jpg",
    )
    return _ok(res)


@frappe.whitelist()
def delete_device_screen_image(name, uuid):
    ip = _device_ip(name)
    res = gateway_delete(f"/api/devices/{ip}/screen-image/{uuid}")
    return _ok(res)


@frappe.whitelist()
def provision_device(name):
    create_device_sync_job("provision_device", "FaceID Device", name, priority=6)
    return _ok(message="Đã xếp hàng provision thiết bị")


@frappe.whitelist()
def get_gateway_status():
    """Tình trạng đường nối Frappe → controller local (hiển thị trên UI máy)."""
    cfg = get_gateway_config()
    configured = bool(cfg["base_url"])
    online = gateway_healthz() if configured else False
    version = None
    if online:
        try:
            version = (gateway_get("/api/healthz") or {}).get("version")
        except Exception:
            version = None
    return _ok(
        {
            "configured": configured,
            "online": online,
            "base_url": cfg["base_url"],
            "version": version,
            "device_count": frappe.db.count("FaceID Device"),
        }
    )


@frappe.whitelist()
def refresh_devices_status(name=None):
    """Đọc trạng thái live từ controller cho 1 máy hoặc toàn bộ."""
    from erp.api.faceid.device_gateway import fetch_device_status, mark_device_offline
    from erp.api.faceid.sync_worker import refresh_all_device_status

    if name:
        doc = frappe.get_doc("FaceID Device", name)
        try:
            return _ok(fetch_device_status(doc))
        except Exception as e:
            mark_device_offline(name, e)
            return _err(f"Không đọc được trạng thái máy: {e}")

    result = refresh_all_device_status()
    if result.get("skipped"):
        return _err("Controller local không phản hồi — kiểm tra WireGuard tunnel", result)
    return _ok(result, message=f"Đã kiểm tra {result.get('checked', 0)} máy")


@frappe.whitelist()
def retry_device_push(name):
    """Đẩy lại khai báo máy xuống controller (khi lần lưu trước bị lỗi tunnel)."""
    from erp.api.faceid.device_gateway import push_device_to_controller

    doc = frappe.get_doc("FaceID Device", name)
    try:
        push_device_to_controller(doc)
    except Exception as e:
        frappe.db.set_value(
            "FaceID Device",
            name,
            {"push_status": "failed", "last_error": str(e)[:500]},
            update_modified=False,
        )
        return _err(f"Vẫn chưa đẩy được xuống controller: {e}")
    return _ok(message="Đã đẩy khai báo máy xuống controller")


@frappe.whitelist()
def discover_unregistered_devices(limit=500):
    """Máy đang đẩy event về listener nhưng chưa được khai báo trên WIS.

    Controller ghi event với device_id NULL nếu IP nguồn chưa có trong bảng
    devices — IP thật nằm trong payload.remoteHostAddr.
    """
    res = gateway_get(f"/api/events?limit={cint(limit) or 500}")
    events = (res or {}).get("events") or []
    known_ips = {
        str(ip).split("/")[0]
        for ip in frappe.get_all("FaceID Device", pluck="ip")
        if ip
    }
    found: dict[str, dict] = {}
    for e in events:
        payload = e.get("payload") or {}
        ip = e.get("device_ip") or payload.get("_source_ip") or payload.get("remoteHostAddr")
        if not ip or e.get("device_id"):
            continue
        ip = str(ip).split("/")[0]
        if ip in known_ips:
            continue
        item = found.setdefault(
            ip,
            {
                "ip": ip,
                "device_name": payload.get("deviceName"),
                "event_count": 0,
                "last_event_at": e.get("occurred_at"),
            },
        )
        item["event_count"] += 1
        if not item.get("device_name") and payload.get("deviceName"):
            item["device_name"] = payload.get("deviceName")
    return _ok(sorted(found.values(), key=lambda x: -x["event_count"]))


# ---- Sync status ----


@frappe.whitelist()
def get_sync_status(person_type=None):
    person_filters = {}
    if person_type:
        person_filters["person_type"] = person_type

    job_stats = person_sync_job_stats(person_type)
    persons_pending = frappe.db.count(
        "FaceID Person", {**person_filters, "sync_status": "pending"}
    )
    persons_synced = frappe.db.count(
        "FaceID Person", {**person_filters, "sync_status": "synced", "is_active": 1}
    )
    persons_on_device = frappe.db.count(
        "FaceID Person", {**person_filters, "on_device": 1}
    )
    persons_error = frappe.db.count(
        "FaceID Person", {**person_filters, "sync_status": "error"}
    )

    sample_errors: list[dict] = []
    type_clause = ""
    err_params: list = []
    if person_type:
        type_clause = " AND p.person_type = %s"
        err_params.append(person_type)
    err_rows = frappe.db.sql(
        f"""
        SELECT j.name, j.ref_name, j.last_error, j.attempts
        FROM `tabFaceID Device Sync Job` j
        INNER JOIN `tabFaceID Person` p ON p.name = j.ref_name
        WHERE j.ref_doctype = 'FaceID Person'
          AND j.job_type IN ('apply_person_access', 'delete_person')
          AND j.state = 'failed'
          AND j.last_error IS NOT NULL AND j.last_error != ''
          {type_clause}
        ORDER BY j.modified DESC
        LIMIT 5
        """,
        tuple(err_params),
        as_dict=True,
    )
    for row in err_rows:
        sample_errors.append(
            {
                "job": row.name,
                "person": row.ref_name,
                "error": row.last_error,
                "attempts": row.attempts,
            }
        )

    return _ok(
        {
            **job_stats,
            "persons_pending": persons_pending,
            "persons_synced": persons_synced,
            "persons_on_device": persons_on_device,
            "persons_error": persons_error,
            "sample_errors": sample_errors,
        }
    )


@frappe.whitelist()
def retry_failed_person_sync_jobs(person_type=None, limit=2000):
    """Thử lại job person failed (operator)."""
    from erp.api.faceid.sync_worker import (
        dedupe_failed_person_sync_jobs,
        drain_pending_device_sync_jobs,
        retry_failed_sync_jobs,
    )

    deduped = dedupe_failed_person_sync_jobs(person_type)
    retried = retry_failed_sync_jobs(person_type, int(limit))
    if retried:
        frappe.enqueue(
            "erp.api.faceid.sync_worker.drain_pending_device_sync_jobs",
            queue="long",
            timeout=7200,
            enqueue_after_commit=True,
        )
    return _ok(
        {"retried": retried, "deduped": deduped, **person_sync_job_stats(person_type)},
        message=f"Đã dọn {deduped} job trùng, đưa {retried} job lỗi vào hàng chờ lại",
    )


@frappe.whitelist()
def list_sync_jobs(state=None, limit=20):
    filters = {}
    if state:
        filters["state"] = state
    rows = frappe.get_all(
        "FaceID Device Sync Job",
        filters=filters,
        fields=["name", "job_type", "ref_name", "state", "attempts", "last_error", "creation"],
        order_by="creation desc",
        limit=int(limit),
    )
    return _ok(rows)


@frappe.whitelist()
def search_person_candidates(person_type, search=None, limit=30):
    """Tìm HS/NV/PH chưa enroll hoặc để link."""
    limit = int(limit)
    if person_type == "student":
        filters = {}
        if search:
            filters["student_name"] = ["like", f"%{search}%"]
        rows = frappe.get_all(
            "CRM Student",
            filters=filters,
            fields=["name", "student_name", "student_code", "campus_id"],
            limit=limit,
        )
        return _ok(rows)
    if person_type == "guardian":
        filters = {}
        if search:
            filters["guardian_name"] = ["like", f"%{search}%"]
        rows = frappe.get_all(
            "CRM Guardian",
            filters=filters,
            fields=["name", "guardian_name", "guardian_id"],
            limit=limit,
        )
        return _ok(rows)
    if person_type == "staff":
        filters = {"enabled": 1}
        if search:
            filters["full_name"] = ["like", f"%{search}%"]
        rows = frappe.get_all(
            "User",
            filters=filters,
            fields=["name", "full_name", "employee_code"],
            limit=limit,
        )
        return _ok(rows)
    return _err("person_type không hợp lệ")
