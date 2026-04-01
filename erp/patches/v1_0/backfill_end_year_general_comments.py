"""
Phiếu khám cuối năm: copy nhận xét chung từ 4 field cũ (dùng chung tên với đầu năm)
sang end_comment_* sau khi migrate schema.
"""

import frappe


def execute():
	if not frappe.db.table_exists("SIS Student Health Checkup"):
		return
	if not frappe.db.has_column("SIS Student Health Checkup", "end_comment_height"):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, disease_condition, health_classification, doctor_recommendation, reference_notes,
			end_comment_height, end_comment_weight, end_comment_bmi, end_comment_eye
		FROM `tabSIS Student Health Checkup`
		WHERE checkup_phase = 'end'
		""",
		as_dict=True,
	)
	for r in rows:
		upd = {}
		if not (r.get("end_comment_height") or "").strip() and (r.get("disease_condition") or "").strip():
			upd["end_comment_height"] = r.get("disease_condition")
		if not (r.get("end_comment_weight") or "").strip() and (r.get("health_classification") or "").strip():
			upd["end_comment_weight"] = r.get("health_classification")
		if not (r.get("end_comment_bmi") or "").strip() and (r.get("doctor_recommendation") or "").strip():
			upd["end_comment_bmi"] = r.get("doctor_recommendation")
		if not (r.get("end_comment_eye") or "").strip() and (r.get("reference_notes") or "").strip():
			upd["end_comment_eye"] = r.get("reference_notes")
		if upd:
			frappe.db.set_value("SIS Student Health Checkup", r["name"], upd, update_modified=False)
	frappe.db.commit()
