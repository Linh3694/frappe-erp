# Copyright (c) 2026, Wellspring International School
"""
Dựng lại hai bản MIRROR của quan hệ gia đình + đồng bộ số/email phẳng của CRM Guardian.

    # 1. Rà soát (KHÔNG ghi gì) — luôn chạy trước:
    bench --site <site> execute erp.scripts.rebuild_family_mirrors.run

    # 2. Chạy thật:
    bench --site <site> execute erp.scripts.rebuild_family_mirrors.run \
        --kwargs "{'dry_run': 0}"

    # Chỉ làm mirror, không đụng số phẳng (hoặc ngược lại):
    ... --kwargs "{'dry_run': 0, 'do_contacts': 0}"
    ... --kwargs "{'dry_run': 0, 'do_mirrors': 0}"

-----------------------------------------------------------------------------------------
LÀM GÌ
-----------------------------------------------------------------------------------------
A. MIRROR. `CRM Family Relationship` được lưu ở BA nơi cho cùng một sự thật:
     CRM Family.relationships           <- bản CHUẨN
     CRM Student.family_relationships   <- mirror
     CRM Guardian.student_relationships <- mirror
   Script dựng lại hai bản mirror TỪ bản chuẩn, nhưng CHỈ cho những bản ghi thật sự lệch:

     - mirror MỒ CÔI  : cặp có ở mirror mà không có ở bản chuẩn
     - THIẾU mirror   : cặp có ở bản chuẩn mà không có ở mirror
     - LỆCH GIÁ TRỊ   : có cả hai nhưng access / key_person / can_pickup khác nhau

   Vì sao đáng làm: có consumer đọc THẲNG mirror chứ không đọc bản chuẩn — rõ nhất là
   erp/api/parent_portal/menu_registration.py, nó cố ý chỉ đọc `student_relationships`
   của Guardian. Thiếu mirror ở đó nghĩa là phụ huynh không đăng ký được suất ăn cho con
   dù quan hệ chuẩn vẫn đúng, và không có thông báo lỗi nào.

B. SỐ / EMAIL PHẲNG. `CRM Guardian.phone_number` và `.email` là mirror của dòng
   `is_primary` trong bảng con. Các endpoint sửa từng số lưu với `flags.ignore_validate`
   nên `CRMGuardian.validate()` — nơi sync chiều bảng-con -> phẳng — bị bỏ qua, và field
   phẳng đứng im ở giá trị lúc tạo. Hậu quả kép: dedup so trên field phẳng vừa CHẶN OAN
   (số cũ đã xoá vẫn chặn người khác đăng ký) vừa LỌT (số mới ở bảng con không ai thấy).
   Đây chính là gốc của những cặp "via child" mà script gộp guardian không bắt được.

   Luật lấy giá trị đúng dùng lại `erp.api.erp_sis.guardian._derive_primary_phone_from_rows`
   — cùng hàm runtime đang dùng, để script và code không thể lệch ngữ nghĩa.

-----------------------------------------------------------------------------------------
BA ĐIỀU CẦN BIẾT
-----------------------------------------------------------------------------------------
1. CHỈ đụng bản ghi lệch. Dựng lại toàn bộ 1762 học sinh + 2514 guardian vừa chậm vừa
   sinh một đống doc-event vô ích — `CRM Student` / `CRM Guardian` đều có `on_update` bắn
   đồng bộ nhóm chat (hooks.py).

2. Guardian KHÔNG có dòng chuẩn nào vẫn có thể cần dọn: nếu mirror của họ còn sót dòng
   thì đó là mirror mồ côi, và `rebuild_*` sẽ set bảng con về rỗng. Vì vậy tập cần xử lý
   lấy từ HỢP của (bản chuẩn ∪ mirror), không phải chỉ từ bản chuẩn.

3. KHÔNG tự đặt `is_primary`. Script chỉ đọc dòng is_primary có sẵn để đồng bộ xuống
   field phẳng. Chọn số nào làm số chính là quyết định nghiệp vụ; bảng con không có dòng
   nào đánh dấu thì lấy dòng đầu (đúng luật runtime), và ca đó được BÁO RA.
"""

from collections import defaultdict

import frappe

from erp.api.erp_sis.guardian import (
    _derive_primary_email_from_rows,
    _derive_primary_phone_from_rows,
)
from erp.utils.family_relationship import (
    _has_can_pickup,
    rebuild_guardian_relationship_mirror,
    rebuild_student_relationship_mirror,
)

CANONICAL = "relationships"
STUDENT_MIRROR = "family_relationships"
GUARDIAN_MIRROR = "student_relationships"

