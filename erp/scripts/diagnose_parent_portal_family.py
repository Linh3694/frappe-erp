# Copyright (c) 2026, Wellspring International School
"""
Vì sao Parent Portal báo "không có gia đình / chưa chọn học sinh" — CÔNG CỤ CHỈ ĐỌC.

    bench --site <site> execute \
        erp.scripts.diagnose_parent_portal_family.run \
        --kwargs "{'phone': '84943685268'}"

    # Đã biết docname guardian thì tra thẳng, khỏi qua số:
    bench --site <site> execute \
        erp.scripts.diagnose_parent_portal_family.run \
        --kwargs "{'guardian': 'CRM-GUARDIAN-00123'}"

Không hàm nào ở đây ghi dữ liệu.

-----------------------------------------------------------------------------------------
BA NGUYÊN NHÂN SCRIPT NÀY PHÂN BIỆT
-----------------------------------------------------------------------------------------
1. TRÙNG BẢN GHI GUARDIAN. Đăng nhập tra CHỈ field phẳng `CRM Guardian.phone_number` rồi
   lấy `guardian_list[0]` (erp/api/parent_portal/otp_auth.py). `frappe.db.get_list` mặc
   định sắp `modified desc`, nên khi một số điện thoại có hai bản ghi, PP bám vào bản
   ĐƯỢC SỬA GẦN NHẤT — quan hệ nằm ở bản kia thì portal rỗng, và thứ tự đổi mỗi lần ai
   đó sửa một trong hai bản (hôm nay đúng, mai sai).

   Quan trọng: `modified desc` chỉ quyết định lúc ĐĂNG NHẬP. Sau đó phiên bị ghim theo
   `guardian_id` nhúng trong email `<guardian_id>@parent.wellspring.edu.vn`
   (`get_current_guardian_comprehensive_data`), nên phụ huynh đã đăng nhập vào bản rỗng
   sẽ ở lại đó VĨNH VIỄN cho tới khi đăng xuất — dù thứ tự `modified` sau đó đã đổi.
   Vì vậy `last_login_at` mới là cột chỉ ra bản ghi mà phụ huynh ĐANG THỰC SỰ dùng, còn
   `modified` chỉ nói lần đăng nhập TIẾP THEO sẽ rơi vào đâu. Hai cột lệch nhau = đang
   có bug, kể cả khi bản đang bind hiện lên đủ học sinh.

2. MẤT DÒNG CHUẨN, CHỈ CÒN MIRROR. Bản chuẩn là `CRM Family.relationships`; hai bản
   `CRM Student.family_relationships` và `CRM Guardian.student_relationships` chỉ là
   mirror (xem erp/utils/family_relationship.py). Query của portal KHÔNG lọc
   `parentfield` nên vẫn nhặt được dòng mirror, nhưng `parent` của chúng là docname
   Student/Guardian -> `get_doc("CRM Family", ...)` ném lỗi, bị nuốt vào `logs`, kết quả
   là 0 gia đình mà không có thông báo nào. Dòng chuẩn trỏ tới family ĐÃ XOÁ cũng cho
   ra đúng triệu chứng đó.

3. CHƯA CÓ QUAN HỆ THẬT. Phụ huynh mới nằm ở `CRM Lead.lead_guardians`; màn hồ sơ vẫn
   hiện đủ vì `_guardian_linked_to_lead` chấp nhận cả bảng con đó, nhưng portal chỉ đọc
   quan hệ gia đình.

Mục [4] trong báo cáo còn liệt kê học sinh của từng nhà và đánh dấu cháu nào PH KHÔNG có
dòng quan hệ trực tiếp — đó là phần portal đang hiện THỪA (nó gom theo NHÀ chứ không theo
cặp), và cũng chính là phần sẽ biến mất nếu sau này siết gate theo `access`.
"""

import frappe

from erp.api.crm.utils import normalize_phone_number
from erp.utils.family_relationship import guardian_phone_matches

CANONICAL_PARENTFIELD = "relationships"

# Trần an toàn khi một số bị dùng chung bởi quá nhiều bản ghi (số tổng đài, số nhập rác).
MAX_CANDIDATES = 20


def _login_candidates(normalized_phone):
    """Đúng truy vấn mà đăng nhập dùng, kể cả thứ tự — để biết PP bám vào bản nào.

    Giữ nguyên biến thể thừa `+{normalized}` của bản gốc: nó không khớp gì (chuỗi đã có
    dấu +) nhưng bỏ đi thì script không còn phản ánh đúng hành vi thật.
    """
    return frappe.db.get_list(
        "CRM Guardian",
        filters={"phone_number": ["in", [normalized_phone, f"+{normalized_phone}"]]},
        fields=["name", "guardian_name", "phone_number", "modified"],
        order_by="modified desc",
        ignore_permissions=True,
    ) or []


