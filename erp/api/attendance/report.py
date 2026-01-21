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
                # Phân loại thời gian dựa trên buổi sáng/chiều
                # Buổi sáng: trước 12h → check-in
                # Buổi chiều: sau 12h → check-out
                morning_records = []  # Các lần quét buổi sáng (trước 12h) - {time, device}
                afternoon_records = []  # Các lần quét buổi chiều (sau 12h) - {time, device}
                total_check_ins = att.total_check_ins or 0
                
                if att.raw_data:
                    try:
                        raw_data = json.loads(att.raw_data) if isinstance(att.raw_data, str) else att.raw_data
                        if raw_data and len(raw_data) > 0:
                            for item in raw_data:
                                ts_str = item.get('timestamp')
                                device = item.get('device_name') or item.get('device') or att.device_name
                                if ts_str:
                                    ts = frappe.utils.get_datetime(ts_str)
                                    record = {'time': ts, 'device': device}
                                    if ts.hour < 12:
                                        morning_records.append(record)
                                    else:
                                        afternoon_records.append(record)
                            total_check_ins = len(raw_data)
                    except Exception:
                        pass
                
                # Nếu không có raw_data, dùng check_in_time và check_out_time gốc
                if not morning_records and not afternoon_records:
                    if att.check_in_time:
                        record = {'time': att.check_in_time, 'device': att.device_name}
                        if att.check_in_time.hour < 12:
                            morning_records.append(record)
                        else:
                            afternoon_records.append(record)
                    if att.check_out_time and att.check_out_time != att.check_in_time:
                        record = {'time': att.check_out_time, 'device': att.device_name}
                        if att.check_out_time.hour < 12:
                            morning_records.append(record)
                        else:
                            afternoon_records.append(record)
                
                # Check-in = lần quét sớm nhất buổi sáng
                check_in_record = min(morning_records, key=lambda x: x['time']) if morning_records else None
                check_in_time = check_in_record['time'] if check_in_record else None
                device_in = check_in_record['device'] if check_in_record else None
                
                # Check-out = lần quét muộn nhất buổi chiều
                check_out_record = max(afternoon_records, key=lambda x: x['time']) if afternoon_records else None
                check_out_time = check_out_record['time'] if check_out_record else None
                device_out = check_out_record['device'] if check_out_record else None
                
                # Xác định trạng thái
                status_morning = None  # Trạng thái buổi sáng
                status_afternoon = None  # Trạng thái buổi chiều
                
                if check_in_time:
                    if check_in_time.hour < 8:
                        status_morning = "on_time"  # Đúng giờ
                    else:
                        status_morning = "late"  # Đi muộn
                else:
                    status_morning = "absent_morning"  # Vắng buổi sáng
                
                if check_out_time:
                    if check_out_time.hour >= 16:
                        status_afternoon = "on_time"  # Tan học đúng giờ
                    else:
                        status_afternoon = "early_leave"  # Về sớm
                else:
                    status_afternoon = "no_checkout"  # Chưa check-out
                
                # Tính có điểm danh hay không (có mặt = có ít nhất 1 lần quét sáng)
                has_check_in = check_in_time is not None
                has_check_out = check_out_time is not None
                
                if has_check_in:
                    checked_in_count += 1
                
                students_result.append({
                    "student_id": student.student_id,
                    "student_name": student.student_name,
                    "student_code": student.student_code,
                    "check_in_time": check_in_time.isoformat() if check_in_time else None,
                    "check_out_time": check_out_time.isoformat() if check_out_time else None,
                    "total_check_ins": total_check_ins,
                    "device_name": device_in or device_out,  # Fallback
                    "device_in": device_in,
                    "device_out": device_out,
                    "status": "checked_in" if has_check_in else "absent_morning",
                    "status_morning": status_morning,
                    "status_afternoon": status_afternoon
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
        
        # Lấy tên giáo viên chủ nhiệm (từ User vì SIS Teacher chỉ có user_id)
        homeroom_teacher_name = None
        if class_doc.homeroom_teacher:
            user_id = frappe.get_value("SIS Teacher", class_doc.homeroom_teacher, "user_id")
            if user_id:
                homeroom_teacher_name = frappe.get_value("User", user_id, "full_name")
        
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
        
        # Kiểm tra campus_id có tồn tại không, nếu không thì tìm theo title hoặc lấy campus có school year
        original_campus_id = campus_id
        campus_exists = frappe.db.exists("SIS Campus", campus_id)
        if not campus_exists:
            # Thử tìm campus theo title
            campus_id = frappe.db.get_value(
                "SIS Campus",
                {"title_vn": original_campus_id},
                "name"
            ) or frappe.db.get_value(
                "SIS Campus",
                {"title_en": original_campus_id},
                "name"
            )
            
            # Nếu vẫn không tìm thấy, lấy campus có school year enabled
            if not campus_id:
                school_year_campus = frappe.db.get_value(
                    "SIS School Year",
                    {"is_enable": 1},
                    "campus_id"
                )
                if school_year_campus:
                    campus_id = school_year_campus
            
            # Cuối cùng lấy campus đầu tiên có school year
            if not campus_id:
                campus_id = frappe.db.get_value(
                    "SIS School Year",
                    {},
                    "campus_id",
                    order_by="creation desc"
                )
            
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
        
        # Query tất cả attendance records 1 lần (bao gồm check_in và check_out)
        # Logic: Buổi sáng (trước 12h) = check-in, Buổi chiều (sau 12h) = check-out
        attendance_map = {}  # code -> {has_check_in, has_check_out}
        if all_student_codes:
            records = frappe.db.sql("""
                SELECT 
                    UPPER(employee_code) as code,
                    check_in_time,
                    check_out_time,
                    raw_data
                FROM `tabERP Time Attendance`
                WHERE UPPER(employee_code) IN %(codes)s
                    AND date = %(date)s
            """, {
                "codes": list(set(all_student_codes)),
                "date": date_obj
            }, as_dict=True)
            
            for r in records:
                morning_times = []
                afternoon_times = []
                
                # Phân loại từ raw_data
                if r.get('raw_data'):
                    try:
                        raw_data = json.loads(r['raw_data']) if isinstance(r['raw_data'], str) else r['raw_data']
                        if raw_data:
                            for item in raw_data:
                                ts_str = item.get('timestamp')
                                if ts_str:
                                    ts = frappe.utils.get_datetime(ts_str)
                                    if ts.hour < 12:
                                        morning_times.append(ts)
                                    else:
                                        afternoon_times.append(ts)
                    except Exception:
                        pass
                
                # Fallback nếu không có raw_data
                if not morning_times and not afternoon_times:
                    if r.get('check_in_time'):
                        if r['check_in_time'].hour < 12:
                            morning_times.append(r['check_in_time'])
                        else:
                            afternoon_times.append(r['check_in_time'])
                    if r.get('check_out_time') and r.get('check_out_time') != r.get('check_in_time'):
                        if r['check_out_time'].hour < 12:
                            morning_times.append(r['check_out_time'])
                        else:
                            afternoon_times.append(r['check_out_time'])
                
                attendance_map[r['code']] = {
                    'has_check_in': len(morning_times) > 0,  # Có quét buổi sáng
                    'has_check_out': len(afternoon_times) > 0  # Có quét buổi chiều
                }
        
        # Đếm tổng số đơn nghỉ phép trong ngày (đơn có start_date <= date <= end_date)
        total_leave_requests = frappe.db.count(
            "SIS Student Leave Request",
            filters={
                "campus_id": campus_id,
                "start_date": ["<=", date_obj],
                "end_date": [">=", date_obj]
            }
        )
        
        # Tính toán thống kê cho từng lớp
        classes_result = []
        total_all = 0
        checked_in_all = 0
        checked_out_all = 0
        
        for cls in classes:
            codes = class_student_map.get(cls.name, [])
            total = len(codes)
            checked_in = sum(1 for c in codes if attendance_map.get(c, {}).get('has_check_in', False))
            checked_out = sum(1 for c in codes if attendance_map.get(c, {}).get('has_check_out', False))
            
            total_all += total
            checked_in_all += checked_in
            checked_out_all += checked_out
            
            classes_result.append({
                "class_id": cls.name,
                "class_title": cls.title,
                "homeroom_teacher": cls.homeroom_teacher,
                "total": total,
                "checked_in": checked_in,
                "not_checked_in": total - checked_in,
                "checked_out": checked_out,
                "not_checked_out": total - checked_out,
                "rate_in": round(checked_in / total * 100, 1) if total > 0 else 0,
                "rate_out": round(checked_out / total * 100, 1) if total > 0 else 0
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
                    "checked_out": checked_out_all,
                    "not_checked_out": total_all - checked_out_all,
                    "rate_in": round(checked_in_all / total_all * 100, 1) if total_all > 0 else 0,
                    "rate_out": round(checked_out_all / total_all * 100, 1) if total_all > 0 else 0,
                    "total_leave_requests": total_leave_requests  # Tổng số đơn nghỉ phép trong ngày
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


@frappe.whitelist(allow_guest=False)
def get_campus_leave_requests(campus_id=None, date=None):
    """
    Lấy danh sách đơn nghỉ phép của campus trong ngày
    
    Args:
        campus_id: ID của campus
        date: Ngày cần xem (YYYY-MM-DD)
    
    Returns:
        {
            success: true,
            data: {
                summary: { total, sick_child, family_matters, other },
                requests: [
                    {
                        name, student_id, student_name, student_code,
                        class_id, class_title, parent_id, parent_name,
                        reason, other_reason, start_date, end_date,
                        total_days, description, submitted_at
                    }
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
        
        # Kiểm tra và tìm campus_id thực sự (giống logic trong get_campus_faceid_summary)
        original_campus_id = campus_id
        campus_exists = frappe.db.exists("SIS Campus", campus_id)
        if not campus_exists:
            # Thử tìm campus theo title
            campus_id = frappe.db.get_value(
                "SIS Campus",
                {"title_vn": original_campus_id},
                "name"
            ) or frappe.db.get_value(
                "SIS Campus",
                {"title_en": original_campus_id},
                "name"
            )
            
            # Nếu vẫn không tìm thấy, lấy campus có school year enabled
            if not campus_id:
                school_year_campus = frappe.db.get_value(
                    "SIS School Year",
                    {"is_enable": 1},
                    "campus_id"
                )
                if school_year_campus:
                    campus_id = school_year_campus
            
            # Cuối cùng lấy campus đầu tiên có school year
            if not campus_id:
                campus_id = frappe.db.get_value(
                    "SIS School Year",
                    {},
                    "campus_id",
                    order_by="creation desc"
                )
            
            if not campus_id:
                return error_response(
                    message="Không tìm thấy campus nào trong hệ thống",
                    code="NO_CAMPUS"
                )
        
        # Lấy danh sách đơn nghỉ phép trong ngày (đơn có start_date <= date <= end_date)
        # Sử dụng subquery để lấy duy nhất lớp regular của học sinh, tránh duplicate
        leave_requests = frappe.db.sql("""
            SELECT 
                lr.name,
                lr.student_id,
                lr.student_name,
                lr.student_code,
                lr.parent_id,
                lr.parent_name,
                lr.reason,
                lr.other_reason,
                lr.start_date,
                lr.end_date,
                lr.total_days,
                lr.description,
                lr.submitted_at,
                cls.class_id,
                cls.class_title
            FROM `tabSIS Student Leave Request` lr
            LEFT JOIN (
                SELECT cs.student_id, cs.class_id, c.title as class_title
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id 
                    AND c.class_type = 'regular'
                    AND c.campus_id = %(campus_id)s
            ) cls ON cls.student_id = lr.student_id
            WHERE lr.campus_id = %(campus_id)s
                AND lr.start_date <= %(date)s
                AND lr.end_date >= %(date)s
            ORDER BY lr.submitted_at DESC
        """, {
            "campus_id": campus_id,
            "date": date_obj
        }, as_dict=True)
        
        # Loại bỏ duplicate dựa trên leave request name (mỗi đơn chỉ hiển thị 1 lần)
        seen_requests = set()
        unique_requests = []
        for lr in leave_requests:
            if lr.name not in seen_requests:
                seen_requests.add(lr.name)
                unique_requests.append(lr)
        
        leave_requests = unique_requests
        
        # Đếm theo lý do
        sick_child_count = sum(1 for r in leave_requests if r.get('reason') == 'sick_child')
        family_matters_count = sum(1 for r in leave_requests if r.get('reason') == 'family_matters')
        other_count = sum(1 for r in leave_requests if r.get('reason') == 'other')
        
        # Format kết quả
        requests_result = []
        for lr in leave_requests:
            requests_result.append({
                "name": lr.name,
                "student_id": lr.student_id,
                "student_name": lr.student_name,
                "student_code": lr.student_code,
                "class_id": lr.class_id,
                "class_title": lr.class_title,
                "parent_id": lr.parent_id,
                "parent_name": lr.parent_name,
                "reason": lr.reason,
                "other_reason": lr.other_reason,
                "start_date": str(lr.start_date) if lr.start_date else None,
                "end_date": str(lr.end_date) if lr.end_date else None,
                "total_days": lr.total_days or 1,
                "description": lr.description,
                "submitted_at": lr.submitted_at.isoformat() if lr.submitted_at else None
            })
        
        return success_response(
            data={
                "summary": {
                    "total": len(leave_requests),
                    "sick_child": sick_child_count,
                    "family_matters": family_matters_count,
                    "other": other_count
                },
                "requests": requests_result
            },
            message="Lấy danh sách đơn nghỉ phép thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_campus_leave_requests error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách đơn nghỉ phép: {str(e)}",
            code="GET_LEAVE_REQUESTS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_campus_leave_requests_by_submitted_date(campus_id=None, start_date=None, end_date=None):
    """
    Lấy danh sách đơn nghỉ phép của campus theo thời gian tạo đơn (submitted_at)
    
    Args:
        campus_id: ID của campus
        start_date: Ngày bắt đầu (YYYY-MM-DD) - lọc theo submitted_at
        end_date: Ngày kết thúc (YYYY-MM-DD) - lọc theo submitted_at
    
    Returns:
        {
            success: true,
            data: {
                summary: { total, sick_child, family_matters, other },
                requests: [...]
            }
        }
    """
    try:
        if not campus_id:
            campus_id = frappe.request.args.get('campus_id')
        if not start_date:
            start_date = frappe.request.args.get('start_date')
        if not end_date:
            end_date = frappe.request.args.get('end_date')
        
        if not campus_id or not start_date or not end_date:
            return error_response(
                message="Thiếu tham số: campus_id, start_date và end_date là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        # Parse dates
        start_date_obj = frappe.utils.getdate(start_date)
        end_date_obj = frappe.utils.getdate(end_date)
        
        # Kiểm tra và tìm campus_id thực sự
        original_campus_id = campus_id
        campus_exists = frappe.db.exists("SIS Campus", campus_id)
        if not campus_exists:
            campus_id = frappe.db.get_value(
                "SIS Campus",
                {"title_vn": original_campus_id},
                "name"
            ) or frappe.db.get_value(
                "SIS Campus",
                {"title_en": original_campus_id},
                "name"
            )
            
            if not campus_id:
                school_year_campus = frappe.db.get_value(
                    "SIS School Year",
                    {"is_enable": 1},
                    "campus_id"
                )
                if school_year_campus:
                    campus_id = school_year_campus
            
            if not campus_id:
                campus_id = frappe.db.get_value(
                    "SIS School Year",
                    {},
                    "campus_id",
                    order_by="creation desc"
                )
            
            if not campus_id:
                return error_response(
                    message="Không tìm thấy campus nào trong hệ thống",
                    code="NO_CAMPUS"
                )
        
        # Lấy danh sách đơn nghỉ phép theo thời gian tạo đơn (submitted_at)
        # Lọc: start_date <= DATE(submitted_at) <= end_date
        leave_requests = frappe.db.sql("""
            SELECT 
                lr.name,
                lr.student_id,
                lr.student_name,
                lr.student_code,
                lr.parent_id,
                lr.parent_name,
                lr.reason,
                lr.other_reason,
                lr.start_date,
                lr.end_date,
                lr.total_days,
                lr.description,
                lr.submitted_at,
                cls.class_id,
                cls.class_title
            FROM `tabSIS Student Leave Request` lr
            LEFT JOIN (
                SELECT cs.student_id, cs.class_id, c.title as class_title
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id 
                    AND c.class_type = 'regular'
                    AND c.campus_id = %(campus_id)s
            ) cls ON cls.student_id = lr.student_id
            WHERE lr.campus_id = %(campus_id)s
                AND DATE(lr.submitted_at) >= %(start_date)s
                AND DATE(lr.submitted_at) <= %(end_date)s
            ORDER BY lr.submitted_at DESC
        """, {
            "campus_id": campus_id,
            "start_date": start_date_obj,
            "end_date": end_date_obj
        }, as_dict=True)
        
        # Loại bỏ duplicate
        seen_requests = set()
        unique_requests = []
        for lr in leave_requests:
            if lr.name not in seen_requests:
                seen_requests.add(lr.name)
                unique_requests.append(lr)
        
        leave_requests = unique_requests
        
        # Đếm theo lý do
        sick_child_count = sum(1 for r in leave_requests if r.get('reason') == 'sick_child')
        family_matters_count = sum(1 for r in leave_requests if r.get('reason') == 'family_matters')
        other_count = sum(1 for r in leave_requests if r.get('reason') == 'other')
        
        # Format kết quả
        requests_result = []
        for lr in leave_requests:
            requests_result.append({
                "name": lr.name,
                "student_id": lr.student_id,
                "student_name": lr.student_name,
                "student_code": lr.student_code,
                "class_id": lr.class_id,
                "class_title": lr.class_title,
                "parent_id": lr.parent_id,
                "parent_name": lr.parent_name,
                "reason": lr.reason,
                "other_reason": lr.other_reason,
                "start_date": str(lr.start_date) if lr.start_date else None,
                "end_date": str(lr.end_date) if lr.end_date else None,
                "total_days": lr.total_days or 1,
                "description": lr.description,
                "submitted_at": lr.submitted_at.isoformat() if lr.submitted_at else None
            })
        
        return success_response(
            data={
                "summary": {
                    "total": len(leave_requests),
                    "sick_child": sick_child_count,
                    "family_matters": family_matters_count,
                    "other": other_count
                },
                "requests": requests_result
            },
            message="Lấy danh sách đơn nghỉ phép theo thời gian tạo thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_campus_leave_requests_by_submitted_date error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách đơn nghỉ phép: {str(e)}",
            code="GET_LEAVE_REQUESTS_ERROR"
        )
