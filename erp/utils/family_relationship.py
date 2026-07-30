# Copyright (c) 2026, Wellspring International School
# Tiện ích quan hệ gia đình dùng chung cho CẢ CRM lẫn SIS.
#
# Bối cảnh: `CRM Family Relationship` là child table được lưu ở BA nơi cho cùng một sự thật:
#   1. CRM Family.relationships          <- BẢN CHUẨN (parentfield = 'relationships')
#   2. CRM Student.family_relationships  <- mirror
#   3. CRM Guardian.student_relationships<- mirror
# Hai bản mirror có thể cũ (xem ghi chú trong erp/api/erp_sis/feedback.py và
# cleanup_orphaned_guardians.py), nên MỌI nguồn đọc để dựng lại đều phải là bản chuẩn.
#
# Quy ước grain (quan trọng):
#   - `access` và `key_person` là thuộc tính của CẶP (student, guardian) — mỗi cháu một
#     người liên lạc chính, quyền xem gán riêng từng cháu. CRM Family chỉ là cái nhóm.
#   - Vì vậy mọi UPDATE/DELETE lên quan hệ phải scope theo `student`, KHÔNG scope theo
#     `parent` (family). Scope theo family là nguyên nhân của lớp bug clobber/xoá nhầm.
#
# Khi dựng lại mirror của một GUARDIAN phải gom quan hệ ở MỌI family người đó tham gia:
# guardian có thể có con ở family khác, giới hạn theo một family sẽ xoá mất các quan hệ đó
# và làm gãy consumer chỉ đọc mirror (vd parent_portal/menu_registration.py lọc
# parenttype='CRM Guardian').
#
# Nửa sau file là phần tra cứu GUARDIAN THEO SĐT (find_guardian_by_phone) — cũng một
# sự thật lưu hai nơi (field phẳng + bảng con), xem ghi chú ở đầu phần đó.

import re

import frappe

def _has_can_pickup():
    """
    `can_pickup` là field MỚI — chỉ tồn tại sau `bench migrate`. SELECT thẳng trên DB
    chưa migrate sẽ throw, nên phải guard. Cùng cách làm với
    erp/api/faceid/admin.py::_relationship_has_can_pickup.
    """
    try:
        return bool(frappe.db.has_column("CRM Family Relationship", "can_pickup"))
    except Exception:
        return False


def _row_fields():
    """
    Cột của một dòng quan hệ. PHẢI đủ mọi cột dữ liệu, vì kết quả được dùng để dựng lại
    hai bản mirror: cột nào thiếu ở đây sẽ về 0/rỗng trong mirror.

    Lý do không dựa vào default của doctype: `Document.append()` KHÔNG áp default
    (frappe/model/base_document.py::_init_child chỉ gọi get_controller(dt)(value)), rồi
    get_valid_dict ép Check bằng `1 if cint(value) else 0` -> thiếu key thành 0, KHÔNG
    phải NULL. Nên mọi `IFNULL(col, 1)` ở phía đọc đều vô hiệu.

    `fr.parent AS family` để caller biết dòng thuộc family nào mà không phải tự viết lại
    câu SQL bản chuẩn (đã từng có 3 bản sao trong repo vì thiếu cột này).
    """
    cols = [
        "fr.parent AS family",
        "fr.student",
        "fr.guardian",
        "fr.relationship_type",
        "fr.key_person",
        "fr.access",
        "fr.display_order",
    ]
    if _has_can_pickup():
        cols.append("fr.can_pickup")
    return ", ".join(cols)


def canonical_relationship_rows(guardian=None, student=None):
    """
    Các dòng quan hệ CHUẨN: nằm dưới CRM Family.relationships và family còn sống
    (docstatus < 2). Cùng idiom với feedback.py / notification_handler.py /
    finance/notification.py.

    Phải truyền ít nhất một trong guardian/student — không thì trả [] để tránh quét cả bảng.
    """
    if not guardian and not student:
        return []
    conds = ["fr.parentfield = 'relationships'", "f.docstatus < 2"]
    params = {}
    if guardian:
        conds.append("fr.guardian = %(guardian)s")
        params["guardian"] = guardian
    if student:
        conds.append("fr.student = %(student)s")
        params["student"] = student
    return frappe.db.sql(
        """
        SELECT {fields}
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON fr.parent = f.name
        WHERE {conds}
        """.format(fields=_row_fields(), conds=" AND ".join(conds)),
        params,
        as_dict=True,
    )


def _mirror_row(row):
    """
    Dòng sạch để append vào bảng con mirror: bỏ khoá `family` (alias của fr.parent, không
    phải field của doctype — `_init_child` tự set parent/parenttype/parentfield).
    """
    return {k: v for k, v in row.items() if k != "family"}