def _canonical_rows(guardian):
    """Dòng quan hệ CHUẨN của guardian, family còn sống."""
    return frappe.db.sql(
        """
        SELECT fr.parent AS family, f.family_code, fr.student,
               IFNULL(fr.access, 0) AS access,
               IFNULL(fr.key_person, 0) AS key_person,
               fr.relationship_type
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON fr.parent = f.name
        WHERE fr.parentfield = %(pf)s
          AND f.docstatus < 2
          AND fr.guardian = %(g)s
        ORDER BY fr.parent, fr.student
        """,
        {"pf": CANONICAL_PARENTFIELD, "g": guardian},
        as_dict=True,
    ) or []


def _broken_canonical_rows(guardian):
    """Dòng khai là chuẩn nhưng family không còn (hoặc đã cancel) — nguyên nhân 2."""
    return frappe.db.sql(
        """
        SELECT fr.parent AS family, fr.student
        FROM `tabCRM Family Relationship` fr
        LEFT JOIN `tabCRM Family` f ON fr.parent = f.name
        WHERE fr.parentfield = %(pf)s
          AND fr.guardian = %(g)s
          AND (f.name IS NULL OR f.docstatus = 2)
        """,
        {"pf": CANONICAL_PARENTFIELD, "g": guardian},
        as_dict=True,
    ) or []


def _mirror_rows(guardian):
    """Đếm dòng mirror theo parentfield — nguyên nhân 2 khi chuẩn = 0 mà mirror > 0."""
    return frappe.db.sql(
        """
        SELECT parentfield, parenttype, COUNT(*) AS rows_count
        FROM `tabCRM Family Relationship`
        WHERE guardian = %(g)s AND parentfield <> %(pf)s
        GROUP BY parentfield, parenttype
        """,
        {"pf": CANONICAL_PARENTFIELD, "g": guardian},
        as_dict=True,
    ) or []


def _lead_guardian_rows(guardian):
    """Hồ sơ Lead đang gắn PH này ở bảng con — nguyên nhân 3."""
    return frappe.db.sql(
        """
        SELECT lg.parent AS lead, l.linked_family, l.linked_student
        FROM `tabCRM Lead Guardian` lg
        INNER JOIN `tabCRM Lead` l ON l.name = lg.parent
        WHERE lg.guardian = %(g)s
        """,
        {"g": guardian},
        as_dict=True,
    ) or []


def _family_members(family):
    """Toàn bộ cặp (student, guardian) của một nhà, kèm tên học sinh."""
    return frappe.db.sql(
        """
        SELECT fr.student, fr.guardian, s.student_name,
               IFNULL(fr.access, 0) AS access, fr.relationship_type
        FROM `tabCRM Family Relationship` fr
        LEFT JOIN `tabCRM Student` s ON s.name = fr.student
        WHERE fr.parentfield = %(pf)s AND fr.parent = %(f)s
        ORDER BY fr.student
        """,
        {"pf": CANONICAL_PARENTFIELD, "f": family},
        as_dict=True,
    ) or []


def _portal_view(guardian):
    """Gọi ĐÚNG hàm portal dùng, để lấy con số thật + `logs` mà client vứt đi."""
    from erp.api.parent_portal.otp_auth import get_guardian_comprehensive_data

    try:
        res = get_guardian_comprehensive_data(guardian) or {}
    except Exception as exc:
        return {"error": str(exc), "families": None, "students": None, "logs": []}
    data = res.get("data") or {}
    return {
        "error": res.get("error"),
        "families": len(data.get("families") or []),
        "students": len(data.get("students") or []),
        "student_names": [
            (s.get("student_name") or s.get("name")) for s in (data.get("students") or [])
        ],
        "logs": res.get("logs") or [],
    }


