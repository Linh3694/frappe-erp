import json
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
            fields=["name", "type", "title_vn", "title_en", "value", "color", "education_stage"],
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
            fields=["name", "class_id", "general_comment"],
            limit=1
        )
        if subject_rows:
            subject_id = subject_rows[0]['name']
            class_id = subject_rows[0]['class_id']
            general_comment = subject_rows[0].get('general_comment')
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

        # Update general comment if provided
        if general_comment is not None:
            frappe.db.set_value("SIS Class Log Subject", subject_id, {"general_comment": general_comment}, update_modified=True)

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
        
        # ⚡ CACHE: Clear class log cache after save (both single and batch)
        try:
            # Clear single period cache
            cache_key = f"class_log:{class_id}:{date}:{period or 'none'}"
            frappe.cache().delete_key(cache_key)
            
            # Clear batch cache - use wildcard pattern
            cache = frappe.cache()
            redis_conn = cache.redis_cache if hasattr(cache, 'redis_cache') else cache
            if hasattr(redis_conn, 'scan_iter'):
                batch_pattern = f"*class_logs_batch:{class_id}:{date}:*"
                batch_keys = list(redis_conn.scan_iter(match=batch_pattern, count=100))
                if batch_keys:
                    redis_conn.delete(*batch_keys)
                    frappe.logger().info(f"✅ Cleared {len(batch_keys)} batch cache keys for {class_id}/{date}")
            
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
            fields=["name", "period", "class_id", "general_comment"]
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
                        "general_comment": subject.get('general_comment')
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

