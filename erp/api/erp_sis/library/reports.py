from typing import List, Dict, Any
from datetime import timedelta

import frappe
from frappe.utils import getdate
from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
)

from ._constants import (
    TRANSACTION_DTYPE,
    TRANSACTION_ITEM_DTYPE,
    FINE_DTYPE,
    COPY_DTYPE,
    TITLE_DTYPE,
)
from ._common import _require_library_role

def _report_date_series(from_date: str, to_date: str) -> List[str]:
    """Sinh danh sách ngày liên tiếp trong khoảng báo cáo."""
    if not from_date or not to_date:
        return []
    current = getdate(from_date)
    end = getdate(to_date)
    dates: List[str] = []
    while current <= end:
        dates.append(str(current))
        current += timedelta(days=1)
    return dates


def _merge_daily_trend(rows: List[Dict[str, Any]], dates: List[str]) -> List[Dict[str, Any]]:
    """Ghép kết quả GROUP BY ngày với chuỗi ngày đầy đủ (thiếu ngày = 0)."""
    by_date = {str(row.get("date")): float(row.get("value") or 0) for row in rows}
    return [{"date": d, "value": by_date.get(d, 0)} for d in dates]


def _daily_transaction_trend(from_date: str, to_date: str, status: Any = None) -> List[Dict[str, Any]]:
    """Đếm phiếu mượn theo borrow_date — dùng sparkline KPI."""
    dates = _report_date_series(from_date, to_date)
    if not dates:
        return []

    params: List[Any] = [from_date, to_date]
    status_clause = ""
    if status == "returned":
        status_clause = " AND status = 'returned'"
    elif status == "borrowing":
        # Trả một phần vẫn còn sách chưa trả → tính vào đang mượn
        status_clause = " AND status IN ('borrowing', 'partial_return')"
    elif status:
        status_clause = " AND status = %s"
        params.append(status)

    rows = frappe.db.sql(
        f"""
        SELECT borrow_date AS date, COUNT(*) AS value
        FROM `tab{TRANSACTION_DTYPE}`
        WHERE borrow_date BETWEEN %s AND %s
        {status_clause}
        GROUP BY borrow_date
        ORDER BY borrow_date
        """,
        params,
        as_dict=True,
    )
    return _merge_daily_trend(rows, dates)


def _daily_total_fine_trend(from_date: str, to_date: str) -> List[Dict[str, Any]]:
    """Chuỗi tổng tiền phạt theo ngày — cộng phạt chưa thu + đã thu."""
    pending = _daily_fine_trend(from_date, to_date, pending=True)
    paid = _daily_fine_trend(from_date, to_date, pending=False)
    return [
        {
            "date": point.get("date"),
            "value": float(point.get("value") or 0) + float(paid[idx].get("value") or 0),
        }
        for idx, point in enumerate(pending)
    ]


def _daily_lost_damaged_trend(from_date: str, to_date: str) -> List[Dict[str, Any]]:
    """Đếm sách mất/hỏng theo ngày trả — dùng sparkline KPI."""
    dates = _report_date_series(from_date, to_date)
    if not dates:
        return []

    rows = frappe.db.sql(
        f"""
        SELECT date_returned AS date, COUNT(*) AS value
        FROM `tab{TRANSACTION_ITEM_DTYPE}`
        WHERE status IN ('lost', 'damaged')
          AND date_returned BETWEEN %s AND %s
        GROUP BY date_returned
        ORDER BY date_returned
        """,
        [from_date, to_date],
        as_dict=True,
    )
    return _merge_daily_trend(rows, dates)


