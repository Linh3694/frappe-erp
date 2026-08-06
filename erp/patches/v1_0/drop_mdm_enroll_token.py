"""Gỡ `MDM Enroll Token` sau khi chuyển sang mô hình check-in → chờ duyệt.

Xóa file DocType khỏi app không tự xóa bản ghi trên site: `bench migrate` chỉ
thêm và sửa, không bao giờ tự xóa DocType (đúng — nếu không thì một lần checkout
nhầm nhánh là mất bảng dữ liệu). Nên phải xóa tường minh ở đây.

Token nhúng per-device không còn tồn tại trong luồng mới: MSI giống hệt nhau
trên mọi máy, danh tính chỉ sinh ra khi admin bấm Duyệt.
"""

import frappe


def execute():
    _drop_field("MDM Device", "enroll_token_used")
    _drop_doctype("MDM Enroll Token")


def _drop_field(doctype: str, fieldname: str):
    if not frappe.db.exists("DocType", doctype):
        return
    name = frappe.db.get_value(
        "Custom Field", {"dt": doctype, "fieldname": fieldname}, "name"
    )
    if name:
        frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)

    table = f"tab{doctype}"
    columns = [c.get("Field") or c.get("column_name") for c in frappe.db.sql(f"DESC `{table}`", as_dict=True)]
    if fieldname in columns:
        frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `{fieldname}`")


def _drop_doctype(doctype: str):
    if not frappe.db.exists("DocType", doctype):
        return
    # force=True: bỏ luôn cả bản ghi dữ liệu còn sót (chưa máy nào enroll bằng
    # token nên không mất gì có ý nghĩa)
    frappe.delete_doc("DocType", doctype, force=True, ignore_permissions=True)
    frappe.db.commit()
