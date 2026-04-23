"""
Order Structure APIs
Quản lý đơn hàng với cấu trúc milestones và fee_lines (version 2).
"""

import frappe
from frappe import _
import json

from erp.utils.api_response import (
    validation_error_response,
    error_response,
    success_response,
    single_item_response,
    not_found_response
)

from .utils import _check_admin_permission
from .collection_log import get_collection_log_stats_for_order_students

_MAX_INHERITANCE_DEPTH = 20


def _order_is_descendant_of(ancestor_id, node_id):
    """
    Trả về True nếu node_id nằm dưới ancestor_id trên cây parent_order_id
    (dùng để không cho chọn đơn con làm cha của tổ tiên, tránh chu trình).
    """
    if not ancestor_id or not node_id or ancestor_id == node_id:
        return False
    walk = frappe.db.get_value("SIS Finance Order", node_id, "parent_order_id")
    depth = 0
    while walk and depth < _MAX_INHERITANCE_DEPTH:
        if walk == ancestor_id:
            return True
        walk = frappe.db.get_value("SIS Finance Order", walk, "parent_order_id")
        depth += 1
    return False


@frappe.whitelist()
def get_eligible_parent_orders(finance_year_id=None, order_type=None, exclude_order_id=None):
    """
    Danh sách đơn có thể chọn làm "Kế thừa từ đơn": cùng năm, cùng loại,
    chưa bị thay thế; loại trừ exclude_order_id (đơn đang sửa) và mọi đơn
    nằm dưới exclude_order_id trong cây (tránh tạo chu trình).
    """
    logs = []
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        if not finance_year_id:
            finance_year_id = frappe.request.args.get("finance_year_id")
        if not order_type:
            order_type = frappe.request.args.get("order_type")
        if not exclude_order_id:
            exclude_order_id = frappe.request.args.get("exclude_order_id")
        if not finance_year_id or not order_type:
            return validation_error_response(
                "Thiếu finance_year_id hoặc order_type",
                {"finance_year_id": [finance_year_id or "bắt buộc"], "order_type": [order_type or "bắt buộc"]},
            )
        raw = frappe.get_all(
            "SIS Finance Order",
            filters={"finance_year_id": finance_year_id, "order_type": order_type, "is_superseded": 0},
            fields=["name", "title", "order_type", "status", "creation"],
            order_by="sort_order asc, creation asc",
            ignore_permissions=True,
        )
        items = []
        for o in raw:
            if exclude_order_id and o.name == exclude_order_id:
                continue
            if exclude_order_id and _order_is_descendant_of(exclude_order_id, o.name):
                continue
            items.append(o)
        return success_response(data={"items": items, "count": len(items)}, message="OK", logs=logs)
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_eligible_parent_orders")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def create_order_simple():
    """
    Tạo đơn hàng đơn giản - KHÔNG cần milestones và fee_lines.
    Version mới cho workflow đơn giản: tạo order -> thêm học sinh -> import số tiền -> upload file.
    
    Body:
        finance_year_id: ID năm tài chính
        title: Tên đơn hàng
        order_type: Loại (tuition/service/activity/other)
        description: Mô tả (optional)
        is_active: Trạng thái hoạt động (default 0)
    
    Returns:
        Thông tin đơn hàng vừa tạo
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền tạo đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        logs.append(f"Tạo đơn hàng đơn giản: {data.get('title')}")
        
        # Validate required fields
        if not data.get('finance_year_id'):
            return validation_error_response("Thiếu finance_year_id", {"finance_year_id": ["Bắt buộc"]})
        if not data.get('title'):
            return validation_error_response("Thiếu title", {"title": ["Bắt buộc"]})
        
        # Tạo đơn hàng - không có milestones và fee_lines
        new_row = {
            "doctype": "SIS Finance Order",
            "finance_year_id": data['finance_year_id'],
            "title": data['title'],
            "order_type": data.get('order_type', 'tuition'),
            "status": "draft",
            "is_active": data.get('is_active', 0),
            "is_required": data.get('is_required', 1),
            "description": data.get('description', ''),
        }
        if data.get("parent_order_id"):
            new_row["parent_order_id"] = data.get("parent_order_id")
        order_doc = frappe.get_doc(new_row)
        
        order_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã tạo đơn hàng: {order_doc.name}")
        
        return success_response(
            data={
                "name": order_doc.name,
                "title": order_doc.title,
                "order_type": order_doc.order_type,
                "status": order_doc.status,
                "is_active": order_doc.is_active,
                "parent_order_id": getattr(order_doc, "parent_order_id", None),
                "is_superseded": getattr(order_doc, "is_superseded", 0),
                "superseded_by": getattr(order_doc, "superseded_by", None),
            },
            message="Tạo đơn hàng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Create Order Simple Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def create_order_with_structure():
    """
    [DEPRECATED - dùng create_order_simple cho workflow mới]
    Tạo đơn hàng mới với cấu trúc milestones và fee_lines.
    
    Body:
        finance_year_id: ID năm tài chính
        title: Tên đơn hàng
        order_type: Loại (tuition/service/activity/other)
        milestones: List[{milestone_number, title, deadline_date, description}]
        fee_lines: List[{line_number, line_type, title_en, title_vn, is_compulsory, is_deduction, formula, note}]
    
    Returns:
        Thông tin đơn hàng vừa tạo
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền tạo đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        logs.append(f"Tạo đơn hàng với cấu trúc mới: {data.get('title')}")
        
        # Validate required fields
        if not data.get('finance_year_id'):
            return validation_error_response("Thiếu finance_year_id", {"finance_year_id": ["Bắt buộc"]})
        if not data.get('title'):
            return validation_error_response("Thiếu title", {"title": ["Bắt buộc"]})
        
        # Tạo đơn hàng
        row_w = {
            "doctype": "SIS Finance Order",
            "finance_year_id": data['finance_year_id'],
            "title": data['title'],
            "order_type": data.get('order_type', 'tuition'),
            "status": "draft",
            "is_active": data.get('is_active', 1),
            "is_required": data.get('is_required', 1),
            "description": data.get('description', ''),
            "debit_note_form_code": data.get('debit_note_form_code', 'TUITION_STANDARD')
        }
        if data.get("parent_order_id"):
            row_w["parent_order_id"] = data.get("parent_order_id")
        order_doc = frappe.get_doc(row_w)
        
        # Thêm milestones
        milestones = data.get('milestones', [])
        if isinstance(milestones, str):
            milestones = json.loads(milestones)
        
        for m in milestones:
            # Đảm bảo payment_scheme không rỗng - dùng 'or' thay vì default dict.get
            scheme = m.get('payment_scheme') or 'yearly'
            logs.append(f"Milestone: scheme={repr(scheme)}, number={m.get('milestone_number')}")
            
            order_doc.append("milestones", {
                "payment_scheme": scheme,
                "milestone_number": m.get('milestone_number'),
                "title": m.get('title'),
                "deadline_date": m.get('deadline_date') or None,
                "column_header_en": m.get('column_header_en', ''),
                "column_header_vn": m.get('column_header_vn', ''),
                "description": m.get('description', '')
            })
        
        # Thêm fee_lines
        fee_lines = data.get('fee_lines', [])
        if isinstance(fee_lines, str):
            fee_lines = json.loads(fee_lines)
        
        for idx, line in enumerate(fee_lines):
            order_doc.append("fee_lines", {
                "line_number": line.get('line_number'),
                "line_type": line.get('line_type', 'item'),
                "title_en": line.get('title_en'),
                "title_vn": line.get('title_vn'),
                "is_compulsory": line.get('is_compulsory', 0),
                "is_deduction": line.get('is_deduction', 0),
                "formula": line.get('formula', ''),
                "note": line.get('note', ''),
                "sort_order": idx
            })
        
        order_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã tạo đơn hàng: {order_doc.name}")
        
        return success_response(
            data={
                "name": order_doc.name,
                "title": order_doc.title,
                "status": order_doc.status,
                "milestones_count": len(order_doc.milestones),
                "fee_lines_count": len(order_doc.fee_lines)
            },
            message="Tạo đơn hàng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Create Order With Structure Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_order_with_structure(order_id=None):
    """
    Lấy chi tiết đơn hàng kèm milestones và fee_lines.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        if not frappe.db.exists("SIS Finance Order", order_id):
            return not_found_response(f"Không tìm thấy đơn hàng: {order_id}")
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        # Build response
        data = {
            "name": order_doc.name,
            "finance_year_id": order_doc.finance_year_id,
            "title": order_doc.title,
            "order_type": order_doc.order_type,
            "status": order_doc.status,
            "is_active": order_doc.is_active,
            "is_required": order_doc.is_required,
            "description": order_doc.description,
            "debit_note_form_code": order_doc.debit_note_form_code or 'TUITION_STANDARD',
            "parent_order_id": getattr(order_doc, "parent_order_id", None),
            "is_superseded": int(getattr(order_doc, "is_superseded", 0) or 0),
            "superseded_by": getattr(order_doc, "superseded_by", None),
            "total_students": order_doc.total_students,
            "data_completed_count": order_doc.data_completed_count,
            "total_collected": order_doc.total_collected,
            "total_outstanding": order_doc.total_outstanding,
            "collection_rate": order_doc.collection_rate,
            "milestones": [],
            "fee_lines": []
        }
        
        # Add milestones
        for m in order_doc.milestones:
            data["milestones"].append({
                "payment_scheme": m.payment_scheme or 'yearly',
                "milestone_number": m.milestone_number,
                "title": m.title,
                "deadline_date": str(m.deadline_date) if m.deadline_date else None,
                "column_header_en": m.column_header_en or '',
                "column_header_vn": m.column_header_vn or '',
                "description": m.description
            })
        
        # Add fee_lines
        for line in order_doc.fee_lines:
            data["fee_lines"].append({
                "idx": line.idx,
                "line_number": line.line_number,
                "line_type": line.line_type,
                "title_en": line.title_en,
                "title_vn": line.title_vn,
                "is_compulsory": line.is_compulsory,
                "is_deduction": line.is_deduction,
                "formula": line.formula,
                "note": line.note,
                "sort_order": line.sort_order
            })
        
        return single_item_response(data, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def update_order_structure():
    """
    Cập nhật cấu trúc milestones và fee_lines của đơn hàng.
    Cho phép ở mọi status trừ closed.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền cập nhật", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id')
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        if not frappe.db.exists("SIS Finance Order", order_id):
            return not_found_response(f"Không tìm thấy: {order_id}")
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        # Chỉ không cho phép khi đã đóng
        if order_doc.status == 'closed':
            return error_response("Không thể cập nhật đơn hàng đã đóng")

        # Kế thừa từ đơn (parent_order_id) — validate trong DocType
        if "parent_order_id" in data:
            pid = data.get("parent_order_id")
            order_doc.parent_order_id = (pid or "").strip() or None
        
        # Cập nhật milestones
        if 'milestones' in data:
            milestones = data['milestones']
            if isinstance(milestones, str):
                milestones = json.loads(milestones)
            
            order_doc.milestones = []
            for m in milestones:
                order_doc.append("milestones", {
                    "payment_scheme": m.get('payment_scheme', 'yearly'),
                    "milestone_number": m.get('milestone_number'),
                    "title": m.get('title'),
                    "deadline_date": m.get('deadline_date') or None,
                    "column_header_en": m.get('column_header_en', ''),
                    "column_header_vn": m.get('column_header_vn', ''),
                    "description": m.get('description', '')
                })
        
        # Cập nhật fee_lines
        if 'fee_lines' in data:
            fee_lines = data['fee_lines']
            if isinstance(fee_lines, str):
                fee_lines = json.loads(fee_lines)
            
            order_doc.fee_lines = []
            for idx, line in enumerate(fee_lines):
                order_doc.append("fee_lines", {
                    "line_number": line.get('line_number'),
                    "line_type": line.get('line_type', 'item'),
                    "title_en": line.get('title_en'),
                    "title_vn": line.get('title_vn'),
                    "is_compulsory": line.get('is_compulsory', 0),
                    "is_deduction": line.get('is_deduction', 0),
                    "formula": line.get('formula', ''),
                    "note": line.get('note', ''),
                    "sort_order": idx
                })
        
        order_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật cấu trúc đơn hàng: {order_id}")
        
        return success_response(
            data={"name": order_doc.name},
            message="Cập nhật thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def add_students_to_order_v2():
    """
    Thêm học sinh vào đơn hàng (version mới).
    Tạo Order Student và Student Order Lines (rỗng, chưa có số tiền).
    
    Nếu order_type = 'tuition', sẽ bỏ qua học sinh đã đóng học phí 
    trong order tuition khác của cùng năm tài chính.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền thêm học sinh", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id')
        student_ids = data.get('student_ids', [])
        # Tùy chọn: alias exclude_paid_in_parent_chain (cùng mặc định với legacy)
        exclude_paid_tuition = data.get('exclude_paid_tuition', True)
        exclude_paid_in_parent_chain = data.get('exclude_paid_in_parent_chain', exclude_paid_tuition)
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        if not student_ids:
            return validation_error_response("Thiếu student_ids", {"student_ids": ["Bắt buộc"]})
        
        if isinstance(student_ids, str):
            student_ids = json.loads(student_ids)
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        if not order_doc.can_add_students():
            return error_response(f"Không thể thêm học sinh khi status = {order_doc.status}")
        
        logs.append(f"Thêm {len(student_ids)} học sinh vào đơn hàng {order_id}")
        
        # Bỏ qua HS đã paid/partial: (1) trên chuỗi đơn cha nếu có parent_order_id;
        # (2) nếu tuition không có parent — giữ hành vi cũ: mọi đơn tuition khác trong năm.
        paid_tuition_student_ids = set()
        if getattr(order_doc, "parent_order_id", None) and exclude_paid_in_parent_chain:
            chain_ids = []
            walk = order_doc.parent_order_id
            depth = 0
            while walk and depth < _MAX_INHERITANCE_DEPTH:
                chain_ids.append(walk)
                walk = frappe.db.get_value("SIS Finance Order", walk, "parent_order_id")
                depth += 1
            if chain_ids:
                # IN clause — bind từng phần tử chuỗi đơn cha
                ph = ",".join(["%s"] * len(chain_ids))
                paid_rows = frappe.db.sql(
                    f"""
                    SELECT DISTINCT os.finance_student_id
                    FROM `tabSIS Finance Order Student` os
                    WHERE os.order_id IN ({ph})
                    AND os.payment_status IN ('paid', 'partial')
                """,
                    chain_ids,
                    as_list=True,
                )
                paid_tuition_student_ids = {r[0] for r in paid_rows}
                if paid_tuition_student_ids:
                    logs.append(
                        f"Tìm thấy {len(paid_tuition_student_ids)} HS đã paid/partial trên chuỗi đơn cha ({len(chain_ids)} đơn)"
                    )
        elif order_doc.order_type == "tuition" and exclude_paid_tuition:
            paid_students = frappe.db.sql(
                """
                SELECT DISTINCT os.finance_student_id
                FROM `tabSIS Finance Order Student` os
                JOIN `tabSIS Finance Order` o ON o.name = os.order_id
                WHERE o.finance_year_id = %(finance_year_id)s
                AND o.order_type = 'tuition'
                AND o.name != %(current_order)s
                AND os.payment_status IN ('paid', 'partial')
            """,
                {"finance_year_id": order_doc.finance_year_id, "current_order": order_id},
                as_list=True,
            )
            paid_tuition_student_ids = {r[0] for r in paid_students}
            if paid_tuition_student_ids:
                logs.append(f"Tìm thấy {len(paid_tuition_student_ids)} học sinh đã có ghi nhận học phí trong năm (legacy, không kế thừa)")
        
        created_count = 0
        skipped_count = 0
        skipped_paid_count = 0  # Số học sinh bị bỏ qua do đã đóng học phí
        
        for student_id in student_ids:
            try:
                # Kiểm tra đã có trong order này chưa
                existing = frappe.db.exists("SIS Finance Order Student", {
                    "order_id": order_id,
                    "finance_student_id": student_id
                })
                
                if existing:
                    skipped_count += 1
                    continue
                
                # Kiểm tra học sinh đã đóng học phí trong order tuition khác chưa
                if student_id in paid_tuition_student_ids:
                    skipped_paid_count += 1
                    continue
                
                # Tạo Order Student
                order_student = frappe.get_doc({
                    "doctype": "SIS Finance Order Student",
                    "order_id": order_id,
                    "finance_student_id": student_id,
                    "data_status": "pending",
                    "payment_status": "unpaid"
                })
                
                # Chỉ tạo Student Order Lines nếu order có fee_lines (legacy mode)
                if order_doc.fee_lines:
                    for line in order_doc.fee_lines:
                        order_student.append("fee_lines", {
                            "order_line_idx": line.idx,
                            "line_number": line.line_number,
                            "line_type": line.line_type,
                            "amounts_json": "{}",
                            "is_calculated": 1 if line.formula else 0
                        })
                
                order_student.insert(ignore_permissions=True)
                created_count += 1
                
            except Exception as e:
                logs.append(f"Lỗi khi thêm học sinh {student_id}: {str(e)}")
                continue
        
        frappe.db.commit()
        
        # Cập nhật thống kê
        order_doc.update_statistics()
        order_doc.update_status_based_on_students()
        
        logs.append(f"Đã thêm {created_count} học sinh, bỏ qua {skipped_count} (đã có), bỏ qua {skipped_paid_count} (đã đóng học phí)")
        
        return success_response(
            data={
                "created_count": created_count,
                "skipped_count": skipped_count,
                "skipped_paid_count": skipped_paid_count,
                "total": len(student_ids),
                "order_id": order_id
            },
            message=f"Thêm thành công {created_count} học sinh",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Add Students To Order V2 Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_order_students_v2(order_id=None, search=None, data_status=None, payment_status=None, page=1, page_size=20):
    """
    Lấy danh sách học sinh trong đơn hàng (version mới với Order Student).
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        if not search:
            search = frappe.request.args.get('search')
        if not data_status:
            data_status = frappe.request.args.get('data_status')
        if not payment_status:
            payment_status = frappe.request.args.get('payment_status')
        
        page = int(frappe.request.args.get('page', page))
        page_size = int(frappe.request.args.get('page_size', page_size))
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        # Build where clause
        where_clauses = ["os.order_id = %(order_id)s"]
        params = {"order_id": order_id}
        
        if search:
            where_clauses.append("(os.student_name LIKE %(search)s OR os.student_code LIKE %(search)s)")
            params["search"] = f"%{search}%"
        
        if data_status:
            where_clauses.append("os.data_status = %(data_status)s")
            params["data_status"] = data_status
        
        if payment_status:
            where_clauses.append("os.payment_status = %(payment_status)s")
            params["payment_status"] = payment_status
        
        where_sql = " AND ".join(where_clauses)
        
        # Count total
        total = frappe.db.sql(f"""
            SELECT COUNT(*) as count
            FROM `tabSIS Finance Order Student` os
            WHERE {where_sql}
        """, params, as_dict=True)[0].count
        
        # Pagination
        offset = (page - 1) * page_size
        total_pages = (total + page_size - 1) // page_size
        
        # Get students - thêm các fields mới cho milestone payment và tuition_paid_elsewhere
        students = frappe.db.sql(f"""
            SELECT 
                os.name, os.order_id, os.finance_student_id,
                os.student_name, os.student_code, os.class_title,
                os.data_status, os.total_amount, os.semester_1_amount, os.semester_2_amount,
                os.paid_amount, os.outstanding_amount, os.payment_status,
                os.latest_debit_note_version, os.latest_debit_note_url,
                os.payment_scheme_choice, os.current_milestone_key,
                os.semester_1_paid, os.semester_2_paid,
                os.milestone_amounts_json,
                os.tuition_paid_elsewhere, os.tuition_paid_elsewhere_order
            FROM `tabSIS Finance Order Student` os
            WHERE {where_sql}
            ORDER BY os.student_name ASC
            LIMIT %(page_size)s OFFSET %(offset)s
        """, {**params, "page_size": page_size, "offset": offset}, as_dict=True)
        
        # Parse milestone_amounts_json cho từng student
        for student in students:
            if student.get('milestone_amounts_json'):
                try:
                    student['milestone_amounts'] = json.loads(student['milestone_amounts_json'])
                except:
                    student['milestone_amounts'] = {}
            else:
                student['milestone_amounts'] = {}

        # Nhật ký thu phí: số lượng + bản ghi mới nhất (badge / xem nhanh)
        # Không để lỗi nhật ký (thiếu bảng / migrate) làm hỏng cả API danh sách HS
        try:
            os_ids = [s["name"] for s in students]
            count_map, latest_map = get_collection_log_stats_for_order_students(os_ids)
            for student in students:
                cid = student["name"]
                student["collection_log_count"] = count_map.get(cid, 0)
                student["latest_collection_log"] = latest_map.get(cid)
        except Exception as log_err:
            frappe.log_error(
                frappe.get_traceback(),
                "get_order_students_v2: collection log stats",
            )
            for student in students:
                student["collection_log_count"] = 0
                student["latest_collection_log"] = None

        return success_response(
            data={
                "items": students,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_paid_in_parent_order_chain(order_id=None):
    """
    Danh sách finance_student_id đã paid/partial trên bất kỳ đơn nào trong chuỗi cha
    (parent, ông, ...) — dùng StudentPool khi đơn có kế thừa, mọi order_type.
    """
    logs = []
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        if not order_id:
            order_id = frappe.request.args.get("order_id")
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        if not getattr(order_doc, "parent_order_id", None):
            return success_response(
                data={"paid_student_ids": [], "paid_students": [], "count": 0, "parent_chain": []},
                message="OK (không có chuỗi cha)",
                logs=logs,
            )
        chain_ids = []
        walk = order_doc.parent_order_id
        depth = 0
        while walk and depth < _MAX_INHERITANCE_DEPTH:
            chain_ids.append(walk)
            walk = frappe.db.get_value("SIS Finance Order", walk, "parent_order_id")
            depth += 1
        if not chain_ids:
            return success_response(
                data={"paid_student_ids": [], "paid_students": [], "count": 0, "parent_chain": []},
                message="OK",
                logs=logs,
            )
        ph = ",".join(["%s"] * len(chain_ids))
        paid_students = frappe.db.sql(
            f"""
            SELECT DISTINCT
                os.finance_student_id,
                fs.student_name,
                fs.student_code,
                o.title as order_title,
                o.name as order_id
            FROM `tabSIS Finance Order Student` os
            JOIN `tabSIS Finance Order` o ON o.name = os.order_id
            JOIN `tabSIS Finance Student` fs ON fs.name = os.finance_student_id
            WHERE os.order_id IN ({ph})
            AND os.payment_status IN ('paid', 'partial')
        """,
            chain_ids,
            as_dict=True,
        )
        paid_ids = [r.finance_student_id for r in paid_students]
        return success_response(
            data={
                "paid_student_ids": paid_ids,
                "paid_students": paid_students,
                "count": len(paid_ids),
                "parent_chain": chain_ids,
            },
            message="OK",
            logs=logs,
        )
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_paid_in_parent_order_chain")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_paid_tuition_students(finance_year_id=None, exclude_order_id=None):
    """
    Lấy danh sách học sinh đã có ghi nhận học phí (paid hoặc partial) trong năm tài chính.
    Dùng để filter trong StudentPoolModal khi thêm học sinh vào order tuition.
    
    Args:
        finance_year_id: ID năm tài chính
        exclude_order_id: ID order cần loại trừ (order hiện tại)
    
    Returns:
        Danh sách finance_student_id đã có ghi nhận học phí
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not finance_year_id:
            finance_year_id = frappe.request.args.get('finance_year_id')
        if not exclude_order_id:
            exclude_order_id = frappe.request.args.get('exclude_order_id')
        
        if not finance_year_id:
            return validation_error_response("Thiếu finance_year_id", {"finance_year_id": ["Bắt buộc"]})
        
        # Query học sinh đã có ghi nhận học phí (paid hoặc partial) trong các order tuition
        where_clause = """
            o.finance_year_id = %(finance_year_id)s
            AND o.order_type = 'tuition'
            AND os.payment_status IN ('paid', 'partial')
        """
        params = {"finance_year_id": finance_year_id}
        
        if exclude_order_id:
            where_clause += " AND o.name != %(exclude_order_id)s"
            params["exclude_order_id"] = exclude_order_id
        
        paid_students = frappe.db.sql(f"""
            SELECT DISTINCT 
                os.finance_student_id,
                fs.student_name,
                fs.student_code,
                o.title as order_title
            FROM `tabSIS Finance Order Student` os
            JOIN `tabSIS Finance Order` o ON o.name = os.order_id
            JOIN `tabSIS Finance Student` fs ON fs.name = os.finance_student_id
            WHERE {where_clause}
        """, params, as_dict=True)
        
        # Trả về list ID và thông tin chi tiết
        paid_ids = [s.finance_student_id for s in paid_students]
        
        return success_response(
            data={
                "paid_student_ids": paid_ids,
                "paid_students": paid_students,
                "count": len(paid_ids)
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)