# Chặn nạp cả bảng vào RAM nếu dữ liệu phình bất thường (cùng ngưỡng family_diagnostics).
MAX_SCAN_ROWS = 300000


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _flag_cols():
    cols = ["key_person", "access"]
    if _has_can_pickup():
        cols.append("can_pickup")
    return cols


def _load_rows():
    """Mọi dòng quan hệ, kèm cờ — một lượt quét, gom trong Python."""
    total = _int(
        frappe.db.sql("SELECT COUNT(*) FROM `tabCRM Family Relationship`", as_dict=False)[0][0]
    )
    if total > MAX_SCAN_ROWS:
        frappe.throw(
            f"CRM Family Relationship co {total} dong (> {MAX_SCAN_ROWS}). Nang MAX_SCAN_ROWS."
        )
    flags = _flag_cols()
    flag_sql = ", ".join(f"IFNULL(fr.`{c}`, 0) AS `{c}`" for c in flags)
    return frappe.db.sql(
        f"""
        SELECT fr.name, fr.parent, fr.parenttype, fr.parentfield,
               fr.student, fr.guardian, {flag_sql},
               f.name AS family_alive
        FROM `tabCRM Family Relationship` fr
        LEFT JOIN `tabCRM Family` f
               ON f.name = fr.parent AND f.docstatus < 2 AND fr.parentfield = %(canon)s
        WHERE IFNULL(fr.student, '') <> '' AND IFNULL(fr.guardian, '') <> ''
        """,
        {"canon": CANONICAL},
        as_dict=True,
    ) or []


def _diff_mirrors():
    """Tập student / guardian cần dựng lại, kèm lý do để báo cáo."""
    flags = _flag_cols()
    rows = _load_rows()

    canonical = {}
    student_mirror = defaultdict(dict)
    guardian_mirror = defaultdict(dict)

    for r in rows:
        pair = (r["student"], r["guardian"])
        pf = r["parentfield"]
        if pf == CANONICAL:
            # family_alive rỗng = dòng chuẩn trỏ tới family đã xoá/cancel -> không tính.
            if r.get("family_alive"):
                canonical[pair] = r
        elif pf == STUDENT_MIRROR and r["parent"] == r["student"]:
            student_mirror[r["student"]][pair] = r
        elif pf == GUARDIAN_MIRROR and r["parent"] == r["guardian"]:
            guardian_mirror[r["guardian"]][pair] = r

    canon_by_student = defaultdict(set)
    canon_by_guardian = defaultdict(set)
    for (sid, gid) in canonical:
        canon_by_student[sid].add((sid, gid))
        canon_by_guardian[gid].add((sid, gid))

    students = {}
    guardians = {}

    def _check(owner_map, canon_map, mirror_map, bucket):
        for owner in set(owner_map) | set(mirror_map):
            want = canon_map.get(owner, set())
            have = mirror_map.get(owner, {})
            orphan = [p for p in have if p not in canonical]
            missing = [p for p in want if p not in have]
            drift = []
            for p in want:
                if p not in have:
                    continue
                c, m = canonical[p], have[p]
                if any(_int(c.get(f)) != _int(m.get(f)) for f in flags):
                    drift.append(p)
            if orphan or missing or drift:
                bucket[owner] = {
                    "orphan": len(orphan),
                    "missing": len(missing),
                    "drift": len(drift),
                }

    _check(canon_by_student, canon_by_student, student_mirror, students)
    _check(canon_by_guardian, canon_by_guardian, guardian_mirror, guardians)
    return students, guardians


