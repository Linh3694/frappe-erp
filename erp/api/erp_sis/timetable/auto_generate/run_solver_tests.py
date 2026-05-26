#!/usr/bin/env python3
"""Chạy test solver core offline — không cần bench/frappe/pytest path hack."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parents[4]
_py = f"{sys.version_info.major}{sys.version_info.minor}"
for _name in (f".test_deps_py{_py}", ".test_deps_py314", ".test_deps_py311", ".test_deps"):
	_candidate = BACKEND / _name
	if _candidate.exists():
		sys.path.insert(0, str(_candidate))
		break
sys.path.insert(0, str(ROOT))


def _run_module(module_name: str) -> tuple[int, int]:
	from importlib import import_module

	mod = import_module(module_name)
	passed = failed = 0
	for name in sorted(dir(mod)):
		if not name.startswith("test_"):
			continue
		fn = getattr(mod, name)
		try:
			fn()
			print(f"  OK  {module_name}.{name}")
			passed += 1
		except Exception:
			print(f"  FAIL {module_name}.{name}")
			traceback.print_exc()
			failed += 1
	return passed, failed


def main() -> int:
	modules = [
		"core.tests.test_p3_schema",
		"core.tests.test_runner_basic",
	]
	total_p = total_f = 0
	for m in modules:
		print(m)
		p, f = _run_module(m)
		total_p += p
		total_f += f
	print(f"\n{total_p} passed, {total_f} failed")
	return 1 if total_f else 0


if __name__ == "__main__":
	raise SystemExit(main())
