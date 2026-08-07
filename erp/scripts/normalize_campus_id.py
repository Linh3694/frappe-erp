"""
GĐ 1 — Chuẩn hoá toàn bộ `campus_id` về CAMPUS-00001.

Tiền đề
-------
Chỉ CAMPUS-00001 (Wellspring 95 Ái Mộ) đang vận hành. CAMPUS-00002 và 2 campus Sài Gòn
(CAMPUS-00003/00004) là campus test, chưa campus nào khác hoạt động. Vì vậy mọi giá trị
`campus_id` khác CAMPUS-00001 — kể cả NULL — đều sai và gán thẳng về CAMPUS-00001 được,
không cần suy qua JOIN.

Đo trên prod 2026-08-07: 438.192 dòng cần chuẩn hoá, nằm trong 24 bảng.
  NULL/rỗng     361.990
  CAMPUS-00002   76.201   (do lỗi preference của Administrator — xem PHAN-TICH-268-GUARDIAN)
  'campus-2'          1   (trong bảng mồ côi)

Vì sao chạy được TRONG GIỜ
--------------------------
`campus_pq_enabled_doctypes` trên prod đang là chuỗi `'"*"'` (thừa cặp nháy) nên
permission query campus TẮT toàn site. Điền `campus_id` KHÔNG làm đổi bất kỳ danh sách
nào người dùng đang nhìn. Rủi ro duy nhất là tải DB → chia lô + nghỉ giữa các lô.

Nguyên tắc
----------
- Dùng SQL UPDATE trực tiếp, KHÔNG `doc.save()`: tránh sinh `tabVersion` (đã 3,19 GB)
  và tránh kích hoạt doc_events (vd. `on_guardian_changed` sẽ đẩy 268 job sync FaceID).
- Phát hiện bảng ĐỘNG qua information_schema, không hard-code, để không lệch khi schema đổi.
- Bỏ qua bảng mồ côi (DocType đã bị xoá) — xử lý ở GĐ 5.

Cách chạy
---------
    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.normalize_campus_id.run

    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.normalize_campus_id.run --kwargs "{'dry_run': False}"

    # chỉ một bảng, để thử trước:
    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.normalize_campus_id.run --kwargs "{'dry_run': False, 'only': 'tabCRM Guardian'}"

    # đảo ngược từ bảng sao lưu:
    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.normalize_campus_id.rollback --kwargs "{'dry_run': False}"
"""

from __future__ import annotations

import time

import frappe

TARGET = "CAMPUS-00001"
BACKUP_TABLE = "_bak_campus_normalize"
BATCH = 5000
SLEEP_BETWEEN_BATCHES = 1.0  # giây


def _as_bool(v) -> bool:
	if isinstance(v, str):
		return v.strip().lower() not in ("false", "0", "no", "")
	return bool(v)


def _tables_with_campus_id():
	db = frappe.conf.get("db_name")
	return [
		r["t"]
		for r in frappe.db.sql(
			"""
			SELECT TABLE_NAME t FROM information_schema.COLUMNS
			WHERE TABLE_SCHEMA=%s AND COLUMN_NAME='campus_id'
			ORDER BY TABLE_NAME
			""",
			(db,),
			as_dict=True,
		)
	]


def _is_orphan(table: str) -> bool:
	"""Bảng còn dữ liệu nhưng DocType tương ứng đã bị xoá."""
	if not table.startswith("tab"):
		return True
	return not frappe.db.exists("DocType", table[3:])


def _affected() -> int:
	"""Số dòng câu lệnh DML vừa rồi tác động.

	KHÔNG dùng `SELECT ROW_COUNT()` qua frappe.db.sql — frappe có thể chèn câu lệnh
	khác vào giữa, làm ROW_COUNT() trả giá trị của câu lệnh sai.
	"""
	cur = getattr(frappe.db, "_cursor", None)
	if cur is not None and getattr(cur, "rowcount", None) is not None:
		return max(int(cur.rowcount), 0)
	# Dự phòng: không xác định được -> trả -1 để vòng lặp dừng an toàn
	return -1


def _frappe_collation() -> str:
	"""Collation mà các bảng Frappe đang dùng.

	Bảng sao lưu PHẢI dùng đúng collation này, nếu không phép so `b.docname = c.name`
	sẽ ném lỗi 1267 "Illegal mix of collations". Mặc định của `CREATE TABLE ...
	DEFAULT CHARSET=utf8mb4` là utf8mb4_general_ci, KHÁC utf8mb4_unicode_ci của Frappe.
	"""
	db = frappe.conf.get("db_name")
	row = frappe.db.sql(
		"""SELECT COLLATION_NAME c FROM information_schema.COLUMNS
		   WHERE TABLE_SCHEMA=%s AND TABLE_NAME='tabDocType' AND COLUMN_NAME='name'""",
		(db,),
		as_dict=True,
	)
	return (row[0]["c"] if row and row[0].get("c") else "utf8mb4_unicode_ci")


