# Blueprint API — Phase 5

import frappe

from erp.lms.services import blueprint_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def register_blueprint():
	try:
		data = frappe.request.json or frappe.form_dict
		result = blueprint_service.register_blueprint(
			template_course_id=data.get("template_course_id"),
			sync_settings=data.get("sync_settings"),
		)
		return single_item_response(result, message="Blueprint registered")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def sync_to_sections():
	try:
		data = frappe.request.json or frappe.form_dict
		result = blueprint_service.sync_to_sections(
			template_course_id=data.get("template_course_id"),
			blueprint_id=data.get("blueprint_id"),
			child_course_ids=data.get("child_course_ids"),
			dry_run=bool(int(data.get("dry_run", 0))),
		)
		return success_response(data=result, message="Blueprint sync completed")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_blueprints():
	try:
		rows = blueprint_service.list_blueprints()
		return success_response(data=rows)
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def create_blueprint_template():
	try:
		data = frappe.request.json or frappe.form_dict
		title = data.get("title")
		if not title:
			return error_response("title bắt buộc", code="VALIDATION_ERROR")
		result = blueprint_service.create_blueprint_template(
			title=title,
			code=data.get("code"),
			program=data.get("program"),
			sync_settings=data.get("sync_settings"),
		)
		return single_item_response(result, message="Blueprint template created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_sync_logs():
	try:
		fd = frappe.form_dict
		rows = blueprint_service.list_blueprint_sync_logs(
			blueprint_id=fd.get("blueprint_id"),
			template_course_id=fd.get("template_course_id"),
		)
		return success_response(data=rows)
	except Exception as exc:
		return error_response(str(exc))
