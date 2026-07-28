"""
Doc-event hooks: bắn sync membership nhóm chat (social-service) khi roster lớp đổi.

Bổ sung cho cron 6:30 hằng ngày — các thay đổi sau có hiệu lực gần như tức thì:
  - Đổi GVCN / phó GVCN trên SIS Class
  - Thêm / sửa / xoá SIS Subject Assignment (phân công giảng dạy)
  - Sửa thông tin PH (tên / SĐT / email liên lạc / ảnh) trên CRM Guardian
  - Đổi liên kết HS↔PH (CRM Family Relationship) qua bất kỳ parent nào
  - Đổi tên HS trên CRM Student
  - HS vào / ra lớp trên SIS Class Student

Cơ chế: enqueue background job (dedupe theo class+year, chạy sau commit) → POST
`/api/social/chat/sync/memberships` của social-service với body {classId, schoolYearId}.

Lưu ý về child table: `CRM Family Relationship` và `CRM Guardian Email` đều là child
doctype (`istable=1`). Doc-event trên child doctype không chạy đáng tin qua luồng save
thông thường, nên hook gắn vào các PARENT giữ chúng:
  - CRM Guardian        → emails (CRM Guardian Email), student_relationships
  - CRM Family          → relationships
  - CRM Student         → family_relationships

Cấu hình site_config.json (thiếu thì hook im lặng bỏ qua, không chặn save):
  - social_service_base_url        vd "https://prod.sis.wellspring.edu.vn"
  - social_service_sync_api_key    trùng FRAPPE_API_KEY của social-service
  - social_service_sync_api_secret trùng FRAPPE_API_SECRET của social-service
"""

import frappe
import requests

# Field trên CRM Guardian thực sự hiển thị trong panel thành viên chat.
# CHỈ những field này (+ child table emails/student_relationships) mới đáng bắn sync:
# `last_login_at` / `jwt_token_version` / `force_logout_at` đổi mỗi lượt PH đăng nhập
# portal — không guard thì mỗi lần login là một job sync vô ích.
_GUARDIAN_WATCHED_FIELDS = ("guardian_name", "phone_number", "email", "guardian_image")

# Field trên CRM Student ảnh hưởng snapshot (studentNames / studentLinks).
_STUDENT_WATCHED_FIELDS = ("student_name", "student_code")

# Cột của child row cần so sánh để biết liên kết HS↔PH có đổi không.
_RELATIONSHIP_KEYS = ("student", "guardian", "relationship_type", "key_person", "display_order")
_GUARDIAN_EMAIL_KEYS = ("email_address", "is_primary")


def _social_service_config():
    base_url = (frappe.conf.get("social_service_base_url") or "").rstrip("/")
    api_key = frappe.conf.get("social_service_sync_api_key") or ""
    api_secret = frappe.conf.get("social_service_sync_api_secret") or ""
    if not base_url or not api_key or not api_secret:
        return None
    return {"base_url": base_url, "api_key": api_key, "api_secret": api_secret}


def enqueue_chat_membership_sync(class_id, school_year_id):
    """Enqueue sync cho một lớp — dedupe khi cùng lớp bắn dồn dập (import/sửa hàng loạt)."""
    if not class_id or not school_year_id:
        return
    if not _social_service_config():
        return
    try:
        frappe.enqueue(
            "erp.api.erp_sis.chat_membership_hooks.push_chat_membership_sync",
            queue="short",
            enqueue_after_commit=True,
            job_id=f"chat-membership-sync::{class_id}::{school_year_id}",
            deduplicate=True,
            class_id=class_id,
            school_year_id=school_year_id,
        )
    except Exception as e:
        frappe.logger().warning(
            f"[Chat Membership Hook] enqueue failed {class_id}/{school_year_id}: {str(e)}"
        )


