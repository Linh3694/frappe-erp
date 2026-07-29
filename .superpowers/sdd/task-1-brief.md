### Task 1: Role gate + lookup `microsoft_id` trước email

**Files:**
- Modify: `Codebase/Wellspring DX/frappe-backend/apps/erp/erp/api/erp_common_user/microsoft_auth.py` (thêm helper gần đầu file sau imports; sửa `find_or_create_frappe_user` ~693–738)
- Create: `Codebase/Wellspring DX/frappe-backend/apps/erp/erp/tests/test_microsoft_admin_sync.py`

**Interfaces:**
- Consumes: `frappe.get_roles`, `frappe.throw`, `frappe.PermissionError`, `frappe.db.get_value`
- Produces:
  - `ADMIN_SYNC_ROLES = ("System Manager", "SIS IT")`
  - `def _require_it_admin() -> None`
  - `find_or_create_frappe_user` lookup order: `mapped_user_id` → `microsoft_id` → email → UPN → create

- [ ] **Step 1: Write the failing test**

Tạo `erp/tests/test_microsoft_admin_sync.py`:

```python
"""Unit tests cho Microsoft admin sync helpers (mock Frappe)."""

import unittest
from unittest.mock import MagicMock, patch


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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Volumes/CORSAIR/Dinox Technologies/Codebase/Wellspring DX/frappe-backend"
./env/bin/python -m unittest erp.tests.test_microsoft_admin_sync -v
```

Nếu không có `env` local, dùng:

```bash
cd "/Volumes/CORSAIR/Dinox Technologies/Codebase/Wellspring DX/frappe-backend/apps/erp"
python -m unittest erp.tests.test_microsoft_admin_sync -v
```

Expected: FAIL — `_require_it_admin` chưa tồn tại / lookup chưa theo `microsoft_id`.

- [ ] **Step 3: Write minimal implementation**

Trong `microsoft_auth.py` sau imports:

```python
ADMIN_SYNC_ROLES = ("System Manager", "SIS IT")


def _require_it_admin() -> None:
	"""Chỉ SIS IT / System Manager được gọi admin sync từ FE."""
	roles = frappe.get_roles(frappe.session.user)
	if not any(r in roles for r in ADMIN_SYNC_ROLES):
		frappe.throw(
			_("Chỉ System Manager hoặc SIS IT được đồng bộ Microsoft"),
			frappe.PermissionError,
		)
```

Trong `find_or_create_frappe_user`, **sau** bước `mapped_user_id`, **trước** bước email:

```python
		# 1b. Tìm theo microsoft_id (tránh tạo trùng khi email local ≠ UPN MS)
		ms_id = user_data.get("id") or getattr(ms_user, "microsoft_id", None)
		if ms_id:
			existing_by_ms = frappe.db.get_value("User", {"microsoft_id": ms_id})
			if existing_by_ms:
				local_user = frappe.get_doc("User", existing_by_ms)
				update_frappe_user(local_user, ms_user, user_data)
				try:
					if hasattr(ms_user, "mapped_user_id"):
						ms_user.mapped_user_id = local_user.name
						ms_user.flags.ignore_permissions = True
						ms_user.save()
				except Exception:
					pass
				return local_user
```

- [ ] **Step 4: Run test to verify it passes**

Cùng lệnh Step 2. Expected: PASS cho `TestRequireItAdmin` và `TestFindOrCreateMicrosoftId`.

- [ ] **Step 5: Commit (repo erp)**

```bash
cd "/Volumes/CORSAIR/Dinox Technologies/Codebase/Wellspring DX/frappe-backend/apps/erp"
git status
git add erp/api/erp_common_user/microsoft_auth.py erp/tests/test_microsoft_admin_sync.py
git commit -m "$(cat <<'EOF'
fix(ms-sync): ưu tiên microsoft_id khi map User và gate role IT admin

EOF
)"
```

---