def _contact_drift(fill_empty=0):
    """Guardian có field phẳng MỒ CÔI so với bảng con.

    ĐỊNH NGHĨA HẸP, cố ý. "Lệch dòng is_primary" là tiêu chí SAI để tự động ghi:

    - `CRM Guardian.phone_number` là thứ ĐĂNG NHẬP tra (otp_auth tra đúng field phẳng,
      không đọc bảng con). Số phẳng khác dòng is_primary nhưng VẪN nằm trong bảng con
      nghĩa là nó vẫn là một số thật của người ta và đăng nhập đang chạy tốt — ghi đè là
      đá phụ huynh ra khỏi tài khoản. Bản dry-run đầu tiên định đổi số của Cao Hải Đăng,
      Trần Ngọc Yến... đều là người vừa gộp xong và đang dùng portal.
    - Field phẳng RỖNG mà bảng con có giá trị thì là chuyện khác: 1800+ email đang rỗng.
      Điền hàng loạt có thể bật luồng gửi thư tới địa chỉ trước nay im lặng, nên phải
      BẬT TƯỜNG MINH bằng `fill_empty`, không làm mặc định.

    Chỉ ghi khi giá trị phẳng KHÔNG còn tồn tại trong bảng con — lúc đó nó chắc chắn là
    rác (số/email đã bị xoá khỏi bảng con mà quên dọn field phẳng), và chính nó gây ra
    lớp bug "chặn oan" ở dedup.
    """
    phones = defaultdict(list)
    for r in frappe.db.sql(
        """
        SELECT parent, phone_number, IFNULL(is_primary, 0) AS is_primary, idx
        FROM `tabCRM Guardian Phone`
        WHERE parenttype = 'CRM Guardian' AND IFNULL(TRIM(phone_number), '') <> ''
        ORDER BY parent, idx
        """,
        as_dict=True,
    ) or []:
        phones[r["parent"]].append(r)

    emails = defaultdict(list)
    for r in frappe.db.sql(
        """
        SELECT parent, email_address, IFNULL(is_primary, 0) AS is_primary, idx
        FROM `tabCRM Guardian Email`
        WHERE parenttype = 'CRM Guardian' AND IFNULL(TRIM(email_address), '') <> ''
        ORDER BY parent, idx
        """,
        as_dict=True,
    ) or []:
        emails[r["parent"]].append(r)

    flat = {
        r["name"]: r
        for r in frappe.db.sql(
            "SELECT name, phone_number, email FROM `tabCRM Guardian`", as_dict=True
        ) or []
    }

    out = []
    skipped_still_valid = 0

    def _collect(name, rows, field, flat_key, want, child_values):
        nonlocal skipped_still_valid
        cur = flat.get(name)
        if cur is None or not want:
            return
        have = (cur.get(flat_key) or "").strip()
        if want.casefold() == have.casefold():
            return
        if have and have.casefold() in child_values:
            # Giá trị phẳng vẫn là một giá trị THẬT của người này -> không đụng.
            skipped_still_valid += 1
            return
        if not have and not fill_empty:
            return
        out.append(
            {
                "guardian": name,
                "field": field,
                "from": have,
                "to": want,
                "kind": "dien vao cho rong" if not have else "thay gia tri mo coi",
                # Không dòng nào đánh dấu is_primary -> luật runtime lấy dòng đầu.
                # Báo ra để người phụ trách biết giá trị này là SUY, không phải khai.
                "no_primary_marked": not any(_int(r["is_primary"]) for r in rows),
            }
        )

    for name, rows in phones.items():
        vals = {(r["phone_number"] or "").strip().casefold() for r in rows}
        _collect(
            name, rows, "phone_number", "phone_number",
            (_derive_primary_phone_from_rows(rows) or "").strip(), vals,
        )
    for name, rows in emails.items():
        vals = {(r["email_address"] or "").strip().casefold() for r in rows}
        _collect(
            name, rows, "email", "email",
            (_derive_primary_email_from_rows(rows) or "").strip(), vals,
        )
    return sorted(out, key=lambda d: (d["guardian"], d["field"])), skipped_still_valid


