"""Inbox khóa học — LMS Conversation / Message (§7.13)."""

import json

import frappe
from frappe.utils import now_datetime

from erp.lms.utils.enrollment import validate_section_enrollment
from erp.lms.utils.permissions import user_enrolled_in_course


def _user_in_conversation(conversation_id: str, user: str) -> bool:
	conv = frappe.db.get_value(
		"LMS Conversation",
		conversation_id,
		["course", "section", "participant_users_json"],
		as_dict=True,
	)
	if not conv:
		return False
	if conv.section:
		try:
			validate_section_enrollment(conv.section, user, min_role="observer")
			return True
		except frappe.PermissionError:
			pass
	if conv.course and user_enrolled_in_course(user, conv.course):
		return True
	participants = conv.participant_users_json
	if isinstance(participants, str):
		try:
			participants = json.loads(participants)
		except json.JSONDecodeError:
			participants = []
	if isinstance(participants, list) and user in participants:
		return True
	return False


def _touch_participants(conversation_id: str, user: str):
	conv = frappe.get_doc("LMS Conversation", conversation_id)
	participants = conv.participant_users_json or []
	if isinstance(participants, str):
		try:
			participants = json.loads(participants)
		except json.JSONDecodeError:
			participants = []
	if not isinstance(participants, list):
		participants = []
	if user not in participants:
		participants.append(user)
		conv.participant_users_json = json.dumps(participants)
		conv.save(ignore_permissions=True)


def get_or_create_section_inbox(section_id: str) -> str:
	"""Tạo hội thoại mặc định cho section nếu chưa có."""
	existing = frappe.db.get_value(
		"LMS Conversation",
		{"section": section_id, "subject": "Hộp thư lớp"},
		"name",
	)
	if existing:
		return existing
	course_id = frappe.db.get_value("LMS Course Section", section_id, "course")
	doc = frappe.get_doc(
		{
			"doctype": "LMS Conversation",
			"course": course_id,
			"section": section_id,
			"subject": "Hộp thư lớp",
			"participant_users_json": "[]",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def list_conversations(course_id: str | None = None, section_id: str | None = None, user: str | None = None) -> list:
	user = user or frappe.session.user
	if section_id:
		validate_section_enrollment(section_id, user, min_role="observer")
		get_or_create_section_inbox(section_id)
		filters = {"section": section_id}
	elif course_id:
		if not user_enrolled_in_course(user, course_id):
			frappe.throw("Không có quyền", frappe.PermissionError)
		filters = {"course": course_id}
	else:
		# Các section user đang enroll
		enrollments = frappe.get_all(
			"LMS Enrollment",
			filters={"user": user, "status": "active"},
			pluck="section",
		)
		student_sections = []
		from erp.lms.utils.permissions import _get_crm_student_for_user

		student_id = _get_crm_student_for_user(user)
		if student_id:
			student_sections = frappe.get_all(
				"LMS Enrollment",
				filters={"student_id": student_id, "status": "active"},
				pluck="section",
			)
		section_ids = list({s for s in (enrollments + student_sections) if s})
		if not section_ids:
			return []
		filters = {"section": ["in", section_ids]}

	rows = frappe.get_all(
		"LMS Conversation",
		filters=filters,
		fields=["name", "subject", "course", "section", "last_message_at"],
		order_by="last_message_at desc, modified desc",
		limit=100,
	)
	# Lọc theo quyền participant / enrollment
	result = []
	for row in rows:
		if _user_in_conversation(row.name, user):
			result.append(row)
	return result


def list_messages(conversation_id: str, user: str | None = None) -> list:
	user = user or frappe.session.user
	if not _user_in_conversation(conversation_id, user):
		frappe.throw("Không có quyền xem hội thoại", frappe.PermissionError)
	return frappe.get_all(
		"LMS Message",
		filters={"conversation": conversation_id},
		fields=["name", "conversation", "sender", "body", "sent_at"],
		order_by="sent_at asc",
		limit=500,
	)


def send_message(conversation_id: str, body: str, user: str | None = None) -> dict:
	user = user or frappe.session.user
	if not body or not str(body).strip():
		frappe.throw("Nội dung tin nhắn bắt buộc")
	if not _user_in_conversation(conversation_id, user):
		frappe.throw("Không có quyền gửi tin", frappe.PermissionError)

	msg = frappe.get_doc(
		{
			"doctype": "LMS Message",
			"conversation": conversation_id,
			"sender": user,
			"body": str(body).strip(),
			"sent_at": now_datetime(),
		}
	)
	msg.insert(ignore_permissions=True)
	_touch_participants(conversation_id, user)
	frappe.db.set_value("LMS Conversation", conversation_id, "last_message_at", msg.sent_at)
	return msg.as_dict()
