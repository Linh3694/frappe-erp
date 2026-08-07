"""
GĐ 0.2 — Gán role campus cho các tài khoản đang thiếu, và set `default_campus`
tường minh cho tài khoản đa campus.

Vì sao cần
----------
Khi bật `campus_pq_enabled_doctypes`, user KHÔNG có role campus nào sẽ nhận
`get_campus_filter() -> {"campus_id": ""}` → điều kiện SQL `campus_id = ''` → **không
khớp dòng nào**; đồng thời `has_campus_permission` trả False → PermissionError.
Đo trên prod 2026-08-07: 350 tài khoản đang bật thiếu role campus (317 `@parent`, 33 nội bộ).

Riêng tài khoản có 2+ role campus mà preference rỗng thì `inject_campus_id` rơi xuống
`campus_roles[0]` — thứ tự role trong `frappe.get_roles()` KHÔNG có ORDER BY và xáo lại
mỗi khi document User được lưu → dữ liệu họ tạo rơi vào campus ngẫu nhiên. Đây đúng là
cơ chế đã gây ra 76.201 dòng sai campus (xem PHAN-TICH-268-GUARDIAN-CAMPUS-00002.md).

Vì sao KHÔNG dùng `doc.save()` trên User
----------------------------------------
`hooks.py` gắn `on_update` cho User:
  - `erp.common.user_hooks.trigger_user_webhooks` — bắn **vô điều kiện**, mỗi user một
    background job POST ra `user_webhook_endpoints`. 320 user = 320 job + 320 HTTP ra ngoài.
  - `erp.api.faceid.person_hooks.on_user_changed` — cái này an toàn, tự thoát sớm nếu
    `enabled` không đổi.
Ngoài ra `doc.save()` sinh bản ghi `tabVersion` (bảng đã 3,19 GB).

Nên script chèn thẳng dòng con `tabHas Role` rồi `frappe.clear_cache(user=...)` để
`frappe.get_roles()` đọc lại. Không đụng tới document User.

Vì sao KHÔNG dùng `assign_campus_role_to_user`
----------------------------------------------
Hàm đó còn tạo `User Permission` cho 24 doctype. 1.272 phụ huynh hiện có role campus mà
KHÔNG có các bản ghi đó và vẫn hoạt động bình thường → giữ cho đồng nhất, chỉ gán role.

Cách chạy
---------
    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.assign_missing_campus_roles.run

    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.assign_missing_campus_roles.run --kwargs "{'dry_run': False}"

    # Đảo ngược (chỉ gỡ đúng những role script này đã gán):
    bench --site prod.sis.wellspring.edu.vn execute \
        erp.scripts.assign_missing_campus_roles.rollback --kwargs "{'dry_run': False}"
"""

from __future__ import annotations

import frappe

CAMPUS_ROLE = "Campus Wellspring 95 Ai Mo"  # role của CAMPUS-00001
CAMPUS_ID = "CAMPUS-00001"

# Tài khoản đa campus cần default_campus tường minh.
# @wssg = Wellspring Sài Gòn → mặc định CAMPUS-00003 (Wellspring Sài Gòn).
MULTI_CAMPUS_DEFAULTS = {
	"danthanh@wssg.edu.vn": "CAMPUS-00003",
	"ngocthao@wssg.edu.vn": "CAMPUS-00003",
	"trang@wssg.edu.vn": "CAMPUS-00003",
}

# Dấu vết để rollback biết dòng nào do script này tạo
MARKER = "assign_missing_campus_roles"


def _as_bool(v) -> bool:
	if isinstance(v, str):
		return v.strip().lower() not in ("false", "0", "no", "")
	return bool(v)


def _targets():
	"""User đang bật, không phải Guest/Administrator, chưa có role campus nào."""
	return frappe.db.sql(
		"""
		SELECT u.name, u.user_type, u.full_name, u.last_active
		FROM `tabUser` u
		WHERE u.enabled = 1
		  AND u.name NOT IN ('Guest','Administrator')
		  AND NOT EXISTS (
		        SELECT 1 FROM `tabHas Role` h
		        WHERE h.parent = u.name AND h.role LIKE 'Campus %'
		      )
		ORDER BY u.name
		""",
		as_dict=True,
	)


