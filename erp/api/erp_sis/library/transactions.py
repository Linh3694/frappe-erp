from typing import List, Dict, Any
from datetime import timedelta

import frappe
from frappe.utils import now, nowdate, getdate
from erp.utils.search import search_names
from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
    not_found_response,
)

from ._constants import (
    COPY_DTYPE,
    TRANSACTION_DTYPE,
    TRANSACTION_ITEM_DTYPE,
    DEFAULT_LOAN_DAYS,
)
from ._common import _require_library_role, _get_json_payload, _parse_date, _log_library_activity
from .settings import _get_library_settings
from .fines import _create_fine_if_needed, _resolve_return_fine_amount, _get_book_copy_cover_price

def _get_user_employee_code(user_id: str) -> str:
    """Lấy mã nhân viên từ User (custom field employee_code)."""
    if not user_id:
        return ""
    try:
        return (frappe.db.get_value("User", user_id, "employee_code") or "").strip()
    except Exception:
        return ""


def _validate_borrower(borrower_id: str, borrower_type: str):
    """Validate borrower exists. Returns (docname, name, student_code, employee_code)."""
    if borrower_type == "student":
        if frappe.db.exists("CRM Student", borrower_id):
            info = frappe.db.get_value(
                "CRM Student", borrower_id, ["student_name", "student_code"], as_dict=True
            )
            student_code = (info.get("student_code") or "").strip()
            return borrower_id, info.get("student_name") or borrower_id, student_code, ""
        docname = frappe.db.get_value("CRM Student", {"student_code": borrower_id}, "name")
        if docname:
            info = frappe.db.get_value(
                "CRM Student", docname, ["student_name", "student_code"], as_dict=True
            )
            student_code = (info.get("student_code") or borrower_id).strip()
            return docname, info.get("student_name") or docname, student_code, ""
        return None, None, None, None

    user_id = None
    teacher_docname = None
    if frappe.db.exists("SIS Teacher", borrower_id):
        teacher_docname = borrower_id
        user_id = frappe.db.get_value("SIS Teacher", borrower_id, "user_id")
    elif frappe.db.exists("User", borrower_id):
        user_id = borrower_id
        teacher_docname = frappe.db.get_value("SIS Teacher", {"user_id": borrower_id}, "name")
    else:
        # Cho phép tra cứu nhân viên theo employee_code
        try:
            user_id = frappe.db.get_value("User", {"employee_code": borrower_id}, "name")
        except Exception:
            user_id = None
        if user_id:
            teacher_docname = frappe.db.get_value("SIS Teacher", {"user_id": user_id}, "name")

    if not user_id:
        return None, None, None, None

    name = frappe.db.get_value("User", user_id, "full_name") or user_id
    employee_code = _get_user_employee_code(user_id) or (borrower_id or "").strip()
    docname = teacher_docname or user_id
    return docname, name, "", employee_code


def _find_active_transaction_for_copy(book_copy_id: str):
    """Tìm phiếu mượn đang mở chứa bản sao."""
    return frappe.db.get_value(
        TRANSACTION_ITEM_DTYPE,
        {
            "book_copy_id": book_copy_id,
            "status": ["in", ["borrowing", "overdue"]],
        },
        "parent",
    )

def _sync_transaction_status(transaction_doc):
    """Cập nhật status của transaction dựa trên items."""
    if not transaction_doc.items:
        return
    statuses = {item.status for item in transaction_doc.items}
    active = statuses - {"returned", "lost", "damaged"}
    if not active:
        transaction_doc.status = "returned"
    elif active == statuses:
        today = getdate(nowdate())
        any_overdue = any(
            item.due_date
            and getdate(item.due_date) < today
            and item.status in {"borrowing", "overdue"}
            for item in transaction_doc.items
        )
        transaction_doc.status = "overdue" if any_overdue else "borrowing"
    else:
        today = getdate(nowdate())
        open_items = [
            item for item in transaction_doc.items if item.status not in {"returned", "lost", "damaged"}
        ]
        any_overdue = any(
            item.due_date and getdate(item.due_date) < today and item.status in {"borrowing", "overdue"}
            for item in open_items
        )
        transaction_doc.status = "overdue" if any_overdue else "partial_return"