def _ensure_backup_table():
	"""Tạo bảng sao lưu đúng collation, hoặc sửa collation nếu bảng đã tồn tại sai."""
	db = frappe.conf.get("db_name")
	coll = _frappe_collation()
	charset = coll.split("_")[0]

	if not frappe.db.sql("SHOW TABLES LIKE %s", (BACKUP_TABLE,)):
		frappe.db.sql(
			"""
			CREATE TABLE `%s` (
			  dt varchar(200), docname varchar(255), old_campus varchar(255),
			  KEY idx_dt_doc (dt, docname)
			) ENGINE=InnoDB DEFAULT CHARSET=%s COLLATE=%s
			""" % (BACKUP_TABLE, charset, coll)
		)
		print("   Da tao bang `%s` (collation %s)" % (BACKUP_TABLE, coll))
		return

	n = frappe.db.sql("SELECT COUNT(*) FROM `%s`" % BACKUP_TABLE)[0][0]
	cur = frappe.db.sql(
		"""SELECT COLLATION_NAME c FROM information_schema.COLUMNS
		   WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME='docname'""",
		(db, BACKUP_TABLE),
		as_dict=True,
	)
	cur_coll = cur[0]["c"] if cur else None
	print("   Bang `%s` da co san %d dong (collation %s) — se BO SUNG, khong ghi de."
	      % (BACKUP_TABLE, n, cur_coll))
	if cur_coll and cur_coll != coll:
		# Chuyen collation, GIU NGUYEN du lieu. Khong duoc xoa bang: gia tri campus_id
		# goc cua nhung dong da chuan hoa chi con ton tai o day.
		frappe.db.sql(
			"ALTER TABLE `%s` CONVERT TO CHARACTER SET %s COLLATE %s" % (BACKUP_TABLE, charset, coll)
		)
		frappe.db.commit()
		print("   Da chuyen collation %s -> %s (giu nguyen %d dong)" % (cur_coll, coll, n))


def _bad_count(table: str) -> int:
	return frappe.db.sql(
		"SELECT COUNT(*) FROM `%s` WHERE campus_id IS NULL OR campus_id='' OR campus_id<>%%s" % table,
		(TARGET,),
	)[0][0]


def _survey(only: str | None = None):
	"""Trả về [(bảng, số dòng sai)] và danh sách bảng mồ côi bị bỏ qua."""
	todo, orphans = [], []
	for t in _tables_with_campus_id():
		if only and t != only:
			continue
		try:
			n = _bad_count(t)
		except Exception as e:
			print("   ! bo qua %s (loi doc: %s)" % (t, e))
			continue
		if not n:
			continue
		if _is_orphan(t):
			orphans.append((t, n))
		else:
			todo.append((t, n))
	todo.sort(key=lambda x: -x[1])
	return todo, orphans


