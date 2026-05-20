"""Cron Phase 6 — engagement score & daily digest stub."""

import frappe

from erp.lms.services import engagement_service, notifications_service


def compute_engagement_score():
	"""Chạy mỗi đêm — tính engagement toàn site."""
	engagement_service.compute_all_sections()


def generate_daily_digest():
	"""7:00 user TZ — stub gom digest; publish notification-service ở Phase 7."""
	# Ghi log để scheduler xác nhận; tích hợp Redis stream sau
	prefs = frappe.get_all(
		"LMS Notification Preference",
		filters={"digest_frequency": ["in", ["daily", "weekly"]]},
		pluck="user",
		limit=500,
	)
	frappe.logger("lms").info(f"generate_daily_digest: {len(prefs)} users (stub)")
	_ = notifications_service  # giữ import cho phase mở rộng
