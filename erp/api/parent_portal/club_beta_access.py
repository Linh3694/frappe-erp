# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

"""
Cổng chạy thử module Câu lạc bộ — GỠ TRƯỚC KHI RELEASE.

Chỉ phụ huynh có số điện thoại nằm trong danh sách chạy thử mới:
  - nhìn thấy đợt đăng ký trên Parent Portal (web + app), và
  - nhận thông báo nhắc mở cổng (in-app + push).

Cùng cơ chế với `SOCIAL_FEATURES_ALLOWED_PHONES` của Bảng tin/Trao đổi bên
`parent-portal/src/constants/featureAccess.ts`, kể cả quy ước **danh sách rỗng
= không giới hạn** — để khi gỡ chỉ cần xoá module này và các chỗ gọi, không phải
nhớ đổi ngược lại một cờ nào.

Cách gỡ khi release:
  1. Xoá file này.
  2. Bỏ `_beta_blocked()` ở đầu 5 endpoint trong `club_registration.py`.
  3. Bỏ `filter_students_for_beta()` trong `erp/sis/tasks/club_reminders.py`.
"""

import frappe

#: Số điện thoại được phép chạy thử. RỖNG = mở cho tất cả (giống bản web).
#: Có thể ghi đè bằng site_config.json để đổi người test mà không cần deploy:
#:     "club_beta_phones": ["0376412589", "0912345678"]
#: Lưu ý: site_config ghi đè HOÀN TOÀN danh sách dưới đây, không cộng dồn.
CLUB_BETA_PHONES: list[str] = [
    # "0376412589",
    # "0378881694",
    # "0976881749",
    # "0904011282",
    # "0985871818",
    # "0948096819",
    # "0394230995",
]

_SITE_CONFIG_KEY = "club_beta_phones"


def normalize_phone(raw) -> str:
    """
    Rút số về phần "thuê bao" để so sánh bất kể định dạng lưu trữ.

    Cổng bằng đúng thuật toán của `normalizePhoneForCompare` bên web:
    +84376412589 / 84376412589 / 0376412589 / có khoảng trắng, dấu chấm… đều ra
    `376412589`. Lệch thuật toán giữa hai đầu là danh sách chạy thử khớp ở web
    mà trượt ở app — kiểu lỗi rất khó nhìn ra.
    """
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if not digits:
        return ""
    # Mã quốc gia VN: chỉ bỏ khi còn đủ dài (tránh cắt nhầm đầu số nội địa).
    if digits.startswith("84") and len(digits) >= 11:
        return digits[2:]
    return digits.lstrip("0")


def _allowed_set() -> set:
    configured = frappe.conf.get(_SITE_CONFIG_KEY)
    source = configured if isinstance(configured, (list, tuple)) else CLUB_BETA_PHONES
    return {p for p in (normalize_phone(x) for x in source) if p}


def beta_gate_enabled() -> bool:
    """False = không giới hạn (danh sách rỗng)."""
    return bool(_allowed_set())


def guardian_phones(guardian_name: str) -> list:
    """
    Mọi số của một phụ huynh: cột phẳng + bảng con.

    Đọc CẢ HAI vì `phone_number` phẳng chỉ là bản mirror của `phone_numbers` và
    đã có tiền lệ lệch nhau (xem module CRM). Sót một nguồn là người test bị
    chặn oan mà không hiểu vì sao.
    """
    if not guardian_name:
        return []

    phones = []
    flat = frappe.db.get_value("CRM Guardian", guardian_name, "phone_number")
    if flat:
        phones.append(flat)
    phones.extend(
        frappe.get_all(
            "CRM Guardian Phone",
            filters={"parent": guardian_name, "parenttype": "CRM Guardian"},
            pluck="phone_number",
        )
        or []
    )
    return [p for p in phones if p]


def is_guardian_allowed(guardian_name: str) -> bool:
    allowed = _allowed_set()
    if not allowed:
        return True
    if not guardian_name:
        return False
    return any(normalize_phone(p) in allowed for p in guardian_phones(guardian_name))


def allowed_parent_emails(student_ids: list):
    """
    Email của CHÍNH những phụ huynh trong danh sách chạy thử, trong số phụ huynh
    của các học sinh này.

    `filter_students_for_beta` chỉ lọc HỌC SINH — giữ em lại vì mẹ nằm trong
    nhóm thì bố cũng lọt vào danh sách gửi. Hàm này cắt tiếp ở tầng người nhận.
    Trả `None` khi cổng đang tắt, để bên gọi truyền thẳng vào
    `send_bulk_parent_notifications(allowed_parent_emails=...)` mà vẫn giữ hành
    vi "gửi cho tất cả".

    Email dựng theo đúng công thức của `get_guardians_for_students`.
    """
    if not _allowed_set() or not student_ids:
        return None

    rows = frappe.db.sql(
        """
        SELECT DISTINCT g.name, g.guardian_id
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON f.name = fr.parent
        INNER JOIN `tabCRM Guardian` g ON g.name = fr.guardian
        WHERE fr.student IN %(students)s
          AND fr.parentfield = 'relationships'
          AND f.docstatus < 2
        """,
        {"students": list(student_ids)},
        as_dict=True,
    )
    return [
        f"{r['guardian_id']}@parent.wellspring.edu.vn"
        for r in rows
        if r.get("guardian_id") and is_guardian_allowed(r["name"])
    ]


def filter_students_for_beta(student_ids: list) -> list:
    """
    Giữ lại học sinh có ÍT NHẤT MỘT phụ huynh nằm trong danh sách chạy thử.

    Dùng cho tác vụ gửi nhắc: học sinh không có phụ huynh nào được phép thì bỏ
    hẳn khỏi lô, để `send_bulk_parent_notifications` không tạo bản ghi in-app cho
    những người chưa được xem module.
    """
    if not student_ids:
        return []

    allowed = _allowed_set()
    if not allowed:
        return list(student_ids)

    # Một query cho cả lô thay vì mỗi học sinh một vòng: lô nhắc có thể tới vài
    # nghìn em, đi từng em là vài nghìn round-trip.
    rows = frappe.db.sql(
        """
        SELECT DISTINCT fr.student, g.name AS guardian
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON f.name = fr.parent
        INNER JOIN `tabCRM Guardian` g ON g.name = fr.guardian
        WHERE fr.student IN %(students)s
          AND fr.parentfield = 'relationships'
          AND f.docstatus < 2
        """,
        {"students": list(student_ids)},
        as_dict=True,
    )
    if not rows:
        return []

    guardian_ids = {r["guardian"] for r in rows}
    ok_guardians = {g for g in guardian_ids if is_guardian_allowed(g)}
    if not ok_guardians:
        return []

    return sorted({r["student"] for r in rows if r["guardian"] in ok_guardians})
