#!/usr/bin/env python3
"""
Chẩn đoán TKB lớp trống trên trang Thời khoá biểu (get_class_week trả rỗng).

Replay đúng từng bước của erp.api.erp_sis.timetable.weeks.get_class_week và in ra
bước nào rớt về 0, kèm so sánh với cách Parent Portal đọc cùng dữ liệu
(erp.api.parent_portal.timetable) — dùng khi admin trống nhưng Parent Portal vẫn thấy TKB.

Usage:
    bench --site your-site console

    from erp.scripts.diagnose_class_week_empty import diagnose
    diagnose(class_title="1A2", week_start="2026-08-03")

    # Chỉ định năm học khi có nhiều lớp trùng tên:
    diagnose(class_title="1A2", week_start="2026-08-03", school_year_title="2026-2027")

    # Quét nhiều lớp một lượt (kiểm tra lỗi toàn cục hay chỉ 1 lớp):
    from erp.scripts.diagnose_class_week_empty import diagnose_many
    diagnose_many(["1A1", "1A2", "2A1"], week_start="2026-08-03")
"""

from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

import frappe

# Cùng bảng map với erp/api/erp_sis/timetable/helpers.py::_day_of_week_to_index
DOW_INDEX = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


def _to_date(value):
    """Chuẩn hoá Date/Datetime/chuỗi ISO về date. None nếu rỗng/không parse được."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year") and not hasattr(value, "hour"):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _day_index(dow: str) -> int:
    key = (dow or "").strip().lower()
    if "\n" in key:
        key = key.split("\n")[0].strip()
    elif "\\n" in key:
        key = key.split("\\n")[0].strip()
    return DOW_INDEX.get(key, -1)


def diagnose(
    class_title: str,
    week_start: str,
    school_year_title: Optional[str] = None,
    verbose: bool = True,
) -> dict:
    """
    Args:
        class_title: Tên lớp như trên UI (short_title hoặc title), vd "1A2"
        week_start: Thứ 2 của tuần đang xem, YYYY-MM-DD
        school_year_title: Lọc năm học khi có nhiều lớp trùng tên, vd "2026-2027"
        verbose: In chi tiết từng bước

    Returns:
        dict tóm tắt: {stopped_at, class_id, instances, rows_admin, rows_raw, entries_expected}
    """
    ws = _to_date(week_start)
    if not ws:
        print(f"❌ week_start không hợp lệ: {week_start} (cần YYYY-MM-DD)")
        return {"stopped_at": "bad_input"}
    we = ws + timedelta(days=6)

    result = {
        "stopped_at": None,
        "class_id": None,
        "instances": 0,
        "rows_admin": 0,
        "rows_raw": 0,
        "entries_expected": 0,
    }

    print("\n" + "=" * 78)
    print(f"🔍 CHẨN ĐOÁN TKB TRỐNG — lớp '{class_title}', tuần {ws} → {we}")
    print("=" * 78)

    # --- B1: SIS Class ----------------------------------------------------
    # SIS School Year không có cột `title` — tên năm học nằm ở title_vn/title_en
    classes = frappe.db.sql(
        """
        SELECT c.name, c.title, c.short_title, c.campus_id, c.school_year_id,
               COALESCE(y.title_vn, y.title_en) AS year_title
        FROM `tabSIS Class` c
        LEFT JOIN `tabSIS School Year` y ON y.name = c.school_year_id
        WHERE c.short_title = %(t)s OR c.title = %(t)s
        """,
        {"t": class_title},
        as_dict=True,
    )
    print(f"\n[B1] SIS Class khớp '{class_title}': {len(classes)} bản ghi")
    for c in classes:
        print(f"     {c.name} | title={c.title} | campus={c.campus_id} | năm={c.year_title}")

    if not classes:
        print("     ❌ DỪNG: không tìm thấy lớp — sai tên, sai campus hoặc sai năm học")
        result["stopped_at"] = "no_class"
        return result

    # Khớp lỏng: title_vn có thể là "Năm học 2026-2027"; cũng chấp nhận truyền thẳng docname
    matched = []
    if school_year_title:
        needle = school_year_title.strip().lower()
        matched = [
            c for c in classes
            if needle in (c.year_title or "").lower() or needle == (c.school_year_id or "").lower()
        ]
        if not matched:
            print(f"     ⚠️  Không lớp nào khớp năm học '{school_year_title}' — xét tất cả bản ghi")
    target = matched or classes
    class_id = target[0].name
    result["class_id"] = class_id

    if len(classes) > 1:
        print(f"     ⚠️  CÓ {len(classes)} BẢN GHI TRÙNG TÊN — import có thể ghi vào bản ghi")
        print(f"        khác với bản ghi UI đang đọc. Đang dùng: {class_id}")

    # --- B2: SIS Timetable Instance --------------------------------------
    all_inst = frappe.get_all(
        "SIS Timetable Instance",
        fields=["name", "timetable_id", "start_date", "end_date", "campus_id"],
        filters={"class_id": class_id},
        order_by="start_date asc",
    )
    print(f"\n[B2] Instance của lớp: {len(all_inst)}")
    for i in all_inst:
        covers = _to_date(i.start_date) <= we and _to_date(i.end_date) >= ws
        print(
            f"     {i.name} | {i.start_date} → {i.end_date} | campus={i.campus_id} "
            f"| {'✅ phủ tuần' if covers else '❌ ngoài tuần'}"
        )

    instances = [i for i in all_inst if _to_date(i.start_date) <= we and _to_date(i.end_date) >= ws]
    result["instances"] = len(instances)

    if not instances:
        print("     ❌ DỪNG: không instance nào phủ tuần → get_class_week trả []")
        print("        Nguyên nhân: ngày 'Áp dụng từ/đến' lúc import không phủ tuần đang xem.")
        result["stopped_at"] = "no_instance_covering_week"
        return result

    instance_ids = [i.name for i in instances]

    # --- B3: rows — filter admin vs filter Parent Portal ------------------
    admin_rows = frappe.get_all(
        "SIS Timetable Instance Row",
        fields=[
            "name", "parent", "day_of_week", "date",
            "valid_from", "valid_to", "timetable_column_id", "subject_id",
        ],
        filters={
            "parent": ["in", instance_ids],
            "parenttype": "SIS Timetable Instance",
            "parentfield": "weekly_pattern",
        },
    )
    raw_rows = frappe.db.sql(
        """
        SELECT name, parent, parentfield, parenttype, day_of_week, date,
               valid_from, valid_to
        FROM `tabSIS Timetable Instance Row`
        WHERE parent IN %(ids)s
        """,
        {"ids": tuple(instance_ids)},
        as_dict=True,
    )
    result["rows_admin"] = len(admin_rows)
    result["rows_raw"] = len(raw_rows)

    print(f"\n[B3] Rows theo filter TRANG ADMIN (parentfield='weekly_pattern'): {len(admin_rows)}")
    print(f"     Rows theo query PARENT PORTAL (không lọc parentfield):        {len(raw_rows)}")
    print(f"     Phân bố parentfield: {dict(Counter(r.parentfield for r in raw_rows))}")
    print(f"     Phân bố parenttype:  {dict(Counter(r.parenttype for r in raw_rows))}")

    if not raw_rows:
        print("     ❌ DỪNG: instance rỗng — import không ghi row nào vào instance này")
        result["stopped_at"] = "instance_has_no_rows"
        return result

    if not admin_rows:
        print("     ❌ DỪNG: rows tồn tại nhưng parentfield/parenttype không khớp filter admin")
        print("        → Trang admin trống trong khi Parent Portal vẫn thấy TKB")
        result["stopped_at"] = "parentfield_mismatch"
        return result

    # --- B4: lọc theo ngày render (logic hiện tại của _build_entries) -----
    pattern_rows = [r for r in admin_rows if not r.get("date")]
    override_rows = [r for r in admin_rows if r.get("date")]

    kept, dropped_by_date, dropped_by_dow = [], [], []
    for r in pattern_rows:
        idx = _day_index(r.get("day_of_week"))
        if idx < 0:
            dropped_by_dow.append(r)
            continue
        render_date = ws + timedelta(days=idx)
        vf = _to_date(r.get("valid_from"))
        vt = _to_date(r.get("valid_to"))
        if (vf and render_date < vf) or (vt and render_date > vt):
            dropped_by_date.append((r, render_date, vf, vt))
        else:
            kept.append(r)

    print(f"\n[B4] Pattern rows: {len(pattern_rows)} (+ {len(override_rows)} override theo ngày)")
    print(f"     Giữ lại sau lọc theo ngày render: {len(kept)}")
    print(f"     Loại vì day_of_week không map được: {len(dropped_by_dow)}")
    if dropped_by_dow:
        print(f"       giá trị lạ: {sorted({str(r.get('day_of_week')) for r in dropped_by_dow})}")
    print(f"     Loại vì ngoài [valid_from, valid_to]: {len(dropped_by_date)}")
    if verbose:
        for r, d, vf, vt in dropped_by_date[:8]:
            print(f"       {r.get('day_of_week')} render {d} ∉ [{vf} .. {vt}]  ({r.name})")
        if len(dropped_by_date) > 8:
            print(f"       ... và {len(dropped_by_date) - 8} row khác")

    result["entries_expected"] = len(kept) + len(override_rows)

    # --- Kết luận ---------------------------------------------------------
    print("\n" + "-" * 78)
    if kept or override_rows:
        print(f"✅ Backend PHẢI trả ~{result['entries_expected']} entries cho tuần này.")
        print("   UI vẫn trống ⇒ lỗi nằm ở cache hoặc frontend. Xoá cache rồi thử lại:")
        print("     frappe.cache().delete_keys('class_week:*')")
        result["stopped_at"] = "backend_ok_check_cache_or_fe"
    else:
        print("❌ Backend trả 0 entries.")
        if dropped_by_date and not dropped_by_dow:
            print("   Nguyên nhân: khoảng hiệu lực của rows không phủ các ngày trong tuần")
            print("   (valid_from/valid_to = ngày 'Áp dụng từ/đến' nhập lúc import).")
            result["stopped_at"] = "rows_out_of_valid_range"
        elif dropped_by_dow and not dropped_by_date:
            print("   Nguyên nhân: day_of_week trong DB không map được — xem giá trị lạ ở [B4].")
            result["stopped_at"] = "bad_day_of_week"
        else:
            print("   Nguyên nhân hỗn hợp — xem chi tiết [B4].")
            result["stopped_at"] = "rows_filtered_out"
    print("-" * 78)

    return result


def diagnose_api(
    class_id: str,
    week_start: str,
    as_user: Optional[str] = None,
    week_end: Optional[str] = None,
) -> dict:
    """
    Bước 2: gọi THẲNG endpoint get_class_week như request thật.

    diagnose() chạy dưới quyền Administrator nên KHÔNG áp permission query.
    Hàm này chạy lại dưới đúng user đang dùng UI để lộ chênh lệch phân quyền/campus.

    Usage:
        from erp.scripts.diagnose_class_week_empty import diagnose_api
        diagnose_api("SIS-CLASS-6137846", "2026-08-03", as_user="admin@wellspring.edu.vn")
    """
    from erp.api.erp_sis.timetable.weeks import get_class_week
    from erp.sis.utils.permission_query import (
        sis_timetable_instance_query,
        sis_timetable_instance_row_query,
    )
    from erp.utils.campus_utils import get_current_campus_from_context

    ws = _to_date(week_start)
    we_str = week_end or str(ws + timedelta(days=6))
    original_user = frappe.session.user
    out = {"user": as_user or original_user, "success": None, "count": None}

    print("\n" + "=" * 78)
    print(f"🔍 GỌI THẲNG get_class_week — lớp {class_id}, tuần {week_start} → {we_str}")
    print("=" * 78)

    try:
        if as_user:
            frappe.set_user(as_user)
        user = frappe.session.user
        print(f"\n[U] User: {user}")

        # Permission query áp lên frappe.get_all trong get_class_week
        try:
            cond_inst = sis_timetable_instance_query(user)
            cond_row = sis_timetable_instance_row_query(user)
            print(f"[P] Permission query SIS Timetable Instance    : {cond_inst or '(rỗng — không lọc)'}")
            print(f"[P] Permission query SIS Timetable Instance Row: {cond_row or '(rỗng — không lọc)'}")
            if cond_inst == "1=0" or cond_row == "1=0":
                print("     ❌ '1=0' ⇒ user KHÔNG có campus nào → mọi query trả rỗng")
        except Exception as e:
            print(f"[P] Không đọc được permission query: {e}")

        try:
            print(f"[C] Campus context của user: {get_current_campus_from_context()}")
        except Exception as e:
            print(f"[C] Không đọc được campus context: {e}")

        # Cache: get_class_week trả sớm nếu cache còn giá trị
        try:
            campus_id = get_current_campus_from_context()
            cache_key = f"class_week:{class_id}:{week_start}:{we_str}:{campus_id or 'none'}"
            cached = frappe.cache().get_value(cache_key)
            print(f"[K] Cache key: {cache_key}")
            print(f"[K] Cache hiện có: {('có, ' + str(len(cached)) + ' entries') if cached else 'trống'}")
        except Exception as e:
            print(f"[K] Không đọc được cache: {e}")

        # Gọi thật — form_dict được set trước nên hàm không chạm frappe.request
        frappe.local.form_dict = frappe._dict({
            "class_id": class_id,
            "week_start": week_start,
            "week_end": we_str,
        })
        res = get_class_week()

        success = res.get("success") if isinstance(res, dict) else None
        data = (res.get("data") if isinstance(res, dict) else None) or []
        out["success"] = success
        out["count"] = len(data)

        print(f"\n[R] success = {success}")
        print(f"[R] message = {res.get('message') if isinstance(res, dict) else res}")
        print(f"[R] số entries = {len(data)}")
        if data[:3]:
            print("[R] 3 entries đầu:")
            for e in data[:3]:
                print(
                    f"     {e.get('date')} | {e.get('day_of_week')} | {e.get('period_name')} "
                    f"| col={e.get('timetable_column_id')} | subj={e.get('subject_title') or e.get('subject_id')}"
                )

        print("\n" + "-" * 78)
        if not data:
            print("❌ API trả rỗng dưới user này trong khi dữ liệu DB đầy đủ")
            print("   → so sánh [P]/[C]: lỗi phân quyền campus hoặc campus context sai")
        else:
            print(f"✅ API trả {len(data)} entries → backend OK, lỗi nằm ở frontend")
            print("   Kiểm tra Network tab: request get_class_week gửi class_id/week_start nào")
        print("-" * 78)
    finally:
        if as_user:
            frappe.set_user(original_user)

    return out


def diagnose_many(class_titles: list, week_start: str, school_year_title: Optional[str] = None):
    """Chạy diagnose cho nhiều lớp, in bảng tổng hợp — phân biệt lỗi toàn cục vs lỗi 1 lớp."""
    summary = []
    for title in class_titles:
        res = diagnose(title, week_start, school_year_title, verbose=False)
        summary.append((title, res))

    print("\n" + "=" * 78)
    print("📊 TỔNG HỢP")
    print("=" * 78)
    print(f"{'Lớp':<10} {'Instance':>9} {'Rows admin':>11} {'Rows raw':>9} {'Entries':>8}  Kết luận")
    for title, r in summary:
        print(
            f"{title:<10} {r.get('instances', 0):>9} {r.get('rows_admin', 0):>11} "
            f"{r.get('rows_raw', 0):>9} {r.get('entries_expected', 0):>8}  {r.get('stopped_at')}"
        )
    print("=" * 78)
    return summary
