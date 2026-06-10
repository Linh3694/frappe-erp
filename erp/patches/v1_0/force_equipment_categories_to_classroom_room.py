# Copyright (c) 2026 Wellspring

import frappe


def execute():
    """
    Dữ liệu cũ: ép toàn bộ danh mục thiết bị hiện có về "Phòng lớp học".
    - Ghi đè child table applicable_room_types thành đúng 1 dòng classroom_room.
    - Đảm bảo có room_type_label để đồng bộ hiển thị.
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

        doc = frappe.get_doc("ERP Administrative Facility Equipment Category", name)
        doc.set("applicable_room_types", [])
        doc.append(
            "applicable_room_types",
            {
                "room_type": "classroom_room",
                "room_type_label": "Phòng lớp học",
            },
        )
        doc.save(ignore_permissions=True)
        changed += 1

    if changed:
        frappe.db.commit()
