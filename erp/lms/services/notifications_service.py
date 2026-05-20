"""Notification preferences — Phase 6 (§7.9)."""

import json

import frappe


DEFAULT_PREFS = {
	"channel": "both",
	"digest_frequency": "daily",
	"quiet_hours_start": "22:00",
	"quiet_hours_end": "07:00",
	"mute_until": None,
	"categories_muted": [],
}


def _normalize(doc: dict | frappe.Document) -> dict:
	cats = doc.get("categories_muted_json") or doc.get("categories_muted") or []
	if isinstance(cats, str):
		try:
			cats = json.loads(cats)
		except json.JSONDecodeError:
			cats = []
	return {
		"user": doc.get("user"),
		"channel": doc.get("channel") or DEFAULT_PREFS["channel"],
		"digest_frequency": doc.get("digest_frequency") or DEFAULT_PREFS["digest_frequency"],
		"quiet_hours_start": doc.get("quiet_hours_start") or DEFAULT_PREFS["quiet_hours_start"],
		"quiet_hours_end": doc.get("quiet_hours_end") or DEFAULT_PREFS["quiet_hours_end"],
		"mute_until": str(doc.get("mute_until")) if doc.get("mute_until") else None,
		"categories_muted": cats if isinstance(cats, list) else [],
	}


def get_preferences(user: str | None = None) -> dict:
	user = user or frappe.session.user
	if frappe.db.exists("LMS Notification Preference", user):
		doc = frappe.get_doc("LMS Notification Preference", user)
		return _normalize(doc)
	return {**DEFAULT_PREFS, "user": user}


def update_preferences(data: dict, user: str | None = None) -> dict:
	user = user or frappe.session.user
	payload = data or {}
	allowed = {
		"channel",
		"digest_frequency",
		"quiet_hours_start",
		"quiet_hours_end",
		"mute_until",
		"categories_muted",
		"categories_muted_json",
	}
	if frappe.db.exists("LMS Notification Preference", user):
		doc = frappe.get_doc("LMS Notification Preference", user)
	else:
		doc = frappe.get_doc({"doctype": "LMS Notification Preference", "user": user})

	for key, val in payload.items():
		if key not in allowed:
			continue
		if key == "categories_muted":
			doc.categories_muted_json = json.dumps(val or [])
		elif key == "categories_muted_json":
			doc.categories_muted_json = val if isinstance(val, str) else json.dumps(val or [])
		else:
			setattr(doc, key, val)
	doc.save(ignore_permissions=True)
	return _normalize(doc)
