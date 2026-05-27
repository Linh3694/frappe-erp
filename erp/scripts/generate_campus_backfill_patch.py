#!/usr/bin/env python3
"""
Sinh file patch backfill campus_id từ parent field.

Chạy:
  cd apps/erp && python3 erp/scripts/generate_campus_backfill_patch.py --phase dot0
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

from erp.scripts._campus_paths import resolve_erp_paths

APP_ROOT, ERP = resolve_erp_paths(__file__)
PATCHES_DIR = ERP / "patches" / "v1_0"
PATCHES_TXT = ERP / "patches.txt"

from erp.utils.campus_phase2_config import PHASE2_BACKFILL  # noqa: E402


def _slug(name: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def render_patch(doctype: str, link_field: str, parent_doctype: str) -> str:
	return f'''"""
Backfill campus_id cho {doctype} từ {parent_doctype}.{link_field}.
"""

from erp.utils.campus_backfill import apply_fallback, backfill_from_join, report_backfill


def execute():
	report = backfill_from_join(
		"{doctype}",
		"{link_field}",
		"{parent_doctype}",
	)
	apply_fallback("{doctype}")
	return report
'''


def register_patch(module_path: str) -> bool:
	text = PATCHES_TXT.read_text(encoding="utf-8")
	if module_path in text:
		return False
	PATCHES_TXT.write_text(text.rstrip() + f"\n{module_path}\n", encoding="utf-8")
	return True


def write_single(doctype: str, link_field: str, parent_doctype: str) -> Path:
	slug = _slug(doctype)
	filename = f"backfill_{slug}_campus_id.py"
	path = PATCHES_DIR / filename
	path.write_text(render_patch(doctype, link_field, parent_doctype), encoding="utf-8")
	module = f"erp.patches.v1_0.backfill_{slug}_campus_id"
	if register_patch(module):
		print(f"  + patches.txt: {module}")
	print(f"  + {path}")
	return path


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--doctype")
	parser.add_argument("--link-field")
	parser.add_argument("--parent-doctype")
	parser.add_argument("--phase")
	args = parser.parse_args()

	if args.doctype:
		if not args.link_field or not args.parent_doctype:
			print("Cần --link-field và --parent-doctype")
			return 1
		write_single(args.doctype, args.link_field, args.parent_doctype)
		return 0

	phases = [args.phase] if args.phase else list(PHASE2_BACKFILL.keys())
	count = 0
	for phase in phases:
		for dt, kind, kw in PHASE2_BACKFILL.get(phase, []):
			if kind != "join":
				continue
			write_single(dt, kw["link_field"], kw["parent_doctype"])
			count += 1

	print(f"Done — {count} patch (join-only). Dùng backfill_phase2_campus_id.py cho full rollout.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
