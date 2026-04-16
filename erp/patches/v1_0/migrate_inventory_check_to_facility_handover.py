# Copyright (c) 2026, Wellspring International School and contributors
# Gộp dữ liệu kiểm kê (Inventory Check) vào bàn giao (Facility Handover) — chiều incoming

import json

import frappe


def execute():
    # Bản giao cũ trước khi có field direction: coi như outgoing
    frappe.db.sql(
        """
        UPDATE `tabERP Administrative Facility Handover`
        SET `direction` = 'outgoing'
        WHERE `direction` IS NULL OR IFNULL(`direction`, '') = ''
        """
    )

    if not frappe.db.exists("DocType", "ERP Administrative Inventory Check"):
        frappe.db.commit()
        return

    ic_names = frappe.get_all("ERP Administrative Inventory Check", pluck="name")
    for name in ic_names:
        ic = frappe.get_doc("ERP Administrative Inventory Check", name)
        dup = frappe.db.exists(
            "ERP Administrative Facility Handover",
            {
                "room": ic.room,
                "direction": "incoming",
                "responsible_user": ic.responsible_user or "",
                "sent_on": ic.submitted_on,
            },
        )
        if dup:
            continue
        fac_sn = ic.facility_snapshot
        if fac_sn is not None and not isinstance(fac_sn, str):
            fac_sn = json.dumps(fac_sn or [], ensure_ascii=False)
        it_sn = ic.it_snapshot
        if it_sn is not None and not isinstance(it_sn, str):
            it_sn = json.dumps(it_sn or [], ensure_ascii=False)
        ho = frappe.get_doc(
            {
                "doctype": "ERP Administrative Facility Handover",
                "room": ic.room,
                "direction": "incoming",
                "handover_type": "responsible_user",
                "class_id": None,
                "responsible_user": ic.responsible_user,
                "status": ic.status,
                "note": ic.note or "",
                "facility_snapshot": fac_sn or "",
                "it_snapshot": it_sn or "",
                "sent_by": ic.responsible_user,
                "sent_on": ic.submitted_on or ic.creation,
                "reviewed_by": ic.reviewed_by,
                "reviewed_on": ic.reviewed_on,
                "review_note": ic.review_note or "",
            }
        )
        ho.insert(ignore_permissions=True)
    frappe.db.commit()
