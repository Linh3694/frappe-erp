#!/usr/bin/env python3
"""
Sinh wrapper permission_query + hooks entry cho danh sách DocType.

Chạy: cd apps/erp && python3 erp/scripts/generate_campus_pq_wrappers.py --phase dot1
"""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

from erp.scripts._campus_paths import resolve_erp_paths

APP_ROOT, _ERP = resolve_erp_paths(__file__)

from erp.utils.campus_phase2_config import all_phase2_doctypes  # noqa: E402


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("doctypes", nargs="*", help="Tên DocType")
	parser.add_argument("--phase", help="dot0-dot6")
	args = parser.parse_args()

	if args.phase:
		doctypes = all_phase2_doctypes([args.phase])
	elif args.doctypes:
		doctypes = args.doctypes
	else:
		doctypes = all_phase2_doctypes()

	apply = runpy.run_path(str(Path(__file__).parent / "phase2_apply_campus_id.py"))
	for dt in doctypes:
		apply["ensure_pq_wrapper"](dt)
	apply["update_hooks"](doctypes)
	print(f"Done — {len(doctypes)} DocType.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
