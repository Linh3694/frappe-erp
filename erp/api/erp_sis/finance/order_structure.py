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
        order_doc = frappe.get_doc({
            "doctype": "SIS Finance Order",
            "finance_year_id": data['finance_year_id'],
            "title": data['title'],
            "order_type": data.get('order_type', 'tuition'),
            "status": "draft",
            "is_active": data.get('is_active', 0),
            "is_required": data.get('is_required', 1),
            "description": data.get('description', '')
        })
        
        order_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã tạo đơn hàng: {order_doc.name}")
        
        return success_response(
            data={
                "name": order_doc.name,
                "title": order_doc.title,
                "order_type": order_doc.order_type,
                "status": order_doc.status,
                "is_active": order_doc.is_active
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
        order_doc = frappe.get_doc({
            "doctype": "SIS Finance Order",
            "finance_year_id": data['finance_year_id'],
            "title": data['title'],
            "order_type": data.get('order_type', 'tuition'),
            "status": "draft",
            "is_active": data.get('is_active', 1),
            "is_required": data.get('is_required', 1),
            "description": data.get('description', ''),
            "debit_note_form_code": data.get('debit_note_form_code', 'TUITION_STANDARD')
        })
        
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
    Chỉ cho phép khi status = draft hoặc students_added.
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
        
        # Chỉ cho phép cập nhật khi status phù hợp
        if order_doc.status not in ['draft', 'students_added']:
            return error_response(f"Không thể cập nhật khi status = {order_doc.status}")
        
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
        # Tùy chọn bỏ qua học sinh đã đóng học phí (mặc định True cho order tuition)
        exclude_paid_tuition = data.get('exclude_paid_tuition', True)
        
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
        
        # Nếu order_type là tuition và exclude_paid_tuition = True, 
        # lấy danh sách học sinh đã đóng học phí trong năm
        paid_tuition_student_ids = set()
        if order_doc.order_type == 'tuition' and exclude_paid_tuition:
            paid_students = frappe.db.sql("""
                SELECT DISTINCT os.finance_student_id
                FROM `tabSIS Finance Order Student` os
                JOIN `tabSIS Finance Order` o ON o.name = os.order_id
                WHERE o.finance_year_id = %(finance_year_id)s
                AND o.order_type = 'tuition'
                AND o.name != %(current_order)s
                AND os.payment_status = 'paid'
            """, {
                "finance_year_id": order_doc.finance_year_id,
                "current_order": order_id
            }, as_list=True)
            paid_tuition_student_ids = {r[0] for r in paid_students}
            if paid_tuition_student_ids:
                logs.append(f"Tìm thấy {len(paid_tuition_student_ids)} học sinh đã đóng học phí trong năm")
        
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
        
        # Get students - thêm các fields mới cho milestone payment
        students = frappe.db.sql(f"""
            SELECT 
                os.name, os.order_id, os.finance_student_id,
                os.student_name, os.student_code, os.class_title,
                os.data_status, os.total_amount, os.paid_amount,
                os.outstanding_amount, os.payment_status,
                os.latest_debit_note_version, os.latest_debit_note_url,
                os.payment_scheme_choice, os.current_milestone_key,
                os.semester_1_paid, os.semester_2_paid,
                os.milestone_amounts_json
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
def get_paid_tuition_students(finance_year_id=None, exclude_order_id=None):
    """
    Lấy danh sách học sinh đã đóng học phí trong năm tài chính.
    Dùng để filter trong StudentPoolModal khi thêm học sinh vào order tuition.
    
    Args:
        finance_year_id: ID năm tài chính
        exclude_order_id: ID order cần loại trừ (order hiện tại)
    
    Returns:
        Danh sách finance_student_id đã đóng học phí
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
        
        # Query học sinh đã đóng học phí trong các order tuition
        where_clause = """
            o.finance_year_id = %(finance_year_id)s
            AND o.order_type = 'tuition'
            AND os.payment_status = 'paid'
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