def _classify(name: str) -> str:
	if "@parent." in name:
		return "phu huynh"
	low = name.lower()
	if low.startswith("workphone") or low.startswith("tablet") or low.startswith("ws1"):
		return "thiet bi"
	return "noi bo"


def run(dry_run: bool = True, include_devices: bool = True):
	dry_run = _as_bool(dry_run)
	include_devices = _as_bool(include_devices)
	print("=== %s ===" % ("XEM TRUOC (dry run)" if dry_run else "THUC HIEN"))
	print()

	if not frappe.db.exists("Role", CAMPUS_ROLE):
		print("! DUNG: role %r khong ton tai" % CAMPUS_ROLE)
		return

	rows = _targets()
	groups = {}
	for r in rows:
		groups.setdefault(_classify(r["name"]), []).append(r)

	print("### 1. Tai khoan dang bat, THIEU role campus")
	print("   %-14s %6s" % ("NHOM", "SO LUONG"))
	for g in sorted(groups, key=lambda k: -len(groups[k])):
		print("   %-14s %6d" % (g, len(groups[g])))
	print("   %-14s %6d" % ("TONG", len(rows)))

	devices = groups.get("thiet bi", [])
	if devices:
		print()
		print("   Tai khoan thiet bi (%d) — chua tung dang nhap thi nen VO HIEU HOA thay vi gan role." % len(devices))
		print("   Script van gan role (lua chon dao nguoc duoc); IT xac nhan roi disable sau:")
		for r in devices[:8]:
			print("     %-45s last_active=%s" % (r["name"], r["last_active"]))
		if len(devices) > 8:
			print("     ... con %d tai khoan" % (len(devices) - 8))

	internal = groups.get("noi bo", [])
	if internal:
		print()
		print("   Tai khoan noi bo (%d) — kiem tra xem con lam viec khong:" % len(internal))
		for r in sorted(internal, key=lambda x: (x["last_active"] is None, x["last_active"]), reverse=True)[:10]:
			print("     %-45s %-22s last_active=%s" % (r["name"], (r["full_name"] or "")[:20], r["last_active"]))

	targets = rows if include_devices else [r for r in rows if _classify(r["name"]) != "thiet bi"]

	print()
	print("### 2. Preference cho tai khoan da campus")
	pref_todo = []
	for user, campus in MULTI_CAMPUS_DEFAULTS.items():
		if not frappe.db.exists("User", user):
			print("   %-45s (khong ton tai, bo qua)" % user)
			continue
		cur = frappe.db.get_value(
			"SIS User Campus Preference", {"user": user}, ["name", "current_campus", "default_campus"], as_dict=True
		)
		if not cur:
			print("   %-45s (chua co ban ghi preference, bo qua)" % user)
			continue
		if cur["current_campus"] and cur["default_campus"]:
			print("   %-45s da co: current=%s default=%s" % (user, cur["current_campus"], cur["default_campus"]))
			continue
		if not frappe.db.exists("SIS Campus", campus):
			print("   %-45s ! campus dich %s khong ton tai" % (user, campus))
			continue
		pref_todo.append((cur["name"], user, campus))
		print("   %-45s -> se set current=default=%s" % (user, campus))

	if dry_run:
		print()
		print("### 3. (dry run) Se thuc hien")
		print("   - Gan role %r cho %d tai khoan" % (CAMPUS_ROLE, len(targets)))
		print("   - Set default/current campus cho %d ban ghi preference" % len(pref_todo))
		print()
		print("   Chay lai voi --kwargs \"{'dry_run': False}\" de thuc hien that.")
		print("   Bo qua tai khoan thiet bi: --kwargs \"{'dry_run': False, 'include_devices': False}\"")
		return

	print()
	print("### 3. Gan role")
	done = 0
	for r in targets:
		# Chen thang dong con: KHONG save document User de tranh on_update ->
		# trigger_user_webhooks (ban vo dieu kien) va tranh sinh ban ghi tabVersion.
		frappe.db.sql(
			"""
			INSERT INTO `tabHas Role`
			  (name, creation, modified, owner, modified_by, docstatus, idx,
			   parent, parentfield, parenttype, role)
			VALUES
			  (%(name)s, NOW(), NOW(), %(owner)s, %(owner)s, 0,
			   (SELECT COALESCE(MAX(x.idx),0)+1 FROM `tabHas Role` x WHERE x.parent=%(parent)s),
			   %(parent)s, 'roles', 'User', %(role)s)
			""",
			{
				"name": frappe.generate_hash(length=10),
				"owner": MARKER,
				"parent": r["name"],
				"role": CAMPUS_ROLE,
			},
		)
		frappe.clear_cache(user=r["name"])
		done += 1
		if done % 50 == 0:
			frappe.db.commit()
			print("   ... %d/%d" % (done, len(targets)))
	frappe.db.commit()
	print("   Da gan role cho %d tai khoan" % done)

	print()
	print("### 4. Set preference cho tai khoan da campus")
	for pname, user, campus in pref_todo:
		frappe.db.set_value(
			"SIS User Campus Preference", pname, {"current_campus": campus, "default_campus": campus}
		)
		print("   OK %-45s -> %s" % (user, campus))
	frappe.db.commit()

	_verify()


