# Copyright (c) 2026, Wellspring International School
"""
Resolver quyền GUARDIAN ↔ STUDENT dùng chung (Parent Portal và mọi nơi cần kiểm tra
một phụ huynh được làm gì với một học sinh).

BỐI CẢNH — vì sao phải có module này
------------------------------------
`CRM Family Relationship` là child table được lưu ở BA nơi cho cùng một sự thật:

    1. CRM Family.relationships           <- BẢN CHUẨN (parentfield = 'relationships')
    2. CRM Student.family_relationships   <- mirror, CÓ THỂ CŨ
    3. CRM Guardian.student_relationships <- mirror, CÓ THỂ CŨ

Vì vậy idiom `frappe.get_all("CRM Family Relationship", filters={"guardian": ...})`
— đang dùng ở phần lớn erp/api/parent_portal/ — SAI ở ba mức:

  a) Đọc lẫn cả 3 bản: một học sinh xuất hiện tối đa 3 lần (duplicate), và
     `frappe.db.get_value(...)` hay `limit=1` sẽ nhặt MỘT dòng bất kỳ trong số đó.
     Nếu bản chuẩn và bản mirror lệch nhau thì cổng quyền (access / key_person) trở
     nên KHÔNG TẤT ĐỊNH — cùng một request có thể pass hoặc fail.
  b) Không loại family đã xoá mềm: thiếu `docstatus < 2` nên quan hệ thuộc family đã
     huỷ vẫn còn quyền.
  c) Nhận cả dòng do PHÍA HỌC SINH khai (CRM Student.family_relationships): học sinh
     tự thêm một người làm "guardian" thì người đó thấy được học sinh. Xem ghi chú
     trong erp/api/parent_portal/menu_registration.py — file đó bịt lỗ này bằng cách
     lọc parenttype='CRM Guardian', nhưng đổi lại phải đọc bản mirror có thể cũ. Lọc
     theo BẢN CHUẨN bịt đúng lỗ đó mà vẫn đọc dữ liệu mới nhất.

Toàn bộ query ở đây đi qua `canonical_relationship_rows()` trong
erp/utils/family_relationship.py (parentfield='relationships' + INNER JOIN
`tabCRM Family` với docstatus < 2) — cùng idiom với erp/api/erp_sis/feedback.py và
erp/utils/notification_handler.py.

GRAIN CỦA QUYỀN
---------------
`access` và `key_person` là thuộc tính của CẶP (student, guardian): mỗi cháu một
người liên lạc chính, quyền xem gán riêng từng cháu. `CRM Family` chỉ là CÁI NHÓM —
KHÔNG BAO GIỜ suy quyền ở mức family (kiểu "cùng family thì thấy hết").

BA MỨC QUYỀN
------------
    "info"        Đòi access = 1.
                  XEM dữ liệu của học sinh: học bạ, tài chính, sổ liên lạc, hồ sơ,
                  điểm danh, thời khoá biểu, nhật ký...

    "operational" Chỉ đòi TỒN TẠI quan hệ chuẩn (không đòi access/key_person).
                  Tác vụ vận hành hằng ngày: đơn xin nghỉ, đăng ký suất ăn...

    "legal"       Đòi key_person = 1.
                  Quyết định pháp lý / cam kết thay mặt gia đình: tái ghi danh, xác
                  nhận thông tin đầu năm...

Ba mức là BA VỊ TỪ ĐỘC LẬP, không lồng nhau:
  - "legal" KHÔNG bao hàm "info": dữ liệu có thể có key_person = 1 mà access = 0.
  - "info" KHÔNG bao hàm "operational" và ngược lại.
Nghiệp vụ nào cần hai điều kiện thì gọi hai lần và AND lại, đừng tự nới một mức.

CÁCH DÙNG
---------
    from erp.utils.family_access import (
        RIGHT_INFO, RIGHT_OPERATIONAL, RIGHT_LEGAL,
        students_for_guardian, guardians_for_student, can_guardian_access_student,
    )

    # Danh sách con mà PH được xem dữ liệu
    student_ids = students_for_guardian(parent_id, RIGHT_INFO)

    # Cổng cho một endpoint xem học bạ
    if not can_guardian_access_student(parent_id, student_id, RIGHT_INFO):
        return forbidden_response("Bạn không có quyền xem thông tin học sinh này")

`right` là hằng do LẬP TRÌNH VIÊN chọn theo nghiệp vụ. TUYỆT ĐỐI không lấy `right`
từ request/form_dict — client sẽ tự hạ mức quyền. Truyền sai tên mức thì hàm raise
ValueError (fail-closed) chứ không im lặng nới quyền.
"""

from erp.utils.family_relationship import canonical_relationship_rows

RIGHT_INFO = "info"
RIGHT_OPERATIONAL = "operational"
RIGHT_LEGAL = "legal"

