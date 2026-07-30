# Copyright (c) 2026, Wellspring International School
"""
Chẩn đoán mức lệch dữ liệu family — CÔNG CỤ CHỈ ĐỌC.

Mục đích: đo TRƯỚC khi quyết định (a) siết gate `access`, (b) bỏ field
`CRM Lead.linked_family`, (c) gộp guardian trùng, (d) đối chiếu khối lượng dòng quan hệ
với các sweep còn hardcode limit=10000. Không hàm nào trong file này ghi dữ liệu: mọi
câu SQL đều đi qua `_sql()` và bị chặn nếu không bắt đầu bằng SELECT.

Quy ước grain (theo `erp/utils/family_relationship.py`):
  - Bản CHUẨN của quan hệ = dòng `tabCRM Family Relationship` có
    parentfield = 'relationships', parent là `CRM Family` còn sống (docstatus < 2).
  - `CRM Student.family_relationships` (parentfield = 'family_relationships') và
    `CRM Guardian.student_relationships` (parentfield = 'student_relationships') chỉ là
    MIRROR, có thể cũ — ở đây chúng là ĐỐI TƯỢNG ĐO, không phải nguồn.
  - `access` / `key_person` là thuộc tính của CẶP (student, guardian). Vì vậy mọi con số
    dưới đây đếm theo CẶP hoặc theo từng học sinh / từng guardian, không đếm theo family.

Cách chạy trên server:
    bench --site <site> execute erp.api.crm.family_diagnostics.run_all
    bench --site <site> execute erp.api.crm.family_diagnostics.access_distribution
    # lấy JSON thay vì text:
    bench --site <site> execute erp.api.crm.family_diagnostics.run_all --kwargs "{'as_dict': 1}"
Hoặc qua HTTP (cần role System Manager / SIS Manager / Registrar / SIS BOD):
    GET /api/method/erp.api.crm.family_diagnostics.run_all

Ghi chú hiệu năng: `student` và `guardian` trên `tabCRM Family Relationship` KHÔNG có
index (xem crm_family_relationship.json). Do đó file này tránh self-join / correlated
subquery trên hai cột đó — chỗ nào cần đối chiếu cặp thì fetch một lần rồi gom trong
Python (xem `_fetch_relationship_rows`). Các câu GROUP BY một bảng và join theo khoá
chính (`fr.parent = f.name`, `s.name`, `g.name`) thì vẫn để SQL làm.
"""

from collections import defaultdict

import frappe

from erp.api.crm.utils import normalize_phone_number

# Số bản ghi ví dụ trả về mỗi loại (để soi tay, không phải để export).
SAMPLE_LIMIT = 20

# Ngưỡng cứng LỊCH SỬ của erp/api/faceid/admin.py::sync_family_pickup:
#   frappe.get_all("CRM Family Relationship", fields=[...], limit=10000)
# Bản cũ đó KHÔNG filter parentfield nên nó đếm cả hai bản mirror -> ngưỡng thực tế bị
# chia ~3. Giữ con số này để trả lời: hồi đó đã cắt mất bao nhiêu (tức có gia đình nào
# không được cấp uỷ quyền đón mà không ai biết), và để đối chiếu với các sweep KHÁC
# trong faceid/admin.py vẫn còn hardcode limit=10000.
FACEID_SYNC_LIMIT = 10000

CANONICAL_PARENTFIELD = "relationships"
STUDENT_MIRROR_PARENTFIELD = "family_relationships"
GUARDIAN_MIRROR_PARENTFIELD = "student_relationships"
_KNOWN_PARENTFIELDS = (
    CANONICAL_PARENTFIELD,
    STUDENT_MIRROR_PARENTFIELD,
    GUARDIAN_MIRROR_PARENTFIELD,
)

# Chặn nạp cả bảng vào RAM nếu dữ liệu phình bất thường.
MAX_SCAN_ROWS = 300000

_DIAGNOSTIC_ROLES = frozenset(
    {"System Manager", "SIS Manager", "Registrar", "SIS BOD"}
)

# Điều kiện "dòng chuẩn" dùng lại nguyên văn ở nhiều câu SQL bên dưới.
_CANONICAL_WHERE = (
    "fr.parentfield = 'relationships' AND f.docstatus < 2"
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _require_access():
    """Chỉ cho phép role quản trị đọc — báo cáo này gom dữ liệu cá nhân xuyên family."""
    if frappe.session.user == "Administrator":
        return
    roles = set(frappe.get_roles(frappe.session.user))
    if roles.isdisjoint(_DIAGNOSTIC_ROLES):
        frappe.throw(
            "Không có quyền chạy chẩn đoán dữ liệu family",
            frappe.PermissionError,
        )


def _sql(query, params=None, as_dict=True):
    """Bọc frappe.db.sql và CHẶN mọi câu không phải SELECT (bảo đảm read-only)."""
    if not query.lstrip().upper().startswith("SELECT"):
        frappe.throw("family_diagnostics chỉ được phép chạy SELECT")
    return frappe.db.sql(query, params or {}, as_dict=as_dict)


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "none")
    return bool(value)


def _is_cli():
    """True khi chạy bằng bench execute / console (không có HTTP request)."""
    return getattr(frappe.local, "request", None) is None


def _str_or_none(value):
    return str(value) if value else None


def _campus_titles():
    rows = _sql(
        """
        SELECT name,
               COALESCE(NULLIF(TRIM(title_vn), ''), NULLIF(TRIM(short_title), ''), name) AS title
        FROM `tabSIS Campus`
        """
    )
    return {r["name"]: r["title"] for r in rows}


def _fetch_relationship_rows(parentfields=_KNOWN_PARENTFIELDS):
    """
    Nạp thô các dòng `CRM Family Relationship` để gom cặp trong Python.

    `family` != NULL chỉ khi dòng đó là dòng CHUẨN và family còn sống (docstatus < 2);
    dòng parentfield='relationships' mà family = NULL nghĩa là family đã bị xoá/cancel
    (một lớp mồ côi riêng, xem `relationship_row_counts`).

    Trả về (rows, truncated). truncated=True khi bảng vượt MAX_SCAN_ROWS — lúc đó KHÔNG
    nạp gì để tránh ăn RAM của server.
    """
    total = _int(
        _sql(
            "SELECT COUNT(*) FROM `tabCRM Family Relationship` WHERE parentfield IN %(pf)s",
            {"pf": tuple(parentfields)},
            as_dict=False,
        )[0][0]
    )
    if total > MAX_SCAN_ROWS:
        return [], True
    rows = _sql(
        """
        SELECT fr.name, fr.parent, fr.parenttype, fr.parentfield,
               fr.student, fr.guardian,
               IFNULL(fr.access, 0) AS access,
               IFNULL(fr.key_person, 0) AS key_person,
               f.name AS family
        FROM `tabCRM Family Relationship` fr
        LEFT JOIN `tabCRM Family` f
               ON fr.parentfield = 'relationships'
              AND fr.parent = f.name
              AND f.docstatus < 2
        WHERE fr.parentfield IN %(pf)s
        """,
        {"pf": tuple(parentfields)},
    )
    return rows, False


