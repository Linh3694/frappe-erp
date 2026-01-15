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
    """Lấy danh sách các ngày Thứ 4 trong tháng"""
    wednesdays = []
    
    # Lấy số ngày trong tháng
    _, num_days = monthrange(year, month)
    
    for day in range(1, num_days + 1):
        date = datetime(year, month, day)
        # Thứ 4 = weekday() == 2 (Monday = 0)
        if date.weekday() == 2:
            wednesdays.append(date.strftime('%Y-%m-%d'))
    
    return wednesdays


@frappe.whitelist()
def get_active_period():
    """
    Lấy kỳ đăng ký suất ăn đang mở cho phụ huynh.
    Trả về thông tin kỳ đăng ký và các ngày Thứ 4 trong tháng.
    """
    logs = []
    
    try:
        logs.append("Đang lấy kỳ đăng ký suất ăn đang mở")
        
        # Lấy thông tin phụ huynh
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent ID: {parent_id}")
        
        # Tìm kỳ đăng ký đang mở (status = 'Open')
        today = getdate(nowdate())
        
        period = frappe.db.sql("""
            SELECT 
                name, title, month, year, start_date, end_date, 
                status, education_stage_id, school_year_id
            FROM `tabSIS Menu Registration Period`
            WHERE status = 'Open'
            AND start_date <= %s
            AND end_date >= %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (today, today), as_dict=True)
        
        if not period:
            logs.append("Không có kỳ đăng ký suất ăn nào đang mở")
            return success_response(
                data=None,
                message="Không có kỳ đăng ký suất ăn nào đang mở",
                logs=logs
            )
        
        period = period[0]
        logs.append(f"Tìm thấy kỳ: {period.name}")
        
        # Lấy danh sách học sinh thuộc cấp học áp dụng
        students = _get_parent_students(parent_id, period.education_stage_id)
        
        if not students:
            logs.append("Không có học sinh nào thuộc cấp học áp dụng")
            return success_response(
                data=None,
                message="Không có học sinh nào thuộc cấp học áp dụng cho kỳ đăng ký này",
                logs=logs
            )
        
        # Lấy các ngày Thứ 4 trong tháng
        wednesdays = _get_wednesdays_in_month(period.year, period.month)
        
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
        
        # Lấy tên cấp học
        education_stage_name = frappe.db.get_value(
            "SIS Education Stage",
            period.education_stage_id,
            "title_vn"
        ) or "Tiểu học"
        
        return success_response(
            data={
                "period": {
                    "name": period.name,
                    "title": period.title,
                    "month": period.month,
                    "year": period.year,
                    "start_date": str(period.start_date),
                    "end_date": str(period.end_date),
                    "education_stage_id": period.education_stage_id,
                    "education_stage_name": education_stage_name
                },
                "wednesdays": wednesdays,
                "total_days": len(wednesdays),
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


@frappe.whitelist()
def get_daily_menu_for_date(date=None):
    """
    Lấy thực đơn Set Á và Set Âu cho một ngày cụ thể.
    Dùng để hiển thị món ăn khi phụ huynh chọn ngày.
    """
    logs = []
    
    try:
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
                data={"set_a": None, "set_au": None},
                message="Chưa có thực đơn cho ngày này",
                logs=logs
            )
        
        # Lấy các meal (chỉ lấy lunch)
        meals = frappe.get_all(
            "SIS Daily Menu Meal",
            filters={"parent": daily_menu.name, "meal_type": "lunch"},
            fields=["name", "meal_type"]
        )
        
        set_a_items = []
        set_au_items = []
        
        for meal in meals:
            # Lấy các items của meal
            items = frappe.get_all(
                "SIS Daily Menu Meal Item",
                filters={"parent": meal.name},
                fields=["menu_category_id", "set_type", "item_type"]
            )
            
            for item in items:
                # Lấy thông tin món ăn
                category = frappe.db.get_value(
                    "SIS Menu Category",
                    item.menu_category_id,
                    ["name", "title_vn", "title_en", "image", "display_name", "display_name_en"],
                    as_dict=True
                )
                
                if category:
                    item_data = {
                        "name": category.name,
                        "title_vn": category.title_vn or category.display_name,
                        "title_en": category.title_en or category.display_name_en,
                        "image": category.image,
                        "item_type": item.item_type
                    }
                    
                    if item.set_type == "set_a":
                        set_a_items.append(item_data)
                    elif item.set_type == "set_au":
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
            ["name", "status", "start_date", "end_date", "month", "year"],
            as_dict=True
        )
        
        if not period:
            return error_response("Kỳ đăng ký không tồn tại", logs=logs)
        
        if period.status != "Open":
            return error_response("Kỳ đăng ký đã đóng", logs=logs)
        
        today = getdate(nowdate())
        if today < getdate(period.start_date) or today > getdate(period.end_date):
            return error_response("Chưa đến hoặc đã hết thời gian đăng ký", logs=logs)
        
        # Lấy thông tin lớp học sinh
        class_info = _get_student_current_class(student_id)
        class_id = class_info.get("class_id") if class_info else None
        
        # Lấy family_id
        family = frappe.db.get_value(
            "CRM Family Relationship",
            {"guardian": parent_id, "student": student_id},
            "parent"
        )
        
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
            reg_doc.family_id = family
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
                "status", "education_stage_id", "school_year_id",
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
            
            # Lấy tên cấp học
            if period.education_stage_id:
                period["education_stage_name"] = frappe.db.get_value(
                    "SIS Education Stage",
                    period.education_stage_id,
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
        
        # Lấy số ngày Thứ 4 trong tháng
        wednesdays = _get_wednesdays_in_month(period.year, period.month)
        total_days = len(wednesdays)
        
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
                "wednesdays": wednesdays
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
def get_class_registrations(class_id=None, period_id=None):
    """
    Lấy danh sách đăng ký theo lớp (cho tab Thực đơn trong ClassInfo).
    Trả về ma trận: học sinh x ngày Thứ 4.
    """
    logs = []
    
    try:
        if not class_id:
            return validation_error_response(
                "Thiếu class_id",
                {"class_id": ["Class ID là bắt buộc"]}
            )
        
        # Nếu không có period_id, tìm kỳ đăng ký đang mở
        if not period_id:
            period = frappe.db.sql("""
                SELECT name, month, year
                FROM `tabSIS Menu Registration Period`
                WHERE status = 'Open'
                ORDER BY created_at DESC
                LIMIT 1
            """, as_dict=True)
            
            if period:
                period_id = period[0].name
                month = period[0].month
                year = period[0].year
            else:
                # Không có kỳ nào đang mở, trả về rỗng
                return success_response(
                    data={
                        "class_id": class_id,
                        "period_id": None,
                        "wednesdays": [],
                        "students": []
                    },
                    message="Không có kỳ đăng ký nào đang mở",
                    logs=logs
                )
        else:
            period = frappe.db.get_value(
                "SIS Menu Registration Period",
                period_id,
                ["month", "year"],
                as_dict=True
            )
            month = period.month
            year = period.year
        
        # Lấy các ngày Thứ 4
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
                "wednesdays": wednesdays,
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
        
        # Get list
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
                r.registered_by
            FROM `tabSIS Menu Registration` r
            INNER JOIN `tabCRM Student` s ON r.student_id = s.name
            LEFT JOIN `tabSIS Class` c ON r.class_id = c.name
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
