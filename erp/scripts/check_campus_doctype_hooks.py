#!/usr/bin/env python3
"""
Kiểm tra DocType có campus_id phải có hooks permission_query + has_permission + wrapper.

Chạy từ thư mục app erp:
  cd apps/erp && python3 erp/scripts/check_campus_doctype_hooks.py

Hoặc qua bench:
  bench --site <site> execute erp.scripts.check_campus_doctype_hooks.main
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Bootstrap: chạy trực tiếp `python3 erp/scripts/...` từ apps/erp
_APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

from erp.scripts._campus_paths import resolve_erp_paths

APP_ROOT, ERP = resolve_erp_paths(__file__)
HOOKS = ERP / "hooks.py"

SKIP = {"SIS Campus", "SIS User Campus Preference"}


def _load_hooks_dict(name: str) -> dict:
	text = HOOKS.read_text(encoding="utf-8")
	ns: dict = {}
	start = text.find(f"{name} = {{")
	if start < 0:
		return {}
	depth = 0
	end = start
	for i, ch in enumerate(text[start:], start):
		if ch == "{":
			depth += 1
		elif ch == "}":
			depth -= 1
			if depth == 0:
				end = i + 1
				break
	block = text[start:end]
	exec(block, ns)  # noqa: S102
	return ns.get(name, {})


def _iter_doctype_jsons():
	for jp in ERP.rglob("*.json"):
		if "/doctype/" not in jp.as_posix():
			continue
		try:
			data = json.loads(jp.read_text(encoding="utf-8"))
		except Exception:
			continue
		if data.get("doctype") != "DocType":
			continue
		name = data.get("name", "")
		if not name or name in SKIP:
			continue
		fields = data.get("fields") or []
		if any(f.get("fieldname") == "campus_id" for f in fields):
			yield name, data


def _resolve_callable(dotted: str) -> bool:
	mod_path, _, fn_name = dotted.rpartition(".")
	rel = mod_path.removeprefix("erp.").replace(".", "/") + ".py"
	py_file = ERP / rel
	if not py_file.exists():
		return False
	text = py_file.read_text(encoding="utf-8")
	return f"def {fn_name}(" in text


def main() -> int:
	pq_hooks = _load_hooks_dict("permission_query_conditions")
	has_hooks = _load_hooks_dict("has_permission")

	missing_pq: list[str] = []
	missing_has: list[str] = []
	missing_wrapper: list[str] = []
	bad_field: list[str] = []

	for name, data in _iter_doctype_jsons():
		if name not in pq_hooks:
			missing_pq.append(name)
		elif not _resolve_callable(pq_hooks[name]):
			missing_wrapper.append(f"{name} → {pq_hooks[name]}")

		if name not in has_hooks:
			missing_has.append(name)

		for f in data.get("fields") or []:
			if f.get("fieldname") != "campus_id":
				continue
			if f.get("fieldtype") == "Link" and f.get("options") != "SIS Campus":
				bad_field.append(f"{name}: options={f.get('options')}")
			break

	ok = not (missing_pq or missing_has or missing_wrapper or bad_field)

	if missing_pq:
		print("Thiếu permission_query_conditions:")
		for m in missing_pq:
			print(f"  - {m}")
	if missing_has:
		print("Thiếu has_permission:")
		for m in missing_has:
			print(f"  - {m}")
	if missing_wrapper:
		print("Wrapper không tồn tại trong source:")
		for m in missing_wrapper:
			print(f"  - {m}")
	if bad_field:
		print("Field campus_id không chuẩn (Link options != SIS Campus):")
		for m in bad_field:
			print(f"  - {m}")

	if ok:
		total = sum(1 for _ in _iter_doctype_jsons())
		print(f"OK — {total} DocType campus_id đã đăng ký hooks + wrapper.")
		return 0

	return 1


if __name__ == "__main__":
	raise SystemExit(main())