def _diagnose(candidate_reports, bound):
    """Kết luận theo thứ tự loại trừ. Trả (mã, câu giải thích)."""
    if not candidate_reports:
        return ("KHONG_TIM_THAY", "Khong co CRM Guardian nao giu so nay o field phang.")

    bound_report = next((c for c in candidate_reports if c["guardian"] == bound), None)
    if bound is None:
        return (
            "SO_CHI_O_BANG_CON",
            "So chi nam o `CRM Guardian Phone`, dang nhap chi tra field phang -> "
            "khong tra ra ai. Chuan hoa lai `phone_number` phang cho ban ghi dung.",
        )

    others_with_rows = [
        c for c in candidate_reports
        if c["guardian"] != bound and c["canonical_rows"]
    ]
    if bound_report and not bound_report["canonical_rows"] and others_with_rows:
        return (
            "NGUYEN_NHAN_1_TRUNG_BAN_GHI",
            "Ban ghi PP bam vao KHONG co dong quan he nao, trong khi ban ghi trung so "
            "thi co. Gop guardian trung (hoac tro quan he ve dung ban) thi PP hien lai.",
        )

    if bound_report and not bound_report["canonical_rows"]:
        if bound_report["mirror_rows"] or bound_report["broken_canonical_rows"]:
            return (
                "NGUYEN_NHAN_2_MAT_DONG_CHUAN",
                "Khong con dong chuan duoi CRM Family (chi con mirror, hoac family da bi "
                "xoa). Dung rebuild_*_relationship_mirror sau khi dung lai dong chuan.",
            )
        if bound_report["lead_guardian_rows"]:
            return (
                "NGUYEN_NHAN_3_CHUA_CO_QUAN_HE",
                "PH moi nam o CRM Lead.lead_guardians, chua co dong CRM Family "
                "Relationship. Phai tao quan he that o man Gia dinh.",
            )
        return (
            "KHONG_CO_QUAN_HE",
            "Ban ghi nay khong co quan he o bat ky dau (chuan, mirror, lead).",
        )

    # Phiên ghim theo guardian_id, không theo `modified`: bản có `last_login_at` mới nhất
    # mới là bản phụ huynh đang thực sự ngồi trong đó. Bản đó khác bản đang bind nghĩa là
    # portal của họ vẫn rỗng, dù báo cáo phía trên trông "đủ học sinh".
    if len(candidate_reports) > 1:
        logged_in = [c for c in candidate_reports if c["last_login_at"]]
        if logged_in:
            session_holder = max(logged_in, key=lambda c: c["last_login_at"])
            if session_holder["guardian"] != bound and not session_holder["canonical_rows"]:
                return (
                    "NGUYEN_NHAN_1_TRUNG_BAN_GHI_PHIEN_O_BAN_RONG",
                    "Ban ghi %s dang nhap gan day nhat (%s) nhung KHONG co dong quan he "
                    "nao -> phu huynh dang ngoi trong ban rong. Ban dang bind (%s) chi la "
                    "noi lan dang nhap TIEP THEO se roi vao, phien hien tai khong doi theo. "
                    "Phai gop hai ban ghi guardian; dang xuat/dang nhap lai chi la vet tam "
                    "va se lat nguoc khi ai do sua ban rong."
                    % (session_holder["guardian"], session_holder["last_login_at"], bound),
                )

    if bound_report and bound_report["portal"]["students"] == 0:
        return (
            "CO_DONG_CHUAN_NHUNG_PORTAL_RONG",
            "Co dong chuan ma portal van tra 0 hoc sinh -> doc muc [3] logs, vong lap "
            "family da nem loi va bi nuot.",
        )

    return (
        "PORTAL_ON",
        "Portal tra ve du hoc sinh cho ban ghi dang duoc bind. Neu PH van bao rong: "
        "app con cache localStorage, cho chu ky refresh 5 phut hoac dang xuat/dang nhap lai.",
    )


def run(phone=None, guardian=None):
    """In báo cáo cho MỘT phụ huynh. Truyền `phone` hoặc `guardian` (docname)."""
    if not phone and not guardian:
        frappe.throw("Can 'phone' hoac 'guardian'.")

    normalized = normalize_phone_number(phone) if phone else None

    if guardian:
        candidates = [guardian]
        login_rows = []
        bound = guardian if frappe.db.exists("CRM Guardian", guardian) else None
        child_only = []
    else:
        login_rows = _login_candidates(normalized)
        bound = login_rows[0]["name"] if login_rows else None
        # Bản khớp qua bảng con: đăng nhập KHÔNG thấy chúng, nhưng quan hệ hay nằm ở đây.
        all_matches = guardian_phone_matches(normalized) or []
        flat_names = {r["name"] for r in login_rows}
        child_only = sorted(
            {m["guardian"] for m in all_matches if m["guardian"] not in flat_names}
        )
        candidates = [r["name"] for r in login_rows] + child_only

    candidates = candidates[:MAX_CANDIDATES]

    reports = []
    for name in candidates:
        # `owner` + `creation` để truy ra ĐƯỜNG nào đã sinh ra bản trùng — mỗi endpoint
        # tạo CRM Guardian có một guard khác nhau, biết ai tạo mới biết phải vá cửa nào.
        doc = frappe.db.get_value(
            "CRM Guardian",
            name,
            [
                "guardian_name", "phone_number", "family_code",
                "modified", "last_login_at", "owner", "creation",
            ],
            as_dict=True,
        ) or {}
        canonical = _canonical_rows(name)
        families = sorted({r["family"] for r in canonical})
        reports.append(
            {
                "guardian": name,
                "guardian_name": doc.get("guardian_name"),
                "phone_number": doc.get("phone_number"),
                "family_code": doc.get("family_code"),
                "modified": str(doc.get("modified") or ""),
                "last_login_at": str(doc.get("last_login_at") or ""),
                "owner": doc.get("owner"),
                "creation": str(doc.get("creation") or ""),
                "is_bound": name == bound,
                "canonical_rows": canonical,
                "broken_canonical_rows": _broken_canonical_rows(name),
                "mirror_rows": _mirror_rows(name),
                "lead_guardian_rows": _lead_guardian_rows(name),
                "families": families,
                "family_members": {f: _family_members(f) for f in families},
                "portal": _portal_view(name),
            }
        )

    code, explain = _diagnose(reports, bound)
    result = {
        "input": {"phone": phone, "normalized": normalized, "guardian": guardian},
        "bound_guardian": bound,
        "candidates": len(reports),
        "child_table_only": child_only,
        "verdict": code,
        "explain": explain,
        "reports": reports,
    }
    _print(result)
    return result


