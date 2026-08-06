# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt
"""
LÕI ĐĂNG KÝ CÂU LẠC BỘ — nơi DUY NHẤT được ghi `SIS Club Registration` và
`SIS Club Offering.registered_count`.

VÌ SAO PHẢI TẬP TRUNG MỘT CHỖ
-----------------------------
Cả API phụ huynh (erp/api/parent_portal/club_registration.py) lẫn API nhà trường
(erp/api/erp_sis/club.py) đều gọi vào đây. Nếu mỗi bên tự "đếm rồi insert" thì
chức năng staff đổi môn sẽ âm thầm làm vượt giới hạn số lượng: hai đường ghi
không cùng lấy một khoá thì không serialize được với nhau.

    ⚠️ Mọi code tương lai insert SIS Club Registration mà KHÔNG qua module này
    đều vô hiệu hoá cơ chế chống vượt slot. Hai UNIQUE index (xem patch
    erp/patches/v1_0/add_club_registration_unique_indexes.py) là lưới cuối cùng,
    nhưng index chỉ chặn được TRÙNG, không chặn được VƯỢT SLOT.

HAI LUẬT NGHIỆP VỤ
------------------
    1. Mỗi học sinh tối đa 1 môn / thứ.
    2. Mỗi học sinh tối đa 1 đăng ký / 1 môn / 1 đợt — kể cả khi môn đó được mở
       ở nhiều thứ khác nhau.

Cả hai đều được ép ở tầng DB bằng UNIQUE index trên `active_student_key`, nên
kể cả khi lock ở đây hỏng thì dữ liệu vẫn không sai.

VÌ SAO `COUNT(*) ... FOR UPDATE` CHỨ KHÔNG PHẢI `frappe.db.count()`
-------------------------------------------------------------------
MariaDB mặc định chạy REPEATABLE READ. `SELECT ... FOR UPDATE` là *locking read*
nên đọc bản committed MỚI NHẤT, nhưng một `COUNT(*)` thường là *consistent read*
— nó trả về snapshot của transaction, vốn đã được thiết lập từ câu đọc ĐẦU TIÊN
của request (thường sớm hơn nhiều so với lúc ta lấy khoá). Đếm kiểu đó sẽ đọc số
CŨ và cho vượt slot, dù đã khoá dòng offering thành công. Vì đã giữ khoá trên
chính offering đó nên gap lock của câu COUNT chỉ đụng phạm vi của offering này —
vốn đã bị serialize sẵn, không làm tăng nguy cơ deadlock.
"""

import time

import frappe
from frappe.utils import now_datetime

from erp.sis.utils import club_days

DT_PERIOD = "SIS Club Registration Period"
DT_OFFERING = "SIS Club Offering"
DT_REGISTRATION = "SIS Club Registration"

MAX_LOCK_ATTEMPTS = 3
LOCK_WAIT_TIMEOUT_SECONDS = 10

# Re-export: nguồn sự thật nằm ở `club_days`, giữ tên ở đây để các module đang
# `from ...club_registration import DAY_ORDER` không phải đổi import.
DAY_LABELS_EN = club_days.DAY_LABELS_EN
DAY_LABELS_VN = club_days.DAY_LABELS_VN
DAY_ORDER = club_days.DAY_ORDER


