#!/usr/bin/env python3
# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt
"""Sinh tài liệu bàn giao từ registry (GD1-11 · PLAN-02 §11.4).

Sinh ra:
  · deploy/config/site_config.example.json   — template placeholder cho provision.sh
  · deploy/config/CONFIG-REFERENCE.md        — bảng tra cứu cho DevOps (GD4-06)

Chạy lại mỗi khi sửa config_spec.py:
    python3 erp/setup/gen_config_docs.py

Không cần frappe. KHÔNG BAO GIỜ đọc giá trị thật — chỉ sinh placeholder.
"""

from __future__ import annotations

import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)                    # …/erp/erp
REPO = os.path.dirname(APP)                    # …/apps/erp
OUT_DIR = os.path.join(REPO, "deploy", "config")

sys.path.insert(0, APP)

# import config_spec mà không kéo theo frappe
import importlib.util

spec = importlib.util.spec_from_file_location("config_spec", os.path.join(HERE, "config_spec.py"))
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

SCOPE_LABEL = {
	cs.WELLSPRING_ONLY: "Wellspring",
	cs.PER_TENANT: "Mỗi tenant",
	cs.OPTIONAL: "Tuỳ chọn",
	cs.DEMO_ONLY: "Chỉ demo",
}


def placeholder(key: str) -> str:
	return "__" + key.upper() + "__"


def gen_example_json() -> str:
	"""Chỉ gồm key mà TENANT MỚI cần đặt — không đổ cả registry vào."""
	out: dict[str, object] = {}
	for k in cs.SITE_CONFIG_SPEC:
		if k.legacy or k.tenant_scope in (cs.WELLSPRING_ONLY, cs.DEMO_ONLY):
			continue
		out[k.key] = placeholder(k.key)
	path = os.path.join(OUT_DIR, "site_config.example.json")
	body = json.dumps(out, indent=1, ensure_ascii=False)
	with open(path, "w", encoding="utf-8") as fh:
		fh.write(body + "\n")
	return f"{path}  ({len(out)} key)"


def _md_cell(text: str) -> str:
	"""Escape ký tự | — nếu không sẽ vỡ bảng markdown."""
	return (text or "").replace("|", "\\|")


def _rows(items):
	for k in items:
		yield (
			f"| `{k.key}` | {'✅' if k.required else '—'} | {'🔒' if k.secret else '—'} | "
			f"{SCOPE_LABEL.get(k.tenant_scope, k.tenant_scope)} | {_md_cell(k.note)} |"
		)


def gen_reference_md() -> str:
	groups = [
		("Nhóm B — Tích hợp microservice", cs.WELLSPRING_ONLY, False),
		("Nhóm C — Nghiệp vụ app erp", cs.PER_TENANT, False),
		("Nhóm D — White-label", None, False),
		("Nhóm E — Legacy (service đã gỡ, code còn tham chiếu)", None, True),
	]
	white_label = {"seed_profile", "demo_fixed_otp", "vivas_sms_url", "vivas_sms_username",
	               "vivas_sms_password", "vivas_sms_brandname", "vivas_sms_enabled"}

	lines = [
		"# CONFIG-REFERENCE — key cấu hình hạ tầng",
		"",
		"> **File này được SINH TỰ ĐỘNG** từ `erp/setup/config_spec.py`.",
		"> Đừng sửa tay — sửa registry rồi chạy `python3 erp/setup/gen_config_docs.py`.",
		"",
		"> Không chứa giá trị thật. Giá trị sống trong `sites/<site>/site_config.json`",
		"> trên máy chủ từng khách, không bao giờ vào git.",
		"",
		"## Cách đọc bảng",
		"",
		"| Cột | Ý nghĩa |",
		"|---|---|",
		"| **Bắt buộc** | ✅ = site mới thiếu key này thì `check_site_config --mode enforce` chặn |",
		"| **Bí mật** | 🔒 = không bao giờ in giá trị ra log/console/chat |",
		"| **Phạm vi** | ai phải đặt: Wellspring / Mỗi tenant / Tuỳ chọn / Chỉ demo |",
		"",
		"## Kiểm tra một site",
		"",
		"```bash",
		"bench --site <site> execute erp.setup.provision.check_site_config",
		"```",
		"",
		"Lệnh này chỉ in **tên key** và trạng thái có/thiếu — không in giá trị.",
		"Dùng nó thay cho `cat site_config.json`, đã có tiền lệ lộ secret qua kênh chat",
		"(`PLAN-01 §2.3`).",
		"",
		"---",
		"",
		"## Nhóm A — Frappe chuẩn",
		"",
		"bench tự sinh, framework tự đọc. App không quản; liệt kê để người vận hành biết:",
		"",
		"```",
	]
	lines += ["  " + ", ".join(sorted(cs.FRAPPE_STANDARD_KEYS))]
	lines += [
		"```",
		"",
		"> ⚠️ **`encryption_key` KHÔNG được xoay.** Frappe dùng nó giải mã password đã lưu",
		"> trong DB; xoay sai là mất toàn bộ credential đã mã hoá. Tenant mới: bench tự sinh.",
		"",
	]

	header = ["", "| Key | Bắt buộc | Bí mật | Phạm vi | Ghi chú |", "|---|:--:|:--:|---|---|"]

	for title, scope, legacy in groups:
		if legacy:
			items = [k for k in cs.SITE_CONFIG_SPEC if k.legacy]
		elif title.startswith("Nhóm D"):
			items = [k for k in cs.SITE_CONFIG_SPEC if k.key in white_label and not k.legacy]
		else:
			items = [k for k in cs.SITE_CONFIG_SPEC
			         if k.tenant_scope == scope and not k.legacy and k.key not in white_label]
		if not items:
			continue
		lines += ["---", "", f"## {title}", *header]
		lines += list(_rows(items))
		lines += [""]

	lines += ["---", "", "## Nguồn cấu hình NGOÀI `site_config.json`", ""]
	for src in cs.EXTERNAL_CONFIG_SOURCES:
		lines += [
			f"### `{src['path']}`", "",
			f"Đọc bởi `{src['reader']}`", "",
			"Key: " + ", ".join(f"`{k}`" for k in src["keys"]), "",
			src["note"], "",
		]

	lines += [
		"---", "",
		f"*Sinh từ {len(cs.SITE_CONFIG_SPEC)} key trong registry "
		f"({len([k for k in cs.SITE_CONFIG_SPEC if k.secret])} bí mật, "
		f"{len([k for k in cs.SITE_CONFIG_SPEC if k.legacy])} legacy).*",
		"",
	]

	path = os.path.join(OUT_DIR, "CONFIG-REFERENCE.md")
	with open(path, "w", encoding="utf-8") as fh:
		fh.write("\n".join(lines))
	return f"{path}  ({len(cs.SITE_CONFIG_SPEC)} key)"


if __name__ == "__main__":
	os.makedirs(OUT_DIR, exist_ok=True)
	print("✓", gen_example_json())
	print("✓", gen_reference_md())
