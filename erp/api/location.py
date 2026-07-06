# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt
#
# API danh mục Địa giới hành chính VN (2 cấp từ 01/07/2025):
#   ERP Province (Tỉnh/Thành phố) -> ERP Ward (Xã/Phường/Thị trấn).
# Dùng cho dropdown địa chỉ (CRM Lead, hồ sơ HS...) và hub cấu hình "Cấu hình Tỉnh/Xã".

import frappe

from erp.utils.api_response import (
	success_response,
	error_response,
	list_response,
	single_item_response,
)
from erp.utils import vn_location


# Các cặp field địa chỉ trên CRM Lead cần migrate string -> Link.
_CRM_LEAD_ADDRESS_PAIRS = [
	("registered_address_province", "registered_address_ward"),
	("current_address_province", "current_address_ward"),
]


# ---------------------------------------------------------------------------
# Đọc danh mục (dropdown + trang cấu hình)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def list_provinces(search=None, only_active=1):
	"""Danh sách Tỉnh/Thành phố (sắp theo mã)."""
	try:
		filters = {}
		if str(only_active) in ("1", "true", "True"):
			filters["is_active"] = 1
		or_filters = None
		if search:
			or_filters = [
				["province_name", "like", f"%{search}%"],
				["province_code", "like", f"%{search}%"],
			]
		rows = frappe.get_all(
			"ERP Province",
			fields=["name", "province_code", "province_name", "province_type", "is_active"],
			filters=filters,
			or_filters=or_filters,
			order_by="province_code asc",
			limit_page_length=0,
		)
		return list_response(rows, "Provinces fetched successfully")
	except Exception as e:
		frappe.log_error(message=frappe.get_traceback(), title="list_provinces failed")
		return error_response(f"Error fetching provinces: {str(e)}")


@frappe.whitelist(allow_guest=False)
def list_wards(province=None, search=None, only_active=1, limit=None):
	"""Danh sách Xã/Phường; lọc theo tỉnh (bắt buộc cho dropdown phụ thuộc)."""
	try:
		filters = {}
		if province:
			filters["province"] = province
		if str(only_active) in ("1", "true", "True"):
			filters["is_active"] = 1
		or_filters = None
		if search:
			or_filters = [
				["ward_name", "like", f"%{search}%"],
				["ward_code", "like", f"%{search}%"],
			]
		rows = frappe.get_all(
			"ERP Ward",
			fields=[
				"name",
				"ward_code",
				"ward_name",
				"ward_type",
				"province",
				"province_name",
				"is_active",
			],
			filters=filters,
			or_filters=or_filters,
			order_by="ward_name asc",
			limit_page_length=int(limit) if limit else 0,
		)
		return list_response(rows, "Wards fetched successfully")
	except Exception as e:
		frappe.log_error(message=frappe.get_traceback(), title="list_wards failed")
		return error_response(f"Error fetching wards: {str(e)}")


@frappe.whitelist(allow_guest=False)
def resolve_names(province=None, ward=None):
	"""Mã -> tên hiển thị (dùng khi cần đổ nhãn cho giá trị đã lưu)."""
	out = {"province_name": None, "ward_name": None}
	try:
		if province and frappe.db.exists("ERP Province", province):
			out["province_name"] = frappe.db.get_value("ERP Province", province, "province_name")
		if ward and frappe.db.exists("ERP Ward", ward):
			out["ward_name"] = frappe.db.get_value("ERP Ward", ward, "ward_name")
		return success_response(out)
	except Exception as e:
		return error_response(str(e))


