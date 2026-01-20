"""
Class Log Report API
Cung cấp các endpoint báo cáo sổ đầu bài
"""

import frappe
from frappe import _
import json
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
        day_name = date_obj.strftime("%A")
        
        # Lấy tên GVCN qua User.full_name
        teacher_ids = [c.homeroom_teacher for c in classes if c.homeroom_teacher]
        teacher_names = {}
        if teacher_ids:
            # Lấy user_id từ SIS Teacher
            teachers = frappe.get_all(
                "SIS Teacher",
                filters={"name": ["in", teacher_ids]},
                fields=["name", "user_id"]
            )
            # Lấy full_name từ User
            for t in teachers:
                if t.user_id:
                    full_name = frappe.db.get_value("User", t.user_id, "full_name")
                    teacher_names[t.name] = full_name
        
        # Đếm số tiết Study theo lịch cho mỗi lớp (chỉ tiết có tên chứa "Tiết")
        # day_of_week trong database là format viết tắt: mon, tue, wed, thu, fri, sat, sun
        day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        day_of_week_short = day_map.get(date_obj.weekday(), 'mon')
        
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
                AND LOWER(tc.period_name) LIKE '%%tiết%%'
                AND (tr.valid_from IS NULL OR tr.valid_from <= %(date)s)
                AND (tr.valid_to IS NULL OR tr.valid_to >= %(date)s)
            GROUP BY ti.class_id
        """, {
            "class_ids": class_ids,
            "date": date_obj,
            "day": day_of_week_short
        }, as_dict=True)
        
        scheduled_map = {r['class_id']: r['period_count'] for r in scheduled_counts}
        
        # Đếm số tiết Study đã nhập log
        entered_counts = frappe.db.sql("""
            SELECT 
                cls.class_id,
                COUNT(DISTINCT cls.period) as entered_count
            FROM `tabSIS Class Log Subject` cls
            LEFT JOIN `tabSIS Class Log Student` clst ON clst.subject_id = cls.name
            WHERE cls.class_id IN %(class_ids)s
                AND cls.log_date = %(date)s
                AND LOWER(cls.period) LIKE '%%tiết%%'
                AND (cls.general_comment IS NOT NULL AND cls.general_comment != '' 
                     OR clst.name IS NOT NULL)
            GROUP BY cls.class_id
        """, {
            "class_ids": class_ids,
            "date": date_obj
        }, as_dict=True)
        
        entered_map = {r['class_id']: r['entered_count'] for r in entered_counts}
        
        # Đếm số học sinh trong mỗi lớp
        student_counts = frappe.db.sql("""
            SELECT 
                class_id,
                COUNT(*) as student_count
            FROM `tabSIS Class Student`
            WHERE class_id IN %(class_ids)s
            GROUP BY class_id
        """, {"class_ids": class_ids}, as_dict=True)
        
        student_count_map = {r['class_id']: r['student_count'] for r in student_counts}
        
        # Đếm số học sinh đã được gửi contact log (status = 'Sent')
        # Cần join qua timetable instance và class log subject
        contact_sent_counts = frappe.db.sql("""
            SELECT 
                cls.class_id,
                COUNT(DISTINCT clst.student_id) as sent_count
            FROM `tabSIS Class Log Subject` cls
            INNER JOIN `tabSIS Class Log Student` clst ON clst.subject_id = cls.name
            WHERE cls.class_id IN %(class_ids)s
                AND cls.log_date = %(date)s
                AND clst.contact_log_status = 'Sent'
            GROUP BY cls.class_id
        """, {
            "class_ids": class_ids,
            "date": date_obj
        }, as_dict=True)
        
        contact_sent_map = {r['class_id']: r['sent_count'] for r in contact_sent_counts}
        
        # Build kết quả
        classes_result = []
        completed_count = 0
        
        for cls in classes:
            total_study = scheduled_map.get(cls.name, 0)
            entered_study = entered_map.get(cls.name, 0)
            total_students = student_count_map.get(cls.name, 0)
            students_sent = contact_sent_map.get(cls.name, 0)
            
            # Class log hoàn thành khi tất cả tiết Study đã nhập
            class_log_complete = (total_study > 0 and entered_study >= total_study)
            
            # Contact log hoàn thành khi 100% học sinh đã được gửi tin nhắn
            contact_log_complete = (total_students > 0 and students_sent >= total_students)
            
            # Lớp hoàn thiện khi cả class log và contact log đều hoàn thành
            is_completed = class_log_complete and contact_log_complete
            
            if is_completed:
                completed_count += 1
            
            classes_result.append({
                "class_id": cls.name,
                "class_title": cls.title,
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
        
        periods_result = []
        
        if timetable_instance:
            # Lấy các tiết học trong ngày (chỉ tiết Study)
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
                    AND LOWER(tc.period_name) LIKE '%%tiết%%'
                    AND (tr.valid_from IS NULL OR tr.valid_from <= %(date)s)
                    AND (tr.valid_to IS NULL OR tr.valid_to >= %(date)s)
                ORDER BY tc.period_name
            """, {
                "instance": timetable_instance,
                "day": day_of_week_short,
                "date": date_obj
            }, as_dict=True)
            
            # Lấy class log subjects đã tạo
            period_names = [p['period_name'] for p in periods_data]
            
            log_map = {}
            if period_names:
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
                
                for log in class_log_subjects:
                    log_map[log['period']] = log
            
            # Build periods result
            for p in periods_data:
                period_name = p['period_name']
                log = log_map.get(period_name)
                
                if log:
                    has_content = log.get('general_comment') or log.get('student_log_count', 0) > 0
                    if has_content:
                        status = "updated" if log.get('modified') != log.get('creation') else "entered"
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
        
        # Lấy danh sách học sinh và trạng thái contact log
        students = frappe.db.sql("""
            SELECT 
                cs.student_id,
                s.student_name
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
            WHERE cs.class_id = %(class_id)s
            ORDER BY s.student_name
        """, {"class_id": class_id}, as_dict=True)
        
        # Lấy contact log status cho ngày này
        contact_log_map = {}
        if timetable_instance:
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
            
            for log in contact_logs:
                contact_log_map[log['student_id']] = {
                    "status": log.get('contact_log_status'),
                    "viewed_count": log.get('contact_log_viewed_count') or 0
                }
        
        # Build contact log result
        students_result = []
        sent_count = 0
        
        for student in students:
            contact_info = contact_log_map.get(student['student_id'], {})
            is_sent = contact_info.get('status') == 'Sent'
            
            if is_sent:
                sent_count += 1
            
            students_result.append({
                "student_id": student['student_id'],
                "student_name": student['student_name'],
                "is_sent": is_sent,
                "viewed_count": contact_info.get('viewed_count', 0)
            })
        
        total_students = len(students)
        total_periods = len(periods_result)
        entered_periods = len([p for p in periods_result if p['status'] != 'not_entered'])
        
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
                    "entered": entered_periods,
                    "rate": round(entered_periods / total_periods * 100, 1) if total_periods > 0 else 0
                },
                "contact_log": {
                    "total_students": total_students,
                    "sent_count": sent_count,
                    "not_sent_count": total_students - sent_count,
                    "rate": round(sent_count / total_students * 100, 1) if total_students > 0 else 0,
                    "students": students_result
                }
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
