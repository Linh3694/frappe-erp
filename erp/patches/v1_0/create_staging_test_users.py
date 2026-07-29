# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe

TEST_USER_COUNT = 10
DEFAULT_PASSWORD = "Wellspring!2026"
EMAIL_TEMPLATE = "test{index:02d}@wellspring.edu.vn"

# Role không được gán trực tiếp cho user (Frappe tự quản lý)
EXCLUDED_ROLES = {"Administrator", "All", "Guest"}


def execute():
	"""Tạo 10 user test (test01 -> test10) với full quyền, dùng cho STAGING.

	Patch chỉ chạy khi site_config.json có cờ:
	    "allow_create_test_users": 1
	Nhờ vậy chạy `bench migrate` trên production sẽ bỏ qua hoàn toàn.

	Bật cờ trên staging:
	    bench --site <site> set-config allow_create_test_users 1
	    bench --site <site> migrate
	    bench --site <site> set-config allow_create_test_users 0
	"""
	if not frappe.conf.get("allow_create_test_users"):
		return

	roles = _all_assignable_roles()
	created, updated = [], []

	for i in range(1, TEST_USER_COUNT + 1):
		username = f"test{i:02d}"
		email = EMAIL_TEMPLATE.format(index=i)

		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
			updated.append(email)
		else:
			user = frappe.new_doc("User")
			user.email = email
			created.append(email)

		user.first_name = f"Test {i:02d}"
		user.username = username
		user.enabled = 1
		user.user_type = "System User"
		user.send_welcome_email = 0
		user.new_password = DEFAULT_PASSWORD
		# Bỏ qua ràng buộc đổi mật khẩu / độ mạnh mật khẩu khi seed
		user.flags.ignore_password_policy = True

		user.set("roles", [])
		for role in roles:
			user.append("roles", {"role": role})

		user.save(ignore_permissions=True)

	frappe.db.commit()
	print(
		f"[create_staging_test_users] Tạo mới {len(created)} user, cập nhật {len(updated)} user, "
		f"gán {len(roles)} role cho mỗi user"
	)


def _all_assignable_roles() -> list[str]:
	names = frappe.get_all(
		"Role",
		filters={"disabled": 0, "is_custom": ("in", [0, 1])},
		pluck="name",
	)
	return [r for r in names if r not in EXCLUDED_ROLES]
