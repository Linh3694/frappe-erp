#!/usr/bin/env python3
"""
Áp dụng campus_id schema + hooks cho DocType Phase 2.

Chạy: cd apps/erp && python3 erp/scripts/phase2_apply_campus_id.py [--phase dot0|...|all]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

from erp.scripts._campus_paths import resolve_erp_paths

APP_ROOT, ERP = resolve_erp_paths(__file__)

from erp.utils.campus_phase2_config import (  # noqa: E402
	CAMPUS_ID_FIELD,
	PHASE2_BACKFILL,
	all_phase2_doctypes,
	pq_module_for,
)

HOOKS = ERP / "hooks.py"
SIS_PQ = ERP / "sis" / "utils" / "permission_query.py"
CRM_PQ = ERP / "crm" / "utils" / "permission_query.py"
LMS_PQ = ERP / "lms" / "utils" / "permissions.py"
GENERIC_PQ = ERP / "utils" / "campus_permission_query.py"

INJECT_HOOK = "erp.utils.campus_document.inject_campus_id"
HAS_CAMPUS_SIS = "erp.sis.utils.campus_permissions.has_campus_permission"
HAS_CAMPUS_CRM = "erp.crm.utils.permission_query.has_crm_permission"
HAS_CAMPUS_LMS = "erp.lms.utils.permissions.has_lms_campus_permission"
HAS_CAMPUS_GENERIC = "erp.utils.campus_permission_query.has_campus_doctype_permission"
HAS_IT = "erp.it_support.permissions.has_it_support_ticket_permission"


def _slug(name: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def find_doctype_json(doctype: str) -> Path | None:
	for jp in ERP.rglob("*.json"):
		if "/doctype/" not in jp.as_posix():
			continue
		try:
			data = json.loads(jp.read_text(encoding="utf-8"))
			if data.get("doctype") == "DocType" and data.get("name") == doctype:
				return jp
		except Exception:
			pass
	return None


def apply_schema(doctype: str, dry_run: bool = False) -> bool:
	jp = find_doctype_json(doctype)
	if not jp:
		print(f"  SKIP schema {doctype}: không tìm thấy JSON")
		return False

	data = json.loads(jp.read_text(encoding="utf-8"))
	fields = data.get("fields") or []
	if any(f.get("fieldname") == "campus_id" for f in fields):
		return False

	field_order = data.get("field_order") or []
	insert_at = 1 if field_order and field_order[0].endswith("_section") or field_order[0] == "basic_information" else 0
	if "basic_information" in field_order:
		insert_at = field_order.index("basic_information") + 1
	elif field_order:
		insert_at = 1

	new_field = dict(CAMPUS_ID_FIELD)
	fields.insert(min(insert_at, len(fields)), new_field)
	if "campus_id" not in field_order:
		field_order.insert(insert_at, "campus_id")

	data["fields"] = fields
	data["field_order"] = field_order

	if not dry_run:
		jp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
	print(f"  + schema {doctype}")
	return True


def pq_path_and_fn(doctype: str) -> tuple[Path, str, str]:
	mod = pq_module_for(doctype)
	slug = _slug(doctype)
	fn = f"{slug}_query"
	if mod == "sis":
		return SIS_PQ, fn, f"erp.sis.utils.permission_query.{fn}"
	if mod == "crm":
		return CRM_PQ, fn, f"erp.crm.utils.permission_query.{fn}"
	if mod == "lms":
		fn = f"lms_{slug.replace('lms_', '')}_query" if not slug.startswith("lms_") else f"{slug}_query"
		if doctype == "LMS Announcement":
			fn = "lms_announcement_query"
		return LMS_PQ, fn, f"erp.lms.utils.permissions.{fn}"
	if mod == "it":
		return ERP / "it_support" / "permissions.py", "it_support_ticket_query", "erp.it_support.permissions.it_support_ticket_query"
	return GENERIC_PQ, fn, f"erp.utils.campus_permission_query.{fn}"


def ensure_pq_wrapper(doctype: str, dry_run: bool = False) -> bool:
	path, fn, _ = pq_path_and_fn(doctype)
	if not path.exists():
		return False
	text = path.read_text(encoding="utf-8")
	if f"def {fn}(" in text:
		return False

	if pq_module_for(doctype) == "it":
		return False

	if pq_module_for(doctype) == "lms":
		block = f'''

def {fn}(user):
\t"""Permission query for {doctype}."""
\treturn lms_campus_query(user, "{doctype}")
'''
	else:
		block = f'''

def {fn}(user):
\t"""Permission query for {doctype}."""
\treturn get_campus_permission_query("{doctype}", user)
'''
		if "get_campus_permission_query" not in text and path == CRM_PQ:
			if "from erp.sis.utils.permission_query import get_campus_permission_query" not in text:
				text = text.replace(
					"import frappe\n",
					"import frappe\n\nfrom erp.sis.utils.permission_query import get_campus_permission_query\n",
				)

	text = text.rstrip() + block + "\n"
	if not dry_run:
		path.write_text(text, encoding="utf-8")
	print(f"  + wrapper {fn} in {path.name}")
	return True


def has_perm_handler(doctype: str) -> str:
	mod = pq_module_for(doctype)
	if mod == "crm":
		return HAS_CAMPUS_CRM
	if mod == "lms":
		return HAS_CAMPUS_LMS
	if mod == "it":
		return HAS_IT
	if mod == "sis":
		return HAS_CAMPUS_SIS
	return HAS_CAMPUS_GENERIC


def update_hooks(doctypes: list[str], dry_run: bool = False) -> None:
	text = HOOKS.read_text(encoding="utf-8")

	pq_block = re.search(r"(permission_query_conditions\s*=\s*\{)([\s\S]*?)(\n\})", text)
	has_block = re.search(r"(has_permission\s*=\s*\{)([\s\S]*?)(\n\})", text)
	doc_block = re.search(r"(doc_events\s*=\s*\{)([\s\S]*?)(\n\})", text)

	if not pq_block or not has_block or not doc_block:
		raise RuntimeError("Không parse được hooks.py blocks")

	pq_inner = pq_block.group(2)
	has_inner = has_block.group(2)
	doc_inner = doc_block.group(2)

	for dt in doctypes:
		_, _, hook_path = pq_path_and_fn(dt)
		pq_line = f'\t"{dt}": "{hook_path}",'
		has_line = f'\t"{dt}": "{has_perm_handler(dt)}",'
		doc_entry = f'\t"{dt}": {{\n\t\t"before_insert": "{INJECT_HOOK}",\n\t}},'

		if f'"{dt}"' not in pq_inner:
			pq_inner += f"\n{pq_line}"
			print(f"  + hook pq {dt}")

		if f'"{dt}"' not in has_inner:
			has_inner += f"\n{has_line}"
			print(f"  + hook has_permission {dt}")

		if f'"{dt}"' not in doc_inner:
			doc_inner += f"\n{doc_entry}"
			print(f"  + hook doc_events {dt}")

	text = (
		text[: pq_block.start(2)]
		+ pq_inner
		+ text[pq_block.end(2) : has_block.start(2)]
		+ has_inner
		+ text[has_block.end(2) : doc_block.start(2)]
		+ doc_inner
		+ text[doc_block.end(2) :]
	)

	if not dry_run:
		HOOKS.write_text(text, encoding="utf-8")


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--phase", default="all", help="dot0-dot6 hoặc all")
	parser.add_argument("--dry-run", action="store_true")
	args = parser.parse_args()

	phases = list(PHASE2_BACKFILL.keys()) if args.phase == "all" else [args.phase]
	doctypes = all_phase2_doctypes(phases)

	print(f"Phase 2 apply campus_id — {len(doctypes)} DocType(s)")
	for dt in doctypes:
		apply_schema(dt, dry_run=args.dry_run)
		ensure_pq_wrapper(dt, dry_run=args.dry_run)

	update_hooks(doctypes, dry_run=args.dry_run)
	print("Done.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