def _daily_fine_trend(from_date: str, to_date: str, *, pending: bool) -> List[Dict[str, Any]]:
    """Chuỗi phạt theo ngày — pending: tổng amount; paid: paid_amount theo payment_date."""
    dates = _report_date_series(from_date, to_date)
    if not dates:
        return []

    if pending:
        rows = frappe.db.sql(
            f"""
            SELECT DATE(creation) AS date, COALESCE(SUM(total_amount), 0) AS value
            FROM `tab{FINE_DTYPE}`
            WHERE status = 'pending' AND DATE(creation) BETWEEN %s AND %s
            GROUP BY DATE(creation)
            ORDER BY DATE(creation)
            """,
            [from_date, to_date],
            as_dict=True,
        )
    else:
        rows = frappe.db.sql(
            f"""
            SELECT COALESCE(payment_date, DATE(creation)) AS date,
                   COALESCE(SUM(paid_amount), 0) AS value
            FROM `tab{FINE_DTYPE}`
            WHERE status = 'paid'
              AND COALESCE(payment_date, DATE(creation)) BETWEEN %s AND %s
            GROUP BY COALESCE(payment_date, DATE(creation))
            ORDER BY COALESCE(payment_date, DATE(creation))
            """,
            [from_date, to_date],
            as_dict=True,
        )
    return _merge_daily_trend(rows, dates)


def _normalize_book_title_key(title: Any) -> str:
    """Chuẩn hoá tên sách để gom các dòng trùng book_title."""
    return str(title or "").strip().casefold()


