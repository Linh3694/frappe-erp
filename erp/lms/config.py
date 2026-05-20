"""Cấu hình LMS — đọc từ site_config hoặc biến môi trường."""

import os

import frappe


def get_media_service_url() -> str:
	return (
		frappe.conf.get("lms_media_service_url")
		or os.environ.get("LMS_MEDIA_SERVICE_URL")
		or "http://127.0.0.1:5020"
	).rstrip("/")


def get_media_internal_secret() -> str:
	return frappe.conf.get("lms_media_internal_secret") or os.environ.get(
		"LMS_MEDIA_INTERNAL_SECRET", ""
	)


def get_media_public_url() -> str:
	return (
		frappe.conf.get("lms_media_public_url")
		or os.environ.get("LMS_MEDIA_PUBLIC_URL")
		or ""
	).rstrip("/")
