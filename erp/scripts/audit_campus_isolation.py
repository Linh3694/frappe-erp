#!/usr/bin/env python3
"""
Audit campus isolation — DocType thiếu campus_id, record NULL, API leak patterns.
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


def main() -> int:
	print("=== Campus isolation audit ===\n")

	# 1. DocType không có campus_id (non-child)
	missing_field: list[str] = []
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
		fields = d.get("fields") or []
		if not any(f.get("fieldname") == "campus_id" for f in fields):
			missing_field.append(name)

	print(f"1. Non-child DocType KHÔNG có campus_id: {len(missing_field)}")
	for n in sorted(missing_field)[:25]:
		print(f"   - {n}")
	if len(missing_field) > 25:
		print(f"   ... +{len(missing_field) - 25} nữa")

	# 2. API gọi include_all_campuses / get_campus_filter_for_all_user_campuses
	api_leaks: list[str] = []
	for py in ERP.rglob("api/**/*.py"):
		text = py.read_text(encoding="utf-8", errors="ignore")
		if "get_campus_filter_for_all_user_campuses" in text:
			api_leaks.append(str(py.relative_to(ERP)))
		elif re.search(r"include_all_campuses\s*=\s*1", text):
			api_leaks.append(str(py.relative_to(ERP)) + " (default include_all=1)")

	print(f"\n2. API file dùng all-campus filter (cần review): {len(api_leaks)}")
	for p in sorted(set(api_leaks))[:20]:
		print(f"   - {p}")

	# 3. FE include_all_campuses
	fe_root = _APP_ROOT.parent.parent / "frappe-sis-frontend" / "src"
	if fe_root.is_dir():
		fe_hits: list[str] = []
		for ts in fe_root.rglob("*.{ts,tsx}"):
			pass
		for ext in ("*.ts", "*.tsx"):
			for ts in fe_root.rglob(ext):
				if "include_all_campuses" in ts.read_text(encoding="utf-8", errors="ignore"):
					fe_hits.append(str(ts.relative_to(fe_root)))
		print(f"\n3. FE gọi include_all_campuses: {len(fe_hits)}")
		for p in fe_hits[:15]:
			print(f"   - {p}")

	print("\nGợi ý: deploy fix get_campus_filter + get_active_campus_id, restart bench, test switch campus.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