def _merge_top_books_by_title(
    rows: List[Dict[str, Any]],
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[List[Dict[str, Any]], int]:
    """Gom top sách theo book_title — mỗi lần mượn +1 vào cùng đầu sách."""
    merged: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        title = str(row.get("book_title") or "").strip()
        key = _normalize_book_title_key(title)
        if not key:
            continue

        borrow_count = int(row.get("borrow_count") or 0)
        if key not in merged:
            merged[key] = {
                "title_id": row.get("title_id") or "",
                "library_code": row.get("library_code") or "",
                "book_title": title,
                "borrow_count": borrow_count,
            }
            continue

        merged[key]["borrow_count"] += borrow_count
        if not merged[key]["title_id"] and row.get("title_id"):
            merged[key]["title_id"] = row["title_id"]
        if not merged[key]["library_code"] and row.get("library_code"):
            merged[key]["library_code"] = row["library_code"]

    sorted_items = sorted(merged.values(), key=lambda item: item["borrow_count"], reverse=True)
    total = len(sorted_items)
    if limit is None:
        return sorted_items, total
    return sorted_items[offset : offset + limit], total


def _build_borrow_date_clause(from_date: str = "", to_date: str = "") -> tuple[str, List[Any]]:
    """Tạo mệnh đề lọc borrow_date cho query top sách/người mượn."""
    date_clause = ""
    params: List[Any] = []
    if from_date and to_date:
        date_clause = "AND t.borrow_date BETWEEN %s AND %s"
        params.extend([from_date, to_date])
    elif from_date:
        date_clause = "AND t.borrow_date >= %s"
        params.append(from_date)
    elif to_date:
        date_clause = "AND t.borrow_date <= %s"
        params.append(to_date)
    return date_clause, params


def _fetch_top_books_raw(from_date: str = "", to_date: str = "") -> List[Dict[str, Any]]:
    """Lấy danh sách sách mượn thô trước khi gom theo book_title."""
    date_clause, params = _build_borrow_date_clause(from_date, to_date)
    return frappe.db.sql(
        f"""
        SELECT
            MAX(title_id) AS title_id,
            MAX(library_code) AS library_code,
            MAX(book_title) AS book_title,
            COUNT(*) AS borrow_count
        FROM (
            SELECT
                TRIM(LOWER(COALESCE(ti.book_title, ''))) AS title_key,
                TRIM(COALESCE(ti.book_title, '')) AS book_title,
                COALESCE(bc.title_id, '') AS title_id,
                COALESCE(lt.library_code, '') AS library_code
            FROM `tabSIS Library Transaction Item` ti
            INNER JOIN `tabSIS Library Transaction` t ON t.name = ti.parent
            LEFT JOIN `tab{COPY_DTYPE}` bc ON bc.generated_code = ti.book_copy_id
            LEFT JOIN `tab{TITLE_DTYPE}` lt ON lt.name = bc.title_id
            WHERE TRIM(COALESCE(ti.book_title, '')) != '' {date_clause}
        ) items
        GROUP BY title_key
        ORDER BY borrow_count DESC
        """,
        params,
        as_dict=True,
    )


@frappe.whitelist(allow_guest=False)
def get_library_borrow_report():
    """Báo cáo mượn/trả theo khoảng thời gian."""
    if (resp := _require_library_role()):
        return resp

    args = frappe.request.args if frappe.request else {}
    from_date = args.get("from_date") or frappe.form_dict.get("from_date") or ""
    to_date = args.get("to_date") or frappe.form_dict.get("to_date") or ""

    tx_filters = {}
    if from_date and to_date:
        tx_filters["borrow_date"] = ["between", [from_date, to_date]]
    elif from_date:
        tx_filters["borrow_date"] = [">=", from_date]
    elif to_date:
        tx_filters["borrow_date"] = ["<=", to_date]

    try:
        total_transactions = frappe.db.count(TRANSACTION_DTYPE, tx_filters)
        borrowing_count = frappe.db.count(
            TRANSACTION_DTYPE,
            {**tx_filters, "status": ["in", ["borrowing", "partial_return"]]},
        )
        overdue_count = frappe.db.count(TRANSACTION_DTYPE, {**tx_filters, "status": "overdue"})
        returned_count = frappe.db.count(TRANSACTION_DTYPE, {**tx_filters, "status": "returned"})
        partial_count = frappe.db.count(TRANSACTION_DTYPE, {**tx_filters, "status": "partial_return"})

        fine_date_clause = ""
        fine_params: List[Any] = []
        if from_date and to_date:
            fine_date_clause = "AND creation BETWEEN %s AND %s"
            fine_params.extend([from_date, to_date])
        elif from_date:
            fine_date_clause = "AND creation >= %s"
            fine_params.append(from_date)
        elif to_date:
            fine_date_clause = "AND creation <= %s"
            fine_params.append(to_date)

        pending_fines = frappe.db.sql(
            f"SELECT COALESCE(SUM(total_amount), 0) FROM `tabSIS Library Fine` WHERE status = 'pending' {fine_date_clause}",
            fine_params,
        )[0][0]
        paid_fines = frappe.db.sql(
            f"SELECT COALESCE(SUM(paid_amount), 0) FROM `tabSIS Library Fine` WHERE status = 'paid' {fine_date_clause}",
            fine_params,
        )[0][0]
        pending_fine_filters: Dict[str, Any] = {"status": "pending"}
        paid_fine_filters: Dict[str, Any] = {"status": "paid"}
        if from_date and to_date:
            pending_fine_filters["creation"] = ["between", [from_date, to_date]]
            paid_fine_filters["creation"] = ["between", [from_date, to_date]]
        pending_fines_count = frappe.db.count(FINE_DTYPE, pending_fine_filters)
        paid_fines_count = frappe.db.count(FINE_DTYPE, paid_fine_filters)
        total_fines = float(pending_fines or 0) + float(paid_fines or 0)

        lost_damaged_date_clause = ""
        lost_damaged_params: List[Any] = []
        if from_date and to_date:
            lost_damaged_date_clause = "AND date_returned BETWEEN %s AND %s"
            lost_damaged_params.extend([from_date, to_date])
        elif from_date:
            lost_damaged_date_clause = "AND date_returned >= %s"
            lost_damaged_params.append(from_date)
        elif to_date:
            lost_damaged_date_clause = "AND date_returned <= %s"
            lost_damaged_params.append(to_date)

        lost_damaged_count = frappe.db.sql(
            f"""
            SELECT COUNT(*)
            FROM `tab{TRANSACTION_ITEM_DTYPE}`
            WHERE status IN ('lost', 'damaged')
            {lost_damaged_date_clause}
            """,
            lost_damaged_params,
        )[0][0]

        trends = {}
        if from_date and to_date:
            trends = {
                "total_transactions": _daily_transaction_trend(from_date, to_date),
                "borrowing": _daily_transaction_trend(from_date, to_date, "borrowing"),
                "overdue": _daily_transaction_trend(from_date, to_date, "overdue"),
                "returned": _daily_transaction_trend(from_date, to_date, "returned"),
                "pending_fines": _daily_fine_trend(from_date, to_date, pending=True),
                "paid_fines": _daily_fine_trend(from_date, to_date, pending=False),
                "total_fines": _daily_total_fine_trend(from_date, to_date),
                "lost_damaged": _daily_lost_damaged_trend(from_date, to_date),
            }

        top_books_raw = _fetch_top_books_raw(from_date, to_date)
        top_books, _ = _merge_top_books_by_title(top_books_raw, limit=100)

        return success_response(
            data={
                "summary": {
                    "total_transactions": total_transactions,
                    "borrowing": borrowing_count,
                    "overdue": overdue_count,
                    "returned": returned_count,
                    "partial_return": partial_count,
                    "pending_fines_total": float(pending_fines or 0),
                    "paid_fines_total": float(paid_fines or 0),
                    "total_fines_total": total_fines,
                    "pending_fines_count": pending_fines_count,
                    "paid_fines_count": paid_fines_count,
                    "lost_damaged_count": int(lost_damaged_count or 0),
                },
                "trends": trends,
                "top_books": top_books,
            },
            message="Fetched library borrow report",
        )
    except Exception as ex:
        frappe.log_error(f"get_library_borrow_report failed: {ex}")
        return error_response(message="Không lấy được báo cáo mượn trả", code="LIB_REPORT_ERROR")


@frappe.whitelist(allow_guest=False)
def get_library_top_books():
    """Top sách mượn nhiều nhất — có phân trang."""
    if (resp := _require_library_role()):
        return resp

    args = frappe.request.args if frappe.request else {}

    def _p(key):
        return args.get(key) or frappe.form_dict.get(key) or ""

    from_date = _p("from_date")
    to_date = _p("to_date")
    page = max(int(_p("page") or 1), 1)
    page_size = min(max(int(_p("page_size") or 10), 1), 100)
    offset = (page - 1) * page_size

    try:
        top_books_raw = _fetch_top_books_raw(from_date, to_date)
        items, total = _merge_top_books_by_title(top_books_raw, limit=page_size, offset=offset)
        return success_response(
            data={"items": items, "total": total},
            message="Fetched top books",
        )
    except Exception as ex:
        frappe.log_error(f"get_library_top_books failed: {ex}")
        return error_response(message="Không lấy được top sách mượn", code="LIB_TOP_BOOKS_ERROR")


@frappe.whitelist(allow_guest=False)
def get_library_top_borrowers():
    """Top người mượn sách nhiều nhất — lọc theo đối tượng, có phân trang."""
    if (resp := _require_library_role()):
        return resp

    args = frappe.request.args if frappe.request else {}

    def _p(key):
        return args.get(key) or frappe.form_dict.get(key) or ""

    from_date = _p("from_date")
    to_date = _p("to_date")
    borrower_type = (_p("borrower_type") or "student").strip()
    page = max(int(_p("page") or 1), 1)
    page_size = min(max(int(_p("page_size") or 10), 1), 100)
    offset = (page - 1) * page_size

    if borrower_type not in {"student", "staff"}:
        return validation_error_response(
            message="borrower_type phải là student hoặc staff",
            errors={"borrower_type": ["invalid"]},
        )

    try:
        date_clause, params = _build_borrow_date_clause(from_date, to_date)
        type_clause = "AND t.borrower_type = %s"
        query_params = [*params, borrower_type]

        total = frappe.db.sql(
            f"""
            SELECT COUNT(*) FROM (
                SELECT t.borrower_id
                FROM `tabSIS Library Transaction` t
                WHERE 1=1 {date_clause} {type_clause}
                GROUP BY t.borrower_id
            ) ranked
            """,
            query_params,
        )[0][0]

        items = frappe.db.sql(
            f"""
            SELECT
                t.borrower_id,
                t.borrower_name,
                COALESCE(NULLIF(t.student_code, ''), NULLIF(t.employee_code, ''), t.borrower_id) AS borrower_code,
                COUNT(*) AS borrow_count
            FROM `tabSIS Library Transaction` t
            WHERE 1=1 {date_clause} {type_clause}
            GROUP BY t.borrower_id, t.borrower_name, borrower_code
            ORDER BY borrow_count DESC
            LIMIT %s OFFSET %s
            """,
            [*query_params, page_size, offset],
            as_dict=True,
        )

        return success_response(
            data={"items": items, "total": int(total or 0)},
            message="Fetched top borrowers",
        )
    except Exception as ex:
        frappe.log_error(f"get_library_top_borrowers failed: {ex}")
        return error_response(message="Không lấy được top người mượn", code="LIB_TOP_BORROWERS_ERROR")
