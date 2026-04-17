"""
Dong bo trang thai CRM Lead (buoc Enrolled) khi hoc sinh duoc gan lop Regular
(tu bang SIS Class Student + SIS Class).
"""

import frappe


def has_regular_class_assignment(crm_student_name: str) -> bool:
    """Tra ve True neu CRM Student da co it nhat mot dong SIS Class Student thuoc lop Regular."""
    if not crm_student_name:
        return False
    r = frappe.db.sql(
        """
        SELECT cs.name
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
        WHERE cs.student_id = %s
          AND (IFNULL(NULLIF(TRIM(c.class_type), ''), 'regular') = 'regular')
        LIMIT 1
        """,
        (crm_student_name,),
    )
    return bool(r)


def promote_leads_to_dang_hoc_if_class_assigned(crm_student_name: str) -> None:
    """
    Neu lead dang Enrolled + Cho xep lop va da co lop Regular thi doi sang Dang hoc.
    Ghi nhan CRM Lead Step History (van buoc Enrolled).
    """
    if not crm_student_name or not has_regular_class_assignment(crm_student_name):
        return

    # Tranh import vong pipeline <-> enrollment
    from erp.api.crm.pipeline import _log_step_change

    leads = frappe.get_all(
        "CRM Lead",
        filters={
            "linked_student": crm_student_name,
            "step": "Enrolled",
            "status": "Cho xep lop",
        },
        pluck="name",
    )
    for lead_name in leads:
        doc = frappe.get_doc("CRM Lead", lead_name)
        old_status = doc.status
        doc.status = "Dang hoc"
        doc.save(ignore_permissions=True)
        _log_step_change(lead_name, "Enrolled", "Enrolled", old_status, doc.status)