def rebuild_guardian_relationship_mirror(guardian_name):
    """
    Dựng lại CRM Guardian.student_relationships từ các dòng chuẩn của guardian này,
    GOM MỌI FAMILY người đó tham gia (xem ghi chú đầu file).

    Gọi SAU khi các dòng chuẩn đã được ghi xuống DB.
    """
    if not guardian_name or not frappe.db.exists("CRM Guardian", guardian_name):
        return
    rows = canonical_relationship_rows(guardian=guardian_name)
    guardian_doc = frappe.get_doc("CRM Guardian", guardian_name)
    guardian_doc.set("student_relationships", [])
    for r in rows:
        guardian_doc.append("student_relationships", _mirror_row(r))
    guardian_doc.flags.ignore_validate = True
    guardian_doc.save(ignore_permissions=True)


def rebuild_student_relationship_mirror(student_name):
    """Dựng lại CRM Student.family_relationships từ các dòng chuẩn của học sinh."""
    if not student_name or not frappe.db.exists("CRM Student", student_name):
        return
    rows = canonical_relationship_rows(student=student_name)
    student_doc = frappe.get_doc("CRM Student", student_name)
    student_doc.set("family_relationships", [])
    for r in rows:
        student_doc.append("family_relationships", _mirror_row(r))
    student_doc.flags.ignore_validate = True
    student_doc.save(ignore_permissions=True)


# ====================================================================================
# Tra cứu GUARDIAN theo SỐ ĐIỆN THOẠI (dedup)
#
# CRM Guardian giữ SĐT ở HAI nơi cho cùng một sự thật:
#   1. `CRM Guardian.phone_number`  <- field phẳng, ĐÚNG MỘT số (mirror của row is_primary)
#   2. `CRM Guardian Phone`         <- bảng con `phone_numbers`, NHIỀU số (số thứ hai,
#                                      số cơ quan, số Zalo riêng...)
# Hầu hết đường dedup cũ chỉ tra field phẳng, nên phụ huynh khai số THỨ HAI ở lần sau
# không đối chiếu được và bị tạo thành Guardian THỨ HAI. Pattern đúng đã có ở
# erp/scripts/import_crm_issues_from_excel.py (_resolve_guardians) — rút ra đây để
# dùng chung.
#
# Định dạng: hệ thống lưu +84xxxxxxxxx, người dùng/Excel nhập 0xxxxxxxxx, và trong DB
# còn sót bản ghi dạng 0... (xem erp/api/crm/import_qlead_excel.py
# .fix_guardian_phone_duplicates). Cả hai dạng là CÙNG một số, nên khớp thêm dạng cũ
# không bao giờ là dương tính giả.
# ====================================================================================


def _e164(phone):
    """
    +84xxxxxxxxx từ chuỗi người dùng nhập ('' nếu không có chữ số nào).

    Chỉ giữ CHỮ SỐ trước khi chuẩn hoá (ô Excel hay lẫn ghi chú: '0912345678 (số
    mẹ)'), nhưng vẫn truyền lại dấu '+' nếu có — normalize_phone_number dùng dấu '+'
    để biết '84' đầu chuỗi là mã quốc gia hay đầu số 084x của VN.

    Import LAZY là BẮT BUỘC, không phải cho gọn: đặt ở module level là vòng THẬT,
    đã kiểm chứng —
        erp.utils.family_relationship -> erp.api.crm.utils -> erp/api/__init__.py
        ('from . import erp_sis') -> erp_sis/__init__.py ('from .family import *')
        -> erp/api/erp_sis/family.py:16 'from erp.utils.family_relationship import
        canonical_relationship_rows' -> module đang nạp dở -> ImportError.
    Nói chung: erp.utils là tầng dưới, không được phụ thuộc erp.api ở module level.
    """
    from erp.api.crm.utils import normalize_phone_number

    raw = "" if phone is None else str(phone).strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    return normalize_phone_number(("+" + digits) if raw.startswith("+") else digits)


