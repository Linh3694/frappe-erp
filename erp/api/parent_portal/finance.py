"""
Parent Portal Finance API
Handles finance viewing for parent portal

API endpoints cho phụ huynh xem khoản phí của học sinh.
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate
from erp.utils.api_response import (
    error_response, 
    success_response, 
    list_response
)


def _get_current_parent():
    """Lấy thông tin phụ huynh đang đăng nhập"""
    user_email = frappe.session.user
    if user_email == "Guest":
        return None

    # Format email: guardian_id@parent.wellspring.edu.vn
    if "@parent.wellspring.edu.vn" not in user_email:
        return None

    guardian_id = user_email.split("@")[0]

    # Lấy guardian name từ guardian_id
    guardian = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
    return guardian


def _get_parent_students(parent_id):
    """
    Lấy danh sách học sinh của phụ huynh.
    Loại bỏ duplicate students.
    """
    if not parent_id:
        return []
    
    # Query CRM Family Relationship để lấy danh sách học sinh
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": parent_id},
        fields=["student"]
    )
    
    # Lấy danh sách unique student IDs
    student_ids = list(set([rel.student for rel in relationships]))
    
    return student_ids


def _filter_orders_for_parent_portal(order_items):
    """
    Lọc danh sách order items cho hiển thị trên Parent Portal.
    
    Tuition orders là các mốc giá thay thế nhau - PHHS chỉ đóng 1 order tuition.
    - Loại bỏ order tuition có tuition_paid_elsewhere = 1 (đã đóng ở order khác)
    - Nếu còn nhiều order tuition chưa đóng, chỉ giữ order mới nhất
    
    Non-tuition orders (service, activity, other) giữ nguyên - cộng dồn bình thường.
    """
    if not order_items:
        return order_items
    
    non_tuition = [i for i in order_items if i.get('order_type') != 'tuition']
    tuition = [i for i in order_items if i.get('order_type') == 'tuition']
    
    if not tuition:
        return order_items
    
    # Loại bỏ tuition đã đóng ở nơi khác
    tuition_valid = [i for i in tuition if not i.get('tuition_paid_elsewhere')]
    
    if len(tuition_valid) <= 1:
        return non_tuition + tuition_valid
    
    # Ưu tiên order đang được đóng (có paid_amount > 0)
    with_payment = [i for i in tuition_valid if (i.get('paid_amount') or 0) > 0]
    if with_payment:
        return non_tuition + [with_payment[0]]
    
    # Chưa đóng order nào → giữ order mới nhất (sort_order cao nhất, creation mới nhất)
    tuition_valid.sort(
        key=lambda x: (x.get('sort_order', 0) or 0, str(x.get('order_creation', ''))),
        reverse=True
    )
    return non_tuition + [tuition_valid[0]]


def _calculate_student_finance_totals(finance_student_id):
    """
    Tính tổng tài chính cho 1 học sinh, xử lý dedup tuition orders.
    Dùng cho bảng tổng quan (get_all_students_finance).
    """
    all_items = frappe.db.sql("""
        SELECT 
            fos.name,
            fos.total_amount,
            fos.paid_amount,
            fos.outstanding_amount,
            fo.order_type,
            IFNULL(fos.tuition_paid_elsewhere, 0) as tuition_paid_elsewhere,
            fo.sort_order,
            fo.creation as order_creation
        FROM `tabSIS Finance Order Student` fos
        INNER JOIN `tabSIS Finance Order` fo ON fos.order_id = fo.name
        WHERE fos.finance_student_id = %s
          AND fo.is_active = 1
    """, (finance_student_id,), as_dict=True)
    
    relevant = _filter_orders_for_parent_portal(all_items)
    
    total = sum(i.get('total_amount') or 0 for i in relevant)
    paid = sum(i.get('paid_amount') or 0 for i in relevant)
    outstanding = sum(i.get('outstanding_amount') or 0 for i in relevant)
    
    return {
        "total_amount": total,
        "paid_amount": paid,
        "outstanding_amount": outstanding
    }


@frappe.whitelist()
def get_student_finance(student_id=None):
    """
    Lấy tổng hợp tài chính của một học sinh.
    Trả về danh sách các năm tài chính và các khoản phí của học sinh đó.
    
    Args:
        student_id: ID học sinh (CRM Student)
    
    Returns:
        Tổng hợp tài chính của học sinh
    """
    logs = []
    
    try:
        # Lấy student_id từ query params nếu không truyền vào
        if not student_id:
            student_id = frappe.request.args.get('student_id')
        
        if not student_id:
            return error_response("Thiếu student_id", logs=logs)
        
        logs.append(f"Lấy thông tin tài chính cho học sinh: {student_id}")
        
        # Kiểm tra phụ huynh có quyền xem không
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Kiểm tra học sinh có thuộc phụ huynh này không
        parent_students = _get_parent_students(parent_id)
        if student_id not in parent_students:
            return error_response("Bạn không có quyền xem thông tin học sinh này", logs=logs)
        
        # Lấy thông tin học sinh
        student = frappe.db.get_value(
            "CRM Student",
            student_id,
            ["student_name", "student_code", "campus_id"],
            as_dict=True
        )
        
        if not student:
            return error_response(f"Không tìm thấy học sinh: {student_id}", logs=logs)
        
        # Lấy danh sách năm tài chính của học sinh
        finance_students = frappe.db.sql("""
            SELECT 
                fs.name as finance_student_id,
                fs.finance_year_id,
                fy.title as finance_year_title,
                fy.school_year_id,
                sy.title_vn as school_year_name_vn,
                sy.title_en as school_year_name_en,
                fy.is_active,
                fs.class_title,
                fs.total_amount,
                fs.paid_amount,
                fs.outstanding_amount,
                fs.payment_status
            FROM `tabSIS Finance Student` fs
            INNER JOIN `tabSIS Finance Year` fy ON fs.finance_year_id = fy.name
            LEFT JOIN `tabSIS School Year` sy ON fy.school_year_id = sy.name
            WHERE fs.student_id = %s
            ORDER BY fy.start_date DESC
        """, (student_id,), as_dict=True)
        
        logs.append(f"Tìm thấy {len(finance_students)} năm tài chính")
        
        # Format kết quả
        result = {
            "student": {
                "id": student_id,
                "name": student.student_name,
                "code": student.student_code
            },
            "finance_years": []
        }
        
        # Status display mapping
        status_display = {
            'unpaid': 'Chưa đóng',
            'partial': 'Đóng một phần',
            'paid': 'Đã đóng đủ'
        }
        
        for fs in finance_students:
            fs['payment_status_display'] = status_display.get(fs.payment_status, fs.payment_status)
            result['finance_years'].append({
                "finance_student_id": fs.finance_student_id,
                "finance_year_id": fs.finance_year_id,
                "finance_year_title": fs.finance_year_title,
                "school_year_name_vn": fs.school_year_name_vn,
                "school_year_name_en": fs.school_year_name_en,
                "is_active": fs.is_active,
                "class_title": fs.class_title,
                "total_amount": fs.total_amount or 0,
                "paid_amount": fs.paid_amount or 0,
                "outstanding_amount": fs.outstanding_amount or 0,
                "payment_status": fs.payment_status,
                "payment_status_display": fs.payment_status_display
            })
        
        return success_response(
            data=result,
            message="Lấy thông tin tài chính thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Student Finance Error")
        return error_response(
            message=f"Lỗi khi lấy thông tin tài chính: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_student_finance_detail(finance_student_id=None):
    """
    Lấy chi tiết các khoản phí của học sinh trong một năm tài chính.
    
    Args:
        finance_student_id: ID của SIS Finance Student
    
    Returns:
        Danh sách các khoản phí và chi tiết thanh toán
    """
    logs = []
    
    try:
        if not finance_student_id:
            finance_student_id = frappe.request.args.get('finance_student_id')
        
        if not finance_student_id:
            return error_response("Thiếu finance_student_id", logs=logs)
        
        logs.append(f"Lấy chi tiết tài chính: {finance_student_id}")
        
        # Kiểm tra phụ huynh có quyền xem không
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Lấy thông tin finance student
        finance_student = frappe.db.get_value(
            "SIS Finance Student",
            finance_student_id,
            ["student_id", "finance_year_id", "student_name", "student_code", "class_title",
             "total_amount", "paid_amount", "outstanding_amount", "payment_status"],
            as_dict=True
        )
        
        if not finance_student:
            return error_response(f"Không tìm thấy: {finance_student_id}", logs=logs)
        
        # Kiểm tra học sinh có thuộc phụ huynh này không
        parent_students = _get_parent_students(parent_id)
        if finance_student.student_id not in parent_students:
            return error_response("Bạn không có quyền xem thông tin này", logs=logs)
        
        # Lấy thông tin năm tài chính
        finance_year = frappe.db.get_value(
            "SIS Finance Year",
            finance_student.finance_year_id,
            ["title", "school_year_id", "is_active"],
            as_dict=True
        )
        
        # Lấy tên năm học
        school_year_info = frappe.db.get_value(
            "SIS School Year",
            finance_year.school_year_id,
            ["title_vn", "title_en"],
            as_dict=True
        ) if finance_year else None
        
        # Lấy danh sách các khoản phí - bao gồm thông tin tuition dedup
        order_students = frappe.db.sql("""
            SELECT 
                fos.name as item_id,
                fos.order_id,
                fo.title as order_title,
                fo.order_type,
                fo.description as order_description,
                fos.total_amount as final_amount,
                fos.paid_amount,
                fos.outstanding_amount,
                fos.payment_status,
                IFNULL(fos.tuition_paid_elsewhere, 0) as tuition_paid_elsewhere,
                fo.sort_order,
                fo.creation as order_creation
            FROM `tabSIS Finance Order Student` fos
            INNER JOIN `tabSIS Finance Order` fo ON fos.order_id = fo.name
            WHERE fos.finance_student_id = %s
              AND fo.is_active = 1
            ORDER BY fo.sort_order ASC, fo.creation ASC
        """, (finance_student_id,), as_dict=True)
        
        # Lọc tuition orders: chỉ giữ 1 order tuition duy nhất cho PHHS
        order_students = _filter_orders_for_parent_portal(order_students)
        
        logs.append(f"Hiển thị {len(order_students)} khoản phí (sau lọc tuition)")
        
        # Format kết quả
        order_type_display = {
            'tuition': 'Học phí',
            'service': 'Phí dịch vụ',
            'activity': 'Phí hoạt động',
            'other': 'Khác'
        }
        
        status_display = {
            'unpaid': 'Chưa đóng',
            'partial': 'Đóng một phần',
            'paid': 'Đã đóng đủ',
            'refunded': 'Đã hoàn tiền'
        }
        
        items = []
        for item in order_students:
            item_data = {
                "item_id": item.item_id,
                "order_id": item.order_id,
                "order_title": item.order_title,
                "order_type": item.order_type,
                "order_type_display": order_type_display.get(item.order_type, item.order_type),
                "order_description": item.order_description,
                "final_amount": item.final_amount or 0,
                "paid_amount": item.paid_amount or 0,
                "outstanding_amount": item.outstanding_amount or 0,
                "payment_status": item.payment_status,
                "payment_status_display": status_display.get(item.payment_status, item.payment_status)
            }
            
            items.append(item_data)
        
        # Tính totals từ các items đã lọc
        filtered_total = sum(item.get("final_amount", 0) for item in items)
        filtered_paid = sum(item.get("paid_amount", 0) for item in items)
        filtered_outstanding = sum(item.get("outstanding_amount", 0) for item in items)
        
        # Tính payment_status dựa trên số liệu đã filter
        if filtered_total == 0:
            filtered_status = 'unpaid'
        elif filtered_paid >= filtered_total:
            filtered_status = 'paid'
        elif filtered_paid > 0:
            filtered_status = 'partial'
        else:
            filtered_status = 'unpaid'
        
        result = {
            "finance_student": {
                "id": finance_student_id,
                "student_id": finance_student.student_id,
                "student_name": finance_student.student_name,
                "student_code": finance_student.student_code,
                "class_title": finance_student.class_title,
                "total_amount": filtered_total,
                "paid_amount": filtered_paid,
                "outstanding_amount": filtered_outstanding,
                "payment_status": filtered_status,
                "payment_status_display": status_display.get(filtered_status, filtered_status)
            },
            "finance_year": {
                "id": finance_student.finance_year_id,
                "title": finance_year.title if finance_year else None,
                "school_year_name_vn": school_year_info.title_vn if school_year_info else None,
                "school_year_name_en": school_year_info.title_en if school_year_info else None,
                "is_active": finance_year.is_active if finance_year else False
            },
            "items": items
        }
        
        return success_response(
            data=result,
            message="Lấy chi tiết thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Student Finance Detail Error")
        return error_response(
            message=f"Lỗi khi lấy chi tiết: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_finance_years():
    """
    Lấy danh sách năm tài chính của các học sinh thuộc phụ huynh.
    Dùng để hiển thị dropdown chọn năm học.
    
    Returns:
        Danh sách năm tài chính unique
    """
    logs = []
    
    try:
        # Kiểm tra phụ huynh
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Lấy danh sách học sinh của phụ huynh
        student_ids = _get_parent_students(parent_id)
        
        if not student_ids:
            return success_response(data=[], message="Không có học sinh", logs=logs)
        
        # Lấy danh sách năm tài chính unique
        placeholders = ', '.join(['%s'] * len(student_ids))
        finance_years = frappe.db.sql(f"""
            SELECT DISTINCT
                fy.name as finance_year_id,
                fy.title,
                fy.is_active,
                sy.title_vn as school_year_name_vn,
                sy.title_en as school_year_name_en
            FROM `tabSIS Finance Student` fs
            INNER JOIN `tabSIS Finance Year` fy ON fs.finance_year_id = fy.name
            LEFT JOIN `tabSIS School Year` sy ON fy.school_year_id = sy.name
            WHERE fs.student_id IN ({placeholders})
            ORDER BY fy.start_date DESC
        """, tuple(student_ids), as_dict=True)
        
        return success_response(
            data=finance_years,
            message="Lấy danh sách năm tài chính thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Finance Years Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_all_students_finance(finance_year_id=None):
    """
    Lấy tổng hợp tài chính của tất cả học sinh của phụ huynh.
    Dùng để hiển thị overview trên dashboard.
    
    Args:
        finance_year_id: ID năm tài chính (optional). Nếu không truyền, lấy năm active.
    
    Returns:
        Tổng hợp tài chính của tất cả học sinh
    """
    logs = []
    
    try:
        # Lấy finance_year_id từ query params nếu không truyền vào
        if not finance_year_id:
            finance_year_id = frappe.request.args.get('finance_year_id')
        
        logs.append(f"Lấy tổng hợp tài chính tất cả học sinh, finance_year_id={finance_year_id}")
        
        # Kiểm tra phụ huynh
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent ID: {parent_id}")
        
        # Lấy danh sách học sinh của phụ huynh
        student_ids = _get_parent_students(parent_id)
        
        if not student_ids:
            return success_response(
                data={
                    "students": [],
                    "summary": {
                        "total_amount": 0,
                        "paid_amount": 0,
                        "outstanding_amount": 0
                    }
                },
                message="Không có học sinh",
                logs=logs
            )
        
        logs.append(f"Tìm thấy {len(student_ids)} học sinh")
        
        # Lấy thông tin tài chính của từng học sinh
        students_finance = []
        total_amount = 0
        total_paid = 0
        total_outstanding = 0
        
        status_display = {
            'unpaid': 'Chưa đóng',
            'partial': 'Đóng một phần',
            'paid': 'Đã đóng đủ'
        }
        
        for student_id in student_ids:
            # Lấy thông tin học sinh
            student = frappe.db.get_value(
                "CRM Student",
                student_id,
                ["student_name", "student_code", "campus_id"],
                as_dict=True
            )
            
            if not student:
                continue
            
            # Lấy năm tài chính - nếu có filter thì dùng filter, nếu không thì lấy năm active
            if finance_year_id:
                active_finance = frappe.db.sql("""
                    SELECT 
                        fs.name as finance_student_id,
                        fs.finance_year_id,
                        fy.title as finance_year_title,
                        fs.class_title
                    FROM `tabSIS Finance Student` fs
                    INNER JOIN `tabSIS Finance Year` fy ON fs.finance_year_id = fy.name
                    WHERE fs.student_id = %s
                      AND fs.finance_year_id = %s
                    LIMIT 1
                """, (student_id, finance_year_id), as_dict=True)
            else:
                active_finance = frappe.db.sql("""
                    SELECT 
                        fs.name as finance_student_id,
                        fs.finance_year_id,
                        fy.title as finance_year_title,
                        fs.class_title
                    FROM `tabSIS Finance Student` fs
                    INNER JOIN `tabSIS Finance Year` fy ON fs.finance_year_id = fy.name
                    WHERE fs.student_id = %s
                      AND fy.is_active = 1
                    LIMIT 1
                """, (student_id,), as_dict=True)
            
            student_data = {
                "student_id": student_id,
                "student_name": student.student_name,
                "student_code": student.student_code,
                "has_active_finance": len(active_finance) > 0
            }
            
            if active_finance:
                af = active_finance[0]
                
                # Tính totals - xử lý dedup tuition orders (chỉ tính 1 order tuition duy nhất)
                ot = _calculate_student_finance_totals(af.finance_student_id)
                
                # Tính payment_status
                if ot["total_amount"] == 0:
                    payment_status = 'unpaid'
                elif ot["paid_amount"] >= ot["total_amount"]:
                    payment_status = 'paid'
                elif ot["paid_amount"] > 0:
                    payment_status = 'partial'
                else:
                    payment_status = 'unpaid'
                
                student_data.update({
                    "finance_student_id": af.finance_student_id,
                    "finance_year_id": af.finance_year_id,
                    "finance_year_title": af.finance_year_title,
                    "class_title": af.class_title,
                    "total_amount": ot["total_amount"],
                    "paid_amount": ot["paid_amount"],
                    "outstanding_amount": ot["outstanding_amount"],
                    "payment_status": payment_status,
                    "payment_status_display": status_display.get(payment_status, payment_status)
                })
                
                total_amount += ot["total_amount"]
                total_paid += ot["paid_amount"]
                total_outstanding += ot["outstanding_amount"]
            
            students_finance.append(student_data)
        
        # Lấy thông tin năm tài chính đang chọn
        selected_year_info = None
        if finance_year_id:
            selected_year_info = frappe.db.get_value(
                "SIS Finance Year",
                finance_year_id,
                ["name as finance_year_id", "title", "is_active"],
                as_dict=True
            )
        elif students_finance and students_finance[0].get("finance_year_id"):
            # Lấy từ student đầu tiên có finance
            for s in students_finance:
                if s.get("finance_year_id"):
                    selected_year_info = frappe.db.get_value(
                        "SIS Finance Year",
                        s["finance_year_id"],
                        ["name as finance_year_id", "title", "is_active"],
                        as_dict=True
                    )
                    break
        
        return success_response(
            data={
                "students": students_finance,
                "summary": {
                    "total_amount": total_amount,
                    "paid_amount": total_paid,
                    "outstanding_amount": total_outstanding
                },
                "selected_finance_year": selected_year_info
            },
            message="Lấy thông tin thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get All Students Finance Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_order_student_documents(order_student_id=None):
    """
    Lấy danh sách tài liệu (Debit Note, Invoice, Receipt) của một order student.
    Dành cho phụ huynh xem tài liệu tài chính.
    
    Args:
        order_student_id: ID của SIS Finance Order Student
    
    Returns:
        Danh sách documents
    """
    logs = []
    
    try:
        if not order_student_id:
            order_student_id = frappe.request.args.get('order_student_id')
        
        if not order_student_id:
            return error_response("Thiếu order_student_id", logs=logs)
        
        # Kiểm tra phụ huynh
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Lấy danh sách học sinh của phụ huynh
        student_ids = _get_parent_students(parent_id)
        
        if not student_ids:
            return error_response("Không có quyền truy cập", logs=logs)
        
        # Kiểm tra order_student có thuộc học sinh của phụ huynh không
        order_student = frappe.db.sql("""
            SELECT 
                fos.name,
                fos.finance_student_id,
                fs.student_id
            FROM `tabSIS Finance Order Student` fos
            INNER JOIN `tabSIS Finance Student` fs ON fos.finance_student_id = fs.name
            WHERE fos.name = %s
        """, (order_student_id,), as_dict=True)
        
        if not order_student:
            return error_response("Không tìm thấy thông tin", logs=logs)
        
        if order_student[0].student_id not in student_ids:
            return error_response("Không có quyền truy cập tài liệu này", logs=logs)
        
        # Lấy danh sách tài liệu
        documents = frappe.get_all(
            "SIS Finance Student Document",
            filters={"order_student_id": order_student_id},
            fields=[
                "name", "order_student_id", "document_type", 
                "file_url", "file_name", "notes",
                "uploaded_at", "creation"
            ],
            order_by="creation desc"
        )
        
        # Format document type labels
        document_type_labels = {
            'debit_note': 'Thông báo học phí',
            'invoice': 'Hóa đơn',
            'receipt': 'Biên lai'
        }
        
        for doc in documents:
            if doc.get('uploaded_at'):
                doc['uploaded_at'] = str(doc['uploaded_at'])
            if doc.get('creation'):
                doc['creation'] = str(doc['creation'])
            doc['document_type_label'] = document_type_labels.get(doc.get('document_type'), doc.get('document_type'))
        
        logs.append(f"Tìm thấy {len(documents)} tài liệu")
        
        return success_response(
            data=documents,
            message="Lấy danh sách tài liệu thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Order Student Documents Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )
