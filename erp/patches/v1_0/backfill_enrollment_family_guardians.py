# -*- coding: utf-8 -*-
"""Bu phu huynh bi thieu trong CRM Family cho cac ho so da nhap hoc truoc ban va.

Boi canh: `erp/api/crm/enrollment.py` truoc day chi dua MOT phu huynh (nguoi lien lac
chinh) tu `lead_guardians` vao CRM Family. Bo/me con lai khong co dong
`CRM Family Relationship` nao -> mat quyen xem portal, khong vao nhom chat, khong nhan
thong bao. Bug da sua o luong runtime; patch nay xu ly du lieu cu.

PHAM VI CO Y HEP — chi THEM, khong bao gio sua/xoa:
  - Chi them dong quan he cho cap (student, guardian) chua co dong CHUAN nao.
  - `access` = 1 (mac dinh khi tao moi). Cap da co dong o cho khac thi bi BO QUA hoan
    toan, nen quyen da bi thu hoi co chu y khong bao gio bi mo lai.
  - `key_person` chi bat khi hoc sinh do CHUA co nguoi lien lac chinh nao trong family
    — khong doi nguoi lien lac chinh ma van hanh da chon.
  - KHONG tao CRM Family moi: hoc sinh chua co family nao thi chi dem va bao cao, vi
    tao family la quyet dinh nghiep vu (campus, ai vao chung nhom).
  - KHONG GOP family trung. Gop la thao tac pha huy (doi family_code cua guardian +
    student, keo theo quyen portal / nhom chat / thong bao) va khong the tu dong doan
    dung family nao la that. Patch chi LIET KE cac guardian dang nam o nhieu family de
    doi van hanh ra soat tay (xem them
    erp.api.crm.family_diagnostics.guardians_in_multiple_families).

Nguon doc CHUAN: dong duoi `CRM Family.relationships` (parentfield='relationships',
family docstatus < 2). Hai ban mirror (`CRM Student.family_relationships`,
`CRM Guardian.student_relationships`) duoc dung lai bang
erp.utils.family_relationship.rebuild_* sau khi ghi.

Idempotent: chay lai khong them dong nao nua.

Chay thu truoc khi migrate (khong ghi gi):
    bench --site <site> execute \
        erp.patches.v1_0.backfill_enrollment_family_guardians.backfill \
        --kwargs "{'dry_run': 1}"
"""

import frappe

from erp.utils.family_relationship import (
	rebuild_guardian_relationship_mirror,
	rebuild_student_relationship_mirror,
)


def _canonical_rows(student=None, guardian=None):
	"""Dong quan he CHUAN kem family dang giu dong do (vi tu nhu ban chuan)."""
	if not student and not guardian:
		return []
	conds = ["fr.parentfield = 'relationships'", "f.docstatus < 2"]
	params = {}
	if student:
		conds.append("fr.student = %(student)s")
		params["student"] = student
	if guardian:
		conds.append("fr.guardian = %(guardian)s")
		params["guardian"] = guardian
	return frappe.db.sql(
		"""
		SELECT fr.parent AS family, fr.student, fr.guardian, fr.key_person, fr.access
		FROM `tabCRM Family Relationship` fr
		INNER JOIN `tabCRM Family` f ON f.name = fr.parent
		WHERE {conds}
		ORDER BY fr.parent
		""".format(conds=" AND ".join(conds)),
		params,
		as_dict=True,
	) or []


def _lead_guardian_rows(lead_name):
	"""Phu huynh khai tren lead, thu tu: nguoi lien lac chinh -> display_order -> idx."""
	return frappe.db.sql(
		"""
		SELECT lg.guardian, lg.relationship_type, lg.is_primary_contact
		FROM `tabCRM Lead Guardian` lg
		INNER JOIN `tabCRM Guardian` g ON g.name = lg.guardian
		WHERE lg.parenttype = 'CRM Lead'
		  AND lg.parent = %(lead)s
		  AND IFNULL(lg.guardian, '') != ''
		ORDER BY lg.is_primary_contact DESC, lg.display_order ASC, lg.idx ASC
		""",
		{"lead": lead_name},
		as_dict=True,
	) or []


def backfill(dry_run=False):
	"""Them dong quan he con thieu. Tra ve dict thong ke (dung cho ca bench execute)."""
	dry_run = bool(int(dry_run or 0))

	leads = frappe.db.sql(
		"""
		SELECT l.name AS lead, l.linked_student AS student
		FROM `tabCRM Lead` l
		INNER JOIN `tabCRM Student` s ON s.name = l.linked_student
		WHERE IFNULL(l.linked_student, '') != ''
		ORDER BY l.name
		""",
		as_dict=True,
	) or []

	stats = {
		"leads_scanned": len(leads),
		"rows_added": 0,
		"students_touched": 0,
		"students_without_family": 0,
		"guardians_touched": 0,
	}
	added_detail = []
	touched_guardians = set()

	for lead in leads:
		student = lead["student"]
		guardian_rows = _lead_guardian_rows(lead["lead"])
		if not guardian_rows:
			continue

		student_rows = _canonical_rows(student=student)
		families = []
		for r in student_rows:
			if r["family"] not in families:
				families.append(r["family"])
		if not families:
			# Chua co family nao -> khong tu tao (quyet dinh nghiep vu), chi dem
			stats["students_without_family"] += 1
			continue

		# Hoc sinh nam o nhieu family (du lieu cu bi tach): bu vao family DAU TIEN theo
		# thu tu docname — xac dinh, va gop family la viec lam tay.
		family_name = families[0]
		existing_pairs = {r["guardian"] for r in student_rows if r.get("guardian")}
		has_key_person = any(
			int(r.get("key_person") or 0)
			for r in student_rows
			if r["family"] == family_name
		)

		missing = [g for g in guardian_rows if g["guardian"] not in existing_pairs]
		if not missing:
			continue

		if dry_run:
			for g in missing:
				added_detail.append(f"{family_name} + {student} <- {g['guardian']}")
				stats["rows_added"] += 1
				touched_guardians.add(g["guardian"])
			stats["students_touched"] += 1
			continue

		family_doc = frappe.get_doc("CRM Family", family_name)
		for g in missing:
			key_person = 0
			if int(g.get("is_primary_contact") or 0) and not has_key_person:
				key_person = 1
				has_key_person = True
			family_doc.append(
				"relationships",
				{
					"student": student,
					"guardian": g["guardian"],
					"relationship_type": g.get("relationship_type") or "guardian",
					"key_person": key_person,
					"access": 1,
					# can_pickup phai ghi tay du doctype khai default 1: Document.append
					# khong ap default, de trong la xuong DB thanh 0.
					"can_pickup": 1,
				},
			)
			added_detail.append(f"{family_name} + {student} <- {g['guardian']}")
			stats["rows_added"] += 1
			touched_guardians.add(g["guardian"])

		family_doc.flags.ignore_validate = True
		family_doc.save(ignore_permissions=True)
		stats["students_touched"] += 1

		rebuild_student_relationship_mirror(student)
		for g in missing:
			rebuild_guardian_relationship_mirror(g["guardian"])
		frappe.db.commit()

	stats["guardians_touched"] = len(touched_guardians)

	frappe.logger().info(
		"backfill_enrollment_family_guardians: "
		+ ", ".join(f"{k}={v}" for k, v in stats.items())
		+ (" (dry_run)" if dry_run else "")
	)
	if added_detail and not dry_run:
		# Title <= 140 ky tu (gioi han CharacterLength cua Error Log)
		frappe.log_error(
			title="Da bu phu huynh thieu vao CRM Family",
			message="Cac dong quan he vua them (family + student <- guardian):\n\n"
			+ "\n".join(added_detail[:2000]),
		)
	return {"stats": stats, "added": added_detail}


def report_split_families():
	"""Liet ke guardian dang co quan he o NHIEU CRM Family (ung vien gop tay).

	KHONG sua gi. Gop family phai lam tay vi con keo theo family_code cua guardian +
	student, quyen portal, nhom chat.
	"""
	rows = frappe.db.sql(
		"""
		SELECT fr.guardian, COUNT(DISTINCT fr.parent) AS families,
		       GROUP_CONCAT(DISTINCT fr.parent ORDER BY fr.parent) AS family_list
		FROM `tabCRM Family Relationship` fr
		INNER JOIN `tabCRM Family` f ON f.name = fr.parent
		WHERE fr.parentfield = 'relationships'
		  AND f.docstatus < 2
		  AND IFNULL(fr.guardian, '') != ''
		GROUP BY fr.guardian
		HAVING families > 1
		ORDER BY families DESC, fr.guardian
		""",
		as_dict=True,
	) or []
	if rows:
		frappe.log_error(
			title="Guardian nam o nhieu CRM Family",
			message=(
				"Cac phu huynh sau dang co quan he o nhieu family — co the la family bi "
				"tach do bug enrollment cu (moi con mot family), cung co the la dung "
				"(con o hai gia dinh khac nhau). Gop PHAI lam tay:\n\n"
				+ "\n".join(f"{r['guardian']}: {r['family_list']}" for r in rows[:2000])
			),
		)
	return rows


def execute():
	backfill()
	report_split_families()
