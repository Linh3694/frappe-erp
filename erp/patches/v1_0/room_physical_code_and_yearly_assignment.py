# Copyright (c) 2026 Wellspring — backfill physical_code, room_number; gợi ý cần review

import frappe


def execute():
    """Sinh physical_code từ title_vn + building short_title nếu thiếu."""
    rooms = frappe.get_all(
        "ERP Administrative Room",
        fields=["name", "title_vn", "building_id", "campus_id"],
        filters={},
    )
    for r in rooms:
        name = r.name
        title = (r.title_vn or "").strip()
        bid = r.building_id
        if not bid:
            continue
        st = frappe.db.get_value("ERP Administrative Building", bid, "short_title") or ""
        if not st or not title:
            continue
        # Coi title_vn cũ là số phòng nếu ngắn (vd 303, 1A2)
        pc = f"{st}.{title.replace(' ', '')}"
        frappe.db.set_value(
            "ERP Administrative Room",
            name,
            {
                "physical_code": pc[:140],
                "room_number": title[:50],
                "needs_review": 1,
            },
            update_modified=False,
        )
    frappe.db.commit()
