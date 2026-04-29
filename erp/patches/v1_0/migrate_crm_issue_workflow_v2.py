import frappe


def execute():
    """Chuẩn hóa dữ liệu CRM Issue theo workflow mới."""
    _ensure_issue_defaults()
    _normalize_issue_results()
    _normalize_occurred_at_to_date()


def _ensure_issue_defaults():
    rows = frappe.get_all(
        "CRM Issue",
        fields=["name", "issue_code", "title", "priority"],
    )
    for row in rows:
        updates = {}
        if not (row.get("title") or "").strip():
            updates["title"] = (row.get("issue_code") or row.get("name") or "").strip()
        if not (row.get("priority") or "").strip():
            updates["priority"] = "Trung binh"
        if updates:
            frappe.db.set_value("CRM Issue", row["name"], updates, update_modified=False)


def _normalize_issue_results():
    mapping = {
        "Dong y nhung chua hai long": "Chua hai long",
        "Tiep tuc theo doi": "",
    }
    for old_value, new_value in mapping.items():
        frappe.db.sql(
            """
            UPDATE `tabCRM Issue`
            SET result = %(new_value)s
            WHERE result = %(old_value)s
            """,
            {"old_value": old_value, "new_value": new_value},
        )


def _normalize_occurred_at_to_date():
    rows = frappe.get_all("CRM Issue", fields=["name", "occurred_at"])
    for row in rows:
        occurred_at = row.get("occurred_at")
        if not occurred_at:
            continue
        date_value = str(occurred_at)[:10]
        if date_value and date_value != str(occurred_at):
            frappe.db.set_value(
                "CRM Issue",
                row["name"],
                "occurred_at",
                date_value,
                update_modified=False,
            )
