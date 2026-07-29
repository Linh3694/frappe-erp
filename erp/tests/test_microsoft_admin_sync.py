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
		frappe_stub = MagicMock()
		frappe_stub.whitelist.side_effect = lambda *args, **kwargs: lambda fn: fn
		sys.modules["frappe"] = frappe_stub
	for stub in (
		"frappe.model",
		"frappe.model.rename_doc",
		"erp.utils",
		"erp.utils.api_response",
		"erp.api.utils",
	):
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


class TestFetchMicrosoftUserPayload(unittest.TestCase):
	@patch("erp.api.erp_common_user.microsoft_auth.requests.get")
	def test_falls_back_to_filter_on_404(self, mock_get):
		from erp.api.erp_common_user.microsoft_auth import _fetch_microsoft_user_payload

		not_found = MagicMock(status_code=404, text='{"error":{"code":"Request_ResourceNotFound"}}')
		ok = MagicMock(status_code=200)
		ok.json.return_value = {
			"value": [{
				"id": "abc",
				"mail": "robert.turner@wellspring.edu.vn",
				"userPrincipalName": "robert.turner@wellspring.edu.vn",
			}]
		}
		mock_get.side_effect = [not_found, ok]

		payload = _fetch_microsoft_user_payload("robert.tuner@wellspring.edu.vn", {"Authorization": "Bearer x"})
		self.assertEqual(payload["id"], "abc")
		self.assertEqual(mock_get.call_count, 2)

	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	@patch("erp.api.erp_common_user.microsoft_auth.requests.get")
	def test_does_not_fallback_on_non_404_errors(self, mock_get, mock_frappe):
		from erp.api.erp_common_user.microsoft_auth import _fetch_microsoft_user_payload

		def _raise_on_throw(msg, *args, **kwargs):
			raise Exception(str(msg))

		mock_frappe.throw.side_effect = _raise_on_throw

		for status_code in (401, 500):
			with self.subTest(status_code=status_code):
				mock_get.reset_mock()
				mock_frappe.throw.reset_mock()
				mock_get.return_value = MagicMock(
					status_code=status_code,
					text=f'{{"error":{{"code":"Err{status_code}"}}}}',
				)

				with self.assertRaises(Exception):
					_fetch_microsoft_user_payload("user@wellspring.edu.vn", {"Authorization": "Bearer x"})

				mock_get.assert_called_once()
				mock_frappe.throw.assert_called_once()


class TestSyncJobCache(unittest.TestCase):
	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	def test_write_and_read_job(self, mock_frappe):
		from erp.api.erp_common_user import microsoft_auth as m

		store = {}
		cache = MagicMock()
		cache.set_value.side_effect = lambda k, v, expires_in_sec=None: store.__setitem__(k, v)
		cache.get_value.side_effect = lambda k: store.get(k)
		mock_frappe.cache.return_value = cache

		payload = {
			"job_id": "job1",
			"status": "queued",
			"processed": 0,
			"created": 0,
			"updated": 0,
			"errors": 0,
			"message": "",
			"started_by": "it@x.com",
		}
		m._write_sync_job("job1", payload)
		self.assertEqual(m._read_sync_job("job1")["status"], "queued")


class TestStartMicrosoftGroupSync(unittest.TestCase):
	@patch("erp.api.erp_common_user.microsoft_auth.success_response")
	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	def test_second_start_returns_active_job_without_enqueue(self, mock_frappe, mock_success):
		from erp.api.erp_common_user import microsoft_auth as m

		existing = {
			"job_id": "active-job",
			"status": "running",
			"processed": 3,
		}
		cache = MagicMock()
		cache.make_key.return_value = b"site|ms_admin_sync_job:active"
		cache.set.return_value = False
		cache.get_value.side_effect = lambda key: (
			"active-job"
			if key == m.MS_ADMIN_SYNC_ACTIVE_KEY
			else existing
		)
		mock_frappe.cache.return_value = cache
		mock_frappe.session.user = "it@wellspring.edu.vn"
		mock_frappe.get_roles.return_value = ["SIS IT"]
		mock_frappe.PermissionError = PermissionError
		mock_success.side_effect = lambda data=None, message=None, **kwargs: {
			"data": data,
			"message": message,
		}

		result = m.admin_start_microsoft_group_sync()

		self.assertEqual(result["data"], existing)
		cache.set.assert_called_once()
		self.assertTrue(cache.set.call_args.kwargs["nx"])
		self.assertEqual(
			cache.set.call_args.kwargs["ex"],
			m.MS_ADMIN_SYNC_JOB_TTL,
		)
		mock_frappe.enqueue.assert_not_called()

	@patch("erp.api.erp_common_user.microsoft_auth.error_response")
	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	def test_enqueue_exception_clears_active_lock_and_marks_job_failed(
		self,
		mock_frappe,
		mock_error,
	):
		from erp.api.erp_common_user import microsoft_auth as m

		cache = MagicMock()
		cache.make_key.return_value = b"site|ms_admin_sync_job:active"
		cache.set.return_value = True
		mock_frappe.cache.return_value = cache
		mock_frappe.session.user = "it@wellspring.edu.vn"
		mock_frappe.get_roles.return_value = ["SIS IT"]
		mock_frappe.PermissionError = PermissionError
		mock_frappe.enqueue.side_effect = RuntimeError("Redis queue unavailable")
		mock_error.side_effect = lambda message, **kwargs: {
			"message": message,
			**kwargs,
		}

		result = m.admin_start_microsoft_group_sync()

		self.assertIn("Redis queue unavailable", result["message"])
		cache.delete_value.assert_called_once_with(m.MS_ADMIN_SYNC_ACTIVE_KEY)
		failed_payload = cache.set_value.call_args_list[-1].args[1]
		self.assertEqual(failed_payload["status"], "failed")
		self.assertIn("Redis queue unavailable", failed_payload["message"])


