# Copyright (c) 2026, Wellspring International School and contributors
# API ticket IT Support — CRUD, comment, subtask, feedback

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from erp.api.erp_it_support.notifications import (
	_emit_it_new_message_realtime,
	_it_send_emails_on_ticket_create,
	_notify_it_assignment_changed,
	_notify_it_feedback,
	_notify_it_status_changed,
	_notify_it_ticket_pickup,
	_notify_it_user_reply_job,
)
from erp.api.erp_it_support.utils import (
	CATEGORY_LABELS,
	COMMENT_DOCTYPE,
	DOCTYPE,
	FEEDBACK_BADGES,
	HISTORY_DOCTYPE,
	SUBTASK_DOCTYPE,
	_LIST_TICKET_FIELDS,
	_append_history,
	_bulk_serialize_tickets,
	_can_read_ticket,
	_creator_profile_from_session,
	_is_it_staff,
	_load_history,
	_load_messages,
	_load_subtasks,
	_merge_attachments,
	_form_field,
	_parse_json_body,
	_resolve_ticket_name,
	_ticket_id_from_request,
	_resolve_category_doc,
	_resolve_pic_from_category_role,
	_save_uploaded_attachments,
	_session_email,
	_subtask_to_dict,
	_ticket_to_dict,
	get_available_roles_list,
)
from erp.utils.api_response import (
	error_response,
	forbidden_response,
	not_found_response,
	success_response,
	validation_error_response,
)