def run(dry_run: bool = True, only: str | None = None, batch: int = BATCH, sleep: float = SLEEP_BETWEEN_BATCHES):
	dry_run = _as_bool(dry_run)
	batch = int(batch)
	sleep = float(sleep)

	print("=== %s ===" % ("XEM TRUOC (dry run)" if dry_run else "THUC HIEN"))
	print()

	if not frappe.db.exists("SIS Campus", TARGET):
		print("! DUNG: campus dich %s khong ton tai" % TARGET)
		return

	print("### 0. Canh bao truoc khi chay")
	pq = frappe.conf.get("campus_pq_enabled_doctypes", "*")
	pq_off = (pq != "*") and ("SIS Class" not in pq)
	print("   campus_pq_enabled_doctypes = %r -> permission query dang %s"
	      % (pq, "TAT (an toan chay trong gio)" if pq_off else "BAT (can can trong!)"))
	if not pq_off:
		print("   ! Permission query dang BAT. Viec doi campus_id SE lam thay doi danh sach")
		print("     nguoi dung nhin thay. Can nhac chay ngoai gio.")

	print()
	print("### 1. Khao sat")
	todo, orphans = _survey(only)
	if not todo and not orphans:
		print("   Khong con dong nao can chuan hoa.")
		return
	print("   %-45s %10s" % ("BANG", "DONG SAI"))
	total = 0
	for t, n in todo:
		print("   %-45s %10d" % (t, n))
		total += n
	print("   %-45s %10d" % ("TONG", total))

	if orphans:
		print()
		print("   Bang MO COI (DocType da bi xoa) — BO QUA, xu ly o GD 5:")
		for t, n in orphans:
			print("     %-43s %10d" % (t, n))

	print()
	print("### 2. Phan bo gia tri sai hien tai")
	dist = {}
	for t, _ in todo:
		try:
			for r in frappe.db.sql(
				"""SELECT COALESCE(NULLIF(campus_id,''),'<NULL>') c, COUNT(*) n FROM `%s`
				   WHERE campus_id IS NULL OR campus_id='' OR campus_id<>%%s GROUP BY c""" % t,
				(TARGET,),
				as_dict=True,
			):
				dist[r["c"]] = dist.get(r["c"], 0) + r["n"]
		except Exception:
			pass
	for k in sorted(dist, key=lambda x: -dist[x]):
		print("   %-20s %10d" % (k, dist[k]))

	if dry_run:
		print()
		print("### 3. (dry run) Se thuc hien")
		print("   - Tao bang sao luu `%s` (doctype, docname, campus_id cu)" % BACKUP_TABLE)
		print("   - UPDATE %d dong tren %d bang, chia lo %d dong, nghi %.1fs giua cac lo"
		      % (total, len(todo), batch, sleep))
		print()
		print("   Chay lai voi --kwargs \"{'dry_run': False}\" de thuc hien that.")
		return

	print()
	print("### 3. Sao luu")
	_ensure_backup_table()

	# Chi sao luu docname CHUA co trong bang backup. Nho vay chay lai nhieu lan van
	# giu duoc gia tri GOC dau tien, khong bi ghi de bang gia tri da chuan hoa.
	for t, _ in todo:
		frappe.db.sql(
			"""INSERT INTO `%s` (dt, docname, old_campus)
			   SELECT %%s, c.name, c.campus_id FROM `%s` c
			   WHERE (c.campus_id IS NULL OR c.campus_id='' OR c.campus_id<>%%s)
			     AND NOT EXISTS (
			           SELECT 1 FROM `%s` b WHERE b.dt=%%s AND b.docname=c.name
			         )""" % (BACKUP_TABLE, t, BACKUP_TABLE),
			(t, TARGET, t),
		)
	frappe.db.commit()
	print("   Tong ban ghi trong `%s`: %d" % (
		BACKUP_TABLE, frappe.db.sql("SELECT COUNT(*) FROM `%s`" % BACKUP_TABLE)[0][0]))

	print()
	print("### 4. Chuan hoa")
	for t, n in todo:
		print("   %s (%d dong)" % (t, n))
		done = 0
		guard = 0
		while True:
			guard += 1
			if guard > 10000:
				print("      ! DUNG: vuot 10.000 lo, co the vong lap khong ket thuc")
				break
			frappe.db.sql(
				"""UPDATE `%s` SET campus_id=%%s
				   WHERE (campus_id IS NULL OR campus_id='' OR campus_id<>%%s)
				   LIMIT %d""" % (t, batch),
				(TARGET, TARGET),
			)
			affected = _affected()
			frappe.db.commit()
			if affected < 0:
				# Khong doc duoc rowcount -> chuyen sang dem truc tiep de biet con lai bao nhieu
				remaining = _bad_count(t)
				print("      (khong doc duoc rowcount) con lai: %d" % remaining)
				if remaining <= 0:
					break
				continue
			if affected == 0:
				break
			done += affected
			if n > batch:
				print("      ... %d/%d" % (done, n))
			if sleep:
				time.sleep(sleep)
		print("      xong: %d dong" % done)

	_verify()


def _verify():
	print()
	print("### 5. Nghiem thu")
	todo, orphans = _survey()
	if not todo:
		print("   Khong con bang nao co campus_id sai (ngoai bang mo coi).")
	else:
		print("   CON SOT:")
		for t, n in todo:
			print("     %-43s %10d" % (t, n))
	if orphans:
		print("   Bang mo coi con lai (co y bo qua):")
		for t, n in orphans:
			print("     %-43s %10d" % (t, n))

	print()
	print("   Phan bo campus_id toan DB:")
	agg = {}
	for t in _tables_with_campus_id():
		try:
			for r in frappe.db.sql(
				"SELECT COALESCE(NULLIF(campus_id,''),'<NULL>') c, COUNT(*) n FROM `%s` GROUP BY c" % t,
				as_dict=True,
			):
				agg[r["c"]] = agg.get(r["c"], 0) + r["n"]
		except Exception:
			pass
	for k in sorted(agg, key=lambda x: -agg[x]):
		print("     %-20s %12d" % (k, agg[k]))

	print()
	print("   Viec tiep theo: them hook inject_campus_id cho cac doctype con thieu (GD 2.2),")
	print("   neu khong cac bang `SIS Class Log *` se sinh lai dong NULL.")


def rollback(dry_run: bool = True):
	"""Khôi phục campus_id từ bảng sao lưu."""
	dry_run = _as_bool(dry_run)
	if not frappe.db.sql("SHOW TABLES LIKE %s", (BACKUP_TABLE,)):
		print("Khong tim thay bang sao luu `%s`." % BACKUP_TABLE)
		return
	rows = frappe.db.sql("SELECT dt, COUNT(*) n FROM `%s` GROUP BY dt ORDER BY n DESC" % BACKUP_TABLE, as_dict=True)
	print("Bang sao luu co:")
	for r in rows:
		print("   %-43s %10d" % (r["dt"], r["n"]))
	if dry_run:
		print("(dry run) Chay lai voi --kwargs \"{'dry_run': False}\" de khoi phuc that.")
		return
	for r in rows:
		t = r["dt"]
		frappe.db.sql(
			"""UPDATE `%s` c JOIN `%s` b ON b.dt=%%s AND b.docname=c.name
			   SET c.campus_id = b.old_campus""" % (t, BACKUP_TABLE),
			(t,),
		)
		frappe.db.commit()
		print("   khoi phuc %s" % t)
	print("Xong. Bang sao luu KHONG bi xoa — tu xoa khi da chac chan.")