VALID_RIGHTS = (RIGHT_INFO, RIGHT_OPERATIONAL, RIGHT_LEGAL)

# Cột quyết định của từng mức. None = chỉ cần tồn tại quan hệ chuẩn.
_RIGHT_FLAG = {
    RIGHT_INFO: "access",
    RIGHT_LEGAL: "key_person",
    RIGHT_OPERATIONAL: None,
}


def _normalize_right(right):
    """Chuẩn hoá + validate tên mức quyền. Sai tên -> raise (không mặc định nới quyền)."""
    normalized = right.strip().lower() if isinstance(right, str) else right
    if normalized not in _RIGHT_FLAG:
        raise ValueError(
            "Mức quyền không hợp lệ: {!r}. Chỉ nhận một trong {}.".format(
                right, ", ".join(VALID_RIGHTS)
            )
        )
    return normalized


def _row_grants(row, right):
    """Một dòng quan hệ chuẩn có cấp mức quyền này không."""
    flag = _RIGHT_FLAG[right]
    if flag is None:
        # "operational": tồn tại dòng chuẩn là đủ.
        return True
    try:
        return int(row.get(flag) or 0) == 1
    except (TypeError, ValueError):
        # Dữ liệu rác ở cột Check -> coi như KHÔNG có quyền.
        return False


def accessible_relationship_rows(*, guardian=None, student=None, right):
    """
    Các dòng quan hệ CHUẨN cấp `right`, đã lọc sạch và bỏ trùng theo cặp
    (student, guardian).

    Đây là primitive của cả 3 hàm public; dùng trực tiếp khi caller còn cần thêm
    `relationship_type` / `key_person` / `display_order` để khỏi query hai lần.

    Phải truyền ít nhất một trong guardian/student (tránh quét cả bảng).
    Quyền của một cặp là HỢP (OR) các dòng chuẩn của cặp đó: guardian có thể xuất
    hiện cùng học sinh ở nhiều family, chỉ cần một dòng cấp quyền là đủ.

    Thứ tự trả về: display_order tăng dần, rồi (student, guardian) — tất định.
    """
    right = _normalize_right(right)
    if not guardian and not student:
        return []

    rows = canonical_relationship_rows(guardian=guardian, student=student) or []

    deduped = {}
    for row in rows:
        row_student = row.get("student")
        row_guardian = row.get("guardian")
        if not row_student or not row_guardian:
            continue
        if not _row_grants(row, right):
            continue
        deduped.setdefault((row_student, row_guardian), row)

    return sorted(
        deduped.values(),
        key=lambda r: (
            int(r.get("display_order") or 0),
            r.get("student") or "",
            r.get("guardian") or "",
        ),
    )


def students_for_guardian(guardian, right):
    """
    Danh sách `CRM Student` mà guardian này được `right` — không trùng, tất định.

    Thay cho idiom cũ:
        frappe.get_all("CRM Family Relationship", filters={"guardian": g},
                       pluck="student")
    (idiom cũ đọc lẫn 2 bản mirror, không lọc docstatus, không lọc access).
    """
    if not guardian:
        return []
    rows = accessible_relationship_rows(guardian=guardian, right=right)
    seen = set()
    out = []
    for row in rows:
        student = row.get("student")
        if student not in seen:
            seen.add(student)
            out.append(student)
    return out


def guardians_for_student(student, right):
    """
    Danh sách `CRM Guardian` được `right` trên học sinh này — không trùng, tất định.

    Với right="legal" đây chính là (các) người liên lạc chính CỦA CHÍNH HỌC SINH ĐÓ.
    Dữ liệu chuẩn nên chỉ có một, nhưng hàm vẫn trả list vì không có ràng buộc DB nào
    bảo đảm điều đó — caller cần đúng một người thì tự kiểm tra len().
    """
    if not student:
        return []
    rows = accessible_relationship_rows(student=student, right=right)
    seen = set()
    out = []
    for row in rows:
        guardian = row.get("guardian")
        if guardian not in seen:
            seen.add(guardian)
            out.append(guardian)
    return out


def can_guardian_access_student(guardian, student, right):
    """
    Cổng quyền cho một cặp cụ thể. True nếu có ít nhất một dòng quan hệ CHUẨN cấp
    `right` cho cặp (student, guardian).

    Thay cho idiom cũ:
        frappe.db.exists("CRM Family Relationship",
                         {"guardian": g, "student": s, "access": 1})
        frappe.db.get_value("CRM Family Relationship",
                            {"guardian": g, "student": s}, "key_person")
    Idiom cũ nhặt một dòng bất kỳ trong 3 bản nên kết quả không tất định.
    """
    if not guardian or not student:
        return False
    return bool(
        accessible_relationship_rows(guardian=guardian, student=student, right=right)
    )