class TestAdminRenameUserEmail(unittest.TestCase):
	"""Case IT sửa email trên MS: rename User local, nhưng phải an toàn."""

	def _mock_error(self, mock_error):
		mock_error.side_effect = lambda message, **kwargs: {"message": message, **kwargs}

	def _as_it_admin(self, mock_frappe):
		mock_frappe.session.user = "it@wellspring.edu.vn"
		mock_frappe.get_roles.return_value = ["SIS IT"]
		mock_frappe.PermissionError = PermissionError
		mock_frappe.form_dict = {}

	@patch("frappe.model.rename_doc.rename_doc")
	@patch("erp.api.erp_common_user.microsoft_auth.error_response")
	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	def test_blocks_when_new_email_already_exists(self, mock_frappe, mock_error, mock_rename):
		from erp.api.erp_common_user import microsoft_auth as m

		self._as_it_admin(mock_frappe)
		self._mock_error(mock_error)
		mock_frappe.db.exists.return_value = True

		result = m.admin_rename_user_email("old@x.vn", "new@x.vn")

		self.assertIn("đã tồn tại", result["message"])
		mock_rename.assert_not_called()

	@patch("frappe.model.rename_doc.rename_doc")
	@patch("erp.api.erp_common_user.microsoft_auth._fetch_microsoft_user_payload")
	@patch("erp.api.erp_common_user.microsoft_auth.get_microsoft_app_token")
	@patch("erp.api.erp_common_user.microsoft_auth.error_response")
	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	def test_blocks_when_new_email_belongs_to_other_ms_account(
		self,
		mock_frappe,
		mock_error,
		mock_token,
		mock_fetch,
		mock_rename,
	):
		from erp.api.erp_common_user import microsoft_auth as m

		self._as_it_admin(mock_frappe)
		self._mock_error(mock_error)
		mock_frappe.db.exists.side_effect = lambda _dt, name: name == "old@x.vn"
		local_user = MagicMock()
		local_user.microsoft_id = "ms-1"
		mock_frappe.get_doc.return_value = local_user
		mock_token.return_value = "token"
		mock_fetch.return_value = {"id": "ms-2"}

		result = m.admin_rename_user_email("old@x.vn", "new@x.vn")

		self.assertIn("tài khoản Microsoft khác", result["message"])
		mock_rename.assert_not_called()

	@patch("frappe.model.rename_doc.rename_doc")
	@patch("erp.api.erp_common_user.microsoft_auth._fetch_microsoft_user_payload")
	@patch("erp.api.erp_common_user.microsoft_auth.get_microsoft_app_token")
	@patch("erp.api.erp_common_user.microsoft_auth.success_response")
	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	def test_renames_and_updates_mapping_when_same_ms_identity(
		self,
		mock_frappe,
		mock_success,
		mock_token,
		mock_fetch,
		mock_rename,
	):
		from erp.api.erp_common_user import microsoft_auth as m

		self._as_it_admin(mock_frappe)
		mock_success.side_effect = lambda data=None, message=None, **kwargs: {
			"data": data,
			"message": message,
		}
		mock_frappe.db.exists.side_effect = lambda _dt, name: name == "old@x.vn"
		local_user = MagicMock()
		local_user.microsoft_id = "ms-1"
		renamed = MagicMock()
		renamed.email = "old@x.vn"
		mock_frappe.get_doc.side_effect = [local_user, renamed]
		mock_frappe.db.get_value.return_value = "MSU-001"
		mock_token.return_value = "token"
		mock_fetch.return_value = {"id": "ms-1"}

		result = m.admin_rename_user_email("old@x.vn", "new@x.vn")

		mock_rename.assert_called_once_with(
			doctype="User",
			old="old@x.vn",
			new="new@x.vn",
			ignore_permissions=True,
			show_alert=False,
		)
		self.assertEqual(renamed.email, "new@x.vn")
		mock_frappe.db.set_value.assert_called_once_with(
			"ERP Microsoft User", "MSU-001", "mapped_user_id", "new@x.vn"
		)
		self.assertEqual(result["data"]["email"], "new@x.vn")

	@patch("frappe.model.rename_doc.rename_doc")
	@patch("erp.api.erp_common_user.microsoft_auth.error_response")
	@patch("erp.api.erp_common_user.microsoft_auth.frappe")
	def test_rejects_same_email(self, mock_frappe, mock_error, mock_rename):
		from erp.api.erp_common_user import microsoft_auth as m

		self._as_it_admin(mock_frappe)
		self._mock_error(mock_error)

		result = m.admin_rename_user_email("a@x.vn", "A@x.vn")

		self.assertIn("trùng email hiện tại", result["message"])
		mock_rename.assert_not_called()


if __name__ == "__main__":
	unittest.main()
