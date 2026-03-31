"""
Sửa báo cáo bị kẹt ở L2: all_sections_l2_approved = 1 nhưng approval_status chưa promote.
Nguyên nhân: approve_class_reports L2 per-subject không set approval_status sau khi counters đủ.

Chạy: bench --site {site} execute erp.patches.v1_0.fix_stuck_l2_approval_status.execute
"""
import frappe


def execute():
    stuck = frappe.get_all(
        "SIS Student Report Card",
        filters={
            "all_sections_l2_approved": 1,
            "approval_status": ["not in", ["level_2_approved", "reviewed", "published"]],
        },
        fields=["name", "approval_status", "template_id", "class_id", "student_id"],
    )

    if not stuck:
        print("Không có bản ghi nào bị kẹt.")
        return

    print(f"Tìm thấy {len(stuck)} bản ghi bị kẹt. Đang sửa...")

    for r in stuck:
        frappe.db.set_value(
            "SIS Student Report Card",
            r.name,
            {"approval_status": "level_2_approved"},
            update_modified=True,
        )
        print(f"  ✓ {r.name} ({r.student_id}): {r.approval_status} → level_2_approved")

    frappe.db.commit()
    print(f"Hoàn tất. Đã sửa {len(stuck)} bản ghi.")