@frappe.whitelist(allow_guest=False)
def get_ticket_categories():
	"""Danh mục ticket (value/label) — khớp FE."""
	try:
		rows = frappe.get_all(
			"ERP IT Support Category",
			fields=["title"],
			order_by="title asc",
		)
		data = []
		for r in rows:
			title = (r.get("title") or "").strip()
			if not title or title == "Email Ticket":
				continue
			data.append({"value": title, "label": CATEGORY_LABELS.get(title, title)})
		if not data:
			data = [
				{"value": k, "label": v}
				for k, v in CATEGORY_LABELS.items()
				if k != "Email Ticket"
			]
		return success_response(data, "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.get_ticket_categories")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_my_tickets():
	try:
		email = _session_email()
		if not email:
			return success_response({"tickets": []}, "OK")
		rows = frappe.get_all(
			DOCTYPE,
			filters={"creator_email": email},
			fields=_LIST_TICKET_FIELDS,
			order_by="modified desc",
		)
		tickets = _bulk_serialize_tickets(rows)
		return success_response({"tickets": tickets}, "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.get_my_tickets")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_all_tickets():
	try:
		if not _is_it_staff():
			return forbidden_response(_("Chỉ đội IT mới xem được tất cả ticket"))
		rows = frappe.get_all(
			DOCTYPE,
			fields=_LIST_TICKET_FIELDS,
			order_by="modified desc",
			limit=2000,
		)
		tickets = _bulk_serialize_tickets(rows)
		return success_response({"tickets": tickets}, "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.get_all_tickets")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_ticket(ticket_id=None, name=None):
	try:
		data = _parse_json_body()
		tid = _resolve_ticket_name(_ticket_id_from_request(data, ticket_id, name))
		if not tid:
			return not_found_response(_("Không tìm thấy ticket"))
		doc = frappe.get_doc(DOCTYPE, tid)
		if not _can_read_ticket(doc):
			return forbidden_response(_("Không có quyền"))
		return success_response(_ticket_to_dict(doc, include_relations=True), "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.get_ticket")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_ticket():
	"""Tạo ticket — hỗ trợ multipart attachments."""
	try:
		data = _parse_json_body()
		title = _form_field("title", data)
		description = _form_field("description", data)
		category_raw = _form_field("category", data)
		if not title or not description or not category_raw:
			return validation_error_response(
				_("Thiếu title, description hoặc category"),
				{"title": ["required"], "description": ["required"], "category": ["required"]},
			)
		category_doc = _resolve_category_doc(category_raw)
		if not category_doc:
			return validation_error_response(_("Danh mục không hợp lệ"), {"category": ["invalid"]})

		priority = _form_field("priority", data, "Medium")
		notes = _form_field("notes", data)
		profile = _creator_profile_from_session()
		pic = _resolve_pic_from_category_role(category_raw)

		row = {
			"doctype": DOCTYPE,
			"title": title,
			"description": description,
			"category": category_doc,
			"priority": priority,
			"notes": notes,
			"status": "Assigned",
			"source": _form_field("source", data, "web"),
			"creator_email": profile["email"],
			"creator_fullname": profile["fullname"],
			"creator_avatar": profile["avatar"],
			"creator_department": profile["department"],
			"creator_jobtitle": profile["jobtitle"],
		}
		if pic:
			row["assigned_to"] = pic
			row["assigned_to_fullname"] = frappe.db.get_value("User", pic, "full_name") or pic
			row["accepted_at"] = now_datetime()

		doc = frappe.get_doc(row)
		doc.insert(ignore_permissions=True)

		new_attachments = _save_uploaded_attachments(doc.name)
		if new_attachments:
			doc.attachments_json = _merge_attachments(None, new_attachments)
			doc.save(ignore_permissions=True)

		_append_history(doc.name, _("Tạo ticket"))
		frappe.db.commit()

		doc.reload()
		try:
			_it_send_emails_on_ticket_create(doc)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "it_support.create_ticket.notify")

		return success_response(_ticket_to_dict(doc), "OK")
	except frappe.DuplicateEntryError:
		frappe.db.rollback()
		return error_response(_("Trùng mã ticket, vui lòng thử lại"), code="DUPLICATE")
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "it_support.create_ticket")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_ticket():
	try:
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(
			_ticket_id_from_request(data, _form_field("ticket_id", data), _form_field("name", data))
		)
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		doc = frappe.get_doc(DOCTYPE, ticket_id)
		if not _can_read_ticket(doc):
			return forbidden_response(_("Không có quyền"))

		old_status = doc.status
		is_staff = _is_it_staff()
		is_creator = doc.creator_email == _session_email()

		title = _form_field("title", data)
		if title:
			doc.title = title
		description = _form_field("description", data)
		if description:
			doc.description = description
		if "notes" in data:
			doc.notes = _form_field("notes", data)
		priority = _form_field("priority", data)
		if priority:
			doc.priority = priority
		category_raw = _form_field("category", data)
		if category_raw:
			cat = _resolve_category_doc(category_raw)
			if cat:
				doc.category = cat

		new_status = _form_field("status", data)
		if new_status and new_status != doc.status:
			if not is_staff:
				return forbidden_response(_("Chỉ đội IT mới đổi trạng thái"))
			doc.status = new_status
			if new_status == "Closed":
				doc.closed_at = now_datetime()
			if new_status in ("Processing", "Assigned") and old_status in ("Done", "Closed"):
				doc.closed_at = None

		new_attachments = _save_uploaded_attachments(doc.name)
		if new_attachments:
			doc.attachments_json = _merge_attachments(doc.attachments_json, new_attachments)

		doc.save(ignore_permissions=True)
		if doc.status != old_status:
			_append_history(doc.name, _("Đổi trạng thái: {0} → {1}").format(old_status, doc.status))
			try:
				_notify_it_status_changed(doc, old_status, doc.status, actor_email=_session_email())
			except Exception:
				frappe.log_error(frappe.get_traceback(), "it_support.update_ticket.notify")
		elif is_creator or is_staff:
			_append_history(doc.name, _("Cập nhật ticket"))
		frappe.db.commit()
		return success_response(_ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name)), "OK")
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "it_support.update_ticket")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_ticket():
	try:
		if not _is_it_staff():
			return forbidden_response(_("Chỉ đội IT mới xóa ticket"))
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(_ticket_id_from_request(data, data.get("ticket_id"), data.get("name")))
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		frappe.delete_doc(DOCTYPE, ticket_id, ignore_permissions=True)
		frappe.db.commit()
		return success_response({"success": True}, "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.delete_ticket")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def assign_ticket():
	"""Nhận ticket (assign to me)."""
	try:
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(_ticket_id_from_request(data, data.get("ticket_id"), data.get("name")))
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		doc = frappe.get_doc(DOCTYPE, ticket_id)
		if not _is_it_staff():
			return forbidden_response(_("Chỉ đội IT mới nhận ticket"))

		user = frappe.session.user
		doc.assigned_to = user
		doc.assigned_to_fullname = frappe.db.get_value("User", user, "full_name") or user
		doc.accepted_at = now_datetime()
		if doc.status == "Assigned":
			doc.status = "Processing"
		doc.save(ignore_permissions=True)
		_append_history(doc.name, _("Nhận xử lý ticket"))
		frappe.db.commit()
		try:
			_notify_it_ticket_pickup(doc)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "it_support.assign_ticket.notify")
		return success_response(_ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name)), "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.assign_ticket")
		return error_response(str(e))


