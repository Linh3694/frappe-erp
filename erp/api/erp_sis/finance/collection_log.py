"""
API Nhật ký thu phí (Collection Log)
Ghi nhận liên hệ / nhắc đóng tiền theo từng SIS Finance Order Student.
"""

import frappe

from erp.utils.api_response import (
    validation_error_response,
    error_response,
    success_response,
)

from .utils import _check_admin_permission, _get_request_data


VALID_ACTIVITY_TYPES = frozenset(
    {"phone_call", "email", "zalo", "in_person", "debit_note_sent", "other"}
)
VALID_OUTCOMES = frozenset(
    {
        "no_answer",
        "will_pay",
        "bank_error",
        "partial_payment",
        "refused",
        "resolved",
        "need_follow_up",
        "other",
    }
)


def _serialize_log_row(row):
    """Chuẩn hoá dict từ DB hoặc doc thành payload JSON."""
    if not row:
        return None
    return {
        "name": row.get("name"),
        "order_student_id": row.get("order_student_id"),
        "activity_type": row.get("activity_type"),
        "outcome": row.get("outcome"),
        "content": row.get("content") or "",
        "follow_up_date": (
            str(row["follow_up_date"]) if row.get("follow_up_date") else None
        ),
        "logged_by": row.get("logged_by"),
        "logged_by_name": row.get("logged_by_name"),
        "creation": str(row["creation"]) if row.get("creation") else None,
        "modified": str(row["modified"]) if row.get("modified") else None,
    }


def get_collection_log_stats_for_order_students(order_student_ids):
    """
    Trả về (count_map, latest_map) cho danh sách order_student_id.
    Dùng nội bộ từ get_order_students_v2 / get_student_orders.
    """
    if not order_student_ids:
        return {}, {}

    placeholders = ", ".join(["%s"] * len(order_student_ids))

    counts = frappe.db.sql(
        f"""
        SELECT order_student_id, COUNT(*) AS cnt
        FROM `tabSIS Finance Collection Log`
        WHERE order_student_id IN ({placeholders})
        GROUP BY order_student_id
        """,
        tuple(order_student_ids),
        as_dict=True,
    )
    count_map = {c["order_student_id"]: int(c["cnt"]) for c in counts}

    # Bản ghi mới nhất theo creation (nếu trùng creation thì lấy name lớn hơn)
    latest_rows = frappe.db.sql(
        f"""
        SELECT cl.name, cl.order_student_id, cl.activity_type, cl.outcome, cl.content,
               cl.follow_up_date, cl.logged_by, cl.logged_by_name, cl.creation, cl.modified
        FROM `tabSIS Finance Collection Log` cl
        INNER JOIN (
            SELECT order_student_id, MAX(creation) AS mc
            FROM `tabSIS Finance Collection Log`
            WHERE order_student_id IN ({placeholders})
            GROUP BY order_student_id
        ) t ON cl.order_student_id = t.order_student_id AND cl.creation = t.mc
        """,
        # Chỉ một IN ({placeholders}) trong subquery → đúng N đối số %s (trước đây nhân đôi tuple gây lỗi format)
        tuple(order_student_ids),
        as_dict=True,
    )

    latest_map = {}
    for row in latest_rows:
        osid = row["order_student_id"]
        ser = _serialize_log_row(row)
        if osid not in latest_map:
            latest_map[osid] = ser
        else:
            prev = latest_map[osid]
            if row.get("name", "") > (prev.get("name") or ""):
                latest_map[osid] = ser

    return count_map, latest_map


