"""
Class Log Report API
Cung cấp các endpoint báo cáo sổ đầu bài
"""

import frappe
from frappe import _
import json
import re
from datetime import datetime, timedelta
from erp.utils.api_response import success_response, error_response


def _get_json_body():
    """Helper để parse JSON từ request body"""
    try:
        if hasattr(frappe, 'request') and getattr(frappe.request, 'data', None):
            return json.loads(frappe.request.data.decode('utf-8'))
    except Exception:
        return {}
    return {}


def _extract_period_number(period_name):
    """
    Extract số đầu tiên từ tên tiết để sort và match
    Ví dụ: "Tiết 1 + 2" -> 1, "Tiết 11" -> 11
    """
    match = re.search(r'\d+', period_name or '')
    return int(match.group()) if match else 999


def _calculate_class_periods_stats(class_id, date_obj, timetable_instance, homeroom_teacher=None, homeroom_teacher_name=None):
    """
    Tính toán số liệu sổ đầu bài cho 1 lớp (logic dùng chung cho dashboard và detail)
    
    Args:
        class_id: ID của lớp
        date_obj: Date object
        timetable_instance: ID của timetable instance
        homeroom_teacher: ID giáo viên chủ nhiệm (optional, cho detail)
        homeroom_teacher_name: Tên giáo viên chủ nhiệm (optional, cho detail)
    
    Returns:
        {
            "total_periods": int,  # Số tiết Study (không tính Homeroom)
            "entered_periods": int,  # Số tiết đã nhập
            "periods_detail": [  # Chi tiết từng tiết (cho detail API)
                {
                    "period": str,
                    "subject_id": str,
                    "subject_name": str,
                    "teacher_id": str,
                    "teacher_name": str,
                    "status": "entered" | "not_entered" | "updated",
                    "has_general_comment": bool,
                    "student_count_with_log": int,
                    "last_modified": str
                }
            ],
            "period_numbers": set  # Set các period_number có trong timetable
        }
    """
    if not timetable_instance:
        return {
            "total_periods": 0,
            "entered_periods": 0,
            "periods_detail": [],
            "period_numbers": set()
        }
    
    # day_of_week trong database là format viết tắt: mon, tue, wed, thu, fri, sat, sun
    day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
    day_of_week_short = day_map.get(date_obj.weekday(), 'mon')
    
    # Lấy các tiết học trong ngày (chỉ tiết Study - có chứa "tiết")
    # GROUP BY period_name để tránh duplicate
    periods_data = frappe.db.sql("""
        SELECT 
            tc.period_name,
            MIN(tc.period_priority) as period_priority,
            MAX(tr.subject_id) as subject_id,
            MAX(COALESCE(ts.title_vn, sub.title)) as subject_name,
            MAX(COALESCE(trt.teacher_id, tr.teacher_1_id)) as teacher_id,
            MAX(COALESCE(u_new.full_name, u_old.full_name)) as teacher_name
        FROM `tabSIS Timetable Instance Row` tr
        INNER JOIN `tabSIS Timetable Column` tc ON tr.timetable_column_id = tc.name
        LEFT JOIN `tabSIS Subject` sub ON tr.subject_id = sub.name
        LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
        LEFT JOIN `tabSIS Timetable Instance Row Teacher` trt ON trt.parent = tr.name 
            AND trt.idx = (SELECT MIN(idx) FROM `tabSIS Timetable Instance Row Teacher` WHERE parent = tr.name)
        LEFT JOIN `tabSIS Teacher` t_new ON trt.teacher_id = t_new.name
        LEFT JOIN `tabUser` u_new ON t_new.user_id = u_new.name
        LEFT JOIN `tabSIS Teacher` t_old ON tr.teacher_1_id = t_old.name
        LEFT JOIN `tabUser` u_old ON t_old.user_id = u_old.name
        WHERE tr.parent = %(instance)s
            AND tr.day_of_week = %(day)s
            AND LOWER(tc.period_name) LIKE '%%tiết%%'
            AND (tr.valid_from IS NULL OR tr.valid_from <= %(date)s)
            AND (tr.valid_to IS NULL OR tr.valid_to >= %(date)s)
        GROUP BY tc.period_name
        ORDER BY MIN(tc.period_priority) ASC
    """, {
        "instance": timetable_instance,
        "day": day_of_week_short,
        "date": date_obj
    }, as_dict=True)
    
    # Sort theo số tiết
    periods_data.sort(key=lambda p: _extract_period_number(p.get('period_name', '')))
    
    # Build period_number_map: period_number -> timetable period_name
    period_number_map = {}
    period_numbers = set()
    for p in periods_data:
        pnum = _extract_period_number(p.get('period_name', ''))
        if pnum not in period_number_map:
            period_number_map[pnum] = p['period_name']
        period_numbers.add(pnum)
    
    # Lấy danh sách học sinh trong lớp
    homeroom_students = frappe.get_all(
        "SIS Class Student",
        filters={"class_id": class_id},
        fields=["student_id"]
    )
    student_ids = [s['student_id'] for s in homeroom_students if s.get('student_id')]
    
    # Query SIS Student Timetable để tìm mixed class cho từng tiết
    mixed_classes = set()
    student_period_class = {}  # (student_id, period_name) -> class_id
    
    if student_ids:
        student_timetable = frappe.db.sql("""
            SELECT 
                st.student_id,
                st.class_id,
                tc.period_name
            FROM `tabSIS Student Timetable` st
            INNER JOIN `tabSIS Timetable Column` tc ON st.timetable_column_id = tc.name
            WHERE st.student_id IN %(student_ids)s
                AND st.date = %(date)s
                AND LOWER(tc.period_name) LIKE '%%tiết%%'
        """, {
            "student_ids": student_ids,
            "date": date_obj
        }, as_dict=True)
        
        for entry in student_timetable:
            if entry['class_id'] != class_id:
                mixed_classes.add(entry['class_id'])
            student_period_class[(entry['student_id'], entry['period_name'])] = entry['class_id']
    
    # Query class logs từ homeroom class
    log_map = {}  # period_number -> log
    period_names = [p['period_name'] for p in periods_data]
    
    if period_names:
        class_log_subjects = frappe.db.sql("""
            SELECT 
                cls.name,
                cls.period,
                cls.class_id,
                cls.general_comment,
                cls.modified,
                cls.creation,
                COUNT(clst.name) as student_log_count
            FROM `tabSIS Class Log Subject` cls
            LEFT JOIN `tabSIS Class Log Student` clst ON clst.subject_id = cls.name
            WHERE cls.class_id = %(class_id)s
                AND cls.log_date = %(date)s
                AND LOWER(cls.period) LIKE '%%tiết%%'
                AND (cls.general_comment IS NOT NULL AND cls.general_comment != '' 
                     OR clst.name IS NOT NULL)
            GROUP BY cls.name, cls.period
        """, {
            "class_id": class_id,
            "date": date_obj
        }, as_dict=True)
        
        # Build log_map theo số tiết đầu tiên
        for log in class_log_subjects:
            period_num = _extract_period_number(log['period'])
            # Chỉ đếm nếu period_number này có trong timetable của lớp
            if period_num in period_numbers and period_num not in log_map:
                log_map[period_num] = log
        
        # Query class logs từ mixed classes
        if mixed_classes:
            mixed_log_subjects = frappe.db.sql("""
                SELECT 
                    cls.name,
                    cls.period,
                    cls.class_id,
                    cls.general_comment,
                    cls.modified,
                    cls.creation,
                    COUNT(clst.name) as student_log_count
                FROM `tabSIS Class Log Subject` cls
                LEFT JOIN `tabSIS Class Log Student` clst ON clst.subject_id = cls.name
                WHERE cls.class_id IN %(mixed_class_ids)s
                    AND cls.log_date = %(date)s
                    AND LOWER(cls.period) LIKE '%%tiết%%'
                    AND (cls.general_comment IS NOT NULL AND cls.general_comment != '' 
                         OR clst.name IS NOT NULL)
                GROUP BY cls.name, cls.period
            """, {
                "mixed_class_ids": list(mixed_classes),
                "date": date_obj
            }, as_dict=True)
            
            for log in mixed_log_subjects:
                period_num = _extract_period_number(log['period'])
                # Chỉ đếm nếu period_number này có trong timetable của homeroom class
                if period_num not in period_numbers:
                    continue
                    
                if period_num not in log_map:
                    log_map[period_num] = log
                else:
                    # Nếu cả 2 đều có log, ưu tiên cái có content
                    existing = log_map[period_num]
                    has_existing_content = existing.get('general_comment') or existing.get('student_log_count', 0) > 0
                    has_new_content = log.get('general_comment') or log.get('student_log_count', 0) > 0
                    
                    if not has_existing_content and has_new_content:
                        log_map[period_num] = log
    
    # Build periods detail
    periods_detail = []
    entered_count = 0
    
    for p in periods_data:
        period_name = p['period_name']
        period_num = _extract_period_number(period_name)
        log = log_map.get(period_num)
        
        if log:
            has_content = log.get('general_comment') or log.get('student_log_count', 0) > 0
            if has_content:
                status = "updated" if log.get('modified') != log.get('creation') else "entered"
                entered_count += 1
            else:
                status = "not_entered"
            
            periods_detail.append({
                "period": period_name,
                "subject_id": p.get('subject_id'),
                "subject_name": p.get('subject_name'),
                "teacher_id": p.get('teacher_id'),
                "teacher_name": p.get('teacher_name'),
                "status": status,
                "has_general_comment": bool(log.get('general_comment')),
                "student_count_with_log": log.get('student_log_count', 0),
                "last_modified": log.get('modified').isoformat() if log.get('modified') else None
            })
        else:
            periods_detail.append({
                "period": period_name,
                "subject_id": p.get('subject_id'),
                "subject_name": p.get('subject_name'),
                "teacher_id": p.get('teacher_id'),
                "teacher_name": p.get('teacher_name'),
                "status": "not_entered",
                "has_general_comment": False,
                "student_count_with_log": 0,
                "last_modified": None
            })
    
    return {
        "total_periods": len(periods_data),
        "entered_periods": entered_count,
        "periods_detail": periods_detail,
        "period_numbers": period_numbers
    }


