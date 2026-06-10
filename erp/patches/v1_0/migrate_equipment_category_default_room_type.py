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

    default_room_type = "classroom_room"
    default_room_type_label = "Phòng lớp học"
    changed = 0
    for row in categories:
        name = row.get("name")
        if not name:
            continue

        doc = frappe.get_doc("ERP Administrative Facility Equipment Category", name)
        rows = doc.get("applicable_room_types") or []
        dirty = not (
            len(rows) == 1
            and (rows[0].room_type or "").strip() == default_room_type
            and (rows[0].room_type_label or "").strip() == default_room_type_label
        )

        if dirty:
            doc.set(
                "applicable_room_types",
                [
                    {
                        "room_type": default_room_type,
                        "room_type_label": default_room_type_label,
                    }
                ],
            )
            doc.save(ignore_permissions=True)
            changed += 1

    if changed:
        frappe.db.commit()