def _create_transaction_internal(
    borrower_id: str,
    borrower_type: str = "student",
    book_codes: List[str] | None = None,
    note: str = "",
    class_or_dept: str = "",
    borrow_date=None,
):
    """Logic tạo phiếu mượn — dùng chung cho create_transaction và borrow_multiple."""
    book_codes = book_codes or []
    settings = _get_library_settings()
    loan_days = int(settings.get("default_loan_days") or DEFAULT_LOAN_DAYS)
    borrow_date = _parse_date(borrow_date) if borrow_date else nowdate()

    borrower_docname, borrower_name, student_code, employee_code = _validate_borrower(borrower_id, borrower_type)
    if not borrower_docname:
        return not_found_response(message=f"Không tìm thấy người mượn: {borrower_id}", code="BORROWER_NOT_FOUND")

    if borrower_type == "student":
        max_books = int(settings.get("max_books_per_student") or 0)
        if max_books > 0:
            active_count = frappe.db.count(
                TRANSACTION_DTYPE,
                {
                    "borrower_id": borrower_docname,
                    "borrower_type": "student",
                    "status": ["in", ["borrowing", "overdue", "partial_return"]],
                },
            )
            if active_count + len(book_codes) > max_books:
                return validation_error_response(
                    message=f"Học sinh chỉ được mượn tối đa {max_books} sách",
                    errors={"book_codes": ["max_limit"]},
                )

    due_date_obj = getdate(borrow_date) + timedelta(days=loan_days)
    due_date_str = due_date_obj.strftime("%Y-%m-%d")

    items = []
    errors = []
    for code in book_codes:
        code = (code or "").strip()
        if not code:
            continue
        try:
            copy_doc = frappe.get_doc(COPY_DTYPE, {"generated_code": code})
            if copy_doc.status != "available":
                errors.append(f"{code}: không khả dụng (đang ở trạng thái {copy_doc.status})")
                continue
            items.append(
                {
                    "doctype": TRANSACTION_ITEM_DTYPE,
                    "book_copy_id": code,
                    "book_title": copy_doc.book_title or "",
                    "book_type": copy_doc.special_code or "",
                    "due_date": due_date_str,
                    "status": "borrowing",
                }
            )
        except frappe.DoesNotExistError:
            errors.append(f"{code}: không tìm thấy bản sao")
        except Exception as ex:
            errors.append(f"{code}: {ex}")

    if not items:
        return validation_error_response(
            message="Không có bản sao nào hợp lệ để mượn",
            errors={"book_codes": errors},
        )

    try:
        tx = frappe.get_doc(
            {
                "doctype": TRANSACTION_DTYPE,
                "borrower_id": borrower_docname,
                "borrower_name": borrower_name,
                "student_code": student_code if borrower_type == "student" else "",
                "employee_code": employee_code if borrower_type == "staff" else "",
                "borrower_type": borrower_type,
                "class_or_dept": class_or_dept,
                "borrow_date": borrow_date,
                "status": "borrowing",
                "note": note,
                "items": items,
            }
        )
        tx.insert(ignore_permissions=True)

        for item in tx.items:
            try:
                copy_doc = frappe.get_doc(COPY_DTYPE, {"generated_code": item.book_copy_id})
                copy_doc.status = "borrowed"
                copy_doc.borrower_id = borrower_docname
                copy_doc.borrower_name = borrower_name
                copy_doc.borrowed_date = borrow_date
                copy_doc.return_date = None
                copy_doc.overdue_days = 0
                copy_doc.save(ignore_permissions=True)
                _log_library_activity(copy_doc.name, "borrow", f"Mượn qua phiếu {tx.name}")
            except Exception as ex:
                frappe.log_error(f"_create_transaction_internal: sync copy {item.book_copy_id} failed: {ex}")

        return {
            "id": tx.name,
            "success_count": len(tx.items),
            "total_count": len(book_codes),
            "errors": errors,
        }
    except Exception as ex:
        frappe.log_error(f"_create_transaction_internal failed: {ex}")
        return error_response(message="Không tạo được phiếu mượn", code="TX_CREATE_ERROR")