def guardian_phone_variants(phone, include_legacy_format=True):
    """
    Các dạng chuỗi cần tra cho MỘT số (một số duy nhất, không phải ô nhiều số),
    theo thứ tự ưu tiên:
      1. +84xxxxxxxxx  — dạng chuẩn đang lưu
      2. 0xxxxxxxxx    — dạng cũ còn sót trong DB
      3. chuỗi thô truyền vào, nếu khác hai dạng trên (giữ nguyên cách viết của
         nguồn dữ liệu, vd '912345678' khi Excel cắt mất số 0 đầu)

    include_legacy_format=0 -> CHỈ dạng chuẩn. Dùng khi caller cần phân biệt hai
    định dạng (vd script gộp bản ghi trùng vì sai định dạng: cho hai dạng khớp lẫn
    nhau là mất luôn ý nghĩa). Dạng thô cũng bị bỏ, vì nó thường CHÍNH LÀ dạng cũ.

    Trả [] nếu chuỗi có ít hơn 8 chữ số: dưới ngưỡng đó không còn là SĐT (cùng
    ngưỡng \\d{8,11} mà import_crm_issues_from_excel dùng), mà tra tiếp thì một ô rác
    như '0' lại khớp đúng bản ghi rác trong DB.
    """
    raw = "" if phone is None else str(phone).strip()
    if len(re.sub(r"\D", "", raw)) < 8:
        return []
    e164 = _e164(raw)
    if not include_legacy_format:
        return [e164] if e164 else []
    out = []
    for cand in (e164, ("0" + e164[3:]) if e164 else "", raw):
        if cand and cand not in out:
            out.append(cand)
    return out


def guardian_phone_matches(phone, include_legacy_format=True, exclude=None):
    """
    Mọi CRM Guardian đang giữ số này, kèm nguồn khớp:
        [{"guardian": docname, "phone": <chuỗi khớp>, "source": "flat"|"child"}]

    Field phẳng được xếp TRƯỚC bảng con, để giữ đúng thứ tự ưu tiên của các đường
    dedup cũ (chúng chỉ tra field phẳng; bảng con là phần bổ sung).

    `source` là thông tin bắt buộc cho caller muốn chuẩn hoá lại field phẳng: chỉ
    được ghi đè `phone_number` khi khớp ở CHÍNH field đó. Khớp qua bảng con nghĩa là
    số này chỉ là số PHỤ của người ta — ghi đè sẽ xoá mất số chính.

    exclude: docname (hoặc list) tự loại khỏi kết quả, dùng khi kiểm tra trùng cho
    một bản ghi đang sửa.
    """
    variants = guardian_phone_variants(phone, include_legacy_format=include_legacy_format)
    if not variants:
        return []
    if isinstance(exclude, str):
        skip = {exclude}
    else:
        skip = set(exclude or ())
    rank = {v: i for i, v in enumerate(variants)}
    params = {"variants": tuple(variants)}

    flat = frappe.db.sql(
        """
        SELECT g.name AS guardian, g.phone_number AS phone
        FROM `tabCRM Guardian` g
        WHERE g.phone_number IN %(variants)s
        """,
        params,
        as_dict=True,
    ) or []
    child = frappe.db.sql(
        """
        SELECT gp.parent AS guardian, gp.phone_number AS phone
        FROM `tabCRM Guardian Phone` gp
        INNER JOIN `tabCRM Guardian` g ON g.name = gp.parent
        WHERE gp.parenttype = 'CRM Guardian'
          AND gp.phone_number IN %(variants)s
        """,
        params,
        as_dict=True,
    ) or []

    out = []
    for source, rows in (("flat", flat), ("child", child)):
        rows = [r for r in rows if r.get("guardian") and r["guardian"] not in skip]
        # thứ tự xác định: dạng chuẩn trước dạng cũ, rồi theo docname
        rows.sort(key=lambda r: (rank.get(r.get("phone"), len(rank)), r["guardian"]))
        for r in rows:
            out.append({"guardian": r["guardian"], "phone": r.get("phone") or "",
                        "source": source})
    return out


def find_guardians_by_phone(phone, include_legacy_format=True, exclude=None):
    """
    Danh sách docname CRM Guardian giữ số này (đã bỏ trùng, giữ thứ tự ưu tiên).
    Nhiều hơn một phần tử = số đang bị dùng bởi nhiều người -> dùng để phát hiện trùng.
    """
    out, seen = [], set()
    for m in guardian_phone_matches(phone, include_legacy_format=include_legacy_format,
                                    exclude=exclude):
        if m["guardian"] not in seen:
            seen.add(m["guardian"])
            out.append(m["guardian"])
    return out


def find_guardian_by_phone(phone, include_legacy_format=True, exclude=None):
    """
    Docname CRM Guardian đầu tiên giữ số này, None nếu không có.

    Tra CẢ field phẳng LẪN bảng con `CRM Guardian Phone` — đây là điểm khác biệt so
    với `frappe.db.get_value("CRM Guardian", {"phone_number": ...})` mà mọi chỗ dedup
    cũ đang dùng.
    """
    rows = find_guardians_by_phone(phone, include_legacy_format=include_legacy_format,
                                   exclude=exclude)
    return rows[0] if rows else None
