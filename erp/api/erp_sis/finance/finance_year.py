"""
Finance Year APIs
Quản lý năm tài chính - CRUD operations và đồng bộ học sinh.
"""

import frappe
from frappe import _
from frappe.utils import now
import json

from erp.utils.api_response import (
    validation_error_response,
    list_response,
    error_response,
    success_response,
    single_item_response,
    not_found_response
)

from .utils import _check_admin_permission, _resolve_campus_id


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


@frappe.whitelist()
def sync_students():
    """
    Đồng bộ học sinh từ SIS Class Student vào năm tài chính.
    Hỗ trợ 2 mode:
    - 'current': Lấy học sinh từ năm học hiện tại (bổ sung học sinh mới)
    - 'previous': Lấy học sinh từ năm học trước, loại trừ khối 12 (chuẩn bị năm N+1)
    
    Body:
        finance_year_id: ID năm tài chính
        mode: 'current' (mặc định) hoặc 'previous'
    
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
        mode = data.get('mode', 'current')  # 'current' hoặc 'previous'
        
        if not finance_year_id:
            return validation_error_response(
                "Thiếu finance_year_id",
                {"finance_year_id": ["Finance Year ID là bắt buộc"]}
            )
        
        logs.append(f"Đồng bộ học sinh cho năm tài chính: {finance_year_id}, mode: {mode}")
        
        # Lấy thông tin năm tài chính
        fy_doc = frappe.get_doc("SIS Finance Year", finance_year_id)
        campus_id = fy_doc.campus_id
        
        if mode == 'previous':
            # Mode: Lấy học sinh từ năm học trước, loại trừ khối 12
            result = _sync_from_previous_year(fy_doc, campus_id, logs)
        else:
            # Mode: Lấy học sinh từ năm học hiện tại (default)
            result = _sync_from_current_year(fy_doc, campus_id, logs)
        
        return result
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Sync Finance Students Error")
        return error_response(
            message=f"Lỗi khi đồng bộ học sinh: {str(e)}",
            logs=logs
        )


def _sync_from_current_year(fy_doc, campus_id, logs):
    """
    Đồng bộ học sinh từ năm học hiện tại (cùng school_year_id).
    Dùng khi N+1 đã trở thành năm hiện tại, cần bổ sung học sinh mới.
    """
    school_year_id = fy_doc.school_year_id
    finance_year_id = fy_doc.name
    
    logs.append(f"Lấy học sinh từ năm học hiện tại: {school_year_id}, Campus: {campus_id}")
    
    # Lấy danh sách học sinh đã xếp lớp REGULAR trong năm học hiện tại
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
    
    logs.append(f"Tìm thấy {len(students)} học sinh đã xếp lớp trong năm học hiện tại")
    
    return _create_finance_students(finance_year_id, campus_id, students, logs, "current")


def _sync_from_previous_year(fy_doc, campus_id, logs):
    """
    Đồng bộ học sinh từ năm học trước (N-1), loại trừ khối 12.
    Dùng khi tạo Finance Year N+1, mặc định học sinh lớp 1-11 sẽ tiếp tục theo học.
    """
    finance_year_id = fy_doc.name
    current_school_year_id = fy_doc.school_year_id
    
    logs.append(f"Tìm năm học trước của: {current_school_year_id}")
    
    # Lấy thông tin năm học hiện tại để tìm năm học trước
    current_sy = frappe.db.get_value(
        "SIS School Year",
        current_school_year_id,
        ["start_date", "campus_id"],
        as_dict=True
    )
    
    if not current_sy:
        return error_response(f"Không tìm thấy năm học: {current_school_year_id}", logs=logs)
    
    # Tìm năm học trước đó (có start_date nhỏ hơn và cùng campus)
    previous_sy = frappe.db.sql("""
        SELECT name, title_vn, start_date
        FROM `tabSIS School Year`
        WHERE campus_id = %(campus_id)s
          AND start_date < %(current_start_date)s
        ORDER BY start_date DESC
        LIMIT 1
    """, {
        "campus_id": campus_id,
        "current_start_date": current_sy.start_date
    }, as_dict=True)
    
    if not previous_sy:
        return error_response(
            "Không tìm thấy năm học trước. Vui lòng dùng mode 'current' để sync từ năm học hiện tại.",
            logs=logs
        )
    
    previous_school_year_id = previous_sy[0].name
    logs.append(f"Năm học trước: {previous_school_year_id} ({previous_sy[0].title_vn})")
    
    # Lấy danh sách học sinh từ năm học trước, loại trừ khối 12
    # JOIN với SIS Education Grade để kiểm tra grade_code không phải "12"
    students = frappe.db.sql("""
        SELECT DISTINCT 
            cs.name as class_student_id,
            cs.student_id,
            s.student_name,
            s.student_code,
            c.name as class_id,
            c.title as class_title,
            eg.grade_code
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
        INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
        LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
        WHERE c.school_year_id = %(school_year_id)s
          AND c.campus_id = %(campus_id)s
          AND (c.class_type = 'regular' OR c.class_type IS NULL OR c.class_type = '')
          AND (
              eg.grade_code IS NULL 
              OR eg.grade_code != '12'
          )
          AND (
              c.title IS NULL 
              OR c.title NOT LIKE '%%12%%'
          )
    """, {
        "school_year_id": previous_school_year_id,
        "campus_id": campus_id
    }, as_dict=True)
    
    logs.append(f"Tìm thấy {len(students)} học sinh từ năm học trước (đã loại trừ khối 12)")
    
    return _create_finance_students(finance_year_id, campus_id, students, logs, "previous")


def _create_finance_students(finance_year_id, campus_id, students, logs, mode):
    """
    Tạo Finance Student records từ danh sách học sinh.
    """
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
                "class_id": student.get("class_id"),
                "class_title": student.get("class_title"),
                "synced_at": now(),
                "synced_from": student.class_student_id,
                "sync_mode": mode  # Ghi nhận mode sync
            })
            fs_doc.insert(ignore_permissions=True)
            created_count += 1
            
        except Exception as e:
            logs.append(f"Lỗi khi tạo record cho {student.student_code}: {str(e)}")
            continue
    
    frappe.db.commit()
    
    # Cập nhật thống kê năm tài chính
    fy_doc = frappe.get_doc("SIS Finance Year", finance_year_id)
    fy_doc.update_statistics()
    
    mode_text = "năm học trước" if mode == "previous" else "năm học hiện tại"
    logs.append(f"Đã tạo {created_count} học sinh mới từ {mode_text}, bỏ qua {skipped_count} học sinh đã tồn tại")
    
    return success_response(
        data={
            "created_count": created_count,
            "skipped_count": skipped_count,
            "total_students": len(students),
            "finance_year_id": finance_year_id,
            "mode": mode
        },
        message=f"Đồng bộ thành công! Tạo mới {created_count} học sinh từ {mode_text}.",
        logs=logs
    )
