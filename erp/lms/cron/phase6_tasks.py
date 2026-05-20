"""Cron Phase 6 — engagement score & daily digest stub."""


def compute_engagement_score():
	"""Chạy mỗi đêm — tính engagement toàn site."""
	import frappe

	from erp.lms.services.engagement_service import compute_all_sections

	compute_all_sections()
	frappe.db.commit()


def generate_daily_digest():
	"""7:00 user TZ — stub gom digest; publish notification-service ở Phase 7."""
	import frappe

	prefs = frappe.get_all(
		"LMS Notification Preference",
		filters={"digest_frequency": ["in", ["daily", "weekly"]]},
		pluck="user",
		limit=500,
	)
	frappe.logger("lms").info(f"generate_daily_digest: {len(prefs)} users (stub)")
