import json
import re
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
        cache_key = f"class_log_options:{education_stage or 'all'}"
        
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

        grouped = {"homework": [], "behavior": [], "participation": [], "issue": [], "top_performance": []}
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
            cache_key_stage = f"class_log_options:{education_stage}"
            frappe.cache().delete_key(cache_key_stage)
            
            # Clear cache "all" (khi không có filter education_stage)
            cache_key_all = "class_log_options:all"
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
            fields=["name", "class_id", "general_comment", "lesson_name", "lesson_score", "homework_assignment"],
            limit=1
        )
        if subject_rows:
            subject_id = subject_rows[0]['name']
            class_id = subject_rows[0]['class_id']
            general_comment = subject_rows[0].get('general_comment')
            lesson_name = subject_rows[0].get('lesson_name')
            lesson_score = subject_rows[0].get('lesson_score')
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
            fields=["name", "period", "class_id", "general_comment", "lesson_name", "lesson_score", "homework_assignment"]
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
        cache_key = f"homeroom_class_logs:{homeroom_class_id}:{date}:periods_{periods_hash}"
        
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
            all_subject_logs = frappe.db.sql("""
                SELECT name, period, class_id, general_comment, lesson_name, lesson_score, homework_assignment, timetable_instance_id
                FROM `tabSIS Class Log Subject`
                WHERE timetable_instance_id IN %(instance_ids)s
                    AND log_date = %(date)s
                    AND LOWER(period) LIKE '%%tiết%%'
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
            if homeroom_subject_log:
                all_subjects.append({
                    "name": homeroom_subject_log['name'],
                    "class_id": homeroom_subject_log['class_id'],
                    "class_title": class_titles.get(homeroom_subject_log['class_id'], homeroom_subject_log['class_id']),
                    "general_comment": homeroom_subject_log.get('general_comment'),
                    "lesson_name": homeroom_subject_log.get('lesson_name'),
                    "lesson_score": homeroom_subject_log.get('lesson_score'),
                    "homework_assignment": homeroom_subject_log.get('homework_assignment'),
                    "is_homeroom": True
                })
            
            # Thêm mixed class subjects
            for mixed_class_id, mixed_log in mixed_subject_logs.items():
                all_subjects.append({
                    "name": mixed_log['name'],
                    "class_id": mixed_log['class_id'],
                    "class_title": class_titles.get(mixed_log['class_id'], mixed_log['class_id']),
                    "general_comment": mixed_log.get('general_comment'),
                    "lesson_name": mixed_log.get('lesson_name'),
                    "lesson_score": mixed_log.get('lesson_score'),
                    "homework_assignment": mixed_log.get('homework_assignment'),
                    "is_homeroom": False
                })
            
            result[period] = {
                "subject": {
                    "name": primary_subject['name'] if primary_subject else None,
                    "timetable_instance_id": primary_subject['timetable_instance_id'] if primary_subject else class_instances.get(homeroom_class_id),
                    "class_id": primary_subject['class_id'] if primary_subject else homeroom_class_id,
                    "general_comment": primary_subject.get('general_comment') if primary_subject else None,
                    "lesson_name": primary_subject.get('lesson_name') if primary_subject else None,
                    "lesson_score": primary_subject.get('lesson_score') if primary_subject else None,
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