# ---------------------------------------------------------------------------
# 1. Phân bố access (chỉ số quyết định có siết gate được không)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def access_distribution():
    """
    Phân bố `access` trên các dòng CHUẨN, tách theo campus.

    Đây là chỉ số quan trọng nhất: nếu siết gate theo access = 1 thì
    `students_without_any_access` là số học sinh mà TOÀN BỘ phụ huynh bị khoá, và
    `guardians_without_access_ever_logged_in` là số phụ huynh ĐANG dùng portal sẽ mất
    quyền ngay lập tức. Hai số này bằng 0 (hoặc nhỏ + giải thích được) thì mới siết được.

    Campus lấy từ family, thiếu thì rơi về campus của học sinh.
    """
    _require_access()

    by_campus = _sql(
        """
        SELECT
            COALESCE(NULLIF(TRIM(f.campus_id), ''), NULLIF(TRIM(s.campus_id), ''), '__unknown__') AS campus_id,
            COUNT(*) AS total_rows,
            SUM(CASE WHEN IFNULL(fr.access, 0) = 1 THEN 1 ELSE 0 END) AS access_granted,
            SUM(CASE WHEN IFNULL(fr.access, 0) = 0 THEN 1 ELSE 0 END) AS access_denied,
            SUM(CASE WHEN IFNULL(fr.key_person, 0) = 1 THEN 1 ELSE 0 END) AS key_person_rows,
            COUNT(DISTINCT fr.student) AS students,
            COUNT(DISTINCT fr.guardian) AS guardians,
            COUNT(DISTINCT fr.parent) AS families
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON fr.parent = f.name
        LEFT JOIN `tabCRM Student` s ON fr.student = s.name
        WHERE {canonical}
        GROUP BY COALESCE(NULLIF(TRIM(f.campus_id), ''), NULLIF(TRIM(s.campus_id), ''), '__unknown__')
        ORDER BY total_rows DESC
        """.format(canonical=_CANONICAL_WHERE)
    )
    titles = _campus_titles()
    for row in by_campus:
        row["campus_title"] = titles.get(row["campus_id"], row["campus_id"])

    totals = {
        "total_rows": sum(_int(r["total_rows"]) for r in by_campus),
        "access_granted": sum(_int(r["access_granted"]) for r in by_campus),
        "access_denied": sum(_int(r["access_denied"]) for r in by_campus),
        "key_person_rows": sum(_int(r["key_person_rows"]) for r in by_campus),
    }
    totals["access_granted_pct"] = round(
        100.0 * totals["access_granted"] / totals["total_rows"], 2
    ) if totals["total_rows"] else 0.0

    # Mức học sinh: ai sẽ bị khoá sạch phụ huynh, và có vi phạm "một cháu một key_person" không.
    # Lưu ý: mẫu số là học sinh CÓ dòng chuẩn, không phải toàn bộ CRM Student.
    per_student = _sql(
        """
        SELECT
            COUNT(*) AS students_with_canonical_rows,
            SUM(CASE WHEN access_rows = 0 THEN 1 ELSE 0 END) AS students_without_any_access,
            SUM(CASE WHEN access_rows > 0 THEN 1 ELSE 0 END) AS students_with_some_access,
            SUM(CASE WHEN key_rows = 0 THEN 1 ELSE 0 END) AS students_without_key_person,
            SUM(CASE WHEN key_rows > 1 THEN 1 ELSE 0 END) AS students_with_multi_key_person
        FROM (
            SELECT fr.student AS student,
                   SUM(CASE WHEN IFNULL(fr.access, 0) = 1 THEN 1 ELSE 0 END) AS access_rows,
                   SUM(CASE WHEN IFNULL(fr.key_person, 0) = 1 THEN 1 ELSE 0 END) AS key_rows
            FROM `tabCRM Family Relationship` fr
            INNER JOIN `tabCRM Family` f ON fr.parent = f.name
            WHERE {canonical}
            GROUP BY fr.student
        ) t
        """.format(canonical=_CANONICAL_WHERE)
    )
    per_student = per_student[0] if per_student else {}

    # Mức guardian: ai mất quyền nếu siết; tách riêng người ĐÃ từng đăng nhập portal.
    # Mẫu số là guardian CÓ dòng chuẩn (tổng guardian xem ở duplicate_guardians_by_phone).
    per_guardian = _sql(
        """
        SELECT
            COUNT(*) AS guardians_with_canonical_rows,
            SUM(CASE WHEN t.access_rows = 0 THEN 1 ELSE 0 END) AS guardians_without_access,
            SUM(CASE WHEN t.access_rows = 0 AND IFNULL(g.portal_activated, 0) = 1 THEN 1 ELSE 0 END)
                AS guardians_without_access_portal_activated,
            SUM(CASE WHEN t.access_rows = 0 AND g.last_login_at IS NOT NULL THEN 1 ELSE 0 END)
                AS guardians_without_access_ever_logged_in
        FROM (
            SELECT fr.guardian AS guardian,
                   SUM(CASE WHEN IFNULL(fr.access, 0) = 1 THEN 1 ELSE 0 END) AS access_rows
            FROM `tabCRM Family Relationship` fr
            INNER JOIN `tabCRM Family` f ON fr.parent = f.name
            WHERE {canonical}
            GROUP BY fr.guardian
        ) t
        LEFT JOIN `tabCRM Guardian` g ON g.name = t.guardian
        """.format(canonical=_CANONICAL_WHERE)
    )
    per_guardian = per_guardian[0] if per_guardian else {}

    sample_students = _sql(
        """
        SELECT t.student, s.student_name, s.student_code, s.campus_id, t.rows_total
        FROM (
            SELECT fr.student AS student, COUNT(*) AS rows_total,
                   SUM(CASE WHEN IFNULL(fr.access, 0) = 1 THEN 1 ELSE 0 END) AS access_rows
            FROM `tabCRM Family Relationship` fr
            INNER JOIN `tabCRM Family` f ON fr.parent = f.name
            WHERE {canonical}
            GROUP BY fr.student
            HAVING access_rows = 0
        ) t
        LEFT JOIN `tabCRM Student` s ON s.name = t.student
        ORDER BY t.rows_total DESC
        LIMIT %(limit)s
        """.format(canonical=_CANONICAL_WHERE),
        {"limit": SAMPLE_LIMIT},
    )

    sample_guardians = _sql(
        """
        SELECT t.guardian, g.guardian_name, g.campus_id,
               IFNULL(g.portal_activated, 0) AS portal_activated,
               g.last_login_at, t.rows_total
        FROM (
            SELECT fr.guardian AS guardian, COUNT(*) AS rows_total,
                   SUM(CASE WHEN IFNULL(fr.access, 0) = 1 THEN 1 ELSE 0 END) AS access_rows
            FROM `tabCRM Family Relationship` fr
            INNER JOIN `tabCRM Family` f ON fr.parent = f.name
            WHERE {canonical}
            GROUP BY fr.guardian
            HAVING access_rows = 0
        ) t
        LEFT JOIN `tabCRM Guardian` g ON g.name = t.guardian
        ORDER BY (g.last_login_at IS NOT NULL) DESC, g.last_login_at DESC, t.rows_total DESC
        LIMIT %(limit)s
        """.format(canonical=_CANONICAL_WHERE),
        {"limit": SAMPLE_LIMIT},
    )
    for row in sample_guardians:
        row["last_login_at"] = _str_or_none(row.get("last_login_at"))

    return {
        "totals": totals,
        "by_campus": by_campus,
        "per_student": per_student,
        "per_guardian": per_guardian,
        "samples": {
            "students_without_any_access": sample_students,
            "guardians_without_access": sample_guardians,
        },
    }


