import frappe


@frappe.whitelist()
def seed_class_log_scores(education_stage=None):
    """Seed a minimal set of Class Log Score options for quick testing."""
    try:
        defaults = {
            "homework": [
                ("Hoàn thành", 1.0),
                ("Chưa hoàn thành", 0.0),
            ],
            "behavior": [
                ("Đúng mực", 1.0),
                ("Vi phạm", -1.0),
            ],
            "participation": [
                ("Tham gia tích cực", 1.0),
                ("Không tham gia", 0.0),
            ],
            "issue": [
                ("Nói chuyện riêng", -0.5),
                ("Không mang đồ dùng", -0.5),
            ],
            "top_performance": [
                ("Học sinh nổi bật", 1.5),
            ]
        }

        for t, arr in defaults.items():
            for title, value in arr:
                exists = frappe.get_all(
                    "SIS Class Log Score",
                    filters={"type": t, "title_vn": title, "education_stage": education_stage},
                    fields=["name"], limit=1
                )
                if not exists:
                    doc = frappe.get_doc({
                        "doctype": "SIS Class Log Score",
                        "type": t,
                        "title_vn": title,
                        "value": value,
                        "education_stage": education_stage,
                        "is_active": 1
                    })
                    doc.insert()
        frappe.db.commit()
        return {"success": True}
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"seed_class_log_scores error: {str(e)}")
        return {"success": False, "message": str(e)}


