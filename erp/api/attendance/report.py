"""
Attendance Report API
Cung cấp các endpoint báo cáo điểm danh FaceID (qua cổng)
"""

import frappe
from frappe import _
import json
from datetime import datetime, timedelta
from erp.utils.api_response import success_response, error_response


@frappe.whitelist(allow_guest=False)
def get_class_faceid_summary(class_id=None, date=None):
    """
    Thống kê điểm danh FaceID cho 1 lớp trong 1 ngày
    
    Args:
        class_id: ID của lớp (SIS Class)
        date: Ngày cần xem (YYYY-MM-DD)
    
    Returns:
        {
            success: true,
            data: {
                class_info: { name, title, homeroom_teacher, total_students },
                summary: { total, checked_in, not_checked_in },
                students: [
                    {
                        student_id, student_name, student_code,
                        check_in_time, check_out_time, total_check_ins,
                        device_name, status  // "checked_in" | "not_checked_in"
                    }
                ]
            }
        }
    """
    try:
        # Lấy params từ request nếu không truyền trực tiếp
        if not class_id:
            class_id = frappe.request.args.get('class_id')
        if not date:
            date = frappe.request.args.get('date')
        
        if not class_id or not date:
            return error_response(
                message="Thiếu tham số: class_id và date là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        # Parse date
        try:
            date_obj = frappe.utils.getdate(date)
        except Exception:
            return error_response(
                message=f"Định dạng ngày không hợp lệ: {date}",
                code="INVALID_DATE"
            )
        
        # Lấy thông tin lớp
        class_doc = frappe.get_doc("SIS Class", class_id)
        
        # Lấy danh sách học sinh trong lớp
        class_students = frappe.db.sql("""
            SELECT 
                cs.student_id,
                s.student_code,
                s.student_name
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
            WHERE cs.class_id = %(class_id)s
            ORDER BY s.student_name
        """, {"class_id": class_id}, as_dict=True)
        
        if not class_students:
            return success_response(
                data={
                    "class_info": {
                        "name": class_doc.name,
                        "title": class_doc.title,
                        "homeroom_teacher": class_doc.homeroom_teacher,
                        "total_students": 0
                    },
                    "summary": {
                        "total": 0,
                        "checked_in": 0,
                        "not_checked_in": 0
                    },
                    "students": []
                },
                message="Lớp không có học sinh"
            )
        
        # Lấy mã học sinh để query attendance
        student_codes = [s['student_code'] for s in class_students if s.get('student_code')]
        
        # Query điểm danh từ ERP Time Attendance
        attendance_records = {}
        if student_codes:
            records = frappe.db.sql("""
                SELECT 
                    employee_code,
                    employee_name,
                    check_in_time,
                    check_out_time,
                    total_check_ins,
                    device_name,
                    raw_data
                FROM `tabERP Time Attendance`
                WHERE employee_code IN %(codes)s
                    AND date = %(date)s
            """, {
                "codes": student_codes,
                "date": date_obj
            }, as_dict=True)
            
            for rec in records:
                attendance_records[rec.employee_code.upper()] = rec
        
        # Build kết quả cho từng học sinh
        students_result = []
        checked_in_count = 0
        
        for student in class_students:
            code = (student.get('student_code') or '').upper()
            att = attendance_records.get(code)
            
            if att:
                checked_in_count += 1
                
                # Recalculate từ raw_data nếu có
                check_in_time = att.check_in_time
                check_out_time = att.check_out_time
                total_check_ins = att.total_check_ins or 0
                
                if att.raw_data:
                    try:
                        raw_data = json.loads(att.raw_data) if isinstance(att.raw_data, str) else att.raw_data
                        if raw_data and len(raw_data) > 0:
                            all_times = []
                            for item in raw_data:
                                ts_str = item.get('timestamp')
                                if ts_str:
                                    all_times.append(frappe.utils.get_datetime(ts_str))
                            if all_times:
                                all_times.sort()
                                check_in_time = all_times[0]
                                check_out_time = all_times[-1]
                                total_check_ins = len(all_times)
                    except Exception:
                        pass
                
                students_result.append({
                    "student_id": student.student_id,
                    "student_name": student.student_name,
                    "student_code": student.student_code,
                    "check_in_time": check_in_time.isoformat() if check_in_time else None,
                    "check_out_time": check_out_time.isoformat() if check_out_time else None,
                    "total_check_ins": total_check_ins,
                    "device_name": att.device_name,
                    "status": "checked_in"
                })
            else:
                students_result.append({
                    "student_id": student.student_id,
                    "student_name": student.student_name,
                    "student_code": student.student_code,
                    "check_in_time": None,
                    "check_out_time": None,
                    "total_check_ins": 0,
                    "device_name": None,
                    "status": "not_checked_in"
                })
        
        total_students = len(class_students)
        
        # Lấy tên giáo viên chủ nhiệm
        homeroom_teacher_name = None
        if class_doc.homeroom_teacher:
            teacher = frappe.get_value("SIS Teacher", class_doc.homeroom_teacher, "teacher_name")
            homeroom_teacher_name = teacher
        
        return success_response(
            data={
                "class_info": {
                    "name": class_doc.name,
                    "title": class_doc.title,
                    "homeroom_teacher": class_doc.homeroom_teacher,
                    "homeroom_teacher_name": homeroom_teacher_name,
                    "total_students": total_students
                },
                "summary": {
                    "total": total_students,
                    "checked_in": checked_in_count,
                    "not_checked_in": total_students - checked_in_count
                },
                "students": students_result
            },
            message="Lấy thống kê điểm danh FaceID thành công"
        )
        
    except frappe.DoesNotExistError:
        return error_response(
            message=f"Không tìm thấy lớp: {class_id}",
            code="CLASS_NOT_FOUND"
        )
    except Exception as e:
        frappe.log_error(f"get_class_faceid_summary error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê điểm danh: {str(e)}",
            code="GET_FACEID_SUMMARY_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_campus_faceid_summary(campus_id=None, date=None):
    """
    Thống kê điểm danh FaceID toàn campus trong 1 ngày
    
    Args:
        campus_id: ID của campus
        date: Ngày cần xem (YYYY-MM-DD)
    
    Returns:
        {
            success: true,
            data: {
                campus_info: { name, title },
                summary: { total_students, checked_in, not_checked_in },
                classes: [
                    { class_id, class_title, total, checked_in, not_checked_in, rate }
                ]
            }
        }
    """
    try:
        if not campus_id:
            campus_id = frappe.request.args.get('campus_id')
        if not date:
            date = frappe.request.args.get('date')
        
        if not campus_id or not date:
            return error_response(
                message="Thiếu tham số: campus_id và date là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        # Parse date
        date_obj = frappe.utils.getdate(date)
        
        # Kiểm tra campus_id có tồn tại không, nếu không thì tìm theo title hoặc lấy campus đầu tiên
        campus_exists = frappe.db.exists("SIS Campus", campus_id)
        if not campus_exists:
            # Thử tìm campus theo title
            campus_id = frappe.db.get_value(
                "SIS Campus",
                {"title_vn": campus_id},
                "name"
            ) or frappe.db.get_value(
                "SIS Campus",
                {"title_en": campus_id},
                "name"
            )
            
            # Nếu vẫn không tìm thấy, lấy campus đầu tiên
            if not campus_id:
                campus_id = frappe.db.get_value("SIS Campus", {}, "name")
            
            if not campus_id:
                return error_response(
                    message="Không tìm thấy campus nào trong hệ thống",
                    code="NO_CAMPUS"
                )
        
        # Tìm năm học theo thứ tự ưu tiên:
        # 1. Năm học có is_enable = 1
        # 2. Năm học mà ngày được chọn nằm trong khoảng start_date - end_date
        # 3. Năm học gần nhất của campus
        school_year = frappe.db.get_value(
            "SIS School Year",
            {"campus_id": campus_id, "is_enable": 1},
            "name"
        )
        
        if not school_year:
            # Tìm năm học theo ngày
            school_year = frappe.db.get_value(
                "SIS School Year",
                {
                    "campus_id": campus_id,
                    "start_date": ["<=", date_obj],
                    "end_date": [">=", date_obj]
                },
                "name"
            )
        
        if not school_year:
            # Lấy năm học gần nhất
            school_year = frappe.db.get_value(
                "SIS School Year",
                {"campus_id": campus_id},
                "name",
                order_by="start_date desc"
            )
        
        if not school_year:
            return error_response(
                message=f"Không tìm thấy năm học cho campus: {campus_id}",
                code="NO_SCHOOL_YEAR"
            )
        
        # Lấy danh sách lớp Regular trong campus (không lấy mixed)
        classes = frappe.get_all(
            "SIS Class",
            filters={
                "campus_id": campus_id,
                "school_year_id": school_year,
                "class_type": "regular"
            },
            fields=["name", "title", "homeroom_teacher"],
            order_by="title asc"
        )
        
        # Lấy tất cả học sinh và mã của họ
        all_student_codes = []
        class_student_map = {}  # class_id -> [student_codes]
        
        for cls in classes:
            students = frappe.db.sql("""
                SELECT s.student_code
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
                WHERE cs.class_id = %(class_id)s
            """, {"class_id": cls.name}, as_dict=True)
            
            codes = [s['student_code'].upper() for s in students if s.get('student_code')]
            class_student_map[cls.name] = codes
            all_student_codes.extend(codes)
        
        # Query tất cả attendance records 1 lần
        attendance_set = set()
        if all_student_codes:
            records = frappe.db.sql("""
                SELECT UPPER(employee_code) as code
                FROM `tabERP Time Attendance`
                WHERE UPPER(employee_code) IN %(codes)s
                    AND date = %(date)s
            """, {
                "codes": list(set(all_student_codes)),
                "date": date_obj
            }, as_dict=True)
            
            attendance_set = {r['code'] for r in records}
        
        # Tính toán thống kê cho từng lớp
        classes_result = []
        total_all = 0
        checked_in_all = 0
        
        for cls in classes:
            codes = class_student_map.get(cls.name, [])
            total = len(codes)
            checked_in = sum(1 for c in codes if c in attendance_set)
            
            total_all += total
            checked_in_all += checked_in
            
            classes_result.append({
                "class_id": cls.name,
                "class_title": cls.title,
                "homeroom_teacher": cls.homeroom_teacher,
                "total": total,
                "checked_in": checked_in,
                "not_checked_in": total - checked_in,
                "rate": round(checked_in / total * 100, 1) if total > 0 else 0
            })
        
        # Sort theo tên lớp (đã được order_by title asc từ query)
        
        return success_response(
            data={
                "campus_info": {
                    "name": campus_id,
                    "school_year": school_year
                },
                "summary": {
                    "total_students": total_all,
                    "checked_in": checked_in_all,
                    "not_checked_in": total_all - checked_in_all,
                    "rate": round(checked_in_all / total_all * 100, 1) if total_all > 0 else 0
                },
                "classes": classes_result
            },
            message="Lấy thống kê điểm danh campus thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_campus_faceid_summary error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê campus: {str(e)}",
            code="GET_CAMPUS_SUMMARY_ERROR"
        )