def run(dry_run=1, do_mirrors=1, do_contacts=1, fill_empty=0, limit=0, verbose=1):
    """
    Dựng lại mirror lệch + dọn field phẳng mồ côi.

    dry_run      1 = chỉ báo cáo (mặc định).
    do_mirrors   0 = bỏ qua phần mirror.
    do_contacts  0 = bỏ qua phần số/email phẳng.
    fill_empty   1 = ĐIỀN cả những field phẳng đang RỖNG từ bảng con. Mặc định TẮT: có
                 hơn 1800 guardian đang rỗng `email`, điền hàng loạt có thể bật luồng gửi
                 thư tới địa chỉ trước nay im lặng. Bật khi đã xác nhận với nghiệp vụ.
    limit        Chỉ xử lý N bản ghi mỗi loại (0 = tất cả) — để thử trước.
    """
    dry_run = _int(dry_run)
    do_mirrors = _int(do_mirrors)
    do_contacts = _int(do_contacts)
    fill_empty = _int(fill_empty)
    limit = _int(limit)
    verbose = _int(verbose)

    students, guardians = _diff_mirrors() if do_mirrors else ({}, {})
    contacts, skipped_still_valid = (
        _contact_drift(fill_empty) if do_contacts else ([], 0)
    )

    result = {
        "params": {
            "dry_run": dry_run,
            "do_mirrors": do_mirrors,
            "do_contacts": do_contacts,
            "fill_empty": fill_empty,
            "limit": limit,
        },
        "contacts_skipped_still_valid": skipped_still_valid,
        "students": [{"name": k, **v} for k, v in sorted(students.items())],
        "guardians": [{"name": k, **v} for k, v in sorted(guardians.items())],
        "contacts": contacts,
        "applied": {"students": 0, "guardians": 0, "contacts": 0},
        "errors": [],
    }

    if not dry_run:
        for i, sid in enumerate(sorted(students)):
            if limit and i >= limit:
                break
            try:
                rebuild_student_relationship_mirror(sid)
                result["applied"]["students"] += 1
            except Exception as exc:
                frappe.db.rollback()
                frappe.log_error(
                    "rebuild_family_mirrors: loi dung lai mirror hoc sinh",
                    frappe.get_traceback(),
                )
                result["errors"].append({"target": sid, "error": str(exc)})
                continue
            frappe.db.commit()

        for i, gid in enumerate(sorted(guardians)):
            if limit and i >= limit:
                break
            try:
                rebuild_guardian_relationship_mirror(gid)
                result["applied"]["guardians"] += 1
            except Exception as exc:
                frappe.db.rollback()
                frappe.log_error(
                    "rebuild_family_mirrors: loi dung lai mirror guardian",
                    frappe.get_traceback(),
                )
                result["errors"].append({"target": gid, "error": str(exc)})
                continue
            frappe.db.commit()

        for i, c in enumerate(contacts):
            if limit and i >= limit:
                break
            # set_value + update_modified=False: đây là đồng bộ mirror, không phải người
            # dùng sửa dữ liệu — không nên làm nhiễu `modified`, nhất là khi đăng nhập
            # từng dựa vào cột đó để chọn bản ghi.
            frappe.db.set_value(
                "CRM Guardian", c["guardian"], c["field"], c["to"], update_modified=False
            )
            result["applied"]["contacts"] += 1
        frappe.db.commit()

    if verbose:
        _print(result)
    return result


def _print(result):
    mode = "DRY RUN — KHONG GHI GI" if result["params"]["dry_run"] else "DA GHI"
    print("=" * 78)
    print(f"DUNG LAI MIRROR QUAN HE + DONG BO SO/EMAIL PHANG  [{mode}]")
    print("=" * 78)

    print(f"[1] HOC SINH can dung lai mirror: {len(result['students'])}")
    for s in result["students"][:40]:
        print(
            f"    {s['name']}  mo coi={s['orphan']} thieu={s['missing']} lech={s['drift']}"
        )
    if len(result["students"]) > 40:
        print(f"    ... con {len(result['students']) - 40} ban ghi nua")
    print("")

    print(f"[2] GUARDIAN can dung lai mirror: {len(result['guardians'])}")
    for g in result["guardians"][:40]:
        print(
            f"    {g['name']}  mo coi={g['orphan']} thieu={g['missing']} lech={g['drift']}"
        )
    if len(result["guardians"]) > 40:
        print(f"    ... con {len(result['guardians']) - 40} ban ghi nua")
    print("")

    print(f"[3] SO/EMAIL PHANG can don: {len(result['contacts'])}")
    print(
        f"    (bo qua {result['contacts_skipped_still_valid']} truong hop gia tri phang "
        "van nam trong bang con — dang dung tot, KHONG dung vao)"
    )
    if not result["params"]["fill_empty"]:
        print("    (fill_empty=0: KHONG dien vao field phang dang rong. Bat khi da xac nhan.)")
    for c in result["contacts"][:40]:
        note = "  <- bang con KHONG co dong nao danh dau is_primary, lay dong dau" if c["no_primary_marked"] else ""
        print(f"    [{c['kind']}] {c['guardian']}.{c['field']}: '{c['from']}' -> '{c['to']}'{note}")
    if len(result["contacts"]) > 40:
        print(f"    ... con {len(result['contacts']) - 40} ban ghi nua")
    print("")

    if not result["params"]["dry_run"]:
        a = result["applied"]
        print(
            f"  DA GHI: {a['students']} hoc sinh, {a['guardians']} guardian, "
            f"{a['contacts']} field phang"
        )

    if result["errors"]:
        print("  --- LOI ---")
        for e in result["errors"]:
            print(f"  [LOI] {e['target']}: {e['error']}")

    if result["params"]["dry_run"]:
        print("  Chay that:  bench --site <site> execute "
              "erp.scripts.rebuild_family_mirrors.run --kwargs \"{'dry_run': 0}\"")
    print("=" * 78)