class ClubRegError(Exception):
    """Lỗi nghiệp vụ có mã — FE map mã sang thông báo song ngữ, không đọc chuỗi VN."""

    def __init__(self, code, message, offering_id=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.offering_id = offering_id

    def as_dict(self):
        return {"offering_id": self.offering_id, "code": self.code, "message": self.message}


# ----------------------------------------------------------------------
# Tiện ích nội bộ
# ----------------------------------------------------------------------


def _is_deadlock(exc) -> bool:
    """Deadlock (1213) hoặc lock wait timeout (1205) — hai lỗi ĐÁNG retry."""
    code = getattr(exc, "args", [None])[0]
    if code in (1213, 1205):
        return True
    text = str(exc).lower()
    return "deadlock" in text or "lock wait timeout" in text


def _classify_duplicate(exc):
    """
    Phân biệt hai UNIQUE index qua TÊN INDEX trong thông báo lỗi của driver.

    Bắt được IntegrityError ở đây là thứ ngăn Frappe trả HTTP 500 khi hai request
    của cùng một học sinh chạy song song — trường hợp rất thường gặp khi phụ huynh
    bấm nút hai lần.
    """
    text = str(exc)
    if "uq_club_reg_student_subject" in text:
        return "ALREADY_REGISTERED", "Học sinh đã đăng ký môn này rồi"
    if "uq_club_reg_student_day" in text:
        return "DAY_TAKEN", "Học sinh đã có một môn khác vào thứ này"
    if "Duplicate entry" in text or isinstance(
        exc, getattr(frappe.exceptions, "DuplicateEntryError", ())
    ):
        return "ALREADY_REGISTERED", "Đăng ký bị trùng"
    return None, None


def day_label(day, lang="vi"):
    table = DAY_LABELS_EN if lang == "en" else DAY_LABELS_VN
    return table.get(day, day)


def get_student_context(student_id, period):
    """
    Lớp chính quy + khối của học sinh tại thời điểm đăng ký.

    Học sinh chưa được xếp lớp thì không suy ra được khối => không khớp được với
    `education_grades` của môn. Trả về lỗi có mã riêng để Parent Portal hiển thị
    thông báo tử tế thay vì "có lỗi xảy ra".
    """
    from erp.utils.student_class import get_regular_class_row

    row = get_regular_class_row(student_id, school_year_id=period.school_year_id)
    if not row:
        raise ClubRegError(
            "NO_REGULAR_CLASS",
            "Học sinh chưa được xếp lớp trong năm học này nên chưa thể đăng ký câu lạc bộ. "
            "Vui lòng liên hệ nhà trường.",
        )

    education_grade_id = frappe.db.get_value("SIS Class", row.get("class_id"), "education_grade")
    return {
        "class_id": row.get("class_id"),
        "class_title": row.get("class_title"),
        "education_grade_id": education_grade_id,
        "school_year_id": row.get("school_year_id") or period.school_year_id,
    }


def get_offering_grade_ids(offering_id):
    rows = frappe.get_all(
        "SIS Club Offering Grade",
        filters={"parent": offering_id, "parenttype": DT_OFFERING},
        fields=["education_grade_id"],
    )
    return {r.education_grade_id for r in rows}


def get_active_registrations(period_id, student_id):
    """Các đăng ký còn hiệu lực của một học sinh trong một đợt."""
    return frappe.get_all(
        DT_REGISTRATION,
        filters={"period_id": period_id, "student_id": student_id, "status": "active"},
        fields=[
            "name",
            "offering_id",
            "subject_id",
            "day_of_week",
            "registration_datetime",
        ],
        order_by="registration_datetime asc",
    )


def recalculate_registered_counts(period_id=None, offering_ids=None):
    """
    Sửa chữa `registered_count` từ số đếm thật.

    Bình thường counter không lệch được vì chỉ được ghi bên trong lock. Hàm này
    dành cho trường hợp có người sửa dữ liệu ngoài luồng (bench console, import).
    """
    conditions = []
    values = {}
    if period_id:
        conditions.append("o.period_id = %(period_id)s")
        values["period_id"] = period_id
    if offering_ids:
        conditions.append("o.name IN %(offering_ids)s")
        values["offering_ids"] = tuple(offering_ids)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    frappe.db.sql(
        f"""
        UPDATE `tab{DT_OFFERING}` o
        SET o.registered_count = (
            SELECT COUNT(*) FROM `tab{DT_REGISTRATION}` r
            WHERE r.offering_id = o.name AND r.status = 'active'
        )
        {where}
        """,
        values,
    )
    frappe.db.commit()


def _sync_count_locked(offering_id):
    """Đếm lại và ghi counter. CHỈ gọi khi đang giữ khoá dòng offering."""
    used = frappe.db.sql(
        f"""
        SELECT COUNT(*) FROM `tab{DT_REGISTRATION}`
        WHERE offering_id = %s AND status = 'active'
        FOR UPDATE
        """,
        (offering_id,),
    )[0][0]
    frappe.db.set_value(
        DT_OFFERING, offering_id, "registered_count", used, update_modified=False
    )
    return used


def _lock_offerings(offering_ids):
    """
    Khoá các dòng offering theo THỨ TỰ TĂNG DẦN của `name`.

    Sắp xếp là BẮT BUỘC: hai request cùng chọn một tập môn nhưng khoá theo thứ tự
    khác nhau sẽ khoá chéo và deadlock. Cùng thứ tự thì chúng chỉ nối đuôi nhau.
    """
    ordered = sorted(set(offering_ids))
    if not ordered:
        return []
    placeholders = ", ".join(["%s"] * len(ordered))
    return frappe.db.sql(
        f"""
        SELECT name, period_id, subject_id, capacity, day_of_week, status, title_vn, title_en
        FROM `tab{DT_OFFERING}`
        WHERE name IN ({placeholders})
        ORDER BY name
        FOR UPDATE
        """,
        tuple(ordered),
        as_dict=True,
    )


def _rollback_to(save_point):
    """
    Rollback tới savepoint, có phương án dự phòng.

    Savepoint có thể đã biến mất (vd transaction bị engine rollback toàn bộ), khi
    đó `rollback to savepoint` sẽ ném lỗi mới và che mất lỗi gốc.
    """
    try:
        frappe.db.rollback(save_point=save_point)
    except Exception:
        frappe.db.rollback()


def _set_short_lock_timeout():
    """
    Fail nhanh thay vì treo worker.

    Mặc định `innodb_lock_wait_timeout` là 50 giây; lúc mở cổng đăng ký mà một
    request kẹt thì cả gunicorn worker đứng theo. 10 giây đủ rộng cho một
    transaction dưới 10 ms và đủ ngắn để trả `SYSTEM_BUSY` kịp thời.
    """
    try:
        frappe.db.sql(f"SET SESSION innodb_lock_wait_timeout = {LOCK_WAIT_TIMEOUT_SECONDS}")
    except Exception:
        # Không phải MariaDB/InnoDB (vd Postgres) — bỏ qua, không phải lỗi chí mạng.
        pass


# ----------------------------------------------------------------------
# Kiểm tra không cần khoá (fail fast, rẻ)
# ----------------------------------------------------------------------


def _prevalidate(period, student_id, offering_ids, enforce_window, ignore_registration_ids=None):
    """
    Trả về (offerings_by_id, student_ctx, pending_ids, skipped, failed).

    `skipped` là các môn học sinh đã đăng ký rồi — KHÔNG coi là lỗi, giúp thao tác
    bấm hai lần trở nên vô hại.

    `ignore_registration_ids` là các đăng ký sắp bị huỷ trong CÙNG một lô sửa.
    Không bỏ qua chúng thì mọi thao tác đổi môn đều bị chính đăng ký cũ chặn:
    đổi Ballet(thứ 2) sang Art&Craft(thứ 2) sẽ dính DAY_TAKEN, đổi một môn sang
    thứ khác sẽ bị coi là ALREADY_REGISTERED.
    """
    ignore_registration_ids = set(ignore_registration_ids or [])
    skipped = []
    failed = []

    if period.status != "Open":
        raise ClubRegError("PERIOD_CLOSED", "Đợt đăng ký chưa mở hoặc đã đóng")

    if enforce_window and not period.is_within_registration_window():
        raise ClubRegError(
            "OUT_OF_WINDOW", "Hiện chưa đến hoặc đã hết thời gian đăng ký"
        )

    student_ctx = get_student_context(student_id, period)

    offerings = {}
    for oid in offering_ids:
        row = frappe.db.get_value(
            DT_OFFERING,
            oid,
            ["name", "period_id", "subject_id", "capacity", "day_of_week", "status", "title_vn"],
            as_dict=True,
        )
        if not row or row.period_id != period.name:
            failed.append(
                ClubRegError("CLUB_NOT_FOUND", "Môn học không thuộc đợt đăng ký này", oid).as_dict()
            )
            continue
        if row.status != "active":
            failed.append(
                ClubRegError("CLUB_INACTIVE", "Môn học đã ngừng nhận đăng ký", oid).as_dict()
            )
            continue
        offerings[oid] = row

    # Khối của học sinh phải nằm trong danh sách khối áp dụng của môn.
    for oid, row in list(offerings.items()):
        grade_ids = get_offering_grade_ids(oid)
        if student_ctx["education_grade_id"] not in grade_ids:
            failed.append(
                ClubRegError(
                    "GRADE_NOT_ELIGIBLE",
                    f"Môn {row.title_vn} không áp dụng cho khối của học sinh",
                    oid,
                ).as_dict()
            )
            offerings.pop(oid)

    # Payload tự mâu thuẫn — bắt trước khi vào lock để thông báo rõ hơn là để
    # unique index bắn ra một IntegrityError chung chung.
    seen_days = {}
    seen_subjects = {}
    for oid, row in list(offerings.items()):
        if row.day_of_week in seen_days:
            failed.append(
                ClubRegError(
                    "DAY_CONFLICT_IN_REQUEST",
                    # Không xưng hô: hàm này dùng chung cho cả Parent Portal lẫn
                    # `staff_create_registration`, "Phụ huynh…" sẽ sai khi nhân
                    # viên nhà trường đăng ký hộ.
                    f"Đang chọn hai môn cùng {day_label(row.day_of_week)}. "
                    "Mỗi thứ chỉ được chọn một môn.",
                    oid,
                ).as_dict()
            )
            offerings.pop(oid)
            continue
        if row.subject_id in seen_subjects:
            failed.append(
                ClubRegError(
                    "SUBJECT_CONFLICT_IN_REQUEST",
                    f"Môn {row.title_vn} đang được chọn ở hai thứ khác nhau. "
                    "Mỗi môn chỉ được đăng ký một lần.",
                    oid,
                ).as_dict()
            )
            offerings.pop(oid)
            continue
        seen_days[row.day_of_week] = oid
        seen_subjects[row.subject_id] = oid

    # Đối chiếu với các đăng ký đã có.
    existing = [
        r
        for r in get_active_registrations(period.name, student_id)
        if r.name not in ignore_registration_ids
    ]
    existing_subjects = {r.subject_id: r for r in existing}
    existing_days = {r.day_of_week: r for r in existing}

    for oid, row in list(offerings.items()):
        prior = existing_subjects.get(row.subject_id)
        if prior:
            skipped.append(
                {
                    "offering_id": oid,
                    "code": "ALREADY_REGISTERED",
                    "message": f"Đã đăng ký môn {row.title_vn} "
                    f"vào {day_label(prior.day_of_week)}",
                    "registration_id": prior.name,
                }
            )
            offerings.pop(oid)
            continue

        clash = existing_days.get(row.day_of_week)
        if clash:
            failed.append(
                ClubRegError(
                    "DAY_TAKEN",
                    f"Học sinh đã có một môn vào {day_label(row.day_of_week)}",
                    oid,
                ).as_dict()
            )
            offerings.pop(oid)

    return offerings, student_ctx, list(offerings.keys()), skipped, failed


def _insert_locked(
    locked, period, student_id, student_ctx, source, actor_user, guardian, atomic
):
    """
    Chèn đăng ký cho các offering ĐANG GIỮ KHOÁ.

    Tách riêng để `register_student_to_clubs` và `update_student_registrations`
    dùng chung đúng một bản kiểm slot — hai bản chép tay là hai cơ hội lệch nhau.
    Người gọi chịu trách nhiệm khoá, savepoint ngoài và commit.

    Trả về (saved, failed).
    """
    saved = []
    lock_failed = []

    for off in locked:
        sp = f"club_reg_{off.name.replace('-', '_')}"
        frappe.db.savepoint(sp)
        try:
            # Locking read: bắt buộc, xem docstring đầu module.
            used = frappe.db.sql(
                f"""
                SELECT COUNT(*) FROM `tab{DT_REGISTRATION}`
                WHERE offering_id = %s AND status = 'active'
                FOR UPDATE
                """,
                (off.name,),
            )[0][0]

            if used >= int(off.capacity or 0):
                raise ClubRegError(
                    "CLUB_FULL",
                    f"Môn {off.title_vn} đã đủ số lượng",
                    off.name,
                )

            doc = frappe.new_doc(DT_REGISTRATION)
            doc.update(
                {
                    "period_id": period.name,
                    "offering_id": off.name,
                    "subject_id": off.subject_id,
                    "day_of_week": off.day_of_week,
                    "student_id": student_id,
                    "school_year_id": student_ctx["school_year_id"],
                    "education_grade_id": student_ctx["education_grade_id"],
                    "class_id": student_ctx["class_id"],
                    "campus_id": period.campus_id,
                    "status": "active",
                    "source": source,
                    "registered_by": actor_user,
                    "registered_by_guardian": guardian,
                    "registration_datetime": now_datetime(),
                }
            )
            doc.flags.ignore_permissions = True
            doc.insert()

            frappe.db.set_value(
                DT_OFFERING,
                off.name,
                "registered_count",
                used + 1,
                update_modified=False,
            )

            saved.append(
                {
                    "registration_id": doc.name,
                    "offering_id": off.name,
                    "subject_id": off.subject_id,
                    "title_vn": off.title_vn,
                    "title_en": off.title_en,
                    "day_of_week": off.day_of_week,
                }
            )

        except ClubRegError as e:
            _rollback_to(sp)
            lock_failed.append(e.as_dict())
            if atomic:
                raise
        except Exception as e:
            if _is_deadlock(e):
                raise
            code, msg = _classify_duplicate(e)
            if code is None:
                raise
            _rollback_to(sp)
            lock_failed.append({"offering_id": off.name, "code": code, "message": msg})
            if atomic:
                raise ClubRegError(code, msg, off.name)

    return saved, lock_failed


def _cancel_locked(registrations, reason, actor_user):
    """
    Huỷ mềm các đăng ký khi ĐANG GIỮ KHOÁ offering của chúng.

    Giữ lại dòng để có vết; controller đặt `active_student_key = NULL` nên học
    sinh đăng ký lại chính môn đó được. Người gọi lo khoá và commit.
    """
    cancelled = []
    for reg in registrations:
        doc = frappe.get_doc(DT_REGISTRATION, reg.name)
        doc.status = "cancelled"
        doc.cancel_reason = reason
        doc.cancelled_by = actor_user
        doc.cancelled_at = now_datetime()
        doc.flags.ignore_permissions = True
        doc.save()
        _sync_count_locked(reg.offering_id)
        cancelled.append(
            {
                "registration_id": reg.name,
                "offering_id": reg.offering_id,
                "subject_id": reg.subject_id,
                "day_of_week": reg.day_of_week,
            }
        )
    return cancelled


# ----------------------------------------------------------------------
# API chính
# ----------------------------------------------------------------------


def register_student_to_clubs(
    period,
    student_id,
    offering_ids,
    actor_user=None,
    guardian=None,
    source="parent_portal",
    enforce_window=True,
    atomic=False,
):
    """
    Đăng ký học sinh vào một hoặc nhiều môn CLB.

    Ngữ nghĩa: CHỈ CỘNG THÊM. Hàm này chỉ INSERT, không bao giờ UPDATE hay DELETE
    dòng đã có. Muốn huỷ/đổi thì dùng `update_student_registrations` hoặc
    `cancel_registration` — huỷ luôn là huỷ MỀM để giữ vết.

    Args:
        period: document SIS Club Registration Period (đã load).
        student_id: CRM Student.
        offering_ids: danh sách SIS Club Offering.
        actor_user: user thực hiện (mặc định session user).
        guardian: CRM Guardian nếu do phụ huynh thực hiện.
        source: 'parent_portal' | 'staff'.
        enforce_window: False cho phép nhà trường đăng ký hộ ngoài khung giờ —
            nhưng luật slot / thứ / trùng môn thì VẪN áp dụng.
        atomic: True thì một môn hỏng là huỷ cả giỏ. Mặc định False (thành công
            một phần): nếu 2/3 môn còn chỗ thì phụ huynh nên nhận được 2 môn đó
            thay vì trắng tay — và vì mô hình vốn cộng dồn nên giỏ lưu một phần
            đã là trạng thái hợp lệ.

    Returns:
        dict {saved: [...], skipped: [...], failed: [...]}
    """
    actor_user = actor_user or frappe.session.user
    offering_ids = [o for o in (offering_ids or []) if o]

    if not offering_ids:
        raise ClubRegError("NO_CLUB_SELECTED", "Vui lòng chọn ít nhất một môn")

    offerings, student_ctx, pending_ids, skipped, failed = _prevalidate(
        period, student_id, offering_ids, enforce_window
    )

    if not pending_ids:
        return {"saved": [], "skipped": skipped, "failed": failed}

    _set_short_lock_timeout()

    for attempt in range(MAX_LOCK_ATTEMPTS):
        outer_sp = f"club_reg_outer_{attempt}"
        frappe.db.savepoint(outer_sp)
        try:
            locked = _lock_offerings(pending_ids)
            saved, lock_failed = _insert_locked(
                locked,
                period=period,
                student_id=student_id,
                student_ctx=student_ctx,
                source=source,
                actor_user=actor_user,
                guardian=guardian,
                atomic=atomic,
            )

            frappe.db.commit()
            return {"saved": saved, "skipped": skipped, "failed": failed + lock_failed}

        except ClubRegError:
            _rollback_to(outer_sp)
            raise
        except Exception as e:
            if _is_deadlock(e):
                # Deadlock (1213) khiến MySQL rollback TOÀN BỘ transaction — savepoint
                # không còn tồn tại nữa, `rollback to savepoint` sẽ lỗi tiếp. Phải
                # rollback full. (Lock wait timeout 1205 thì chỉ rollback một câu lệnh,
                # nhưng rollback full ở đây vẫn an toàn vì ta sắp thử lại từ đầu.)
                frappe.db.rollback()
                if attempt < MAX_LOCK_ATTEMPTS - 1:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise ClubRegError(
                    "SYSTEM_BUSY",
                    "Hệ thống đang bận do có nhiều người đăng ký cùng lúc. "
                    "Vui lòng thử lại sau giây lát.",
                )
            _rollback_to(outer_sp)
            raise

    raise ClubRegError(
        "SYSTEM_BUSY",
        "Hệ thống đang bận do có nhiều người đăng ký cùng lúc. Vui lòng thử lại sau giây lát.",
    )


def update_student_registrations(
    period,
    student_id,
    cancel_registration_ids=None,
    offering_ids=None,
    actor_user=None,
    guardian=None,
    source="parent_portal",
    enforce_window=True,
    reason=None,
):
    """
    Sửa đăng ký của một học sinh: huỷ một số môn và/hoặc thêm môn mới, TRONG
    MỘT giao dịch.

    Vì sao phải chung một giao dịch (thay vì gọi cancel rồi gọi register):
    đổi môn là "huỷ A để lấy B". Nếu huỷ A trước rồi B hết chỗ, phụ huynh mất cả
    hai — mà B hết chỗ đúng lúc đó là chuyện thường lúc cổng mở. Ở đây B không
    vào được thì A không bị huỷ.

    Lô CHỈ thêm môn (không huỷ gì) không đi qua đây mà uỷ lại cho
    `register_student_to_clubs`, để giữ nguyên ngữ nghĩa thành công một phần:
    chọn 3 môn mà 1 môn hết chỗ thì vẫn nên nhận được 2 môn kia.

    Returns:
        dict {cancelled, saved, skipped, failed}. `failed` khác rỗng nghĩa là
        KHÔNG có gì được áp dụng (đã rollback) — không phải áp dụng một phần.
    """
    actor_user = actor_user or frappe.session.user
    cancel_registration_ids = [c for c in (cancel_registration_ids or []) if c]
    offering_ids = [o for o in (offering_ids or []) if o]

    if not cancel_registration_ids:
        result = register_student_to_clubs(
            period,
            student_id,
            offering_ids,
            actor_user=actor_user,
            guardian=guardian,
            source=source,
            enforce_window=enforce_window,
        )
        return {"cancelled": [], **result}

    if period.status != "Open":
        raise ClubRegError("PERIOD_CLOSED", "Đợt đăng ký chưa mở hoặc đã đóng")
    if enforce_window and not period.is_within_registration_window():
        raise ClubRegError(
            "OUT_OF_WINDOW", "Đã hết thời gian đăng ký nên không sửa được nữa"
        )

    # Chỉ được huỷ đăng ký ĐANG hiệu lực, của ĐÚNG học sinh này, trong ĐÚNG đợt
    # này. Thiếu bất kỳ vế nào là một phụ huynh huỷ được đăng ký của con nhà khác.
    to_cancel = []
    for reg_id in dict.fromkeys(cancel_registration_ids):
        reg = frappe.db.get_value(
            DT_REGISTRATION,
            reg_id,
            ["name", "offering_id", "subject_id", "day_of_week", "status", "student_id", "period_id"],
            as_dict=True,
        )
        if not reg or reg.student_id != student_id or reg.period_id != period.name:
            raise ClubRegError("REGISTRATION_NOT_FOUND", "Không tìm thấy đăng ký", reg_id)
        if reg.status != "active":
            raise ClubRegError("ALREADY_CANCELLED", "Đăng ký này đã được huỷ trước đó", reg_id)
        to_cancel.append(reg)

    # Lô chỉ-huỷ không cần context lớp của học sinh (mà `get_student_context` còn
    # ném lỗi khi bé chưa xếp lớp) — bỏ tick môn cũ thì không phụ thuộc khối.
    if offering_ids:
        _, student_ctx, pending_ids, skipped, failed = _prevalidate(
            period,
            student_id,
            offering_ids,
            enforce_window,
            ignore_registration_ids=[r.name for r in to_cancel],
        )
    else:
        student_ctx, pending_ids, skipped, failed = None, [], [], []

    # Có môn hỏng ngay từ vòng kiểm rẻ -> chưa đụng DB, dừng luôn để không huỷ
    # nhầm môn cũ.
    if failed:
        return {"cancelled": [], "saved": [], "skipped": skipped, "failed": failed}

    _set_short_lock_timeout()

    for attempt in range(MAX_LOCK_ATTEMPTS):
        outer_sp = f"club_upd_outer_{attempt}"
        frappe.db.savepoint(outer_sp)
        try:
            # Khoá MỘT LẦN cả offering bị huỷ lẫn offering sắp thêm: cùng một tập
            # khoá, cùng thứ tự name, nên không khoá chéo với luồng đăng ký.
            locked = _lock_offerings([r.offering_id for r in to_cancel] + pending_ids)
            locked_new = [off for off in locked if off.name in set(pending_ids)]

            cancelled = _cancel_locked(to_cancel, reason, actor_user)
            saved, _ = _insert_locked(
                locked_new,
                period=period,
                student_id=student_id,
                student_ctx=student_ctx,
                source=source,
                actor_user=actor_user,
                guardian=guardian,
                atomic=True,
            )

            frappe.db.commit()
            return {
                "cancelled": cancelled,
                "saved": saved,
                "skipped": skipped,
                "failed": [],
            }

        except ClubRegError as e:
            # Giữ nguyên hiện trạng: môn cũ không bị huỷ.
            _rollback_to(outer_sp)
            return {"cancelled": [], "saved": [], "skipped": skipped, "failed": [e.as_dict()]}
        except Exception as e:
            if _is_deadlock(e):
                frappe.db.rollback()
                if attempt < MAX_LOCK_ATTEMPTS - 1:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise ClubRegError(
                    "SYSTEM_BUSY",
                    "Hệ thống đang bận do có nhiều người đăng ký cùng lúc. "
                    "Vui lòng thử lại sau giây lát.",
                )
            _rollback_to(outer_sp)
            raise

    raise ClubRegError(
        "SYSTEM_BUSY",
        "Hệ thống đang bận do có nhiều người đăng ký cùng lúc. Vui lòng thử lại sau giây lát.",
    )


def cancel_registration(registration_id, reason=None, actor_user=None):
    """
    Nhà trường huỷ một đăng ký.

    Huỷ mềm: giữ dòng để có vết, đặt `active_student_key = NULL` (controller lo)
    nên học sinh có thể đăng ký lại chính môn đó.
    """
    actor_user = actor_user or frappe.session.user

    reg = frappe.db.get_value(
        DT_REGISTRATION, registration_id, ["name", "offering_id", "status"], as_dict=True
    )
    if not reg:
        raise ClubRegError("REGISTRATION_NOT_FOUND", "Không tìm thấy đăng ký")
    if reg.status != "active":
        raise ClubRegError("ALREADY_CANCELLED", "Đăng ký này đã được huỷ trước đó")

    _set_short_lock_timeout()
    try:
        _lock_offerings([reg.offering_id])

        doc = frappe.get_doc(DT_REGISTRATION, registration_id)
        doc.status = "cancelled"
        doc.cancel_reason = reason
        doc.cancelled_by = actor_user
        doc.cancelled_at = now_datetime()
        doc.flags.ignore_permissions = True
        doc.save()

        _sync_count_locked(reg.offering_id)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise

    return {"registration_id": registration_id, "offering_id": reg.offering_id}


def move_registration(registration_id, target_offering_id, reason=None, actor_user=None):
    """
    Nhà trường chuyển một đăng ký sang môn khác.

    Chạy atomic: khoá CẢ HAI offering theo thứ tự name (tránh deadkock khi hai
    staff chuyển ngược chiều nhau), kiểm lại slot ở đích và cả hai luật nghiệp vụ,
    rồi đồng bộ counter hai bên.
    """
    actor_user = actor_user or frappe.session.user

    reg = frappe.db.get_value(
        DT_REGISTRATION,
        registration_id,
        ["name", "period_id", "offering_id", "subject_id", "student_id", "status"],
        as_dict=True,
    )
    if not reg:
        raise ClubRegError("REGISTRATION_NOT_FOUND", "Không tìm thấy đăng ký")
    if reg.status != "active":
        raise ClubRegError("ALREADY_CANCELLED", "Đăng ký này đã được huỷ")
    if reg.offering_id == target_offering_id:
        raise ClubRegError("SAME_CLUB", "Môn đích trùng với môn hiện tại")

    target = frappe.db.get_value(
        DT_OFFERING,
        target_offering_id,
        ["name", "period_id", "subject_id", "day_of_week", "capacity", "status", "title_vn"],
        as_dict=True,
    )
    if not target:
        raise ClubRegError("CLUB_NOT_FOUND", "Không tìm thấy môn đích")
    if target.period_id != reg.period_id:
        raise ClubRegError("CLUB_NOT_FOUND", "Môn đích không thuộc cùng đợt đăng ký")
    if target.status != "active":
        raise ClubRegError("CLUB_INACTIVE", "Môn đích đã ngừng nhận đăng ký")

    # Khối của học sinh phải hợp lệ với môn đích.
    student_grade = frappe.db.get_value(
        DT_REGISTRATION, registration_id, "education_grade_id"
    )
    if student_grade and student_grade not in get_offering_grade_ids(target_offering_id):
        raise ClubRegError(
            "GRADE_NOT_ELIGIBLE", "Môn đích không áp dụng cho khối của học sinh", target_offering_id
        )

    # Luật 1 và luật 2 phải kiểm lại ở đích, bỏ qua chính dòng đang chuyển.
    others = [r for r in get_active_registrations(reg.period_id, reg.student_id) if r.name != registration_id]
    if any(r.subject_id == target.subject_id for r in others):
        raise ClubRegError(
            "ALREADY_REGISTERED",
            f"Học sinh đã đăng ký môn {target.title_vn} ở một thứ khác",
            target_offering_id,
        )
    if any(r.day_of_week == target.day_of_week for r in others):
        raise ClubRegError(
            "DAY_TAKEN",
            f"Học sinh đã có một môn khác vào {day_label(target.day_of_week)}",
            target_offering_id,
        )

    source_offering_id = reg.offering_id
    _set_short_lock_timeout()

    try:
        _lock_offerings([source_offering_id, target_offering_id])

        used = frappe.db.sql(
            f"""
            SELECT COUNT(*) FROM `tab{DT_REGISTRATION}`
            WHERE offering_id = %s AND status = 'active'
            FOR UPDATE
            """,
            (target_offering_id,),
        )[0][0]
        if used >= int(target.capacity or 0):
            raise ClubRegError(
                "CLUB_FULL", f"Môn {target.title_vn} đã đủ số lượng", target_offering_id
            )

        doc = frappe.get_doc(DT_REGISTRATION, registration_id)
        doc.moved_from_offering_id = source_offering_id
        doc.offering_id = target_offering_id
        doc.subject_id = target.subject_id
        doc.day_of_week = target.day_of_week
        doc.cancel_reason = reason
        doc.flags.ignore_permissions = True
        doc.save()

        _sync_count_locked(source_offering_id)
        _sync_count_locked(target_offering_id)
        frappe.db.commit()

    except ClubRegError:
        frappe.db.rollback()
        raise
    except Exception as e:
        frappe.db.rollback()
        code, msg = _classify_duplicate(e)
        if code:
            raise ClubRegError(code, msg, target_offering_id)
        raise

    return {
        "registration_id": registration_id,
        "from_offering_id": source_offering_id,
        "to_offering_id": target_offering_id,
    }