def _calculate_contact_log_stats(class_id, date_obj, include_students_detail=False):
    """
    Tính toán số liệu sổ liên lạc cho 1 lớp (logic dùng chung cho dashboard và detail)
    
    Args:
        class_id: ID của lớp
        date_obj: Date object
        include_students_detail: Có trả về danh sách học sinh chi tiết không
    
    Returns:
        {
            "total_students": int,
            "sent_count": int,
            "not_sent_count": int,
            "rate": float,
            "students": [  # Chỉ có khi include_students_detail=True
                {
                    "student_id": str,
                    "student_name": str,
                    "is_sent": bool,
                    "viewed_count": int
                }
            ]
        }
    """
    # Lấy danh sách học sinh trong lớp
    students = frappe.db.sql("""
        SELECT 
            cs.student_id,
            s.student_name
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
        WHERE cs.class_id = %(class_id)s
        ORDER BY s.student_name
    """, {"class_id": class_id}, as_dict=True)
    
    total_students = len(students)
    
    if total_students == 0:
        result = {
            "total_students": 0,
            "sent_count": 0,
            "not_sent_count": 0,
            "rate": 0
        }
        if include_students_detail:
            result["students"] = []
        return result
    
    # Lấy contact log status cho ngày này
    # Đếm distinct student_id có contact_log_status = 'Sent'
    contact_logs = frappe.db.sql("""
        SELECT 
            clst.student_id,
            clst.contact_log_status,
            clst.contact_log_viewed_count
        FROM `tabSIS Class Log Subject` cls
        INNER JOIN `tabSIS Class Log Student` clst ON clst.subject_id = cls.name
        WHERE cls.class_id = %(class_id)s
            AND cls.log_date = %(date)s
    """, {
        "class_id": class_id,
        "date": date_obj
    }, as_dict=True)
    
    # Build contact_log_map: student_id -> {status, viewed_count}
    # Một student có thể xuất hiện nhiều lần (nhiều tiết), lấy status 'Sent' nếu có bất kỳ record nào là Sent
    contact_log_map = {}
    for log in contact_logs:
        student_id = log['student_id']
        if student_id not in contact_log_map:
            contact_log_map[student_id] = {
                "status": log.get('contact_log_status'),
                "viewed_count": log.get('contact_log_viewed_count') or 0
            }
        else:
            # Nếu đã có record, ưu tiên status 'Sent'
            if log.get('contact_log_status') == 'Sent':
                contact_log_map[student_id]["status"] = 'Sent'
            # Cộng dồn viewed_count
            contact_log_map[student_id]["viewed_count"] += log.get('contact_log_viewed_count') or 0
    
    # Đếm số học sinh đã gửi
    sent_count = 0
    students_result = []
    
    for student in students:
        contact_info = contact_log_map.get(student['student_id'], {})
        is_sent = contact_info.get('status') == 'Sent'
        
        if is_sent:
            sent_count += 1
        
        if include_students_detail:
            students_result.append({
                "student_id": student['student_id'],
                "student_name": student['student_name'],
                "is_sent": is_sent,
                "viewed_count": contact_info.get('viewed_count', 0)
            })
    
    result = {
        "total_students": total_students,
        "sent_count": sent_count,
        "not_sent_count": total_students - sent_count,
        "rate": round(sent_count / total_students * 100, 1) if total_students > 0 else 0
    }
    
    if include_students_detail:
        result["students"] = students_result
    
    return result