# ---------------------------------------------------------------------------
# CRUD cho trang cấu hình
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def save_province(data):
	"""Tạo/cập nhật một Tỉnh/Thành phố."""
	try:
		payload = frappe.parse_json(data) if isinstance(data, str) else data
		name = payload.get("name")
		if name and frappe.db.exists("ERP Province", name):
			doc = frappe.get_doc("ERP Province", name)
			doc.update(
				{
					"province_name": payload.get("province_name"),
					"province_type": payload.get("province_type"),
					"is_active": payload.get("is_active", 1),
				}
			)
		else:
			doc = frappe.get_doc(
				{
					"doctype": "ERP Province",
					"province_code": payload.get("province_code"),
					"province_name": payload.get("province_name"),
					"province_type": payload.get("province_type"),
					"is_active": payload.get("is_active", 1),
				}
			)
		doc.save()
		vn_location.clear_cache()
		return single_item_response(doc.as_dict(), "Province saved")
	except frappe.exceptions.ValidationError as e:
		return error_response(str(e), code="VALIDATION_ERROR")
	except Exception as e:
		frappe.log_error(message=frappe.get_traceback(), title="save_province failed")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_province(name):
	"""Xoá một Tỉnh (chặn nếu còn Xã trực thuộc)."""
	try:
		count = frappe.db.count("ERP Ward", {"province": name})
		if count:
			return error_response(
				f"Không thể xoá: còn {count} Xã/Phường trực thuộc tỉnh này",
				code="HAS_CHILDREN",
			)
		frappe.delete_doc("ERP Province", name)
		vn_location.clear_cache()
		return success_response(message="Province deleted")
	except Exception as e:
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def save_ward(data):
	"""Tạo/cập nhật một Xã/Phường/Thị trấn."""
	try:
		payload = frappe.parse_json(data) if isinstance(data, str) else data
		name = payload.get("name")
		if name and frappe.db.exists("ERP Ward", name):
			doc = frappe.get_doc("ERP Ward", name)
			doc.update(
				{
					"ward_name": payload.get("ward_name"),
					"province": payload.get("province"),
					"ward_type": payload.get("ward_type"),
					"is_active": payload.get("is_active", 1),
				}
			)
		else:
			doc = frappe.get_doc(
				{
					"doctype": "ERP Ward",
					"ward_code": payload.get("ward_code"),
					"ward_name": payload.get("ward_name"),
					"province": payload.get("province"),
					"ward_type": payload.get("ward_type"),
					"is_active": payload.get("is_active", 1),
				}
			)
		doc.save()
		vn_location.clear_cache()
		return single_item_response(doc.as_dict(), "Ward saved")
	except frappe.exceptions.ValidationError as e:
		return error_response(str(e), code="VALIDATION_ERROR")
	except Exception as e:
		frappe.log_error(message=frappe.get_traceback(), title="save_ward failed")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def delete_ward(name):
	"""Xoá một Xã/Phường."""
	try:
		frappe.delete_doc("ERP Ward", name)
		vn_location.clear_cache()
		return success_response(message="Ward deleted")
	except Exception as e:
		return error_response(str(e))


# ---------------------------------------------------------------------------
# Nhập danh mục hàng loạt (seed từ file chuẩn 01/07/2025)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def import_provinces(rows):
	"""Upsert danh sách Tỉnh. rows = [{province_code, province_name, province_type?}].

	Idempotent theo province_code. Trả về số tạo mới / cập nhật.
	"""
	try:
		items = frappe.parse_json(rows) if isinstance(rows, str) else rows
		created = updated = 0
		errors = []
		for r in items:
			code = (r.get("province_code") or "").strip()
			name = (r.get("province_name") or "").strip()
			if not code or not name:
				errors.append({"row": r, "error": "Thiếu mã hoặc tên tỉnh"})
				continue
			try:
				if frappe.db.exists("ERP Province", code):
					doc = frappe.get_doc("ERP Province", code)
					doc.province_name = name
					if r.get("province_type"):
						doc.province_type = r.get("province_type")
					doc.save(ignore_permissions=True)
					updated += 1
				else:
					frappe.get_doc(
						{
							"doctype": "ERP Province",
							"province_code": code,
							"province_name": name,
							"province_type": r.get("province_type"),
							"is_active": 1,
						}
					).insert(ignore_permissions=True)
					created += 1
			except Exception as row_err:
				errors.append({"row": r, "error": str(row_err)})
		frappe.db.commit()
		vn_location.clear_cache()
		return success_response(
			{"created": created, "updated": updated, "errors": errors},
			message=f"Import Tỉnh: {created} mới, {updated} cập nhật, {len(errors)} lỗi",
		)
	except Exception as e:
		frappe.log_error(message=frappe.get_traceback(), title="import_provinces failed")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def reconcile_crm_lead_addresses(commit=0, blank_unmatched=0, limit=None):
	"""Migrate string -> Link cho địa chỉ CRM Lead (chạy SAU khi đã seed danh mục).

	Đối chiếu chuỗi tự do hiện có trong các cột địa chỉ với ERP Province/ERP Ward:
	  - Tỉnh khớp  -> ghi mã tỉnh + tên.
	  - Xã khớp trong tỉnh đó -> ghi mã xã + tên.
	Tham số:
	  - commit=0 (mặc định): DRY-RUN, không ghi gì, chỉ trả về thống kê + mẫu chưa khớp.
	  - commit=1: ghi giá trị đã khớp.
	  - blank_unmatched=1: đồng thời xoá rỗng các giá trị KHÔNG khớp (dọn để tránh
	    LinkValidationError khi lead được lưu về sau). Chỉ dùng ở lần dọn cuối.

	An toàn: idempotent; giá trị đã là mã hợp lệ sẽ bỏ qua. KHÔNG đăng ký trong
	patches.txt để tránh tự chạy trước khi danh mục được seed (sẽ xoá nhầm dữ liệu).
	"""
	do_commit = str(commit) in ("1", "true", "True")
	do_blank = str(blank_unmatched) in ("1", "true", "True")
	vn_location.clear_cache()

	stats = {
		"leads_scanned": 0,
		"province_matched": 0,
		"ward_matched": 0,
		"province_unmatched": 0,
		"ward_unmatched": 0,
		"blanked": 0,
	}
	unmatched_samples = []

	fields = ["name"]
	for pf, wf in _CRM_LEAD_ADDRESS_PAIRS:
		fields += [pf, wf]

	leads = frappe.get_all(
		"CRM Lead",
		fields=fields,
		limit_page_length=int(limit) if limit else 0,
	)

	for lead in leads:
		stats["leads_scanned"] += 1
		updates = {}
		for pf, wf in _CRM_LEAD_ADDRESS_PAIRS:
			raw_prov = (lead.get(pf) or "").strip()
			raw_ward = (lead.get(wf) or "").strip()

			prov_code = None
			if raw_prov:
				# đã là mã hợp lệ?
				if frappe.db.exists("ERP Province", raw_prov):
					prov_code = raw_prov
				else:
					prov_code = vn_location.resolve_province_code(raw_prov)
				if prov_code:
					stats["province_matched"] += 1
					if prov_code != raw_prov:
						updates[pf] = prov_code
						updates[pf + "_name"] = frappe.db.get_value(
							"ERP Province", prov_code, "province_name"
						)
				else:
					stats["province_unmatched"] += 1
					if len(unmatched_samples) < 100:
						unmatched_samples.append(
							{"lead": lead["name"], "field": pf, "value": raw_prov}
						)
					if do_blank:
						updates[pf] = None
						updates[pf + "_name"] = None
						stats["blanked"] += 1

			if raw_ward:
				ward_code = None
				if frappe.db.exists("ERP Ward", raw_ward):
					ward_code = raw_ward
				elif prov_code:
					ward_code = vn_location.resolve_ward_code(raw_ward, prov_code)
				if ward_code:
					stats["ward_matched"] += 1
					if ward_code != raw_ward:
						updates[wf] = ward_code
						updates[wf + "_name"] = frappe.db.get_value(
							"ERP Ward", ward_code, "ward_name"
						)
				else:
					stats["ward_unmatched"] += 1
					if len(unmatched_samples) < 100:
						unmatched_samples.append(
							{"lead": lead["name"], "field": wf, "value": raw_ward}
						)
					if do_blank:
						updates[wf] = None
						updates[wf + "_name"] = None
						stats["blanked"] += 1

		if updates and do_commit:
			frappe.db.set_value("CRM Lead", lead["name"], updates, update_modified=False)

	if do_commit:
		frappe.db.commit()

	msg = (
		("ĐÃ GHI. " if do_commit else "DRY-RUN (chưa ghi). ")
		+ f"Tỉnh khớp {stats['province_matched']}/"
		+ f"{stats['province_matched'] + stats['province_unmatched']}, "
		+ f"Xã khớp {stats['ward_matched']}/"
		+ f"{stats['ward_matched'] + stats['ward_unmatched']}."
	)
	return success_response(
		{"stats": stats, "unmatched_samples": unmatched_samples},
		message=msg,
	)


