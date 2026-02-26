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
    
    # Thử tìm campus đầu tiên nếu không tìm được
    first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
    return first_campus


@frappe.whitelist(allow_guest=False)
def get_period_attendance_overview(date=None, period=None, campus_id=None, education_stage_id=None):
    """
    Thống kê điểm danh 1 tiết cho tất cả các lớp
    
    Args:
        date: Ngày cần xem (YYYY-MM-DD)
        period: Tên tiết (e.g. "Tiết 1", "Homeroom") hoặc ID của SIS Timetable Column
        campus_id: Campus ID (optional)
        education_stage_id: Education Stage ID để filter lớp theo cấp học (optional)
    
    Returns:
        {
            success: true,
            data: {
                period: "Tiết 1",
                date: "2025-01-19",
                summary: { total_classes, total_students, present, absent, late, completed_classes, incomplete_classes },
                classes: [
                    {
                        class_id, class_title, 
                        total, present, absent, late, excused,
                        teacher_id, teacher_name, subject_name,
                        has_attendance, rate
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
        if not education_stage_id:
            education_stage_id = frappe.request.args.get('education_stage_id')
        
        if not date or not period:
            return error_response(
                message="Thiếu tham số: date và period là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        # Parse date
        date_obj = frappe.utils.getdate(date)
        
        # Resolve campus_id từ format frontend sang format database
        campus_id = _resolve_campus_id(campus_id)
        
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
        
        # Lấy period_name từ timetable_column nếu period là ID
        period_name = period
        if period.startswith("SIS-TIMETABLE-COLUMN"):
            tc = frappe.db.get_value("SIS Timetable Column", period, "period_name")
            if tc:
                period_name = tc
        
        # Lấy danh sách lớp, có thể filter theo education_stage_id
        if education_stage_id:
            # Query với filter theo education_stage thông qua education_grade
            classes = frappe.db.sql("""
                SELECT DISTINCT c.name, c.title, c.homeroom_teacher, c.education_grade
                FROM `tabSIS Class` c
                LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
                WHERE c.school_year_id = %(school_year)s
                    AND c.class_type = 'regular'
                    AND (c.campus_id = %(campus_id)s OR %(campus_id)s IS NULL)
                    AND eg.education_stage_id = %(education_stage_id)s
                ORDER BY c.title
            """, {
                "school_year": school_year,
                "campus_id": campus_id,
                "education_stage_id": education_stage_id
            }, as_dict=True)
        else:
            # Query không filter education_stage
            class_filters = {
                "school_year_id": school_year,
                "class_type": "regular"
            }
            if campus_id:
                class_filters["campus_id"] = campus_id
            
            classes = frappe.get_all(
                "SIS Class",
                filters=class_filters,
                fields=["name", "title", "homeroom_teacher", "education_grade"]
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
            "period": period_name
        }, as_dict=True)
        
        # Build attendance map: class_id -> {status -> count}
        attendance_map = {}
        for row in attendance_data:
            if row['class_id'] not in attendance_map:
                attendance_map[row['class_id']] = {}
            attendance_map[row['class_id']][row['status']] = row['count']
        
        # Lấy giáo viên và môn học dạy tiết này (từ timetable)
        teacher_map = {}
        if period_name.lower() != 'homeroom':
            # day_of_week trong database là format viết tắt: mon, tue, wed, thu, fri, sat, sun
            day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
            day_of_week_short = day_map.get(date_obj.weekday(), 'mon')
            
            # Query timetable để lấy môn học
            # SIS Timetable Instance Row có subject_id link đến SIS Subject
            # SIS Subject có timetable_subject_id link đến SIS Timetable Subject (có title_vn)
            timetable_data = frappe.db.sql("""
                SELECT 
                    ti.class_id,
                    tr.name as row_id,
                    tr.subject_id,
                    COALESCE(ts.title_vn, sub.title) as subject_name
                FROM `tabSIS Timetable Instance` ti
                INNER JOIN `tabSIS Timetable Instance Row` tr ON tr.parent = ti.name
                LEFT JOIN `tabSIS Subject` sub ON tr.subject_id = sub.name
                LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
                WHERE ti.class_id IN %(class_ids)s
                    AND ti.start_date <= %(date)s
                    AND (ti.end_date >= %(date)s OR ti.end_date IS NULL)
                    AND tr.timetable_column_id = %(period_id)s
                    AND tr.day_of_week = %(day_of_week)s
                    AND (tr.valid_from IS NULL OR tr.valid_from <= %(date)s)
                    AND (tr.valid_to IS NULL OR tr.valid_to >= %(date)s)
            """, {
                "class_ids": class_ids,
                "date": date_obj,
                "period_id": period if period.startswith("SIS-TIMETABLE-COLUMN") else None,
                "day_of_week": day_of_week_short
            }, as_dict=True)
            
            # Nếu không tìm được bằng period_id, thử tìm bằng period_name
            if not timetable_data:
                timetable_data = frappe.db.sql("""
                    SELECT 
                        ti.class_id,
                        tr.name as row_id,
                        tr.subject_id,
                        COALESCE(ts.title_vn, sub.title) as subject_name
                    FROM `tabSIS Timetable Instance` ti
                    INNER JOIN `tabSIS Timetable Instance Row` tr ON tr.parent = ti.name
                    INNER JOIN `tabSIS Timetable Column` tc ON tr.timetable_column_id = tc.name
                    LEFT JOIN `tabSIS Subject` sub ON tr.subject_id = sub.name
                    LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
                    WHERE ti.class_id IN %(class_ids)s
                        AND ti.start_date <= %(date)s
                        AND (ti.end_date >= %(date)s OR ti.end_date IS NULL)
                        AND tc.period_name = %(period_name)s
                        AND tr.day_of_week = %(day_of_week)s
                        AND (tr.valid_from IS NULL OR tr.valid_from <= %(date)s)
                        AND (tr.valid_to IS NULL OR tr.valid_to >= %(date)s)
                """, {
                    "class_ids": class_ids,
                    "date": date_obj,
                    "period_name": period_name,
                    "day_of_week": day_of_week_short
                }, as_dict=True)
            
            # Lấy teacher từ child table cho các rows tìm được
            row_ids = [row['row_id'] for row in timetable_data if row.get('row_id')]
            teacher_data_by_row = {}
            
            if row_ids:
                # Lấy teacher đầu tiên (sort_order thấp nhất) từ child table
                teacher_rows = frappe.db.sql("""
                    SELECT 
                        trt.parent as row_id,
                        trt.teacher_id,
                        u.full_name as teacher_name
                    FROM `tabSIS Timetable Instance Row Teacher` trt
                    LEFT JOIN `tabSIS Teacher` t ON trt.teacher_id = t.name
                    LEFT JOIN `tabUser` u ON t.user_id = u.name
                    WHERE trt.parent IN %(row_ids)s
                    ORDER BY trt.sort_order ASC
                """, {
                    "row_ids": row_ids
                }, as_dict=True)
                
                for trow in teacher_rows:
                    if trow['row_id'] not in teacher_data_by_row:
                        teacher_data_by_row[trow['row_id']] = {
                            "teacher_id": trow.get('teacher_id'),
                            "teacher_name": trow.get('teacher_name')
                        }
            
            for row in timetable_data:
                row_id = row.get('row_id')
                teacher_info = teacher_data_by_row.get(row_id, {})
                teacher_map[row['class_id']] = {
                    "teacher_id": teacher_info.get('teacher_id'),
                    "teacher_name": teacher_info.get('teacher_name'),
                    "subject_id": row.get('subject_id'),
                    "subject_name": row.get('subject_name')
                }
        
        # Build kết quả cho từng lớp
        classes_result = []
        total_students_all = 0
        present_all = 0
        absent_all = 0
        late_all = 0
        completed_classes = 0
        incomplete_classes = 0
        
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
            
            # FIX BUG: Chỉ coi là "đã điểm danh" khi có ít nhất 1 record với status KHÁC excused
            # Vì excused có thể được tạo tự động từ đơn nghỉ phép (leave request)
            # Khi giáo viên điểm danh, tất cả học sinh sẽ có status (present/absent/late/excused)
            # Nên nếu chỉ có excused thì nghĩa là chưa điểm danh thủ công
            has_attendance = sum([present, absent, late, left_early]) > 0
            if has_attendance:
                completed_classes += 1
            else:
                incomplete_classes += 1
            
            # Lấy teacher info và subject info
            teacher_info = teacher_map.get(cls.name)
            if not teacher_info and cls.homeroom_teacher:
                # Fallback về homeroom teacher
                # SIS Teacher chỉ có user_id, cần query User để lấy full_name
                teacher_user_id = frappe.get_value("SIS Teacher", cls.homeroom_teacher, "user_id")
                teacher_name = None
                if teacher_user_id:
                    teacher_name = frappe.get_value("User", teacher_user_id, "full_name")
                teacher_info = {
                    "teacher_id": cls.homeroom_teacher,
                    "teacher_name": teacher_name,
                    "subject_id": None,
                    "subject_name": None
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
                "subject_id": teacher_info.get('subject_id') if teacher_info else None,
                "subject_name": teacher_info.get('subject_name') if teacher_info else None,
                "has_attendance": has_attendance,
                "rate": round(present / total * 100, 1) if total > 0 else 0
            })
        
        # Sort theo tên lớp
        classes_result.sort(key=lambda x: x['class_title'])
        
        return success_response(
            data={
                "period": period_name,
                "period_id": period if period.startswith("SIS-TIMETABLE-COLUMN") else None,
                "date": str(date_obj),
                "summary": {
                    "total_classes": len(classes),
                    "total_students": total_students_all,
                    "present": present_all,
                    "absent": absent_all,
                    "late": late_all,
                    "completed_classes": completed_classes,
                    "incomplete_classes": incomplete_classes,
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
        # SIS Teacher chỉ có user_id, cần query User để lấy full_name
        homeroom_teacher_name = None
        if class_doc.homeroom_teacher:
            teacher_user_id = frappe.get_value("SIS Teacher", class_doc.homeroom_teacher, "user_id")
            if teacher_user_id:
                homeroom_teacher_name = frappe.get_value("User", teacher_user_id, "full_name")
        
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
            # day_of_week trong database là format viết tắt: mon, tue, wed, thu, fri, sat, sun
            day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
            day_of_week_short = day_map.get(date_obj.weekday(), 'mon')
            
            # Lấy các rows trong timetable instance cho ngày này
            # SIS Subject có timetable_subject_id link đến SIS Timetable Subject (có title_vn)
            rows_data = frappe.db.sql("""
                SELECT 
                    tr.name as row_id,
                    tc.period_name,
                    tr.subject_id,
                    COALESCE(ts.title_vn, sub.title) as subject_name
                FROM `tabSIS Timetable Instance Row` tr
                LEFT JOIN `tabSIS Timetable Column` tc ON tr.timetable_column_id = tc.name
                LEFT JOIN `tabSIS Subject` sub ON tr.subject_id = sub.name
                LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
                WHERE tr.parent = %(instance)s
                    AND tr.day_of_week = %(day)s
                    AND (tr.valid_from IS NULL OR tr.valid_from <= %(date)s)
                    AND (tr.valid_to IS NULL OR tr.valid_to >= %(date)s)
                ORDER BY tc.period_priority
            """, {
                "instance": timetable_instance,
                "day": day_of_week_short,
                "date": date_obj
            }, as_dict=True)
            
            # Lấy teacher từ child table
            row_ids = [r['row_id'] for r in rows_data if r.get('row_id')]
            teacher_map = {}
            
            if row_ids:
                teacher_rows = frappe.db.sql("""
                    SELECT 
                        trt.parent as row_id,
                        trt.teacher_id,
                        u.full_name as teacher_name
                    FROM `tabSIS Timetable Instance Row Teacher` trt
                    LEFT JOIN `tabSIS Teacher` t ON trt.teacher_id = t.name
                    LEFT JOIN `tabUser` u ON t.user_id = u.name
                    WHERE trt.parent IN %(row_ids)s
                    ORDER BY trt.sort_order ASC
                """, {
                    "row_ids": row_ids
                }, as_dict=True)
                
                for trow in teacher_rows:
                    if trow['row_id'] not in teacher_map:
                        teacher_map[trow['row_id']] = {
                            "teacher_id": trow.get('teacher_id'),
                            "teacher_name": trow.get('teacher_name')
                        }
            
            # Build periods_data với teacher info
            for row in rows_data:
                row_id = row.get('row_id')
                teacher_info = teacher_map.get(row_id, {})
                periods_data.append({
                    "period_name": row.get('period_name'),
                    "subject_id": row.get('subject_id'),
                    "subject_name": row.get('subject_name'),
                    "teacher_id": teacher_info.get('teacher_id'),
                    "teacher_name": teacher_info.get('teacher_name')
                })
        
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
                # FIX BUG: Không tính excused vì có thể tự động từ đơn nghỉ phép
                "has_attendance": sum([present, absent, late, left_early]) > 0,
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


@frappe.whitelist(allow_guest=False)
def get_education_stages(campus_id=None):
    """
    Lấy danh sách các cấp học (Education Stages) của campus
    
    Args:
        campus_id: Campus ID (optional, nếu không truyền sẽ lấy từ context)
    
    Returns:
        {
            success: true,
            data: [
                { name, title_vn, title_en, short_title }
            ]
        }
    """
    try:
        if not campus_id:
            campus_id = frappe.request.args.get('campus_id')
        
        # Resolve campus_id từ format frontend sang format database
        campus_id = _resolve_campus_id(campus_id)
        
        # Lấy campus từ context nếu không truyền
        if not campus_id:
            try:
                from erp.sis.utils.campus_permissions import get_current_user_campus
                campus_id = get_current_user_campus()
            except Exception:
                pass
        
        if not campus_id:
            return error_response(
                message="Thiếu tham số: campus_id là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        # Lấy danh sách education stages của campus
        stages = frappe.get_all(
            "SIS Education Stage",
            filters={"campus_id": campus_id},
            fields=["name", "title_vn", "title_en", "short_title"],
            order_by="title_vn asc"
        )
        
        return success_response(
            data=stages,
            message="Lấy danh sách cấp học thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_education_stages error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách cấp học: {str(e)}",
            code="GET_EDUCATION_STAGES_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_timetable_columns(education_stage_id=None, campus_id=None, date=None):
    """
    Lấy danh sách các tiết học (Timetable Columns) theo cấp học
    
    Logic:
    1. Nếu có date: Tìm schedule active cho ngày đó, lấy periods từ schedule
    2. Nếu không có schedule active: Fallback về legacy periods (schedule_id is NULL)
    3. Dedupe theo period_priority (ưu tiên schedule periods)
    
    Args:
        education_stage_id: Education Stage ID (required)
        campus_id: Campus ID (optional)
        date: Ngày cần lấy periods (YYYY-MM-DD), nếu không truyền sẽ dùng ngày hôm nay
    
    Returns:
        {
            success: true,
            data: [
                { 
                    name, period_name, period_priority, 
                    start_time, end_time, period_type 
                }
            ]
        }
    """
    try:
        from frappe.utils import getdate, nowdate
        from datetime import timedelta
        
        if not education_stage_id:
            education_stage_id = frappe.request.args.get('education_stage_id')
        if not campus_id:
            campus_id = frappe.request.args.get('campus_id')
        if not date:
            date = frappe.request.args.get('date')
        
        if not education_stage_id:
            return error_response(
                message="Thiếu tham số: education_stage_id là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        # Resolve campus_id từ format frontend sang format database
        campus_id = _resolve_campus_id(campus_id)
        
        # Lấy campus từ context nếu không truyền
        if not campus_id:
            try:
                from erp.sis.utils.campus_permissions import get_current_user_campus
                campus_id = get_current_user_campus()
            except Exception:
                pass
        
        # Nếu không truyền date, dùng ngày hôm nay
        target_date = getdate(date) if date else getdate(nowdate())
        
        columns = []
        
        # Tìm schedule active cho ngày target_date
        schedule_filters = {
            "campus_id": campus_id,
            "education_stage_id": education_stage_id,
            "is_active": 1,
            "start_date": ["<=", target_date],
            "end_date": [">=", target_date]
        }
        
        active_schedules = frappe.get_all(
            "SIS Schedule",
            filters=schedule_filters,
            fields=["name"],
            order_by="start_date desc"
        )
        
        if active_schedules:
            # Lấy periods từ schedule active
            schedule_ids = [s.name for s in active_schedules]
            columns = frappe.get_all(
                "SIS Timetable Column",
                filters={
                    "schedule_id": ["in", schedule_ids],
                    "education_stage_id": education_stage_id,
                    "period_type": "study"
                },
                fields=["name", "period_name", "period_priority", "start_time", "end_time", "period_type", "schedule_id"],
                order_by="period_priority asc"
            )
        
        # Nếu không có periods từ schedule, fallback về legacy
        if not columns:
            legacy_filters = {
                "education_stage_id": education_stage_id,
                "period_type": "study",
                "schedule_id": ["is", "not set"]
            }
            if campus_id:
                legacy_filters["campus_id"] = campus_id
            
            columns = frappe.get_all(
                "SIS Timetable Column",
                filters=legacy_filters,
                fields=["name", "period_name", "period_priority", "start_time", "end_time", "period_type", "schedule_id"],
                order_by="period_priority asc"
            )
        
        # Dedupe theo period_priority (chỉ giữ 1 period cho mỗi priority)
        seen_priorities = set()
        deduped_columns = []
        for col in columns:
            priority = col.get("period_priority")
            if priority not in seen_priorities:
                seen_priorities.add(priority)
                deduped_columns.append(col)
        columns = deduped_columns
        
        # Format thời gian
        def format_time(time_value):
            if not time_value:
                return ""
            if isinstance(time_value, timedelta):
                total_seconds = int(time_value.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                return f"{hours:02d}:{minutes:02d}"
            return str(time_value)[:5]
        
        for col in columns:
            col['start_time'] = format_time(col.get('start_time'))
            col['end_time'] = format_time(col.get('end_time'))
            # Bỏ schedule_id khỏi response để đơn giản hóa
            col.pop('schedule_id', None)
        
        # Thêm tiết Homeroom - tiết đặc biệt không có trong schedule
        # Đặt ở cuối với priority cao nhất
        max_priority = max([col.get('period_priority', 0) for col in columns], default=0) + 1
        homeroom_period = {
            "name": "HOMEROOM",
            "period_name": "Homeroom",
            "period_priority": max_priority,
            "start_time": "",
            "end_time": "",
            "period_type": "study"
        }
        columns.append(homeroom_period)
        
        return success_response(
            data=columns,
            message="Lấy danh sách tiết học thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_timetable_columns error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách tiết học: {str(e)}",
            code="GET_TIMETABLE_COLUMNS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_school_attendance_summary(date=None, period=None, campus_id=None):
    """
    Lấy thống kê điểm danh toàn trường cho 1 tiết (thường là Homeroom)
    Bao gồm: tổng học sinh, đã điểm danh, có mặt, vắng, muộn
    
    Args:
        date: Ngày cần xem (YYYY-MM-DD)
        period: Tên tiết (e.g. "Homeroom")
        campus_id: Campus ID (optional)
    
    Returns:
        {
            success: true,
            data: {
                date: "2026-02-23",
                period: "Homeroom",
                school_year: "2025-2026",
                summary: {
                    total_students: 1519,      # Tổng học sinh toàn trường
                    total_attendance: 1512,    # Tổng đã điểm danh
                    not_attendance: 7,         # Chưa điểm danh
                    present: 1285,             # Có mặt
                    late: 34,                  # Đến muộn
                    present_total: 1319,       # Tổng có mặt (present + late)
                    absent: 16,                # Vắng không phép
                    excused: 177,              # Vắng có phép
                    left_early: 0,             # Về sớm
                    total_absent: 193,         # Tổng vắng (absent + excused)
                    attendance_rate: 87.2      # Tỷ lệ có mặt
                }
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
        
        if not date:
            return error_response(
                message="Thiếu tham số: date là bắt buộc",
                code="MISSING_PARAMS"
            )
        
        # Default period là Homeroom
        if not period:
            period = 'Homeroom'
        
        # Parse date
        date_obj = frappe.utils.getdate(date)
        
        # Resolve campus_id từ format frontend sang format database
        campus_id = _resolve_campus_id(campus_id)
        
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
        
        if not school_year:
            return error_response(
                message="Không tìm thấy năm học đang active",
                code="NO_ACTIVE_SCHOOL_YEAR"
            )
        
        # Build class filters
        class_filters = {
            "school_year_id": school_year,
            "class_type": "regular"
        }
        if campus_id:
            class_filters["campus_id"] = campus_id
        
        # Lấy tổng số học sinh toàn trường
        total_students = frappe.db.sql("""
            SELECT COUNT(DISTINCT cs.student_id) as total
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
            WHERE c.school_year_id = %(school_year)s 
                AND c.class_type = 'regular'
                AND (c.campus_id = %(campus_id)s OR %(campus_id)s IS NULL)
        """, {
            "school_year": school_year,
            "campus_id": campus_id
        })[0][0] or 0
        
        # Lấy thống kê điểm danh
        stats = frappe.db.sql("""
            SELECT 
                COUNT(*) as total_attendance,
                SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) as present,
                SUM(CASE WHEN a.status = 'late' THEN 1 ELSE 0 END) as late,
                SUM(CASE WHEN a.status IN ('present', 'late') THEN 1 ELSE 0 END) as present_total,
                SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) as absent,
                SUM(CASE WHEN a.status = 'excused' THEN 1 ELSE 0 END) as excused,
                SUM(CASE WHEN a.status = 'left_early' THEN 1 ELSE 0 END) as left_early
            FROM `tabSIS Class Attendance` a
            INNER JOIN `tabSIS Class` c ON a.class_id = c.name
            WHERE a.date = %(date)s 
                AND a.period = %(period)s
                AND c.school_year_id = %(school_year)s 
                AND c.class_type = 'regular'
                AND (c.campus_id = %(campus_id)s OR %(campus_id)s IS NULL)
        """, {
            "date": date_obj,
            "period": period,
            "school_year": school_year,
            "campus_id": campus_id
        }, as_dict=True)[0]
        
        # Tính toán các giá trị
        total_attendance = int(stats['total_attendance'] or 0)
        present = int(stats['present'] or 0)
        late = int(stats['late'] or 0)
        present_total = int(stats['present_total'] or 0)
        absent = int(stats['absent'] or 0)
        excused = int(stats['excused'] or 0)
        left_early = int(stats['left_early'] or 0)
        total_absent = absent + excused
        not_attendance = total_students - total_attendance
        
        # Tính tỷ lệ có mặt
        attendance_rate = round(present_total / total_attendance * 100, 1) if total_attendance > 0 else 0
        
        return success_response(
            data={
                "date": str(date_obj),
                "period": period,
                "school_year": school_year,
                "summary": {
                    "total_students": total_students,
                    "total_attendance": total_attendance,
                    "not_attendance": not_attendance,
                    "present": present,
                    "late": late,
                    "present_total": present_total,
                    "absent": absent,
                    "excused": excused,
                    "left_early": left_early,
                    "total_absent": total_absent,
                    "attendance_rate": attendance_rate
                }
            },
            message="Lấy thống kê điểm danh toàn trường thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"get_school_attendance_summary error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê điểm danh toàn trường: {str(e)}",
            code="GET_SCHOOL_ATTENDANCE_SUMMARY_ERROR"
        )
