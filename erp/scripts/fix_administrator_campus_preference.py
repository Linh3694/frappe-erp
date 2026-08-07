"""
Sửa `SIS User Campus Preference` của Administrator về CAMPUS-00001.

Vì sao cần
----------
`get_current_campus_from_context()` không có guard cho Administrator. Frappe trả TOÀN BỘ
role cho Administrator, nên hàm này luôn coi Administrator là "user đa campus" và luôn
đọc bản ghi preference. Bản ghi đó do chính job nền `extend_daily_trips_job` tự tạo lúc
00:30:51 ngày 2026-05-28, seed bằng `get_user_campuses('Administrator')[0]` — phần tử đầu
của một truy vấn KHÔNG có ORDER BY (mặc định `modified desc`), tình cờ ra CAMPUS-00002.

Hậu quả đã đo trên prod: 76.201 dòng bị đóng dấu CAMPUS-00002, trong đó 74.779 dòng
`SIS Bus Daily Trip Student` do job nền sinh ra liên tục từ 28/05 đến 07/08.
Xem PHAN-TICH-268-GUARDIAN-CAMPUS-00002.md.

Đây là BĂNG DÁN — chặn thiệt hại ngay mà không cần deploy. Sửa gốc là thêm guard
Administrator vào `campus_utils.get_current_campus_from_context` (GĐ 2.1 của kế hoạch).

QUAN TRỌNG: sửa bằng UPDATE, TUYỆT ĐỐI KHÔNG XOÁ bản ghi này.
Nếu xoá, `get_or_create_preference` sẽ tạo lại và seed bằng campus có `modified` mới nhất
— hiện là CAMPUS-00001 (may mắn), nhưng chỉ cần ai đó sửa một campus test là giá trị seed
đổi sang campus test đó.

Cách chạy
---------
    # Xem trước:
    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.fix_administrator_campus_preference.run

    # Thực hiện:
    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.fix_administrator_campus_preference.run --kwargs "{'dry_run': False}"
"""

from __future__ import annotations

import frappe

TARGET_CAMPUS = "CAMPUS-00001"
USER = "Administrator"


def _as_bool(v) -> bool:
	if isinstance(v, str):
		return v.strip().lower() not in ("false", "0", "no", "")
	return bool(v)


def _show_state(label: str):
	print("### %s" % label)
	rows = frappe.db.sql(
		"""SELECT name, user, current_campus, default_campus, modified
		   FROM `tabSIS User Campus Preference` WHERE user=%s""",
		(USER,),
		as_dict=True,
	)
	if not rows:
		print("   (khong co ban ghi preference cho %s)" % USER)
	for r in rows:
		print(
			"   %s | current=%s | default=%s | modified=%s"
			% (r["name"], r["current_campus"], r["default_campus"], r["modified"])
		)
	return rows


def run(dry_run: bool = True):
	dry_run = _as_bool(dry_run)
	print("=== %s ===" % ("XEM TRUOC (dry run)" if dry_run else "THUC HIEN"))
	print()

	rows = _show_state("1. Truoc khi sua")

	print()
	print("### 2. Kiem tra dieu kien")
	if not frappe.db.exists("SIS Campus", TARGET_CAMPUS):
		print("   ! DUNG: campus dich %s khong ton tai" % TARGET_CAMPUS)
		return
	print("   campus dich %s: ton tai" % TARGET_CAMPUS)

	if not rows:
		print("   ! Khong co ban ghi de sua.")
		print("     Luu y: KHONG tao moi bang script nay — hay de he thong tu tao roi chay lai,")
		print("     hoac tao qua UI de di dung duong validate.")
		return

	need = [r for r in rows if r["current_campus"] != TARGET_CAMPUS or r["default_campus"] != TARGET_CAMPUS]
	if not need:
		print("   Da dung roi, khong can sua.")
		_report_others()
		return
	print("   Can sua %d ban ghi." % len(need))

	if dry_run:
		print()
		print("### 3. (dry run) Se thuc hien:")
		for r in need:
			print(
				"   UPDATE %s: current_campus %s -> %s, default_campus %s -> %s"
				% (r["name"], r["current_campus"], TARGET_CAMPUS, r["default_campus"], TARGET_CAMPUS)
			)
		print()
		print("   Chay lai voi --kwargs \"{'dry_run': False}\" de thuc hien that.")
		_report_others()
		return

	print()
	print("### 3. Sua")
	# Dung db.set_value: khong chay doc.save() nen khong sinh ban ghi tabVersion
	# (bang nay da 3,19 GB). Validation khong can vi Administrator co moi campus.
	for r in need:
		frappe.db.set_value(
			"SIS User Campus Preference",
			r["name"],
			{"current_campus": TARGET_CAMPUS, "default_campus": TARGET_CAMPUS},
		)
		print("   OK %s -> %s" % (r["name"], TARGET_CAMPUS))
	frappe.db.commit()

	print()
	_show_state("4. Sau khi sua")

	print()
	print("### 5. Kiem chung lai bang chinh ham he thong dung")
	try:
		from erp.sis.doctype.sis_user_campus_preference.sis_user_campus_preference import (
			SISUserCampusPreference,
		)

		print("   get_current_campus(Administrator) =", SISUserCampusPreference.get_current_campus(USER))
	except Exception as e:
		print("   (khong goi duoc:", e, ")")

	_report_others()

	print()
	print("### 7. Viec con lai")
	print("   - Theo doi job 00:30 dem nay: kiem tra khong con dong CAMPUS-00002 moi")
	print("     SELECT MAX(creation) FROM `tabSIS Bus Daily Trip Student` WHERE campus_id='CAMPUS-00002';")
	print("   - Chuyen 76.201 dong CAMPUS-00002 cu ve CAMPUS-00001 (GD 1 cua ke hoach)")
	print("   - Sua goc: them guard Administrator vao get_current_campus_from_context (GD 2.1)")


def _report_others(limit: int = 15):
	"""Bao cao TONG HOP (chi doc) cac preference bat thuong khac — khong tu sua."""
	print()
	print("### 6. Preference bat thuong khac (CHI BAO CAO, khong sua)")

	# Tong hop theo nhom, KHONG liet ke tung dong — co the co hang tram ban ghi.
	summary = frappe.db.sql(
		"""
		SELECT
		  CASE
		    WHEN (p.current_campus IS NULL OR p.current_campus='')
		     AND (p.default_campus IS NULL OR p.default_campus='') THEN 'ca hai NULL'
		    WHEN (p.current_campus IS NULL OR p.current_campus='') THEN 'chi current NULL'
		    WHEN (p.default_campus IS NULL OR p.default_campus='') THEN 'chi default NULL'
		    ELSE 'current <> default'
		  END loai,
		  CASE
		    WHEN p.user LIKE '%%@parent.%%' THEN 'phu huynh'
		    WHEN p.user LIKE '%%@wssg.edu.vn' OR p.user LIKE '%%@wellspringsaigon%%' THEN 'tai khoan SG'
		    ELSE 'noi bo/hoc sinh'
		  END nhom,
		  COUNT(*) n
		FROM `tabSIS User Campus Preference` p
		WHERE p.user <> %s
		  AND (p.current_campus IS NULL OR p.current_campus = ''
		       OR p.default_campus IS NULL OR p.default_campus = ''
		       OR p.current_campus <> p.default_campus)
		GROUP BY loai, nhom ORDER BY n DESC
		""",
		(USER,),
		as_dict=True,
	)
	if not summary:
		print("   (khong co)")
		return
	print("   %-20s %-18s %6s" % ("LOAI", "NHOM", "SO LUONG"))
	for r in summary:
		print("   %-20s %-18s %6d" % (r["loai"], r["nhom"], r["n"]))

	# Chi liet ke chi tiet nhom THUC SU dang lo: current <> default (lech nhau)
	mismatch = frappe.db.sql(
		"""
		SELECT p.user, p.current_campus, p.default_campus
		FROM `tabSIS User Campus Preference` p
		WHERE p.user <> %s
		  AND p.current_campus IS NOT NULL AND p.current_campus <> ''
		  AND p.default_campus IS NOT NULL AND p.default_campus <> ''
		  AND p.current_campus <> p.default_campus
		ORDER BY p.user LIMIT %s
		""",
		(USER, limit),
		as_dict=True,
	)
	if mismatch:
		print()
		print("   Nhom 'current <> default' (dang xem campus khac campus mac dinh):")
		for r in mismatch:
			print("     %-45s current=%-14s default=%s" % (r["user"], r["current_campus"], r["default_campus"]))

	print()
	print("   Ghi chu: 'ca hai NULL' KHONG gay hai neu user co dung 1 role campus —")
	print("   get_active_campus_id se bo qua preference rong va lay campus tu role.")
	print("   Chi nguy hiem voi user da campus (xem P1-6) hoac khong co role campus nao.")
