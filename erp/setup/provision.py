# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt
"""Tiện ích kiểm tra cấu hình site khi triển khai (GD1-11 · PLAN-02 §11.3).

Chạy:
    bench --site <site> execute erp.setup.provision.check_site_config
    bench --site <site> execute erp.setup.provision.check_site_config \\
          --kwargs "{'mode': 'warn'}"

`mode`:
  · "warn"    — chỉ liệt kê, luôn thoát 0. Dùng trên prod để đối chiếu.
  · "enforce" — thiếu key bắt buộc thì raise. Dùng trong provision.sh (GD4-01)
                và upgrade-all.sh sau migrate.

CAM KẾT: hàm này **không bao giờ in giá trị** của bất kỳ key nào được đánh dấu
secret — chỉ in tên key và trạng thái có/thiếu. Đây là lý do nó tồn tại: đã có
tiền lệ dán nguyên site_config kèm giá trị ra kênh chat (PLAN-01 §2.3).
"""

import frappe

from erp.setup.config_spec import (
	DEMO_ONLY,
	FRAPPE_STANDARD_KEYS,
	PER_TENANT,
	SITE_CONFIG_SPEC,
	SPEC_BY_KEY,
	WELLSPRING_ONLY,
	EXTERNAL_CONFIG_SOURCES,
)


def _present(conf: dict, key: str) -> bool:
	value = conf.get(key)
	if value is None:
		return False
	if isinstance(value, str) and not value.strip():
		return False
	return True


def check_site_config(mode: str = "warn", tenant_scope: str | None = None) -> dict:
	"""Đối chiếu site_config hiện tại với registry.

	tenant_scope: lọc theo phạm vi khi enforce cho tenant mới
	              ("per-tenant" bỏ qua các key wellspring-only).
	"""
	conf = dict(frappe.conf or {})
	site = frappe.local.site if hasattr(frappe.local, "site") else "?"

	missing_required, present, missing_optional = [], [], []
	legacy_present, demo_leak = [], []

	for spec in SITE_CONFIG_SPEC:
		if tenant_scope and spec.tenant_scope == WELLSPRING_ONLY:
			continue
		has = _present(conf, spec.key)
		if spec.legacy:
			if has:
				legacy_present.append(spec.key)
			continue
		if spec.tenant_scope == DEMO_ONLY and has:
			demo_leak.append(spec.key)
			continue
		if has:
			present.append(spec.key)
		elif spec.required:
			missing_required.append(spec.key)
		else:
			missing_optional.append(spec.key)

	# Key có trong site nhưng chưa khai trong registry
	undeclared = sorted(
		k for k in conf
		if k not in SPEC_BY_KEY and k not in FRAPPE_STANDARD_KEYS and not k.startswith("_")
	)

	print(f"\n═══ check_site_config · site={site} · mode={mode}")
	print(f"   Đã có       : {len(present)} key")
	print(f"   Thiếu (tuỳ) : {len(missing_optional)} key")

	if missing_required:
		print(f"\n   🔴 THIẾU KEY BẮT BUỘC ({len(missing_required)}):")
		for k in missing_required:
			print(f"        {k}  — {SPEC_BY_KEY[k].note or '(không có ghi chú)'}")

	if demo_leak:
		print(f"\n   🔴 KEY CHỈ DÀNH CHO SITE DEMO nhưng có mặt ở đây ({len(demo_leak)}):")
		for k in demo_leak:
			print(f"        {k}  — CẤM trên site khách/prod")

	if conf.get("seed_profile") and tenant_scope == PER_TENANT:
		print("\n   🔴 seed_profile có mặt trên site tenant — patch seed sẽ ghi giá trị "
		      "Wellspring vào site này (PLAN-02 §4.1)")

	if legacy_present:
		print(f"\n   ℹ️  Key legacy còn sót ({len(legacy_present)}) — service đã gỡ, code còn "
		      f"tham chiếu. Wellspring giữ nguyên, tenant mới không set:")
		print(f"        {', '.join(legacy_present)}")

	if undeclared:
		print(f"\n   ⚠️  Key có trong site nhưng CHƯA KHAI trong config_spec.py ({len(undeclared)}):")
		for k in undeclared:
			print(f"        {k}")
		print("        → bổ sung vào SITE_CONFIG_SPEC rồi chạy lại")

	print("\n   Nguồn cấu hình ngoài site_config (provision phải xử lý riêng):")
	for src in EXTERNAL_CONFIG_SOURCES:
		print(f"        {src['path']}  ← {src['reader']}")

	result = {
		"site": site,
		"mode": mode,
		"present": present,
		"missing_required": missing_required,
		"missing_optional": missing_optional,
		"legacy_present": legacy_present,
		"undeclared": undeclared,
		"demo_leak": demo_leak,
	}

	if mode == "enforce" and (missing_required or demo_leak):
		problems = []
		if missing_required:
			problems.append(f"thiếu {len(missing_required)} key bắt buộc")
		if demo_leak:
			problems.append(f"{len(demo_leak)} key demo-only lọt vào site này")
		raise frappe.ValidationError(
			f"check_site_config thất bại: {', '.join(problems)}. Xem log ở trên."
		)

	print("\n   ✓ Không có lỗi chặn\n" if not missing_required else "")
	return result
