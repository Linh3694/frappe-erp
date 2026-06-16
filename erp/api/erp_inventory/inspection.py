# Copyright (c) 2026, Wellspring International School
# API kiểm tra thiết bị IT

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from erp.utils.api_response import error_response, not_found_response, validation_error_response
from erp.api.erp_inventory.inventory_helpers import (
	device_doc_to_fe,
	parse_request_data,
	read_api_param,
	normalize_api_param,
	normalize_device_type,
	datetime_to_iso,
	resolve_user_link,
	user_to_fe,
)
from erp.api.erp_inventory.device import _resolve_device_name
from erp.api.erp_inventory.handover_file import _ensure_inventory_folder


def _read_inspection_id(inspection_id=None):
	"""Đọc inspection_id từ kwargs / query / JSON body."""
	data = parse_request_data()
	resolved = read_api_param("inspection_id", "inspectionId", fallback=inspection_id)
	if not resolved and data:
		resolved = normalize_api_param(data.get("inspection_id") or data.get("inspectionId"))
	return resolved


def _resolve_inspection_device_id(device_id, device_type=None):
	raw = normalize_api_param(device_id)
	if not raw:
		return None
	return _resolve_device_name(raw, normalize_device_type(device_type) or None)


SECTION_DEFAULTS = {
	"externalCondition": {"overallCondition": "", "notes": ""},
	"cpu": {"performance": "", "temperature": "", "overallCondition": "", "notes": ""},
	"ram": {"consumption": "", "overallCondition": "", "notes": ""},
	"storage": {"remainingCapacity": "", "overallCondition": "", "notes": ""},
	"battery": {"capacity": "", "performance": "", "chargeCycles": "", "overallCondition": "", "notes": ""},
	"display": {"colorAndBrightness": "", "overallCondition": "", "notes": ""},
	"connectivity": {"overallCondition": "", "notes": ""},
	"software": {"overallCondition": "", "notes": ""},
}


def _sections_to_results(sections) -> dict:
	results = {k: dict(v) for k, v in SECTION_DEFAULTS.items()}
	for row in sections or []:
		key = row.section_key
		if key not in results:
			results[key] = {}
		entry = results[key]
		if row.overall_condition is not None:
			entry["overallCondition"] = row.overall_condition
		if row.notes is not None:
			entry["notes"] = row.notes
		if row.metric_a is not None:
			if key == "cpu":
				entry["performance"] = row.metric_a
			elif key == "ram":
				entry["consumption"] = row.metric_a
			elif key == "storage":
				entry["remainingCapacity"] = row.metric_a
			elif key == "battery":
				entry["capacity"] = row.metric_a
			elif key == "display":
				entry["colorAndBrightness"] = row.metric_a
		if row.metric_b is not None:
			if key == "cpu":
				entry["temperature"] = row.metric_b
			elif key == "battery":
				entry["performance"] = row.metric_b
		if row.metric_c is not None and key == "battery":
			entry["chargeCycles"] = row.metric_c
	return results


def _results_to_sections(results: dict):
	rows = []
	if not isinstance(results, dict):
		return rows
	for key, val in results.items():
		if not isinstance(val, dict):
			continue
		row = {"section_key": key, "overall_condition": val.get("overallCondition") or "", "notes": val.get("notes") or ""}
		if key == "cpu":
			row["metric_a"] = val.get("performance") or ""
			row["metric_b"] = val.get("temperature") or ""
		elif key == "ram":
			row["metric_a"] = val.get("consumption") or ""
		elif key == "storage":
			row["metric_a"] = val.get("remainingCapacity") or ""
		elif key == "battery":
			row["metric_a"] = val.get("capacity") or ""
			row["metric_b"] = val.get("performance") or ""
			row["metric_c"] = val.get("chargeCycles") or ""
		elif key == "display":
			row["metric_a"] = val.get("colorAndBrightness") or ""
		rows.append(row)
	return rows