def _return_items_internal(tx_id: str, return_items: List[Dict[str, Any]]):
    """Logic trả sách — dùng chung cho return_transaction_items và return_copy."""
    VALID_RETURN_STATUSES = {"returned", "lost", "damaged"}

    try:
        tx = frappe.get_doc(TRANSACTION_DTYPE, tx_id)
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy phiếu mượn", code="TX_NOT_FOUND")

    errors = []
    updated = 0
    today = nowdate()

    for ret in return_items:
        book_copy_id = (ret.get("book_copy_id") or "").strip()
        new_status = (ret.get("status") or "returned").strip()
        item_note = ret.get("note") or ""
        fine_amount = ret.get("fine_amount")

        if new_status not in VALID_RETURN_STATUSES:
            errors.append(f"{book_copy_id}: status không hợp lệ ({new_status})")
            continue

        matched = None
        for item in tx.items:
            if item.book_copy_id == book_copy_id:
                matched = item
                break

        if not matched:
            errors.append(f"{book_copy_id}: không thuộc phiếu mượn này")
            continue

        if matched.status not in {"borrowing", "overdue"}:
            errors.append(f"{book_copy_id}: đã ở trạng thái {matched.status}")
            continue

        resolved_amount, fine_type = _resolve_return_fine_amount(new_status, fine_amount, matched, book_copy_id)

        matched.status = new_status
        matched.date_returned = today
        matched.note = item_note
        matched.fine_amount = resolved_amount

        try:
            from .copies import _get_copy_by_identifier, _sync_copy_after_return
            copy_doc = _get_copy_by_identifier(book_copy_id)
            _sync_copy_after_return(copy_doc, new_status, today)
            copy_doc.save(ignore_permissions=True)
            _log_library_activity(copy_doc.name, "return", f"Trả qua phiếu {tx.name}: {new_status}")
        except frappe.DoesNotExistError:
            errors.append(f"{book_copy_id}: không tìm thấy bản sao")
        except Exception as ex:
            frappe.log_error(f"_return_items_internal: sync copy {book_copy_id} failed: {ex}")

        if fine_type and resolved_amount > 0:
            _create_fine_if_needed(tx.name, book_copy_id, tx.borrower_id, fine_type, resolved_amount)

        updated += 1

    _sync_transaction_status(tx)
    tx.save(ignore_permissions=True)
    return {"success_count": updated, "errors": errors}


def sync_overdue_status():
    """Đồng bộ trạng thái quá hạn — gọi từ cron hoặc thủ công."""
    today = getdate(nowdate())
    overdue_items = frappe.db.sql(
        """
        SELECT name, parent, book_copy_id, due_date
        FROM `tabSIS Library Transaction Item`
        WHERE status = 'borrowing' AND due_date IS NOT NULL AND due_date < %s
        """,
        today,
        as_dict=True,
    )

    tx_ids = set()
    for item in overdue_items:
        frappe.db.set_value(TRANSACTION_ITEM_DTYPE, item.name, "status", "overdue", update_modified=False)
        tx_ids.add(item.parent)
        try:
            copy_doc = frappe.get_doc(COPY_DTYPE, {"generated_code": item.book_copy_id})
            copy_doc.status = "overdue"
            delta = (today - getdate(item.due_date)).days
            copy_doc.overdue_days = max(delta, 0)
            copy_doc.save(ignore_permissions=True)
        except Exception as ex:
            frappe.log_error(f"sync_overdue_status: copy {item.book_copy_id} failed: {ex}")

    for tx_id in tx_ids:
        try:
            tx = frappe.get_doc(TRANSACTION_DTYPE, tx_id)
            _sync_transaction_status(tx)
            tx.save(ignore_permissions=True)
        except Exception as ex:
            frappe.log_error(f"sync_overdue_status: tx {tx_id} failed: {ex}")

    frappe.db.commit()
    return len(overdue_items)


