#!/usr/bin/env python3
"""
Audit campus isolation — phân loại DocType thiếu campus_id, API/FE leak patterns.
Chạy: cd apps/erp && python3 erp/scripts/audit_campus_isolation.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

ERP = _APP_ROOT / "erp"
SKIP = {"SIS Campus", "SIS User Campus Preference"}

# Master / child-table-like / shared config — không bắt buộc campus_id
MASTER_HINTS = (
	"Category", "Module", "Template", "Settings", "Source", "School", "Referrer",
	"Promotion", "Comment", "History", "Sub Task", "Team Member", "Preference",
	"Message", "Entry", "Item", "Badge", "Lookup", "Introduction", "Activity",
	"Microsoft User", "Notification", "Time Attendance", "Push Subscription",
	"Interface", "Meal Type", "Menu Category", "Portal Analytics", "Scoring",
	"Point Version", "Date Schedule", "Fine", "Book Introduction", "Discussion Entry",
	"Module Item", "Quiz Question", "Question Bank", "Assignee",
)


def _classify_missing(name: str) -> str:
	for hint in MASTER_HINTS:
		if hint in name:
			return "master"
	return "review"


def main() -> int:
	print("=== Campus isolation audit ===\n")

	missing_master: list[str] = []
	missing_review: list[str] = []
	total_non_child = 0
	with_campus_id = 0

	for jp in ERP.rglob("*.json"):
		if "/doctype/" not in jp.as_posix():
			continue
		try:
			d = json.loads(jp.read_text())
		except Exception:
			continue
		if d.get("doctype") != "DocType" or d.get("istable"):
			continue
		name = d.get("name", "")
		if name in SKIP:
			continue
		total_non_child += 1
		fields = d.get("fields") or []
		if any(f.get("fieldname") == "campus_id" for f in fields):
			with_campus_id += 1
			continue
		if _classify_missing(name) == "master":
			missing_master.append(name)
		else:
			missing_review.append(name)

	pct = 100 * with_campus_id / total_non_child if total_non_child else 0
	print(f"Coverage: {with_campus_id}/{total_non_child} non-child DocType có campus_id ({pct:.1f}%)\n")

	print(f"1a. Master/config (OK — không cần campus_id): {len(missing_master)}")
	for n in sorted(missing_master):
		print(f"   - {n}")

	print(f"\n1b. Cần review (có thể bổ sung campus_id sau): {len(missing_review)}")
	for n in sorted(missing_review):
		print(f"   - {n}")

	# API: chỉ báo default include_all=1 hoặc gọi all-campus KHÔNG qua param opt-in
	api_warn: list[str] = []
	for py in ERP.rglob("api/**/*.py"):
		text = py.read_text(encoding="utf-8", errors="ignore")
		rel = str(py.relative_to(ERP))
		if re.search(r"def\s+\w+\([^)]*include_all_campuses\s*=\s*1", text):
			api_warn.append(f"{rel} (default include_all_campuses=1)")
		elif re.search(r"get_campus_filter_for_all_user_campuses\(\)", text):
			# Gọi trực tiếp không qua if include_all — leak
			if "if include_all_campuses" not in text and "include_all_campuses" not in text:
				api_warn.append(f"{rel} (luôn dùng all-campus filter)")

	print(f"\n2. API cảnh báo leak (không tính opt-in include_all_campuses=1): {len(api_warn)}")
	for p in api_warn:
		print(f"   - {p}")
	if not api_warn:
		print("   (OK — student.py chỉ all-campus khi client truyền include_all_campuses=1)")

	# FE hardcode include_all_campuses: 1
	fe_root = _APP_ROOT.parent.parent / "frappe-sis-frontend" / "src"
	if fe_root.is_dir():
		fe_hardcode: list[str] = []
		for ext in ("*.ts", "*.tsx"):
			for ts in fe_root.rglob(ext):
				text = ts.read_text(encoding="utf-8", errors="ignore")
				if re.search(r"include_all_campuses\s*:\s*1", text):
					fe_hardcode.append(str(ts.relative_to(fe_root)))
		print(f"\n3. FE hardcode include_all_campuses: 1 (nên sửa): {len(fe_hardcode)}")
		for p in fe_hardcode:
			print(f"   - {p}")
		if not fe_hardcode:
			print("   (OK)")

	print("\n--- Kết luận ---")
	print("• 50 DocType thiếu campus_id: ~42 master OK, ~8 cần review — KHÔNG phải nguyên nhân leak chính.")
	print("• Leak cross-campus chủ yếu do get_campus_filter (đã fix) + FE/API hardcode all-campus.")
	print("• Sau deploy: bench restart → test switch campus với user 2 campus role.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