@frappe.whitelist(allow_guest=False)
def get_class_log_status(class_id=None, date=None):
    """
    Lấy trạng thái nhập sổ đầu bài của 1 lớp trong 1 ngày
    
    Args:
        class_id: ID của lớp
        date: Ngày cần xem (YYYY-MM-DD)
    
    Returns:
        {
            success: true,
            data: {
                class_info: { name, title, homeroom_teacher },
                periods: [
                    {
                        period, subject_id, subject_name,
                        teacher_id, teacher_name,
                        status: "entered" | "not_entered" | "updated",
                        has_general_comment, student_count_with_log,
                        last_modified
                    }
                ],
                summary: { total_periods, entered, not_entered, rate }
            }
        }
    """
    try:
        if not class_id:
            class_id = frappe.request.args.get('class_id')
        if not date:
            date = frappe.request.args.get('date')
        
        if not class_id or not date:
            return error_response(
                message="Thiếu tham số: class_id và date là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        date_obj = frappe.utils.getdate(date)
        
        # Lấy thông tin lớp
        class_doc = frappe.get_doc("SIS Class", class_id)
        
        # Lấy tên giáo viên chủ nhiệm qua User.full_name
        homeroom_teacher_name = None
        if class_doc.homeroom_teacher:
            teacher_user_id = frappe.get_value("SIS Teacher", class_doc.homeroom_teacher, "user_id")
            if teacher_user_id:
                homeroom_teacher_name = frappe.get_value("User", teacher_user_id, "full_name")
        
        # Lấy timetable instance (xử lý cả trường hợp end_date là NULL)
        timetable_instance_result = frappe.db.sql("""
            SELECT name FROM `tabSIS Timetable Instance`
            WHERE class_id = %(class_id)s
                AND start_date <= %(date)s
                AND (end_date >= %(date)s OR end_date IS NULL)
            LIMIT 1
        """, {
            "class_id": class_id,
            "date": date_obj
        }, as_dict=True)
        timetable_instance = timetable_instance_result[0].name if timetable_instance_result else None
        
        if not timetable_instance:
            return success_response(
                data={
                    "class_info": {
                        "name": class_doc.name,
                        "title": class_doc.title,
                        "homeroom_teacher": class_doc.homeroom_teacher,
                        "homeroom_teacher_name": homeroom_teacher_name
                    },
                    "periods": [],
                    "summary": {
                        "total_periods": 0,
                        "entered": 0,
                        "not_entered": 0,
                        "rate": 0
                    }
                },
                message="Không có thời khóa biểu cho ngày này"
            )
        
        # Lấy các tiết học trong ngày
        # day_of_week trong database là format viết tắt: mon, tue, wed, thu, fri, sat, sun
        day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        day_of_week_short = day_map.get(date_obj.weekday(), 'mon')
        
        # Lấy giáo viên từ child table hoặc deprecated field
        periods_data = frappe.db.sql("""
            SELECT 
                tc.period_name,
                tr.subject_id,
                COALESCE(ts.title_vn, sub.title) as subject_name,
                COALESCE(trt.teacher_id, tr.teacher_1_id) as teacher_id,
                COALESCE(u_new.full_name, u_old.full_name) as teacher_name
            FROM `tabSIS Timetable Instance Row` tr
            INNER JOIN `tabSIS Timetable Column` tc ON tr.timetable_column_id = tc.name
            LEFT JOIN `tabSIS Subject` sub ON tr.subject_id = sub.name
            LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
            -- Lấy giáo viên từ child table (ưu tiên sort_order nhỏ nhất)
            LEFT JOIN `tabSIS Timetable Instance Row Teacher` trt ON trt.parent = tr.name 
                AND trt.idx = (SELECT MIN(idx) FROM `tabSIS Timetable Instance Row Teacher` WHERE parent = tr.name)
            LEFT JOIN `tabSIS Teacher` t_new ON trt.teacher_id = t_new.name
            LEFT JOIN `tabUser` u_new ON t_new.user_id = u_new.name
            -- Fallback: lấy từ deprecated field
            LEFT JOIN `tabSIS Teacher` t_old ON tr.teacher_1_id = t_old.name
            LEFT JOIN `tabUser` u_old ON t_old.user_id = u_old.name
            WHERE tr.parent = %(instance)s
                AND tr.day_of_week = %(day)s
                AND (tr.valid_from IS NULL OR tr.valid_from <= %(date)s)
                AND (tr.valid_to IS NULL OR tr.valid_to >= %(date)s)
            ORDER BY tc.period_name
        """, {
            "instance": timetable_instance,
            "day": day_of_week_short,
            "date": date_obj
        }, as_dict=True)
        
        # Thêm Homeroom
        periods_data.append({
            "period_name": "Homeroom",
            "subject_id": None,
            "subject_name": "Homeroom",
            "teacher_id": class_doc.homeroom_teacher,
            "teacher_name": homeroom_teacher_name
        })
        
        # Lấy class log subjects đã tạo
        period_names = [p['period_name'] for p in periods_data]
        
        class_log_subjects = frappe.db.sql("""
            SELECT 
                cls.name,
                cls.period,
                cls.general_comment,
                cls.modified,
                cls.creation,
                COUNT(clst.name) as student_log_count
            FROM `tabSIS Class Log Subject` cls
            LEFT JOIN `tabSIS Class Log Student` clst ON clst.subject_id = cls.name
            WHERE cls.timetable_instance_id = %(instance)s
                AND cls.log_date = %(date)s
                AND cls.period IN %(periods)s
            GROUP BY cls.name
        """, {
            "instance": timetable_instance,
            "date": date_obj,
            "periods": period_names
        }, as_dict=True)
        
        # Build map: period -> log subject
        log_map = {}
        for log in class_log_subjects:
            log_map[log['period']] = log
        
        # Build kết quả
        periods_result = []
        entered_count = 0
        
        for p in periods_data:
            period_name = p['period_name']
            log = log_map.get(period_name)
            
            if log:
                # Có log -> kiểm tra đã nhập hay chưa
                has_content = log.get('general_comment') or log.get('student_log_count', 0) > 0
                
                if has_content:
                    # Kiểm tra có cập nhật sau khi tạo không
                    status = "updated" if log.get('modified') != log.get('creation') else "entered"
                    entered_count += 1
                else:
                    status = "not_entered"
                
                periods_result.append({
                    "period": period_name,
                    "subject_id": p.get('subject_id'),
                    "subject_name": p.get('subject_name'),
                    "teacher_id": p.get('teacher_id'),
                    "teacher_name": p.get('teacher_name'),
                    "status": status,
                    "has_general_comment": bool(log.get('general_comment')),
                    "student_count_with_log": log.get('student_log_count', 0),
                    "last_modified": log.get('modified').isoformat() if log.get('modified') else None
                })
            else:
                periods_result.append({
                    "period": period_name,
                    "subject_id": p.get('subject_id'),
                    "subject_name": p.get('subject_name'),
                    "teacher_id": p.get('teacher_id'),
                    "teacher_name": p.get('teacher_name'),
                    "status": "not_entered",
                    "has_general_comment": False,
                    "student_count_with_log": 0,
                    "last_modified": None
                })
        
        total_periods = len(periods_result)
        
        return success_response(
            data={
                "class_info": {
                    "name": class_doc.name,
                    "title": class_doc.title,
                    "homeroom_teacher": class_doc.homeroom_teacher,
                    "homeroom_teacher_name": homeroom_teacher_name
                },
                "periods": periods_result,
                "summary": {
                    "total_periods": total_periods,
                    "entered": entered_count,
                    "not_entered": total_periods - entered_count,
                    "rate": round(entered_count / total_periods * 100, 1) if total_periods > 0 else 0
                }
            },
            message="Lấy trạng thái sổ đầu bài thành công"
        )
        
    except frappe.DoesNotExistError:
        return error_response(
            message=f"Không tìm thấy lớp: {class_id}",
            code="CLASS_NOT_FOUND"
        )
    except Exception as e:
        frappe.log_error(f"get_class_log_status error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy trạng thái sổ đầu bài: {str(e)}",
            code="GET_CLASS_LOG_STATUS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_teacher_class_log_summary(teacher_id=None, start_date=None, end_date=None):
    """
    Thống kê sổ đầu bài của 1 giáo viên trong khoảng thời gian
    
    Args:
        teacher_id: ID của giáo viên
        start_date: Ngày bắt đầu (YYYY-MM-DD)
        end_date: Ngày kết thúc (YYYY-MM-DD)
    
    Returns:
        {
            success: true,
            data: {
                teacher_info: { name, teacher_name, subjects },
                summary: { total_periods, entered, not_entered, rate },
                logs: [
                    {
                        date, class_id, class_title, period, subject_name,
                        status, last_modified
                    }
                ]
            }
        }
    """
    try:
        if not teacher_id:
            teacher_id = frappe.request.args.get('teacher_id')
        if not start_date:
            start_date = frappe.request.args.get('start_date')
        if not end_date:
            end_date = frappe.request.args.get('end_date')
        
        if not teacher_id:
            return error_response(
                message="Thiếu tham số: teacher_id là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        # Default date range: 7 ngày gần nhất
        if not end_date:
            end_date_obj = frappe.utils.today()
        else:
            end_date_obj = frappe.utils.getdate(end_date)
        
        if not start_date:
            start_date_obj = end_date_obj - timedelta(days=6)
        else:
            start_date_obj = frappe.utils.getdate(start_date)
        
        # Lấy thông tin giáo viên
        teacher = frappe.get_doc("SIS Teacher", teacher_id)
        
        # Lấy tên giáo viên từ User.full_name
        teacher_full_name = None
        if teacher.user_id:
            teacher_full_name = frappe.get_value("User", teacher.user_id, "full_name")
        
        # Lấy các môn giáo viên dạy - sử dụng SIS Timetable Instance Row
        teacher_subjects = frappe.db.sql("""
            SELECT DISTINCT s.name, s.title
            FROM `tabSIS Timetable Instance Row` tr
            INNER JOIN `tabSIS Subject` s ON tr.subject_id = s.name
            WHERE tr.teacher_1_id = %(teacher_id)s
        """, {"teacher_id": teacher_id}, as_dict=True)
        
        # Lấy tất cả các tiết GV đã dạy trong khoảng thời gian
        # Query từ timetable - sử dụng SIS Timetable Instance Row
        scheduled_periods = frappe.db.sql("""
            SELECT DISTINCT
                ti.class_id,
                c.title as class_title,
                tc.period_name,
                tr.subject_id,
                COALESCE(ts.title_vn, sub.title) as subject_name,
                tr.day_of_week
            FROM `tabSIS Timetable Instance Row` tr
            INNER JOIN `tabSIS Timetable Instance` ti ON tr.parent = ti.name
            INNER JOIN `tabSIS Timetable Column` tc ON tr.timetable_column_id = tc.name
            INNER JOIN `tabSIS Class` c ON ti.class_id = c.name
            LEFT JOIN `tabSIS Subject` sub ON tr.subject_id = sub.name
            LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
            WHERE tr.teacher_1_id = %(teacher_id)s
                AND ti.start_date <= %(end_date)s
                AND (ti.end_date >= %(start_date)s OR ti.end_date IS NULL)
        """, {
            "teacher_id": teacher_id,
            "start_date": start_date_obj,
            "end_date": end_date_obj
        }, as_dict=True)
        
        # Cũng kiểm tra các lớp mà GV là chủ nhiệm
        homeroom_classes = frappe.get_all(
            "SIS Class",
            filters={"homeroom_teacher": teacher_id},
            fields=["name", "title"]
        )
        
        # Map day_of_week format: database dùng 'mon', 'tue', v.v.
        day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        
        # Generate all expected logs based on schedule and date range
        expected_logs = []
        current_date = start_date_obj
        
        while current_date <= end_date_obj:
            day_short = day_map.get(current_date.weekday(), 'mon')
            
            # Thêm các tiết theo lịch
            for period in scheduled_periods:
                if period['day_of_week'] == day_short:
                    expected_logs.append({
                        "date": current_date,
                        "class_id": period['class_id'],
                        "class_title": period['class_title'],
                        "period": period['period_name'],
                        "subject_id": period['subject_id'],
                        "subject_name": period['subject_name'],
                        "is_homeroom": False
                    })
            
            # Thêm Homeroom cho các lớp chủ nhiệm
            for cls in homeroom_classes:
                expected_logs.append({
                    "date": current_date,
                    "class_id": cls.name,
                    "class_title": cls.title,
                    "period": "Homeroom",
                    "subject_id": None,
                    "subject_name": "Homeroom",
                    "is_homeroom": True
                })
            
            current_date += timedelta(days=1)
        
        # Lấy tất cả class log subjects đã tạo cho các lớp/tiết này
        if expected_logs:
            class_ids = list(set(e['class_id'] for e in expected_logs))
            
            actual_logs = frappe.db.sql("""
                SELECT 
                    cls.name,
                    cls.class_id,
                    cls.log_date,
                    cls.period,
                    cls.general_comment,
                    cls.modified,
                    cls.creation,
                    COUNT(clst.name) as student_log_count
                FROM `tabSIS Class Log Subject` cls
                LEFT JOIN `tabSIS Class Log Student` clst ON clst.subject_id = cls.name
                WHERE cls.class_id IN %(class_ids)s
                    AND cls.log_date BETWEEN %(start)s AND %(end)s
                    AND cls.recorded_by IN (
                        SELECT u.name FROM `tabUser` u
                        INNER JOIN `tabSIS Teacher` t ON t.user_id = u.name
                        WHERE t.name = %(teacher_id)s
                    )
                GROUP BY cls.name
            """, {
                "class_ids": class_ids,
                "start": start_date_obj,
                "end": end_date_obj,
                "teacher_id": teacher_id
            }, as_dict=True)
            
            # Build map: (class_id, date, period) -> log
            log_map = {}
            for log in actual_logs:
                key = (log['class_id'], str(log['log_date']), log['period'])
                log_map[key] = log
        else:
            log_map = {}
        
        # Build kết quả
        logs_result = []
        entered_count = 0
        
        for exp in expected_logs:
            key = (exp['class_id'], str(exp['date']), exp['period'])
            actual = log_map.get(key)
            
            if actual:
                has_content = actual.get('general_comment') or actual.get('student_log_count', 0) > 0
                if has_content:
                    status = "updated" if actual.get('modified') != actual.get('creation') else "entered"
                    entered_count += 1
                else:
                    status = "not_entered"
                
                logs_result.append({
                    "date": str(exp['date']),
                    "class_id": exp['class_id'],
                    "class_title": exp['class_title'],
                    "period": exp['period'],
                    "subject_name": exp['subject_name'],
                    "status": status,
                    "last_modified": actual.get('modified').isoformat() if actual.get('modified') else None
                })
            else:
                logs_result.append({
                    "date": str(exp['date']),
                    "class_id": exp['class_id'],
                    "class_title": exp['class_title'],
                    "period": exp['period'],
                    "subject_name": exp['subject_name'],
                    "status": "not_entered",
                    "last_modified": None
                })
        
        # Sort by date desc, then period
        logs_result.sort(key=lambda x: (x['date'], x['period']), reverse=True)
        
        total_periods = len(expected_logs)
        
        return success_response(
            data={
                "teacher_info": {
                    "name": teacher.name,
                    "teacher_name": teacher_full_name,
                    "subjects": [{"name": s['name'], "title": s['title']} for s in teacher_subjects]
                },
                "summary": {
                    "total_periods": total_periods,
                    "entered": entered_count,
                    "not_entered": total_periods - entered_count,
                    "rate": round(entered_count / total_periods * 100, 1) if total_periods > 0 else 0
                },
                "logs": logs_result,
                "date_range": {
                    "start": str(start_date_obj),
                    "end": str(end_date_obj)
                }
            },
            message="Lấy thống kê sổ đầu bài giáo viên thành công"
        )
        
    except frappe.DoesNotExistError:
        return error_response(
            message=f"Không tìm thấy giáo viên: {teacher_id}",
            code="TEACHER_NOT_FOUND"
        )
    except Exception as e:
        frappe.log_error(f"get_teacher_class_log_summary error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê sổ đầu bài: {str(e)}",
            code="GET_TEACHER_LOG_SUMMARY_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_campus_class_log_overview(campus_id=None, date=None):
    """
    Thống kê tổng quan sổ đầu bài toàn campus trong 1 ngày
    
    Args:
        campus_id: Campus ID
        date: Ngày cần xem (YYYY-MM-DD)
    
    Returns:
        {
            success: true,
            data: {
                summary: { total_periods, entered, not_entered, rate },
                classes: [
                    { class_id, class_title, total, entered, not_entered, rate }
                ]
            }
        }
    """
    try:
        if not campus_id:
            campus_id = frappe.request.args.get('campus_id')
        if not date:
            date = frappe.request.args.get('date')
        
        if not date:
            return error_response(
                message="Thiếu tham số: date là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        date_obj = frappe.utils.getdate(date)
        
        # Lấy campus từ context nếu không truyền
        if not campus_id:
            try:
                from erp.sis.utils.campus_permissions import get_current_user_campus
                campus_id = get_current_user_campus()
            except Exception:
                pass
        
        # Lấy active school year (is_enable = 1)
        school_year_filters = {"is_enable": 1}
        if campus_id:
            school_year_filters["campus_id"] = campus_id
        
        school_year = frappe.db.get_value("SIS School Year", school_year_filters, "name")
        
        # Lấy danh sách lớp
        class_filters = {
            "school_year_id": school_year,
            "class_type": "Regular"
        }
        if campus_id:
            class_filters["campus_id"] = campus_id
        
        classes = frappe.get_all(
            "SIS Class",
            filters=class_filters,
            fields=["name", "title"]
        )
        
        if not classes:
            return success_response(
                data={
                    "summary": {
                        "total_periods": 0,
                        "entered": 0,
                        "not_entered": 0,
                        "rate": 0
                    },
                    "classes": []
                },
                message="Không có lớp nào"
            )
        
        class_ids = [c.name for c in classes]
        
        # day_of_week trong database là format viết tắt: mon, tue, wed, thu, fri, sat, sun
        day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        day_of_week_short = day_map.get(date_obj.weekday(), 'mon')
        
        # Đếm số tiết theo lịch cho mỗi lớp
        scheduled_counts = frappe.db.sql("""
            SELECT 
                ti.class_id,
                COUNT(DISTINCT tc.period_name) as period_count
            FROM `tabSIS Timetable Instance` ti
            INNER JOIN `tabSIS Timetable Instance Row` tr ON tr.parent = ti.name
            INNER JOIN `tabSIS Timetable Column` tc ON tr.timetable_column_id = tc.name
            WHERE ti.class_id IN %(class_ids)s
                AND ti.start_date <= %(date)s
                AND (ti.end_date >= %(date)s OR ti.end_date IS NULL)
                AND tr.day_of_week = %(day)s
                AND (tr.valid_from IS NULL OR tr.valid_from <= %(date)s)
                AND (tr.valid_to IS NULL OR tr.valid_to >= %(date)s)
            GROUP BY ti.class_id
        """, {
            "class_ids": class_ids,
            "date": date_obj,
            "day": day_of_week_short
        }, as_dict=True)
        
        scheduled_map = {r['class_id']: r['period_count'] + 1 for r in scheduled_counts}  # +1 for Homeroom
        
        # Đếm số log đã nhập
        entered_counts = frappe.db.sql("""
            SELECT 
                cls.class_id,
                COUNT(DISTINCT cls.period) as entered_count
            FROM `tabSIS Class Log Subject` cls
            LEFT JOIN `tabSIS Class Log Student` clst ON clst.subject_id = cls.name
            WHERE cls.class_id IN %(class_ids)s
                AND cls.log_date = %(date)s
                AND (cls.general_comment IS NOT NULL OR clst.name IS NOT NULL)
            GROUP BY cls.class_id
        """, {
            "class_ids": class_ids,
            "date": date_obj
        }, as_dict=True)
        
        entered_map = {r['class_id']: r['entered_count'] for r in entered_counts}
        
        # Build kết quả
        classes_result = []
        total_all = 0
        entered_all = 0
        
        for cls in classes:
            total = scheduled_map.get(cls.name, 1)  # Ít nhất 1 (Homeroom)
            entered = entered_map.get(cls.name, 0)
            
            total_all += total
            entered_all += entered
            
            classes_result.append({
                "class_id": cls.name,
                "class_title": cls.title,
                "total": total,
                "entered": entered,
                "not_entered": total - entered,
                "rate": round(entered / total * 100, 1) if total > 0 else 0
            })
        
        # Sort theo tỷ lệ hoàn thành (thấp trước)
        classes_result.sort(key=lambda x: x['rate'])
        
        return success_response(
            data={
                "summary": {
                    "total_periods": total_all,
                    "entered": entered_all,
                    "not_entered": total_all - entered_all,
                    "rate": round(entered_all / total_all * 100, 1) if total_all > 0 else 0
                },
                "classes": classes_result
            },
            message="Lấy thống kê sổ đầu bài campus thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_campus_class_log_overview error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê campus: {str(e)}",
            code="GET_CAMPUS_LOG_OVERVIEW_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_class_log_dashboard(date=None, campus_id=None):
    """
    Lấy tổng hợp dashboard sổ đầu bài cho tất cả lớp Regular
    Bao gồm thông tin class log và contact log status
    
    Sử dụng helper functions để đảm bảo logic nhất quán với detail API
    
    Một lớp được coi là "hoàn thiện" khi:
    1. Tất cả các tiết Study đã được nhập sổ đầu bài
    2. GVCN đã gửi tin nhắn (Contact Log) đến 100% học sinh
    
    Args:
        date: Ngày cần xem (YYYY-MM-DD), mặc định là hôm nay
        campus_id: Campus ID (optional)
    
    Returns:
        {
            success: true,
            data: {
                summary: { total_regular, completed, incomplete },
                classes: [
                    {
                        class_id, class_title, homeroom_teacher_name,
                        total_study_periods, entered_periods,
                        total_students, students_with_contact_sent,
                        class_log_complete, contact_log_complete, is_completed
                    }
                ]
            }
        }
    """
    try:
        if not date:
            date = frappe.request.args.get('date')
        if not campus_id:
            campus_id = frappe.request.args.get('campus_id')
        
        if not date:
            date = frappe.utils.today()
        
        date_obj = frappe.utils.getdate(date)
        
        # Lấy campus từ context nếu không truyền
        if not campus_id:
            try:
                from erp.sis.utils.campus_permissions import get_current_user_campus
                campus_id = get_current_user_campus()
            except Exception:
                pass
        
        # Lấy active school year (is_enable = 1)
        school_year_filters = {"is_enable": 1}
        if campus_id:
            school_year_filters["campus_id"] = campus_id
        
        school_year = frappe.db.get_value("SIS School Year", school_year_filters, "name")
        
        # Lấy danh sách lớp Regular kèm education_stage_id qua education_grade
        classes = frappe.db.sql("""
            SELECT 
                c.name,
                c.title,
                c.homeroom_teacher,
                eg.education_stage_id
            FROM `tabSIS Class` c
            LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
            WHERE c.school_year_id = %(school_year)s
                AND c.class_type = 'Regular'
                {campus_filter}
        """.format(
            campus_filter="AND c.campus_id = %(campus_id)s" if campus_id else ""
        ), {
            "school_year": school_year,
            "campus_id": campus_id
        }, as_dict=True)
        
        if not classes:
            return success_response(
                data={
                    "summary": {
                        "total_regular": 0,
                        "completed": 0,
                        "incomplete": 0
                    },
                    "classes": []
                },
                message="Không có lớp Regular nào"
            )
        
        class_ids = [c.name for c in classes]
        
        # Lấy tên GVCN qua User.full_name - OPTIMIZED: 1 query thay vì N queries
        teacher_ids = [c.homeroom_teacher for c in classes if c.homeroom_teacher]
        teacher_names = {}
        if teacher_ids:
            teacher_data = frappe.db.sql("""
                SELECT t.name, u.full_name
                FROM `tabSIS Teacher` t
                INNER JOIN `tabUser` u ON t.user_id = u.name
                WHERE t.name IN %(teacher_ids)s
            """, {"teacher_ids": teacher_ids}, as_dict=True)
            teacher_names = {t['name']: t['full_name'] for t in teacher_data}
        
        # Lấy timetable instance cho tất cả lớp - BATCH QUERY để tối ưu
        timetable_instances = frappe.db.sql("""
            SELECT class_id, name 
            FROM `tabSIS Timetable Instance`
            WHERE class_id IN %(class_ids)s
                AND start_date <= %(date)s
                AND (end_date >= %(date)s OR end_date IS NULL)
        """, {
            "class_ids": class_ids,
            "date": date_obj
        }, as_dict=True)
        
        timetable_map = {ti['class_id']: ti['name'] for ti in timetable_instances}
        
        # Build kết quả - sử dụng helper functions để đảm bảo nhất quán với detail API
        classes_result = []
        completed_count = 0
        
        for cls in classes:
            class_id = cls.name
            timetable_instance = timetable_map.get(class_id)
            
            # Sử dụng helper để tính số liệu periods (đồng bộ với detail API)
            periods_stats = _calculate_class_periods_stats(
                class_id, 
                date_obj, 
                timetable_instance
            )
            
            # Sử dụng helper để tính số liệu contact log (đồng bộ với detail API)
            contact_stats = _calculate_contact_log_stats(class_id, date_obj, include_students_detail=False)
            
            total_study = periods_stats["total_periods"]
            entered_study = periods_stats["entered_periods"]
            total_students = contact_stats["total_students"]
            students_sent = contact_stats["sent_count"]
            
            # Class log hoàn thành khi tất cả tiết Study đã nhập
            class_log_complete = (total_study > 0 and entered_study >= total_study)
            
            # Contact log hoàn thành khi 100% học sinh đã được gửi tin nhắn
            contact_log_complete = (total_students > 0 and students_sent >= total_students)
            
            # Lớp hoàn thiện khi cả class log và contact log đều hoàn thành
            is_completed = class_log_complete and contact_log_complete
            
            if is_completed:
                completed_count += 1
            
            classes_result.append({
                "class_id": class_id,
                "class_title": cls.title,
                "homeroom_teacher_id": cls.homeroom_teacher,
                "homeroom_teacher_name": teacher_names.get(cls.homeroom_teacher),
                "education_stage_id": cls.get('education_stage_id'),
                "total_study_periods": total_study,
                "entered_periods": entered_study,
                "total_students": total_students,
                "students_with_contact_sent": students_sent,
                "class_log_complete": class_log_complete,
                "contact_log_complete": contact_log_complete,
                "is_completed": is_completed
            })
        
        # Sort: chưa hoàn thành trước, sau đó theo tên lớp
        classes_result.sort(key=lambda x: (x['is_completed'], x['class_title']))
        
        total_regular = len(classes)
        
        return success_response(
            data={
                "summary": {
                    "total_regular": total_regular,
                    "completed": completed_count,
                    "incomplete": total_regular - completed_count
                },
                "classes": classes_result
            },
            message="Lấy dashboard sổ đầu bài thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_class_log_dashboard error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy dashboard sổ đầu bài: {str(e)}",
            code="GET_CLASS_LOG_DASHBOARD_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_class_log_detail(class_id=None, date=None):
    """
    Lấy chi tiết sổ đầu bài của 1 lớp bao gồm:
    - Thông tin các tiết học
    - Trạng thái contact log của từng học sinh
    
    Sử dụng helper functions để đảm bảo logic nhất quán với dashboard
    
    Args:
        class_id: ID của lớp
        date: Ngày cần xem (YYYY-MM-DD)
    
    Returns:
        {
            success: true,
            data: {
                class_info: { ... },
                periods: [ ... ],
                contact_log: {
                    total_students, sent_count, not_sent_count,
                    students: [ { student_id, student_name, is_sent, viewed_count } ]
                }
            }
        }
    """
    try:
        if not class_id:
            class_id = frappe.request.args.get('class_id')
        if not date:
            date = frappe.request.args.get('date')
        
        if not class_id or not date:
            return error_response(
                message="Thiếu tham số: class_id và date là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        date_obj = frappe.utils.getdate(date)
        
        # Lấy thông tin lớp
        class_doc = frappe.get_doc("SIS Class", class_id)
        
        # Lấy tên giáo viên chủ nhiệm qua User.full_name
        homeroom_teacher_name = None
        if class_doc.homeroom_teacher:
            teacher_user_id = frappe.get_value("SIS Teacher", class_doc.homeroom_teacher, "user_id")
            if teacher_user_id:
                homeroom_teacher_name = frappe.get_value("User", teacher_user_id, "full_name")
        
        # Lấy timetable instance (xử lý cả trường hợp end_date là NULL)
        timetable_instance_result = frappe.db.sql("""
            SELECT name FROM `tabSIS Timetable Instance`
            WHERE class_id = %(class_id)s
                AND start_date <= %(date)s
                AND (end_date >= %(date)s OR end_date IS NULL)
            LIMIT 1
        """, {
            "class_id": class_id,
            "date": date_obj
        }, as_dict=True)
        timetable_instance = timetable_instance_result[0].name if timetable_instance_result else None
        
        # Sử dụng helper để tính số liệu periods (đồng bộ với dashboard)
        periods_stats = _calculate_class_periods_stats(
            class_id, 
            date_obj, 
            timetable_instance,
            homeroom_teacher=class_doc.homeroom_teacher,
            homeroom_teacher_name=homeroom_teacher_name
        )
        
        # Build periods result - thêm Homeroom ở đầu
        periods_result = []
        
        if timetable_instance:
            # FIX BUG: Chỉ đếm records với status KHÁC excused
            # Vì excused có thể được tạo tự động từ đơn nghỉ phép (leave request)
            homeroom_attendance_count = frappe.db.sql("""
                SELECT COUNT(DISTINCT student_id) as count
                FROM `tabSIS Class Attendance`
                WHERE class_id = %(class_id)s
                    AND date = %(date)s
                    AND period = 'Homeroom'
                    AND status IN ('present', 'absent', 'late')
            """, {
                "class_id": class_id,
                "date": date_obj
            }, as_dict=True)
            
            homeroom_has_attendance = (homeroom_attendance_count[0]['count'] if homeroom_attendance_count else 0) > 0
            
            # Thêm tiết Homeroom ở đầu
            periods_result.append({
                "period": "Homeroom",
                "subject_id": None,
                "subject_name": "Sinh hoạt lớp",
                "teacher_id": class_doc.homeroom_teacher,
                "teacher_name": homeroom_teacher_name,
                "status": "entered" if homeroom_has_attendance else "not_entered",
                "has_general_comment": False,
                "student_count_with_log": 0,
                "last_modified": None,
                "is_homeroom": True
            })
        
        # Thêm các tiết Study từ helper
        periods_result.extend(periods_stats["periods_detail"])
        
        # Sử dụng helper để tính số liệu contact log (đồng bộ với dashboard)
        contact_stats = _calculate_contact_log_stats(class_id, date_obj, include_students_detail=True)
        
        return success_response(
            data={
                "class_info": {
                    "name": class_doc.name,
                    "title": class_doc.title,
                    "homeroom_teacher": class_doc.homeroom_teacher,
                    "homeroom_teacher_name": homeroom_teacher_name
                },
                "periods": periods_result,
                "summary": {
                    "total_periods": periods_stats["total_periods"],
                    "entered": periods_stats["entered_periods"],
                    "rate": round(periods_stats["entered_periods"] / periods_stats["total_periods"] * 100, 1) if periods_stats["total_periods"] > 0 else 0
                },
                "contact_log": contact_stats
            },
            message="Lấy chi tiết sổ đầu bài thành công"
        )
        
    except frappe.DoesNotExistError:
        return error_response(
            message=f"Không tìm thấy lớp: {class_id}",
            code="CLASS_NOT_FOUND"
        )
    except Exception as e:
        frappe.log_error(f"get_class_log_detail error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy chi tiết sổ đầu bài: {str(e)}",
            code="GET_CLASS_LOG_DETAIL_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_subject_teachers_dashboard(date=None, campus_id=None):
    """
    Lấy dashboard sổ đầu bài theo giáo viên bộ môn
    Trả về danh sách tất cả GV có tiết dạy trong ngày cùng tiến độ nhập sổ
    
    Args:
        date: Ngày cần xem (YYYY-MM-DD), mặc định là hôm nay
        campus_id: Campus ID (optional)
    
    Returns:
        {
            success: true,
            data: {
                summary: { total_teachers, completed_teachers, incomplete_teachers },
                teachers: [
                    {
                        teacher_id, teacher_name, total_periods, entered_periods, rate,
                        education_stage_ids: [str],
                        classes: [
                            { class_id, class_title, education_stage_id, period, subject_name, status }
                        ]
                    }
                ]
            }
        }
    """
    try:
        if not date:
            date = frappe.request.args.get('date')
        if not campus_id:
            campus_id = frappe.request.args.get('campus_id')
        
        if not date:
            date = frappe.utils.today()
        
        date_obj = frappe.utils.getdate(date)
        
        # Lấy campus từ context nếu không truyền
        if not campus_id:
            try:
                from erp.sis.utils.campus_permissions import get_current_user_campus
                campus_id = get_current_user_campus()
            except Exception:
                pass
        
        # Lấy active school year
        school_year_filters = {"is_enable": 1}
        if campus_id:
            school_year_filters["campus_id"] = campus_id
        
        school_year = frappe.db.get_value("SIS School Year", school_year_filters, "name")
        
        # day_of_week format: mon, tue, wed, thu, fri, sat, sun
        day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        day_of_week_short = day_map.get(date_obj.weekday(), 'mon')
        
        # Lấy tất cả tiết dạy của GV bộ môn trong ngày (chỉ lớp Regular, bỏ tiểu học)
        # Bỏ tiểu học: education_stage_id != 'EDU-STAGE-00001' VÀ tên lớp không phải lớp 1-5
        # Sử dụng GROUP BY để loại bỏ duplicate (do JOIN với nhiều bảng)
        scheduled_periods = frappe.db.sql("""
            SELECT 
                COALESCE(trt.teacher_id, tr.teacher_1_id) as teacher_id,
                ti.class_id,
                c.title as class_title,
                eg.education_stage_id,
                tc.period_name,
                MAX(COALESCE(ts.title_vn, sub.title)) as subject_name,
                tr.subject_id
            FROM `tabSIS Timetable Instance Row` tr
            INNER JOIN `tabSIS Timetable Instance` ti ON tr.parent = ti.name
            INNER JOIN `tabSIS Timetable Column` tc ON tr.timetable_column_id = tc.name
            INNER JOIN `tabSIS Class` c ON ti.class_id = c.name
            LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
            LEFT JOIN `tabSIS Subject` sub ON tr.subject_id = sub.name
            LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
            LEFT JOIN `tabSIS Timetable Instance Row Teacher` trt ON trt.parent = tr.name 
                AND trt.idx = (SELECT MIN(idx) FROM `tabSIS Timetable Instance Row Teacher` WHERE parent = tr.name)
            WHERE ti.start_date <= %(date)s
                AND (ti.end_date >= %(date)s OR ti.end_date IS NULL)
                AND tr.day_of_week = %(day)s
                AND LOWER(tc.period_name) LIKE '%%tiết%%'
                AND (tr.valid_from IS NULL OR tr.valid_from <= %(date)s)
                AND (tr.valid_to IS NULL OR tr.valid_to >= %(date)s)
                AND c.class_type = 'Regular'
                AND c.school_year_id = %(school_year)s
                AND (eg.education_stage_id IS NULL OR eg.education_stage_id != 'EDU-STAGE-00001')
                AND NOT (c.title REGEXP '^Lớp [1-5][^0-9]' OR c.title REGEXP '^Lớp [1-5]$')
                {campus_filter}
            GROUP BY COALESCE(trt.teacher_id, tr.teacher_1_id), ti.class_id, tc.period_name, tr.subject_id, c.title, eg.education_stage_id
        """.format(
            campus_filter="AND c.campus_id = %(campus_id)s" if campus_id else ""
        ), {
            "date": date_obj,
            "day": day_of_week_short,
            "school_year": school_year,
            "campus_id": campus_id
        }, as_dict=True)
        
        if not scheduled_periods:
            return success_response(
                data={
                    "summary": {
                        "total_teachers": 0,
                        "completed_teachers": 0,
                        "incomplete_teachers": 0
                    },
                    "teachers": []
                },
                message="Không có tiết dạy nào trong ngày này"
            )
        
        # Lấy tên giáo viên
        teacher_ids = list(set(p['teacher_id'] for p in scheduled_periods if p.get('teacher_id')))
        teacher_names = {}
        if teacher_ids:
            teacher_data = frappe.db.sql("""
                SELECT t.name, u.full_name
                FROM `tabSIS Teacher` t
                INNER JOIN `tabUser` u ON t.user_id = u.name
                WHERE t.name IN %(teacher_ids)s
            """, {"teacher_ids": teacher_ids}, as_dict=True)
            teacher_names = {t['name']: t['full_name'] for t in teacher_data}
        
        # Lấy tất cả class logs trong ngày cho các lớp liên quan
        class_ids = list(set(p['class_id'] for p in scheduled_periods))
        
        entered_logs = {}
        if class_ids:
            logs_data = frappe.db.sql("""
                SELECT 
                    cls.class_id,
                    cls.period,
                    cls.recorded_by,
                    cls.general_comment,
                    cls.modified,
                    cls.creation,
                    COUNT(clst.name) as student_log_count
                FROM `tabSIS Class Log Subject` cls
                LEFT JOIN `tabSIS Class Log Student` clst ON clst.subject_id = cls.name
                WHERE cls.class_id IN %(class_ids)s
                    AND cls.log_date = %(date)s
                    AND LOWER(cls.period) LIKE '%%tiết%%'
                GROUP BY cls.name, cls.class_id, cls.period
            """, {
                "class_ids": class_ids,
                "date": date_obj
            }, as_dict=True)
            
            for log in logs_data:
                period_num = _extract_period_number(log['period'])
                key = (log['class_id'], period_num)
                has_content = log.get('general_comment') or log.get('student_log_count', 0) > 0
                if has_content:
                    entered_logs[key] = log
        
        # Group theo teacher
        teacher_data_map = {}
        for p in scheduled_periods:
            teacher_id = p.get('teacher_id')
            if not teacher_id:
                continue
            
            if teacher_id not in teacher_data_map:
                teacher_data_map[teacher_id] = {
                    "teacher_id": teacher_id,
                    "teacher_name": teacher_names.get(teacher_id, "Không xác định"),
                    "total_periods": 0,
                    "entered_periods": 0,
                    "education_stage_ids": set(),
                    "classes": []
                }
            
            period_num = _extract_period_number(p['period_name'])
            key = (p['class_id'], period_num)
            log = entered_logs.get(key)
            
            if log:
                has_content = log.get('general_comment') or log.get('student_log_count', 0) > 0
                if has_content:
                    status = "updated" if log.get('modified') != log.get('creation') else "entered"
                else:
                    status = "not_entered"
            else:
                status = "not_entered"
            
            teacher_data_map[teacher_id]["total_periods"] += 1
            if status in ("entered", "updated"):
                teacher_data_map[teacher_id]["entered_periods"] += 1
            
            if p.get('education_stage_id'):
                teacher_data_map[teacher_id]["education_stage_ids"].add(p['education_stage_id'])
            
            teacher_data_map[teacher_id]["classes"].append({
                "class_id": p['class_id'],
                "class_title": p['class_title'],
                "education_stage_id": p.get('education_stage_id'),
                "period": p['period_name'],
                "subject_name": p.get('subject_name') or "Không xác định",
                "status": status
            })
        
        # Build result
        teachers_result = []
        completed_count = 0
        
        for teacher_id, data in teacher_data_map.items():
            total = data["total_periods"]
            entered = data["entered_periods"]
            rate = round(entered / total * 100, 1) if total > 0 else 0
            is_completed = (total > 0 and entered >= total)
            
            if is_completed:
                completed_count += 1
            
            teachers_result.append({
                "teacher_id": teacher_id,
                "teacher_name": data["teacher_name"],
                "total_periods": total,
                "entered_periods": entered,
                "rate": rate,
                "is_completed": is_completed,
                "education_stage_ids": list(data["education_stage_ids"]),
                "classes": sorted(data["classes"], key=lambda x: _extract_period_number(x['period']))
            })
        
        # Sort: chưa hoàn thành trước, sau đó theo tên
        teachers_result.sort(key=lambda x: (x['is_completed'], x['teacher_name']))
        
        total_teachers = len(teachers_result)
        
        return success_response(
            data={
                "summary": {
                    "total_teachers": total_teachers,
                    "completed_teachers": completed_count,
                    "incomplete_teachers": total_teachers - completed_count
                },
                "teachers": teachers_result
            },
            message="Lấy dashboard GV bộ môn thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_subject_teachers_dashboard error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy dashboard GV bộ môn: {str(e)}",
            code="GET_SUBJECT_TEACHERS_DASHBOARD_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_my_today_tasks(date=None):
    """
    Lấy danh sách công việc hôm nay của giáo viên hiện tại cho trang Home
    Bao gồm: tiết dạy, điểm danh homeroom, sổ liên lạc, đơn nghỉ phép, check-in/out
    
    Args:
        date: Ngày cần xem (YYYY-MM-DD), mặc định là hôm nay
    
    Returns:
        {
            success: true,
            data: {
                teacher_id: str,
                teacher_name: str,
                today_periods: [{period_name, class_id, class_title, subject_name, class_log_status}],
                homeroom_tasks: [{class_id, class_title, task_type, status, detail, sent_count, total_count}],
                leave_summary: [{class_id, class_title, leave_count, reasons: [{reason, count}]}],
                checkin_info: {check_in_time, check_out_time, total_check_ins}
            }
        }
    """
    try:
        if not date:
            date = frappe.request.args.get('date') if hasattr(frappe, 'request') and frappe.request else None
        if not date:
            date = frappe.utils.today()
        
        date_obj = frappe.utils.getdate(date)
        
        # 1. Resolve current user -> SIS Teacher
        current_user = frappe.session.user
        teacher = frappe.db.get_value(
            "SIS Teacher", 
            {"user_id": current_user}, 
            ["name", "user_id", "employee_code"],
            as_dict=True
        )
        
        if not teacher:
            return success_response(
                data={
                    "teacher_id": None,
                    "teacher_name": None,
                    "today_periods": [],
                    "homeroom_tasks": [],
                    "leave_summary": [],
                    "checkin_info": None
                },
                message="User không phải là giáo viên trong hệ thống"
            )
        
        teacher_id = teacher.name
        
        # Lấy tên giáo viên từ User
        teacher_name = frappe.get_value("User", current_user, "full_name") or current_user
        
        # 2. Lấy active school year
        school_year = frappe.db.get_value("SIS School Year", {"is_enable": 1}, "name")
        
        # 3. Lấy các tiết dạy hôm nay của giáo viên từ timetable
        # day_of_week format: mon, tue, wed, thu, fri, sat, sun
        day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        day_of_week_short = day_map.get(date_obj.weekday(), 'mon')
        
        today_periods = []
        
        if school_year:
            # Query các tiết dạy của giáo viên hôm nay
            # Dựa vào SIS Timetable Instance Row và kiểm tra teacher_id
            periods_data = frappe.db.sql("""
                SELECT DISTINCT
                    tc.period_name,
                    ti.class_id,
                    c.title as class_title,
                    tr.subject_id,
                    COALESCE(ts.title_vn, sub.title) as subject_name
                FROM `tabSIS Timetable Instance Row` tr
                INNER JOIN `tabSIS Timetable Instance` ti ON tr.parent = ti.name
                INNER JOIN `tabSIS Timetable Column` tc ON tr.timetable_column_id = tc.name
                INNER JOIN `tabSIS Class` c ON ti.class_id = c.name
                LEFT JOIN `tabSIS Subject` sub ON tr.subject_id = sub.name
                LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
                LEFT JOIN `tabSIS Timetable Instance Row Teacher` trt ON trt.parent = tr.name
                WHERE c.school_year_id = %(school_year)s
                    AND c.class_type = 'Regular'
                    AND tr.day_of_week = %(day)s
                    AND LOWER(tc.period_name) LIKE '%%tiết%%'
                    AND (tr.valid_from IS NULL OR tr.valid_from <= %(date)s)
                    AND (tr.valid_to IS NULL OR tr.valid_to >= %(date)s)
                    AND (ti.end_date IS NULL OR ti.end_date >= %(date)s)
                    AND ti.start_date <= %(date)s
                    AND (
                        trt.teacher_id = %(teacher_id)s
                        OR (trt.teacher_id IS NULL AND tr.teacher_1_id = %(teacher_id)s)
                    )
                ORDER BY tc.period_priority, c.title
            """, {
                "school_year": school_year,
                "day": day_of_week_short,
                "date": date_obj,
                "teacher_id": teacher_id
            }, as_dict=True)
            
            # Lấy tất cả class_ids để query class log status một lần
            class_ids = list(set([p['class_id'] for p in periods_data]))
            
            # Query class log status cho tất cả class + period + subject hôm nay
            class_log_map = {}
            if class_ids:
                logs = frappe.db.sql("""
                    SELECT 
                        cls.class_id,
                        cls.period_name,
                        cls.subject_id,
                        CASE 
                            WHEN cls.modified > cls.creation THEN 'updated'
                            WHEN cls.name IS NOT NULL THEN 'entered'
                            ELSE 'not_entered'
                        END as status
                    FROM `tabSIS Class Log Subject` cls
                    WHERE cls.class_id IN %(class_ids)s
                        AND cls.log_date = %(date)s
                """, {
                    "class_ids": class_ids,
                    "date": date_obj
                }, as_dict=True)
                
                for log in logs:
                    key = f"{log['class_id']}|{log['period_name']}|{log['subject_id']}"
                    class_log_map[key] = log['status']
            
            # Build today_periods result
            for p in periods_data:
                key = f"{p['class_id']}|{p['period_name']}|{p['subject_id']}"
                status = class_log_map.get(key, 'not_entered')
                
                today_periods.append({
                    "period_name": p['period_name'],
                    "class_id": p['class_id'],
                    "class_title": p['class_title'],
                    "subject_name": p['subject_name'] or "Không xác định",
                    "class_log_status": status
                })
        
        # 4. Lấy các lớp chủ nhiệm của giáo viên
        homeroom_tasks = []
        homeroom_class_ids = []
        
        if school_year:
            homeroom_classes = frappe.db.sql("""
                SELECT name as class_id, title as class_title
                FROM `tabSIS Class`
                WHERE school_year_id = %(school_year)s
                    AND class_type = 'Regular'
                    AND (homeroom_teacher = %(teacher_id)s OR vice_homeroom_teacher = %(teacher_id)s)
                ORDER BY title
            """, {
                "school_year": school_year,
                "teacher_id": teacher_id
            }, as_dict=True)
            
            homeroom_class_ids = [c['class_id'] for c in homeroom_classes]
            
            for cls in homeroom_classes:
                class_id = cls['class_id']
                class_title = cls['class_title']
                
                # Task 1: Điểm danh Homeroom
                # Kiểm tra xem đã có Class Log Subject cho period Homeroom chưa
                homeroom_log = frappe.db.get_value(
                    "SIS Class Log Subject",
                    {
                        "class_id": class_id,
                        "log_date": date_obj,
                        "period_name": "Homeroom"
                    },
                    "name"
                )
                
                homeroom_tasks.append({
                    "class_id": class_id,
                    "class_title": class_title,
                    "task_type": "homeroom_attendance",
                    "status": "completed" if homeroom_log else "pending",
                    "detail": "Đã điểm danh" if homeroom_log else "Chưa điểm danh",
                    "sent_count": None,
                    "total_count": None
                })
                
                # Task 2: Sổ liên lạc
                contact_stats = _calculate_contact_log_stats(class_id, date_obj, include_students_detail=False)
                sent_count = contact_stats.get("sent_count", 0)
                total_count = contact_stats.get("total_students", 0)
                is_complete = total_count > 0 and sent_count >= total_count
                
                homeroom_tasks.append({
                    "class_id": class_id,
                    "class_title": class_title,
                    "task_type": "contact_log",
                    "status": "completed" if is_complete else "pending",
                    "detail": f"{sent_count}/{total_count} HS" if total_count > 0 else "Không có HS",
                    "sent_count": sent_count,
                    "total_count": total_count
                })
        
        # 5. Lấy đơn nghỉ phép của các lớp chủ nhiệm hôm nay
        leave_summary = []
        
        if homeroom_class_ids:
            # Lấy các học sinh trong các lớp chủ nhiệm
            class_students = frappe.db.sql("""
                SELECT cs.class_id, cs.student_id
                FROM `tabSIS Class Student` cs
                WHERE cs.class_id IN %(class_ids)s
            """, {"class_ids": homeroom_class_ids}, as_dict=True)
            
            # Map student -> class
            student_class_map = {}
            for row in class_students:
                student_class_map[row['student_id']] = row['class_id']
            
            student_ids = list(student_class_map.keys())
            
            if student_ids:
                # Lấy đơn nghỉ phép active hôm nay
                leave_requests = frappe.db.sql("""
                    SELECT student_id, reason, other_reason
                    FROM `tabSIS Student Leave Request`
                    WHERE student_id IN %(student_ids)s
                        AND start_date <= %(date)s
                        AND end_date >= %(date)s
                """, {
                    "student_ids": student_ids,
                    "date": date_obj
                }, as_dict=True)
                
                # Group theo class
                class_leave_map = {}  # class_id -> {count, reasons: {reason: count}}
                for lr in leave_requests:
                    class_id = student_class_map.get(lr['student_id'])
                    if not class_id:
                        continue
                    
                    if class_id not in class_leave_map:
                        class_leave_map[class_id] = {"count": 0, "reasons": {}}
                    
                    class_leave_map[class_id]["count"] += 1
                    
                    # Lấy reason hiển thị
                    reason_text = lr['reason'] or lr.get('other_reason') or "Khác"
                    if reason_text not in class_leave_map[class_id]["reasons"]:
                        class_leave_map[class_id]["reasons"][reason_text] = 0
                    class_leave_map[class_id]["reasons"][reason_text] += 1
                
                # Build leave_summary
                # Lấy class_title từ homeroom_classes
                class_title_map = {c['class_id']: c['class_title'] for c in homeroom_classes}
                
                for class_id in homeroom_class_ids:
                    leave_data = class_leave_map.get(class_id, {"count": 0, "reasons": {}})
                    reasons_list = [
                        {"reason": r, "count": c} 
                        for r, c in leave_data["reasons"].items()
                    ]
                    
                    leave_summary.append({
                        "class_id": class_id,
                        "class_title": class_title_map.get(class_id, ""),
                        "leave_count": leave_data["count"],
                        "reasons": reasons_list
                    })
        
        # 6. Lấy thông tin check-in/check-out từ ERP Time Attendance
        checkin_info = None
        
        # Thử lấy employee_code từ teacher hoặc user
        employee_code = teacher.get('employee_code')
        
        # Nếu không có employee_code trong teacher, thử lấy từ User.username hoặc email prefix
        if not employee_code:
            user_doc = frappe.get_doc("User", current_user)
            # Ưu tiên username, sau đó email prefix
            employee_code = user_doc.username or current_user.split('@')[0]
        
        if employee_code:
            # Query ERP Time Attendance
            attendance = frappe.db.get_value(
                "ERP Time Attendance",
                {
                    "employee_code": employee_code,
                    "date": date_obj
                },
                ["check_in_time", "check_out_time", "total_check_ins", "raw_data"],
                as_dict=True
            )
            
            if attendance:
                check_in_time = attendance.get('check_in_time')
                check_out_time = attendance.get('check_out_time')
                total_check_ins = attendance.get('total_check_ins') or 0
                
                # Recalculate từ raw_data nếu có (giống logic trong query.py)
                if attendance.get('raw_data'):
                    try:
                        import json
                        raw_data = json.loads(attendance['raw_data']) if isinstance(attendance['raw_data'], str) else attendance['raw_data']
                        if raw_data and len(raw_data) > 0:
                            all_times = []
                            for item in raw_data:
                                ts_str = item.get('timestamp', '')
                                if ts_str:
                                    parsed_ts = frappe.utils.get_datetime(ts_str)
                                    if parsed_ts.tzinfo is not None:
                                        parsed_ts = parsed_ts.replace(tzinfo=None)
                                    all_times.append(parsed_ts)
                            
                            if all_times:
                                all_times.sort()
                                check_in_time = all_times[0]
                                check_out_time = all_times[-1] if len(all_times) > 1 else None
                                total_check_ins = len(all_times)
                    except Exception as e:
                        frappe.log_error(f"Error parsing raw_data: {str(e)}")
                
                # Format time string
                def format_time_str(dt):
                    if not dt:
                        return None
                    if hasattr(dt, 'strftime'):
                        return dt.strftime('%H:%M')
                    return str(dt)[:5] if dt else None
                
                checkin_info = {
                    "check_in_time": format_time_str(check_in_time),
                    "check_out_time": format_time_str(check_out_time),
                    "total_check_ins": total_check_ins
                }
        
        return success_response(
            data={
                "teacher_id": teacher_id,
                "teacher_name": teacher_name,
                "today_periods": today_periods,
                "homeroom_tasks": homeroom_tasks,
                "leave_summary": leave_summary,
                "checkin_info": checkin_info
            },
            message="Lấy công việc hôm nay thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_my_today_tasks error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy công việc hôm nay: {str(e)}",
            code="GET_MY_TODAY_TASKS_ERROR"
        )
