# Copyright (c) 2026, Wellspring International School and contributors
# Sinh file .ics và gửi lời mời lịch qua email-service (Microsoft Graph).

import base64
import uuid

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from erp.utils.email_service import send_email_via_service

ICS_TZ = "Asia/Ho_Chi_Minh"
ICS_PRODID = "-//Wellspring International School//Room Booking//VI"


def ensure_calendar_uid(doc):
	"""Sinh UID ổn định cho lịch nếu chưa có."""
	if (doc.calendar_uid or "").strip():
		return doc.calendar_uid
	uid = f"{doc.name}-{uuid.uuid4().hex[:12]}@wellspring-room-booking"
	frappe.db.set_value(doc.doctype, doc.name, "calendar_uid", uid, update_modified=False)
	doc.calendar_uid = uid
	return uid


def _ics_escape(text):
	"""Escape ký tự đặc biệt theo RFC 5545."""
	if not text:
		return ""
	s = str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
	return s


def _ics_local_dt(dt):
	"""Datetime → chuỗi ICS local (TZID=Asia/Ho_Chi_Minh)."""
	d = get_datetime(dt)
	if not d:
		return ""
	return d.strftime("%Y%m%dT%H%M%S")


def _ics_utc_stamp(dt=None):
	"""DTSTAMP theo UTC."""
	d = get_datetime(dt or now_datetime())
	return d.strftime("%Y%m%dT%H%M%SZ")


def _room_location(doc):
	"""Ghép tên phòng + tòa nhà cho trường LOCATION."""
	room_label = frappe.db.get_value("ERP Administrative Room", doc.room_id, "title_vn") or doc.room_id
	building_label = (
		frappe.db.get_value("ERP Administrative Building", doc.building_id, "title_vn") or doc.building_id
	)
	parts = [p for p in [room_label, building_label] if p]
	return " — ".join(parts)


def build_ics(doc, method="REQUEST"):
	"""Sinh nội dung VCALENDAR cho booking (REQUEST hoặc CANCEL)."""
	uid = ensure_calendar_uid(doc)
	seq = int(doc.calendar_sequence or 0)
	method = (method or "REQUEST").upper()
	status = "CANCELLED" if method == "CANCEL" else "CONFIRMED"

	org_name = _ics_escape(doc.booked_by_fullname or doc.booked_by_email or "")
	org_email = (doc.booked_by_email or "").strip()
	organizer = f"ORGANIZER;CN={org_name}:mailto:{org_email}" if org_email else ""

	attendee_lines = []
	for row in doc.get("attendees") or []:
		em = (row.email or "").strip()
		if not em:
			continue
		cn = _ics_escape(row.full_name or em)
		attendee_lines.append(f"ATTENDEE;CN={cn};RSVP=TRUE;ROLE=REQ-PARTICIPANT:mailto:{em}")

	lines = [
		"BEGIN:VCALENDAR",
		"VERSION:2.0",
		f"PRODID:{ICS_PRODID}",
		"CALSCALE:GREGORIAN",
		f"METHOD:{method}",
		"BEGIN:VEVENT",
		f"UID:{uid}",
		f"SEQUENCE:{seq}",
		f"DTSTAMP:{_ics_utc_stamp()}",
		f"DTSTART;TZID={ICS_TZ}:{_ics_local_dt(doc.start_time)}",
		f"DTEND;TZID={ICS_TZ}:{_ics_local_dt(doc.end_time)}",
		f"SUMMARY:{_ics_escape(doc.title or doc.name)}",
		f"LOCATION:{_ics_escape(_room_location(doc))}",
		f"DESCRIPTION:{_ics_escape(doc.description or '')}",
		f"STATUS:{status}",
	]
	if organizer:
		lines.append(organizer)
	lines.extend(attendee_lines)
	lines.extend(["END:VEVENT", "END:VCALENDAR"])
	return "\r\n".join(lines) + "\r\n"


def _booking_recipients(doc):
	"""Danh sách email nhận lời mời: người đặt + người tham dự (không trùng)."""
	seen = set()
	result = []
	for em in [(doc.booked_by_email or "").strip(), *[
		(r.email or "").strip() for r in (doc.get("attendees") or [])
	]]:
		key = em.lower()
		if not em or key in seen:
			continue
		seen.add(key)
		result.append(em)
	return result


def send_booking_invites(doc, method="REQUEST"):
	"""Gửi email kèm file .ics qua email-service — lỗi gửi mail không làm fail booking."""
	try:
		recipients = _booking_recipients(doc)
		if not recipients:
			return
		ics_content = build_ics(doc, method=method)
		method_upper = (method or "REQUEST").upper()
		is_cancel = method_upper == "CANCEL"
		ics_method = "CANCEL" if is_cancel else "REQUEST"
		subject = (
			_(f"[Huỷ đặt phòng] {doc.title or doc.name}")
			if is_cancel
			else _(f"[Đặt phòng] {doc.title or doc.name}")
		)
		text = (
			"Cuộc họp đã được huỷ. Tệp đính kèm giúp cập nhật lịch của bạn."
			if is_cancel
			else "Vui lòng mở tệp đính kèm để thêm sự kiện vào lịch (Google Calendar, Outlook, Apple Calendar)."
		)
		body_html = f"<p>{frappe.utils.escape_html(_(text))}</p>"
		attachments = [
			{
				"name": f"dat-phong-{doc.name}.ics",
				"contentType": f"text/calendar; method={ics_method}",
				"contentBytes": base64.b64encode(ics_content.encode("utf-8")).decode("ascii"),
			}
		]
		from_email = (frappe.conf.get("room_booking_email_from") or "").strip() or None
		result = send_email_via_service(
			to_list=recipients,
			subject=subject,
			body=body_html,
			from_email=from_email,
			attachments=attachments,
		)
		if not result.get("success"):
			frappe.log_error(
				result.get("message") or "send_email_via_service failed",
				"room_booking_ics.send_booking_invites",
			)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "room_booking_ics.send_booking_invites")


def bump_calendar_sequence(doc):
	"""Tăng SEQUENCE trước khi gửi cập nhật lịch."""
	seq = int(doc.calendar_sequence or 0) + 1
	frappe.db.set_value(doc.doctype, doc.name, "calendar_sequence", seq, update_modified=False)
	doc.calendar_sequence = seq