@frappe.whitelist(allow_guest=False)
def create_transaction():
    """Tạo phiếu mượn mới."""
    if (resp := _require_library_role()):
        return resp

    data = _get_json_payload()
    borrower_id = (data.get("borrower_id") or "").strip()
    borrower_type = (data.get("borrower_type") or "student").strip()
    book_codes = data.get("book_codes") or []
    note = data.get("note") or ""
    class_or_dept = data.get("class_or_dept") or ""
    raw_date = data.get("borrow_date")

    if not borrower_id:
        return validation_error_response(message="Thiếu mã người mượn", errors={"borrower_id": ["required"]})
    if borrower_type not in {"student", "staff"}:
        return validation_error_response(message="borrower_type phải là student hoặc staff", errors={"borrower_type": ["invalid"]})
    if not book_codes:
        return validation_error_response(message="Cần ít nhất 1 bản sao", errors={"book_codes": ["required"]})

    result = _create_transaction_internal(
        borrower_id=borrower_id,
        borrower_type=borrower_type,
        book_codes=book_codes,
        note=note,
        class_or_dept=class_or_dept,
        borrow_date=raw_date,
    )
    if isinstance(result, dict) and result.get("success") is False:
        return result
    return success_response(data=result, message="Tạo phiếu mượn thành công")


@frappe.whitelist(allow_guest=False)
def list_transactions():
    """Danh sách phiếu mượn.

    Query params:
      status, borrower_id, borrower_type, search, from_date, to_date, page, page_size
    """
    if (resp := _require_library_role()):
        return resp

    args = frappe.request.args if frappe.request else {}
    def _p(key):
        return args.get(key) or frappe.form_dict.get(key) or ""

    status = _p("status")
    borrower_id = _p("borrower_id")
    borrower_type = _p("borrower_type")
    search = _p("search")
    from_date = _p("from_date")
    to_date = _p("to_date")
    page = int(_p("page") or 1)
    page_size = min(int(_p("page_size") or 20), 100)
    offset = (page - 1) * page_size

    filters = {}
    if status == "borrowing":
        # Trả một phần vẫn còn sách chưa trả → hiển thị cùng tab Đang mượn
        filters["status"] = ["in", ["borrowing", "partial_return"]]
    elif status:
        filters["status"] = status
    if borrower_type:
        filters["borrower_type"] = borrower_type
    if from_date and to_date:
        filters["borrow_date"] = ["between", [from_date, to_date]]
    elif from_date:
        filters["borrow_date"] = [">=", from_date]
    elif to_date:
        filters["borrow_date"] = ["<=", to_date]

    or_filters = {}
    if borrower_id:
        _bnames = search_names(
            TRANSACTION_DTYPE, ["borrower_id", "student_code", "employee_code"], borrower_id
        )
        or_filters = {"name": ["in", _bnames or ["__no_match__"]]}
    if search:
        _names = search_names(
            TRANSACTION_DTYPE,
            ["borrower_name", "borrower_id", "student_code", "employee_code", "name"],
            search,
        )
        or_filters = {"name": ["in", _names or ["__no_match__"]]}

    try:
        total = frappe.db.count(TRANSACTION_DTYPE, filters=filters)
        rows = frappe.get_all(
            TRANSACTION_DTYPE,
            filters=filters,
            or_filters=or_filters if or_filters else None,
            fields=[
                "name", "borrower_id", "borrower_name", "student_code", "employee_code",
                "borrower_type", "class_or_dept", "borrow_date", "status", "note",
                "creation", "modified",
            ],
            order_by="borrow_date desc, creation desc",
            limit=page_size,
            start=offset,
        )

        # Attach items count, due date, and overdue days per transaction
        for row in rows:
            row["id"] = row.pop("name")
            item_count = frappe.db.count(
                TRANSACTION_ITEM_DTYPE,
                filters={"parent": row["id"]},
            )
            row["item_count"] = item_count

            # Fetch the first item's due date
            due_date = frappe.db.get_value(
                TRANSACTION_ITEM_DTYPE,
                {"parent": row["id"]},
                "due_date",
            )
            row["due_date"] = str(due_date) if due_date else None

            # Calculate overdue days
            overdue_days = 0
            if row["status"] in ["borrowing", "overdue", "partial_return"]:
                items = frappe.get_all(
                    TRANSACTION_ITEM_DTYPE,
                    filters={"parent": row["id"], "status": ["!=", "returned"]},
                    fields=["due_date"],
                )
                today = getdate(nowdate())
                for item in items:
                    if item.due_date:
                        item_due = getdate(item.due_date)
                        if item_due < today:
                            delta = (today - item_due).days
                            if delta > overdue_days:
                                overdue_days = delta
            row["overdue_days"] = overdue_days

        return success_response(
            data={"items": rows, "total": total},
            message="Fetched transactions",
        )
    except Exception as ex:
        frappe.log_error(f"list_transactions failed: {ex}")
        return error_response(message="Không lấy được danh sách phiếu mượn", code="TX_LIST_ERROR")


