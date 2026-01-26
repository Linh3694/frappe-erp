"""
Parent Portal Menu Registration API
Handles menu registration (Á/Âu) for parent portal

API endpoints cho phụ huynh đăng ký suất ăn Á/Âu qua Parent Portal.
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, now, get_first_day, get_last_day
import json
from datetime import datetime, timedelta
from calendar import monthrange
from erp.utils.api_response import (
    validation_error_response, 
    list_response, 
    error_response, 
    success_response, 
    single_item_response,
    not_found_response
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


def _get_parent_students(parent_id, education_stage_id=None):
    """
    Lấy danh sách học sinh của phụ huynh.
    Có thể lọc theo cấp học (education_stage_id).
    """
    if not parent_id:
        return []
    
    # Query CRM Family Relationship để lấy danh sách học sinh
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": parent_id},
        fields=["student", "relationship_type", "key_person"]
    )
    
    students_dict = {}
    for rel in relationships:
        if rel.student in students_dict:
            continue
            
        try:
            student = frappe.get_doc("CRM Student", rel.student)
            
            # Lấy lớp hiện tại
            current_class = _get_student_current_class(student.name, student.campus_id)
            
            # Kiểm tra education_stage nếu có filter
            if education_stage_id and current_class:
                class_education_stage = _get_class_education_stage(current_class.get("class_id"))
                if class_education_stage != education_stage_id:
                    continue
            
            # Lấy ảnh học sinh
            sis_photo = _get_student_photo(student.name)
            
            students_dict[student.name] = {
                "name": student.name,
                "student_name": student.student_name,
                "student_code": student.student_code,
                "campus_id": student.campus_id,
                "current_class": current_class.get("class_title") if current_class else None,
                "current_class_id": current_class.get("class_id") if current_class else None,
                "sis_photo": sis_photo
            }
        except Exception as e:
            frappe.logger().error(f"Error getting student {rel.student}: {str(e)}")
            continue
    
    return list(students_dict.values())


def _get_student_current_class(student_id, campus_id=None):
    """Lấy lớp hiện tại của học sinh"""
    if not student_id:
        return None
    
    if not campus_id:
        campus_id = frappe.db.get_value("CRM Student", student_id, "campus_id")
    
    if not campus_id:
        return None
    
    # Lấy năm học hiện tại
    current_school_year = frappe.db.get_value(
        "SIS School Year",
        {"is_enable": 1, "campus_id": campus_id},
        "name",
        order_by="start_date desc"
    )
    
    if not current_school_year:
        return None
    
    # Tìm lớp regular của học sinh
    class_student = frappe.db.sql("""
        SELECT cs.class_id, c.title as class_title
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
        WHERE cs.student_id = %s
        AND cs.school_year_id = %s
        AND (c.class_type = 'regular' OR c.class_type IS NULL OR c.class_type = '')
        LIMIT 1
    """, (student_id, current_school_year), as_dict=True)
    
    if class_student:
        return {
            "class_id": class_student[0].class_id,
            "class_title": class_student[0].class_title
        }
    
    return None


def _get_class_education_stage(class_id):
    """Lấy education_stage_id của lớp"""
    if not class_id:
        return None
    
    education_grade = frappe.db.get_value("SIS Class", class_id, "education_grade")
    if not education_grade:
        return None
    
    education_stage = frappe.db.get_value("SIS Education Grade", education_grade, "education_stage_id")
    return education_stage


def _get_student_photo(student_id):
    """Lấy ảnh học sinh từ SIS Photo"""
    try:
        current_school_year = frappe.db.get_value(
            "SIS School Year",
            {"is_enable": 1},
            "name",
            order_by="start_date desc"
        )
        
        sis_photos = frappe.db.sql("""
            SELECT photo
            FROM `tabSIS Photo`
            WHERE student_id = %s
                AND type = 'student'
                AND status = 'Active'
            ORDER BY 
                CASE WHEN school_year_id = %s THEN 0 ELSE 1 END,
                upload_date DESC,
                creation DESC
            LIMIT 1
        """, (student_id, current_school_year), as_dict=True)

        if sis_photos:
            return sis_photos[0]["photo"]
    except Exception as e:
        frappe.logger().error(f"Error getting photo for {student_id}: {str(e)}")
    
    return None


def _get_wednesdays_in_month(year, month):
    """
    [DEPRECATED] Lấy danh sách các ngày Thứ 4 trong tháng.
    Sử dụng registration_dates từ doctype thay thế.
    """
    wednesdays = []
    
    # Lấy số ngày trong tháng
    _, num_days = monthrange(year, month)
    
    for day in range(1, num_days + 1):
        date = datetime(year, month, day)
        # Thứ 4 = weekday() == 2 (Monday = 0)
        if date.weekday() == 2:
            wednesdays.append(date.strftime('%Y-%m-%d'))
    
    return wednesdays


def _get_registration_dates(period_id):
    """Lấy danh sách ngày đăng ký từ child table"""
    dates = frappe.get_all(
        "SIS Menu Registration Period Date",
        filters={"parent": period_id},
        fields=["date"],
        order_by="date asc"
    )
    return [str(d.date) for d in dates]


def _check_parent_timeline(period):
    """Kiểm tra có trong timeline phụ huynh không"""
    from frappe.utils import now_datetime, get_datetime
    now = now_datetime()
    
    if period.get("parent_start_datetime") and period.get("parent_end_datetime"):
        start = get_datetime(period.parent_start_datetime)
        end = get_datetime(period.parent_end_datetime)
        return start <= now <= end
    
    # Fallback: kiểm tra theo deprecated fields
    if period.get("start_date") and period.get("end_date"):
        today = getdate(nowdate())
        return getdate(period.start_date) <= today <= getdate(period.end_date)
    
    return False


def _check_teacher_timeline(period):
    """
    Kiểm tra có trong timeline GVCN không.
    Ưu tiên: teacher_timeline > parent_timeline > start_date/end_date
    """
    from frappe.utils import now_datetime, get_datetime, getdate
    now = now_datetime()
    today = getdate()
    
    # Ưu tiên 1: Teacher timeline
    if period.get("teacher_start_datetime") and period.get("teacher_end_datetime"):
        start = get_datetime(period.teacher_start_datetime)
        end = get_datetime(period.teacher_end_datetime)
        return start <= now <= end
    
    # Ưu tiên 2: Parent timeline (GVCN có thể dùng nếu chưa có teacher timeline riêng)
    if period.get("parent_start_datetime") and period.get("parent_end_datetime"):
        start = get_datetime(period.parent_start_datetime)
        end = get_datetime(period.parent_end_datetime)
        return start <= now <= end
    
    # Ưu tiên 3: Legacy start_date/end_date
    if period.get("start_date") and period.get("end_date"):
        start = getdate(period.start_date)
        end = getdate(period.end_date)
        return start <= today <= end
    
    return False


def _get_current_teacher_class():
    """Lấy lớp chủ nhiệm của giáo viên đang đăng nhập"""
    user_email = frappe.session.user
    if user_email == "Guest":
        return None
    
    # Lấy teacher từ email
    teacher = frappe.db.get_value("SIS Teacher", {"user_id": user_email}, "name")
    if not teacher:
        return None
    
    # Lấy năm học hiện tại
    current_year = frappe.db.get_value(
        "SIS School Year",
        {"is_enable": 1},
        "name"
    )
    
    if not current_year:
        return None
    
    # Lấy lớp chủ nhiệm
    homeroom_class = frappe.db.get_value(
        "SIS Class",
        {
            "homeroom_teacher": teacher,
            "school_year_id": current_year
        },
        ["name", "class_title", "education_grade"],
        as_dict=True
    )
    
    return homeroom_class


@frappe.whitelist()
def get_active_period():
    """
    Lấy kỳ đăng ký suất ăn đang mở cho phụ huynh.
    Trả về thông tin kỳ đăng ký và danh sách ngày đăng ký từ registration_dates.
    """
    logs = []
    
    try:
        logs.append("Đang lấy kỳ đăng ký suất ăn đang mở")
        
        # Lấy thông tin phụ huynh
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent ID: {parent_id}")
        
        # Tìm kỳ đăng ký đang mở (status = 'Open') và trong parent timeline
        from frappe.utils import now_datetime
        now = now_datetime()
        
        # Query kỳ đăng ký - ưu tiên check parent_start_datetime/parent_end_datetime
        period = frappe.db.sql("""
            SELECT 
                name, title, month, year, 
                start_date, end_date,
                parent_start_datetime, parent_end_datetime,
                teacher_start_datetime, teacher_end_datetime,
                status, school_year_id
            FROM `tabSIS Menu Registration Period`
            WHERE status = 'Open'
            AND (
                (parent_start_datetime IS NOT NULL AND parent_start_datetime <= %s AND parent_end_datetime >= %s)
                OR (parent_start_datetime IS NULL AND start_date <= %s AND end_date >= %s)
            )
            ORDER BY creation DESC
            LIMIT 1
        """, (now, now, getdate(nowdate()), getdate(nowdate())), as_dict=True)
        
        if not period:
            logs.append("Không có kỳ đăng ký suất ăn nào đang mở cho phụ huynh")
            return success_response(
                data=None,
                message="Không có kỳ đăng ký suất ăn nào đang mở",
                logs=logs
            )
        
        period = period[0]
        logs.append(f"Tìm thấy kỳ: {period.name}")
        
        # Kiểm tra có trong parent timeline không
        if not _check_parent_timeline(period):
            logs.append("Không trong thời gian đăng ký của phụ huynh")
            return success_response(
                data=None,
                message="Chưa đến hoặc đã hết thời gian đăng ký",
                logs=logs
            )
        
        # Lấy education_stages từ child table
        education_stages = frappe.get_all(
            "SIS Menu Registration Period Education Stage",
            filters={"parent": period.name},
            fields=["education_stage_id"]
        )
        education_stage_ids = [es.education_stage_id for es in education_stages]
        
        # Lấy danh sách học sinh thuộc các cấp học áp dụng
        students = []
        for stage_id in education_stage_ids:
            stage_students = _get_parent_students(parent_id, stage_id)
            students.extend(stage_students)
        
        # Loại bỏ trùng lặp
        seen = set()
        unique_students = []
        for s in students:
            if s["name"] not in seen:
                seen.add(s["name"])
                unique_students.append(s)
        students = unique_students
        
        if not students:
            logs.append("Không có học sinh nào thuộc cấp học áp dụng")
            return success_response(
                data=None,
                message="Không có học sinh nào thuộc cấp học áp dụng cho kỳ đăng ký này",
                logs=logs
            )
        
        # Lấy danh sách ngày đăng ký từ registration_dates
        registration_dates = _get_registration_dates(period.name)
        
        # Fallback: nếu chưa có registration_dates, dùng wednesdays
        if not registration_dates:
            registration_dates = _get_wednesdays_in_month(period.year, period.month)
        
        # Lấy thông tin đăng ký hiện có cho từng học sinh
        for student in students:
            existing_reg = frappe.db.get_value(
                "SIS Menu Registration",
                {
                    "period": period.name,
                    "student_id": student["name"]
                },
                ["name", "registration_date"],
                as_dict=True
            )
            
            if existing_reg:
                student["registration_id"] = existing_reg.name
                student["has_registered"] = True
                
                # Lấy chi tiết đăng ký
                items = frappe.get_all(
                    "SIS Menu Registration Item",
                    filters={"parent": existing_reg.name},
                    fields=["date", "choice"]
                )
                student["registrations"] = {item.date.strftime('%Y-%m-%d'): item.choice for item in items}
                
                # Tính số ngày đã đăng ký
                student["registered_count"] = len(items)
            else:
                student["registration_id"] = None
                student["has_registered"] = False
                student["registrations"] = {}
                student["registered_count"] = 0
        
        # Lấy tên cấp học (lấy cấp đầu tiên nếu có nhiều)
        education_stage_name = ""
        if education_stage_ids:
            education_stage_name = frappe.db.get_value(
                "SIS Education Stage",
                education_stage_ids[0],
                "title_vn"
            ) or ""
        
        return success_response(
            data={
                "period": {
                    "name": period.name,
                    "title": period.title,
                    "month": period.month,
                    "year": period.year,
                    "start_date": str(period.start_date) if period.start_date else None,
                    "end_date": str(period.end_date) if period.end_date else None,
                    "parent_start_datetime": str(period.parent_start_datetime) if period.parent_start_datetime else None,
                    "parent_end_datetime": str(period.parent_end_datetime) if period.parent_end_datetime else None,
                    "education_stage_ids": education_stage_ids,
                    "education_stage_name": education_stage_name
                },
                "registration_dates": registration_dates,
                "wednesdays": registration_dates,  # Backward compatibility
                "total_days": len(registration_dates),
                "students": students
            },
            message="Lấy kỳ đăng ký thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Active Menu Period Error")
        return error_response(
            message=f"Lỗi khi lấy kỳ đăng ký: {str(e)}",
            logs=logs
        )


@frappe.whitelist(allow_guest=True)
def get_daily_menu_for_date(date=None):
    """
    Lấy thực đơn Set Á và Set Âu cho một ngày cụ thể.
    Dùng để hiển thị món ăn khi phụ huynh chọn ngày trong trang đăng ký suất ăn.
    """
    logs = []
    
    try:
        # Lấy date từ request args nếu không có trong function params
        if not date:
            date = frappe.form_dict.get('date') or (frappe.request.args.get('date') if frappe.request else None)
        
        if not date:
            return validation_error_response(
                "Thiếu ngày",
                {"date": ["Ngày là bắt buộc"]}
            )
        
        logs.append(f"Lấy thực đơn cho ngày: {date}")
        
        # Tìm daily menu cho ngày này
        daily_menu = frappe.db.get_value(
            "SIS Daily Menu",
            {"menu_date": date},
            ["name", "menu_date"],
            as_dict=True
        )
        
        if not daily_menu:
            return success_response(
                data={"date": date, "daily_menu_id": None, "set_a": [], "set_au": []},
                message="Chưa có thực đơn cho ngày này",
                logs=logs
            )
        
        # Lấy document đầy đủ để access items child table
        daily_menu_doc = frappe.get_doc("SIS Daily Menu", daily_menu.name)
        
        set_a_items = []
        set_au_items = []
        
        # Parse items từ child table
        for item in daily_menu_doc.items or []:
            # Chỉ lấy lunch items
            if item.meal_type != "lunch":
                continue
            
            # Lấy thông tin món ăn
            category = None
            if item.menu_category_id:
                category = frappe.db.get_value(
                    "SIS Menu Category",
                    item.menu_category_id,
                    ["name", "title_vn", "title_en", "image_url", "code"],
                    as_dict=True
                )
            
            if category:
                # Dùng display_name từ item nếu có, fallback về category title
                display_name = item.display_name or category.title_vn or ""
                display_name_en = item.display_name_en or category.title_en or ""
                
                item_data = {
                    "id": category.name,
                    "name": category.name,
                    "title_vn": category.title_vn or "",
                    "title_en": category.title_en or "",
                    "display_name": display_name,
                    "display_name_en": display_name_en,
                    "image_url": category.image_url or "",
                    "code": category.code or ""
                }
                
                # Kiểm tra meal_type_reference để xác định set_a hay set_au
                meal_ref = (item.meal_type_reference or "").lower()
                if "set_a" in meal_ref and "set_au" not in meal_ref:
                    set_a_items.append(item_data)
                elif "set_au" in meal_ref:
                    set_au_items.append(item_data)
        
        return success_response(
            data={
                "date": date,
                "daily_menu_id": daily_menu.name,
                "set_a": set_a_items,
                "set_au": set_au_items
            },
            message="Lấy thực đơn thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Daily Menu Error")
        return error_response(
            message=f"Lỗi khi lấy thực đơn: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def save_registration():
    """
    Lưu đăng ký suất ăn cho học sinh.
    Phụ huynh gọi API này để lưu lựa chọn Á/Âu cho các ngày Thứ 4.
    """
    logs = []
    
    try:
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        logs.append(f"Nhận request: {json.dumps(data, default=str)}")
        
        # Validate required fields
        required_fields = ['period_id', 'student_id', 'registrations']
        for field in required_fields:
            if field not in data or data[field] is None:
                return validation_error_response(
                    f"Thiếu trường bắt buộc: {field}",
                    {field: [f"Trường {field} là bắt buộc"]}
                )
        
        period_id = data['period_id']
        student_id = data['student_id']
        registrations = data['registrations']
        
        # Parse registrations nếu là string
        if isinstance(registrations, str):
            registrations = json.loads(registrations)
        
        # Validate registrations không rỗng
        if not registrations:
            return validation_error_response(
                "Vui lòng chọn suất ăn cho ít nhất một ngày",
                {"registrations": ["Danh sách đăng ký không được rỗng"]}
            )
        
        # Get current parent
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent: {parent_id}")
        
        # Kiểm tra học sinh thuộc phụ huynh
        relationship = frappe.db.exists(
            "CRM Family Relationship",
            {"guardian": parent_id, "student": student_id}
        )
        
        if not relationship:
            return error_response(
                "Bạn không có quyền đăng ký cho học sinh này",
                logs=logs
            )
        
        # Kiểm tra kỳ đăng ký còn mở
        period = frappe.db.get_value(
            "SIS Menu Registration Period",
            period_id,
            ["name", "status", "start_date", "end_date", "month", "year",
             "parent_start_datetime", "parent_end_datetime"],
            as_dict=True
        )
        
        if not period:
            return error_response("Kỳ đăng ký không tồn tại", logs=logs)
        
        if period.status != "Open":
            return error_response("Kỳ đăng ký đã đóng", logs=logs)
        
        # Kiểm tra parent timeline
        if not _check_parent_timeline(period):
            return error_response("Chưa đến hoặc đã hết thời gian đăng ký", logs=logs)
        
        # Lấy thông tin lớp học sinh
        class_info = _get_student_current_class(student_id)
        class_id = class_info.get("class_id") if class_info else None
        
        # Lấy family_id - query từ CRM Family có chứa relationship này
        family_id = None
        try:
            # Tìm CRM Family Relationship record
            rel_record = frappe.db.get_value(
                "CRM Family Relationship",
                {"guardian": parent_id, "student": student_id},
                ["name", "parent"],
                as_dict=True
            )
            if rel_record and rel_record.parent:
                # Kiểm tra xem parent có phải là CRM Family không
                if frappe.db.exists("CRM Family", rel_record.parent):
                    family_id = rel_record.parent
                    logs.append(f"Family ID: {family_id}")
                else:
                    logs.append(f"Parent {rel_record.parent} không phải CRM Family, bỏ qua")
        except Exception as e:
            logs.append(f"Không thể lấy family_id: {str(e)}")
        
        # Tìm đăng ký hiện có hoặc tạo mới
        existing = frappe.db.get_value(
            "SIS Menu Registration",
            {"period": period_id, "student_id": student_id},
            "name"
        )
        
        if existing:
            # Cập nhật đăng ký hiện có
            reg_doc = frappe.get_doc("SIS Menu Registration", existing)
            reg_doc.registrations = []  # Clear existing items
            logs.append(f"Cập nhật đăng ký: {existing}")
        else:
            # Tạo đăng ký mới
            reg_doc = frappe.new_doc("SIS Menu Registration")
            reg_doc.period = period_id
            reg_doc.student_id = student_id
            if family_id:
                reg_doc.family_id = family_id
            if class_id:
                reg_doc.class_id = class_id
            reg_doc.registered_by = frappe.session.user
            logs.append("Tạo đăng ký mới")
        
        # Thêm các items
        valid_choices = ["A", "AU"]
        for date_str, choice in registrations.items():
            if choice not in valid_choices:
                return validation_error_response(
                    f"Lựa chọn '{choice}' không hợp lệ",
                    {"choice": [f"Lựa chọn phải là: {', '.join(valid_choices)}"]}
                )
            
            reg_doc.append("registrations", {
                "date": date_str,
                "choice": choice
            })
        
        # Lưu
        reg_doc.flags.ignore_permissions = True
        reg_doc.save()
        frappe.db.commit()
        
        logs.append(f"Đã lưu đăng ký: {reg_doc.name}")
        
        # Lấy thông tin học sinh
        student_name = frappe.db.get_value("CRM Student", student_id, "student_name")
        
        return success_response(
            data={
                "registration_id": reg_doc.name,
                "student_id": student_id,
                "student_name": student_name,
                "period_id": period_id,
                "registered_count": len(registrations)
            },
            message=f"Đã lưu đăng ký suất ăn cho {student_name}",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Save Menu Registration Error")
        return error_response(
            message=f"Lỗi khi lưu đăng ký: {str(e)}",
            logs=logs
        )


# ============== ADMIN APIs ==============

@frappe.whitelist()
def get_period_list(status=None, page=1, page_size=20):
    """
    Lấy danh sách kỳ đăng ký suất ăn (cho Admin).
    """
    logs = []
    
    try:
        filters = {}
        if status:
            filters["status"] = status
        
        # Count total
        total = frappe.db.count("SIS Menu Registration Period", filters)
        
        # Get list
        periods = frappe.get_all(
            "SIS Menu Registration Period",
            filters=filters,
            fields=[
                "name", "title", "month", "year", "start_date", "end_date",
                "status", "school_year_id",
                "created_at", "created_by"
            ],
            order_by="year desc, month desc",
            start=(int(page) - 1) * int(page_size),
            page_length=int(page_size)
        )
        
        # Enrich data
        for period in periods:
            # Đếm số đăng ký
            reg_count = frappe.db.count(
                "SIS Menu Registration",
                {"period": period.name}
            )
            period["registration_count"] = reg_count
            
            # Lấy danh sách cấp học từ child table
            education_stages = frappe.get_all(
                "SIS Menu Registration Period Education Stage",
                filters={"parent": period.name},
                fields=["education_stage_id", "education_stage_name"]
            )
            period["education_stages"] = education_stages
            
            # Tạo chuỗi tên cấp học để hiển thị
            stage_names = []
            for stage in education_stages:
                if stage.education_stage_name:
                    stage_names.append(stage.education_stage_name)
                elif stage.education_stage_id:
                    name = frappe.db.get_value("SIS Education Stage", stage.education_stage_id, "title_vn")
                    if name:
                        stage_names.append(name)
            period["education_stage_names"] = ", ".join(stage_names) if stage_names else ""
            
            # Lấy tên năm học
            if period.school_year_id:
                period["school_year_name"] = frappe.db.get_value(
                    "SIS School Year",
                    period.school_year_id,
                    "title_vn"
                )
        
        return success_response(
            data={
                "items": periods,
                "total": total,
                "page": int(page),
                "page_size": int(page_size)
            },
            message="Lấy danh sách kỳ đăng ký thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Menu Period List Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_period_stats(period_id=None):
    """
    Lấy thống kê cho kỳ đăng ký (Tổng/Á/Âu/Chưa đăng ký).
    """
    logs = []
    
    try:
        # Lấy period_id từ request args nếu không có trong function params
        if not period_id:
            period_id = frappe.form_dict.get('period_id') or (frappe.request.args.get('period_id') if frappe.request else None)
        
        if not period_id:
            return validation_error_response(
                "Thiếu period_id",
                {"period_id": ["Period ID là bắt buộc"]}
            )
        
        period = frappe.db.get_value(
            "SIS Menu Registration Period",
            period_id,
            ["name", "month", "year", "education_stage_id", "school_year_id"],
            as_dict=True
        )
        
        if not period:
            return not_found_response("Không tìm thấy kỳ đăng ký")
        
        # Lấy danh sách ngày đăng ký từ registration_dates
        registration_dates = _get_registration_dates(period_id)
        
        # Fallback: nếu chưa có registration_dates, dùng wednesdays
        if not registration_dates:
            registration_dates = _get_wednesdays_in_month(period.year, period.month)
        
        total_days = len(registration_dates)
        
        # Đếm tổng số học sinh thuộc cấp học
        # TODO: Query từ SIS Class Student theo education_stage và school_year
        total_students = frappe.db.sql("""
            SELECT COUNT(DISTINCT cs.student_id) as count
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
            INNER JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
            WHERE cs.school_year_id = %s
            AND eg.education_stage_id = %s
        """, (period.school_year_id, period.education_stage_id), as_dict=True)
        
        total_student_count = total_students[0].count if total_students else 0
        
        # Đếm số đăng ký
        registrations = frappe.db.sql("""
            SELECT 
                COUNT(DISTINCT r.student_id) as registered_students,
                SUM(CASE WHEN ri.choice = 'A' THEN 1 ELSE 0 END) as choice_a,
                SUM(CASE WHEN ri.choice = 'AU' THEN 1 ELSE 0 END) as choice_au
            FROM `tabSIS Menu Registration` r
            INNER JOIN `tabSIS Menu Registration Item` ri ON ri.parent = r.name
            WHERE r.period = %s
        """, (period_id,), as_dict=True)
        
        stats = registrations[0] if registrations else {}
        registered_students = stats.get("registered_students") or 0
        choice_a = stats.get("choice_a") or 0
        choice_au = stats.get("choice_au") or 0
        
        # Tính số chưa đăng ký
        not_registered = total_student_count - registered_students
        
        return success_response(
            data={
                "period_id": period_id,
                "total_students": total_student_count,
                "total_days": total_days,
                "registered_students": registered_students,
                "not_registered": not_registered if not_registered > 0 else 0,
                "choice_a": choice_a,
                "choice_au": choice_au,
                "registration_dates": registration_dates,
                "wednesdays": registration_dates  # Backward compatibility
            },
            message="Lấy thống kê thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Period Stats Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_class_registrations(class_id=None, month=None, year=None):
    """
    Lấy danh sách đăng ký theo lớp và tháng (cho tab Thực đơn trong ClassInfo).
    Trả về ma trận: học sinh x ngày Thứ 4.
    """
    logs = []
    
    try:
        # Lấy params từ request args nếu không có trong function params
        if not class_id:
            class_id = frappe.form_dict.get('class_id') or (frappe.request.args.get('class_id') if frappe.request else None)
        if not month:
            month = frappe.form_dict.get('month') or (frappe.request.args.get('month') if frappe.request else None)
        if not year:
            year = frappe.form_dict.get('year') or (frappe.request.args.get('year') if frappe.request else None)
        
        if not class_id:
            return validation_error_response(
                "Thiếu class_id",
                {"class_id": ["Class ID là bắt buộc"]}
            )
        
        # Nếu không có month/year, dùng tháng hiện tại
        if not month or not year:
            today = getdate(nowdate())
            month = today.month
            year = today.year
        else:
            month = int(month)
            year = int(year)
        
        # Tìm period_id nếu có (để query registrations)
        period = frappe.db.get_value(
            "SIS Menu Registration Period",
            {"month": month, "year": year},
            ["name"],
            as_dict=True
        )
        period_id = period.name if period else None
        
        # Lấy danh sách ngày đăng ký từ period
        if period_id:
            wednesdays = _get_registration_dates(period_id)
        else:
            wednesdays = []
        
        # Fallback: nếu không có registration_dates, dùng wednesdays cũ
        if not wednesdays:
            wednesdays = _get_wednesdays_in_month(year, month)
        
        # Lấy danh sách học sinh trong lớp
        class_students = frappe.db.sql("""
            SELECT 
                cs.student_id,
                s.student_name,
                s.student_code
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
            WHERE cs.class_id = %s
            ORDER BY s.student_name
        """, (class_id,), as_dict=True)
        
        # Lấy đăng ký cho từng học sinh
        for student in class_students:
            registration = frappe.db.get_value(
                "SIS Menu Registration",
                {"period": period_id, "student_id": student.student_id},
                "name"
            )
            
            if registration:
                items = frappe.get_all(
                    "SIS Menu Registration Item",
                    filters={"parent": registration},
                    fields=["date", "choice"]
                )
                student["registrations"] = {
                    item.date.strftime('%Y-%m-%d'): item.choice 
                    for item in items
                }
            else:
                student["registrations"] = {}
        
        return success_response(
            data={
                "class_id": class_id,
                "period_id": period_id,
                "month": month,
                "year": year,
                "registration_dates": wednesdays,
                "wednesdays": wednesdays,  # Backward compatibility
                "students": class_students
            },
            message="Lấy danh sách đăng ký thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Class Registrations Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_period_registrations(period_id=None, page=1, page_size=50, search=None):
    """
    Lấy danh sách phụ huynh đã đăng ký trong kỳ (cho trang chi tiết kỳ đăng ký).
    """
    logs = []
    
    try:
        # Lấy params từ request args nếu không có trong function params
        if not period_id:
            period_id = frappe.form_dict.get('period_id') or (frappe.request.args.get('period_id') if frappe.request else None)
        if page == 1:
            page = frappe.form_dict.get('page') or (frappe.request.args.get('page') if frappe.request else None) or 1
        if page_size == 50:
            page_size = frappe.form_dict.get('page_size') or (frappe.request.args.get('page_size') if frappe.request else None) or 50
        if not search:
            search = frappe.form_dict.get('search') or (frappe.request.args.get('search') if frappe.request else None)
        
        if not period_id:
            return validation_error_response(
                "Thiếu period_id",
                {"period_id": ["Period ID là bắt buộc"]}
            )
        
        # Build query
        conditions = ["r.period = %s"]
        params = [period_id]
        
        if search:
            conditions.append("(s.student_name LIKE %s OR s.student_code LIKE %s)")
            search_param = f"%{search}%"
            params.extend([search_param, search_param])
        
        where_clause = " AND ".join(conditions)
        
        # Count total
        count_sql = f"""
            SELECT COUNT(DISTINCT r.name) as count
            FROM `tabSIS Menu Registration` r
            INNER JOIN `tabCRM Student` s ON r.student_id = s.name
            WHERE {where_clause}
        """
        total = frappe.db.sql(count_sql, params, as_dict=True)[0].count
        
        # Get list - JOIN thêm để lấy education_stage
        offset = (int(page) - 1) * int(page_size)
        list_sql = f"""
            SELECT 
                r.name,
                r.student_id,
                s.student_name,
                s.student_code,
                r.class_id,
                c.title as class_name,
                r.registration_date,
                r.registered_by,
                es.name as education_stage_id,
                es.title_vn as education_stage_name
            FROM `tabSIS Menu Registration` r
            INNER JOIN `tabCRM Student` s ON r.student_id = s.name
            LEFT JOIN `tabSIS Class` c ON r.class_id = c.name
            LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
            LEFT JOIN `tabSIS Education Stage` es ON eg.education_stage_id = es.name
            WHERE {where_clause}
            ORDER BY r.registration_date DESC
            LIMIT %s OFFSET %s
        """
        params.extend([int(page_size), offset])
        
        registrations = frappe.db.sql(list_sql, params, as_dict=True)
        
        # Enrich với chi tiết đăng ký
        for reg in registrations:
            items = frappe.get_all(
                "SIS Menu Registration Item",
                filters={"parent": reg.name},
                fields=["date", "choice"]
            )
            reg["items"] = items
            
            # Đếm A/AU
            reg["choice_a_count"] = len([i for i in items if i.choice == "A"])
            reg["choice_au_count"] = len([i for i in items if i.choice == "AU"])
        
        return success_response(
            data={
                "items": registrations,
                "total": total,
                "page": int(page),
                "page_size": int(page_size)
            },
            message="Lấy danh sách đăng ký thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Admin Get Period Registrations Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def check_open_period():
    """
    Kiểm tra có kỳ đăng ký suất ăn đang mở không.
    Kiểm tra status = "Open" VÀ ngày hiện tại nằm trong khoảng start_date - end_date.
    Trả về period_id nếu có, None nếu không.
    """
    logs = []
    
    try:
        today = nowdate()
        logs.append(f"Ngày hiện tại: {today}")
        
        # Tìm kỳ đăng ký đang mở VÀ ngày hiện tại nằm trong khoảng start_date - end_date
        period = frappe.db.sql("""
            SELECT name, title, month, year, start_date, end_date
            FROM `tabSIS Menu Registration Period`
            WHERE status = 'Open'
            AND start_date <= %(today)s
            AND end_date >= %(today)s
            LIMIT 1
        """, {"today": today}, as_dict=True)
        
        if period and len(period) > 0:
            p = period[0]
            logs.append(f"Tìm thấy kỳ đăng ký: {p.name} ({p.start_date} - {p.end_date})")
            return success_response(
                data={
                    "has_open_period": True,
                    "period_id": p.name,
                    "period_title": p.title,
                    "month": p.month,
                    "year": p.year,
                    "start_date": str(p.start_date),
                    "end_date": str(p.end_date)
                },
                message="Có kỳ đăng ký đang mở",
                logs=logs
            )
        else:
            logs.append("Không có kỳ đăng ký nào đang mở tại thời điểm này")
            return success_response(
                data={
                    "has_open_period": False,
                    "period_id": None
                },
                message="Không có kỳ đăng ký nào đang mở",
                logs=logs
            )
            
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Check Open Period Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def send_menu_registration_reminder():
    """
    Gửi push notification nhắc phụ huynh đăng ký suất ăn Á/Âu.
    
    POST body:
    {
        "student_ids": ["CRM-STUDENT-00001", ...],  # Danh sách ID học sinh cần nhắc
        "message": "Nội dung tin nhắn tùy chỉnh"    # Nội dung do user nhập
    }
    
    Trả về:
    {
        "success": true,
        "data": {
            "success_count": 10,
            "failed_count": 2,
            "total_students": 12
        }
    }
    """
    logs = []
    
    try:
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        student_ids = data.get('student_ids', [])
        message = data.get('message', '')
        
        if isinstance(student_ids, str):
            student_ids = json.loads(student_ids)
        
        if not student_ids:
            return validation_error_response(
                "Thiếu danh sách học sinh",
                {"student_ids": ["Danh sách học sinh là bắt buộc"]}
            )
        
        if not message or not message.strip():
            return validation_error_response(
                "Thiếu nội dung tin nhắn",
                {"message": ["Nội dung tin nhắn là bắt buộc"]}
            )
        
        # Giới hạn độ dài message (150 ký tự để hiển thị tốt trên mobile)
        message = message.strip()[:150]
        
        logs.append(f"Gửi nhắc nhở cho {len(student_ids)} học sinh")
        logs.append(f"Message: {message}")
        
        # Gửi push notification
        try:
            from erp.utils.notification_handler import send_bulk_parent_notifications
            
            # Sử dụng notification_type = "reminder"
            result = send_bulk_parent_notifications(
                recipient_type="reminder",
                recipients_data={
                    "student_ids": student_ids
                },
                title="Đăng ký suất ăn",
                body=message,
                icon="/icon.png",
                data={
                    "type": "reminder",
                    "subtype": "menu_registration",
                    "url": "/menu/registration"  # URL trên parent-portal
                }
            )
            
            logs.append(f"Kết quả gửi: {result}")
            
            return success_response(
                data={
                    "success_count": result.get("success_count", 0),
                    "failed_count": result.get("failed_count", 0),
                    "total_students": len(student_ids),
                    "total_parents": result.get("total_parents", 0)
                },
                message=f"Đã gửi thông báo đến {result.get('success_count', 0)} phụ huynh",
                logs=logs
            )
            
        except Exception as notif_err:
            logs.append(f"Lỗi gửi notification: {str(notif_err)}")
            frappe.log_error(frappe.get_traceback(), "Send Menu Registration Reminder Error")
            return error_response(
                message=f"Lỗi khi gửi thông báo: {str(notif_err)}",
                logs=logs
            )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Send Menu Registration Reminder Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def delete_period():
    """
    Xóa kỳ đăng ký suất ăn.
    Chỉ có thể xóa kỳ chưa có đơn đăng ký, trừ khi:
    - User có role System Manager VÀ force_delete=true
    - Khi đó sẽ xóa tất cả đơn đăng ký trước khi xóa kỳ
    """
    logs = []
    
    try:
        # Kiểm tra quyền
        if "System Manager" not in frappe.get_roles(frappe.session.user) and \
           "SIS Admin" not in frappe.get_roles(frappe.session.user):
            return error_response("Bạn không có quyền truy cập", logs=logs)
        
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        period_id = data.get('period_id')
        force_delete = data.get('force_delete', False)
        
        # Chuyển đổi force_delete sang boolean nếu là string
        if isinstance(force_delete, str):
            force_delete = force_delete.lower() in ('true', '1', 'yes')
        
        if not period_id:
            return validation_error_response(
                "Thiếu period_id",
                {"period_id": ["Period ID là bắt buộc"]}
            )
        
        # Kiểm tra tồn tại
        if not frappe.db.exists("SIS Menu Registration Period", period_id):
            return not_found_response("Không tìm thấy kỳ đăng ký")
        
        # Kiểm tra có đơn đăng ký hay không (field tên là "period" không phải "period_id")
        registration_count = frappe.db.count(
            "SIS Menu Registration",
            {"period": period_id}
        )
        
        deleted_registrations = 0
        
        if registration_count > 0:
            # Kiểm tra nếu user là System Manager và force_delete=true
            is_system_manager = "System Manager" in frappe.get_roles(frappe.session.user)
            
            if force_delete and is_system_manager:
                # Xóa tất cả đơn đăng ký của kỳ này
                logs.append(f"System Manager đang xóa {registration_count} đơn đăng ký...")
                
                registrations = frappe.get_all(
                    "SIS Menu Registration",
                    filters={"period": period_id},
                    pluck="name"
                )
                
                for reg_name in registrations:
                    frappe.delete_doc("SIS Menu Registration", reg_name, force=True)
                    deleted_registrations += 1
                
                logs.append(f"Đã xóa {deleted_registrations} đơn đăng ký")
            else:
                # Không có quyền force delete
                if not is_system_manager:
                    return error_response(
                        f"Không thể xóa kỳ đăng ký vì đã có {registration_count} đơn đăng ký. Chỉ System Manager mới có quyền xóa.",
                        logs=logs
                    )
                else:
                    return error_response(
                        f"Không thể xóa kỳ đăng ký vì đã có {registration_count} đơn đăng ký",
                        logs=logs
                    )
        
        # Xóa kỳ đăng ký (force=True để bỏ qua kiểm tra linked documents vì đã xóa hết ở trên)
        frappe.delete_doc("SIS Menu Registration Period", period_id, force=True)
        frappe.db.commit()
        
        logs.append(f"Đã xóa kỳ đăng ký: {period_id}")
        
        message = "Đã xóa kỳ đăng ký thành công"
        if deleted_registrations > 0:
            message += f" (bao gồm {deleted_registrations} đơn đăng ký)"
        
        return success_response(
            data={"message": message, "deleted_registrations": deleted_registrations},
            message=message,
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Delete Menu Registration Period Error")
        return error_response(
            message=f"Lỗi khi xóa: {str(e)}",
            logs=logs
        )


# ============================================
# TEACHER APIs - Cho giáo viên chủ nhiệm
# ============================================

@frappe.whitelist()
def get_teacher_active_period(class_id=None):
    """
    Lấy kỳ đăng ký suất ăn đang mở cho GVCN.
    Kiểm tra theo teacher_start_datetime và teacher_end_datetime.
    """
    logs = []
    
    try:
        # Lấy class_id từ request nếu không có
        if not class_id:
            class_id = frappe.form_dict.get('class_id') or (frappe.request.args.get('class_id') if frappe.request else None)
        
        if not class_id:
            return validation_error_response(
                "Thiếu class_id",
                {"class_id": ["Class ID là bắt buộc"]}
            )
        
        logs.append(f"Class ID: {class_id}")
        
        # Kiểm tra quyền: user phải là GVCN của lớp này
        user_email = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": user_email}, "name")
        
        if not teacher:
            return error_response("Bạn không phải là giáo viên", logs=logs)
        
        class_info = frappe.db.get_value(
            "SIS Class",
            class_id,
            ["homeroom_teacher", "vice_homeroom_teacher", "title", "education_grade", "school_year_id"],
            as_dict=True
        )
        
        if not class_info:
            return not_found_response("Không tìm thấy lớp")
        
        if teacher not in [class_info.homeroom_teacher, class_info.vice_homeroom_teacher]:
            return error_response("Bạn không phải GVCN của lớp này", logs=logs)
        
        # Lấy education_stage từ grade
        education_stage_id = frappe.db.get_value(
            "SIS Education Grade",
            class_info.education_grade,
            "education_stage_id"
        )
        
        # Tìm kỳ đăng ký đang trong teacher timeline
        from frappe.utils import now_datetime, getdate
        now = now_datetime()
        today = getdate()
        
        # Ưu tiên: tìm kỳ có teacher timeline trước
        period = frappe.db.sql("""
            SELECT 
                p.name, p.title, p.month, p.year,
                p.parent_start_datetime, p.parent_end_datetime,
                p.teacher_start_datetime, p.teacher_end_datetime,
                p.start_date, p.end_date,
                p.status, p.school_year_id
            FROM `tabSIS Menu Registration Period` p
            INNER JOIN `tabSIS Menu Registration Period Education Stage` es 
                ON es.parent = p.name
            WHERE p.status = 'Open'
            AND p.teacher_start_datetime IS NOT NULL
            AND p.teacher_start_datetime <= %s
            AND p.teacher_end_datetime >= %s
            AND es.education_stage_id = %s
            ORDER BY p.creation DESC
            LIMIT 1
        """, (now, now, education_stage_id), as_dict=True)
        
        # Fallback: nếu không có teacher timeline, tìm kỳ theo start_date/end_date cũ
        if not period:
            logs.append("Không tìm thấy kỳ với teacher timeline, thử fallback...")
            period = frappe.db.sql("""
                SELECT 
                    p.name, p.title, p.month, p.year,
                    p.parent_start_datetime, p.parent_end_datetime,
                    p.teacher_start_datetime, p.teacher_end_datetime,
                    p.start_date, p.end_date,
                    p.status, p.school_year_id
                FROM `tabSIS Menu Registration Period` p
                INNER JOIN `tabSIS Menu Registration Period Education Stage` es 
                    ON es.parent = p.name
                WHERE p.status = 'Open'
                AND (
                    (p.start_date IS NOT NULL AND p.start_date <= %s AND p.end_date >= %s)
                    OR
                    (p.parent_start_datetime IS NOT NULL AND DATE(p.parent_start_datetime) <= %s AND DATE(p.parent_end_datetime) >= %s)
                )
                AND es.education_stage_id = %s
                ORDER BY p.creation DESC
                LIMIT 1
            """, (today, today, today, today, education_stage_id), as_dict=True)
        
        if not period:
            logs.append("Không có kỳ đăng ký nào đang mở cho GVCN")
            return success_response(
                data=None,
                message="Không có kỳ đăng ký nào đang mở cho GVCN",
                logs=logs
            )
        
        period = period[0]
        logs.append(f"Tìm thấy kỳ: {period.name}")
        
        # Lấy danh sách ngày đăng ký
        registration_dates = _get_registration_dates(period.name)
        
        if not registration_dates:
            registration_dates = _get_wednesdays_in_month(period.year, period.month)
        
        # Lấy danh sách học sinh trong lớp
        students = frappe.db.sql("""
            SELECT 
                cs.student_id,
                s.student_name,
                s.student_code
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
            WHERE cs.class_id = %s
            AND cs.school_year_id = %s
            ORDER BY s.student_name
        """, (class_id, class_info.school_year_id), as_dict=True)
        
        # Lấy thông tin đăng ký hiện có
        for student in students:
            existing_reg = frappe.db.get_value(
                "SIS Menu Registration",
                {
                    "period": period.name,
                    "student_id": student.student_id
                },
                ["name"],
                as_dict=True
            )
            
            if existing_reg:
                items = frappe.get_all(
                    "SIS Menu Registration Item",
                    filters={"parent": existing_reg.name},
                    fields=["date", "choice"]
                )
                student["registrations"] = {str(item.date): item.choice for item in items}
                student["registration_id"] = existing_reg.name
            else:
                student["registrations"] = {}
                student["registration_id"] = None
        
        # Xác định timeline để hiển thị (ưu tiên teacher timeline, fallback về parent/legacy)
        teacher_start = period.teacher_start_datetime or period.parent_start_datetime or period.start_date
        teacher_end = period.teacher_end_datetime or period.parent_end_datetime or period.end_date
        
        # Kiểm tra có thể edit không (có teacher timeline riêng hoặc fallback)
        can_edit = True
        if period.teacher_start_datetime and period.teacher_end_datetime:
            # Có teacher timeline riêng - đã check ở trên
            can_edit = True
        else:
            # Fallback - cho phép edit nếu trong khoảng start_date/end_date
            can_edit = True
        
        return success_response(
            data={
                "period": {
                    "name": period.name,
                    "title": period.title,
                    "month": period.month,
                    "year": period.year,
                    "teacher_start_datetime": str(teacher_start) if teacher_start else None,
                    "teacher_end_datetime": str(teacher_end) if teacher_end else None
                },
                "registration_dates": registration_dates,
                "total_days": len(registration_dates),
                "students": students,
                "class_info": {
                    "class_id": class_id,
                    "class_title": class_info.title
                },
                "can_edit": can_edit
            },
            message="Lấy kỳ đăng ký thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Teacher Get Active Period Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def teacher_save_registration():
    """
    GVCN lưu đăng ký suất ăn cho học sinh trong lớp.
    """
    logs = []
    
    try:
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        logs.append(f"Nhận request: {json.dumps(data, default=str)}")
        
        # Validate required fields
        required_fields = ['period_id', 'class_id', 'student_registrations']
        for field in required_fields:
            if field not in data or data[field] is None:
                return validation_error_response(
                    f"Thiếu trường bắt buộc: {field}",
                    {field: [f"Trường {field} là bắt buộc"]}
                )
        
        period_id = data['period_id']
        class_id = data['class_id']
        student_registrations = data['student_registrations']
        
        # Parse nếu là string
        if isinstance(student_registrations, str):
            student_registrations = json.loads(student_registrations)
        
        # Kiểm tra quyền GVCN
        user_email = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": user_email}, "name")
        
        if not teacher:
            return error_response("Bạn không phải là giáo viên", logs=logs)
        
        class_info = frappe.db.get_value(
            "SIS Class",
            class_id,
            ["homeroom_teacher", "vice_homeroom_teacher", "school_year_id"],
            as_dict=True
        )
        
        if not class_info:
            return not_found_response("Không tìm thấy lớp")
        
        if teacher not in [class_info.homeroom_teacher, class_info.vice_homeroom_teacher]:
            return error_response("Bạn không phải GVCN của lớp này", logs=logs)
        
        # Kiểm tra kỳ đăng ký và teacher timeline
        period = frappe.db.get_value(
            "SIS Menu Registration Period",
            period_id,
            ["name", "status", "teacher_start_datetime", "teacher_end_datetime", 
             "parent_start_datetime", "parent_end_datetime", "start_date", "end_date"],
            as_dict=True
        )
        
        if not period:
            return not_found_response("Không tìm thấy kỳ đăng ký")
        
        if period.status != "Open":
            return error_response("Kỳ đăng ký đã đóng", logs=logs)
        
        if not _check_teacher_timeline(period):
            return error_response("Không trong thời gian đăng ký của GVCN", logs=logs)
        
        # Lưu cho từng học sinh
        saved_count = 0
        valid_choices = ["A", "AU", ""]  # Empty string để xóa đăng ký
        
        for student_id, registrations in student_registrations.items():
            if isinstance(registrations, str):
                registrations = json.loads(registrations)
            
            # Kiểm tra học sinh thuộc lớp
            is_student_in_class = frappe.db.exists(
                "SIS Class Student",
                {
                    "class_id": class_id,
                    "student_id": student_id,
                    "school_year_id": class_info.school_year_id
                }
            )
            
            if not is_student_in_class:
                logs.append(f"Học sinh {student_id} không thuộc lớp {class_id}")
                continue
            
            # Tìm hoặc tạo registration
            existing = frappe.db.get_value(
                "SIS Menu Registration",
                {"period": period_id, "student_id": student_id},
                "name"
            )
            
            # Lọc bỏ các ngày không đăng ký (empty string)
            valid_registrations = {k: v for k, v in registrations.items() if v and v in ["A", "AU"]}
            
            if existing:
                if not valid_registrations:
                    # Xóa đăng ký nếu không còn item nào
                    frappe.delete_doc("SIS Menu Registration", existing, force=True)
                    logs.append(f"Đã xóa đăng ký cho học sinh {student_id}")
                else:
                    reg_doc = frappe.get_doc("SIS Menu Registration", existing)
                    reg_doc.registrations = []
                    for date_str, choice in valid_registrations.items():
                        reg_doc.append("registrations", {
                            "date": date_str,
                            "choice": choice
                        })
                    reg_doc.flags.ignore_permissions = True
                    reg_doc.save()
                    saved_count += 1
            else:
                if valid_registrations:
                    reg_doc = frappe.new_doc("SIS Menu Registration")
                    reg_doc.period = period_id
                    reg_doc.student_id = student_id
                    reg_doc.class_id = class_id
                    reg_doc.registered_by = frappe.session.user
                    
                    for date_str, choice in valid_registrations.items():
                        reg_doc.append("registrations", {
                            "date": date_str,
                            "choice": choice
                        })
                    
                    reg_doc.flags.ignore_permissions = True
                    reg_doc.insert()
                    saved_count += 1
        
        frappe.db.commit()
        
        return success_response(
            data={"saved_count": saved_count},
            message=f"Đã lưu đăng ký cho {saved_count} học sinh",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Teacher Save Registration Error")
        return error_response(
            message=f"Lỗi: {str(e)}",
            logs=logs
        )
