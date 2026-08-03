# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt
"""Giá trị mặc định khi Single DocType chưa được khởi tạo.

Cố ý dùng giá trị TRUNG TÍNH (không phải Wellspring) — site mới cài sẽ thấy
placeholder rõ ràng và biết phải vào cấu hình. Riêng site Wellspring hiện tại
được patch seed (GD1-05) ghi đè bằng giá trị thật.
"""

DEFAULT_SCHOOL = {
	"school_name_vn": "Tên trường",
	"school_name_en": "School Name",
	"short_name": "SIS",
	"school_code": "",
	"slogan_vn": "",
	"slogan_en": "",
	"established_year": None,
	"accreditation_note": "",
	"contact_email": "",
	"support_email": "",
	"it_email": "",
	"hotline": "",
	"address_vn": "",
	"address_en": "",
	"website_url": "",
	"facebook_url": "",
	"youtube_url": "",
	"instagram_url": "",
	"zalo_url": "",
	"identity_email_domain": "parent.local",
	"primary_domain": "",
	"default_language": "vi",
	"default_timezone": "Asia/Ho_Chi_Minh",
	"legal_entity_name": "",
	"copyright_text": "",
	"tax_code": "",
}

DEFAULT_BRANDING = {
	"logo_full": None,
	"logo_full_dark": None,
	"logo_icon": None,
	"favicon": None,
	"login_illustration": None,
	"splash_image": None,
	"accreditation_logo": None,
	"color_primary": "#F05023",
	"color_secondary": "#002855",
	"color_on_primary": "#FFFFFF",
	"sidebar_style": "light",
	"staff_app_name": "School Portal",  # tên trung tính chốt 03/08/2026 (thay "Staff Portal")
	"parent_app_name": "Parent Portal",
	"social_feed_name": "Feed",
	"ai_assistant_name": "AI Assistant",
	"student_nickname": "Học sinh",
	"seasonal_theme": "default",
	"seasonal_from": None,
	"seasonal_to": None,
	"enable_snowfall": 0,
	"email_header_html": "",
	"email_footer_html": "",
}

FEATURE_FIELDS = [
	"feat_sis", "feat_timetable", "feat_report_card", "feat_attendance",
	"feat_bus", "feat_menu", "feat_health", "feat_library", "feat_facility",
	"feat_finance", "feat_procurement",
	"feat_parent_portal", "feat_social_feed", "feat_chat", "feat_news",
	"feat_lms", "feat_crm_admission", "feat_ai_assistant",
	"feat_it_inventory", "feat_monitoring",
]

DEFAULT_FEATURES = {name: True for name in FEATURE_FIELDS}
DEFAULT_FEATURES.update({"feat_lms": False, "feat_ai_assistant": False, "feat_monitoring": False})