def _resolve_frappe_user_ref(user_ref: str) -> tuple[str, str]:
	"""Map User.name hoặc email → (User.name, full_name)."""
	assigned = (user_ref or "").strip()
	if not assigned:
		return "", ""
	if frappe.db.exists("User", assigned):
		full_name = frappe.db.get_value("User", assigned, "full_name") or assigned
		return assigned, full_name
	resolved = frappe.db.get_value("User", {"email": assigned}, "name") or assigned
	full_name = frappe.db.get_value("User", resolved, "full_name") or resolved
	return resolved, full_name


@frappe.whitelist(allow_guest=False)
def reassign_ticket():
	"""Chuyển ticket cho nhân viên IT khác (mobile admin)."""
	try:
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(_ticket_id_from_request(data, data.get("ticket_id"), data.get("name")))
		assignee_ref = (data.get("assignedTo") or data.get("assigned_to") or "").strip()
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		if not assignee_ref:
			return validation_error_response(_("Thiếu người được giao"))
		if not _is_it_staff():
			return forbidden_response(_("Chỉ đội IT mới chuyển ticket"))

		assignee_user, assignee_name = _resolve_frappe_user_ref(assignee_ref)
		if not assignee_user or not frappe.db.exists("User", assignee_user):
			return validation_error_response(_("Không tìm thấy người dùng"))

		doc = frappe.get_doc(DOCTYPE, ticket_id)
		previous_assignee = doc.assigned_to
		doc.assigned_to = assignee_user
		doc.assigned_to_fullname = assignee_name
		if not doc.accepted_at:
			doc.accepted_at = now_datetime()
		if doc.status == "Assigned":
			doc.status = "Processing"
		doc.save(ignore_permissions=True)

		_append_history(
			doc.name,
			_("Chuyển xử lý từ {0} sang {1}").format(
				previous_assignee or _("Chưa giao"),
				assignee_name,
			),
		)
		frappe.db.commit()
		try:
			if assignee_user != previous_assignee:
				_notify_it_assignment_changed(doc, assignee_user)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "it_support.reassign_ticket.notify")
		return success_response(_ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name)), "OK")
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "it_support.reassign_ticket")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def cancel_ticket():
	try:
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(_ticket_id_from_request(data, data.get("ticket_id"), data.get("name")))
		cancel_reason = (data.get("cancelReason") or data.get("cancellation_reason") or "").strip()
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		doc = frappe.get_doc(DOCTYPE, ticket_id)
		email = _session_email()
		if not _is_it_staff() and doc.creator_email != email:
			return forbidden_response(_("Không có quyền hủy ticket"))
		if not cancel_reason:
			return validation_error_response(_("Vui lòng nhập lý do hủy"))

		old_status = doc.status
		doc.status = "Cancelled"
		doc.cancellation_reason = cancel_reason
		doc.save(ignore_permissions=True)
		_append_history(doc.name, _("Hủy ticket"), detail=cancel_reason)
		frappe.db.commit()
		try:
			_notify_it_status_changed(
				doc,
				old_status,
				"Cancelled",
				{"cancellationReason": cancel_reason},
				actor_email=email,
			)
		except Exception:
			pass
		return success_response(_ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name)), "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.cancel_ticket")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def reopen_ticket():
	try:
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(_ticket_id_from_request(data, data.get("ticket_id"), data.get("name")))
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		doc = frappe.get_doc(DOCTYPE, ticket_id)
		if doc.creator_email != _session_email() and not _is_it_staff():
			return forbidden_response(_("Không có quyền"))
		if doc.status not in ("Done", "Closed", "Cancelled"):
			return validation_error_response(_("Ticket không thể mở lại ở trạng thái hiện tại"))

		old_status = doc.status
		doc.status = "Processing"
		doc.closed_at = None
		doc.save(ignore_permissions=True)
		_append_history(doc.name, _("Mở lại ticket"))
		frappe.db.commit()
		try:
			_notify_it_status_changed(doc, old_status, doc.status, actor_email=_session_email())
		except Exception:
			pass
		return success_response({"success": True, "ticket": _ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name))}, "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.reopen_ticket")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def accept_feedback():
	try:
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(_ticket_id_from_request(data, data.get("ticket_id"), data.get("name")))
		rating = int(data.get("rating") or 0)
		comment = (data.get("comment") or "").strip()
		badges = data.get("badges") or []
		if isinstance(badges, str):
			try:
				badges = json.loads(badges)
			except Exception:
				badges = []
		if rating < 1 or rating > 5:
			return validation_error_response(_("Đánh giá phải từ 1 đến 5 sao"))
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		doc = frappe.get_doc(DOCTYPE, ticket_id)
		if doc.creator_email != _session_email():
			return forbidden_response(_("Chỉ người tạo mới đánh giá"))
		if doc.status not in ("Assigned", "Processing", "Waiting for Customer", "Done"):
			return validation_error_response(_("Ticket không thể đóng ở trạng thái hiện tại"))

		invalid_badges = [b for b in badges if b not in FEEDBACK_BADGES]
		if invalid_badges:
			return validation_error_response(_("Badge không hợp lệ: {0}").format(", ".join(invalid_badges)))

		old_status = doc.status
		doc.feedback_rating = rating
		doc.feedback_comment = comment
		doc.feedback_badges = json.dumps(badges, separators=(",", ":")) if badges else None
		doc.status = "Closed"
		doc.closed_at = now_datetime()
		doc.save(ignore_permissions=True)
		_append_history(doc.name, _("Chấp nhận kết quả — {0} sao").format(rating))
		frappe.db.commit()
		try:
			actor = _session_email()
			_notify_it_feedback(doc, actor_email=actor)
			_notify_it_status_changed(doc, old_status, "Closed", actor_email=actor)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "it_support.accept_feedback.notify")
		return success_response(
			{
				"success": True,
				"message": _("Cảm ơn bạn đã đánh giá! Ticket đã được đóng thành công."),
				"ticket": _ticket_to_dict(frappe.get_doc(DOCTYPE, doc.name)),
			},
			"OK",
		)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.accept_feedback")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_feedback_stats(email=None):
	try:
		data = _parse_json_body()
		em = (email or data.get("email") or frappe.form_dict.get("email") or "").strip()
		if not em:
			return validation_error_response(_("Thiếu email"))
		user_name = frappe.db.get_value("User", {"email": em}, "name")
		if not user_name:
			return not_found_response(_("Người dùng không tồn tại"))

		all_tickets = frappe.get_all(
			DOCTYPE,
			filters={"assigned_to": user_name},
			fields=["name", "status", "feedback_rating", "feedback_badges"],
		)
		total = len(all_tickets)
		closed = sum(1 for t in all_tickets if t.status == "Closed")
		completed = sum(1 for t in all_tickets if t.status in ("Done", "Closed"))
		with_fb = [t for t in all_tickets if (t.feedback_rating or 0) >= 1]

		if not with_fb:
			return success_response(
				{
					"user": {"email": em},
					"summary": {
						"totalTickets": total,
						"completedTickets": completed,
						"closedTickets": closed,
						"feedbackCount": 0,
					},
					"feedback": {
						"averageRating": 0,
						"badges": [],
						"badgeCounts": {},
					},
				},
				"OK",
			)

		ratings = [t.feedback_rating for t in with_fb]
		avg = sum(ratings) / len(ratings)
		badge_counts = {}
		for t in with_fb:
			for b in _parse_badges(t.feedback_badges):
				badge_counts[b] = badge_counts.get(b, 0) + 1

		return success_response(
			{
				"user": {"email": em},
				"summary": {
					"totalTickets": total,
					"completedTickets": completed,
					"closedTickets": closed,
					"feedbackCount": len(with_fb),
				},
				"feedback": {
					"averageRating": round(avg, 1),
					"badges": sorted(badge_counts.keys(), key=lambda x: -badge_counts[x]),
					"badgeCounts": badge_counts,
				},
			},
			"OK",
		)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.get_feedback_stats")
		return error_response(str(e))