@frappe.whitelist(allow_guest=False)
def import_wards(rows):
	"""Upsert danh sách Xã. rows = [{ward_code, ward_name, province, ward_type?}].

	`province` là mã tỉnh (name ERP Province). Idempotent theo ward_code.
	"""
	try:
		items = frappe.parse_json(rows) if isinstance(rows, str) else rows
		created = updated = 0
		errors = []
		for r in items:
			code = (r.get("ward_code") or "").strip()
			name = (r.get("ward_name") or "").strip()
			province = (r.get("province") or "").strip()
			if not code or not name or not province:
				errors.append({"row": r, "error": "Thiếu mã/tên xã hoặc mã tỉnh"})
				continue
			if not frappe.db.exists("ERP Province", province):
				errors.append({"row": r, "error": f"Tỉnh không tồn tại: {province}"})
				continue
			try:
				if frappe.db.exists("ERP Ward", code):
					doc = frappe.get_doc("ERP Ward", code)
					doc.ward_name = name
					doc.province = province
					if r.get("ward_type"):
						doc.ward_type = r.get("ward_type")
					doc.save(ignore_permissions=True)
					updated += 1
				else:
					frappe.get_doc(
						{
							"doctype": "ERP Ward",
							"ward_code": code,
							"ward_name": name,
							"province": province,
							"ward_type": r.get("ward_type"),
							"is_active": 1,
						}
					).insert(ignore_permissions=True)
					created += 1
			except Exception as row_err:
				errors.append({"row": r, "error": str(row_err)})
		frappe.db.commit()
		vn_location.clear_cache()
		return success_response(
			{"created": created, "updated": updated, "errors": errors},
			message=f"Import Xã: {created} mới, {updated} cập nhật, {len(errors)} lỗi",
		)
	except Exception as e:
		frappe.log_error(message=frappe.get_traceback(), title="import_wards failed")
		return error_response(str(e))