@frappe.whitelist(allow_guest=False)
def get_transaction():
    """Chi tiết 1 phiếu mượn (kèm items).

    Query: id
    """
    if (resp := _require_library_role()):
        return resp

    data = _get_json_payload()
    tx_id = (
        data.get("transaction_id")
        or data.get("id")
        or frappe.form_dict.get("transaction_id")
        or frappe.form_dict.get("id")
        or ""
    )
    if not tx_id:
        return validation_error_response(message="Thiếu id", errors={"id": ["required"]})

    try:
        tx = frappe.get_doc(TRANSACTION_DTYPE, tx_id)
        items = []
        for item in tx.items:
            cover_price = _get_book_copy_cover_price(item.book_copy_id)
            items.append({
                "id": item.name,
                "book_copy_id": item.book_copy_id,
                "book_title": item.book_title,
                "book_type": item.book_type,
                "due_date": str(item.due_date) if item.due_date else None,
                "date_returned": str(item.date_returned) if item.date_returned else None,
                "status": item.status,
                "fine_amount": item.fine_amount or 0,
                "cover_price": cover_price or None,
                "note": item.note or "",
            })
        return success_response(
            data={
                "id": tx.name,
                "borrower_id": tx.borrower_id,
                "borrower_name": tx.borrower_name,
                "student_code": tx.student_code or "",
                "employee_code": tx.employee_code or "",
                "borrower_type": tx.borrower_type,
                "class_or_dept": tx.class_or_dept,
                "borrow_date": str(tx.borrow_date) if tx.borrow_date else None,
                "status": tx.status,
                "note": tx.note or "",
                "items": items,
                "creation": str(tx.creation) if tx.creation else None,
                "modified": str(tx.modified) if tx.modified else None,
            },
            message="Fetched transaction",
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Không tìm thấy phiếu mượn", code="TX_NOT_FOUND")
    except Exception as ex:
        frappe.log_error(f"get_transaction failed: {ex}")
        return error_response(message="Không lấy được phiếu mượn", code="TX_GET_ERROR")


@frappe.whitelist(allow_guest=False)
def return_transaction_items():
    """Trả sách cho một phiếu mượn."""
    if (resp := _require_library_role()):
        return resp

    data = _get_json_payload()
    tx_id = (data.get("transaction_id") or "").strip()
    return_items = data.get("items") or []

    if not tx_id:
        return validation_error_response(message="Thiếu transaction_id", errors={"transaction_id": ["required"]})
    if not return_items:
        return validation_error_response(message="Cần ít nhất 1 bản sao để trả", errors={"items": ["required"]})

    result = _return_items_internal(tx_id, return_items)
    if isinstance(result, dict) and result.get("success") is False:
        return result
    return success_response(data=result, message="Cập nhật trả sách thành công")