def _print(result):
    print("=" * 78)
    print("CHAN DOAN PARENT PORTAL — %s" % (result["input"]["normalized"] or result["input"]["guardian"]))
    print("=" * 78)

    print("[1] BAN GHI GUARDIAN CUNG SO")
    if not result["reports"]:
        print("    Khong co ban ghi nao.")
    for r in result["reports"]:
        mark = "<= PP BAM VAO" if r["is_bound"] else ""
        print(
            "    %-28s %-24s %s  modified=%s  last_login=%s %s"
            % (r["guardian"], (r["guardian_name"] or "")[:24], r["phone_number"],
               r["modified"], r["last_login_at"] or "-", mark)
        )
        print("        tao luc %s boi %s" % (r["creation"], r["owner"]))
    if result["child_table_only"]:
        print(
            "    Chi khop o bang con (dang nhap KHONG tra ra): %s"
            % ", ".join(result["child_table_only"])
        )
    print("")

    print("[2] QUAN HE CUA TUNG BAN GHI")
    for r in result["reports"]:
        print("    %s (%s)" % (r["guardian"], r["guardian_name"]))
        print(
            "      dong chuan: %s | dong chuan hong (family mat/cancel): %s | lead_guardians: %s"
            % (len(r["canonical_rows"]), len(r["broken_canonical_rows"]), len(r["lead_guardian_rows"]))
        )
        for m in r["mirror_rows"]:
            print("      mirror %s/%s: %s dong" % (m["parenttype"], m["parentfield"], m["rows_count"]))
        for row in r["canonical_rows"]:
            print(
                "      + %s / %s  quan he=%s access=%s key=%s"
                % (row["family_code"] or row["family"], row["student"],
                   row["relationship_type"], row["access"], row["key_person"])
            )
        for row in r["broken_canonical_rows"]:
            print("      ! family %s khong con — dong nay lam vong lap nem loi" % row["family"])
    print("")

    print("[3] PORTAL THUC SU TRA VE (goi thang get_guardian_comprehensive_data)")
    for r in result["reports"]:
        p = r["portal"]
        print(
            "    %s -> %s gia dinh, %s hoc sinh %s"
            % (r["guardian"], p["families"], p["students"],
               ("| LOI: %s" % p["error"]) if p.get("error") else "")
        )
        if p.get("student_names"):
            print("      %s" % ", ".join(p["student_names"]))
        for line in p["logs"]:
            if line.startswith("⚠️") or line.startswith("❌"):
                print("      %s" % line)
    print("")

    print("[4] HOC SINH TRONG NHA (phan PP dang gom theo NHA, khong theo cap)")
    for r in result["reports"]:
        for fam, members in (r["family_members"] or {}).items():
            direct = {m["student"] for m in members if m["guardian"] == r["guardian"]}
            alls = {}
            for m in members:
                alls.setdefault(m["student"], m.get("student_name") or m["student"])
            for sid, sname in sorted(alls.items()):
                tag = "" if sid in direct else "  <= KHONG co dong quan he truc tiep (PP van hien)"
                print("    %s / %s %s%s" % (fam, sid, sname, tag))
    print("")

    print("=" * 78)
    print("KET LUAN: %s" % result["verdict"])
    print("  %s" % result["explain"])
    print("=" * 78)
