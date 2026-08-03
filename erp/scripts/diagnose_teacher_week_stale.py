#!/usr/bin/env python3
"""
Chẩn đoán TKB giáo viên không cập nhật sau khi sửa phân công giảng dạy.

TKB giáo viên đi qua 3 tầng, hỏng tầng nào cũng ra cùng một triệu chứng "sửa phân
công rồi mà TKB vẫn cũ":

    SIS Subject Assignment            (phân công — cái admin vừa sửa)
      → SIS Timetable Instance Row    (pattern rows, sync_assignment_to_timetable)
      → SIS Teacher Timetable         (materialized view, sync_for_rows)
      → Redis cache teacher_week:*    (TTL 300s, erp/api/erp_sis/timetable/weeks.py)

Script chỉ ĐỌC, không sửa gì. Nó in từng tầng để biết đứt ở đâu:
  - (1) có phân công mới, (2) pattern rows không có GV  → sync_assignment_to_timetable hỏng
  - (2) đúng, (3) thiếu/còn GV cũ                        → materialized view chưa sync
  - (2)(3) đúng, (5) còn key teacher_week                → cache stale (thứ tự invalidate)

Usage:
    bench --site your-site console

    from erp.scripts.diagnose_teacher_week_stale import diagnose
    diagnose("long.chuhai@wellspring.edu.vn", week_start="2026-08-03")
"""

from datetime import timedelta
from typing import Optional

import frappe


def _week_end(week_start: str) -> str:
	return str(frappe.utils.getdate(week_start) + timedelta(days=6))


def _resolve_teachers(email_or_id: str):
	"""Trả list SIS Teacher name — cùng cách get_teacher_week resolve (name hoặc user_id)."""
	ids = []
	if frappe.db.exists("SIS Teacher", email_or_id):
		ids.append(email_or_id)
	for t in frappe.get_all("SIS Teacher", fields=["name"], filters={"user_id": email_or_id}, limit=50):
		if t.name not in ids:
			ids.append(t.name)
	return ids


