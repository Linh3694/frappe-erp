# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt
"""Seed cấu hình hệ thống bằng đúng giá trị Wellspring đang chạy.

Mục tiêu: sau khi migrate, người dùng KHÔNG nhận ra bất kỳ thay đổi nào.
Chỉ ghi vào field đang trống → chạy lại an toàn (idempotent).

Nguyên tắc bắt buộc (PLAN-00 §4 nguyên tắc 2): **seed = hiện trạng**.
Field nào chưa xác nhận được giá trị thật thì KHÔNG seed — để trống còn hơn
điền sai, vì điền sai làm người dùng Wellspring thấy giao diện đổi.
Danh sách field đang chờ xác nhận nằm ở cuối file.

Quyết định 03/08/2026 (chủ sản phẩm):
  · Wellspring có 2 campus, School Profile chỉ chứa 1 bộ giá trị → seed campus
    Hà Nội (CAMPUS-00001). Vấn đề đa campus ghi nhận thành nợ, xem
    `white-label-plans/BACKLOG-da-campus.md`.
  · KHÔNG seed ERP Feature Settings — để DocType dùng default của nó, người vận
    hành tự bật/tắt trên hub UI (GD1-09).
"""

import frappe

# Giá trị đã đối chiếu được từ codebase 03/08/2026 (số chỗ tham chiếu trong ngoặc)
SCHOOL_SEED = {
	"school_name_vn": "Wellspring Hà Nội",                        # 19 chỗ
	"school_name_en": "Wellspring Hanoi",                         # 26 chỗ + footer landing
	"short_name": "WIS",                                          # 105 file
	"school_code": "WSHN",                                        # 17 file, <title> parent portal
	"accreditation_note": "WASC",                                 # logo WASC ở footer
	"support_email": "support@wellspring.edu.vn",                 # 4 chỗ
	"it_email": "it@wellspring.edu.vn",                           # 42 chỗ
	"website_url": "https://wellspring.edu.vn",                   # 4 chỗ
	"identity_email_domain": "parent.wellspring.edu.vn",          # 19 chỗ, mẫu <guardian_id>@<domain>
	"hotline": "(+84) 24 7305 8668",                              # FooterSection.tsx:18 (campus HN)
	"address_vn": "Số 95, Phố Ái Mộ, Phường Bồ Đề, Hà Nội",       # FooterSection.tsx:21 (campus HN)
	"default_language": "vi",
	"default_timezone": "Asia/Ho_Chi_Minh",
}

BRANDING_SEED = {
	"color_primary": "#F05023",        # tokens.css
	"color_secondary": "#002855",      # tokens.css
	"color_on_primary": "#FFFFFF",
	"sidebar_style": "light",
	"staff_app_name": "WIS",           # 105 file
	"parent_app_name": "Parent Portal",
	"social_feed_name": "Wislife",     # 63 file
	"ai_assistant_name": "LIAVI",      # 8 file
	"student_nickname": "WISers",      # 13 file
	"seasonal_theme": "default",
}


def _seed_single(doctype: str, values: dict):
	if not frappe.db.exists("DocType", doctype):
		print(f"[seed_system_config] Bỏ qua {doctype} — DocType chưa tồn tại")
		return
	doc = frappe.get_single(doctype)
	changed = []
	for key, value in values.items():
		field = doc.meta.get_field(key)
		if field is None:
			continue
		current = doc.get(key)
		# Check field: 0 là giá trị hợp lệ → chỉ seed khi thực sự chưa set (None)
		is_empty = current is None if field.fieldtype == "Check" else current in (None, "")
		if is_empty:
			doc.set(key, value)
			changed.append(key)
	if changed:
		doc.flags.ignore_permissions = True
		doc.save()
		print(f"[seed_system_config] {doctype}: seed {len(changed)} field → {', '.join(changed)}")
	else:
		print(f"[seed_system_config] {doctype}: đã có dữ liệu, không seed")


def execute():
	# Chốt an toàn: chỉ seed khi site được đánh dấu rõ ràng là site Wellspring (§4.1).
	# Site khách mới KHÔNG có marker này → không seed gì, dùng _defaults.py trung tính.
	#   bench --site <site> set-config seed_profile wellspring
	if (frappe.conf.get("seed_profile") or "") != "wellspring":
		print("[seed_system_config] Bỏ qua — site không có seed_profile=wellspring")
		return

	_seed_single("ERP School Profile", SCHOOL_SEED)
	_seed_single("ERP Branding Settings", BRANDING_SEED)
	# ERP Feature Settings: cố ý KHÔNG seed — xem docstring đầu file.
	frappe.db.commit()

	from erp.api.erp_common_system.config import clear_bootstrap_cache

	clear_bootstrap_cache()


# ---------------------------------------------------------------------------
# CHỜ XÁC NHẬN — chưa seed vì không tìm được giá trị thật trong codebase.
# Bổ sung vào SCHOOL_SEED khi có, rồi chạy lại `bench migrate` (patch idempotent
# nên field đã seed sẽ không bị ghi đè, field mới sẽ được điền).
#
#   established_year      Năm thành lập
#   legal_entity_name     Code có "Wellspring International Bilingual School Hanoi" (3 chỗ),
#                         PLAN-02 §4.2 đoán "Wellspring International Bilingual Schools"
#   tax_code              Mã số thuế
#   contact_email         PLAN-02 §4.2 đoán info@wellspring.edu.vn — không thấy trong code
#   slogan_vn/slogan_en   Có hay để trống?
#   copyright_text        Câu chữ chính xác cho footer
#   address_en            Địa chỉ tiếng Anh của campus Hà Nội
#   primary_domain        3 ứng viên trong code: prod.sis.wellspring.edu.vn (124 chỗ),
#                         wis.wellspring.edu.vn (8), admin.sis.wellspring.edu.vn (4)
#   facebook_url          FooterSection.tsx có đủ 4 icon MXH nhưng href ĐỀU là "#"
#   youtube_url           → chưa ai điền. Chỉ tìm được https://youtube.com/@wellspring ở 2 chỗ khác.
#   instagram_url         PLAN-02 §4.2 tự ghi chú các URL này là "giá trị suy đoán,
#   zalo_url                phải xác nhận với bộ phận truyền thông trước khi merge".
# ---------------------------------------------------------------------------
