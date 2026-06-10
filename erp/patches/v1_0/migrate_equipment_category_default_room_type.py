# Copyright (c) 2026 Wellspring

import frappe


def execute():
    """
    Backfill dữ liệu cũ:
    - Danh mục thiết bị chưa có applicable_room_types
    - Mặc định gán về classroom_room (Phòng lớp học)
    """
    categories = frappe.get_all(
        "ERP Administrative Facility Equipment Category",
        fields=["name"],
        filters={},
    )
    if not categories:
        return

    changed = 0
    for row in categories:
        name = row.get("name")
        if not name:
            continue

        exists = frappe.db.exists(
            "ERP Administrative Facility Equipment Category Room Type",
            {"parent": name, "parenttype": "ERP Administrative Facility Equipment Category"},
        )
        if exists:
            continue

        doc = frappe.get_doc("ERP Administrative Facility Equipment Category", name)
        doc.append("applicable_room_types", {"room_type": "classroom_room"})
        doc.save(ignore_permissions=True)
        changed += 1

    if changed:
        frappe.db.commit()