def _verify():
	print()
	print("### 5. Nghiem thu")
	left = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabUser` u
		WHERE u.enabled=1 AND u.name NOT IN ('Guest','Administrator')
		  AND NOT EXISTS (SELECT 1 FROM `tabHas Role` h
		                  WHERE h.parent=u.name AND h.role LIKE 'Campus %')
		"""
	)[0][0]
	print("   Tai khoan dang bat con THIEU role campus:", left, "(ky vong 0, hoac chi con thiet bi neu bo qua)")

	print("   Phan bo role campus:")
	for r in frappe.db.sql(
		"""SELECT h.role, COUNT(DISTINCT h.parent) n FROM `tabHas Role` h
		   WHERE h.role LIKE 'Campus %' GROUP BY h.role ORDER BY n DESC""",
		as_dict=True,
	):
		print("     %-40s %d user" % (r["role"], r["n"]))

	print("   User da campus va preference cua ho:")
	for r in frappe.db.sql(
		"""SELECT h.parent u, COUNT(*) n FROM `tabHas Role` h
		   WHERE h.role LIKE 'Campus %' GROUP BY h.parent HAVING n>1""",
		as_dict=True,
	):
		pref = frappe.db.get_value(
			"SIS User Campus Preference", {"user": r["u"]}, ["current_campus", "default_campus"], as_dict=True
		)
		print(
			"     %-45s %d role | current=%s default=%s"
			% (r["u"], r["n"], (pref or {}).get("current_campus"), (pref or {}).get("default_campus"))
		)

	print()
	print("   Luu y: da goi frappe.clear_cache() cho tung user. Neu co worker dang chay,")
	print("   can nhac `bench --site <site> clear-cache` de chac chan moi tien trinh doc lai role.")


def rollback(dry_run: bool = True):
	"""Gỡ đúng những dòng Has Role do script này tạo (owner = MARKER)."""
	dry_run = _as_bool(dry_run)
	rows = frappe.db.sql(
		"SELECT name, parent FROM `tabHas Role` WHERE owner=%s AND role=%s", (MARKER, CAMPUS_ROLE), as_dict=True
	)
	print("So dong Has Role do script tao:", len(rows))
	if dry_run:
		print("(dry run) Chay lai voi --kwargs \"{'dry_run': False}\" de go that.")
		return
	for r in rows:
		frappe.db.sql("DELETE FROM `tabHas Role` WHERE name=%s", (r["name"],))
		frappe.clear_cache(user=r["parent"])
	frappe.db.commit()
	print("Da go", len(rows), "dong.")
	print("Luu y: preference da set o buoc 4 KHONG bi dao nguoc — sua tay neu can.")
