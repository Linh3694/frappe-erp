"""
Đổi tên 2 campus Sài Gòn về đúng định dạng autoname, rồi chỉnh bộ đếm naming series
để campus tạo sau đi đúng đường `format:CAMPUS-{#####}`.

Bối cảnh
--------
CAMPUS-6343158 / CAMPUS-6343161 được tạo với docname chỉ định sẵn, không qua autoname.
Điều này làm hỏng mọi đoạn code map campus theo chỉ số (`f"CAMPUS-{n:05d}"`), vốn
không bao giờ sinh ra được docname 7 chữ số. Xem BAO-CAO-QUAN-LY-DU-LIEU-THEO-CAMPUS.md.

An toàn
-------
Đã kiểm chứng trên prod 2026-08-07: cả 2 campus có **0 dòng** ở mọi cột `campus_id`
trên toàn bộ 195 bảng. Tham chiếu duy nhất là 138 dòng `User Permission.for_value`
(69 mỗi campus). Role campus đặt tên theo `title_en` nên không bị ảnh hưởng.

Thao tác này ĐẢO NGƯỢC ĐƯỢC (đổi tên ngược lại).

Cách chạy
---------
    # Xem trước, không ghi gì:
    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.rename_saigon_campuses.run

    # Thực hiện thật:
    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.rename_saigon_campuses.run --kwargs "{'dry_run': False}"

    # Đảo ngược nếu cần:
    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.rename_saigon_campuses.rollback --kwargs "{'dry_run': False}"
"""

from __future__ import annotations

import frappe

# Dùng hàm gốc, KHÔNG dùng alias `frappe.rename_doc`.
# Alias ở frappe/__init__.py có chữ ký hẹp hơn (không nhận `ignore_permissions`)
# và được bọc bởi lớp kiểm tra kiểu, nên truyền tham số thừa sẽ ném TypeError.
from frappe.model.rename_doc import rename_doc as _frappe_rename_doc

# (docname hiện tại, docname đích) — thứ tự theo creation
OLD_NEW = [
	("CAMPUS-6343158", "CAMPUS-00003"),  # Wellspring Sài Gòn
	("CAMPUS-6343161", "CAMPUS-00004"),  # Wellspring Nam Sài Gòn
]

# Bộ đếm series sau khi đổi tên — phải bằng số thứ tự campus lớn nhất,
# nếu không campus tạo tiếp theo sẽ trùng tên với campus vừa đổi.
SERIES_TARGET = 4
SERIES_PREFIX = "CAMPUS-"


def _series_row():
	rows = frappe.db.sql(
		"SELECT name, current FROM `tabSeries` WHERE name LIKE %s", (SERIES_PREFIX + "%",), as_dict=True
	)
	return rows[0] if rows else None


def _count_refs(docname: str) -> list[tuple[str, str, int]]:
	"""Đếm mọi tham chiếu tới docname trong các cột có thể chứa campus."""
	db = frappe.conf.get("db_name")
	cols = frappe.db.sql(
		"""
		SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
		WHERE TABLE_SCHEMA=%s AND DATA_TYPE IN ('varchar','char')
		  AND (COLUMN_NAME LIKE '%%campus%%'
		       OR COLUMN_NAME IN ('for_value','current_campus','default_campus'))
		""",
		(db,),
		as_dict=True,
	)
	found = []
	for c in cols:
		try:
			n = frappe.db.sql(
				"SELECT COUNT(*) FROM `%s` WHERE `%s`=%%s" % (c["TABLE_NAME"], c["COLUMN_NAME"]),
				(docname,),
			)[0][0]
			if n:
				found.append((c["TABLE_NAME"], c["COLUMN_NAME"], n))
		except Exception:
			pass
	return found