def _parse_badges(raw):
	if not raw:
		return []
	if isinstance(raw, list):
		return raw
	try:
		parsed = json.loads(raw)
		return parsed if isinstance(parsed, list) else []
	except Exception:
		return []


# --- Subtasks ---


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_subtasks(ticket_id=None):
	try:
		data = _parse_json_body()
		tid = _resolve_ticket_name(_ticket_id_from_request(data, ticket_id))
		if not tid:
			return not_found_response(_("Không tìm thấy ticket"))
		doc = frappe.get_doc(DOCTYPE, tid)
		if not _can_read_ticket(doc):
			return forbidden_response(_("Không có quyền"))
		return success_response({"success": True, "subTasks": _load_subtasks(tid)}, "OK")
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def create_subtask():
	try:
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(_ticket_id_from_request(data, data.get("ticket_id"), data.get("name")))
		title = (data.get("title") or "").strip()
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		if not title:
			return validation_error_response(_("Thiếu tiêu đề subtask"))
		doc = frappe.get_doc(DOCTYPE, ticket_id)
		if not _is_it_staff():
			return forbidden_response(_("Chỉ đội IT tạo subtask"))

		assigned = (data.get("assignedTo") or data.get("assigned_to") or "").strip()
		assigned_name = ""
		if assigned:
			if frappe.db.exists("User", assigned):
				assigned_name = frappe.db.get_value("User", assigned, "full_name") or assigned
			else:
				assigned = frappe.db.get_value("User", {"email": assigned}, "name") or assigned
				assigned_name = frappe.db.get_value("User", assigned, "full_name") or assigned

		st = frappe.get_doc(
			{
				"doctype": SUBTASK_DOCTYPE,
				"ticket": ticket_id,
				"title": title,
				"description": (data.get("description") or "").strip(),
				"assigned_to": assigned or None,
				"assigned_to_fullname": assigned_name,
				"status": (data.get("status") or "In Progress").strip(),
			}
		)
		st.insert(ignore_permissions=True)
		_append_history(ticket_id, _("Tạo subtask: {0}").format(title))
		frappe.db.commit()
		return success_response({"success": True, "ticket": _ticket_to_dict(frappe.get_doc(DOCTYPE, ticket_id), include_relations=True)}, "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.create_subtask")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def update_subtask():
	try:
		data = _parse_json_body()
		ticket_id = data.get("ticket_id")
		sub_id = data.get("sub_task_id") or data.get("subTaskId")
		status = (data.get("status") or "").strip()
		if not sub_id or not frappe.db.exists(SUBTASK_DOCTYPE, sub_id):
			return not_found_response(_("Không tìm thấy subtask"))
		st = frappe.get_doc(SUBTASK_DOCTYPE, sub_id)
		tid = _resolve_ticket_name(_ticket_id_from_request(data, ticket_id)) or st.ticket
		if not tid:
			return not_found_response(_("Không tìm thấy ticket"))
		tdoc = frappe.get_doc(DOCTYPE, tid)
		if not _is_it_staff() and tdoc.assigned_to != frappe.session.user:
			return forbidden_response(_("Không có quyền"))
		if status:
			st.status = status
			st.save(ignore_permissions=True)
			_append_history(tid, _("Cập nhật subtask → {0}").format(status))
		frappe.db.commit()
		return success_response({"success": True}, "OK")
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_subtask():
	try:
		data = _parse_json_body()
		sub_id = data.get("sub_task_id") or data.get("subTaskId")
		if not sub_id or not frappe.db.exists(SUBTASK_DOCTYPE, sub_id):
			return not_found_response(_("Không tìm thấy subtask"))
		st = frappe.get_doc(SUBTASK_DOCTYPE, sub_id)
		tdoc = frappe.get_doc(DOCTYPE, st.ticket)
		if not _is_it_staff() and tdoc.assigned_to != frappe.session.user:
			return forbidden_response(_("Không có quyền"))
		frappe.delete_doc(SUBTASK_DOCTYPE, sub_id, ignore_permissions=True)
		frappe.db.commit()
		return success_response({"success": True}, "OK")
	except Exception as e:
		return error_response(str(e))


