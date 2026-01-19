"""
Attendance Report API
Cung cấp các endpoint báo cáo điểm danh theo tiết cho tất cả lớp
"""

import frappe
from frappe import _
import json
from datetime import datetime
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
def get_period_attendance_overview(date=None, period=None, campus_id=None):
    """
    Thống kê điểm danh 1 tiết cho tất cả các lớp
    
    Args:
        date: Ngày cần xem (YYYY-MM-DD)
        period: Tên tiết (e.g. "Tiết 1", "Homeroom")
        campus_id: Campus ID (optional)
    
    Returns:
        {
            success: true,
            data: {
                period: "Tiết 1",
                date: "2025-01-19",
                summary: { total_classes, total_students, present, absent, late },
                classes: [
                    {
                        class_id, class_title, 
                        total, present, absent, late, excused,
                        teacher_id, teacher_name,
                        rate
                    }
                ]
            }
        }
    """
    try:
        # Lấy params
        if not date:
            date = frappe.request.args.get('date')
        if not period:
            period = frappe.request.args.get('period')
        if not campus_id:
            campus_id = frappe.request.args.get('campus_id')
        
        if not date or not period:
            return error_response(
                message="Thiếu tham số: date và period là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        # Parse date
        date_obj = frappe.utils.getdate(date)
        
        # Lấy campus từ context nếu không truyền
        if not campus_id:
            try:
                from erp.sis.utils.campus_permissions import get_current_user_campus
                campus_id = get_current_user_campus()
            except Exception:
                pass
        
        # Lấy active school year
        school_year_filters = {"is_active": 1}
        if campus_id:
            school_year_filters["campus_id"] = campus_id
        
        school_year = frappe.db.get_value("SIS School Year", school_year_filters, "name")
        
        # Lấy danh sách lớp (chỉ lớp regular cho homeroom, tất cả cho các tiết khác)
        class_filters = {
            "school_year_id": school_year,
            "class_type": "regular"
        }
        if campus_id:
            class_filters["campus_id"] = campus_id
        
        classes = frappe.get_all(
            "SIS Class",
            filters=class_filters,
            fields=["name", "title", "homeroom_teacher"]
        )
        
        if not classes:
            return success_response(
                data={
                    "period": period,
                    "date": str(date_obj),
                    "summary": {
                        "total_classes": 0,
                        "total_students": 0,
                        "present": 0,
                        "absent": 0,
                        "late": 0
                    },
                    "classes": []
                },
                message="Không có lớp nào"
            )
        
        class_ids = [c.name for c in classes]
        
        # Batch query: Đếm học sinh trong mỗi lớp
        student_counts = frappe.db.sql("""
            SELECT class_id, COUNT(*) as count
            FROM `tabSIS Class Student`
            WHERE class_id IN %(class_ids)s
            GROUP BY class_id
        """, {"class_ids": class_ids}, as_dict=True)
        
        student_count_map = {r['class_id']: r['count'] for r in student_counts}
        
        # Batch query: Lấy attendance cho tiết này
        attendance_data = frappe.db.sql("""
            SELECT 
                class_id,
                status,
                COUNT(*) as count
            FROM `tabSIS Class Attendance`
            WHERE class_id IN %(class_ids)s
                AND date = %(date)s
                AND period = %(period)s
            GROUP BY class_id, status
        """, {
            "class_ids": class_ids,
            "date": date_obj,
            "period": period
        }, as_dict=True)
        
        # Build attendance map: class_id -> {status -> count}
        attendance_map = {}
        for row in attendance_data:
            if row['class_id'] not in attendance_map:
                attendance_map[row['class_id']] = {}
            attendance_map[row['class_id']][row['status']] = row['count']
        
        # Lấy giáo viên dạy tiết này (từ timetable)
        teacher_map = {}
        if period.lower() != 'homeroom':
            # Query timetable để lấy giáo viên bộ môn
            timetable_data = frappe.db.sql("""
                SELECT 
                    ti.class_id,
                    tc.teacher_id,
                    t.teacher_name
                FROM `tabSIS Timetable Instance` ti
                INNER JOIN `tabSIS Timetable Column` tc ON tc.timetable_instance_id = ti.name
                INNER JOIN `tabSIS Teacher` t ON tc.teacher_id = t.name
                WHERE ti.class_id IN %(class_ids)s
                    AND ti.start_date <= %(date)s
                    AND ti.end_date >= %(date)s
                    AND tc.period_name = %(period)s
                    AND tc.day_of_week = DAYNAME(%(date)s)
            """, {
                "class_ids": class_ids,
                "date": date_obj,
                "period": period
            }, as_dict=True)
            
            for row in timetable_data:
                teacher_map[row['class_id']] = {
                    "teacher_id": row['teacher_id'],
                    "teacher_name": row['teacher_name']
                }
        
        # Build kết quả cho từng lớp
        classes_result = []
        total_students_all = 0
        present_all = 0
        absent_all = 0
        late_all = 0
        
        for cls in classes:
            total = student_count_map.get(cls.name, 0)
            att = attendance_map.get(cls.name, {})
            
            present = att.get('present', 0)
            absent = att.get('absent', 0)
            late = att.get('late', 0)
            excused = att.get('excused', 0)
            left_early = att.get('left_early', 0)
            
            total_students_all += total
            present_all += present
            absent_all += absent
            late_all += late
            
            # Lấy teacher info
            teacher_info = teacher_map.get(cls.name)
            if not teacher_info and cls.homeroom_teacher:
                # Fallback về homeroom teacher
                teacher_name = frappe.get_value("SIS Teacher", cls.homeroom_teacher, "teacher_name")
                teacher_info = {
                    "teacher_id": cls.homeroom_teacher,
                    "teacher_name": teacher_name
                }
            
            classes_result.append({
                "class_id": cls.name,
                "class_title": cls.title,
                "total": total,
                "present": present,
                "absent": absent,
                "late": late,
                "excused": excused,
                "left_early": left_early,
                "teacher_id": teacher_info.get('teacher_id') if teacher_info else None,
                "teacher_name": teacher_info.get('teacher_name') if teacher_info else None,
                "has_attendance": sum([present, absent, late, excused, left_early]) > 0,
                "rate": round(present / total * 100, 1) if total > 0 else 0
            })
        
        # Sort theo tên lớp
        classes_result.sort(key=lambda x: x['class_title'])
        
        return success_response(
            data={
                "period": period,
                "date": str(date_obj),
                "summary": {
                    "total_classes": len(classes),
                    "total_students": total_students_all,
                    "present": present_all,
                    "absent": absent_all,
                    "late": late_all,
                    "rate": round(present_all / total_students_all * 100, 1) if total_students_all > 0 else 0
                },
                "classes": classes_result
            },
            message="Lấy thống kê điểm danh theo tiết thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_period_attendance_overview error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê điểm danh: {str(e)}",
            code="GET_PERIOD_OVERVIEW_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_class_attendance_summary(class_id=None, date=None):
    """
    Thống kê điểm danh tất cả các tiết của 1 lớp trong 1 ngày
    
    Args:
        class_id: ID của lớp
        date: Ngày cần xem (YYYY-MM-DD)
    
    Returns:
        {
            success: true,
            data: {
                class_info: { name, title, homeroom_teacher, total_students },
                periods: [
                    {
                        period, subject_id, subject_name,
                        teacher_id, teacher_name,
                        present, absent, late, excused,
                        has_attendance
                    }
                ]
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
        
        # Đếm học sinh
        total_students = frappe.db.count("SIS Class Student", {"class_id": class_id})
        
        # Lấy tên giáo viên chủ nhiệm
        homeroom_teacher_name = None
        if class_doc.homeroom_teacher:
            homeroom_teacher_name = frappe.get_value("SIS Teacher", class_doc.homeroom_teacher, "teacher_name")
        
        # Lấy timetable instance
        timetable_instance = frappe.db.get_value(
            "SIS Timetable Instance",
            {
                "class_id": class_id,
                "start_date": ["<=", date_obj],
                "end_date": [">=", date_obj]
            },
            "name"
        )
        
        # Lấy các tiết học trong ngày từ timetable
        periods_data = []
        if timetable_instance:
            # Lấy day_of_week
            day_of_week = date_obj.strftime("%A")
            
            periods_data = frappe.db.sql("""
                SELECT 
                    tc.period_name,
                    tc.subject_id,
                    sub.title as subject_name,
                    tc.teacher_id,
                    t.teacher_name
                FROM `tabSIS Timetable Column` tc
                LEFT JOIN `tabSIS Subject` sub ON tc.subject_id = sub.name
                LEFT JOIN `tabSIS Teacher` t ON tc.teacher_id = t.name
                WHERE tc.timetable_instance_id = %(instance)s
                    AND tc.day_of_week = %(day)s
                ORDER BY tc.period_name
            """, {
                "instance": timetable_instance,
                "day": day_of_week
            }, as_dict=True)
        
        # Thêm Homeroom vào cuối
        periods_data.append({
            "period_name": "Homeroom",
            "subject_id": None,
            "subject_name": "Homeroom",
            "teacher_id": class_doc.homeroom_teacher,
            "teacher_name": homeroom_teacher_name
        })
        
        # Lấy tất cả attendance data cho các tiết
        period_names = [p['period_name'] for p in periods_data]
        
        attendance_data = frappe.db.sql("""
            SELECT 
                period,
                status,
                COUNT(*) as count
            FROM `tabSIS Class Attendance`
            WHERE class_id = %(class_id)s
                AND date = %(date)s
                AND period IN %(periods)s
            GROUP BY period, status
        """, {
            "class_id": class_id,
            "date": date_obj,
            "periods": period_names
        }, as_dict=True)
        
        # Build map: period -> {status -> count}
        attendance_map = {}
        for row in attendance_data:
            if row['period'] not in attendance_map:
                attendance_map[row['period']] = {}
            attendance_map[row['period']][row['status']] = row['count']
        
        # Build kết quả
        periods_result = []
        for p in periods_data:
            period_name = p['period_name']
            att = attendance_map.get(period_name, {})
            
            present = att.get('present', 0)
            absent = att.get('absent', 0)
            late = att.get('late', 0)
            excused = att.get('excused', 0)
            left_early = att.get('left_early', 0)
            
            periods_result.append({
                "period": period_name,
                "subject_id": p.get('subject_id'),
                "subject_name": p.get('subject_name'),
                "teacher_id": p.get('teacher_id'),
                "teacher_name": p.get('teacher_name'),
                "total": total_students,
                "present": present,
                "absent": absent,
                "late": late,
                "excused": excused,
                "left_early": left_early,
                "has_attendance": sum([present, absent, late, excused, left_early]) > 0,
                "rate": round(present / total_students * 100, 1) if total_students > 0 else 0
            })
        
        return success_response(
            data={
                "class_info": {
                    "name": class_doc.name,
                    "title": class_doc.title,
                    "homeroom_teacher": class_doc.homeroom_teacher,
                    "homeroom_teacher_name": homeroom_teacher_name,
                    "total_students": total_students
                },
                "periods": periods_result
            },
            message="Lấy thống kê điểm danh lớp thành công"
        )
        
    except frappe.DoesNotExistError:
        return error_response(
            message=f"Không tìm thấy lớp: {class_id}",
            code="CLASS_NOT_FOUND"
        )
    except Exception as e:
        frappe.log_error(f"get_class_attendance_summary error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê điểm danh: {str(e)}",
            code="GET_CLASS_ATTENDANCE_ERROR"
        )
