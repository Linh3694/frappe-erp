"""Unit tests cho Microsoft admin sync helpers (mock Frappe)."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load_microsoft_auth_module():
	"""Nạp microsoft_auth trực tiếp — tránh erp.api.__init__ (pandas/Frappe bench)."""
	mod_name = "erp.api.erp_common_user.microsoft_auth"
	if mod_name in sys.modules:
		return sys.modules[mod_name]

	erp_root = Path(__file__).resolve().parents[1]
	pkg_specs = (
		("erp", erp_root, None),
		("erp.api", erp_root / "api", "erp"),
		("erp.api.erp_common_user", erp_root / "api" / "erp_common_user", "erp.api"),
	)
	for name, path, parent in pkg_specs:
		if name in sys.modules:
			continue
		pkg = types.ModuleType(name)
		pkg.__path__ = [str(path)]
		sys.modules[name] = pkg
		if parent:
			setattr(sys.modules[parent], name.rsplit(".", 1)[-1], pkg)

	if "frappe" not in sys.modules:
		sys.modules["frappe"] = MagicMock()
	for stub in ("erp.utils", "erp.utils.api_response", "erp.api.utils"):
		if stub not in sys.modules:
			sys.modules[stub] = MagicMock()

	spec = importlib.util.spec_from_file_location(
		mod_name,
		erp_root / "api" / "erp_common_user" / "microsoft_auth.py",
	)
	mod = importlib.util.module_from_spec(spec)
	sys.modules[mod_name] = mod
	setattr(sys.modules["erp.api.erp_common_user"], "microsoft_auth", mod)
	spec.loader.exec_module(mod)
	return mod


_load_microsoft_auth_module()


class TestRequireItAdmin(unittest.TestCase):
	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	def test_allow_sis_it(self, mock_frappe):
		from erp.api.erp_common_user.microsoft_auth import _require_it_admin

		mock_frappe.session.user = "it@wellspring.edu.vn"
		mock_frappe.get_roles.return_value = ["SIS IT"]
		_require_it_admin()  # không throw

	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	def test_deny_teacher(self, mock_frappe):
		from erp.api.erp_common_user.microsoft_auth import _require_it_admin

		mock_frappe.session.user = "teacher@wellspring.edu.vn"
		mock_frappe.get_roles.return_value = ["SIS Teacher"]
		mock_frappe.PermissionError = PermissionError
		mock_frappe.throw.side_effect = PermissionError("denied")
		with self.assertRaises(PermissionError):
			_require_it_admin()


class TestFindOrCreateMicrosoftId(unittest.TestCase):
	@patch("erp.api.erp_common_user.microsoft_auth.update_frappe_user")
	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	def test_prefers_microsoft_id_over_email(self, mock_frappe, mock_update):
		from erp.api.erp_common_user.microsoft_auth import find_or_create_frappe_user

		ms_user = MagicMock()
		ms_user.mapped_user_id = None
		ms_user.microsoft_id = "82b9f608-1d80-45e5-bd99-c034b037ad7b"

		local = MagicMock()
		local.name = "robert.tuner@wellspring.edu.vn"
		mock_frappe.db.get_value.side_effect = lambda doctype, filters, *a, **k: (
			"robert.tuner@wellspring.edu.vn"
			if isinstance(filters, dict) and filters.get("microsoft_id")
			else None
		)
		mock_frappe.get_doc.return_value = local
		mock_update.return_value = local

		user_data = {
			"id": "82b9f608-1d80-45e5-bd99-c034b037ad7b",
			"mail": "robert.turner@wellspring.edu.vn",
			"userPrincipalName": "robert.turner@wellspring.edu.vn",
		}
		result = find_or_create_frappe_user(ms_user, user_data)
		self.assertIs(result, local)
		mock_frappe.get_doc.assert_called_with("User", "robert.tuner@wellspring.edu.vn")


if __name__ == "__main__":
	unittest.main()