def diagnose(email_or_teacher_id: str, week_start: str, verbose: bool = True):
	ws = str(frappe.utils.getdate(week_start))
	we = _week_end(ws)

	teachers = frappe.get_all(
		"SIS Teacher",
		fields=["name", "user_id", "campus_id"],
		filters={"user_id": email_or_teacher_id},
	)
	tids = _resolve_teachers(email_or_teacher_id)

	print("=" * 78)
	print(f"🔎 TKB giáo viên: {email_or_teacher_id} | tuần {ws} .. {we}")
	print("=" * 78)
	print(f"SIS Teacher resolve → {tids}")
	for t in teachers:
		print(f"   {t.name}  user_id={t.user_id}  campus={t.campus_id}")
	if not tids:
		print("❌ Không tìm thấy SIS Teacher cho định danh này — dừng.")
		return {"stopped_at": "no_teacher"}

	result = {"teacher_ids": tids}

	# --- 1) Phân công ------------------------------------------------------
	print("\n--- 1) SIS Subject Assignment (phân công) ---")
	assignments = frappe.db.sql(
		"""
		SELECT sa.name, sa.class_id, c.title AS class_title, sa.actual_subject_id,
		       sa.application_type, sa.start_date, sa.end_date, sa.modified
		FROM `tabSIS Subject Assignment` sa
		LEFT JOIN `tabSIS Class` c ON c.name = sa.class_id
		WHERE sa.teacher_id IN %(t)s
		ORDER BY sa.modified DESC
		""",
		{"t": tuple(tids)},
		as_dict=True,
	)
	print(f"   count = {len(assignments)}")
	for a in assignments:
		print(
			f"   {a.name}  lớp={a.class_title or a.class_id}  môn={a.actual_subject_id}  "
			f"{a.application_type} {a.start_date or ''}..{a.end_date or ''}  sửa lúc {a.modified}"
		)
	result["assignments"] = len(assignments)

	# --- 2) Timetable Instance Row ------------------------------------------
	# ⚠️ GV nằm ở child table `SIS Timetable Instance Row Teacher` — teacher_1_id/
	# teacher_2_id đã DEPRECATED nên KHÔNG được dùng để tra.
	# ⚠️ Phân công `from_date` sinh OVERRIDE row (date NOT NULL), `full_year` sửa
	# PATTERN row (date IS NULL) — phải đếm cả hai.
	print("\n--- 2) SIS Timetable Instance Row (qua child table teachers) ---")
	rows = frappe.db.sql(
		"""
		SELECT r.name, r.parent, i.class_id, r.date, r.day_of_week, r.timetable_column_id,
		       r.subject_id, r.valid_from, r.valid_to, r.modified
		FROM `tabSIS Timetable Instance Row` r
		JOIN `tabSIS Timetable Instance` i ON i.name = r.parent
		JOIN `tabSIS Timetable Instance Row Teacher` rt
		     ON rt.parent = r.name AND rt.parentfield = 'teachers'
		WHERE rt.teacher_id IN %(t)s
		ORDER BY i.class_id, r.date, r.day_of_week
		""",
		{"t": tuple(tids)},
		as_dict=True,
	)
	pattern = [r for r in rows if not r.date]
	override = [r for r in rows if r.date]
	in_week = [r for r in override if ws <= str(r.date) <= we]
	print(f"   tổng = {len(rows)}   (pattern={len(pattern)}, override={len(override)}, "
	      f"override trong tuần={len(in_week)})")
	if verbose:
		for r in rows[:60]:
			print(
				f"   {r.class_id}  {r.date or 'PATTERN'}  {r.day_of_week}  cột={r.timetable_column_id}  "
				f"môn={r.subject_id}  hiệu lực {r.valid_from or ''}..{r.valid_to or ''}"
			)
		if len(rows) > 60:
			print(f"   ... (còn {len(rows) - 60} dòng)")
	result["pattern_rows"] = len(pattern)
	result["override_rows"] = len(override)
	result["rows_total"] = len(rows)

	# --- 2b) Dò từng phân công: vì sao sync ra 0 row? ------------------------
	# Replay find_pattern_rows() của timetable_sync_v2 — đây là chỗ sync bỏ cuộc
	# với "No pattern rows found", và lỗi đó đang bị nuốt trong except.
	print("\n--- 2b) Dò từng phân công (replay find_pattern_rows) ---")
	from erp.api.erp_sis.subject_assignment.timetable_sync_v2 import (
		find_pattern_rows,
		get_all_subject_ids_from_actual,
	)

	broken = []
	for a in assignments:
		doc = frappe.get_doc("SIS Subject Assignment", a.name)
		subj_ids = get_all_subject_ids_from_actual(doc.actual_subject_id, doc.campus_id) or []
		insts = frappe.get_all("SIS Timetable Instance", filters={"class_id": doc.class_id}, pluck="name")
		prows = find_pattern_rows(doc.class_id, doc.actual_subject_id, doc.campus_id) if subj_ids else []
		mine = len([
			r for r in rows
			if r.class_id == doc.class_id and (not r.date or ws <= str(r.date) <= we)
		])
		if not subj_ids:
			why = "❌ actual_subject KHÔNG map sang SIS Subject nào (campus này)"
		elif not insts:
			why = "❌ lớp chưa có SIS Timetable Instance"
		elif not prows:
			why = "❌ instance không có pattern row nào mang subject này (TKB lớp chưa xếp môn)"
		elif not mine:
			why = "⚠️ có pattern row nhưng GV chưa được gắn vào row nào"
		else:
			why = "✅ ok"
		if not why.startswith("✅"):
			broken.append((a.class_title or a.class_id, why))
		print(
			f"   {(a.class_title or a.class_id):<12} {doc.application_type:<10} "
			f"subjects={len(subj_ids)} instances={len(insts)} pattern_rows={len(prows)} "
			f"rows_có_GV={mine}  {why}"
		)
	result["broken"] = broken

	# --- 3) Materialized view ---------------------------------------------
	print(f"\n--- 3) SIS Teacher Timetable (materialized) tuần {ws}..{we} ---")
	tt = frappe.db.sql(
		"""
		SELECT name, class_id, date, day_of_week, timetable_column_id, subject_id,
		       timetable_instance_id, modified
		FROM `tabSIS Teacher Timetable`
		WHERE teacher_id IN %(t)s AND date BETWEEN %(ws)s AND %(we)s
		ORDER BY date, day_of_week
		""",
		{"t": tuple(tids), "ws": ws, "we": we},
		as_dict=True,
	)
	print(f"   count = {len(tt)}   ← đây chính là số ô hiển thị trên lưới TKB")
	for r in tt:
		print(
			f"   {r.date}  {r.day_of_week}  lớp={r.class_id}  cột={r.timetable_column_id}  "
			f"môn={r.subject_id}  sửa lúc {r.modified}"
		)
	result["teacher_timetable"] = len(tt)

	# --- 4) Đối chiếu pattern vs materialized ------------------------------
	print("\n--- 4) Đối chiếu pattern rows ↔ materialized ---")
	inst_ids = sorted({r.parent for r in rows})
	if not inst_ids:
		print("   (không có pattern row nào để đối chiếu)")
	else:
		instances = frappe.db.sql(
			"""
			SELECT name, class_id, start_date, end_date
			FROM `tabSIS Timetable Instance` WHERE name IN %(i)s
			""",
			{"i": tuple(inst_ids)},
			as_dict=True,
		)
		for e in instances:
			n_pattern = len([r for r in rows if r.parent == e.name])
			n_mat = len([x for x in tt if x.timetable_instance_id == e.name])
			covers = str(e.start_date) <= we and str(e.end_date) >= ws
			flag = "✅" if (not covers or n_mat) else "❌ THIẾU"
			print(
				f"   {flag} instance {e.name} lớp={e.class_id} ({e.start_date}..{e.end_date}, "
				f"phủ tuần này: {covers}) → pattern={n_pattern}, materialized trong tuần={n_mat}"
			)
	result["instances"] = len(inst_ids)

	# --- 5) Redis cache ----------------------------------------------------
	print("\n--- 5) Redis cache (TTL 300s) ---")
	cache = frappe.cache()
	conn = getattr(cache, "redis_cache", None) or cache
	cache_counts = {}
	for pat in ("*teacher_week:*", "*class_week:*", "*teacher_classes*"):
		try:
			keys = list(conn.scan_iter(match=pat, count=500))
			cache_counts[pat] = len(keys)
			print(f"   {pat} → {len(keys)} key")
			for k in keys[:10]:
				print(f"      {k}")
		except Exception as e:
			cache_counts[pat] = f"scan lỗi: {e}"
			print(f"   {pat} → scan lỗi: {e}")
	result["cache"] = cache_counts

	# --- Kết luận ----------------------------------------------------------
	print("\n" + "=" * 78)
	if not assignments:
		verdict = "Không có phân công nào cho GV này — kiểm tra lại phía phân công"
	elif broken:
		verdict = (
			f"SYNC ASSIGNMENT → INSTANCE ROW không chạy được cho {len(broken)} lớp "
			f"({', '.join(c for c, _ in broken[:6])}{'...' if len(broken) > 6 else ''}) — xem cột lý do ở khối 2b"
		)
	elif rows and not tt:
		verdict = "MATERIALIZED VIEW chưa sync (sync_for_rows) — chạy resync_all_teacher_timetables"
	elif rows and tt:
		verdict = "Dữ liệu nền ĐÚNG → nếu UI vẫn sai thì là cache teacher_week (thứ tự invalidate)"
	else:
		verdict = "Chưa kết luận được, xem chi tiết từng khối ở trên"
	print(f"📌 KẾT LUẬN: {verdict}")
	print("=" * 78)
	result["verdict"] = verdict
	return result


def diagnose_many(emails: list, week_start: str):
	"""Chạy cho nhiều GV, in bảng tổng hợp — phân biệt lỗi toàn cục vs lỗi 1 GV."""
	summary = []
	for email in emails:
		summary.append((email, diagnose(email, week_start, verbose=False)))

	print("\n" + "=" * 78)
	print("📊 TỔNG HỢP")
	print("=" * 78)
	print(f"{'Giáo viên':<38} {'PhânCông':>9} {'Pattern':>8} {'TKB':>5}  Kết luận")
	for email, r in summary:
		print(
			f"{email:<38} {r.get('assignments', 0):>9} {r.get('pattern_rows', 0):>8} "
			f"{r.get('teacher_timetable', 0):>5}  {r.get('verdict')}"
		)
	print("=" * 78)
	return summary