# ---------------------------------------------------------------------------
# 2. Guardian trùng người theo số điện thoại đã chuẩn hoá
# ---------------------------------------------------------------------------


@frappe.whitelist()
def duplicate_guardians_by_phone():
    """
    Gom guardian theo SĐT đã chuẩn hoá (+84xxxxxxxxx) — xét CẢ field phẳng
    `CRM Guardian.phone_number` LẪN bảng con `CRM Guardian Phone.phone_number`.

    Chuẩn hoá bằng `erp.api.crm.utils.normalize_phone_number`, nên hai bản ghi
    "0912..." và "+84912..." được coi là cùng người. Việc gom làm trong Python vì
    hàm chuẩn hoá là Python (SQL không tái tạo được đúng luật 084x/83x của nó).

    Trả về các nhóm có > 1 guardian DISTINCT, kèm luôn mức lệch giữa field phẳng và
    bảng con (mirror drift) — hai chỗ này phải sync tay nên rất dễ lệch.
    """
    _require_access()

    guardians = _sql(
        """
        SELECT name, guardian_name, campus_id, phone_number,
               IFNULL(portal_activated, 0) AS portal_activated, last_login_at
        FROM `tabCRM Guardian`
        """
    )
    child_phones = _sql(
        """
        SELECT parent AS guardian, phone_number, IFNULL(is_primary, 0) AS is_primary
        FROM `tabCRM Guardian Phone`
        WHERE parenttype = 'CRM Guardian'
          AND parentfield = 'phone_numbers'
          AND IFNULL(TRIM(phone_number), '') <> ''
        """
    )

    meta = {g["name"]: g for g in guardians}
    flat_norm = {}
    for g in guardians:
        norm = normalize_phone_number(g.get("phone_number") or "")
        if norm and norm != "+84":
            flat_norm[g["name"]] = norm

    child_norm = defaultdict(set)
    child_primary = {}
    for row in child_phones:
        norm = normalize_phone_number(row.get("phone_number") or "")
        if not norm or norm == "+84":
            continue
        child_norm[row["guardian"]].add(norm)
        if _int(row.get("is_primary")) == 1:
            child_primary[row["guardian"]] = norm

    # norm -> {guardian: set(sources)}
    groups = defaultdict(lambda: defaultdict(set))
    for guardian, norm in flat_norm.items():
        groups[norm][guardian].add("flat")
    for guardian, norms in child_norm.items():
        for norm in norms:
            groups[norm][guardian].add("child")

    dup_groups = {n: gs for n, gs in groups.items() if len(gs) > 1}
    ordered = sorted(dup_groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    # Mirror drift giữa field phẳng và bảng con.
    flat_missing_but_child_has = []
    flat_not_in_child = []
    flat_not_primary = []
    for guardian in meta:
        norms = child_norm.get(guardian) or set()
        flat = flat_norm.get(guardian)
        if not norms:
            continue
        if not flat:
            flat_missing_but_child_has.append(guardian)
        elif flat not in norms:
            flat_not_in_child.append(guardian)
        elif child_primary.get(guardian) and child_primary[guardian] != flat:
            flat_not_primary.append(guardian)

    def _guardian_brief(name):
        g = meta.get(name) or {}
        return {
            "guardian": name,
            "guardian_name": g.get("guardian_name"),
            "campus_id": g.get("campus_id"),
            "portal_activated": _int(g.get("portal_activated")),
            "last_login_at": _str_or_none(g.get("last_login_at")),
            "flat_phone": g.get("phone_number"),
            "flat_normalized": flat_norm.get(name),
            "child_normalized": sorted(child_norm.get(name) or []),
        }

    sample_group_guardians = set()
    for _norm, gs in ordered[:SAMPLE_LIMIT]:
        sample_group_guardians.update(gs.keys())
    links = _canonical_links_for_guardians(sample_group_guardians)

    samples = []
    for norm, gs in ordered[:SAMPLE_LIMIT]:
        entries = []
        for guardian in sorted(gs.keys()):
            brief = _guardian_brief(guardian)
            brief["matched_via"] = sorted(gs[guardian])
            brief["students"] = sorted(links.get(guardian, {}).get("students", []))
            brief["families"] = sorted(links.get(guardian, {}).get("families", []))
            entries.append(brief)
        all_students = set()
        for e in entries:
            all_students.update(e["students"])
        samples.append(
            {
                "normalized_phone": norm,
                "guardian_count": len(entries),
                "distinct_students": len(all_students),
                # same_student=True: gần như chắc chắn là một người bị tạo 2 lần.
                "same_student_only": len(all_students) == 1,
                "guardians": entries,
            }
        )

    return {
        "totals": {
            "guardians_total": len(meta),
            "guardians_with_flat_phone": len(flat_norm),
            "guardians_with_child_phone": len(child_norm),
            "distinct_normalized_phones": len(groups),
            "duplicate_groups": len(dup_groups),
            "guardians_in_duplicate_groups": len(
                {g for gs in dup_groups.values() for g in gs}
            ),
            "max_group_size": max((len(gs) for gs in dup_groups.values()), default=0),
        },
        "mirror_drift": {
            "flat_empty_but_child_has_phone": len(flat_missing_but_child_has),
            "flat_phone_not_in_child_table": len(flat_not_in_child),
            "flat_phone_not_the_primary_child_row": len(flat_not_primary),
        },
        "samples": {
            "duplicate_groups": samples,
            "flat_empty_but_child_has_phone": [
                _guardian_brief(g) for g in flat_missing_but_child_has[:SAMPLE_LIMIT]
            ],
            "flat_phone_not_in_child_table": [
                _guardian_brief(g) for g in flat_not_in_child[:SAMPLE_LIMIT]
            ],
        },
    }


def _canonical_links_for_guardians(guardian_names):
    """{guardian: {students: [...], families: [...]}} từ các dòng CHUẨN. Dùng cho sample."""
    names = [g for g in (guardian_names or []) if g]
    if not names:
        return {}
    rows = _sql(
        """
        SELECT fr.guardian, fr.student, fr.parent AS family
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON fr.parent = f.name
        WHERE {canonical} AND fr.guardian IN %(guardians)s
        """.format(canonical=_CANONICAL_WHERE),
        {"guardians": tuple(names)},
    )
    out = defaultdict(lambda: {"students": set(), "families": set()})
    for r in rows:
        out[r["guardian"]]["students"].add(r["student"])
        out[r["guardian"]]["families"].add(r["family"])
    return out


# ---------------------------------------------------------------------------
# 3. CRM Lead: linked_student vs linked_family
# ---------------------------------------------------------------------------


@frappe.whitelist()
def lead_family_link_stats():
    """
    Đo `CRM Lead.linked_family` để chốt việc BỎ field này.

    - `student_without_family`: lead có linked_student nhưng linked_family rỗng — đây là
      lead nhập học qua `run_create_enrollment_records` (enrollment.py không set field đó).
    - `with_linked_family`: lead còn giá trị (do migration gán) — số này quyết định lượng
      dữ liệu phải dọn khi bỏ field.
    - `dangling_linked_family`: trỏ tới family không còn tồn tại / đã cancel.
    - `linked_family_conflicts_student`: linked_family KHÁC hẳn family suy ra từ
      linked_student qua dòng chuẩn -> field đang SAI, không chỉ là rỗng.
    """
    _require_access()

    totals = _sql(
        """
        SELECT
            COUNT(*) AS total_leads,
            SUM(CASE WHEN IFNULL(linked_student, '') <> '' THEN 1 ELSE 0 END) AS with_linked_student,
            SUM(CASE WHEN IFNULL(linked_family, '') <> '' THEN 1 ELSE 0 END) AS with_linked_family,
            SUM(CASE WHEN IFNULL(linked_student, '') <> '' AND IFNULL(linked_family, '') = ''
                     THEN 1 ELSE 0 END) AS student_without_family,
            SUM(CASE WHEN IFNULL(linked_student, '') = '' AND IFNULL(linked_family, '') <> ''
                     THEN 1 ELSE 0 END) AS family_without_student,
            SUM(CASE WHEN IFNULL(linked_student, '') = '' AND IFNULL(linked_family, '') = ''
                     THEN 1 ELSE 0 END) AS neither
        FROM `tabCRM Lead`
        """
    )
    totals = totals[0] if totals else {}

    by_step = _sql(
        """
        SELECT IFNULL(step, '') AS step, COUNT(*) AS lead_count
        FROM `tabCRM Lead`
        WHERE IFNULL(linked_student, '') <> '' AND IFNULL(linked_family, '') = ''
        GROUP BY IFNULL(step, '')
        ORDER BY lead_count DESC
        """
    )

    dangling = _sql(
        """
        SELECT COUNT(*) AS dangling_linked_family
        FROM `tabCRM Lead` l
        LEFT JOIN `tabCRM Family` f ON l.linked_family = f.name AND f.docstatus < 2
        WHERE IFNULL(l.linked_family, '') <> '' AND f.name IS NULL
        """
    )
    dangling_count = _int(dangling[0]["dangling_linked_family"]) if dangling else 0

    sample_dangling = _sql(
        """
        SELECT l.name, l.crm_code, l.student_name, l.step, l.linked_family, l.linked_student
        FROM `tabCRM Lead` l
        LEFT JOIN `tabCRM Family` f ON l.linked_family = f.name AND f.docstatus < 2
        WHERE IFNULL(l.linked_family, '') <> '' AND f.name IS NULL
        ORDER BY l.modified DESC
        LIMIT %(limit)s
        """,
        {"limit": SAMPLE_LIMIT},
    )

    sample_no_family = _sql(
        """
        SELECT name, crm_code, student_name, step, status, linked_student, campus_id
        FROM `tabCRM Lead`
        WHERE IFNULL(linked_student, '') <> '' AND IFNULL(linked_family, '') = ''
        ORDER BY modified DESC
        LIMIT %(limit)s
        """,
        {"limit": SAMPLE_LIMIT},
    )

    # Đối chiếu linked_family với family suy ra từ linked_student — gom trong Python vì
    # join fr.student = l.linked_student sẽ quét chéo hai bảng lớn trên cột không index.
    student_families = defaultdict(set)
    for r in _sql(
        """
        SELECT fr.student, fr.parent AS family
        FROM `tabCRM Family Relationship` fr
        INNER JOIN `tabCRM Family` f ON fr.parent = f.name
        WHERE {canonical}
        """.format(canonical=_CANONICAL_WHERE)
    ):
        student_families[r["student"]].add(r["family"])

    linked_both = _sql(
        """
        SELECT name, crm_code, student_name, step, linked_student, linked_family
        FROM `tabCRM Lead`
        WHERE IFNULL(linked_student, '') <> '' AND IFNULL(linked_family, '') <> ''
        """
    )
    conflicts = []
    agree = 0
    student_has_no_canonical = 0
    for lead in linked_both:
        fams = student_families.get(lead["linked_student"]) or set()
        if not fams:
            student_has_no_canonical += 1
            continue
        if lead["linked_family"] in fams:
            agree += 1
        else:
            lead = dict(lead)
            lead["families_via_student"] = sorted(fams)
            conflicts.append(lead)

    return {
        "totals": totals,
        "student_without_family_by_step": by_step,
        "linked_family_health": {
            "dangling_linked_family": dangling_count,
            "linked_family_matches_student": agree,
            "linked_family_conflicts_student": len(conflicts),
            "student_has_no_canonical_relationship": student_has_no_canonical,
        },
        "samples": {
            "student_without_family": sample_no_family,
            "dangling_linked_family": sample_dangling,
            "linked_family_conflicts_student": conflicts[:SAMPLE_LIMIT],
        },
    }


# ---------------------------------------------------------------------------
# 4. Family nghi trùng do bug anh chị em
# ---------------------------------------------------------------------------


@frappe.whitelist()
def guardians_in_multiple_families():
    """
    Guardian xuất hiện ở > 1 `CRM Family` (qua dòng CHUẨN).

    Đây là dấu vết của bug tách family khi có anh/chị/em: đúng nghiệp vụ thì hai cháu
    cùng bố mẹ phải nằm CÙNG một family. Ngược lại, nhiều family chung guardian còn làm
    `_resolve_linked_family_for_student` trả về family của anh/chị (xem ghi chú trong
    `erp/api/crm/lead.py::_resolve_family_for_lead`).

    Gom trong Python từ một lần fetch dòng chuẩn (cột guardian không có index nên
    self-join sẽ rất chậm).
    """
    _require_access()

    rows, truncated = _fetch_relationship_rows((CANONICAL_PARENTFIELD,))
    if truncated:
        return {
            "error": "Bảng CRM Family Relationship vượt MAX_SCAN_ROWS=%s, bỏ qua phân tích"
            % MAX_SCAN_ROWS
        }

    guardian_families = defaultdict(set)
    guardian_family_students = defaultdict(lambda: defaultdict(set))
    families = set()
    for r in rows:
        if not r.get("family"):
            continue
        families.add(r["family"])
        guardian_families[r["guardian"]].add(r["family"])
        guardian_family_students[r["guardian"]][r["family"]].add(r["student"])

    multi = {g: f for g, f in guardian_families.items() if len(f) > 1}
    families_involved = {fam for fams in multi.values() for fam in fams}

    ordered = sorted(multi.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    sample_guardians = [g for g, _f in ordered[:SAMPLE_LIMIT]]
    names = {}
    if sample_guardians:
        for r in _sql(
            """
            SELECT name, guardian_name, campus_id FROM `tabCRM Guardian`
            WHERE name IN %(names)s
            """,
            {"names": tuple(sample_guardians)},
        ):
            names[r["name"]] = r

    samples = []
    for guardian, fams in ordered[:SAMPLE_LIMIT]:
        meta = names.get(guardian) or {}
        samples.append(
            {
                "guardian": guardian,
                "guardian_name": meta.get("guardian_name"),
                "campus_id": meta.get("campus_id"),
                "family_count": len(fams),
                "families": [
                    {
                        "family": fam,
                        "students": sorted(guardian_family_students[guardian][fam]),
                    }
                    for fam in sorted(fams)
                ],
            }
        )

    return {
        "totals": {
            "canonical_rows": len([r for r in rows if r.get("family")]),
            "guardians_with_canonical_rows": len(guardian_families),
            "families_with_canonical_rows": len(families),
            "guardians_in_multiple_families": len(multi),
            "families_involved": len(families_involved),
            "max_families_per_guardian": max((len(f) for f in multi.values()), default=0),
        },
        "samples": {"guardians_in_multiple_families": samples},
    }


# ---------------------------------------------------------------------------
# 5. Tổng số dòng + mirror mồ côi
# ---------------------------------------------------------------------------


@frappe.whitelist()
def relationship_row_counts():
    """
    Đếm dòng `CRM Family Relationship` theo parenttype/parentfield và đo mirror mồ côi.

    Hai việc:
      a) Đối chiếu TỔNG SỐ DÒNG với ngưỡng lịch sử limit=10000 của
         `erp/api/faceid/admin.py::sync_family_pickup`. Bản cũ gọi get_all KHÔNG filter
         parentfield nên đếm cả 2 bản mirror -> vượt ngưỡng là mất uỷ quyền đón lặng lẽ.
         Ngưỡng đó đã được bỏ khi hàm được viết lại theo dòng chuẩn, nên con số ở đây
         dùng để (i) biết hồi đó đã cắt mất bao nhiêu, (ii) canh các sweep khác còn cap.
      b) Đếm mirror mồ côi: cặp (student, guardian) có dòng dưới CRM Student /
         CRM Guardian mà KHÔNG có dòng chuẩn tương ứng; và ngược lại (dòng chuẩn thiếu
         mirror), cộng thêm lệch access/key_person giữa chuẩn và mirror.
    """
    _require_access()

    by_parent = _sql(
        """
        SELECT IFNULL(parenttype, '') AS parenttype,
               IFNULL(parentfield, '') AS parentfield,
               COUNT(*) AS row_count
        FROM `tabCRM Family Relationship`
        GROUP BY IFNULL(parenttype, ''), IFNULL(parentfield, '')
        ORDER BY row_count DESC
        """
    )
    total_rows = sum(_int(r["row_count"]) for r in by_parent)
    unexpected = [r for r in by_parent if r["parentfield"] not in _KNOWN_PARENTFIELDS]
    canonical_row_count = sum(
        _int(r["row_count"])
        for r in by_parent
        if r["parentfield"] == CANONICAL_PARENTFIELD
    )

    result = {
        "rows_by_parent": by_parent,
        "totals": {
            "total_rows_all_parentfields": total_rows,
            "canonical_rows": canonical_row_count,
            "rows_with_unexpected_parentfield": sum(
                _int(r["row_count"]) for r in unexpected
            ),
        },
        "faceid_sync_family_pickup": {
            "historical_hard_limit": FACEID_SYNC_LIMIT,
            "rows_seen_by_old_unfiltered_call": total_rows,
            "rows_needed_by_canonical_sweep": canonical_row_count,
            "old_limit_exceeded": total_rows > FACEID_SYNC_LIMIT,
            "canonical_sweep_would_exceed_that_limit": canonical_row_count
            > FACEID_SYNC_LIMIT,
            "note": (
                "Bản cũ gọi get_all('CRM Family Relationship', limit=10000) KHÔNG filter "
                "parentfield nên đọc cả 2 bản mirror; vượt ngưỡng là cắt im lặng, một phần "
                "gia đình không được cấp uỷ quyền đón. Ngưỡng đó đã bỏ khi hàm được viết "
                "lại theo dòng chuẩn — số ở đây để biết mức thiệt hại cũ và để canh các "
                "sweep khác trong faceid/admin.py vẫn còn hardcode 10000."
            ),
        },
    }

    rows, truncated = _fetch_relationship_rows()
    if truncated:
        result["mirror_health"] = {
            "error": "Bảng vượt MAX_SCAN_ROWS=%s, bỏ qua phân tích mirror" % MAX_SCAN_ROWS
        }
        return result

    canonical = {}
    canonical_dup_pairs = defaultdict(int)
    canonical_dead_family = []
    student_mirror = defaultdict(list)
    guardian_mirror = defaultdict(list)
    broken_rows = []

    for r in rows:
        # student/guardian là reqd=1 nhưng dữ liệu cũ có thể rỗng; nếu để lọt, mọi dòng
        # rỗng sẽ dồn vào cùng một "cặp" (None, None) và làm sai hết phần đối chiếu.
        if not r.get("student") or not r.get("guardian"):
            broken_rows.append(r)
            continue
        pair = (r["student"], r["guardian"])
        pf = r["parentfield"]
        if pf == CANONICAL_PARENTFIELD:
            if not r.get("family"):
                canonical_dead_family.append(r)
                continue
            if pair in canonical:
                canonical_dup_pairs[pair] += 1
            else:
                canonical[pair] = r
        elif pf == STUDENT_MIRROR_PARENTFIELD:
            student_mirror[pair].append(r)
        elif pf == GUARDIAN_MIRROR_PARENTFIELD:
            guardian_mirror[pair].append(r)

    def _orphans(mirror_map):
        return [
            row
            for pair, rows_ in mirror_map.items()
            if pair not in canonical
            for row in rows_
        ]

    orphan_student = _orphans(student_mirror)
    orphan_guardian = _orphans(guardian_mirror)

    missing_student_mirror = [
        r for pair, r in canonical.items() if pair not in student_mirror
    ]
    missing_guardian_mirror = [
        r for pair, r in canonical.items() if pair not in guardian_mirror
    ]

    # Lệch giá trị: mirror còn giữ access/key_person cũ -> consumer đọc mirror ra kết quả khác.
    value_mismatch = []
    for pair, canon in canonical.items():
        for label, rows_ in (
            ("CRM Student.family_relationships", student_mirror.get(pair) or []),
            ("CRM Guardian.student_relationships", guardian_mirror.get(pair) or []),
        ):
            for m in rows_:
                if _int(m["access"]) != _int(canon["access"]) or _int(
                    m["key_person"]
                ) != _int(canon["key_person"]):
                    value_mismatch.append(
                        {
                            "student": pair[0],
                            "guardian": pair[1],
                            "mirror": label,
                            "mirror_row": m["name"],
                            "mirror_parent": m["parent"],
                            "canonical_row": canon["name"],
                            "canonical_family": canon["family"],
                            "canonical_access": _int(canon["access"]),
                            "mirror_access": _int(m["access"]),
                            "canonical_key_person": _int(canon["key_person"]),
                            "mirror_key_person": _int(m["key_person"]),
                        }
                    )

    def _brief(rows_):
        return [
            {
                "row": r["name"],
                "parenttype": r["parenttype"],
                "parent": r["parent"],
                "student": r["student"],
                "guardian": r["guardian"],
                "access": _int(r["access"]),
                "key_person": _int(r["key_person"]),
            }
            for r in rows_[:SAMPLE_LIMIT]
        ]

    result["mirror_health"] = {
        "canonical_pairs": len(canonical),
        "rows_missing_student_or_guardian": len(broken_rows),
        "canonical_rows_with_dead_or_missing_family": len(canonical_dead_family),
        "canonical_duplicate_pairs": len(canonical_dup_pairs),
        "orphan_student_mirror_rows": len(orphan_student),
        "orphan_guardian_mirror_rows": len(orphan_guardian),
        "canonical_pairs_missing_student_mirror": len(missing_student_mirror),
        "canonical_pairs_missing_guardian_mirror": len(missing_guardian_mirror),
        "mirror_value_mismatch_rows": len(value_mismatch),
    }
    result["samples"] = {
        "rows_missing_student_or_guardian": _brief(broken_rows),
        "orphan_student_mirror_rows": _brief(orphan_student),
        "orphan_guardian_mirror_rows": _brief(orphan_guardian),
        "canonical_rows_with_dead_or_missing_family": _brief(canonical_dead_family),
        "canonical_pairs_missing_student_mirror": _brief(missing_student_mirror),
        "canonical_pairs_missing_guardian_mirror": _brief(missing_guardian_mirror),
        "mirror_value_mismatch_rows": value_mismatch[:SAMPLE_LIMIT],
    }
    return result


# ---------------------------------------------------------------------------
# Tổng hợp
# ---------------------------------------------------------------------------

_METRICS = (
    ("access_distribution", access_distribution),
    ("duplicate_guardians_by_phone", duplicate_guardians_by_phone),
    ("lead_family_link_stats", lead_family_link_stats),
    ("guardians_in_multiple_families", guardians_in_multiple_families),
    ("relationship_row_counts", relationship_row_counts),
)


def collect_all():
    """Chạy cả 5 chỉ số. Một chỉ số lỗi thì ghi lỗi vào chỗ của nó, không làm hỏng cả báo cáo."""
    _require_access()
    out = {}
    for key, fn in _METRICS:
        try:
            out[key] = fn()
        except Exception:
            out[key] = {"error": frappe.get_traceback(with_context=False)}
    return out


def _pct(part, whole):
    part, whole = _int(part), _int(whole)
    if not whole:
        return "-"
    return "%.1f%%" % (100.0 * part / whole)


def _format_report(data):
    """Báo cáo text để đọc trực tiếp trên terminal."""
    L = []
    add = L.append

    add("=" * 78)
    add(
        "CHẨN ĐOÁN LỆCH DỮ LIỆU FAMILY (chỉ đọc) — site: %s"
        % getattr(frappe.local, "site", "?")
    )
    add("Thời điểm: %s" % frappe.utils.now())
    add("=" * 78)

    # --- 1
    d = data.get("access_distribution") or {}
    add("")
    add("[1] PHÂN BỐ access TRÊN DÒNG CHUẨN  (chỉ số quyết định siết gate)")
    add("-" * 78)
    if d.get("error"):
        add("  LỖI: %s" % d["error"])
    else:
        t = d.get("totals") or {}
        add(
            "  Tổng dòng chuẩn: %s | access=1: %s (%s) | access=0: %s | key_person=1: %s"
            % (
                t.get("total_rows"),
                t.get("access_granted"),
                _pct(t.get("access_granted"), t.get("total_rows")),
                t.get("access_denied"),
                t.get("key_person_rows"),
            )
        )
        ps = d.get("per_student") or {}
        add(
            "  Học sinh có dòng chuẩn: %s | KHÔNG có phụ huynh nào access=1: %s (%s)"
            % (
                ps.get("students_with_canonical_rows"),
                ps.get("students_without_any_access"),
                _pct(
                    ps.get("students_without_any_access"),
                    ps.get("students_with_canonical_rows"),
                ),
            )
        )
        add(
            "  Học sinh không có key_person: %s | có >1 key_person: %s  (nghiệp vụ: mỗi cháu ĐÚNG 1)"
            % (
                ps.get("students_without_key_person"),
                ps.get("students_with_multi_key_person"),
            )
        )
        pg = d.get("per_guardian") or {}
        add(
            "  Guardian có dòng chuẩn: %s | không có dòng access=1 nào: %s (%s)"
            % (
                pg.get("guardians_with_canonical_rows"),
                pg.get("guardians_without_access"),
                _pct(
                    pg.get("guardians_without_access"),
                    pg.get("guardians_with_canonical_rows"),
                ),
            )
        )
        add(
            "    trong đó portal_activated=1: %s | ĐÃ TỪNG đăng nhập: %s  <-- siết gate là khoá đúng những người này"
            % (
                pg.get("guardians_without_access_portal_activated"),
                pg.get("guardians_without_access_ever_logged_in"),
            )
        )
        add("  Theo campus:")
        for row in d.get("by_campus") or []:
            add(
                "    %-28s dòng %-7s access=1 %-7s (%s)  HS %-6s PH %-6s"
                % (
                    (row.get("campus_title") or "")[:28],
                    row.get("total_rows"),
                    row.get("access_granted"),
                    _pct(row.get("access_granted"), row.get("total_rows")),
                    row.get("students"),
                    row.get("guardians"),
                )
            )
        samples = (d.get("samples") or {}).get("guardians_without_access") or []
        if samples:
            add("  Ví dụ guardian sẽ mất quyền (ưu tiên người đã đăng nhập):")
            for s in samples[:10]:
                add(
                    "    %s | %s | login: %s | dòng quan hệ: %s"
                    % (
                        s.get("guardian"),
                        s.get("guardian_name"),
                        s.get("last_login_at") or "chưa bao giờ",
                        s.get("rows_total"),
                    )
                )

    # --- 2
    d = data.get("duplicate_guardians_by_phone") or {}
    add("")
    add("[2] GUARDIAN TRÙNG NGƯỜI THEO SĐT CHUẨN HOÁ (+84...)")
    add("-" * 78)
    if d.get("error"):
        add("  LỖI: %s" % d["error"])
    else:
        t = d.get("totals") or {}
        add(
            "  Guardian: %s | có SĐT phẳng: %s | có SĐT bảng con: %s | SĐT distinct: %s"
            % (
                t.get("guardians_total"),
                t.get("guardians_with_flat_phone"),
                t.get("guardians_with_child_phone"),
                t.get("distinct_normalized_phones"),
            )
        )
        add(
            "  Nhóm trùng (>1 guardian/SĐT): %s | guardian liên quan: %s | nhóm lớn nhất: %s"
            % (
                t.get("duplicate_groups"),
                t.get("guardians_in_duplicate_groups"),
                t.get("max_group_size"),
            )
        )
        md = d.get("mirror_drift") or {}
        add(
            "  Lệch mirror phẳng<->bảng con: phẳng rỗng %s | phẳng không có trong bảng con %s | phẳng != is_primary %s"
            % (
                md.get("flat_empty_but_child_has_phone"),
                md.get("flat_phone_not_in_child_table"),
                md.get("flat_phone_not_the_primary_child_row"),
            )
        )
        for s in ((d.get("samples") or {}).get("duplicate_groups") or [])[:10]:
            add(
                "    %s -> %s guardian, %s học sinh distinct%s"
                % (
                    s.get("normalized_phone"),
                    s.get("guardian_count"),
                    s.get("distinct_students"),
                    "  (cùng 1 HS: gần như chắc là 1 người tạo 2 lần)"
                    if s.get("same_student_only")
                    else "",
                )
            )
            for g in s.get("guardians") or []:
                add(
                    "        %s | %s | via %s | families %s"
                    % (
                        g.get("guardian"),
                        g.get("guardian_name"),
                        ",".join(g.get("matched_via") or []),
                        ",".join(g.get("families") or []) or "-",
                    )
                )

    # --- 3
    d = data.get("lead_family_link_stats") or {}
    add("")
    add("[3] CRM LEAD: linked_student vs linked_family")
    add("-" * 78)
    if d.get("error"):
        add("  LỖI: %s" % d["error"])
    else:
        t = d.get("totals") or {}
        add(
            "  Tổng lead: %s | có linked_student: %s | có linked_family: %s"
            % (
                t.get("total_leads"),
                t.get("with_linked_student"),
                t.get("with_linked_family"),
            )
        )
        add(
            "  Có linked_student NHƯNG linked_family rỗng: %s (%s tổng lead)"
            % (
                t.get("student_without_family"),
                _pct(t.get("student_without_family"), t.get("total_leads")),
            )
        )
        add(
            "  Có linked_family nhưng KHÔNG có linked_student: %s | không có cả hai: %s"
            % (t.get("family_without_student"), t.get("neither"))
        )
        h = d.get("linked_family_health") or {}
        add(
            "  linked_family: khớp family suy từ HS %s | LỆCH %s | family đã xoá/cancel %s | HS chưa có dòng chuẩn %s"
            % (
                h.get("linked_family_matches_student"),
                h.get("linked_family_conflicts_student"),
                h.get("dangling_linked_family"),
                h.get("student_has_no_canonical_relationship"),
            )
        )
        rows = d.get("student_without_family_by_step") or []
        if rows:
            add("  Phân bố theo bước (lead thiếu linked_family):")
            for r in rows:
                add("    %-14s %s" % (r.get("step") or "(rỗng)", r.get("lead_count")))

    # --- 4
    d = data.get("guardians_in_multiple_families") or {}
    add("")
    add("[4] FAMILY NGHI TRÙNG (guardian nằm ở >1 CRM Family)")
    add("-" * 78)
    if d.get("error"):
        add("  LỖI: %s" % d["error"])
    else:
        t = d.get("totals") or {}
        add(
            "  Family: %s | guardian: %s | guardian ở >1 family: %s (%s) | family liên quan: %s | max family/guardian: %s"
            % (
                t.get("families_with_canonical_rows"),
                t.get("guardians_with_canonical_rows"),
                t.get("guardians_in_multiple_families"),
                _pct(
                    t.get("guardians_in_multiple_families"),
                    t.get("guardians_with_canonical_rows"),
                ),
                t.get("families_involved"),
                t.get("max_families_per_guardian"),
            )
        )
        for s in ((d.get("samples") or {}).get("guardians_in_multiple_families") or [])[
            :10
        ]:
            add(
                "    %s | %s | %s family"
                % (s.get("guardian"), s.get("guardian_name"), s.get("family_count"))
            )
            for f in s.get("families") or []:
                add(
                    "        %s -> HS: %s"
                    % (f.get("family"), ", ".join(f.get("students") or []))
                )

    # --- 5
    d = data.get("relationship_row_counts") or {}
    add("")
    add("[5] TỔNG SỐ DÒNG QUAN HỆ + MIRROR MỒ CÔI")
    add("-" * 78)
    if d.get("error"):
        add("  LỖI: %s" % d["error"])
    else:
        t = d.get("totals") or {}
        fs = d.get("faceid_sync_family_pickup") or {}
        add(
            "  Tổng dòng (mọi parentfield): %s | riêng dòng chuẩn: %s"
            % (t.get("total_rows_all_parentfields"), t.get("canonical_rows"))
        )
        for r in d.get("rows_by_parent") or []:
            add(
                "    %-16s %-24s %s"
                % (
                    r.get("parenttype") or "(rỗng)",
                    r.get("parentfield") or "(rỗng)",
                    r.get("row_count"),
                )
            )
        if t.get("rows_with_unexpected_parentfield"):
            add(
                "    CẢNH BÁO: %s dòng có parentfield lạ (không thuộc 3 nhóm đã biết)"
                % t["rows_with_unexpected_parentfield"]
            )
        add(
            "  So với ngưỡng lịch sử limit=10000 (faceid/admin.py sync_family_pickup):"
        )
        add(
            "    bản cũ (đếm cả mirror): %s | dòng chuẩn: %s"
            % (
                "VƯỢT NGƯỠNG — đã từng cắt im lặng"
                if fs.get("old_limit_exceeded")
                else "trong ngưỡng",
                "VƯỢT NGƯỠNG"
                if fs.get("canonical_sweep_would_exceed_that_limit")
                else "trong ngưỡng",
            )
        )
        add("    %s" % fs.get("note"))
        m = d.get("mirror_health") or {}
        if m.get("error"):
            add("  %s" % m["error"])
        else:
            add("  Cặp (student, guardian) chuẩn: %s" % m.get("canonical_pairs"))
            add(
                "  Dòng chuẩn có family đã xoá/cancel: %s | cặp chuẩn bị lặp: %s"
                % (
                    m.get("canonical_rows_with_dead_or_missing_family"),
                    m.get("canonical_duplicate_pairs"),
                )
            )
            add(
                "  Mirror MỒ CÔI (không có dòng chuẩn): CRM Student %s | CRM Guardian %s"
                % (
                    m.get("orphan_student_mirror_rows"),
                    m.get("orphan_guardian_mirror_rows"),
                )
            )
            add(
                "  Cặp chuẩn THIẾU mirror: CRM Student %s | CRM Guardian %s"
                % (
                    m.get("canonical_pairs_missing_student_mirror"),
                    m.get("canonical_pairs_missing_guardian_mirror"),
                )
            )
            add(
                "  Mirror lệch giá trị access/key_person so với chuẩn: %s dòng"
                % m.get("mirror_value_mismatch_rows")
            )
            if m.get("rows_missing_student_or_guardian"):
                add(
                    "  CẢNH BÁO: %s dòng rỗng student hoặc guardian (đã loại khỏi phần đối chiếu)"
                    % m["rows_missing_student_or_guardian"]
                )

    add("")
    add("=" * 78)
    add("ĐỌC KẾT QUẢ")
    add("-" * 78)
    add("  - Siết gate access chỉ an toàn khi [1] guardians_without_access_ever_logged_in ~ 0.")
    add("    Nếu số đó lớn, phải backfill access=1 cho các cặp hợp lệ TRƯỚC khi siết.")
    add("  - [5] mirror mồ côi / lệch giá trị > 0 = có consumer đang đọc mirror ra kết quả sai;")
    add("    dựng lại bằng erp.utils.family_relationship.rebuild_*_relationship_mirror.")
    add("  - [4] > 0 = còn family bị tách sai theo anh/chị/em; gộp family trước khi bỏ linked_family.")
    add("  - Mọi số ở trên chỉ ĐO. File này không sửa gì; việc sửa nằm ở patch/endpoint riêng.")
    add("=" * 78)
    return "\n".join(L)


@frappe.whitelist()
def run_all(as_dict=0):
    """
    Chạy cả 5 chỉ số và in báo cáo text dễ đọc.

        bench --site <site> execute erp.api.crm.family_diagnostics.run_all

    - Chạy từ CLI: in thẳng ra terminal (bench execute json-dump giá trị trả về nên
      trả None để không in lại bản escape \\n).
    - Chạy qua HTTP: trả về chuỗi text.
    - as_dict=1: trả {"text": ..., "data": ...} để lưu/so sánh về sau.
    """
    _require_access()
    data = collect_all()
    text = _format_report(data)
    if _truthy(as_dict):
        return {"text": text, "data": data}
    if _is_cli():
        print(text)
        return None
    return text
