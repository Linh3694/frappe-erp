# Copyright (c) 2026, Wellspring International School
# Endpoint danh sách quốc gia cho dropdown Quốc tịch (lưu tên Anh, hiển thị nhãn tiếng Việt).

import frappe

from erp.utils.api_response import list_response
from erp.utils.country import get_vi_label
from erp.utils.search import strip_accents


@frappe.whitelist()
def list_countries():
	"""Trả [{ value, label, code }] cho dropdown.

	- value: tên record Country (tiếng Anh) — giá trị lưu xuống DB.
	- label: nhãn tiếng Việt (fallback tên Anh nếu chưa có trong COUNTRY_VI_LABELS).
	- code : mã ISO 2 ký tự (vd "vn").

	"Vietnam" ghim lên đầu; phần còn lại sắp theo nhãn tiếng Việt (bỏ dấu).
	"""
	countries = frappe.get_all("Country", fields=["name", "code"])

	out = [
		{
			"value": c.get("name"),
			"label": get_vi_label(c.get("name")),
			"code": (c.get("code") or "").strip().lower(),
		}
		for c in countries
		if c.get("name")
	]

	out.sort(key=lambda x: (x["value"] != "Vietnam", strip_accents(x["label"])))
	return list_response(out)
