import frappe
from frappe.utils import getdate, nowdate
from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
    not_found_response,
)

from ._constants import FINE_DTYPE, COPY_DTYPE, TRANSACTION_DTYPE
from erp.utils.search import search_names
from ._common import _require_library_role, _get_json_payload, _parse_date

def _create_fine_if_needed(
    transaction_id: str,
    book_copy_id: str,
    borrower_id: str,
    fine_type: str,
    total_amount,
):
    """Tạo phiếu phạt nếu chưa có pending cho cùng transaction + bản sao."""
    amount = float(total_amount or 0)
    if amount <= 0:
        return
    existing = frappe.db.exists(
        FINE_DTYPE,
        {
            "transaction_id": transaction_id,
            "book_copy_id": book_copy_id,
            "status": "pending",
        },
    )
    if existing:
        return
    try:
        frappe.get_doc(
            {
                "doctype": FINE_DTYPE,
                "transaction_id": transaction_id,
                "book_copy_id": book_copy_id,
                "borrower_id": borrower_id,
                "fine_type": fine_type,
                "total_amount": amount,
                "paid_amount": 0,
                "status": "pending",
            }
        ).insert(ignore_permissions=True)
    except Exception as ex:
        frappe.log_error(f"_create_fine_if_needed failed: {ex}")


def _get_book_copy_cover_price(book_copy_id: str) -> float:
    """Lấy giá bìa từ bản sao sách."""
    if not book_copy_id:
        return 0
    try:
        price = frappe.db.get_value(COPY_DTYPE, {"generated_code": book_copy_id}, "cover_price")
        return float(price or 0)
    except Exception:
        return 0


def _resolve_return_fine_amount(new_status: str, fine_amount, matched_item, book_copy_id: str):
    """Tính tiền phạt khi trả sách — mặc định theo giá bìa sách."""
    # Thủ thư nhập số tiền (kể cả 0 để miễn phạt)
    if fine_amount is not None and fine_amount != "":
        amount = float(fine_amount)
        if amount <= 0:
            return 0, None
        fine_type = new_status if new_status in {"lost", "damaged"} else "overdue"
        return amount, fine_type

    cover_price = _get_book_copy_cover_price(book_copy_id)

    if new_status in {"lost", "damaged"}:
        if cover_price > 0:
            return cover_price, new_status
        return 0, None

    if matched_item.due_date and getdate(matched_item.due_date) < getdate(nowdate()):
        if cover_price > 0:
            return cover_price, "overdue"

    return 0, None

@frappe.whitelist(allow_guest=False)
def list_fines():
    """Danh sách phiếu phạt.

    Query: status, borrower_id, transaction_id, page, page_size
    """
    if (resp := _require_library_role()):
        return resp

    params = frappe.form_dict
    status = params.get("status") or ""
    borrower_id = params.get("borrower_id") or ""
    transaction_id = params.get("transaction_id") or ""
    page = int(params.get("page") or 1)
    page_size = min(int(params.get("page_size") or 20), 100)
    offset = (page - 1) * page_size

    filters = {}
    if status:
        filters["status"] = status
    if borrower_id:
        _names = search_names(FINE_DTYPE, ["borrower_id"], borrower_id)
        filters["name"] = ["in", _names or ["__no_match__"]]
    if transaction_id:
        filters["transaction_id"] = transaction_id

    try:
        total = frappe.db.count(FINE_DTYPE, filters=filters)
        rows = frappe.get_all(
            FINE_DTYPE,
            filters=filters,
            fields=[
                "name", "transaction_id", "book_copy_id", "borrower_id",
                "fine_type", "total_amount", "paid_amount", "payment_date",
                "status", "waive_reason", "creation", "modified",
            ],
            order_by="creation desc",
            limit=page_size,
            start=offset,
        )
        for row in rows:
            row["id"] = row.pop("name")
        return success_response(data={"items": rows, "total": total}, message="Fetched fines")
    except Exception as ex:
        frappe.log_error(f"list_fines failed: {ex}")
        return error_response(message="Không lấy được danh sách phạt", code="FINE_LIST_ERROR")


@frappe.whitelist(allow_guest=False)
def create_fine():
    """Tạo phiếu phạt thủ công.

    Body: transaction_id, book_copy_id, borrower_id, fine_type, total_amount
    """
    if (resp := _require_library_role()):
        return resp

    data = _get_json_payload()
    transaction_id = (data.get("transaction_id") or "").strip()
    book_copy_id = (data.get("book_copy_id") or "").strip()
    borrower_id = (data.get("borrower_id") or "").strip()
    fine_type = (data.get("fine_type") or "").strip()
    total_amount = data.get("total_amount") or 0

    if not transaction_id:
        return validation_error_response(message="Thiếu transaction_id", errors={"transaction_id": ["required"]})
    if not borrower_id:
        return validation_error_response(message="Thiếu borrower_id", errors={"borrower_id": ["required"]})
    if fine_type not in {"overdue", "lost", "damaged"}:
        return validation_error_response(message="fine_type không hợp lệ", errors={"fine_type": ["invalid"]})
    if not total_amount or float(total_amount) <= 0:
        total_amount = _get_book_copy_cover_price(book_copy_id)
    if not total_amount or float(total_amount) <= 0:
        return validation_error_response(message="Số tiền phạt phải lớn hơn 0", errors={"total_amount": ["invalid"]})

    if not frappe.db.exists(TRANSACTION_DTYPE, transaction_id):
        return not_found_response(message="Không tìm thấy phiếu mượn", code="TX_NOT_FOUND")

    try:
        fine = frappe.get_doc({
            "doctype": FINE_DTYPE,
            "transaction_id": transaction_id,
            "book_copy_id": book_copy_id,
            "borrower_id": borrower_id,
            "fine_type": fine_type,
            "total_amount": float(total_amount),
            "paid_amount": 0,
            "status": "pending",
        })
        fine.insert(ignore_permissions=True)
        return success_response(
            data={"id": fine.name},
            message="Tạo phiếu phạt thành công",
        )
    except Exception as ex:
        frappe.log_error(f"create_fine failed: {ex}")
        return error_response(message="Không tạo được phiếu phạt", code="FINE_CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def update_fine():
    """Cập nhật phiếu phạt (thanh toán / miễn phạt).

    Body: id, paid_amount, payment_date, status, waive_reason
    """
    if (resp := _require_library_role()):
        return resp

    data = _get_json_payload()
    fine_id = (data.get("id") or "").strip()
    if not fine_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})

    try:
        fine = frappe.get_doc(FINE_DTYPE, fine_id)
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy phiếu phạt", code="FINE_NOT_FOUND")

    try:
        if "paid_amount" in data:
            fine.paid_amount = float(data["paid_amount"] or 0)
        if "payment_date" in data:
            fine.payment_date = _parse_date(data["payment_date"]) if data["payment_date"] else None
        if "status" in data:
            new_status = data["status"]
            if new_status not in {"pending", "paid", "waived"}:
                return validation_error_response(message="Status không hợp lệ", errors={"status": ["invalid"]})
            fine.status = new_status
        if "waive_reason" in data:
            fine.waive_reason = data["waive_reason"] or ""

        fine.save(ignore_permissions=True)
        return success_response(data={"id": fine.name}, message="Cập nhật phiếu phạt thành công")
    except Exception as ex:
        frappe.log_error(f"update_fine failed: {ex}")
        return error_response(message="Không cập nhật được phiếu phạt", code="FINE_UPDATE_ERROR")