def _rename(pairs, dry_run: bool):
	print("=== %s ===" % ("XEM TRUOC (dry run)" if dry_run else "THUC HIEN"))
	print()

	print("### 1. Trang thai truoc")
	for r in frappe.db.sql(
		"SELECT name, title_vn, title_en, short_title FROM `tabSIS Campus` ORDER BY creation", as_dict=True
	):
		print("   %-16s | %-26s | %-24s | %s" % (r["name"], r["title_vn"], r["title_en"], r["short_title"]))
	print("   naming series:", _series_row())

	print()
	print("### 2. Kiem tra dieu kien")
	blocked = False
	for old, new in pairs:
		if not frappe.db.exists("SIS Campus", old):
			print("   ! %s khong ton tai -> bo qua" % old)
			continue
		if frappe.db.exists("SIS Campus", new):
			print("   ! DUNG: %s da ton tai" % new)
			blocked = True
			continue
		refs = _count_refs(old)
		total = sum(n for _, _, n in refs)
		print("   %s -> %s | %d tham chieu" % (old, new, total))
		for tbl, col, n in refs:
			print("       %s.%s = %d" % (tbl, col, n))
	if blocked:
		print()
		print("   => Co dieu kien khong thoa. Dung lai.")
		return

	if dry_run:
		print()
		print("### 3. (dry run) Se thuc hien:")
		for old, new in pairs:
			print("   rename_doc('SIS Campus', %r, %r)" % (old, new))
		print("   UPDATE tabSeries SET current=%d" % SERIES_TARGET)
		print()
		print("   Chay lai voi --kwargs \"{'dry_run': False}\" de thuc hien that.")
		return

	print()
	print("### 3. Doi ten")
	for old, new in pairs:
		if not frappe.db.exists("SIS Campus", old):
			continue
		title = frappe.db.get_value("SIS Campus", old, "title_vn")
		_frappe_rename_doc(
			doctype="SIS Campus",
			old=old,
			new=new,
			force=True,
			ignore_permissions=True,
			show_alert=False,
		)
		frappe.db.commit()
		print("   OK  %s -> %s   (%s)" % (old, new, title))

	print()
	print("### 4. Vet con sot (User Permission.for_value co the khong duoc rename_doc cap nhat)")
	for old, new in pairs:
		refs = _count_refs(old)
		if not refs:
			print("   %s: sach" % old)
			continue
		for tbl, col, n in refs:
			frappe.db.sql("UPDATE `%s` SET `%s`=%%s WHERE `%s`=%%s" % (tbl, col, col), (new, old))
			print("   %s: da sua %s.%s (%d dong)" % (old, tbl, col, n))
		frappe.db.commit()

	print()
	print("### 5. Bo dem naming series")
	row = _series_row()
	print("   truoc:", row)
	if row:
		frappe.db.sql("UPDATE `tabSeries` SET current=%s WHERE name=%s", (SERIES_TARGET, row["name"]))
	else:
		frappe.db.sql("INSERT INTO `tabSeries` (name, current) VALUES (%s, %s)", (SERIES_PREFIX, SERIES_TARGET))
	frappe.db.commit()
	print("   sau :", _series_row())

	_verify(pairs)


def _verify(pairs):
	print()
	print("### 6. Nghiem thu")
	print("   -- campus --")
	for r in frappe.db.sql(
		"SELECT name, title_vn, title_en, short_title FROM `tabSIS Campus` ORDER BY name", as_dict=True
	):
		print("   %-16s | %-26s | %-24s | %s" % (r["name"], r["title_vn"], r["title_en"], r["short_title"]))

	print("   -- tham chieu ten cu con sot --")
	leftover = 0
	for old, _ in pairs:
		for tbl, col, n in _count_refs(old):
			print("   CON SOT %s.%s = %s (%d)" % (tbl, col, old, n))
			leftover += n
	print("   tong con sot:", leftover)

	print("   -- User Permission --")
	for r in frappe.db.sql(
		"""SELECT for_value, COUNT(DISTINCT user) u, COUNT(*) n
		   FROM `tabUser Permission` WHERE allow='SIS Campus'
		   GROUP BY for_value ORDER BY for_value""",
		as_dict=True,
	):
		print("   %-16s %d user / %d ban ghi" % (r["for_value"], r["u"], r["n"]))

	print("   -- role campus (dat theo title_en nen khong doi) --")
	for r in frappe.db.sql("SELECT name FROM `tabRole` WHERE name LIKE 'Campus %' ORDER BY name", as_dict=True):
		print("   ", r["name"])

	print("   -- campus tiep theo se mang ten --")
	row = _series_row()
	nxt = (row["current"] if row else 0) + 1
	print("   CAMPUS-%05d" % nxt)


def run(dry_run: bool = True):
	"""Đổi tên 2 campus Sài Gòn về định dạng chuẩn. Mặc định chỉ xem trước."""
	_rename(OLD_NEW, dry_run=_as_bool(dry_run))


def rollback(dry_run: bool = True):
	"""Đảo ngược: trả 2 campus về docname cũ và hạ bộ đếm series về 2."""
	global SERIES_TARGET
	pairs = [(new, old) for old, new in OLD_NEW]
	SERIES_TARGET = 2
	_rename(pairs, dry_run=_as_bool(dry_run))


def _as_bool(v) -> bool:
	if isinstance(v, str):
		return v.strip().lower() not in ("false", "0", "no", "")
	return bool(v)