@frappe.whitelist()
def get_collection_logs(order_student_id=None):
    """
    Lấy danh sách nhật ký thu phí theo order_student_id, sắp xếp mới nhất trước.
    """
    logs = []

    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)

        if not order_student_id:
            order_student_id = frappe.request.args.get("order_student_id")

        if not order_student_id:
            return validation_error_response(
                "Thiếu order_student_id",
                {"order_student_id": ["Bắt buộc"]},
            )

        if not frappe.db.exists("SIS Finance Order Student", order_student_id):
            return error_response(
                f"Không tìm thấy học sinh trong đơn: {order_student_id}", logs=logs
            )

        rows = frappe.get_all(
            "SIS Finance Collection Log",
            filters={"order_student_id": order_student_id},
            fields=[
                "name",
                "order_student_id",
                "activity_type",
                "outcome",
                "content",
                "follow_up_date",
                "logged_by",
                "logged_by_name",
                "creation",
                "modified",
            ],
            order_by="creation desc",
        )

        items = [_serialize_log_row(r) for r in rows]

        return success_response(data=items, logs=logs)

    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_collection_logs")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def create_collection_log():
    """
    Tạo bản ghi nhật ký thu phí (JSON body).
    """
    logs = []

    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền thực hiện", logs=logs)

        data = _get_request_data()
        order_student_id = data.get("order_student_id")
        content = (data.get("content") or "").strip()
        # Tuỳ chọn — nếu client gửi (tương thích cũ)
        activity_type = data.get("activity_type") or "other"
        outcome = data.get("outcome") or "other"
        follow_up_date = data.get("follow_up_date") or None

        if not order_student_id:
            return validation_error_response(
                "Thiếu order_student_id",
                {"order_student_id": ["Bắt buộc"]},
            )
        if not content:
            return validation_error_response(
                "Thiếu nội dung",
                {"content": ["Nội dung chi tiết là bắt buộc"]},
            )
        if activity_type not in VALID_ACTIVITY_TYPES:
            return validation_error_response(
                "activity_type không hợp lệ",
                {"activity_type": ["Giá trị không hợp lệ"]},
            )
        if outcome not in VALID_OUTCOMES:
            return validation_error_response(
                "outcome không hợp lệ",
                {"outcome": ["Giá trị không hợp lệ"]},
            )

        if not frappe.db.exists("SIS Finance Order Student", order_student_id):
            return error_response(
                f"Không tìm thấy học sinh trong đơn: {order_student_id}", logs=logs
            )

        doc = frappe.get_doc(
            {
                "doctype": "SIS Finance Collection Log",
                "order_student_id": order_student_id,
                "activity_type": activity_type,
                "outcome": outcome,
                "content": content,
                "follow_up_date": follow_up_date or None,
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        row = doc.as_dict()
        return success_response(
            data=_serialize_log_row(row),
            message="Đã thêm nhật ký thu phí",
            logs=logs,
        )

    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "create_collection_log")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def update_collection_log():
    """
    Cập nhật bản ghi nhật ký (JSON body: name + các field cần sửa).
    """
    logs = []

    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền thực hiện", logs=logs)

        data = _get_request_data()
        name = data.get("name")
        if not name:
            return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})

        if not frappe.db.exists("SIS Finance Collection Log", name):
            return error_response(f"Không tìm thấy bản ghi: {name}", logs=logs)

        doc = frappe.get_doc("SIS Finance Collection Log", name)

        if "activity_type" in data:
            at = data.get("activity_type")
            if at not in VALID_ACTIVITY_TYPES:
                return validation_error_response(
                    "activity_type không hợp lệ",
                    {"activity_type": ["Giá trị không hợp lệ"]},
                )
            doc.activity_type = at

        if "outcome" in data:
            oc = data.get("outcome")
            if oc not in VALID_OUTCOMES:
                return validation_error_response(
                    "outcome không hợp lệ",
                    {"outcome": ["Giá trị không hợp lệ"]},
                )
            doc.outcome = oc

        if "content" in data:
            doc.content = (data.get("content") or "").strip()
            if not doc.content:
                return validation_error_response(
                    "Nội dung không được để trống",
                    {"content": ["Bắt buộc"]},
                )

        if "follow_up_date" in data:
            doc.follow_up_date = data.get("follow_up_date") or None

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data=_serialize_log_row(doc.as_dict()),
            message="Đã cập nhật nhật ký",
            logs=logs,
        )

    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "update_collection_log")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def delete_collection_log(name=None):
    """
    Xóa một bản ghi nhật ký (query hoặc JSON: name).
    """
    logs = []

    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền xóa", logs=logs)

        if not name:
            data = _get_request_data()
            name = data.get("name") or frappe.form_dict.get("name")
        if not name:
            name = frappe.request.args.get("name")

        if not name:
            return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})

        if not frappe.db.exists("SIS Finance Collection Log", name):
            return error_response(f"Không tìm thấy bản ghi: {name}", logs=logs)

        frappe.delete_doc("SIS Finance Collection Log", name, ignore_permissions=True)
        frappe.db.commit()

        return success_response(data={"name": name}, message="Đã xóa nhật ký", logs=logs)

    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "delete_collection_log")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_collection_log_count(order_student_id=None):
    """Đếm số bản ghi nhật ký theo order_student_id."""
    logs = []

    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)

        if not order_student_id:
            order_student_id = frappe.request.args.get("order_student_id")

        if not order_student_id:
            return validation_error_response(
                "Thiếu order_student_id",
                {"order_student_id": ["Bắt buộc"]},
            )

        count = frappe.db.count(
            "SIS Finance Collection Log", {"order_student_id": order_student_id}
        )

        return success_response(data={"count": count}, logs=logs)

    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)