def push_chat_membership_sync(class_id, school_year_id):
    """Background job: gọi endpoint sync của social-service cho đúng một lớp."""
    cfg = _social_service_config()
    if not cfg:
        return
    try:
        resp = requests.post(
            f"{cfg['base_url']}/api/social/chat/sync/memberships",
            json={"classId": class_id, "schoolYearId": school_year_id},
            headers={
                "Authorization": f"token {cfg['api_key']}:{cfg['api_secret']}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        body = {}
        try:
            body = resp.json()
        except Exception:
            pass
        frappe.logger().info(
            f"[Chat Membership Hook] synced {class_id}/{school_year_id}: "
            f"status={resp.status_code} summary={body.get('data', {}) if isinstance(body, dict) else ''}"
        )
    except Exception as e:
        frappe.logger().warning(
            f"[Chat Membership Hook] push failed {class_id}/{school_year_id}: {str(e)}"
        )


def on_sis_class_change(doc, method=None):
    """SIS Class on_update/after_insert — chỉ bắn khi GVCN/phó GVCN đổi (hoặc lớp mới)."""
    try:
        changed = True
        if method == "on_update":
            prev = doc.get_doc_before_save()
            if prev:
                changed = (
                    (prev.get("homeroom_teacher") or "") != (doc.get("homeroom_teacher") or "")
                    or (prev.get("vice_homeroom_teacher") or "") != (doc.get("vice_homeroom_teacher") or "")
                )
        if changed:
            enqueue_chat_membership_sync(doc.name, doc.get("school_year_id"))
    except Exception as e:
        # Hook không được chặn luồng lưu doc.
        frappe.logger().warning(f"[Chat Membership Hook] on_sis_class_change: {str(e)}")


def on_subject_assignment_change(doc, method=None):
    """SIS Subject Assignment after_insert/on_update/on_trash — roster GVBM đổi."""
    try:
        enqueue_chat_membership_sync(doc.get("class_id"), doc.get("school_year_id"))
    except Exception as e:
        frappe.logger().warning(
            f"[Chat Membership Hook] on_subject_assignment_change: {str(e)}"
        )


# ---------------------------------------------------------------------------
# Phía PH / HS — tìm ngược từ người ra lớp rồi enqueue.
# ---------------------------------------------------------------------------


def _enabled_school_years():
    """Năm học đang bật — khớp bộ lọc của list_class_chat_sync_targets."""
    return frappe.get_all("SIS School Year", filters={"is_enable": 1}, pluck="name") or []


def _enqueue_for_students(student_ids):
    """HS → các lớp đang hoạt động của HS đó → enqueue sync từng lớp.

    KHÔNG lọc `class_type = regular`: nhóm lớp mixed/club đã tồn tại vẫn phải được
    reconcile. Chiều TẠO MỚI đã được chặn sẵn bởi guard CLASS_TYPE_NOT_REGULAR trong
    social-service (services/chatMembershipSync.js), nên ở đây để rộng là an toàn.
    """
    student_ids = sorted({s for s in (student_ids or []) if s})
    if not student_ids:
        return
    if not _social_service_config():
        return

    enabled_years = _enabled_school_years()
    if not enabled_years:
        return

    rows = frappe.get_all(
        "SIS Class Student",
        filters={
            "student_id": ["in", student_ids],
            "school_year_id": ["in", enabled_years],
        },
        fields=["class_id", "school_year_id"],
        ignore_permissions=True,
        limit_page_length=0,
    ) or []

    for class_id, school_year_id in {
        (r.get("class_id"), r.get("school_year_id")) for r in rows
    }:
        enqueue_chat_membership_sync(class_id, school_year_id)


def enqueue_chat_membership_sync_for_students(student_ids):
    """Bắn sync theo danh sách HS — cho luồng nghiệp vụ tự gọi (không qua doc-event).

    Dùng khi handler sửa child table bằng SQL trực tiếp nên `get_doc_before_save()` không
    còn phản ánh bản trước (vd `family.update_family_members`): doc-event không nhìn thấy
    HS bị gỡ, phải truyền HỢP (HS cũ ∪ HS mới) vào đây.
    """
    _enqueue_for_students(student_ids)


def _students_linked_to_guardian(guardian_docname):
    """HS liên kết PH theo BẢNG (mọi parent: CRM Family / CRM Student / CRM Guardian).

    Dùng raw SQL chứ không `frappe.get_all`: `CRM Family Relationship` là child doctype,
    query builder bắt buộc có filter `parent` để resolve parent doctype (xem các call site
    ở erp/api/crm/lead.py đều truyền `parent`). Ở đây ta cần TẤT CẢ row của PH bất kể
    nằm dưới parent nào, nên đi thẳng bảng — cùng cách `build_guardians_by_student_ids`
    trong erp/api/erp_sis/family.py đang làm.
    """
    if not guardian_docname:
        return set()
    rows = frappe.db.sql(
        """
        SELECT DISTINCT student
        FROM `tabCRM Family Relationship`
        WHERE guardian = %(guardian)s AND IFNULL(student, '') != ''
        """,
        {"guardian": guardian_docname},
        as_dict=True,
    ) or []
    return {r.get("student") for r in rows if r.get("student")}


def _students_from_child(doc, fieldname):
    """Cột `student` của một child table trên doc (dùng cho cả bản trước-khi-lưu)."""
    out = set()
    for row in (doc.get(fieldname) or []):
        getter = row.get if hasattr(row, "get") else (lambda k, _r=row: getattr(_r, k, None))
        sid = getter("student")
        if sid:
            out.add(sid)
    return out


def _child_signature(doc, fieldname, keys):
    """Chữ ký so sánh child table — phát hiện thêm/sửa/xoá row mà không cần diff từng dòng."""
    out = []
    for row in (doc.get(fieldname) or []):
        getter = row.get if hasattr(row, "get") else (lambda k, _r=row: getattr(_r, k, None))
        out.append(tuple(str(getter(k) or "") for k in keys))
    return sorted(out)


def _scalar_fields_changed(prev, doc, fields):
    return any((prev.get(f) or "") != (doc.get(f) or "") for f in fields)


def on_guardian_change(doc, method=None):
    """CRM Guardian on_update — chỉ bắn khi field hiển thị hoặc child table đổi."""
    try:
        # Chưa cấu hình social-service ⇒ bỏ qua trước khi đụng DB (handler này có query SQL
        # chạy trước guard trong _enqueue_for_students).
        if not _social_service_config():
            return
        prev = doc.get_doc_before_save()
        if prev is not None:
            changed = (
                _scalar_fields_changed(prev, doc, _GUARDIAN_WATCHED_FIELDS)
                or _child_signature(prev, "emails", _GUARDIAN_EMAIL_KEYS)
                != _child_signature(doc, "emails", _GUARDIAN_EMAIL_KEYS)
                or _child_signature(prev, "student_relationships", _RELATIONSHIP_KEYS)
                != _child_signature(doc, "student_relationships", _RELATIONSHIP_KEYS)
            )
            if not changed:
                return
        # Hợp cả HS ở bản TRƯỚC khi lưu: gỡ liên kết PH↔HS xong thì HS đó không còn
        # trong doc mới lẫn trong bảng, nhưng nhóm chat của HS đó vẫn phải reconcile
        # để PH bị gỡ rời nhóm.
        student_ids = _students_linked_to_guardian(doc.name)
        student_ids |= _students_from_child(doc, "student_relationships")
        if prev is not None:
            student_ids |= _students_from_child(prev, "student_relationships")
        _enqueue_for_students(student_ids)
    except Exception as e:
        frappe.logger().warning(f"[Chat Membership Hook] on_guardian_change: {str(e)}")


def on_student_change(doc, method=None):
    """CRM Student on_update — tên HS (subtitle "Phụ huynh của …") hoặc liên kết PH đổi."""
    try:
        prev = doc.get_doc_before_save()
        if prev is not None:
            changed = (
                _scalar_fields_changed(prev, doc, _STUDENT_WATCHED_FIELDS)
                or _child_signature(prev, "family_relationships", _RELATIONSHIP_KEYS)
                != _child_signature(doc, "family_relationships", _RELATIONSHIP_KEYS)
            )
            if not changed:
                return
        _enqueue_for_students([doc.name])
    except Exception as e:
        frappe.logger().warning(f"[Chat Membership Hook] on_student_change: {str(e)}")


def on_family_change(doc, method=None):
    """CRM Family on_update — child table `relationships` là nguồn HS↔PH của gia đình."""
    try:
        prev = doc.get_doc_before_save()
        if prev is not None and _child_signature(
            prev, "relationships", _RELATIONSHIP_KEYS
        ) == _child_signature(doc, "relationships", _RELATIONSHIP_KEYS):
            return
        # Hợp bản trước — xoá row thì HS đó không còn trong doc mới (xem on_guardian_change).
        student_ids = _students_from_child(doc, "relationships")
        if prev is not None:
            student_ids |= _students_from_child(prev, "relationships")
        _enqueue_for_students(student_ids)
    except Exception as e:
        frappe.logger().warning(f"[Chat Membership Hook] on_family_change: {str(e)}")


def on_class_student_change(doc, method=None):
    """SIS Class Student after_insert/on_update/on_trash — HS vào/ra lớp."""
    try:
        enqueue_chat_membership_sync(doc.get("class_id"), doc.get("school_year_id"))
    except Exception as e:
        frappe.logger().warning(
            f"[Chat Membership Hook] on_class_student_change: {str(e)}"
        )
