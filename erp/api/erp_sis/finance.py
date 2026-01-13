"""
Admin Finance API
Handles finance management for admin/registrar staff

API endpoints cho admin quản lý năm tài chính, đơn hàng và học sinh.
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, now
import json
from erp.utils.api_response import (
    validation_error_response, 
    list_response, 
    error_response, 
    success_response, 
    single_item_response,
    not_found_response
)


def _check_admin_permission():
    """Kiểm tra quyền admin"""
    user_roles = frappe.get_roles(frappe.session.user)
    allowed_roles = ['System Manager', 'SIS Manager', 'Registrar', 'SIS BOD']
    
    if not any(role in user_roles for role in allowed_roles):
        return False
    return True


def _resolve_campus_id(campus_id):
    """
    Chuyển đổi campus_id từ format frontend (campus-1) sang format database (CAMPUS-00001)
    """
    if not campus_id:
        return None
    
    # Nếu đã đúng format CAMPUS-xxxxx thì return luôn
    if campus_id.startswith("CAMPUS-"):
        if frappe.db.exists("SIS Campus", campus_id):
            return campus_id
    
    # Nếu là format campus-1, campus-2, etc.
    if campus_id.startswith("campus-"):
        try:
            campus_index = int(campus_id.split("-")[1])
            mapped_campus = f"CAMPUS-{campus_index:05d}"
            if frappe.db.exists("SIS Campus", mapped_campus):
                return mapped_campus
        except (ValueError, IndexError):
            pass
    
    # Thử tìm theo name trực tiếp
    if frappe.db.exists("SIS Campus", campus_id):
        return campus_id
    
    # Thử tìm campus đầu tiên
    first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
    if first_campus:
        return first_campus
    
    return None


# ==================== FINANCE YEAR APIs ====================

@frappe.whitelist()
def get_finance_years(campus_id=None):
    """
    Lấy danh sách năm tài chính.
    
    Args:
        campus_id: Filter theo campus (optional)
    
    Returns:
        List các năm tài chính với thống kê cơ bản
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy campus_id từ query params nếu không truyền vào
        if not campus_id:
            campus_id = frappe.request.args.get('campus_id')
        
        # Resolve campus_id
        resolved_campus = _resolve_campus_id(campus_id) if campus_id else None
        
        logs.append(f"Lấy danh sách năm tài chính, campus: {resolved_campus}")
        
        # Build filters
        filters = {}
        if resolved_campus:
            filters['campus_id'] = resolved_campus
        
        # Lấy danh sách năm tài chính
        finance_years = frappe.get_all(
            "SIS Finance Year",
            filters=filters,
            fields=[
                "name", "title", "school_year_id", "campus_id", 
                "is_active", "start_date", "end_date",
                "total_students", "total_orders", "total_amount", "total_paid"
            ],
            order_by="start_date desc"
        )
        
        # Thêm thông tin school year và campus name
        for fy in finance_years:
            # Lấy tên năm học
            school_year_info = frappe.db.get_value(
                "SIS School Year", 
                fy.school_year_id, 
                ["title_vn", "title_en"],
                as_dict=True
            )
            if school_year_info:
                fy['school_year_name_vn'] = school_year_info.title_vn
                fy['school_year_name_en'] = school_year_info.title_en
            
            # Lấy tên campus
            campus_info = frappe.db.get_value(
                "SIS Campus", 
                fy.campus_id, 
                ["title_vn", "title_en"],
                as_dict=True
            )
            if campus_info:
                fy['campus_name'] = campus_info.title_vn
                fy['campus_name_en'] = campus_info.title_en
            else:
                fy['campus_name'] = None
                fy['campus_name_en'] = None
        
        logs.append(f"Tìm thấy {len(finance_years)} năm tài chính")
        
        return list_response(finance_years, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Finance Years Error")
        return error_response(
            message=f"Lỗi khi lấy danh sách năm tài chính: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_finance_year(finance_year_id=None):
    """
    Lấy chi tiết một năm tài chính.
    
    Args:
        finance_year_id: ID của năm tài chính
    
    Returns:
        Thông tin chi tiết năm tài chính
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not finance_year_id:
            finance_year_id = frappe.request.args.get('finance_year_id')
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        logs.append(f"Lấy chi tiết năm tài chính: {finance_year_id}")
        
        if not frappe.db.exists("SIS Finance Year", finance_year_id):
            return not_found_response(f"Không tìm thấy năm tài chính: {finance_year_id}")
        
        fy_doc = frappe.get_doc("SIS Finance Year", finance_year_id)
        
        # Build response data
        data = {
            "name": fy_doc.name,
            "title": fy_doc.title,
            "school_year_id": fy_doc.school_year_id,
            "campus_id": fy_doc.campus_id,
            "is_active": fy_doc.is_active,
            "start_date": str(fy_doc.start_date) if fy_doc.start_date else None,
            "end_date": str(fy_doc.end_date) if fy_doc.end_date else None,
            "description": fy_doc.description,
            "total_students": fy_doc.total_students,
            "total_orders": fy_doc.total_orders,
            "total_amount": fy_doc.total_amount,
            "total_paid": fy_doc.total_paid,
            "created_by": fy_doc.created_by,
            "created_at": str(fy_doc.created_at) if fy_doc.created_at else None
        }
        
        # Lấy thông tin school year
        school_year_info = frappe.db.get_value(
            "SIS School Year", 
            fy_doc.school_year_id, 
            ["title_vn", "title_en"],
            as_dict=True
        )
        if school_year_info:
            data['school_year_name_vn'] = school_year_info.title_vn
            data['school_year_name_en'] = school_year_info.title_en
        
        # Lấy tên campus
        campus_info = frappe.db.get_value(
            "SIS Campus", 
            fy_doc.campus_id, 
            ["title_vn", "title_en"],
            as_dict=True
        )
        if campus_info:
            data['campus_name'] = campus_info.title_vn
            data['campus_name_en'] = campus_info.title_en
        else:
            data['campus_name'] = None
            data['campus_name_en'] = None
        
        return single_item_response(data, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Finance Year Error")
        return error_response(
            message=f"Lỗi khi lấy chi tiết năm tài chính: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def create_finance_year():
    """
    Tạo năm tài chính mới.
    Mỗi năm học chỉ có 1 năm tài chính đi kèm.
    Ngày bắt đầu/kết thúc được lấy tự động từ năm học.
    
    Body:
        title: Tên năm tài chính
        school_year_id: ID năm học
        campus_id: ID campus
        description: Mô tả (optional)
    
    Returns:
        Thông tin năm tài chính vừa tạo
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền tạo năm tài chính", logs=logs)
        
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        logs.append(f"Tạo năm tài chính mới: {json.dumps(data, default=str)}")
        
        # Validate required fields
        required_fields = ['title', 'school_year_id', 'campus_id']
        for field in required_fields:
            if field not in data or not data[field]:
                return validation_error_response(
                    f"Thiếu trường bắt buộc: {field}",
                    {field: [f"Trường {field} là bắt buộc"]}
                )
        
        # Resolve campus_id
        campus_id = _resolve_campus_id(data['campus_id'])
        if not campus_id:
            return error_response("Campus không hợp lệ", logs=logs)
        
        # Kiểm tra năm học có tồn tại không
        school_year = frappe.db.get_value(
            "SIS School Year",
            data['school_year_id'],
            ["name", "start_date", "end_date", "title_vn"],
            as_dict=True
        )
        if not school_year:
            return error_response(f"Năm học không tồn tại: {data['school_year_id']}", logs=logs)
        
        # Kiểm tra xem đã có năm tài chính cho năm học này chưa
        existing_fy = frappe.db.exists("SIS Finance Year", {
            "school_year_id": data['school_year_id'],
            "campus_id": campus_id
        })
        if existing_fy:
            return validation_error_response(
                f"Năm tài chính cho năm học {school_year.title_vn} đã tồn tại",
                {"school_year_id": ["Mỗi năm học chỉ có 1 năm tài chính đi kèm"]}
            )
        
        # Tạo năm tài chính với start_date/end_date từ năm học
        fy_doc = frappe.get_doc({
            "doctype": "SIS Finance Year",
            "title": data['title'],
            "school_year_id": data['school_year_id'],
            "campus_id": campus_id,
            "start_date": school_year.start_date,
            "end_date": school_year.end_date,
            "is_active": 1,  # Mặc định active khi tạo mới
            "description": data.get('description', '')
        })
        
        fy_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã tạo năm tài chính: {fy_doc.name}")
        
        return success_response(
            data={
                "name": fy_doc.name,
                "title": fy_doc.title
            },
            message="Tạo năm tài chính thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Create Finance Year Error")
        return error_response(
            message=f"Lỗi khi tạo năm tài chính: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def update_finance_year():
    """
    Cập nhật năm tài chính.
    Chỉ cho phép cập nhật title và description.
    school_year_id không thể thay đổi sau khi tạo.
    
    Body:
        finance_year_id: ID năm tài chính cần cập nhật
        title: Tên năm tài chính (optional)
        description: Mô tả (optional)
    
    Returns:
        Thông tin năm tài chính sau cập nhật
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền cập nhật năm tài chính", logs=logs)
        
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        finance_year_id = data.get('finance_year_id') or data.get('name')
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        logs.append(f"Cập nhật năm tài chính: {finance_year_id}")
        
        if not frappe.db.exists("SIS Finance Year", finance_year_id):
            return not_found_response(f"Không tìm thấy năm tài chính: {finance_year_id}")
        
        fy_doc = frappe.get_doc("SIS Finance Year", finance_year_id)
        
        # Chỉ cho phép cập nhật title và description
        if 'title' in data:
            fy_doc.title = data['title']
        if 'description' in data:
            fy_doc.description = data['description']
        
        fy_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật năm tài chính: {fy_doc.name}")
        
        return success_response(
            data={"name": fy_doc.name},
            message="Cập nhật năm tài chính thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Update Finance Year Error")
        return error_response(
            message=f"Lỗi khi cập nhật năm tài chính: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def delete_finance_year():
    """
    Xóa năm tài chính.
    
    Body:
        finance_year_id: ID năm tài chính cần xóa
    
    Returns:
        Kết quả xóa
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền xóa năm tài chính", logs=logs)
        
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        finance_year_id = data.get('finance_year_id')
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        logs.append(f"Xóa năm tài chính: {finance_year_id}")
        
        if not frappe.db.exists("SIS Finance Year", finance_year_id):
            return not_found_response(f"Không tìm thấy năm tài chính: {finance_year_id}")
        
        # Kiểm tra có học sinh hay đơn hàng không
        student_count = frappe.db.count("SIS Finance Student", {"finance_year_id": finance_year_id})
        order_count = frappe.db.count("SIS Finance Order", {"finance_year_id": finance_year_id})
        
        if student_count > 0 or order_count > 0:
            return error_response(
                f"Không thể xóa năm tài chính vì còn {student_count} học sinh và {order_count} đơn hàng",
                logs=logs
            )
        
        frappe.delete_doc("SIS Finance Year", finance_year_id, ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã xóa năm tài chính: {finance_year_id}")
        
        return success_response(
            message="Xóa năm tài chính thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Delete Finance Year Error")
        return error_response(
            message=f"Lỗi khi xóa năm tài chính: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def toggle_finance_year_active():
    """
    Bật/tắt trạng thái active của năm tài chính.
    
    Body:
        finance_year_id: ID năm tài chính
        is_active: Trạng thái active mới
    
    Returns:
        Trạng thái mới
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền thay đổi trạng thái", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        finance_year_id = data.get('finance_year_id')
        is_active = data.get('is_active', False)
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Finance Year", finance_year_id):
            return not_found_response(f"Không tìm thấy năm tài chính: {finance_year_id}")
        
        fy_doc = frappe.get_doc("SIS Finance Year", finance_year_id)
        fy_doc.is_active = 1 if is_active else 0
        fy_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã {'kích hoạt' if is_active else 'tắt'} năm tài chính: {finance_year_id}")
        
        return success_response(
            data={
                "name": fy_doc.name,
                "is_active": fy_doc.is_active
            },
            message=f"Đã {'kích hoạt' if is_active else 'tắt'} năm tài chính",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


# ==================== FINANCE STUDENT APIs ====================

@frappe.whitelist()
def sync_students():
    """
    Đồng bộ học sinh từ SIS Class Student vào năm tài chính.
    Lấy danh sách học sinh đã xếp lớp regular trong năm học tương ứng.
    
    Body:
        finance_year_id: ID năm tài chính
    
    Returns:
        Số lượng học sinh đã đồng bộ
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền đồng bộ học sinh", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        finance_year_id = data.get('finance_year_id')
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        logs.append(f"Đồng bộ học sinh cho năm tài chính: {finance_year_id}")
        
        # Lấy thông tin năm tài chính
        fy_doc = frappe.get_doc("SIS Finance Year", finance_year_id)
        school_year_id = fy_doc.school_year_id
        campus_id = fy_doc.campus_id
        
        logs.append(f"Lấy học sinh từ năm học: {school_year_id}, Campus: {campus_id}")
        
        # Lấy danh sách học sinh đã xếp lớp REGULAR trong năm học
        students = frappe.db.sql("""
            SELECT DISTINCT 
                cs.name as class_student_id,
                cs.student_id,
                s.student_name,
                s.student_code,
                c.name as class_id,
                c.title as class_title
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
            INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
            WHERE c.school_year_id = %(school_year_id)s
              AND c.campus_id = %(campus_id)s
              AND (c.class_type = 'regular' OR c.class_type IS NULL OR c.class_type = '')
        """, {
            "school_year_id": school_year_id,
            "campus_id": campus_id
        }, as_dict=True)
        
        logs.append(f"Tìm thấy {len(students)} học sinh đã xếp lớp")
        
        created_count = 0
        skipped_count = 0
        
        for student in students:
            try:
                # Kiểm tra đã có record chưa
                existing = frappe.db.exists("SIS Finance Student", {
                    "finance_year_id": finance_year_id,
                    "student_id": student.student_id
                })
                
                if existing:
                    skipped_count += 1
                    continue
                
                # Tạo record mới
                fs_doc = frappe.get_doc({
                    "doctype": "SIS Finance Student",
                    "finance_year_id": finance_year_id,
                    "student_id": student.student_id,
                    "student_name": student.student_name,
                    "student_code": student.student_code,
                    "campus_id": campus_id,
                    "class_id": student.class_id,
                    "class_title": student.class_title,
                    "synced_at": now(),
                    "synced_from": student.class_student_id
                })
                fs_doc.insert(ignore_permissions=True)
                created_count += 1
                
            except Exception as e:
                logs.append(f"Lỗi khi tạo record cho {student.student_code}: {str(e)}")
                continue
        
        frappe.db.commit()
        
        # Cập nhật thống kê năm tài chính
        fy_doc.update_statistics()
        
        logs.append(f"Đã tạo {created_count} học sinh mới, bỏ qua {skipped_count} học sinh đã tồn tại")
        
        return success_response(
            data={
                "created_count": created_count,
                "skipped_count": skipped_count,
                "total_students": len(students),
                "finance_year_id": finance_year_id
            },
            message=f"Đồng bộ thành công! Tạo mới {created_count} học sinh.",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Sync Finance Students Error")
        return error_response(
            message=f"Lỗi khi đồng bộ học sinh: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_finance_students(finance_year_id=None, search=None, page=1, page_size=20):
    """
    Lấy danh sách học sinh trong năm tài chính.
    
    Args:
        finance_year_id: ID năm tài chính
        search: Tìm kiếm theo tên/mã học sinh
        page: Trang
        page_size: Số lượng mỗi trang
    
    Returns:
        Danh sách học sinh với pagination
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy params
        if not finance_year_id:
            finance_year_id = frappe.request.args.get('finance_year_id')
        if not search:
            search = frappe.request.args.get('search')
        if page == 1:
            page = int(frappe.request.args.get('page', 1))
        if page_size == 20:
            page_size = int(frappe.request.args.get('page_size', 20))
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        logs.append(f"Lấy danh sách học sinh, finance_year: {finance_year_id}, search: {search}")
        
        # Build where clause
        where_clauses = ["finance_year_id = %(finance_year_id)s"]
        params = {"finance_year_id": finance_year_id}
        
        if search:
            where_clauses.append("(student_name LIKE %(search)s OR student_code LIKE %(search)s)")
            params["search"] = f"%{search}%"
        
        where_sql = " AND ".join(where_clauses)
        
        # Đếm tổng số
        total = frappe.db.sql(f"""
            SELECT COUNT(*) as count
            FROM `tabSIS Finance Student`
            WHERE {where_sql}
        """, params, as_dict=True)[0].count
        
        # Tính pagination
        offset = (page - 1) * page_size
        total_pages = (total + page_size - 1) // page_size
        
        # Lấy danh sách học sinh
        students = frappe.db.sql(f"""
            SELECT 
                name, finance_year_id, student_id, student_name, student_code,
                campus_id, class_id, class_title,
                total_amount, paid_amount, outstanding_amount, payment_status
            FROM `tabSIS Finance Student`
            WHERE {where_sql}
            ORDER BY student_name ASC
            LIMIT %(page_size)s OFFSET %(offset)s
        """, {**params, "page_size": page_size, "offset": offset}, as_dict=True)
        
        logs.append(f"Tìm thấy {total} học sinh, trả về {len(students)} học sinh")
        
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
        frappe.log_error(frappe.get_traceback(), "Get Finance Students Error")
        return error_response(
            message=f"Lỗi khi lấy danh sách học sinh: {str(e)}",
            logs=logs
        )


# ==================== FINANCE ORDER APIs ====================

@frappe.whitelist()
def get_orders(finance_year_id=None):
    """
    Lấy danh sách đơn hàng/khoản phí trong năm tài chính.
    
    Args:
        finance_year_id: ID năm tài chính
    
    Returns:
        Danh sách đơn hàng
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not finance_year_id:
            finance_year_id = frappe.request.args.get('finance_year_id')
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        logs.append(f"Lấy danh sách đơn hàng, finance_year: {finance_year_id}")
        
        orders = frappe.get_all(
            "SIS Finance Order",
            filters={"finance_year_id": finance_year_id},
            fields=[
                "name", "title", "order_type", "is_active", "is_required",
                "total_amount", "payment_type", "installment_count", "deadline",
                "total_students", "total_collected", "total_outstanding", "collection_rate",
                "sort_order"
            ],
            order_by="sort_order asc, creation asc"
        )
        
        # Format order_type display
        order_type_display = {
            'tuition': 'Học phí',
            'service': 'Phí dịch vụ',
            'activity': 'Phí hoạt động',
            'other': 'Khác'
        }
        
        for order in orders:
            order['order_type_display'] = order_type_display.get(order.order_type, order.order_type)
            order['payment_type_display'] = 'Chia kỳ' if order.payment_type == 'installment' else 'Một lần'
        
        logs.append(f"Tìm thấy {len(orders)} đơn hàng")
        
        return list_response(orders, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Finance Orders Error")
        return error_response(
            message=f"Lỗi khi lấy danh sách đơn hàng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_order(order_id=None):
    """
    Lấy chi tiết một đơn hàng.
    
    Args:
        order_id: ID đơn hàng
    
    Returns:
        Thông tin chi tiết đơn hàng
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Finance Order", order_id):
            return not_found_response(f"Không tìm thấy đơn hàng: {order_id}")
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        data = {
            "name": order_doc.name,
            "finance_year_id": order_doc.finance_year_id,
            "title": order_doc.title,
            "order_type": order_doc.order_type,
            "is_active": order_doc.is_active,
            "is_required": order_doc.is_required,
            "sort_order": order_doc.sort_order,
            "description": order_doc.description,
            "total_amount": order_doc.total_amount,
            "payment_type": order_doc.payment_type,
            "installment_count": order_doc.installment_count,
            "deadline": str(order_doc.deadline) if order_doc.deadline else None,
            "late_fee_percent": order_doc.late_fee_percent,
            "total_students": order_doc.total_students,
            "total_collected": order_doc.total_collected,
            "total_outstanding": order_doc.total_outstanding,
            "collection_rate": order_doc.collection_rate
        }
        
        return single_item_response(data, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def create_order():
    """
    Tạo đơn hàng/khoản phí mới.
    
    Body:
        finance_year_id, title, order_type, total_amount, payment_type, 
        installment_count, deadline, is_active, is_required, description
    
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
        
        logs.append(f"Tạo đơn hàng mới: {json.dumps(data, default=str)}")
        
        # Validate required fields
        required_fields = ['finance_year_id', 'title', 'total_amount']
        for field in required_fields:
            if field not in data or data[field] is None:
                return validation_error_response(
                    f"Thiếu trường bắt buộc: {field}",
                    {field: [f"Trường {field} là bắt buộc"]}
                )
        
        # Tạo đơn hàng
        order_doc = frappe.get_doc({
            "doctype": "SIS Finance Order",
            "finance_year_id": data['finance_year_id'],
            "title": data['title'],
            "order_type": data.get('order_type', 'tuition'),
            "total_amount": data['total_amount'],
            "payment_type": data.get('payment_type', 'single'),
            "installment_count": data.get('installment_count', 1),
            "deadline": data.get('deadline'),
            "is_active": data.get('is_active', 1),
            "is_required": data.get('is_required', 1),
            "sort_order": data.get('sort_order', 0),
            "description": data.get('description', ''),
            "late_fee_percent": data.get('late_fee_percent', 0)
        })
        
        order_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã tạo đơn hàng: {order_doc.name}")
        
        return success_response(
            data={
                "name": order_doc.name,
                "title": order_doc.title
            },
            message="Tạo đơn hàng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Create Finance Order Error")
        return error_response(
            message=f"Lỗi khi tạo đơn hàng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def update_order():
    """
    Cập nhật đơn hàng.
    
    Body:
        order_id: ID đơn hàng
        Các trường cần cập nhật
    
    Returns:
        Thông tin đơn hàng sau cập nhật
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền cập nhật đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id') or data.get('name')
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Finance Order", order_id):
            return not_found_response(f"Không tìm thấy đơn hàng: {order_id}")
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        # Cập nhật các trường
        updatable_fields = [
            'title', 'order_type', 'total_amount', 'payment_type',
            'installment_count', 'deadline', 'is_active', 'is_required',
            'sort_order', 'description', 'late_fee_percent'
        ]
        
        for field in updatable_fields:
            if field in data:
                setattr(order_doc, field, data[field])
        
        order_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật đơn hàng: {order_doc.name}")
        
        return success_response(
            data={"name": order_doc.name},
            message="Cập nhật đơn hàng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def delete_order():
    """
    Xóa đơn hàng.
    
    Body:
        order_id: ID đơn hàng
    
    Returns:
        Kết quả xóa
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền xóa đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id')
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Finance Order", order_id):
            return not_found_response(f"Không tìm thấy đơn hàng: {order_id}")
        
        # Kiểm tra có order items không
        item_count = frappe.db.count("SIS Finance Order Item", {"order_id": order_id})
        if item_count > 0:
            return error_response(
                f"Không thể xóa đơn hàng vì đã có {item_count} học sinh được gán",
                logs=logs
            )
        
        frappe.delete_doc("SIS Finance Order", order_id, ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã xóa đơn hàng: {order_id}")
        
        return success_response(
            message="Xóa đơn hàng thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


# ==================== ORDER ITEM APIs ====================

@frappe.whitelist()
def assign_order_to_students():
    """
    Gán đơn hàng cho học sinh (tạo order items).
    
    Body:
        order_id: ID đơn hàng
        student_ids: List ID học sinh (SIS Finance Student)
        amount: Số tiền (mặc định lấy từ order)
        deadline: Hạn thanh toán (mặc định lấy từ order)
    
    Returns:
        Số lượng học sinh đã được gán
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền gán đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id')
        student_ids = data.get('student_ids', [])
        
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        if not student_ids:
            return validation_error_response(
                "Thiếu student_ids",
                {"student_ids": ["Danh sách học sinh là bắt buộc"]}
            )
        
        # Convert string to list nếu cần
        if isinstance(student_ids, str):
            student_ids = json.loads(student_ids)
        
        logs.append(f"Gán đơn hàng {order_id} cho {len(student_ids)} học sinh")
        
        # Lấy thông tin order
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        amount = data.get('amount') or order_doc.total_amount
        deadline = data.get('deadline') or order_doc.deadline
        
        created_count = 0
        skipped_count = 0
        
        for student_id in student_ids:
            try:
                # Kiểm tra đã có item chưa
                existing = frappe.db.exists("SIS Finance Order Item", {
                    "order_id": order_id,
                    "finance_student_id": student_id
                })
                
                if existing:
                    skipped_count += 1
                    continue
                
                # Tạo order item
                item_doc = frappe.get_doc({
                    "doctype": "SIS Finance Order Item",
                    "order_id": order_id,
                    "finance_student_id": student_id,
                    "amount": amount,
                    "deadline": deadline
                })
                item_doc.insert(ignore_permissions=True)
                created_count += 1
                
            except Exception as e:
                logs.append(f"Lỗi gán cho học sinh {student_id}: {str(e)}")
                continue
        
        frappe.db.commit()
        
        # Cập nhật thống kê
        order_doc.update_statistics()
        
        logs.append(f"Đã gán cho {created_count} học sinh, bỏ qua {skipped_count} học sinh đã tồn tại")
        
        return success_response(
            data={
                "created_count": created_count,
                "skipped_count": skipped_count,
                "order_id": order_id
            },
            message=f"Gán thành công cho {created_count} học sinh",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Assign Order To Students Error")
        return error_response(
            message=f"Lỗi khi gán đơn hàng: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def assign_order_to_all_students():
    """
    Gán đơn hàng cho tất cả học sinh trong năm tài chính.
    
    Body:
        order_id: ID đơn hàng
    
    Returns:
        Số lượng học sinh đã được gán
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền gán đơn hàng", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id')
        
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        # Lấy thông tin order
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        finance_year_id = order_doc.finance_year_id
        
        # Lấy tất cả học sinh trong năm tài chính
        students = frappe.get_all(
            "SIS Finance Student",
            filters={"finance_year_id": finance_year_id},
            fields=["name"]
        )
        
        student_ids = [s.name for s in students]
        
        logs.append(f"Gán đơn hàng {order_id} cho tất cả {len(student_ids)} học sinh")
        
        # Gọi lại hàm assign_order_to_students
        # Tạo request data mới
        frappe.request.json = {
            "order_id": order_id,
            "student_ids": student_ids
        }
        
        return assign_order_to_students()
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_order_items(order_id=None, search=None, payment_status=None, page=1, page_size=20):
    """
    Lấy danh sách chi tiết học sinh trong đơn hàng.
    
    Args:
        order_id: ID đơn hàng
        search: Tìm kiếm theo tên/mã học sinh
        payment_status: Filter theo trạng thái thanh toán
        page, page_size: Pagination
    
    Returns:
        Danh sách order items
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy params
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        if not search:
            search = frappe.request.args.get('search')
        if not payment_status:
            payment_status = frappe.request.args.get('payment_status')
        if page == 1:
            page = int(frappe.request.args.get('page', 1))
        if page_size == 20:
            page_size = int(frappe.request.args.get('page_size', 20))
        
        if not order_id:
            return validation_error_response(
                "Thiếu order_id",
                {"order_id": ["Order ID là bắt buộc"]}
            )
        
        # Build where clause
        where_clauses = ["foi.order_id = %(order_id)s"]
        params = {"order_id": order_id}
        
        if search:
            where_clauses.append("(foi.student_name LIKE %(search)s OR foi.student_code LIKE %(search)s)")
            params["search"] = f"%{search}%"
        
        if payment_status:
            where_clauses.append("foi.payment_status = %(payment_status)s")
            params["payment_status"] = payment_status
        
        where_sql = " AND ".join(where_clauses)
        
        # Đếm tổng số
        total = frappe.db.sql(f"""
            SELECT COUNT(*) as count
            FROM `tabSIS Finance Order Item` foi
            WHERE {where_sql}
        """, params, as_dict=True)[0].count
        
        # Tính pagination
        offset = (page - 1) * page_size
        total_pages = (total + page_size - 1) // page_size
        
        # Lấy danh sách items
        items = frappe.db.sql(f"""
            SELECT 
                foi.name, foi.order_id, foi.finance_student_id,
                foi.student_name, foi.student_code, foi.class_title,
                foi.amount, foi.discount_amount, foi.final_amount,
                foi.paid_amount, foi.outstanding_amount, foi.payment_status,
                foi.deadline, foi.late_fee, foi.last_payment_date, foi.notes
            FROM `tabSIS Finance Order Item` foi
            WHERE {where_sql}
            ORDER BY foi.student_name ASC
            LIMIT %(page_size)s OFFSET %(offset)s
        """, {**params, "page_size": page_size, "offset": offset}, as_dict=True)
        
        # Format payment_status display
        status_display = {
            'unpaid': 'Chưa đóng',
            'partial': 'Đóng một phần',
            'paid': 'Đã đóng đủ',
            'refunded': 'Đã hoàn tiền'
        }
        
        for item in items:
            item['payment_status_display'] = status_display.get(item.payment_status, item.payment_status)
        
        return success_response(
            data={
                "items": items,
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
def update_payment_status():
    """
    Cập nhật trạng thái thanh toán cho order item.
    
    Body:
        item_id: ID order item
        paid_amount: Số tiền đã đóng
        payment_status: Trạng thái (optional, tự tính nếu không truyền)
        notes: Ghi chú
    
    Returns:
        Thông tin item sau cập nhật
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền cập nhật", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        item_id = data.get('item_id')
        if not item_id:
            return validation_error_response(
                "Thiếu item_id",
                {"item_id": ["Item ID là bắt buộc"]}
            )
        
        if not frappe.db.exists("SIS Finance Order Item", item_id):
            return not_found_response(f"Không tìm thấy: {item_id}")
        
        item_doc = frappe.get_doc("SIS Finance Order Item", item_id)
        
        # Cập nhật paid_amount
        if 'paid_amount' in data:
            item_doc.paid_amount = data['paid_amount']
            item_doc.last_payment_date = nowdate()
        
        # Cập nhật payment_status (nếu có)
        if 'payment_status' in data:
            item_doc.payment_status = data['payment_status']
        
        # Cập nhật notes
        if 'notes' in data:
            item_doc.notes = data['notes']
        
        # Cập nhật discount_amount nếu có
        if 'discount_amount' in data:
            item_doc.discount_amount = data['discount_amount']
        
        item_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật payment status cho: {item_id}")
        
        return success_response(
            data={
                "name": item_doc.name,
                "paid_amount": item_doc.paid_amount,
                "outstanding_amount": item_doc.outstanding_amount,
                "payment_status": item_doc.payment_status
            },
            message="Cập nhật thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def import_payment_status():
    """
    Import trạng thái thanh toán từ file Excel.
    File Excel cần có các cột: student_code, order_id (hoặc order_title), paid_amount
    
    Body (form-data):
        file: File Excel
        finance_year_id: ID năm tài chính
    
    Returns:
        Kết quả import
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền import", logs=logs)
        
        # Lấy file từ request
        files = frappe.request.files
        if 'file' not in files:
            return validation_error_response(
                "Thiếu file",
                {"file": ["File Excel là bắt buộc"]}
            )
        
        file = files['file']
        finance_year_id = frappe.form_dict.get('finance_year_id')
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        logs.append(f"Import payment status cho năm tài chính: {finance_year_id}")
        
        # Đọc file Excel
        import pandas as pd
        df = pd.read_excel(file)
        
        # Validate columns
        required_cols = ['student_code', 'paid_amount']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            return validation_error_response(
                f"File thiếu các cột: {', '.join(missing_cols)}",
                {"file": [f"Cần có các cột: {', '.join(required_cols)}"]}
            )
        
        success_count = 0
        error_count = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                student_code = str(row['student_code']).strip()
                paid_amount = float(row['paid_amount'])
                order_title = row.get('order_title', '') or row.get('order_id', '')
                
                # Tìm finance student
                finance_student = frappe.db.get_value(
                    "SIS Finance Student",
                    {
                        "finance_year_id": finance_year_id,
                        "student_code": student_code
                    },
                    "name"
                )
                
                if not finance_student:
                    errors.append({
                        "row": idx + 2,
                        "error": f"Không tìm thấy học sinh: {student_code}",
                        "data": {"student_code": student_code}
                    })
                    error_count += 1
                    continue
                
                # Tìm order item
                filters = {"finance_student_id": finance_student}
                
                # Nếu có order_title, filter thêm
                if order_title:
                    order_id = frappe.db.get_value(
                        "SIS Finance Order",
                        {"finance_year_id": finance_year_id, "title": order_title},
                        "name"
                    )
                    if order_id:
                        filters["order_id"] = order_id
                
                # Lấy tất cả order items của học sinh này
                items = frappe.get_all(
                    "SIS Finance Order Item",
                    filters=filters,
                    fields=["name"]
                )
                
                if not items:
                    errors.append({
                        "row": idx + 2,
                        "error": f"Không tìm thấy khoản phí cho học sinh: {student_code}",
                        "data": {"student_code": student_code}
                    })
                    error_count += 1
                    continue
                
                # Cập nhật paid_amount cho item đầu tiên (hoặc item theo order_title)
                item_doc = frappe.get_doc("SIS Finance Order Item", items[0].name)
                item_doc.paid_amount = paid_amount
                item_doc.last_payment_date = nowdate()
                item_doc.save(ignore_permissions=True)
                
                success_count += 1
                
            except Exception as e:
                errors.append({
                    "row": idx + 2,
                    "error": str(e),
                    "data": {"student_code": row.get('student_code', '')}
                })
                error_count += 1
        
        frappe.db.commit()
        
        logs.append(f"Import xong: {success_count} thành công, {error_count} lỗi")
        
        return success_response(
            data={
                "success_count": success_count,
                "error_count": error_count,
                "total_count": len(df),
                "errors": errors[:20],  # Chỉ trả về 20 lỗi đầu tiên
                "errors_preview": errors[:10]
            },
            message=f"Import thành công {success_count}/{len(df)} dòng",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Import Payment Status Error")
        return error_response(
            message=f"Lỗi khi import: {str(e)}",
            logs=logs
        )


# ==================== STATISTICS APIs ====================

@frappe.whitelist()
def get_finance_year_statistics(finance_year_id=None):
    """
    Lấy thống kê chi tiết của năm tài chính.
    
    Args:
        finance_year_id: ID năm tài chính
    
    Returns:
        Thống kê tổng hợp
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not finance_year_id:
            finance_year_id = frappe.request.args.get('finance_year_id')
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        # Thống kê học sinh
        student_stats = frappe.db.sql("""
            SELECT 
                COUNT(*) as total_students,
                SUM(CASE WHEN payment_status = 'paid' THEN 1 ELSE 0 END) as paid_students,
                SUM(CASE WHEN payment_status = 'partial' THEN 1 ELSE 0 END) as partial_students,
                SUM(CASE WHEN payment_status = 'unpaid' THEN 1 ELSE 0 END) as unpaid_students
            FROM `tabSIS Finance Student`
            WHERE finance_year_id = %s
        """, (finance_year_id,), as_dict=True)[0]
        
        # Thống kê đơn hàng
        order_stats = frappe.db.sql("""
            SELECT 
                COUNT(*) as total_orders,
                COALESCE(SUM(total_amount), 0) as total_order_amount
            FROM `tabSIS Finance Order`
            WHERE finance_year_id = %s AND is_active = 1
        """, (finance_year_id,), as_dict=True)[0]
        
        # Thống kê thanh toán
        payment_stats = frappe.db.sql("""
            SELECT 
                COALESCE(SUM(foi.amount), 0) as total_amount,
                COALESCE(SUM(foi.paid_amount), 0) as total_paid,
                COALESCE(SUM(foi.outstanding_amount), 0) as total_outstanding
            FROM `tabSIS Finance Order Item` foi
            INNER JOIN `tabSIS Finance Order` fo ON foi.order_id = fo.name
            WHERE fo.finance_year_id = %s
        """, (finance_year_id,), as_dict=True)[0]
        
        # Tính tỷ lệ thu
        collection_rate = 0
        if payment_stats.total_amount > 0:
            collection_rate = (payment_stats.total_paid / payment_stats.total_amount) * 100
        
        return success_response(
            data={
                "students": {
                    "total": student_stats.total_students or 0,
                    "paid": student_stats.paid_students or 0,
                    "partial": student_stats.partial_students or 0,
                    "unpaid": student_stats.unpaid_students or 0
                },
                "orders": {
                    "total": order_stats.total_orders or 0,
                    "total_amount": order_stats.total_order_amount or 0
                },
                "payments": {
                    "total_amount": payment_stats.total_amount or 0,
                    "total_paid": payment_stats.total_paid or 0,
                    "total_outstanding": payment_stats.total_outstanding or 0,
                    "collection_rate": round(collection_rate, 2)
                }
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def export_finance_data(finance_year_id=None):
    """
    Xuất dữ liệu tài chính ra Excel.
    
    Args:
        finance_year_id: ID năm tài chính
    
    Returns:
        Dữ liệu để tạo file Excel
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền xuất dữ liệu", logs=logs)
        
        if not finance_year_id:
            finance_year_id = frappe.request.args.get('finance_year_id')
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        # Lấy danh sách chi tiết
        items = frappe.db.sql("""
            SELECT 
                fs.student_code as 'Mã học sinh',
                fs.student_name as 'Tên học sinh',
                fs.class_title as 'Lớp',
                fo.title as 'Khoản phí',
                fo.order_type as 'Loại',
                foi.amount as 'Số tiền',
                foi.discount_amount as 'Giảm giá',
                foi.final_amount as 'Phải đóng',
                foi.paid_amount as 'Đã đóng',
                foi.outstanding_amount as 'Còn nợ',
                foi.payment_status as 'Trạng thái',
                foi.deadline as 'Hạn thanh toán',
                foi.last_payment_date as 'Ngày thanh toán cuối'
            FROM `tabSIS Finance Order Item` foi
            INNER JOIN `tabSIS Finance Student` fs ON foi.finance_student_id = fs.name
            INNER JOIN `tabSIS Finance Order` fo ON foi.order_id = fo.name
            WHERE fo.finance_year_id = %s
            ORDER BY fs.student_name, fo.sort_order
        """, (finance_year_id,), as_dict=True)
        
        return success_response(
            data={"items": items},
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


# ==================== NEW ORDER APIs (with milestones & fee_lines) ====================

@frappe.whitelist()
def create_order_with_structure():
    """
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
            "description": data.get('description', '')
        })
        
        # Thêm milestones
        milestones = data.get('milestones', [])
        if isinstance(milestones, str):
            milestones = json.loads(milestones)
        
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


# ==================== STUDENT POOL APIs ====================

@frappe.whitelist()
def add_students_to_order_v2():
    """
    Thêm học sinh vào đơn hàng (version mới).
    Tạo Order Student và Student Order Lines (rỗng, chưa có số tiền).
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
        
        created_count = 0
        skipped_count = 0
        
        for student_id in student_ids:
            try:
                # Kiểm tra đã có chưa
                existing = frappe.db.exists("SIS Finance Order Student", {
                    "order_id": order_id,
                    "finance_student_id": student_id
                })
                
                if existing:
                    skipped_count += 1
                    continue
                
                # Tạo Order Student
                order_student = frappe.get_doc({
                    "doctype": "SIS Finance Order Student",
                    "order_id": order_id,
                    "finance_student_id": student_id,
                    "data_status": "pending",
                    "payment_status": "unpaid"
                })
                
                # Tạo Student Order Lines từ fee_lines của order
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
        
        logs.append(f"Đã thêm {created_count} học sinh, bỏ qua {skipped_count}")
        
        return success_response(
            data={
                "created_count": created_count,
                "skipped_count": skipped_count,
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
        
        # Get students
        students = frappe.db.sql(f"""
            SELECT 
                os.name, os.order_id, os.finance_student_id,
                os.student_name, os.student_code, os.class_title,
                os.data_status, os.total_amount, os.paid_amount,
                os.outstanding_amount, os.payment_status,
                os.latest_debit_note_version, os.latest_debit_note_url
            FROM `tabSIS Finance Order Student` os
            WHERE {where_sql}
            ORDER BY os.student_name ASC
            LIMIT %(page_size)s OFFSET %(offset)s
        """, {**params, "page_size": page_size, "offset": offset}, as_dict=True)
        
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


# ==================== EXCEL IMPORT/EXPORT APIs ====================

@frappe.whitelist()
def export_order_excel_template(order_id=None):
    """
    Export Excel template để admin điền số tiền.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền xuất template", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        # Build headers
        headers = ["student_code", "student_name", "class_title"]
        header_labels = ["Mã học sinh", "Tên học sinh", "Lớp"]
        
        # Sắp xếp milestones theo payment_scheme rồi milestone_number
        sorted_milestones = sorted(
            order_doc.milestones, 
            key=lambda m: (m.payment_scheme or 'yearly', m.milestone_number)
        )
        
        # Thêm các cột số tiền theo từng line và milestone
        for line in order_doc.fee_lines:
            # Bỏ qua dòng tự động tính (total, subtotal có formula)
            if line.line_type in ['total', 'subtotal'] and line.formula:
                continue
            
            for milestone in sorted_milestones:
                scheme = milestone.payment_scheme or 'yearly'
                # Key format: {line_number}_{scheme}_{milestone_number}
                col_name = f"{line.line_number}_{scheme}_{milestone.milestone_number}"
                headers.append(col_name)
                
                # Label hiển thị
                scheme_label = "Năm" if scheme == 'yearly' else "Kỳ"
                header_labels.append(f"{line.line_number} - {scheme_label} {milestone.milestone_number}: {milestone.title}")
        
        headers.append("note")
        header_labels.append("Ghi chú")
        
        # Get students
        students = frappe.get_all(
            "SIS Finance Order Student",
            filters={"order_id": order_id},
            fields=["name", "student_code", "student_name", "class_title", "notes"]
        )
        
        # Build rows
        rows = []
        for student in students:
            row = {
                "student_code": student.student_code,
                "student_name": student.student_name,
                "class_title": student.class_title,
                "note": student.notes or ""
            }
            
            # Thêm các cột số tiền (rỗng)
            for line in order_doc.fee_lines:
                if line.line_type in ['total', 'subtotal'] and line.formula:
                    continue
                for milestone in sorted_milestones:
                    scheme = milestone.payment_scheme or 'yearly'
                    col_name = f"{line.line_number}_{scheme}_{milestone.milestone_number}"
                    row[col_name] = ""
            
            rows.append(row)
        
        return success_response(
            data={
                "headers": headers,
                "header_labels": header_labels,
                "rows": rows,
                "order_title": order_doc.title,
                "milestones": [
                    {
                        "payment_scheme": m.payment_scheme or 'yearly',
                        "number": m.milestone_number, 
                        "title": m.title,
                        "key": f"{m.payment_scheme or 'yearly'}_{m.milestone_number}"
                    } for m in sorted_milestones
                ],
                "fee_lines": [{"number": l.line_number, "title_vn": l.title_vn, "title_en": l.title_en} for l in order_doc.fee_lines]
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def import_student_fee_data():
    """
    Import số tiền từ Excel.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền import", logs=logs)
        
        files = frappe.request.files
        if 'file' not in files:
            return validation_error_response("Thiếu file", {"file": ["File Excel là bắt buộc"]})
        
        file = files['file']
        order_id = frappe.form_dict.get('order_id')
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        if not order_doc.can_import_data():
            return error_response(f"Không thể import khi status = {order_doc.status}")
        
        logs.append(f"Import số tiền cho đơn hàng: {order_id}")
        
        # Đọc Excel
        import pandas as pd
        df = pd.read_excel(file)
        
        # Validate cột student_code
        if 'student_code' not in df.columns:
            return validation_error_response("Thiếu cột student_code", {"file": ["Cần có cột student_code"]})
        
        success_count = 0
        error_count = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                student_code = str(row['student_code']).strip()
                
                # Tìm Order Student
                order_student = frappe.db.get_value(
                    "SIS Finance Order Student",
                    {"order_id": order_id, "student_code": student_code},
                    "name"
                )
                
                if not order_student:
                    errors.append({"row": idx + 2, "error": f"Không tìm thấy học sinh: {student_code}"})
                    error_count += 1
                    continue
                
                order_student_doc = frappe.get_doc("SIS Finance Order Student", order_student)
                
                # Cập nhật số tiền cho từng line
                for fee_line in order_student_doc.fee_lines:
                    if fee_line.is_calculated:
                        continue
                    
                    amounts = {}
                    for milestone in order_doc.milestones:
                        scheme = milestone.payment_scheme or 'yearly'
                        # Dùng key format mới: {line_number}_{scheme}_{milestone_number}
                        col_name = f"{fee_line.line_number}_{scheme}_{milestone.milestone_number}"
                        if col_name in row and pd.notna(row[col_name]):
                            try:
                                # Key trong amounts_json: {scheme}_{milestone_number}
                                amounts[f"{scheme}_{milestone.milestone_number}"] = float(row[col_name])
                            except (ValueError, TypeError):
                                pass
                    
                    if amounts:
                        fee_line.amounts_json = json.dumps(amounts)
                
                # Tính toán các dòng total/subtotal
                _calculate_totals_v2(order_student_doc, order_doc)
                
                # Cập nhật note
                if 'note' in row and pd.notna(row['note']):
                    order_student_doc.notes = str(row['note'])
                
                order_student_doc.save(ignore_permissions=True)
                success_count += 1
                
            except Exception as e:
                errors.append({"row": idx + 2, "error": str(e), "student_code": row.get('student_code', '')})
                error_count += 1
        
        frappe.db.commit()
        
        # Cập nhật statistics
        order_doc.update_statistics()
        order_doc.update_status_based_on_students()
        
        logs.append(f"Import xong: {success_count} thành công, {error_count} lỗi")
        
        return success_response(
            data={
                "success_count": success_count,
                "error_count": error_count,
                "total_count": len(df),
                "errors": errors[:20]
            },
            message=f"Import thành công {success_count}/{len(df)} dòng",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Import Student Fee Data Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


def _calculate_totals_v2(order_student_doc, order_doc):
    """
    Tính toán các dòng total/subtotal dựa trên formula.
    """
    import re
    
    # Lấy tất cả amounts theo line_number
    line_amounts = {}
    for fee_line in order_student_doc.fee_lines:
        if fee_line.amounts_json:
            try:
                line_amounts[fee_line.line_number] = json.loads(fee_line.amounts_json)
            except:
                line_amounts[fee_line.line_number] = {}
    
    # Lấy danh sách milestone keys với format mới: {scheme}_{number}
    milestone_keys = [
        f"{m.payment_scheme or 'yearly'}_{m.milestone_number}" 
        for m in order_doc.milestones
    ]
    
    # Tính toán các dòng có formula
    for fee_line in order_student_doc.fee_lines:
        order_line = order_doc.get_fee_line(fee_line.line_number)
        if not order_line or not order_line.formula:
            continue
        
        formula = order_line.formula
        calculated_amounts = {}
        
        for m_key in milestone_keys:
            eval_formula = formula
            matches = re.findall(r'\(([0-9.]+)\)', formula)
            
            for match in matches:
                value = line_amounts.get(match, {}).get(m_key, 0) or 0
                eval_formula = eval_formula.replace(f"({match})", str(value))
            
            try:
                result = eval(eval_formula)
                calculated_amounts[m_key] = result
            except:
                calculated_amounts[m_key] = 0
        
        fee_line.amounts_json = json.dumps(calculated_amounts)
        fee_line.is_calculated = 1


# ==================== SEND BATCH APIs ====================

@frappe.whitelist()
def create_send_batch():
    """
    Tạo đợt gửi thông báo mới.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền tạo đợt gửi", logs=logs)
        
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        order_id = data.get('order_id')
        milestone_number = data.get('milestone_number')
        student_ids = data.get('student_ids', [])
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        if not milestone_number:
            return validation_error_response("Thiếu milestone_number", {"milestone_number": ["Bắt buộc"]})
        
        order_doc = frappe.get_doc("SIS Finance Order", order_id)
        
        if not order_doc.can_create_send_batch():
            return error_response(f"Không thể tạo đợt gửi khi status = {order_doc.status}")
        
        if isinstance(student_ids, str):
            student_ids = json.loads(student_ids)
        
        # Nếu không chỉ định student_ids, lấy tất cả chưa đóng
        if not student_ids:
            students = frappe.get_all(
                "SIS Finance Order Student",
                filters={"order_id": order_id, "payment_status": ["!=", "paid"]},
                fields=["name"]
            )
            student_ids = [s.name for s in students]
        
        if not student_ids:
            return error_response("Không có học sinh nào để gửi")
        
        logs.append(f"Tạo đợt gửi cho {len(student_ids)} học sinh, mốc {milestone_number}")
        
        # Tạo Send Batch
        batch_doc = frappe.get_doc({
            "doctype": "SIS Finance Send Batch",
            "order_id": order_id,
            "milestone_number": int(milestone_number),
            "total_students": len(student_ids),
            "status": "draft",
            "notification_template": data.get('notification_template', ''),
            "notification_channel": data.get('notification_channel', 'app')
        })
        batch_doc.insert(ignore_permissions=True)
        
        # Tạo Debit Note History cho từng học sinh
        for student_id in student_ids:
            try:
                order_student = frappe.get_doc("SIS Finance Order Student", student_id)
                
                # Tạo snapshot số tiền
                amount_snapshot = {}
                for fee_line in order_student.fee_lines:
                    if fee_line.amounts_json:
                        amount_snapshot[fee_line.line_number] = json.loads(fee_line.amounts_json)
                
                # Tạo Debit Note History
                history_doc = frappe.get_doc({
                    "doctype": "SIS Finance Debit Note History",
                    "order_student_id": student_id,
                    "send_batch_id": batch_doc.name,
                    "milestone_number": int(milestone_number),
                    "amount_snapshot": json.dumps(amount_snapshot)
                })
                history_doc.insert(ignore_permissions=True)
                
            except Exception as e:
                logs.append(f"Lỗi tạo history cho {student_id}: {str(e)}")
        
        frappe.db.commit()
        
        return success_response(
            data={
                "name": batch_doc.name,
                "batch_number": batch_doc.batch_number,
                "milestone_number": batch_doc.milestone_number,
                "total_students": batch_doc.total_students,
                "status": batch_doc.status
            },
            message=f"Tạo đợt gửi #{batch_doc.batch_number} thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Create Send Batch Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_send_batches(order_id=None):
    """
    Lấy danh sách các đợt gửi của đơn hàng.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        batches = frappe.get_all(
            "SIS Finance Send Batch",
            filters={"order_id": order_id},
            fields=[
                "name", "batch_number", "milestone_number", "milestone_title",
                "status", "total_students", "sent_at", "sent_by",
                "sent_count", "failed_count", "read_count"
            ],
            order_by="batch_number desc"
        )
        
        return list_response(batches, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_unpaid_students(order_id=None):
    """
    Lấy danh sách học sinh chưa đóng tiền.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_id:
            order_id = frappe.request.args.get('order_id')
        
        if not order_id:
            return validation_error_response("Thiếu order_id", {"order_id": ["Bắt buộc"]})
        
        students = frappe.get_all(
            "SIS Finance Order Student",
            filters={
                "order_id": order_id,
                "payment_status": ["!=", "paid"],
                "data_status": "complete"
            },
            fields=["name", "student_code", "student_name", "class_title", "total_amount", "paid_amount", "outstanding_amount", "payment_status"]
        )
        
        return list_response(students, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


# ==================== DEBIT NOTE APIs ====================

@frappe.whitelist()
def get_debit_note_preview(order_student_id=None, milestone_key=None):
    """
    Lấy data để preview Debit Note cho học sinh.
    Trả về số tiền cho TẤT CẢ các mốc (4 cột).
    
    Args:
        order_student_id: ID của SIS Finance Order Student
        milestone_key: Optional - key của mốc highlight (VD: yearly_1, semester_2)
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_student_id:
            order_student_id = frappe.request.args.get('order_student_id')
        if not milestone_key:
            milestone_key = frappe.request.args.get('milestone_key')
        
        if not order_student_id:
            return validation_error_response("Thiếu order_student_id", {"order_student_id": ["Bắt buộc"]})
        
        order_student = frappe.get_doc("SIS Finance Order Student", order_student_id)
        order_doc = frappe.get_doc("SIS Finance Order", order_student.order_id)
        
        # Sắp xếp milestones theo payment_scheme rồi milestone_number
        sorted_milestones = sorted(
            order_doc.milestones,
            key=lambda m: (m.payment_scheme or 'yearly', m.milestone_number)
        )
        
        # Nếu không có milestone_key, dùng milestone đầu tiên
        if not milestone_key and sorted_milestones:
            first_m = sorted_milestones[0]
            milestone_key = f"{first_m.payment_scheme or 'yearly'}_{first_m.milestone_number}"
        
        lines = []
        for fee_line in order_student.fee_lines:
            order_line = order_doc.get_fee_line(fee_line.line_number)
            
            amounts = {}
            if fee_line.amounts_json:
                try:
                    amounts = json.loads(fee_line.amounts_json)
                except:
                    pass
            
            lines.append({
                "line_number": fee_line.line_number,
                "line_type": fee_line.line_type,
                "title_en": order_line.title_en if order_line else "",
                "title_vn": order_line.title_vn if order_line else "",
                "is_compulsory": order_line.is_compulsory if order_line else 0,
                "is_deduction": order_line.is_deduction if order_line else 0,
                "note": fee_line.note or (order_line.note if order_line else ""),
                "amounts": amounts  # Tất cả amounts: {yearly_1: X, yearly_2: Y, semester_1: Z, semester_2: W}
            })
        
        # Nhóm milestones theo payment_scheme
        yearly_milestones = []
        semester_milestones = []
        
        for m in sorted_milestones:
            scheme = m.payment_scheme or 'yearly'
            m_key = f"{scheme}_{m.milestone_number}"
            m_data = {
                "key": m_key,
                "payment_scheme": scheme,
                "milestone_number": m.milestone_number,
                "title": m.title,
                "column_header_en": m.column_header_en or m.title,
                "column_header_vn": m.column_header_vn or m.title,
                "deadline_date": str(m.deadline_date) if m.deadline_date else None,
                "is_current": m_key == milestone_key
            }
            if scheme == 'yearly':
                yearly_milestones.append(m_data)
            else:
                semester_milestones.append(m_data)
        
        return success_response(
            data={
                "student": {
                    "name": order_student.name,
                    "student_code": order_student.student_code,
                    "student_name": order_student.student_name,
                    "class_title": order_student.class_title
                },
                "order": {
                    "name": order_doc.name,
                    "title": order_doc.title
                },
                "current_milestone_key": milestone_key,
                "yearly_milestones": yearly_milestones,    # Đóng cả năm
                "semester_milestones": semester_milestones, # Đóng theo kỳ
                "lines": lines
            },
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def get_debit_note_history(order_student_id=None):
    """
    Lấy lịch sử các phiên bản Debit Note của học sinh.
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        if not order_student_id:
            order_student_id = frappe.request.args.get('order_student_id')
        
        if not order_student_id:
            return validation_error_response("Thiếu order_student_id", {"order_student_id": ["Bắt buộc"]})
        
        histories = frappe.get_all(
            "SIS Finance Debit Note History",
            filters={"order_student_id": order_student_id},
            fields=[
                "name", "version", "milestone_number", "milestone_title",
                "generated_at", "pdf_url", "sent_via", "sent_at", "read_at"
            ],
            order_by="version desc"
        )
        
        return list_response(histories, logs=logs)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        return error_response(f"Lỗi: {str(e)}", logs=logs)

