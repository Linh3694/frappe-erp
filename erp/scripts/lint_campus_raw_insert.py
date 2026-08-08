#!/usr/bin/env python3
"""
Lint: chặn `INSERT INTO \\`tabX\\`` thô mà thiếu cột `campus_id`.

Vì sao cần
----------
Hook `before_insert: inject_campus_id` CHỈ chạy với `doc.insert()`. Với
`frappe.db.sql("INSERT INTO ...")` thì hook không chạy, và bản ghi ra đời với
campus_id NULL — vô hình trong mọi danh sách đã lọc campus, đồng thời đọc được
từ mọi campus ở mức document.

Đây từng là nguyên nhân của 282.149 dòng `SIS Class Log Student` và 60.826 dòng
`SIS Teacher Timetable` bị NULL trên production (rà soát 2026-08-07).

`check_campus_doctype_hooks.py` KHÔNG bắt được loại lỗi này — nó chỉ kiểm tra
việc đăng ký hook, không đọc câu SQL.

Cách chạy
---------
    python3 erp/scripts/lint_campus_raw_insert.py            # quét toàn bộ erp/
    python3 erp/scripts/lint_campus_raw_insert.py a.py b.py  # chỉ vài file (pre-commit)

Thoát 0 nếu sạch, 1 nếu có vi phạm.

Bỏ qua có chủ đích
------------------
Thêm `# campus-lint: ignore` ở CÙNG dòng `INSERT INTO` hoặc dòng ngay trước đó,
kèm lý do. Chỉ dùng khi doctype thật sự không có campus_id hoặc code đã chết.
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(HERE)  # .../erp
REPO_ROOT = os.path.dirname(APP_ROOT)

IGNORE_MARK = "campus-lint: ignore"

# INSERT INTO `tabX` ( cols ) — chấp nhận xuống dòng giữa các phần
RE_INSERT_COLS = re.compile(
	r"INSERT\s+(?:IGNORE\s+)?INTO\s+`tab([^`]+)`\s*\(([^)]*)\)", re.IGNORECASE | re.DOTALL
)
# INSERT INTO `tabX` SELECT ... (không liệt kê cột) — không kiểm chứng được
RE_INSERT_NOCOLS = re.compile(
	r"INSERT\s+(?:IGNORE\s+)?INTO\s+`tab([^`]+)`\s*(?:SELECT|VALUES)", re.IGNORECASE
)


def doctypes_with_campus_id() -> set[str]:
	"""Đọc JSON doctype trên đĩa — KHÔNG cần frappe/DB, chạy được trong CI."""
	found = set()
	for root, _dirs, files in os.walk(APP_ROOT):
		if os.sep + "doctype" + os.sep not in root + os.sep:
			continue
		for fn in files:
			if not fn.endswith(".json"):
				continue
			path = os.path.join(root, fn)
			try:
				with open(path, encoding="utf-8") as fh:
					data = json.load(fh)
			except Exception:
				continue
			if data.get("doctype") != "DocType":
				continue
			name = data.get("name")
			if not name:
				continue
			for f in data.get("fields") or []:
				if f.get("fieldname") == "campus_id":
					found.add(name)
					break
	return found


# Số dòng nhìn ngược để tìm marker. Cần >2 vì câu SQL thường nằm sau một dòng
# gán kiểu `sql = f"""`, đẩy `INSERT INTO` ra xa comment.
LOOKBACK = 4


def _suppressed(lines: list[str], line_no: int) -> bool:
	"""Có `# campus-lint: ignore` ở dòng này hoặc vài dòng ngay trước không."""
	for back in range(LOOKBACK + 1):
		idx = line_no - 1 - back
		if 0 <= idx < len(lines) and IGNORE_MARK in lines[idx]:
			return True
	return False


def scan_file(path: str, campus_doctypes: set[str]) -> list[tuple[int, str, str]]:
	try:
		with open(path, encoding="utf-8") as fh:
			src = fh.read()
	except Exception:
		return []
	lines = src.split("\n")
	issues: list[tuple[int, str, str]] = []
	seen_spans: list[tuple[int, int]] = []

	for m in RE_INSERT_COLS.finditer(src):
		doctype, cols = m.group(1), m.group(2)
		seen_spans.append(m.span())
		if doctype not in campus_doctypes:
			continue
		line_no = src[: m.start()].count("\n") + 1
		if _suppressed(lines, line_no):
			continue
		col_names = {c.strip().strip("`") for c in cols.replace("\n", " ").split(",")}
		if "campus_id" not in col_names:
			issues.append((line_no, doctype, "thiếu cột campus_id"))

	# INSERT không liệt kê cột — không thể kiểm chứng, bắt buộc khai báo cột
	for m in RE_INSERT_NOCOLS.finditer(src):
		if any(s <= m.start() < e for s, e in seen_spans):
			continue
		doctype = m.group(1)
		if doctype not in campus_doctypes:
			continue
		line_no = src[: m.start()].count("\n") + 1
		if _suppressed(lines, line_no):
			continue
		issues.append((line_no, doctype, "INSERT không liệt kê cột — không kiểm chứng được campus_id"))

	return issues


def main(argv: list[str]) -> int:
	campus_doctypes = doctypes_with_campus_id()
	if not campus_doctypes:
		print("campus-lint: không đọc được doctype nào có campus_id — bỏ qua.")
		return 0

	targets: list[str] = []
	if argv:
		targets = [p for p in argv if p.endswith(".py") and os.path.exists(p)]
	else:
		for root, dirs, files in os.walk(APP_ROOT):
			dirs[:] = [d for d in dirs if d not in ("node_modules", "__pycache__", ".git")]
			targets.extend(os.path.join(root, f) for f in files if f.endswith(".py"))

	total = 0
	for path in sorted(targets):
		for line_no, doctype, reason in scan_file(path, campus_doctypes):
			rel = os.path.relpath(path, REPO_ROOT)
			print(f"{rel}:{line_no}: [{doctype}] {reason}")
			total += 1

	if total:
		print()
		print(f"❌ campus-lint: {total} lệnh INSERT thô thiếu campus_id.")
		print()
		print("   Hook inject_campus_id KHÔNG chạy với frappe.db.sql('INSERT INTO ...').")
		print("   Thêm cột campus_id vào danh sách cột VÀ giá trị tương ứng.")
		print("   Lấy campus theo DỮ LIỆU, ví dụ:")
		print("       campus_id = frappe.db.get_value('SIS Class', class_id, 'campus_id')")
		print("   Đừng lấy theo session — job nền chạy dưới Administrator sẽ đóng dấu sai campus.")
		print()
		print("   Nhớ đếm lại số cột và số placeholder sau khi thêm.")
		print("   Chi tiết: CLAUDE.md mục 1.3")
		print("   Nếu thực sự không áp dụng: thêm '# campus-lint: ignore' kèm lý do.")
		return 1

	print(f"OK — campus-lint: {len(targets)} file, không có INSERT thô thiếu campus_id.")
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