def inspection_to_fe(doc, populate_device=True):
	device_data = None
	if populate_device and doc.device and frappe.db.exists("ERP Inventory Device", doc.device):
		device_data = device_doc_to_fe(frappe.get_doc("ERP Inventory Device", doc.device), include_history=False)
	inspector_name = ""
	if doc.inspector and frappe.db.exists("User", doc.inspector):
		inspector_name = frappe.db.get_value("User", doc.inspector, "full_name") or doc.inspector
	return {
		"_id": doc.name,
		"deviceId": doc.device,
		"deviceType": doc.device_type,
		"inspectorId": doc.inspector,
		"inspectorName": inspector_name,
		"inspectionDate": datetime_to_iso(doc.inspection_date),
		"results": _sections_to_results(doc.sections),
		"overallAssessment": doc.overall_assessment or "",
		"passed": bool(doc.passed),
		"recommendations": doc.recommendations or "",
		"technicalConclusion": doc.technical_conclusion or "",
		"followUpRecommendation": doc.follow_up_recommendation or "",
		"report": {
			"fileName": (doc.report_file_url or "").split("/")[-1] if doc.report_file_url else "",
			"filePath": doc.report_file_url or "",
			"createdAt": datetime_to_iso(doc.modified),
		},
		"deviceId_populated": device_data,
	}


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_inspections(deviceId=None, inspectorId=None, startDate=None, endDate=None):
	try:
		filters = {}
		device_id = read_api_param("deviceId", "device_id", fallback=deviceId)
		if device_id:
			resolved = _resolve_inspection_device_id(device_id)
			if resolved:
				filters["device"] = resolved
		inspector_id = read_api_param("inspectorId", "inspector_id", fallback=inspectorId)
		if inspector_id:
			filters["inspector"] = resolve_user_link(inspector_id) or inspector_id
		start_date = read_api_param("startDate", "start_date", fallback=startDate)
		end_date = read_api_param("endDate", "end_date", fallback=endDate)
		if start_date and end_date:
			filters["inspection_date"] = ["between", [start_date, end_date]]

		names = frappe.get_all("ERP Inventory Inspection", filters=filters, pluck="name", order_by="inspection_date desc")
		data = []
		for name in names:
			doc = frappe.get_doc("ERP Inventory Inspection", name)
			data.append(inspection_to_fe(doc))
		return {"data": data}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.get_inspections")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_inspection_by_id(inspection_id=None):
	try:
		inspection_id = _read_inspection_id(inspection_id)
		if not inspection_id:
			return validation_error_response(_("inspection_id là bắt buộc"), {"inspection_id": ["required"]})
		if not frappe.db.exists("ERP Inventory Inspection", inspection_id):
			return not_found_response(_("Inspection not found"))
		doc = frappe.get_doc("ERP Inventory Inspection", inspection_id)
		return {"data": inspection_to_fe(doc)}
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_latest_inspection_by_device(device_id=None):
	try:
		device_id = read_api_param("device_id", "deviceId", fallback=device_id)
		if not device_id:
			data = parse_request_data()
			device_id = normalize_api_param(data.get("device_id") or data.get("deviceId"))
		resolved_device = _resolve_inspection_device_id(device_id)
		if not resolved_device:
			return {"message": "No inspection found", "data": None}

		rows = frappe.get_all(
			"ERP Inventory Inspection",
			filters={"device": resolved_device},
			fields=["name"],
			order_by="inspection_date desc",
			limit=1,
		)
		if not rows:
			return {"message": "No inspection found", "data": None}
		doc = frappe.get_doc("ERP Inventory Inspection", rows[0].name)
		return {"message": "OK", "data": inspection_to_fe(doc)}
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def create_inspection():
	try:
		data = parse_request_data()
		device_id = normalize_api_param(data.get("deviceId") or data.get("device_id"))
		device_type = normalize_device_type(data.get("deviceType") or data.get("device_type"))
		if not device_id:
			return validation_error_response(_("deviceId required"), {"deviceId": ["required"]})

		resolved_device = _resolve_inspection_device_id(device_id, device_type)
		if not resolved_device:
			return validation_error_response(_("Không tìm thấy thiết bị"), {"deviceId": ["not_found"]})

		if not device_type:
			device_type = frappe.db.get_value("ERP Inventory Device", resolved_device, "device_type") or ""

		inspector = resolve_user_link(frappe.session.user) or frappe.session.user
		if data.get("inspectorId"):
			inspector = resolve_user_link(data.get("inspectorId")) or inspector

		doc = frappe.get_doc(
			{
				"doctype": "ERP Inventory Inspection",
				"device": resolved_device,
				"device_type": device_type,
				"inspector": inspector,
				"inspection_date": data.get("inspectionDate") or now_datetime(),
				"overall_assessment": data.get("overallAssessment") or "",
				"passed": 1 if data.get("passed", True) else 0,
				"recommendations": data.get("recommendations") or "",
				"technical_conclusion": data.get("technicalConclusion") or "",
				"follow_up_recommendation": data.get("followUpRecommendation") or "",
			}
		)
		for row in _results_to_sections(data.get("results") or {}):
			doc.append("sections", row)
		doc.insert(ignore_permissions=False)
		frappe.db.commit()
		return {"data": inspection_to_fe(doc)}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.create_inspection")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def update_inspection(inspection_id=None):
	try:
		data = parse_request_data()
		inspection_id = _read_inspection_id(inspection_id)
		if not inspection_id:
			return validation_error_response(_("inspection_id là bắt buộc"), {"inspection_id": ["required"]})
		if not frappe.db.exists("ERP Inventory Inspection", inspection_id):
			return not_found_response(_("Inspection not found"))
		doc = frappe.get_doc("ERP Inventory Inspection", inspection_id)
		for fn in (
			"overall_assessment",
			"recommendations",
			"technical_conclusion",
			"follow_up_recommendation",
		):
			key = fn
			camel = "".join(w[:1].upper() + w[1:] for w in fn.split("_"))
			if camel in data:
				doc.set(fn, data.get(camel))
			elif key in data:
				doc.set(fn, data.get(key))
		if "passed" in data:
			doc.passed = 1 if data.get("passed") else 0
		if "results" in data:
			doc.sections = []
			for row in _results_to_sections(data.get("results") or {}):
				doc.append("sections", row)
		doc.save(ignore_permissions=False)
		frappe.db.commit()
		return {"data": inspection_to_fe(doc)}
	except Exception as e:
		frappe.db.rollback()
		return error_response(str(e))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def delete_inspection(inspection_id=None):
	try:
		inspection_id = _read_inspection_id(inspection_id)
		if not inspection_id:
			return validation_error_response(_("inspection_id là bắt buộc"), {"inspection_id": ["required"]})
		if not frappe.db.exists("ERP Inventory Inspection", inspection_id):
			return not_found_response(_("Inspection not found"))
		frappe.delete_doc("ERP Inventory Inspection", inspection_id, ignore_permissions=False)
		frappe.db.commit()
		return {"message": "Inspection deleted"}
	except Exception as e:
		frappe.db.rollback()
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def upload_inspection_report():
	"""Upload báo cáo kiểm tra — multipart file."""
	try:
		files = frappe.request.files
		if not files or "file" not in files:
			return validation_error_response(_("Không có file"), {"file": ["required"]})
		data = frappe.form_dict
		inspect_id = data.get("inspectId") or data.get("inspection_id")
		if not inspect_id or not frappe.db.exists("ERP Inventory Inspection", inspect_id):
			return not_found_response(_("Inspection not found"))

		_ensure_inventory_folder("reports")

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": files["file"].filename,
				"content": files["file"].stream.read(),
				"is_private": 0,
				"folder": "Home/inventory/reports",
				"attached_to_doctype": "ERP Inventory Inspection",
				"attached_to_name": inspect_id,
			}
		)
		file_doc.save(ignore_permissions=True)
		inspection = frappe.get_doc("ERP Inventory Inspection", inspect_id)
		inspection.report_file_url = file_doc.file_url
		inspection.report_file = file_doc.file_url
		inspection.save(ignore_permissions=True)
		frappe.db.commit()
		return {"message": "Upload thành công", "fileUrl": file_doc.file_url}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.upload_inspection_report")
		return error_response(str(e))
