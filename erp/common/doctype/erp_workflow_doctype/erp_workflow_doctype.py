# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ERPWorkflowDoctype(Document):
    def validate(self):
        # state_field mặc định
        if not self.state_field:
            self.state_field = "workflow_state"


# ---------------------------------------------------------------------------
# Helper tra cứu registry (dùng bởi engine generic / API)
# ---------------------------------------------------------------------------

WF_DOCTYPE = "ERP Workflow Doctype"


def get_registry(target_doctype):
    """Trả dict cấu hình registry của 1 doctype (hoặc None nếu chưa bật)."""
    if not target_doctype:
        return None
    name = frappe.db.get_value(WF_DOCTYPE, {"target_doctype": target_doctype, "is_enabled": 1}, "name")
    if not name:
        return None
    row = frappe.db.get_value(
        WF_DOCTYPE,
        name,
        ["target_doctype", "requester_field", "title_field", "state_field", "owner_editor_fields", "label", "icon", "module"],
        as_dict=True,
    )
    if row:
        row["owner_editor_fields"] = [
            x.strip() for x in (row.get("owner_editor_fields") or "").replace("\n", ",").split(",") if x.strip()
        ]
    return row


def enabled_doctypes():
    """Danh sách target_doctype đã bật workflow."""
    return frappe.get_all(WF_DOCTYPE, filters={"is_enabled": 1}, pluck="target_doctype")
