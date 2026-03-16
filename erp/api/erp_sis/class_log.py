import json
import re
from datetime import datetime as dt, timedelta
import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response


def _get_body():
    try:
        if hasattr(frappe, 'request') and getattr(frappe.request, 'data', None):
            return json.loads(frappe.request.data.decode('utf-8'))
    except Exception:
        return {}
    return {}


@frappe.whitelist(allow_guest=False)
def get_class_log_options(education_stage=None):
    """Get class log options (master data)
    
    ⚡ Performance: Cached for 30 minutes (shared cache - master data)
    """
    try:
        if not education_stage and getattr(frappe, 'request', None):
            education_stage = frappe.request.args.get('education_stage')

        filters = {"is_active": 1}
        if education_stage:
            filters["education_stage"] = education_stage
        
        # ⚡ CACHE: Check Redis cache first (30 min TTL - shared cache for master data)
        # v2: thêm homeroom type - đổi key để invalidate cache cũ
        cache_key = f"class_log_options:v2:{education_stage or 'all'}"
        
        try:
            cached_data = frappe.cache().get_value(cache_key)
            if cached_data:
                frappe.logger().info(f"✅ Cache HIT for class_log_options {education_stage or 'all'}")
                return success_response(
                    data=cached_data,
                    message="Options fetched (cached)",
                    meta={"backend_logs": {"count": sum(len(v) for v in cached_data.values()), "cached": True}}
                )
        except Exception as cache_error:
            frappe.logger().warning(f"Cache read failed: {cache_error}")
        
        frappe.logger().info(f"❌ Cache MISS for class_log_options {education_stage or 'all'} - fetching from DB")

        rows = frappe.get_all(
            "SIS Class Log Score",
            filters=filters,
            fields=["name", "type", "title_vn", "title_en", "value", "color", "education_stage", "is_default"],
            order_by="type asc, value desc, title_vn asc"
        )

        grouped = {"homeroom": [], "homework": [], "behavior": [], "participation": [], "issue": [], "top_performance": []}
        for r in rows:
            t = (r.get('type') or '').lower()
            if t in grouped:
                grouped[t].append(r)
        
        # ⚡ CACHE: Store result in Redis (30 min = 1800 sec)
        try:
            frappe.cache().set_value(cache_key, grouped, expires_in_sec=1800)
            frappe.logger().info(f"✅ Cached class_log_options for {education_stage or 'all'}")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache write failed: {cache_error}")

        meta = {"backend_logs": {"count": len(rows)}}
        return success_response(data=grouped, message="Options fetched", meta=meta)
    except Exception as e:
        frappe.log_error(f"get_class_log_options error: {str(e)}")
        return error_response(message="Failed to fetch class log options", code="GET_LOG_OPTIONS_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def set_class_log_score_default():
    """Set a class log score as default for its education_stage + type combination.
    
    Khi set is_default=1 cho một record, tự động set is_default=0 cho các record khác
    cùng education_stage + type để đảm bảo chỉ có 1 default per education_stage + type.
    
    POST body:
    {
        "name": "SIS-CLS-LOG-SCORE-00001",
        "is_default": 1  // 0 hoặc 1
    }
    """
    try:
        body = _get_body() or {}
        name = body.get('name')
        is_default = body.get('is_default', 0)
        
        if not name:
            return error_response(message="Missing required parameter: name", code="MISSING_PARAMS")
        
        # Lấy thông tin record hiện tại
        score_doc = frappe.get_doc("SIS Class Log Score", name)
        education_stage = score_doc.education_stage
        score_type = score_doc.type
        
        # Nếu set is_default = 1, cần unset các record khác cùng education_stage + type
        if is_default:
            # Unset all other defaults for same education_stage + type
            frappe.db.sql("""
                UPDATE `tabSIS Class Log Score`
                SET is_default = 0
                WHERE education_stage = %(education_stage)s
                    AND type = %(type)s
                    AND name != %(name)s
                    AND is_default = 1
            """, {
                "education_stage": education_stage,
                "type": score_type,
                "name": name
            })
        
        # Update the target record
        frappe.db.set_value("SIS Class Log Score", name, "is_default", 1 if is_default else 0)
        frappe.db.commit()
        
        # Clear cache để frontend nhận được data mới
        try:
            # Clear cache cho education_stage cụ thể
            cache_key_stage = f"class_log_options:v2:{education_stage}"
            frappe.cache().delete_key(cache_key_stage)
            
            # Clear cache "all" (khi không có filter education_stage)
            cache_key_all = "class_log_options:v2:all"
            frappe.cache().delete_key(cache_key_all)
            
            frappe.logger().info(f"✅ Cleared class_log_options cache after setting default: {name}")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache clear failed: {cache_error}")
        
        return success_response(
            message=f"Default {'set' if is_default else 'unset'} successfully",
            data={"name": name, "is_default": 1 if is_default else 0}
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"set_class_log_score_default error: {str(e)}")
        return error_response(message="Failed to set default", code="SET_DEFAULT_ERROR")


@frappe.whitelist(allow_guest=False)
def get_class_log(timetable_instance=None, class_id=None, date=None, period=None):
    """Get class log data for a specific period
    
    ⚡ Performance: Cached for 10 minutes (user-specific)
    """
    try:
        if not timetable_instance and getattr(frappe, 'request', None):
            timetable_instance = frappe.request.args.get('timetable_instance')
            class_id = class_id or frappe.request.args.get('class_id')
            date = date or frappe.request.args.get('date')
            period = period or frappe.request.args.get('period')

        # Resolve timetable_instance if not provided
        if not timetable_instance:
            if not class_id or not date:
                return error_response(message="Missing parameters: timetable_instance or (class_id, date)", code="MISSING_PARAMS")
            inst_row = frappe.get_all(
                "SIS Timetable Instance",
                filters={
                    "class_id": class_id,
                    "start_date": ["<=", date],
                    "end_date": [">=", date],
                },
                fields=["name"], limit=1
            )
            if not inst_row:
                return error_response(message="No timetable instance found for class/date", code="INSTANCE_NOT_FOUND")
            timetable_instance = inst_row[0]['name']
        
        # ⚡ CACHE: Check Redis cache first (10 min TTL - user-specific)
        # Use class_id+date+period as key (more stable than timetable_instance)
        cache_key = f"class_log:{class_id}:{date}:{period or 'none'}"
        
        try:
            cached_data = frappe.cache().get_value(cache_key)
            if cached_data:
                frappe.logger().info(f"✅ Cache HIT for class_log {class_id}/{date}/{period or 'none'}")
                return success_response(
                    data=cached_data,
                    message="Class log fetched (cached)",
                    meta={"class_id": cached_data.get("subject", {}).get("class_id"), "backend_logs": {"cached": True}}
                )
        except Exception as cache_error:
            frappe.logger().warning(f"Cache read failed: {cache_error}")
        
        frappe.logger().info(f"❌ Cache MISS for class_log {class_id}/{date}/{period or 'none'} - fetching from DB")

        # Ensure subject record exists for this instance
        filters = {"timetable_instance_id": timetable_instance}
        if date:
            filters["log_date"] = date
        if period:
            filters["period"] = period
        subject_rows = frappe.get_all(
            "SIS Class Log Subject",
            filters=filters,
            fields=["name", "class_id", "general_comment", "lesson_name", "lesson_score", "is_practise_test", "homework_assignment"],
            limit=1
        )
        if subject_rows:
            subject_id = subject_rows[0]['name']
            class_id = subject_rows[0]['class_id']
            general_comment = subject_rows[0].get('general_comment')
            lesson_name = subject_rows[0].get('lesson_name')
            lesson_score = subject_rows[0].get('lesson_score')
            is_practise_test = subject_rows[0].get('is_practise_test')
            homework_assignment = subject_rows[0].get('homework_assignment')
        else:
            # Resolve class from instance
            inst = frappe.get_doc("SIS Timetable Instance", timetable_instance)
            class_id = inst.class_id
            from erp.sis.utils.campus_permissions import get_current_user_campus, get_user_campuses
            campus_id = None
            try:
                campus_id = get_current_user_campus()
                if not campus_id:
                    campuses = get_user_campuses(frappe.session.user)
                    campus_id = campuses[0] if campuses else None
            except Exception:
                pass
            doc = frappe.get_doc({
                "doctype": "SIS Class Log Subject",
                "timetable_instance_id": timetable_instance,
                "class_id": class_id,
                "log_date": date,
                "period": period,
                "recorded_by": frappe.session.user,
                "campus_id": campus_id
            })
            doc.insert()
            subject_id = doc.name
            general_comment = None
            lesson_name = None
            lesson_score = None
            is_practise_test = 0
            homework_assignment = None

        # Load student logs
        student_logs = frappe.get_all(
            "SIS Class Log Student",
            filters={"subject_id": subject_id},
            fields=[
                "name", "student_id", "class_student_id", "homework", "behavior", "participation", "issues", "is_top_performance", "specific_comment", "value"
            ]
        )

        # Fallback: if no logs yet, prefill with class students so FE can display and edit
        if not student_logs:
            fallback_students = frappe.get_all(
                "SIS Class Student",
                filters={"class_id": class_id},
                fields=[
                    "name as class_student_id",
                    "student_id",
                ]
            )
            # Ensure consistent keys with expected response (no grades yet)
            student_logs = [
                {
                    "student_id": s.get("student_id"),
                    "class_student_id": s.get("class_student_id"),
                }
                for s in fallback_students
                if s.get("student_id")
            ]

        data = {
            "subject": {
                "name": subject_id,
                "timetable_instance_id": timetable_instance,
                "class_id": class_id,
                "general_comment": general_comment,
                "lesson_name": lesson_name,
                "lesson_score": lesson_score,
                "is_practise_test": is_practise_test,
                "homework_assignment": homework_assignment,
            },
            "students": student_logs
        }
        
        # ⚡ CACHE: Store result in Redis (10 min = 600 sec)
        try:
            frappe.cache().set_value(cache_key, data, expires_in_sec=600)
            frappe.logger().info(f"✅ Cached class_log for {class_id}/{date}/{period or 'none'}")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache write failed: {cache_error}")
        
        meta = {"class_id": class_id, "backend_logs": {"subject_created": not bool(subject_rows), "prefilled_from_class_students": not bool(subject_rows) or len(student_logs) == 0}}
        return success_response(data=data, message="Class log fetched", meta=meta)
    except Exception as e:
        frappe.log_error(f"get_class_log error: {str(e)}")
        return error_response(message="Failed to fetch class log", code="GET_CLASS_LOG_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def save_class_log():
    try:
        body = _get_body() or {}
        timetable_instance = body.get('timetable_instance')
        class_id = body.get('class_id')
        date = body.get('date')
        period = body.get('period')
        general_comment = body.get('general_comment')
        lesson_name = body.get('lesson_name')
        lesson_score = body.get('lesson_score')
        is_practise_test = body.get('is_practise_test')
        homework_assignment = body.get('homework_assignment')
        items = body.get('students') or []
        if not timetable_instance:
            if not class_id or not date:
                return error_response(message="Missing parameters: timetable_instance or (class_id, date)", code="MISSING_PARAMS")
            inst_row = frappe.get_all(
                "SIS Timetable Instance",
                filters={
                    "class_id": class_id,
                    "start_date": ["<=", date],
                    "end_date": [">=", date],
                },
                fields=["name"], limit=1
            )
            if not inst_row:
                return error_response(message="No timetable instance found for class/date", code="INSTANCE_NOT_FOUND")
            timetable_instance = inst_row[0]['name']

        # Ensure subject exists
        filters = {"timetable_instance_id": timetable_instance}
        if date:
            filters["log_date"] = date
        if period:
            filters["period"] = period
        subject_rows = frappe.get_all(
            "SIS Class Log Subject",
            filters=filters,
            fields=["name", "class_id"], limit=1
        )
        if subject_rows:
            subject_id = subject_rows[0]['name']
            class_id = subject_rows[0]['class_id']
        else:
            inst = frappe.get_doc("SIS Timetable Instance", timetable_instance)
            class_id = inst.class_id
            from erp.sis.utils.campus_permissions import get_current_user_campus, get_user_campuses
            campus_id = None
            try:
                campus_id = get_current_user_campus()
                if not campus_id:
                    campuses = get_user_campuses(frappe.session.user)
                    campus_id = campuses[0] if campuses else None
            except Exception:
                pass
            doc = frappe.get_doc({
                "doctype": "SIS Class Log Subject",
                "timetable_instance_id": timetable_instance,
                "class_id": class_id,
                "log_date": date,
                "period": period,
                "recorded_by": frappe.session.user,
                "campus_id": campus_id
            })
            doc.insert()
            subject_id = doc.name

        # Update subject fields if provided
        update_fields = {}
        if general_comment is not None:
            update_fields["general_comment"] = general_comment
        if lesson_name is not None:
            update_fields["lesson_name"] = lesson_name
        if lesson_score is not None:
            update_fields["lesson_score"] = lesson_score
        if is_practise_test is not None:
            update_fields["is_practise_test"] = 1 if is_practise_test else 0
        if homework_assignment is not None:
            update_fields["homework_assignment"] = homework_assignment
        
        if update_fields:
            frappe.db.set_value("SIS Class Log Subject", subject_id, update_fields, update_modified=True)

        upserts = 0
        for it in items:
            student_id = (it or {}).get('student_id') or (it or {}).get('class_student')
            class_student_id = (it or {}).get('class_student')
            values = {
                "subject_id": subject_id,
                "student_id": student_id,
                "class_student_id": class_student_id,
                "homework": (it or {}).get('homework'),
                "behavior": (it or {}).get('behavior'),
                "participation": (it or {}).get('participation'),
                # legacy kept for backward compatibility but we now use 'issues' (comma-separated) and 'is_top_performance'
                "issues": (it or {}).get('issues') or (it or {}).get('issue'),
                "is_top_performance": 1 if ((it or {}).get('is_top_performance') or (it or {}).get('top_performance')) else 0,
                "specific_comment": (it or {}).get('specific_comment'),
                "value": (it or {}).get('value') or 0,
            }
            if not student_id:
                continue

            existing = frappe.get_all(
                "SIS Class Log Student",
                filters={"subject_id": subject_id, "student_id": student_id},
                fields=["name"], limit=1
            )
            if existing:
                frappe.db.set_value("SIS Class Log Student", existing[0]['name'], values, update_modified=True)
            else:
                doc = frappe.get_doc({"doctype": "SIS Class Log Student", **values})
                doc.insert()
                upserts += 1

        frappe.db.commit()
        
        # ⚡ CACHE: Clear class log cache after save (single, batch, and homeroom)
        try:
            # Clear single period cache
            cache_key = f"class_log:{class_id}:{date}:{period or 'none'}"
            frappe.cache().delete_key(cache_key)
            
            # Clear batch cache - use wildcard pattern
            cache = frappe.cache()
            redis_conn = cache.redis_cache if hasattr(cache, 'redis_cache') else cache
            if hasattr(redis_conn, 'scan_iter'):
                # Clear regular batch cache
                batch_pattern = f"*class_logs_batch:{class_id}:{date}:*"
                batch_keys = list(redis_conn.scan_iter(match=batch_pattern, count=100))
                if batch_keys:
                    redis_conn.delete(*batch_keys)
                    frappe.logger().info(f"✅ Cleared {len(batch_keys)} batch cache keys for {class_id}/{date}")
                
                # Clear homeroom class logs cache (any homeroom that references this class)
                homeroom_pattern = f"*homeroom_class_logs:*:{date}:*"
                homeroom_keys = list(redis_conn.scan_iter(match=homeroom_pattern, count=100))
                if homeroom_keys:
                    redis_conn.delete(*homeroom_keys)
                    frappe.logger().info(f"✅ Cleared {len(homeroom_keys)} homeroom cache keys for date {date}")
            
            frappe.logger().info(f"✅ Cleared class_log cache after save: {class_id}/{date}/{period or 'none'}")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache clear failed: {cache_error}")
        
        meta = {"class_id": class_id, "backend_logs": {"inserted": upserts, "total": len(items)}}
        return success_response(message=f"Saved class log ({upserts} inserted)", meta=meta)
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"save_class_log error: {str(e)}")
        return error_response(message="Failed to save class log", code="SAVE_CLASS_LOG_ERROR")


@frappe.whitelist(allow_guest=False, methods=['POST'])
def batch_get_class_logs():
    """
    Get class logs for multiple periods in a single request
    
    ⚡ Performance: Cached for 10 minutes (user-specific)
    
    POST body:
    {
        "class_id": "CLASS-001",
        "date": "2025-10-10",
        "periods": ["1", "2", "3", "4", ...]
    }
    
    Returns:
    {
        "success": true,
        "data": {
            "1": { subject: {...}, students: [...] },
            "2": { subject: {...}, students: [...] },
            ...
        }
    }
    """
    try:
        frappe.logger().info("🚀 [Backend] batch_get_class_logs called")
        
        body = _get_body() or {}
        class_id = body.get('class_id')
        date = body.get('date')
        periods = body.get('periods') or []
        
        if not class_id or not date or not periods:
            return error_response(
                message="Missing required parameters: class_id, date, periods",
                code="MISSING_PARAMS"
            )
        
        # ⚡ CACHE: Check Redis cache first (10 min TTL - user-specific)
        # Hash periods list for stable cache key
        import hashlib
        import json
        periods_hash = hashlib.md5(json.dumps(sorted(periods)).encode()).hexdigest()[:8]
        cache_key = f"class_logs_batch:{class_id}:{date}:periods_{periods_hash}"
        
        try:
            cached_data = frappe.cache().get_value(cache_key)
            if cached_data:
                frappe.logger().info(f"✅ Cache HIT for batch_class_logs {class_id}/{date} ({len(periods)} periods)")
                return success_response(
                    data=cached_data,
                    message=f"Fetched class logs for {len(periods)} periods (cached)"
                )
        except Exception as cache_error:
            frappe.logger().warning(f"Cache read failed: {cache_error}")
        
        frappe.logger().info(f"❌ Cache MISS for batch_class_logs {class_id}/{date} - fetching from DB")
        frappe.logger().info(f"📅 [Backend] Getting class logs for {len(periods)} periods")
        
        # Get timetable instance for this class/date
        inst_row = frappe.get_all(
            "SIS Timetable Instance",
            filters={
                "class_id": class_id,
                "start_date": ["<=", date],
                "end_date": [">=", date],
            },
            fields=["name"], 
            limit=1
        )
        
        if not inst_row:
            # No timetable instance = no logs yet, return empty structure
            result = {period: {"subject": None, "students": []} for period in periods}
            return success_response(data=result, message="No timetable instance found")
        
        timetable_instance = inst_row[0]['name']
        
        # Batch query: Get all subject logs for these periods at once
        subject_logs = frappe.get_all(
            "SIS Class Log Subject",
            filters={
                "timetable_instance_id": timetable_instance,
                "log_date": date,
                "period": ["in", periods]
            },
            fields=["name", "period", "class_id", "general_comment", "lesson_name", "lesson_score", "is_practise_test", "homework_assignment"]
        )
        
        # Build map: period -> subject
        subject_by_period = {log['period']: log for log in subject_logs}
        
        # Batch query: Get all student logs for these subjects at once
        subject_ids = [log['name'] for log in subject_logs]
        student_logs = []
        
        if subject_ids:
            student_logs = frappe.get_all(
                "SIS Class Log Student",
                filters={"subject_id": ["in", subject_ids]},
                fields=[
                    "subject_id",
                    "student_id",
                    "class_student_id",
                    "homework",
                    "behavior",
                    "participation",
                    "issues",
                    "is_top_performance"
                ]
            )
        
        # Build map: subject_id -> list of students
        students_by_subject = {}
        for student_log in student_logs:
            subject_id = student_log['subject_id']
            if subject_id not in students_by_subject:
                students_by_subject[subject_id] = []
            students_by_subject[subject_id].append(student_log)
        
        # Get class students for fallback (if no logs yet)
        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"class_id": class_id},
            fields=["name as class_student_id", "student_id"]
        )
        
        fallback_students = [
            {"student_id": s["student_id"], "class_student_id": s["class_student_id"]}
            for s in class_students if s.get("student_id")
        ]
        
        # Build result structure for each period
        result = {}
        for period in periods:
            subject = subject_by_period.get(period)
            
            if subject:
                # We have logs for this period
                subject_id = subject['name']
                students = students_by_subject.get(subject_id, fallback_students)
                
                result[period] = {
                    "subject": {
                        "name": subject_id,
                        "timetable_instance_id": timetable_instance,
                        "class_id": subject['class_id'],
                        "general_comment": subject.get('general_comment'),
                        "lesson_name": subject.get('lesson_name'),
                        "lesson_score": subject.get('lesson_score'),
                        "is_practise_test": subject.get('is_practise_test'),
                        "homework_assignment": subject.get('homework_assignment')
                    },
                    "students": students
                }
            else:
                # No logs yet for this period - return fallback structure
                result[period] = {
                    "subject": None,
                    "students": fallback_students
                }
        
        frappe.logger().info(f"✅ [Backend] Returning logs for {len(result)} periods")
        
        # ⚡ CACHE: Store result in Redis (10 min = 600 sec)
        try:
            frappe.cache().set_value(cache_key, result, expires_in_sec=600)
            frappe.logger().info(f"✅ Cached batch_class_logs for {class_id}/{date}")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache write failed: {cache_error}")
        
        return success_response(
            data=result,
            message=f"Fetched class logs for {len(periods)} periods"
        )
        
    except Exception as e:
        frappe.logger().error(f"❌ [Backend] batch_get_class_logs error: {str(e)}")
        frappe.log_error(f"batch_get_class_logs error: {str(e)}", "Batch Get Class Logs Error")
        return error_response(
            message=f"Failed to fetch batch class logs: {str(e)}",
            code="BATCH_GET_CLASS_LOGS_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def batch_get_homeroom_class_logs():
    """
    Get aggregated class logs for homeroom class view.
    
    This endpoint handles the case where students may study in different classes 
    (regular vs mixed) for different periods. It aggregates class logs from all 
    relevant classes for students belonging to the homeroom class.
    
    ⚡ Performance: Optimized with batch queries using WHERE IN clause,
    Redis caching (2 min TTL - short due to multi-source aggregation),
    and dict lookups instead of loops.
    
    POST body:
    {
        "homeroom_class_id": "CLASS-001",  // The homeroom/regular class ID
        "date": "2025-10-10",
        "periods": ["Tiết 1", "Tiết 2", "Tiết 3", ...]
    }
    
    Returns:
    {
        "success": true,
        "data": {
            "Tiết 1": { 
                "subject": {...}, 
                "students": [
                    {
                        "student_id": "...",
                        "homework": "...",
                        "behavior": "...",
                        "attendance": "present"  // ✨ NEW: attendance status
                    }
                ],
                "source_class_id": "CLASS-001",  // Which class this log came from
                "is_homeroom_class": true
            },
            "Tiết 2": { 
                "subject": {...}, 
                "students": [...],
                "source_class_id": "MIXED-MATH-001",  // From mixed class
                "is_homeroom_class": false
            },
            ...
        },
        "meta": {
            "homeroom_class_id": "CLASS-001",
            "student_count": 30,
            "classes_queried": ["CLASS-001", "MIXED-MATH-001", ...]
        }
    }
    
    ✨ Attendance Logic:
    - Queries attendance from the ACTUAL class each student attends for each period
    - Priority: Event Attendance > Class Attendance
    - Returns null if no attendance record found
    """
    try:
        import time
        import hashlib
        total_start = time.time()
        frappe.logger().info("🏠 [Backend] batch_get_homeroom_class_logs called")
        
        body = _get_body() or {}
        homeroom_class_id = body.get('homeroom_class_id')
        date = body.get('date')
        periods = body.get('periods') or []
        
        if not homeroom_class_id or not date or not periods:
            return error_response(
                message="Missing required parameters: homeroom_class_id, date, periods",
                code="MISSING_PARAMS"
            )
        
        # ⚡ CACHE: Check Redis cache first (2 min TTL - short because multi-source aggregation)
        # This endpoint aggregates: class logs + class attendance + event attendance
        # Using short TTL instead of complex event-driven invalidation
        periods_hash = hashlib.md5(json.dumps(sorted(periods)).encode()).hexdigest()[:8]
        # v5: subject_title tra theo recorded_by từ SIS Teacher Timetable (chính xác theo GV ghi log)
        cache_key = f"homeroom_class_logs_v5:{homeroom_class_id}:{date}:periods_{periods_hash}"
        
        try:
            cached_data = frappe.cache().get_value(cache_key)
            if cached_data:
                frappe.logger().info(f"✅ Cache HIT for homeroom_class_logs {homeroom_class_id}/{date}")
                return success_response(
                    data=cached_data['data'],
                    message=f"Fetched homeroom class logs for {len(periods)} periods (cached)",
                    meta=cached_data.get('meta', {})
                )
        except Exception as cache_error:
            frappe.logger().warning(f"Cache read failed: {cache_error}")
        
        frappe.logger().info(f"❌ Cache MISS - fetching from DB for {homeroom_class_id}, date={date}, {len(periods)} periods")
        
        # ⏱️ PROFILING: Track time for each step
        step_times = {}
        
        # Step 1: Lấy TẤT CẢ học sinh trong homeroom class (không filter class_type)
        # Lý do: Frontend hiển thị tất cả học sinh, backend cũng phải trả về tất cả
        # để tránh trường hợp một số học sinh hiện "N/A" dù đã được điểm danh
        step_start = time.time()
        homeroom_students = frappe.get_all(
            "SIS Class Student",
            filters={"class_id": homeroom_class_id},
            fields=["name as class_student_id", "student_id"]
        )
        
        student_ids = [s['student_id'] for s in homeroom_students if s.get('student_id')]
        
        # ⚡ OPTIMIZATION: Build student_id -> class_student_id lookup dict (O(1) instead of O(n))
        student_to_class_student = {s['student_id']: s['class_student_id'] for s in homeroom_students if s.get('student_id')}
        step_times['1_homeroom_students'] = (time.time() - step_start) * 1000
        
        frappe.logger().info(f"👨‍🎓 [Backend] Found {len(student_ids)} students in homeroom class ({step_times['1_homeroom_students']:.0f}ms)")
        
        if not student_ids:
            # No students, return empty structure
            result = {period: {"subject": None, "students": [], "source_class_id": homeroom_class_id, "is_homeroom_class": True} for period in periods}
            return success_response(data=result, message="No students found in homeroom class")
        
        # Step 2: Query SIS Student Timetable to find which class each student attends for each period
        # This tells us if a student is in a mixed class for a specific period
        step_start = time.time()
        
        # Helper function để extract period number từ period_name
        def extract_period_number(period_name):
            """Extract số đầu tiên từ tên tiết (VD: 'Tiết 1 + 2' -> 1, 'Tiết 11' -> 11)"""
            match = re.search(r'\d+', period_name or '')
            return int(match.group()) if match else None
        
        # Build map: period_number -> combined_period_name (request periods)
        # VD: "Tiết 1 + 2" -> period_numbers [1, 2] -> map 1 -> "Tiết 1 + 2", 2 -> "Tiết 1 + 2"
        period_number_to_combined = {}
        for period in periods:
            period_num = extract_period_number(period)
            if period_num:
                period_number_to_combined[period_num] = period
                # Nếu là combined period (VD: "Tiết 1 + 2"), cũng map period thứ 2
                # Extract all numbers từ period name
                all_nums = re.findall(r'\d+', period or '')
                for num_str in all_nums:
                    num = int(num_str)
                    if num not in period_number_to_combined:
                        period_number_to_combined[num] = period
        
        # Query SIS Student Timetable với LIKE '%tiết%' để lấy tất cả tiết học
        # Sau đó filter và map theo period_number
        student_timetable_entries = frappe.db.sql("""
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
            "date": date
        }, as_dict=True)
        step_times['2_student_timetable'] = (time.time() - step_start) * 1000
        
        frappe.logger().info(f"📋 [Backend] Found {len(student_timetable_entries)} student timetable entries ({step_times['2_student_timetable']:.0f}ms)")
        
        # Build mapping: (student_id, period) -> class_id
        # Map từ single period (VD: "Tiết 1") về combined period (VD: "Tiết 1 + 2")
        student_period_class = {}
        for entry in student_timetable_entries:
            # Extract period number từ entry
            entry_period_num = extract_period_number(entry['period_name'])
            if entry_period_num and entry_period_num in period_number_to_combined:
                # Map về combined period name từ request
                combined_period = period_number_to_combined[entry_period_num]
                key = (entry['student_id'], combined_period)
                # Chỉ set nếu chưa có (ưu tiên entry đầu tiên)
                if key not in student_period_class:
                    student_period_class[key] = entry['class_id']
        
        # ⚡ Step 2b: Fallback - Tìm mixed class qua SIS Class Attendance
        # Nếu SIS Student Timetable không có data (chỉ có homeroom), kiểm tra SIS Class Attendance
        # để xem student có attendance ở mixed class nào
        step_start_2b = time.time()
        
        # Tìm tất cả attendance của students hôm nay (ở bất kỳ class nào ngoài homeroom)
        mixed_attendance_entries = frappe.db.sql("""
            SELECT student_id, class_id, period
            FROM `tabSIS Class Attendance`
            WHERE date = %(date)s
                AND student_id IN %(student_ids)s
                AND class_id != %(homeroom_class_id)s
                AND LOWER(period) LIKE '%%tiết%%'
        """, {
            "date": date,
            "student_ids": student_ids,
            "homeroom_class_id": homeroom_class_id
        }, as_dict=True)
        
        # Map mixed class từ attendance vào student_period_class
        for entry in mixed_attendance_entries:
            entry_period_num = extract_period_number(entry['period'])
            if entry_period_num and entry_period_num in period_number_to_combined:
                combined_period = period_number_to_combined[entry_period_num]
                key = (entry['student_id'], combined_period)
                # Ưu tiên mixed class từ attendance (override homeroom nếu có)
                if key not in student_period_class or student_period_class[key] == homeroom_class_id:
                    student_period_class[key] = entry['class_id']
        
        step_times['2b_mixed_attendance'] = (time.time() - step_start_2b) * 1000
        frappe.logger().info(f"📋 [Backend] Found {len(mixed_attendance_entries)} mixed class attendance entries ({step_times['2b_mixed_attendance']:.0f}ms)")
        
        # ⚡ Step 2c: Tìm mixed class qua SIS Class Student
        # Nếu vẫn chưa tìm thấy mixed class, kiểm tra students thuộc class nào
        step_start_2c = time.time()
        
        # Tìm tất cả class mà students thuộc về (ngoài homeroom)
        mixed_class_students = frappe.db.sql("""
            SELECT cs.student_id, cs.class_id, c.title as class_title
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
            WHERE cs.student_id IN %(student_ids)s
                AND cs.class_id != %(homeroom_class_id)s
                AND c.class_type = 'mixed'
        """, {
            "student_ids": student_ids,
            "homeroom_class_id": homeroom_class_id
        }, as_dict=True)
        
        # Build map: student_id -> list of mixed classes
        student_mixed_classes = {}
        for entry in mixed_class_students:
            if entry['student_id'] not in student_mixed_classes:
                student_mixed_classes[entry['student_id']] = []
            student_mixed_classes[entry['student_id']].append(entry['class_id'])
        
        step_times['2c_mixed_class_student'] = (time.time() - step_start_2c) * 1000
        frappe.logger().info(f"📋 [Backend] Found {len(mixed_class_students)} mixed class student entries ({step_times['2c_mixed_class_student']:.0f}ms)")
        
        # Step 3: Determine which classes we need to query for each period
        period_class_students = {}  # period -> {class_id -> [student_ids]}
        all_classes_to_query = set()
        
        # QUAN TRỌNG: Luôn thêm homeroom class vào danh sách query
        # Vì attendance có thể được lưu ở homeroom class dù timetable nói học sinh học ở mixed class
        all_classes_to_query.add(homeroom_class_id)
        
        # ⚡ Thêm tất cả mixed classes mà students thuộc về
        # Điều này đảm bảo chúng ta query class log subjects từ mixed class
        for student_id, mixed_classes in student_mixed_classes.items():
            for mixed_class in mixed_classes:
                all_classes_to_query.add(mixed_class)
        
        for period in periods:
            period_class_students[period] = {}
            for student_id in student_ids:
                key = (student_id, period)
                actual_class = student_period_class.get(key, homeroom_class_id)
                all_classes_to_query.add(actual_class)
                
                if actual_class not in period_class_students[period]:
                    period_class_students[period][actual_class] = []
                period_class_students[period][actual_class].append(student_id)
        
        frappe.logger().info(f"🏫 [Backend] Will query {len(all_classes_to_query)} classes: {list(all_classes_to_query)}")
        
        # ⚡ Step 3b: Query tên lớp (class_title) cho tất cả các class
        class_titles = {}
        if all_classes_to_query:
            class_title_rows = frappe.db.sql("""
                SELECT name, title
                FROM `tabSIS Class`
                WHERE name IN %(class_ids)s
            """, {"class_ids": list(all_classes_to_query)}, as_dict=True)
            
            for row in class_title_rows:
                class_titles[row['name']] = row['title']
        
        # ⚡ Step 4: BATCH query timetable instances (single query instead of N queries)
        step_start = time.time()
        class_instances = {}
        if all_classes_to_query:
            instance_rows = frappe.db.sql("""
                SELECT class_id, name
                FROM `tabSIS Timetable Instance`
                WHERE class_id IN %(class_ids)s
                    AND start_date <= %(date)s
                    AND end_date >= %(date)s
            """, {
                "class_ids": list(all_classes_to_query),
                "date": date
            }, as_dict=True)
            
            for row in instance_rows:
                class_instances[row['class_id']] = row['name']
        step_times['4_timetable_instances'] = (time.time() - step_start) * 1000
        
        frappe.logger().info(f"📚 [Backend] Found {len(class_instances)} timetable instances ({step_times['4_timetable_instances']:.0f}ms)")
        
        # Step 5: Batch query all class log subjects for all classes and periods
        # Query với LIKE '%tiết%' để lấy tất cả, sau đó filter và map theo period_number
        step_start = time.time()
        all_subject_logs = []
        instance_ids = list(class_instances.values())
        
        if instance_ids:
            # Lấy dữ liệu class log subject (thêm recorded_by để tra môn học theo giáo viên)
            all_subject_logs = frappe.db.sql("""
                SELECT cls.name, cls.period, cls.class_id, cls.general_comment, cls.lesson_name, cls.lesson_score,
                    cls.is_practise_test, cls.homework_assignment, cls.timetable_instance_id, cls.recorded_by
                FROM `tabSIS Class Log Subject` cls
                WHERE cls.timetable_instance_id IN %(instance_ids)s
                    AND cls.log_date = %(date)s
                    AND LOWER(cls.period) LIKE '%%tiết%%'
            """, {
                "instance_ids": instance_ids,
                "date": date
            }, as_dict=True)
        
        # Build map: (class_id, period) -> subject_log
        # Map từ single period (VD: "Tiết 1") về combined period (VD: "Tiết 1 + 2") nếu cần
        subject_by_class_period = {}
        for log in all_subject_logs:
            log_period_num = extract_period_number(log['period'])
            
            # Nếu period trong log match exact với request periods -> dùng trực tiếp
            if log['period'] in periods:
                key = (log['class_id'], log['period'])
                subject_by_class_period[key] = log
            # Nếu không match exact nhưng period_number match -> map về combined period
            elif log_period_num and log_period_num in period_number_to_combined:
                combined_period = period_number_to_combined[log_period_num]
                key = (log['class_id'], combined_period)
                # Chỉ set nếu chưa có (ưu tiên entry đầu tiên)
                if key not in subject_by_class_period:
                    subject_by_class_period[key] = log
        step_times['5_class_log_subjects'] = (time.time() - step_start) * 1000
        
        frappe.logger().info(f"📝 [Backend] Found {len(all_subject_logs)} class log subjects ({step_times['5_class_log_subjects']:.0f}ms)")
        
        # ⭐ Step 5b: Lấy subject_title từ SIS Teacher Timetable theo người ghi (recorded_by)
        # Ưu tiên tra môn học theo đúng giáo viên đã ghi log (chính xác hơn tra theo lớp)
        # Vì nhiều GV khác nhau có thể ghi log cùng 1 tiết dưới cùng 1 lớp chủ nhiệm
        step_start = time.time()
        if all_subject_logs:
            recorded_bys = list({log.get('recorded_by') for log in all_subject_logs if log.get('recorded_by')})
            class_ids_for_teacher = list({log['class_id'] for log in all_subject_logs})

            teacher_timetable_rows = []
            if recorded_bys and class_ids_for_teacher:
                teacher_timetable_rows = frappe.db.sql("""
                    SELECT t.user_id as user_id, tt.class_id, tc.period_name, tc.period_priority,
                        COALESCE(ts.title_vn, ts.title_en, s.title) as subject_title
                    FROM `tabSIS Teacher Timetable` tt
                    INNER JOIN `tabSIS Teacher` t ON tt.teacher_id = t.name
                    INNER JOIN `tabSIS Timetable Column` tc ON tt.timetable_column_id = tc.name
                    LEFT JOIN `tabSIS Subject` s ON tt.subject_id = s.name
                    LEFT JOIN `tabSIS Timetable Subject` ts ON s.timetable_subject_id = ts.name
                    WHERE t.user_id IN %(user_ids)s
                        AND tt.class_id IN %(class_ids)s
                        AND tt.date = %(date)s
                        AND LOWER(tc.period_name) LIKE '%%tiết%%'
                """, {
                    "user_ids": recorded_bys,
                    "class_ids": class_ids_for_teacher,
                    "date": date
                }, as_dict=True)

            # Map (user_id, class_id, period_name/combined) -> subject_title
            teacher_subject_map = {}
            for row in teacher_timetable_rows:
                if not row.get('subject_title'):
                    continue
                key_exact = (row['user_id'], row['class_id'], row['period_name'])
                if key_exact not in teacher_subject_map:
                    teacher_subject_map[key_exact] = row['subject_title']
                # Cũng map theo period_priority -> combined period name
                p_priority = row.get('period_priority')
                if p_priority and p_priority in period_number_to_combined:
                    combined = period_number_to_combined[p_priority]
                    key_combined = (row['user_id'], row['class_id'], combined)
                    if key_combined not in teacher_subject_map:
                        teacher_subject_map[key_combined] = row['subject_title']

            # Gán subject_title từ teacher timetable (ưu tiên 1)
            for log in all_subject_logs:
                user_id = log.get('recorded_by')
                if not user_id:
                    continue
                key = (user_id, log['class_id'], log['period'])
                if key in teacher_subject_map:
                    log['subject_title'] = teacher_subject_map[key]
                    continue
                # Fallback: map period_number -> combined
                log_period_num = extract_period_number(log['period'])
                if log_period_num and log_period_num in period_number_to_combined:
                    combined_period = period_number_to_combined[log_period_num]
                    key2 = (user_id, log['class_id'], combined_period)
                    if key2 in teacher_subject_map:
                        log['subject_title'] = teacher_subject_map[key2]

            # Fallback (ưu tiên 2): SIS Timetable Instance Row cho các log chưa có subject_title
            # (khi recorded_by không phải là GV có trong SIS Teacher Timetable)
            logs_without_subject = [log for log in all_subject_logs if not log.get('subject_title')]
            if logs_without_subject and instance_ids:
                date_obj_5b = dt.strptime(date, "%Y-%m-%d")
                day_of_week_5b = date_obj_5b.strftime("%A").lower()[:3]

                sis_timetable_rows = frappe.db.sql("""
                    SELECT ti.class_id, tc.period_name, tc.period_priority,
                        COALESCE(ts.title_vn, ts.title_en, sub.title) as subject_title
                    FROM `tabSIS Timetable Instance Row` tir
                    INNER JOIN `tabSIS Timetable Instance` ti ON tir.parent = ti.name
                    INNER JOIN `tabSIS Timetable Column` tc ON tir.timetable_column_id = tc.name
                    INNER JOIN `tabSIS Subject` sub ON tir.subject_id = sub.name
                    LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
                    WHERE ti.name IN %(instance_ids)s
                        AND tir.day_of_week = %(day_of_week)s
                        AND tir.subject_id IS NOT NULL
                        AND LOWER(tc.period_name) LIKE '%%tiết%%'
                """, {"instance_ids": instance_ids, "day_of_week": day_of_week_5b}, as_dict=True)

                sis_subject_title_map = {}
                for row in sis_timetable_rows:
                    if not row.get('subject_title'):
                        continue
                    key_exact = (row['class_id'], row['period_name'])
                    if key_exact not in sis_subject_title_map:
                        sis_subject_title_map[key_exact] = row['subject_title']
                    p_priority = row.get('period_priority')
                    if p_priority and p_priority in period_number_to_combined:
                        combined = period_number_to_combined[p_priority]
                        key_combined = (row['class_id'], combined)
                        if key_combined not in sis_subject_title_map:
                            sis_subject_title_map[key_combined] = row['subject_title']

                for log in logs_without_subject:
                    key = (log['class_id'], log['period'])
                    if key in sis_subject_title_map:
                        log['subject_title'] = sis_subject_title_map[key]
                        continue
                    log_period_num = extract_period_number(log['period'])
                    if log_period_num and log_period_num in period_number_to_combined:
                        combined = period_number_to_combined[log_period_num]
                        key2 = (log['class_id'], combined)
                        if key2 in sis_subject_title_map:
                            log['subject_title'] = sis_subject_title_map[key2]

            frappe.logger().info(f"📚 [Backend] Enriched subject_title: teacher_map={len(teacher_timetable_rows)} entries, {len([l for l in all_subject_logs if l.get('subject_title')])} logs updated ({(time.time() - step_start)*1000:.0f}ms)")
        
        # Step 6: Batch query all student logs
        step_start = time.time()
        subject_ids = [log['name'] for log in all_subject_logs]
        all_student_logs = []
        
        if subject_ids:
            all_student_logs = frappe.db.sql("""
                SELECT 
                    subject_id,
                    student_id,
                    class_student_id,
                    homework,
                    behavior,
                    participation,
                    issues,
                    is_top_performance,
                    specific_comment
                FROM `tabSIS Class Log Student`
                WHERE subject_id IN %(subject_ids)s
            """, {"subject_ids": subject_ids}, as_dict=True)
        
        # Build map: subject_id -> {student_id -> student_log}
        students_by_subject = {}
        for student_log in all_student_logs:
            subject_id = student_log['subject_id']
            if subject_id not in students_by_subject:
                students_by_subject[subject_id] = {}
            students_by_subject[subject_id][student_log['student_id']] = student_log
        step_times['6_student_logs'] = (time.time() - step_start) * 1000
        
        frappe.logger().info(f"👥 [Backend] Found {len(all_student_logs)} student logs ({step_times['6_student_logs']:.0f}ms)")
        
        # Step 7: Batch query attendance data (both class and event attendance)
        step_start = time.time()
        
        # ⚡ Query all class attendance in single query
        # Dùng LIKE '%tiết%' để lấy tất cả tiết, sau đó map theo period_number
        class_attendance_records = frappe.db.sql("""
            SELECT student_id, period, status, class_id
            FROM `tabSIS Class Attendance`
            WHERE date = %(date)s
                AND student_id IN %(student_ids)s
                AND LOWER(period) LIKE '%%tiết%%'
                AND class_id IN %(class_ids)s
        """, {
            "date": date,
            "student_ids": student_ids,
            "class_ids": list(all_classes_to_query)
        }, as_dict=True)
        
        # Build map: (student_id, period) -> attendance status
        # Logic: Ưu tiên attendance từ expected_class (timetable), fallback về homeroom class
        # Lý do: Attendance có thể được lưu ở homeroom class dù timetable nói học sinh học ở mixed class
        class_attendance_map = {}
        homeroom_attendance_map = {}  # Fallback map cho homeroom class
        
        for record in class_attendance_records:
            # Map period từ attendance record về combined period từ request
            record_period_num = extract_period_number(record['period'])
            
            # Tìm combined period tương ứng
            mapped_period = record['period']  # Default: giữ nguyên
            if record['period'] in periods:
                mapped_period = record['period']
            elif record_period_num and record_period_num in period_number_to_combined:
                mapped_period = period_number_to_combined[record_period_num]
            else:
                continue  # Skip nếu không map được
            
            key = (record['student_id'], mapped_period)
            expected_class = student_period_class.get(key, homeroom_class_id)
            
            # Lưu attendance từ homeroom class vào fallback map
            if record['class_id'] == homeroom_class_id:
                if key not in homeroom_attendance_map:
                    homeroom_attendance_map[key] = record['status']
            
            # Nếu class_id match với expected_class, ưu tiên dùng
            if record['class_id'] == expected_class:
                if key not in class_attendance_map:
                    class_attendance_map[key] = record['status']
        
        # Merge: Dùng homeroom fallback nếu không có từ expected_class
        for key, status in homeroom_attendance_map.items():
            if key not in class_attendance_map:
                class_attendance_map[key] = status
        
        step_times['7a_class_attendance'] = (time.time() - step_start) * 1000
        frappe.logger().info(f"📊 [Backend] Loaded {len(class_attendance_map)} class attendance records ({step_times['7a_class_attendance']:.0f}ms)")
        
        # ⚡ Query event attendance with optimized single query
        step_start = time.time()
        event_attendance_map = {}
        try:
            # Get education_stage_id using SQL (faster than get_doc)
            edu_stage_result = frappe.db.sql("""
                SELECT eg.education_stage_id
                FROM `tabSIS Class` c
                INNER JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
                WHERE c.name = %(class_id)s
            """, {"class_id": homeroom_class_id}, as_dict=True)
            
            education_stage_id = edu_stage_result[0]['education_stage_id'] if edu_stage_result else None
            
            if education_stage_id:
                event_attendance_records = frappe.db.sql("""
                    SELECT student_id, period, status
                    FROM `tabSIS Event Attendance`
                    WHERE date = %(date)s
                        AND student_id IN %(student_ids)s
                        AND LOWER(period) LIKE '%%tiết%%'
                        AND education_stage_id = %(education_stage_id)s
                """, {
                    "date": date,
                    "student_ids": student_ids,
                    "education_stage_id": education_stage_id
                }, as_dict=True)
                
                for record in event_attendance_records:
                    # Map period từ event attendance về combined period từ request
                    record_period_num = extract_period_number(record['period'])
                    
                    mapped_period = record['period']
                    if record['period'] in periods:
                        mapped_period = record['period']
                    elif record_period_num and record_period_num in period_number_to_combined:
                        mapped_period = period_number_to_combined[record_period_num]
                    else:
                        continue
                    
                    key = (record['student_id'], mapped_period)
                    if key not in event_attendance_map:
                        event_attendance_map[key] = record['status']
                
                frappe.logger().info(f"🎪 [Backend] Found {len(event_attendance_records)} event attendance records")
        except Exception as e:
            frappe.logger().warning(f"⚠️ [Backend] Could not load event attendance: {str(e)}")
        
        step_times['7b_event_attendance'] = (time.time() - step_start) * 1000
        
        # ⚡ Step 7c: Build map (class_id, period) -> subject_title từ thời khóa biểu
        # Dùng SIS Timetable Instance Row (weekly pattern theo day_of_week)
        # Giống cách parent portal lấy thời khoá biểu, đã kiểm chứng chính xác
        step_start = time.time()
        timetable_subject_map = {}  # (class_id, period) -> subject_title
        if instance_ids:
            date_obj_7c = dt.strptime(date, "%Y-%m-%d")
            day_of_week_7c = date_obj_7c.strftime("%A").lower()[:3]

            timetable_instance_subjects = frappe.db.sql("""
                SELECT ti.class_id, tc.period_name, tc.period_priority,
                    COALESCE(ts.title_vn, ts.title_en, sub.title) as subject_title
                FROM `tabSIS Timetable Instance Row` tir
                INNER JOIN `tabSIS Timetable Instance` ti ON tir.parent = ti.name
                INNER JOIN `tabSIS Timetable Column` tc ON tir.timetable_column_id = tc.name
                INNER JOIN `tabSIS Subject` sub ON tir.subject_id = sub.name
                LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
                WHERE ti.name IN %(instance_ids)s
                    AND tir.day_of_week = %(day_of_week)s
                    AND tir.subject_id IS NOT NULL
                    AND LOWER(tc.period_name) LIKE '%%tiết%%'
            """, {
                "instance_ids": instance_ids,
                "day_of_week": day_of_week_7c
            }, as_dict=True)
            for row in timetable_instance_subjects:
                class_id = row.get('class_id')
                if not class_id:
                    continue
                period_name = row.get('period_name') or ''
                period_priority = row.get('period_priority')
                subject_title = row.get('subject_title')
                if not subject_title:
                    continue
                if period_name in periods:
                    key = (class_id, period_name)
                    if key not in timetable_subject_map:
                        timetable_subject_map[key] = subject_title
                if period_priority is not None and period_priority in period_number_to_combined:
                    combined = period_number_to_combined[period_priority]
                    key = (class_id, combined)
                    if key not in timetable_subject_map:
                        timetable_subject_map[key] = subject_title
        step_times['7c_timetable_subjects'] = (time.time() - step_start) * 1000
        frappe.logger().info(f"📚 [Backend] Built timetable_subject_map with {len(timetable_subject_map)} entries from Timetable Instance Row ({step_times['7c_timetable_subjects']:.0f}ms)")
        
        # Step 8: Build result for each period
        step_start = time.time()
        result = {}
        
        for period in periods:
            classes_for_period = period_class_students.get(period, {})
            
            period_student_logs = []
            source_classes = set()
            primary_subject = None
            students_with_logs = set()  # Track students đã có log để không duplicate
            
            # ⚡ STEP 8a: Tìm subject_log từ homeroom class trước
            homeroom_subject_key = (homeroom_class_id, period)
            homeroom_subject_log = subject_by_class_period.get(homeroom_subject_key)
            
            if homeroom_subject_log:
                primary_subject = homeroom_subject_log
                source_classes.add(homeroom_class_id)
            
            # ⚡ STEP 8b: Tìm subject_log từ mixed class
            # Kiểm tra tất cả mixed class mà students thuộc về
            mixed_subject_logs = {}  # class_id -> subject_log
            for student_id in student_ids:
                mixed_classes = student_mixed_classes.get(student_id, [])
                for mixed_class_id in mixed_classes:
                    if mixed_class_id not in mixed_subject_logs:
                        mixed_key = (mixed_class_id, period)
                        mixed_log = subject_by_class_period.get(mixed_key)
                        if mixed_log:
                            mixed_subject_logs[mixed_class_id] = mixed_log
                            source_classes.add(mixed_class_id)
                            # Nếu chưa có primary_subject, dùng mixed class
                            if primary_subject is None:
                                primary_subject = mixed_log
            
            # ⚡ STEP 8c: Build student logs - ưu tiên data từ mixed class
            for student_id in student_ids:
                attendance_key = (student_id, period)
                class_attendance_status = class_attendance_map.get(attendance_key)
                event_attendance_status = event_attendance_map.get(attendance_key)
                final_attendance = event_attendance_status or class_attendance_status
                
                student_log_found = False
                
                # Kiểm tra mixed class trước (ưu tiên cao hơn homeroom)
                mixed_classes = student_mixed_classes.get(student_id, [])
                for mixed_class_id in mixed_classes:
                    mixed_log = mixed_subject_logs.get(mixed_class_id)
                    if mixed_log:
                        subject_student_logs = students_by_subject.get(mixed_log['name'], {})
                        if student_id in subject_student_logs:
                            student_log = subject_student_logs[student_id].copy()
                            student_log['attendance'] = final_attendance
                            period_student_logs.append(student_log)
                            students_with_logs.add(student_id)
                            student_log_found = True
                            break
                
                if student_log_found:
                    continue
                
                # Fallback: Kiểm tra homeroom class
                if homeroom_subject_log:
                    subject_student_logs = students_by_subject.get(homeroom_subject_log['name'], {})
                    if student_id in subject_student_logs:
                        student_log = subject_student_logs[student_id].copy()
                        student_log['attendance'] = final_attendance
                        period_student_logs.append(student_log)
                        students_with_logs.add(student_id)
                        continue
                
                # No log found - add basic info
                period_student_logs.append({
                    "student_id": student_id,
                    "class_student_id": student_to_class_student.get(student_id),
                    "attendance": final_attendance
                })
            
            # Determine primary class
            primary_class = homeroom_class_id
            if mixed_subject_logs:
                # Nếu có subject_log từ mixed class, dùng mixed class đầu tiên
                primary_class = list(mixed_subject_logs.keys())[0]
            
            # ⭐ Build all_subjects - thông tin chi tiết của tất cả các lớp (homeroom + mixed)
            all_subjects = []
            
            # Thêm homeroom class subject nếu có
            # subject_title từ Step 5b, fallback sang timetable_subject_map nếu null
            if homeroom_subject_log:
                homeroom_subj_title = homeroom_subject_log.get('subject_title') or timetable_subject_map.get((homeroom_subject_log['class_id'], period))
                all_subjects.append({
                    "name": homeroom_subject_log['name'],
                    "subject_title": homeroom_subj_title,
                    "class_id": homeroom_subject_log['class_id'],
                    "class_title": class_titles.get(homeroom_subject_log['class_id'], homeroom_subject_log['class_id']),
                    "general_comment": homeroom_subject_log.get('general_comment'),
                    "lesson_name": homeroom_subject_log.get('lesson_name'),
                    "lesson_score": homeroom_subject_log.get('lesson_score'),
                    "is_practise_test": homeroom_subject_log.get('is_practise_test'),
                    "homework_assignment": homeroom_subject_log.get('homework_assignment'),
                    "is_homeroom": True
                })
            
            # Thêm mixed class subjects
            # subject_title từ Step 5b, fallback sang timetable_subject_map nếu null
            for mixed_class_id, mixed_log in mixed_subject_logs.items():
                mixed_subj_title = mixed_log.get('subject_title') or timetable_subject_map.get((mixed_log['class_id'], period))
                all_subjects.append({
                    "name": mixed_log['name'],
                    "subject_title": mixed_subj_title,
                    "class_id": mixed_log['class_id'],
                    "class_title": class_titles.get(mixed_log['class_id'], mixed_log['class_id']),
                    "general_comment": mixed_log.get('general_comment'),
                    "lesson_name": mixed_log.get('lesson_name'),
                    "lesson_score": mixed_log.get('lesson_score'),
                    "is_practise_test": mixed_log.get('is_practise_test'),
                    "homework_assignment": mixed_log.get('homework_assignment'),
                    "is_homeroom": False
                })
            
            # ⭐ Khi chưa có sổ đầu bài: thêm placeholder với subject_title từ thời khóa biểu
            if not all_subjects:
                subject_from_timetable = None
                # Ưu tiên homeroom class, sau đó thử class có học sinh trong tiết này
                for cid in [homeroom_class_id] + list(classes_for_period.keys()):
                    subject_from_timetable = timetable_subject_map.get((cid, period))
                    if subject_from_timetable:
                        all_subjects.append({
                            "name": None,
                            "subject_title": subject_from_timetable,
                            "class_id": cid,
                            "class_title": class_titles.get(cid, cid),
                            "general_comment": None,
                            "lesson_name": None,
                            "lesson_score": None,
                            "is_practise_test": 0,
                            "homework_assignment": None,
                            "is_homeroom": (cid == homeroom_class_id)
                        })
                        break
            
            # subject_title cho subject chính: ưu tiên Step 5b, fallback timetable_subject_map
            primary_subj_title = None
            if primary_subject:
                primary_subj_title = primary_subject.get('subject_title') or timetable_subject_map.get((primary_subject['class_id'], period))
            
            result[period] = {
                "subject": {
                    "name": primary_subject['name'] if primary_subject else None,
                    "timetable_instance_id": primary_subject['timetable_instance_id'] if primary_subject else class_instances.get(homeroom_class_id),
                    "class_id": primary_subject['class_id'] if primary_subject else homeroom_class_id,
                    "subject_title": primary_subj_title,
                    "general_comment": primary_subject.get('general_comment') if primary_subject else None,
                    "lesson_name": primary_subject.get('lesson_name') if primary_subject else None,
                    "lesson_score": primary_subject.get('lesson_score') if primary_subject else None,
                    "is_practise_test": primary_subject.get('is_practise_test') if primary_subject else 0,
                    "homework_assignment": primary_subject.get('homework_assignment') if primary_subject else None
                } if primary_subject else None,
                "all_subjects": all_subjects,  # ⭐ Thông tin chi tiết của tất cả các lớp
                "students": period_student_logs,
                "source_class_id": primary_subject['class_id'] if primary_subject else homeroom_class_id,
                "source_classes": list(source_classes),
                "is_homeroom_class": (primary_subject['class_id'] if primary_subject else homeroom_class_id) == homeroom_class_id
            }
        
        step_times['8_build_result'] = (time.time() - step_start) * 1000
        
        total_time = (time.time() - total_start) * 1000
        frappe.logger().info(f"✅ [Backend] Returning aggregated logs for {len(result)} periods")
        frappe.logger().info(f"⚡ [Backend] TOTAL API TIME: {total_time:.0f}ms")
        frappe.logger().info(f"⏱️ [Backend] Step times: {step_times}")
        
        meta = {
            "homeroom_class_id": homeroom_class_id,
            "homeroom_class_title": class_titles.get(homeroom_class_id, homeroom_class_id),  # ⭐ Tên lớp chủ nhiệm
            "student_count": len(student_ids),
            "classes_queried": list(all_classes_to_query),
            "performance_ms": int(total_time),
            "step_times_ms": step_times  # ⏱️ Detailed profiling for debugging
        }
        
        # ⚡ CACHE: Store result in Redis (2 min = 120 sec)
        # Short TTL because this endpoint aggregates data from multiple sources:
        # - Class logs (invalidated on save_class_log)
        # - Class attendance (changes frequently)
        # - Event attendance (changes frequently)
        # - Student timetable (rarely changes but not tracked)
        # Short TTL ensures data freshness without complex invalidation logic
        try:
            frappe.cache().set_value(cache_key, {"data": result, "meta": meta}, expires_in_sec=120)
            frappe.logger().info(f"✅ Cached homeroom_class_logs for {homeroom_class_id}/{date} (TTL=2min)")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache write failed: {cache_error}")
        
        return success_response(
            data=result,
            message=f"Fetched homeroom class logs for {len(periods)} periods",
            meta=meta
        )
        
    except Exception as e:
        frappe.logger().error(f"❌ [Backend] batch_get_homeroom_class_logs error: {str(e)}")
        import traceback
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")
        frappe.log_error(f"batch_get_homeroom_class_logs error: {str(e)}", "Batch Get Homeroom Class Logs Error")
        return error_response(
            message=f"Failed to fetch homeroom class logs: {str(e)}",
            code="BATCH_GET_HOMEROOM_CLASS_LOGS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_student_classlog_summary(student_id=None, class_id=None, date=None):
    """
    Lấy tổng hợp dữ liệu class log của 1 học sinh trong 1 ngày,
    dùng để gửi cho AI Agent tạo nhận xét sổ liên lạc.
    
    GET params:
    - student_id: ID học sinh (CRM Student name)
    - class_id: ID lớp chủ nhiệm (homeroom class)
    - date: Ngày cần lấy (YYYY-MM-DD)
    
    Returns:
    {
        "student_name": "Nguyen Van A",
        "date": "2026-03-10",
        "comments": [
            {
                "period": "Tiết 1",
                "subject": "Toán",
                "homework": "Hoàn thành đầy đủ",
                "behavior": "Tốt",
                "participation": "Tích cực",
                "issues": null,
                "specific_comment": "Hiểu bài nhanh",
                "general_comment": "Lớp học tập trung",
                "homework_assignment": "Bài tập trang 45"
            }
        ]
    }
    """
    try:
        # Lấy params từ GET request
        if not student_id and getattr(frappe, 'request', None):
            student_id = frappe.request.args.get('student_id')
        if not class_id and getattr(frappe, 'request', None):
            class_id = frappe.request.args.get('class_id')
        if not date and getattr(frappe, 'request', None):
            date = frappe.request.args.get('date')

        include_empty_periods = (
            frappe.request.args.get('include_empty_periods') == '1'
            if getattr(frappe, 'request', None) else False
        )

        if not student_id or not class_id or not date:
            return error_response(
                message="Missing required parameters: student_id, class_id, date",
                code="MISSING_PARAMS"
            )

        frappe.logger().info(f"🤖 [AI Summary] get_student_classlog_summary: student={student_id}, class={class_id}, date={date}")

        # ⚡ CACHE: TTL ngắn (90 giây) vì class log thay đổi thường xuyên
        # v3: fix resolve subject từ Timetable Instance Row + ưu tiên mixed class
        cache_key = f"student_classlog_summary_v3:{student_id}:{class_id}:{date}"
        try:
            cached = frappe.cache().get_value(cache_key)
            if cached:
                frappe.logger().info(f"✅ Cache HIT student_classlog_summary {student_id}/{date}")
                return success_response(data=cached, message="Student classlog summary (cached)")
        except Exception:
            pass

        # Lấy tên học sinh
        student_name = frappe.db.get_value("CRM Student", student_id, "student_name") or student_id

        # Lấy timetable instance của class trong ngày
        instance_rows = frappe.db.sql("""
            SELECT name, class_id
            FROM `tabSIS Timetable Instance`
            WHERE class_id = %(class_id)s
                AND start_date <= %(date)s
                AND end_date >= %(date)s
            LIMIT 1
        """, {"class_id": class_id, "date": date}, as_dict=True)

        homeroom_instance_id = instance_rows[0]['name'] if instance_rows else None

        # Tìm mixed class mà học sinh có thể đang học
        mixed_class_rows = frappe.db.sql("""
            SELECT cs.class_id, c.title as class_title
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
            WHERE cs.student_id = %(student_id)s
                AND cs.class_id != %(class_id)s
                AND c.class_type = 'mixed'
        """, {"student_id": student_id, "class_id": class_id}, as_dict=True)

        mixed_class_ids = [r['class_id'] for r in mixed_class_rows]
        mixed_class_title_map = {r['class_id']: r['class_title'] for r in mixed_class_rows}

        # Lấy timetable instances của tất cả mixed class
        all_instance_ids = [homeroom_instance_id] if homeroom_instance_id else []
        all_class_ids = [class_id] + mixed_class_ids

        if mixed_class_ids:
            mixed_instances = frappe.db.sql("""
                SELECT name, class_id
                FROM `tabSIS Timetable Instance`
                WHERE class_id IN %(class_ids)s
                    AND start_date <= %(date)s
                    AND end_date >= %(date)s
            """, {"class_ids": mixed_class_ids, "date": date}, as_dict=True)
            for mi in mixed_instances:
                if mi['name'] not in all_instance_ids:
                    all_instance_ids.append(mi['name'])

        if not all_instance_ids:
            return success_response(
                data={"student_name": student_name, "date": date, "comments": []},
                message="No timetable instance found for this class and date"
            )

        # Lấy tất cả class log subjects của các timetable instance trong ngày (chỉ tiết học)
        subject_logs = frappe.db.sql("""
            SELECT 
                cls.name as subject_id,
                cls.period,
                cls.class_id,
                cls.general_comment,
                cls.lesson_name,
                cls.lesson_score,
                cls.is_practise_test,
                cls.homework_assignment,
                cls.timetable_instance_id
            FROM `tabSIS Class Log Subject` cls
            WHERE cls.timetable_instance_id IN %(instance_ids)s
                AND cls.log_date = %(date)s
                AND LOWER(cls.period) LIKE '%%tiết%%'
            ORDER BY cls.period ASC
        """, {"instance_ids": all_instance_ids, "date": date}, as_dict=True)

        if not subject_logs:
            return success_response(
                data={"student_name": student_name, "date": date, "comments": []},
                message="No class log found for this date"
            )

        subject_ids = [sl['subject_id'] for sl in subject_logs]

        # Lấy dữ liệu học sinh cho tất cả tiết (chỉ của student_id này)
        student_logs = frappe.db.sql("""
            SELECT 
                subject_id,
                homework,
                behavior,
                participation,
                issues,
                specific_comment,
                is_top_performance
            FROM `tabSIS Class Log Student`
            WHERE subject_id IN %(subject_ids)s
                AND student_id = %(student_id)s
        """, {"subject_ids": subject_ids, "student_id": student_id}, as_dict=True)

        # Map subject_id -> student_log để lookup O(1)
        student_log_by_subject = {sl['subject_id']: sl for sl in student_logs}

        # Lấy tên môn học từ SIS Timetable Instance Row (weekly pattern theo day_of_week)
        # Giống cách parent portal (_get_class_timetable_for_date) lấy thời khoá biểu,
        # đã kiểm chứng hoạt động chính xác (SIS Student Timetable có thể bị lệch dữ liệu)
        date_obj = dt.strptime(date, "%Y-%m-%d")
        day_of_week = date_obj.strftime("%A").lower()[:3]  # "mon", "tue", "wed", etc.

        instance_row_subjects = frappe.db.sql("""
            SELECT 
                ti.class_id,
                tc.period_name,
                tc.period_priority,
                sub.title as subject_title
            FROM `tabSIS Timetable Instance Row` tir
            INNER JOIN `tabSIS Timetable Instance` ti ON tir.parent = ti.name
            INNER JOIN `tabSIS Timetable Column` tc ON tir.timetable_column_id = tc.name
            INNER JOIN `tabSIS Subject` sub ON tir.subject_id = sub.name
            WHERE ti.name IN %(instance_ids)s
                AND tir.day_of_week = %(day_of_week)s
                AND tir.subject_id IS NOT NULL
                AND LOWER(tc.period_name) LIKE '%%tiết%%'
        """, {
            "instance_ids": all_instance_ids,
            "day_of_week": day_of_week
        }, as_dict=True)

        # Map: (period, class_id) -> subject_title để match đúng môn theo từng lớp
        period_class_subject_map = {}
        for entry in instance_row_subjects:
            period = entry['period_name']
            class_id_val = entry['class_id']
            if not entry.get('subject_title'):
                continue
            key = (period, class_id_val)
            if key not in period_class_subject_map:
                period_class_subject_map[key] = entry['subject_title']

        # Xác định lớp thực tế và môn đúng cho từng tiết
        # Mixed class ưu tiên hơn homeroom (học sinh enrolled mixed sẽ học ở đó)
        period_correct_subject = {}
        for (period, cid), subj in period_class_subject_map.items():
            if cid in mixed_class_ids:
                period_correct_subject[period] = subj
            elif period not in period_correct_subject:
                period_correct_subject[period] = subj

        frappe.logger().info(f"🤖 [AI Summary] period_class_subject_map: {period_class_subject_map}")
        frappe.logger().info(f"🤖 [AI Summary] period_correct_subject: {period_correct_subject}")
        frappe.logger().info(f"🤖 [AI Summary] mixed_class_ids: {mixed_class_ids}")

        # Lấy tất cả score names cần resolve (homework/behavior/participation + issues)
        score_names = set()
        for sl in student_logs:
            if sl.get('homework'):
                score_names.add(sl['homework'])
            if sl.get('behavior'):
                score_names.add(sl['behavior'])
            if sl.get('participation'):
                score_names.add(sl['participation'])
            # issues là comma-separated score names
            if sl.get('issues'):
                for issue_name in sl['issues'].split(','):
                    issue_name = issue_name.strip()
                    if issue_name:
                        score_names.add(issue_name)

        # Resolve score name -> title_vn, color bằng 1 query (để FE hiển thị badge màu)
        score_map = {}
        score_color_map = {}
        if score_names:
            score_rows = frappe.db.sql("""
                SELECT name, title_vn, color
                FROM `tabSIS Class Log Score`
                WHERE name IN %(names)s
            """, {"names": list(score_names)}, as_dict=True)
            score_map = {r['name']: r['title_vn'] for r in score_rows}
            score_color_map = {r['name']: (r.get('color') or '#F6F6F6') for r in score_rows}

        # Lấy tên lớp homeroom để dùng làm fallback
        homeroom_class_title = frappe.db.get_value("SIS Class", class_id, "title") or class_id

        # Tổng hợp dữ liệu theo từng tiết
        comments = []
        for subject_log in subject_logs:
            subject_id = subject_log['subject_id']
            student_log = student_log_by_subject.get(subject_id)
            period_name = subject_log['period']

            # Luôn dùng môn từ lớp học sinh thực sự học (mixed ưu tiên hơn homeroom)
            subject_title = period_correct_subject.get(period_name)
            if not subject_title:
                subject_title = period_class_subject_map.get((period_name, subject_log['class_id']))
            if not subject_title:
                if subject_log['class_id'] != class_id:
                    subject_title = mixed_class_title_map.get(subject_log['class_id'], subject_log['class_id'])
                else:
                    subject_title = homeroom_class_title

            # Resolve issues: comma-separated score names -> list {title, color} cho badge
            issues_list = []
            if student_log and student_log.get('issues'):
                for issue_name in student_log['issues'].split(','):
                    issue_name = issue_name.strip()
                    if issue_name:
                        issues_list.append({
                            "title": score_map.get(issue_name, issue_name),
                            "color": score_color_map.get(issue_name, '#F6F6F6')
                        })

            homework_val = score_map.get(student_log['homework']) if student_log and student_log.get('homework') else None
            behavior_val = score_map.get(student_log['behavior']) if student_log and student_log.get('behavior') else None
            participation_val = score_map.get(student_log['participation']) if student_log and student_log.get('participation') else None

            comment_item = {
                "period": period_name,
                "subject": subject_title,
                "general_comment": subject_log.get('general_comment') or None,
                "is_practise_test": subject_log.get('is_practise_test'),
                "homework_assignment": subject_log.get('homework_assignment') or None,
                "homework": homework_val,
                "homework_color": score_color_map.get(student_log['homework']) if student_log and student_log.get('homework') else None,
                "behavior": behavior_val,
                "behavior_color": score_color_map.get(student_log['behavior']) if student_log and student_log.get('behavior') else None,
                "participation": participation_val,
                "participation_color": score_color_map.get(student_log['participation']) if student_log and student_log.get('participation') else None,
                "issues": ', '.join([i['title'] for i in issues_list]) if issues_list else None,
                "issues_list": issues_list,
                "specific_comment": student_log.get('specific_comment') or None if student_log else None,
                "is_top_performance": 1 if (student_log and student_log.get('is_top_performance')) else 0,
            }

            has_data = any([
                comment_item['homework'],
                comment_item['behavior'],
                comment_item['participation'],
                comment_item['issues'],
                comment_item['specific_comment'],
                comment_item['general_comment'],
                comment_item['is_top_performance'],
            ])

            if has_data or include_empty_periods:
                comments.append(comment_item)

        # Loại bỏ trùng lặp tiết: giữ entry có nhiều dữ liệu học sinh nhất
        unique_comments = {}
        for comment in comments:
            period = comment['period']
            student_fields = ['homework', 'behavior', 'participation', 'issues', 'specific_comment']
            student_data_count = sum(1 for k in student_fields if comment.get(k))
            if period not in unique_comments:
                unique_comments[period] = (comment, student_data_count)
            else:
                _, existing_count = unique_comments[period]
                if student_data_count > existing_count:
                    unique_comments[period] = (comment, student_data_count)
        comments = [v[0] for v in sorted(unique_comments.values(), key=lambda x: x[0]['period'])]

        # Lấy danh sách tên đầy đủ tất cả học sinh trong lớp để AI phân biệt tên viết tắt
        all_student_names = []
        try:
            class_students = frappe.db.sql("""
                SELECT s.student_name
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
                WHERE cs.class_id = %(class_id)s
                ORDER BY s.student_name
            """, {"class_id": class_id}, as_dict=True)
            all_student_names = [r['student_name'] for r in class_students if r.get('student_name')]
        except Exception:
            pass

        result = {
            "student_name": student_name,
            "date": date,
            "comments": comments,
            "all_student_names": all_student_names
        }

        # Cache 90 giây
        try:
            frappe.cache().set_value(cache_key, result, expires_in_sec=90)
        except Exception:
            pass

        frappe.logger().info(f"✅ [AI Summary] Returning {len(comments)} period comments for student {student_name}")
        return success_response(
            data=result,
            message=f"Fetched classlog summary for {student_name} on {date}",
            meta={"period_count": len(comments)}
        )

    except Exception as e:
        frappe.logger().error(f"❌ [AI Summary] get_student_classlog_summary error: {str(e)}")
        import traceback
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")
        return error_response(
            message=f"Failed to fetch student classlog summary: {str(e)}",
            code="GET_STUDENT_CLASSLOG_SUMMARY_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_wis_academic_scores(class_id=None, date_from=None, date_to=None):
    """
    Tính WIS Study Point (điểm học tập) cho tất cả học sinh trong lớp theo khoảng ngày.

    Công thức: Score = (h / b × 100) × (c / p)^n
    - h = tổng lesson_score (homework + behavior + participation + top_performance + attendance_penalty)
    - b = max_lesson_score × p
    - p = số tiết kế hoạch từ thời khóa biểu, trừ tiết đánh dấu is_practise_test=1
    - c = số tiết tham gia (present + late + excused)
    - n = 0.7

    Quy tắc:
    - p lấy từ SIS Timetable Instance Row, không phụ thuộc giáo viên có nhập sổ đầu bài hay không
    - p chỉ giảm khi giáo viên vào class log và đánh dấu tiết đó là kiểm tra/nghỉ (is_practise_test=1)
    - Ngày nghỉ lễ (SIS Calendar type=holiday) bị bỏ qua
    - Nếu tất cả tiết trong ngày đều is_practise_test=1 thì p=0, ngày đó không tính vào days_with_data
    - Tiết không có class log: dùng default values cho h, lesson_score=0 cho Điểm lớp

    GET params: class_id, date_from, date_to (YYYY-MM-DD)
    Thêm include_detail=1 để xem các điểm thành phần (h, b, p, c, base_score, attendance_factor) đối chiếu công thức.
    """
    try:
        if getattr(frappe, 'request', None):
            class_id = class_id or frappe.request.args.get('class_id')
            date_from = date_from or frappe.request.args.get('date_from')
            date_to = date_to or frappe.request.args.get('date_to')

        include_detail = False
        if getattr(frappe, 'request', None):
            include_detail = frappe.request.args.get('include_detail') in ("1", "true", "yes")

        if not class_id or not date_from or not date_to:
            return error_response(
                message="Missing required parameters: class_id, date_from, date_to",
                code="MISSING_PARAMS"
            )

        # Kiểm tra cache (TTL 5 phút) - bỏ qua khi include_detail để không cache dữ liệu debug
        cache_key = f"wis_academic_scores:{class_id}:{date_from}:{date_to}"
        if not include_detail:
            try:
                cached = frappe.cache().get_value(cache_key)
                if cached:
                    return success_response(data=cached, message="WIS academic scores (cached)")
            except Exception:
                pass

        # Lấy education_stage, campus của lớp để filter score options và ngày nghỉ
        class_doc = frappe.db.get_value(
            "SIS Class", class_id,
            ["education_grade", "name", "campus_id"],
            as_dict=True
        )
        if not class_doc:
            return error_response(message="Class not found", code="CLASS_NOT_FOUND")

        education_stage = None
        if class_doc.get("education_grade"):
            education_stage = frappe.db.get_value("SIS Education Grade", class_doc["education_grade"], "education_stage_id")

        # Bước 1: Lấy score options và xây dựng map
        score_filters = {"is_active": 1}
        if education_stage:
            score_filters["education_stage"] = education_stage

        score_rows = frappe.get_all(
            "SIS Class Log Score",
            filters=score_filters,
            fields=["name", "type", "value", "is_default"]
        )

        score_value_map = {}
        default_values = {"homework": 0, "behavior": 0, "participation": 0, "top_performance": 0}
        max_by_type = {"homework": 0, "behavior": 0, "participation": 0}

        for r in score_rows:
            name = r.get("name")
            t = (r.get("type") or "").lower()
            val = float(r.get("value") or 0)
            score_value_map[name] = val

            if t in default_values and r.get("is_default"):
                default_values[t] = val
            if t in max_by_type and val > max_by_type[t]:
                max_by_type[t] = val

        max_lesson_score = max_by_type["homework"] + max_by_type["behavior"] + max_by_type["participation"]
        if max_lesson_score <= 0:
            max_lesson_score = 15

        def _get_score_value(score_name):
            """Lấy value từ score_name, fallback DB nếu không có trong map (do filter education_stage)."""
            if not score_name:
                return None
            if score_name in score_value_map:
                return score_value_map[score_name]
            val = frappe.db.get_value("SIS Class Log Score", score_name, "value")
            return float(val) if val is not None else None

        # Attendance penalty mapping (wis-point.md Section 2.3)
        ATTENDANCE_PENALTY = {"present": 0, "late": -1, "excused": 0, "absent": -3}
        N = 0.7

        # Lấy danh sách học sinh homeroom
        homeroom_students = frappe.get_all(
            "SIS Class Student",
            filters={"class_id": class_id},
            fields=["student_id"]
        )
        student_ids = [s["student_id"] for s in homeroom_students if s.get("student_id")]

        if not student_ids:
            result = {"scores": {}, "class_score": None, "config": {"n": N, "max_lesson_score": max_lesson_score}}
            try:
                frappe.cache().set_value(cache_key, result, expires_in_sec=300)
            except Exception:
                pass
            return success_response(data=result, message="No students in class")

        # Lấy mixed classes
        mixed_rows = frappe.db.sql("""
            SELECT cs.student_id, cs.class_id
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
            WHERE cs.student_id IN %(student_ids)s
                AND cs.class_id != %(class_id)s
                AND c.class_type = 'mixed'
        """, {"student_ids": student_ids, "class_id": class_id}, as_dict=True)

        student_mixed_classes = {}
        all_class_ids = {class_id}
        for row in mixed_rows:
            if row["student_id"] not in student_mixed_classes:
                student_mixed_classes[row["student_id"]] = []
            student_mixed_classes[row["student_id"]].append(row["class_id"])
            all_class_ids.add(row["class_id"])

        # education_stage_id cho event attendance
        edu_stage_id = None
        if education_stage:
            edu_stage_id = education_stage
        else:
            eg_row = frappe.db.sql("""
                SELECT eg.education_stage_id FROM `tabSIS Class` c
                INNER JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
                WHERE c.name = %(class_id)s
            """, {"class_id": class_id}, as_dict=True)
            if eg_row:
                edu_stage_id = eg_row[0]["education_stage_id"]

        def _extract_period_num(period_name):
            match = re.search(r"\d+", period_name or "")
            return int(match.group()) if match else None

        # Tích lũy điểm theo student: { student_id: [daily_scores] }
        student_daily_scores = {sid: [] for sid in student_ids}
        # Tích lũy Điểm lớp: [lesson_scores] theo từng tiết trong khoảng
        class_daily_scores = []
        # Chi tiết để đối chiếu công thức (khi include_detail=true)
        student_daily_details = {sid: [] for sid in student_ids}
        class_daily_details = []

        # Bước 1: Lấy danh sách ngày nghỉ lễ (SIS Calendar type=holiday)
        date_from_obj = dt.strptime(date_from, "%Y-%m-%d").date()
        date_to_obj = dt.strptime(date_to, "%Y-%m-%d").date()
        holiday_dates = set()
        cal_filters = {
            "type": "holiday",
            "start_date": ["<=", date_to],
            "end_date": [">=", date_from],
        }
        if class_doc.get("campus_id"):
            cal_filters["campus_id"] = class_doc["campus_id"]
        holidays = frappe.get_all(
            "SIS Calendar", filters=cal_filters, fields=["start_date", "end_date"]
        )
        for h in holidays:
            d = h["start_date"]
            while d <= h["end_date"]:
                if date_from_obj <= d <= date_to_obj:
                    holiday_dates.add(d.strftime("%Y-%m-%d"))
                d += timedelta(days=1)

        # Lặp từng ngày trong khoảng
        current = date_from_obj
        end = date_to_obj

        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            # Bỏ qua ngày nghỉ lễ
            if date_str in holiday_dates:
                current += timedelta(days=1)
                continue

            day_of_week = current.strftime("%A").lower()[:3]

            # Lấy timetable instances cho tất cả class
            instance_rows = frappe.db.sql("""
                SELECT class_id, name
                FROM `tabSIS Timetable Instance`
                WHERE class_id IN %(class_ids)s
                    AND start_date <= %(date)s
                    AND end_date >= %(date)s
            """, {"class_ids": list(all_class_ids), "date": date_str}, as_dict=True)

            class_instances = {r["class_id"]: r["name"] for r in instance_rows}
            instance_ids = list(class_instances.values())

            if not instance_ids:
                current += timedelta(days=1)
                continue

            # Bước 2: Lấy p từ thời khóa biểu (SIS Timetable Instance Row), không phụ thuộc class log
            timetable_periods = frappe.db.sql("""
                SELECT tir.period_name
                FROM `tabSIS Timetable Instance Row` tir
                WHERE tir.parent IN %(instance_ids)s
                    AND tir.day_of_week = %(dow)s
                    AND LOWER(COALESCE(tir.period_name, '')) LIKE '%%tiết%%'
                    AND (tir.valid_from IS NULL OR tir.valid_from <= %(date)s)
                    AND (tir.valid_to IS NULL OR tir.valid_to >= %(date)s)
            """, {"instance_ids": instance_ids, "dow": day_of_week, "date": date_str}, as_dict=True)

            timetable_period_set = {r["period_name"] for r in timetable_periods if r.get("period_name")}
            if not timetable_period_set:
                current += timedelta(days=1)
                continue

            # Lấy class log subjects (tất cả, kể cả is_practise_test) để biết tiết nào đánh dấu kiểm tra/nghỉ
            subject_logs = frappe.db.sql("""
                SELECT cls.name, cls.period, cls.class_id, cls.lesson_score, cls.is_practise_test
                FROM `tabSIS Class Log Subject` cls
                WHERE cls.timetable_instance_id IN %(instance_ids)s
                    AND cls.log_date = %(date)s
                    AND LOWER(cls.period) LIKE '%%tiết%%'
            """, {"instance_ids": instance_ids, "date": date_str}, as_dict=True)

            # Trừ tiết bị đánh dấu is_practise_test = 1
            excluded_periods = set()
            for sl in subject_logs:
                if sl.get("is_practise_test"):
                    period_val = sl.get("period") or ""
                    if period_val in timetable_period_set:
                        excluded_periods.add(period_val)
                    else:
                        pnum = _extract_period_num(period_val)
                        if pnum is not None:
                            for pn in timetable_period_set:
                                if _extract_period_num(pn) == pnum:
                                    excluded_periods.add(pn)
                                    break

            period_set = timetable_period_set - excluded_periods
            p = len(period_set)

            # Bước 2b: Nếu tất cả tiết đều kiểm tra/nghỉ -> không tính ngày này
            if p <= 0:
                current += timedelta(days=1)
                continue

            # Build (class_id, period) -> subject (tất cả subject logs để tra cứu)
            subject_by_class_period = {}
            for sl in subject_logs:
                key = (sl["class_id"], sl["period"])
                if key not in subject_by_class_period:
                    subject_by_class_period[key] = sl
                # Thêm mapping theo period_name từ TKB nếu khác (chuẩn hóa tên)
                pnum = _extract_period_num(sl.get("period"))
                if pnum is not None:
                    for pn in timetable_period_set:
                        if _extract_period_num(pn) == pnum:
                            alt_key = (sl["class_id"], pn)
                            if alt_key not in subject_by_class_period:
                                subject_by_class_period[alt_key] = sl
                            break

            subject_ids = [log["name"] for log in subject_logs]
            students_by_subject = {}
            if subject_ids:
                student_logs = frappe.db.sql("""
                    SELECT subject_id, student_id, homework, behavior, participation, is_top_performance, top_performance
                    FROM `tabSIS Class Log Student`
                    WHERE subject_id IN %(subject_ids)s
                """, {"subject_ids": subject_ids}, as_dict=True)
            else:
                student_logs = []

            for sl in student_logs:
                sid = sl["subject_id"]
                if sid not in students_by_subject:
                    students_by_subject[sid] = {}
                students_by_subject[sid][sl["student_id"]] = sl

            # student_id + period_num -> student_log (fallback khi tra cứu theo subject_key không khớp)
            student_period_data = {}
            for sl in subject_logs:
                pnum = _extract_period_num(sl.get("period"))
                if pnum is not None:
                    for sid, stu_log in students_by_subject.get(sl["name"], {}).items():
                        student_period_data[(sid, pnum)] = stu_log

            # Lấy attendance
            class_att = frappe.db.sql("""
                SELECT student_id, period, status, class_id
                FROM `tabSIS Class Attendance`
                WHERE date = %(date)s
                    AND student_id IN %(student_ids)s
                    AND LOWER(period) LIKE '%%tiết%%'
                    AND class_id IN %(class_ids)s
            """, {"date": date_str, "student_ids": student_ids, "class_ids": list(all_class_ids)}, as_dict=True)

            # Map (student_id, period) -> class_id từ SIS Student Timetable
            stt_rows = frappe.db.sql("""
                SELECT st.student_id, st.class_id, tc.period_name
                FROM `tabSIS Student Timetable` st
                INNER JOIN `tabSIS Timetable Column` tc ON st.timetable_column_id = tc.name
                WHERE st.student_id IN %(student_ids)s
                    AND st.date = %(date)s
                    AND LOWER(tc.period_name) LIKE '%%tiết%%'
            """, {"student_ids": student_ids, "date": date_str}, as_dict=True)

            student_period_class = {}
            period_num_to_name = {_extract_period_num(pn): pn for pn in period_set}
            for row in stt_rows:
                num = _extract_period_num(row["period_name"])
                if num and num in period_num_to_name:
                    pname = period_num_to_name[num]
                    key = (row["student_id"], pname)
                    if key not in student_period_class:
                        student_period_class[key] = row["class_id"]

            # Class Attendance = nơi GV điểm danh → ưu tiên hơn SIS Student Timetable khi có
            for row in class_att:
                num = _extract_period_num(row["period"])
                pname = row["period"] if row["period"] in period_set else (period_num_to_name.get(num) if num in period_num_to_name else None)
                if pname:
                    key = (row["student_id"], pname)
                    student_period_class[key] = row["class_id"]

            # Build attendance map (student_id, period) -> status
            attendance_map = {}
            for row in class_att:
                num = _extract_period_num(row["period"])
                pname = row["period"] if row["period"] in period_set else (period_num_to_name.get(num) if num in period_num_to_name else None)
                if pname:
                    key = (row["student_id"], pname)
                    if key not in attendance_map:
                        attendance_map[key] = (row["status"] or "present").lower()

            # Event Attendance: chỉ query nếu bảng có cột period (schema có thể khác giữa các môi trường)
            if edu_stage_id and frappe.db.has_column("SIS Event Attendance", "period"):
                try:
                    event_att = frappe.db.sql("""
                        SELECT student_id, period, status
                        FROM `tabSIS Event Attendance`
                        WHERE date = %(date)s
                            AND student_id IN %(student_ids)s
                            AND LOWER(period) LIKE '%%tiết%%'
                            AND education_stage_id = %(edu_stage_id)s
                    """, {"date": date_str, "student_ids": student_ids, "edu_stage_id": edu_stage_id}, as_dict=True)
                    for row in event_att:
                        num = _extract_period_num(row.get("period"))
                        pname = row.get("period") if row.get("period") in period_set else (period_num_to_name.get(num) if num in period_num_to_name else None)
                        if pname:
                            key = (row["student_id"], pname)
                            if key not in attendance_map:
                                attendance_map[key] = (row.get("status") or "present").lower()
                except Exception:
                    pass

            # Tính Điểm lớp cho ngày (wis-point):
            # - Tiết học lớp chính quy: Điểm tiết học = lesson_score trong sổ đầu bài
            # - Tiết học lớp chạy: Điểm tiết học = lesson_score của lớp chạy đó trong sổ đầu bài
            # - Điểm tiết học = trung bình có trọng số theo số HS mỗi lớp
            # VD: 13 HS lớp chạy A (điểm 8), 7 HS lớp chạy B (điểm 9) -> (13*8 + 7*9)/20 = 8.35
            # Tiết không có lesson_score (GV chưa nhập) dùng 0
            daily_lesson_scores = []
            for period in period_set:
                # Đếm số HS homeroom tham gia mỗi class (chính quy hoặc lớp chạy)
                class_counts = {}  # class_id -> số HS
                for sid in student_ids:
                    actual_class = student_period_class.get((sid, period), class_id)
                    class_counts[actual_class] = class_counts.get(actual_class, 0) + 1

                weighted_sum = 0
                total_count = 0
                for cid, count in class_counts.items():
                    subj = subject_by_class_period.get((cid, period))
                    ls = subj.get("lesson_score") if subj else None
                    try:
                        weighted_sum += int(ls or 0) * count
                    except (ValueError, TypeError):
                        weighted_sum += 0
                    total_count += count

                if total_count > 0:
                    daily_lesson_scores.append(weighted_sum / total_count)

            if daily_lesson_scores:
                class_daily_scores.extend(daily_lesson_scores)
                if include_detail:
                    period_breakdown = []
                    for pr in sorted(period_set):
                        class_counts_pr = {}
                        for sid in student_ids:
                            ac = student_period_class.get((sid, pr), class_id)
                            class_counts_pr[ac] = class_counts_pr.get(ac, 0) + 1
                        ws, tc = 0, 0
                        for cid, cnt in class_counts_pr.items():
                            subj = subject_by_class_period.get((cid, pr))
                            ls = subj.get("lesson_score") if subj else None
                            try:
                                ws += int(ls or 0) * cnt
                            except (ValueError, TypeError):
                                pass
                            tc += cnt
                        period_breakdown.append({
                            "period": pr,
                            "lesson_score": round(ws / tc, 2) if tc > 0 else 0,
                        })
                    class_daily_details.append({
                        "date": date_str,
                        "lesson_scores_per_period": period_breakdown,
                        "daily_avg": round(sum(daily_lesson_scores) / len(daily_lesson_scores), 2),
                    })

            # Tính điểm cho từng học sinh
            for student_id in student_ids:
                h = 0.0
                c = 0

                for period in period_set:
                    actual_class = student_period_class.get((student_id, period), class_id)
                    subject_key = (actual_class, period)
                    subject_log = subject_by_class_period.get(subject_key)
                    # Fallback: sổ đầu bài thường tạo cho lớp chủ nhiệm, thử class_id khi học sinh ở lớp chạy
                    if subject_log is None and actual_class != class_id:
                        subject_log = subject_by_class_period.get((class_id, period))

                    # Chỉ tính c và penalty khi có dữ liệu điểm danh cho tiết đó
                    att_status = attendance_map.get((student_id, period))
                    if att_status is not None:
                        if att_status not in ("present", "late", "excused", "absent"):
                            att_status = "absent"
                        # wis-point.md 2.2: Có mặt + muộn + vắng có phép tính vào c; vắng không phép không tính
                        if att_status in ("present", "late", "excused"):
                            c += 1
                        penalty = ATTENDANCE_PENALTY.get(att_status, 0)
                    else:
                        penalty = 0

                    if subject_log:
                        subject_id = subject_log["name"]
                        student_log = students_by_subject.get(subject_id, {}).get(student_id)
                        # Fallback: tra theo (student_id, số_tiết) - tránh lỗi khớp tên period
                        if student_log is None:
                            pnum_per = _extract_period_num(period)
                            student_log = student_period_data.get((student_id, pnum_per)) if pnum_per else None
                        hw_val = _get_score_value(student_log.get("homework")) if student_log and student_log.get("homework") else default_values["homework"]
                        beh_val = _get_score_value(student_log.get("behavior")) if student_log and student_log.get("behavior") else default_values["behavior"]
                        part_val = _get_score_value(student_log.get("participation")) if student_log and student_log.get("participation") else default_values["participation"]
                        # wis-point.md: praise_score = value từ SIS Class Log Score (top_performance). Ưu tiên link, else default, fallback +1 khi được khen
                        if student_log and student_log.get("is_top_performance"):
                            praise_val = _get_score_value(student_log.get("top_performance")) if student_log.get("top_performance") else default_values["top_performance"]
                            if (praise_val or 0) == 0:
                                praise_val = 1  # Được khen nhưng chưa cấu hình → +1 điểm
                        else:
                            praise_val = 0
                    else:
                        # Không có class log -> mặc định 0 cho tất cả thông số
                        hw_val = 0
                        beh_val = 0
                        part_val = 0
                        praise_val = 0

                    lesson_score = (hw_val or 0) + (beh_val or 0) + (part_val or 0) + (praise_val or 0) + penalty
                    # wis-point.md: Tiết nghỉ không phép → h=0 cho tiết đó (không cộng lesson_score vào h)
                    if att_status is not None and att_status == "absent":
                        h += 0
                    else:
                        h += lesson_score

                if p > 0:
                    b = max_lesson_score * p
                    base_score = (h / b) * 100 if b > 0 else 0
                    # Không có dữ liệu điểm danh (c=0) -> att=1, không phạt
                    attendance_factor = (c / p) ** N if c > 0 else 1
                    daily_score = max(0, base_score * attendance_factor)
                    student_daily_scores[student_id].append(daily_score)
                    if include_detail:
                        student_daily_details[student_id].append({
                            "date": date_str,
                            "h": round(h, 2),
                            "b": round(b, 2),
                            "p": p,
                            "c": c,
                            "base_score": round(base_score, 2),
                            "attendance_factor": round(attendance_factor, 4),
                            "daily_score": round(daily_score, 2),
                            "formula": f"base_score * attendance_factor = ({h}/{b})*100 * ({c}/{p})^{N}",
                        })

            current += timedelta(days=1)

        # Tổng hợp: trung bình các daily_score
        scores = {}
        for sid in student_ids:
            daily_list = student_daily_scores[sid]
            if daily_list:
                avg = sum(daily_list) / len(daily_list)
                scores[sid] = {"academic_score": round(avg, 2), "days_with_data": len(daily_list)}
            else:
                scores[sid] = {"academic_score": 0, "days_with_data": 0}
            if include_detail:
                scores[sid]["detail"] = student_daily_details[sid]

        # Điểm lớp = trung bình tất cả Điểm tiết học trong khoảng
        avg_class_score = sum(class_daily_scores) / len(class_daily_scores) if class_daily_scores else None

        result = {
            "scores": scores,
            "class_score": round(avg_class_score, 2) if avg_class_score is not None else None,
            "config": {"n": N, "max_lesson_score": max_lesson_score}
        }
        if include_detail:
            result["class_score_detail"] = class_daily_details
            result["formula"] = "Score = (h/b × 100) × (c/p)^n  với h=tổng lesson_score, b=max×p, c=tiết tham gia, n=0.7"

        if not include_detail:
            try:
                frappe.cache().set_value(cache_key, result, expires_in_sec=300)
            except Exception:
                pass

        return success_response(data=result, message="WIS academic scores calculated")

    except Exception as e:
        frappe.logger().error(f"get_wis_academic_scores error: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        frappe.log_error(f"get_wis_academic_scores error: {str(e)}", "WIS Academic Scores Error")
        return error_response(
            message=f"Failed to calculate WIS academic scores: {str(e)}",
            code="GET_WIS_ACADEMIC_SCORES_ERROR"
        )