# --- Comments / messages ---


@frappe.whitelist(allow_guest=False)
def get_comments():
	try:
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(_ticket_id_from_request(data, data.get("ticket_id"), data.get("name")))
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		doc = frappe.get_doc(DOCTYPE, ticket_id)
		if not _can_read_ticket(doc):
			return forbidden_response(_("Không có quyền"))
		messages = _load_messages(ticket_id)
		return success_response({"success": True, "messages": messages}, "OK")
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def send_comment():
	try:
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(
			_ticket_id_from_request(data, _form_field("ticket_id", data) or _form_field("name", data))
		)
		text = _form_field("text", data)
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		doc = frappe.get_doc(DOCTYPE, ticket_id)
		if not _can_read_ticket(doc):
			return forbidden_response(_("Không có quyền"))

		raw_images = data.get("images") or []
		if isinstance(raw_images, str):
			raw_images = [raw_images] if raw_images.strip() else []
		images = [str(u).strip() for u in raw_images if u]

		# Upload file kèm tin nhắn (multipart field `files`)
		uploaded = _save_uploaded_attachments(ticket_id)
		for att in uploaded:
			if att.get("url"):
				images.append(att["url"])

		if not text and not images:
			return validation_error_response(_("Vui lòng nhập nội dung hoặc đính kèm ảnh"))

		if doc.status not in ("Processing", "Waiting for Customer"):
			return validation_error_response(_("Không thể gửi tin nhắn khi ticket ở trạng thái hiện tại"))

		email = _session_email()
		user = frappe.session.user
		ufn = frappe.db.get_value("User", user, "full_name") or user
		uimg = frappe.db.get_value("User", user, "user_image") or ""

		is_creator = doc.creator_email == email
		is_assigned = doc.assigned_to == user
		is_staff = _is_it_staff()

		status_changed = False
		old_status = doc.status
		new_status = doc.status

		if is_assigned and doc.status == "Processing":
			doc.status = "Waiting for Customer"
			status_changed = True
			new_status = doc.status
		elif is_creator and doc.status == "Waiting for Customer" and not is_assigned:
			doc.status = "Processing"
			status_changed = True
			new_status = doc.status

		if images and text:
			msg_type = "text_with_images"
		elif images:
			msg_type = "image"
		else:
			msg_type = "text"

		row = {
			"doctype": COMMENT_DOCTYPE,
			"ticket": ticket_id,
			"sender_email": email,
			"sender_fullname": ufn,
			"sender_avatar": uimg,
			"text": text,
			"message_type": msg_type,
		}
		if images:
			row["images_json"] = json.dumps(images, separators=(",", ":"))
		c = frappe.get_doc(row)
		c.insert(ignore_permissions=True)

		if status_changed:
			doc.save(ignore_permissions=True)
			_append_history(ticket_id, _("Đổi trạng thái: {0} → {1}").format(old_status, new_status))

		excerpt = text[:500] if text else (_("Gửi {0} ảnh/video").format(len(images)) if images else "")
		_append_history(ticket_id, _("Trao đổi"), detail=excerpt or None)
		frappe.db.commit()

		msg_snippet = text[:80] if text else (_("Gửi ảnh/video") if images else "")
		try:
			frappe.enqueue(
				method="erp.api.erp_it_support.notifications._notify_it_user_reply_job",
				queue="short",
				job_name=f"it_ticket_reply_{ticket_id}",
				ticket_id=ticket_id,
				sender_email=email,
				message_snippet=msg_snippet,
				enqueue_after_commit=True,
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "it_support.send_comment.enqueue")

		if status_changed:
			try:
				_notify_it_status_changed(
					frappe.get_doc(DOCTYPE, ticket_id),
					old_status,
					new_status,
					{"messageContent": text, "messageSender": ufn},
					actor_email=email,
				)
			except Exception:
				pass

		message_data = {
			"_id": c.name,
			"sender": {"_id": email, "fullname": ufn, "email": email, "avatarUrl": uimg},
			"text": text,
			"timestamp": c.creation,
			"type": msg_type,
			"images": images,
		}
		try:
			_emit_it_new_message_realtime(frappe.get_doc(DOCTYPE, ticket_id), message_data, email)
		except Exception:
			pass

		resp = {
			"success": True,
			"message": "OK",
			"messageData": message_data,
			"ticket": _ticket_to_dict(frappe.get_doc(DOCTYPE, ticket_id)),
		}
		if status_changed:
			resp.update(
				{
					"statusChanged": True,
					"oldStatus": old_status,
					"newStatus": new_status,
				}
			)
		return success_response(resp, "OK")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "it_support.send_comment")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_history():
	try:
		data = _parse_json_body()
		ticket_id = _resolve_ticket_name(_ticket_id_from_request(data, data.get("ticket_id"), data.get("name")))
		if not ticket_id:
			return not_found_response(_("Không tìm thấy ticket"))
		doc = frappe.get_doc(DOCTYPE, ticket_id)
		if not _can_read_ticket(doc):
			return forbidden_response(_("Không có quyền"))
		return success_response(_load_history(ticket_id), "OK")
	except Exception as e:
		return error_response(str(e))
