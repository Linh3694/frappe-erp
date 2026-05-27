"""
Resolve đường dẫn erp — script nằm trong ``erp/scripts/``.
"""

from __future__ import annotations

from pathlib import Path


def resolve_erp_paths(script_file: str | Path) -> tuple[Path, Path]:
	"""
	Trả về (app_root, erp_package_dir).

	Layout: ``apps/erp/erp/scripts/*.py`` → app_root=``apps/erp``, erp=``apps/erp/erp``
	"""
	erp_pkg = Path(script_file).resolve().parent.parent
	hooks = erp_pkg / "hooks.py"
	if not hooks.is_file():
		raise FileNotFoundError(
			f"Không tìm thấy hooks.py tại {hooks}. "
			"Script campus phải nằm trong apps/erp/erp/scripts/."
		)
	return erp_pkg.parent, erp_pkg
