
import frappe
from datetime import datetime

def run():
    from datetime import datetime  # Đảm bảo có sẵn khi chạy trong console
    title = "12AB2"
    date_str = "2026-03-09"
    day_of_week = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A").lower()[:3]  # mon, tue, ...

    print("=" * 80)
    print(f"KIỂM TRA ĐIỂM LỚP WIS - Lớp {title} - Ngày {date_str}")
    print("=" * 80)

    # 1. Tìm class_id (12AB2 nằm ở short_title)
    class_doc = frappe.db.get_value(
        "SIS Class",
        {"short_title": title},
        ["name", "title", "short_title", "class_type"],
        as_dict=True
    )
    if not class_doc:
        class_doc = frappe.db.get_value(
            "SIS Class",
            {"title": title},
            ["name", "title", "short_title", "class_type"],
            as_dict=True
        )
    if not class_doc:
        class_doc = frappe.db.get_value(
            "SIS Class",
            title,
            ["name", "title", "short_title", "class_type"],
            as_dict=True
        )
    if not class_doc:
        print(f"\n[LỖI] Không tìm thấy lớp {title}")
        return

    class_id = class_doc.get("name") or title
    print(f"\n1. LỚP: {class_id} (title={class_doc.get('title')}, short_title={class_doc.get('short_title')}, type={class_doc.get('class_type')})")

    # 2. Lấy student_ids (homeroom)
    student_ids = frappe.get_all(
        "SIS Class Student",
        filters={"class_id": class_id},
        pluck="student_id"
    )
    print(f"   Số HS homeroom: {len(student_ids)}")

    # 3. Lấy mixed classes
    mixed_rows = frappe.db.sql("""
        SELECT cs.student_id, cs.class_id
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
        WHERE cs.student_id IN %(student_ids)s
            AND cs.class_id != %(class_id)s
            AND c.class_type = 'mixed'
    """, {"student_ids": student_ids, "class_id": class_id}, as_dict=True)

    all_class_ids = {class_id}
    for r in mixed_rows:
        all_class_ids.add(r["class_id"])
    print(f"   Các class_id (homeroom + mixed): {list(all_class_ids)}")
    # Kiểm tra class_type của từng lớp - nếu đều là regular thì không nên có HS "mix"
    for cid in all_class_ids:
        ct = frappe.db.get_value("SIS Class", cid, ["class_type", "short_title", "title"], as_dict=True)
        print(f"      - {ct.get('short_title') or ct.get('title')} ({cid}): class_type={ct.get('class_type')}")

    # 4. Timetable instances
    instance_rows = frappe.db.sql("""
        SELECT class_id, name
        FROM `tabSIS Timetable Instance`
        WHERE class_id IN %(class_ids)s
            AND start_date <= %(date)s
            AND end_date >= %(date)s
    """, {"class_ids": list(all_class_ids), "date": date_str}, as_dict=True)

    class_instances = {r["class_id"]: r["name"] for r in instance_rows}
    instance_ids = list(class_instances.values())
    print(f"\n2. TIMETABLE INSTANCES: {instance_ids}")

    if not instance_ids:
        print("[LỖI] Không có timetable instance")
        return

    # 5. Các tiết trong TKB (day_of_week)
    timetable_periods = frappe.db.sql("""
        SELECT tir.period_name, tir.parent
        FROM `tabSIS Timetable Instance Row` tir
        WHERE tir.parent IN %(instance_ids)s
            AND tir.day_of_week = %(dow)s
            AND LOWER(COALESCE(tir.period_name, '')) LIKE '%%tiết%%'
            AND (tir.valid_from IS NULL OR tir.valid_from <= %(date)s)
            AND (tir.valid_to IS NULL OR tir.valid_to >= %(date)s)
        ORDER BY tir.period_priority
    """, {"instance_ids": instance_ids, "dow": day_of_week, "date": date_str}, as_dict=True)

    period_set = sorted(set(r["period_name"] for r in timetable_periods if r.get("period_name")))
    print(f"\n3. CÁC TIẾT TRONG TKB (day={day_of_week}): {period_set}")

    # 6. Class Log Subject - lesson_score theo (class_id, period)
    subject_logs = frappe.db.sql("""
        SELECT cls.name, cls.period, cls.class_id, c.title, cls.lesson_score, cls.is_practise_test
        FROM `tabSIS Class Log Subject` cls
        INNER JOIN `tabSIS Class` c ON cls.class_id = c.name
        WHERE cls.timetable_instance_id IN %(instance_ids)s
            AND cls.log_date = %(date)s
            AND LOWER(cls.period) LIKE '%%tiết%%'
        ORDER BY cls.period, cls.class_id
    """, {"instance_ids": instance_ids, "date": date_str}, as_dict=True)

    print(f"\n4. SỔ ĐẦU BÀI (Class Log Subject) - lesson_score:")
    print("   " + "-" * 70)
    for sl in subject_logs:
        print(f"   class={sl['class_id']} ({sl['title']}) | period={sl['period']!r} | lesson_score={sl['lesson_score']} | is_practise_test={sl.get('is_practise_test')}")

    # 7. SIS Student Timetable - (student_id, period) -> class_id
    stt_rows = frappe.db.sql("""
        SELECT st.student_id, st.class_id, tc.period_name
        FROM `tabSIS Student Timetable` st
        INNER JOIN `tabSIS Timetable Column` tc ON st.timetable_column_id = tc.name
        WHERE st.student_id IN %(student_ids)s
            AND st.date = %(date)s
            AND LOWER(tc.period_name) LIKE '%%tiết%%'
    """, {"student_ids": student_ids, "date": date_str}, as_dict=True)

    # Map period_num -> period_name từ TKB
    import re
    def _extract_period_num(p):
        m = re.search(r"\d+", p or "")
        return int(m.group()) if m else None

    period_num_to_name = {_extract_period_num(p): p for p in period_set if _extract_period_num(p) is not None}

    student_period_class = {}
    for row in stt_rows:
        num = _extract_period_num(row["period_name"])
        pname = row["period_name"] if row["period_name"] in period_set else (period_num_to_name.get(num) if num in period_num_to_name else None)
        if pname:
            key = (row["student_id"], pname)
            if key not in student_period_class:
                student_period_class[key] = row["class_id"]

    # 8. Class Attendance (bổ sung)
    class_att = frappe.db.sql("""
        SELECT student_id, period, status, class_id
        FROM `tabSIS Class Attendance`
        WHERE date = %(date)s
            AND student_id IN %(student_ids)s
            AND LOWER(period) LIKE '%%tiết%%'
            AND class_id IN %(class_ids)s
    """, {"date": date_str, "student_ids": student_ids, "class_ids": list(all_class_ids)}, as_dict=True)

    for row in class_att:
        num = _extract_period_num(row["period"])
        pname = row["period"] if row["period"] in period_set else (period_num_to_name.get(num) if num in period_num_to_name else None)
        if pname:
            key = (row["student_id"], pname)
            if key not in student_period_class or student_period_class[key] == class_id:
                student_period_class[key] = row["class_id"]

    # 9. subject_by_class_period
    subject_by_class_period = {}
    for sl in subject_logs:
        key = (sl["class_id"], sl["period"])
        subject_by_class_period[key] = sl
        pnum = _extract_period_num(sl.get("period"))
        if pnum is not None:
            for pn in period_set:
                if _extract_period_num(pn) == pnum:
                    alt_key = (sl["class_id"], pn)
                    if alt_key not in subject_by_class_period:
                        subject_by_class_period[alt_key] = sl
                    break

    # 10. Tính Điểm lớp theo từng tiết (công thức thực tế)
    print(f"\n5. PHÂN BỐ HS THEO LỚP TỪNG TIẾT (student_period_class):")
    print("   (Mẫu: 5 học sinh đầu tiên)")

    for period in period_set:
        class_counts = {}
        for sid in student_ids:
            ac = student_period_class.get((sid, period), class_id)
            class_counts[ac] = class_counts.get(ac, 0) + 1

        # Lấy tên lớp (ưu tiên short_title như 12AB2)
        class_names = {}
        for cid in class_counts:
            doc = frappe.db.get_value("SIS Class", cid, ["short_title", "title"], as_dict=True)
            class_names[cid] = (doc.get("short_title") or doc.get("title")) if doc else cid

        print(f"\n   Tiết {period}:")
        for cid, cnt in sorted(class_counts.items(), key=lambda x: -x[1]):
            subj = subject_by_class_period.get((cid, period))
            ls = subj.get("lesson_score") if subj else None
            ls_val = int(ls or 0) if ls else 0
            print(f"      - {class_names.get(cid, cid)}: {cnt} HS, lesson_score={ls} -> {ls_val}")
            # Liệt kê HS học lớp chạy (khác homeroom)
            if cid != class_id and cnt > 0:
                mixed_students = [sid for sid in student_ids if student_period_class.get((sid, period), class_id) == cid]
                for sid in mixed_students[:5]:  # Tối đa 5 HS
                    stu_name = frappe.db.get_value("CRM Student", sid, ["student_name", "student_code"], as_dict=True)
                    name_str = (stu_name.get("student_name") or stu_name.get("student_code") or sid) if stu_name else sid
                    print(f"         + {name_str} ({sid})")
                if len(mixed_students) > 5:
                    print(f"         + ... và {len(mixed_students) - 5} HS khác")

    # 11. Tính weighted average từng tiết
    print(f"\n6. ĐIỂM TIẾT HỌC (weighted avg) VÀ TB NGÀY:")
    daily_scores = []
    for period in period_set:
        class_counts = {}
        for sid in student_ids:
            ac = student_period_class.get((sid, period), class_id)
            class_counts[ac] = class_counts.get(ac, 0) + 1

        weighted_sum = 0
        total_count = 0
        for cid, count in class_counts.items():
            subj = subject_by_class_period.get((cid, period))
            ls = subj.get("lesson_score") if subj else None
            try:
                weighted_sum += int(ls or 0) * count
            except (ValueError, TypeError):
                pass
            total_count += count

        if total_count > 0:
            score = weighted_sum / total_count
            daily_scores.append(score)
            print(f"   {period}: ({weighted_sum}/{total_count}) = {score:.2f}")

    if daily_scores:
        avg = sum(daily_scores) / len(daily_scores)
        print(f"\n   -> TB ngày: {avg:.2f}")
        print(f"   (So sánh: hiển thị 5.27)")

    # 12. Tổng hợp: HS nào học lớp chạy (khác homeroom)
    # Lưu ý: Nếu 10AB1 cũng là homeroom thì đây có thể là LỖI DỮ LIỆU - SIS Student Timetable hoặc Class Attendance gán sai
    print(f"\n7. HỌC SINH HỌC LỚP KHÁC 12AB2 (nguồn: SIS Student Timetable, Class Attendance):")
    mixed_by_class = {}  # class_id -> [(student_id, periods)]
    for sid in student_ids:
        for period in period_set:
            ac = student_period_class.get((sid, period), class_id)
            if ac != class_id:
                if ac not in mixed_by_class:
                    mixed_by_class[ac] = {}
                if sid not in mixed_by_class[ac]:
                    mixed_by_class[ac][sid] = []
                mixed_by_class[ac][sid].append(period)
    for cid, students in mixed_by_class.items():
        cname = frappe.db.get_value("SIS Class", cid, "short_title") or frappe.db.get_value("SIS Class", cid, "title") or cid
        ctype = frappe.db.get_value("SIS Class", cid, "class_type")
        print(f"\n   Lớp {cname} ({cid}, class_type={ctype}):")
        for sid, periods in students.items():
            stu = frappe.db.get_value("CRM Student", sid, ["student_name", "student_code"], as_dict=True)
            name_str = (stu.get("student_name") or stu.get("student_code") or sid) if stu else sid
            print(f"      - {name_str} ({sid})")
            print(f"        Tiết: {', '.join(periods)}")
        if ctype == "regular":
            print(f"      [!] {cname} là lớp regular/homeroom - HS 12AB2 không nên học ở đây!")
            # Debug: HS có trong SIS Class Student của lớp này không?
            for sid in students.keys():
                in_class = frappe.db.exists("SIS Class Student", {"student_id": sid, "class_id": cid})
                print(f"      [Debug] {sid} có trong SIS Class Student của {cname}? {bool(in_class)}")

    # 8b. Nguồn dữ liệu: SIS Student Timetable vs Class Attendance (cho HS bị gán lớp regular khác)
    debug_sid, debug_periods = None, []
    for cid in mixed_by_class:
        if frappe.db.get_value("SIS Class", cid, "class_type") == "regular":
            for s, pr in mixed_by_class[cid].items():
                debug_sid, debug_periods = s, pr
                break
            break
    if debug_sid and debug_periods:
        sample_period = debug_periods[0]
        pnum = _extract_period_num(sample_period)
        print(f"\n8. NGUỒN PHÂN LỚP - HS {debug_sid} tiết {sample_period}:")
        stt = frappe.db.sql("""
            SELECT st.name, st.class_id, tc.period_name
            FROM `tabSIS Student Timetable` st
            JOIN `tabSIS Timetable Column` tc ON st.timetable_column_id = tc.name
            WHERE st.student_id = %(sid)s AND st.date = %(date)s
            AND LOWER(tc.period_name) LIKE %(period_like)s
        """, {"sid": debug_sid, "date": date_str, "period_like": f"%{pnum}%"}, as_dict=True)
        att = frappe.db.sql("""
            SELECT name, class_id, period FROM `tabSIS Class Attendance`
            WHERE student_id = %(sid)s AND date = %(date)s AND LOWER(period) LIKE %(period_like)s
        """, {"sid": debug_sid, "date": date_str, "period_like": f"%{pnum}%"}, as_dict=True)
        print(f"   SIS Student Timetable: {stt}")
        print(f"   Class Attendance: {att}")

    print("\n" + "=" * 80)


# Gọi run() khi chạy - bắt buộc khi paste/exec
run()
