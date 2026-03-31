"""
Chuyển bảng điểm trên SIS Discipline Violation sang SIS Discipline Violation Point Version.
Chạy sau migrate khi DocType đã tồn tại; idempotent (bỏ qua vi phạm đã có ít nhất 1 phiên bản).
"""

import frappe


def execute():
	if not frappe.db.table_exists("SIS Discipline Violation Point Version"):
		return

	for vname in frappe.get_all("SIS Discipline Violation", pluck="name"):
		if frappe.db.count("SIS Discipline Violation Point Version", {"violation": vname}):
			continue
		doc = frappe.get_doc("SIS Discipline Violation", vname)
		if not (doc.student_points or doc.class_points):
			continue

		ed = frappe.utils.getdate(doc.creation) if doc.creation else frappe.utils.today()

		pv = frappe.get_doc(
			{
				"doctype": "SIS Discipline Violation Point Version",
				"violation": vname,
				"label": "Mặc định (migrate)",
				"effective_date": ed,
			}
		)
		for row in doc.student_points or []:
			pv.append(
				"student_points",
				{
					"violation_count": row.violation_count,
					"level": str(row.level or "1"),
					"points": row.points,
				},
			)
		for row in doc.class_points or []:
			pv.append(
				"class_points",
				{
					"violation_count": row.violation_count,
					"level": str(row.level or "1"),
					"points": row.points,
				},
			)
		pv.insert(ignore_permissions=True)

	frappe.db.commit()
