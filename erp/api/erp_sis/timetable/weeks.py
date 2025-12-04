# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable Weekly Queries

Handles teacher and class weekly timetable retrieval.
These are the main endpoints for displaying timetables in the frontend.
"""

import frappe
from frappe import _
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    error_response,
    list_response,
    validation_error_response,
)
from .helpers import (
    _parse_iso_date,
    _add_days,
    _build_entries,
    _apply_timetable_overrides
)


@frappe.whitelist(allow_guest=False)
def get_teacher_week():
    """Return teacher's weekly timetable entries (normalized for FE WeeklyGrid).

    Expects timetable rows stored in Doctype `SIS Timetable Instance Row` with fields:
    - day_of_week (mon..sun)
    - timetable_column_id (link to SIS Timetable Column)
    - subject_id / subject_title
    - teacher_names (from teachers child table)
    - class_id
    
    ⚡ Performance: Cached for 5 minutes per teacher/week/stage
    """
    try:
        # Get parameters from frappe request
        teacher_id = frappe.local.form_dict.get("teacher_id") or frappe.request.args.get("teacher_id")
        week_start = frappe.local.form_dict.get("week_start") or frappe.request.args.get("week_start")
        week_end = frappe.local.form_dict.get("week_end") or frappe.request.args.get("week_end")
        education_stage = frappe.local.form_dict.get("education_stage") or frappe.request.args.get("education_stage")

        if not teacher_id:
            return validation_error_response("Validation failed", {"teacher_id": ["Teacher is required"]})
        if not week_start:
            return validation_error_response("Validation failed", {"week_start": ["Week start is required"]})

        # ⚡ CACHE: Check Redis cache first (5 min TTL)
        campus_id = get_current_campus_from_context()
        cache_key = f"teacher_week:{teacher_id}:{week_start}:{week_end or 'default'}:{education_stage or 'none'}:{campus_id or 'none'}"
        
        try:
            cached_data = frappe.cache().get_value(cache_key)
            if cached_data:
                frappe.logger().info(f"✅ Cache HIT for teacher_week {teacher_id} (week {week_start})")
                return list_response(
                    data=cached_data,
                    message="Class week fetched successfully (cached)"
                )
        except Exception as cache_error:
            frappe.logger().warning(f"Cache read failed: {cache_error}")
        
        frappe.logger().info(f"❌ Cache MISS for teacher_week {teacher_id} (week {week_start}) - fetching from DB")

        ws = _parse_iso_date(week_start)

        # Resolve teacher_id to SIS Teacher doc name(s) if passed as User email/name
        resolved_teacher_ids = set()
        try:
            # Try direct match by Teacher name
            if frappe.db.exists("SIS Teacher", teacher_id):
                resolved_teacher_ids.add(teacher_id)
            # Try match by user_id (User.name/email)
            alt = frappe.get_all(
                "SIS Teacher",
                fields=["name"],
                filters={"user_id": teacher_id},
                limit=50,
            )
            for t in alt:
                resolved_teacher_ids.add(t.name)
            # If still empty and looks like email, try normalized case-sensitive name
            if not resolved_teacher_ids and "@" in (teacher_id or ""):
                user = frappe.get_all(
                    "User",
                    fields=["name"],
                    filters={"name": teacher_id},
                    limit=1,
                )
                if user:
                    alt2 = frappe.get_all(
                        "SIS Teacher",
                        fields=["name"],
                        filters={"user_id": user[0].name},
                        limit=50,
                    )
                    for t in alt2:
                        resolved_teacher_ids.add(t.name)
        except Exception as resolve_error:
            frappe.logger().warning(f"⚠️ Failed to resolve teacher ID {teacher_id}: {str(resolve_error)}")
        # Fallback to original id if nothing resolved
        if not resolved_teacher_ids:
            resolved_teacher_ids.add(teacher_id)
        
        # ⚡ Removed redundant test query - campus_id filter is handled in Teacher Timetable query
        filters = {}
        
        # Add education_stage filter by getting valid timetable_column_ids
        if education_stage:
            try:
                # Get timetable columns for this education stage
                column_filters = {"education_stage_id": education_stage}
                if campus_id:
                    column_filters["campus_id"] = campus_id
                
                frappe.logger().info(f"🔍 TIMETABLE: Filtering by education_stage={education_stage} with column_filters={column_filters}")
                    
                valid_columns = frappe.get_all(
                    "SIS Timetable Column",
                    fields=["name"],
                    filters=column_filters
                )
                
                frappe.logger().info(f"🔍 TIMETABLE: Found {len(valid_columns)} valid columns for education_stage={education_stage}")
                
                if valid_columns:
                    valid_column_ids = [col.name for col in valid_columns]
                    filters["timetable_column_id"] = ["in", valid_column_ids]
                    frappe.logger().info(f"✅ TIMETABLE: Applied filter with {len(valid_column_ids)} column IDs")
                else:
                    # If no columns found for this education stage, return empty
                    frappe.logger().warning(f"⚠️ TIMETABLE: No timetable columns found for education_stage={education_stage}")
                    return list_response([], "No timetable columns found for this education stage")
                    
            except Exception as education_filter_error:
                # ❌ DO NOT silently ignore errors - log and return error response
                error_msg = f"Error filtering by education stage {education_stage}: {str(education_filter_error)}"
                frappe.logger().error(f"❌ TIMETABLE: {error_msg}")
                frappe.log_error(error_msg, "Timetable Education Stage Filter Error")
                return error_response(error_msg)

        # ✅ NEW APPROACH: Query from SIS Teacher Timetable materialized view instead of Instance Rows
        # This ensures we only return entries that have been properly created with teacher assignments
        
        # Build date filter for the week
        teacher_timetable_filters = {
            "date": ["between", [ws, week_end]] if week_end else [">=", ws]
        }
        
        # Add education_stage filter if already applied to 'filters'
        if "timetable_column_id" in filters:
            teacher_timetable_filters["timetable_column_id"] = filters["timetable_column_id"]
        
        try:
            # ⚡ OPTIMIZED: Query all teachers at once using IN clause instead of loop
            teacher_timetable_filters["teacher_id"] = ["in", list(resolved_teacher_ids)]
            
            rows = frappe.get_all(
                "SIS Teacher Timetable",
                fields=[
                    "name",
                    "teacher_id", 
                    "class_id",
                    "day_of_week",
                    "timetable_column_id",
                    "subject_id",
                    "room_id",
                    "date",
                    "timetable_instance_id"
                ],
                filters=teacher_timetable_filters,
                order_by="date asc, day_of_week asc"
            )
            
            # Map to structure expected by downstream code
            for row in rows:
                row["parent"] = row.get("timetable_instance_id")
                
        except Exception as query_error:
            return error_response(f"Query failed: {str(query_error)}")
        # Enrich subject_title and teacher_names
        try:
            subject_ids = list({r.get("subject_id") for r in rows if r.get("subject_id")})
            subject_title_map = {}
            timetable_subject_by_subject = {}
            timetable_subject_title_map = {}
            if subject_ids:
                subj_rows = frappe.get_all(
                    "SIS Subject",
                    fields=["name", "title", "timetable_subject_id"],
                    filters={"name": ["in", subject_ids]},
                )
                for s in subj_rows:
                    subject_title_map[s.name] = s.title
                    if s.get("timetable_subject_id"):
                        timetable_subject_by_subject[s.name] = s.get("timetable_subject_id")
                # Load timetable subject titles for display preference
                ts_ids = list({ts for ts in timetable_subject_by_subject.values() if ts})
                if ts_ids:
                    ts_rows = frappe.get_all(
                        "SIS Timetable Subject",
                        fields=["name", "title_vn", "title_en"],
                        filters={"name": ["in", ts_ids]},
                    )
                    for ts in ts_rows:
                        timetable_subject_title_map[ts.name] = ts.title_vn or ts.title_en or ""

            # Get row IDs to query teachers from child table (for Instance Rows)
            # Also collect teacher_id from rows that come from Teacher Timetable view
            row_ids = [r.get("name") for r in rows if r.get("name")]
            row_teachers_map = {}  # row_id -> list of teacher_ids
            
            if row_ids:
                # Query child table for teachers (only applies to Instance Rows)
                teacher_children = frappe.get_all(
                    "SIS Timetable Instance Row Teacher",
                    fields=["parent", "teacher_id", "sort_order"],
                    filters={"parent": ["in", row_ids]},
                    order_by="parent asc, sort_order asc"
                )
                
                # Group by parent (row_id)
                for child in teacher_children:
                    row_id = child.parent
                    if row_id not in row_teachers_map:
                        row_teachers_map[row_id] = []
                    row_teachers_map[row_id].append(child.teacher_id)
            
            # For rows from Teacher Timetable view, they have teacher_id directly
            for r in rows:
                if r.get("teacher_id") and r.get("name") not in row_teachers_map:
                    # This row is from Teacher Timetable view, use teacher_id directly
                    row_teachers_map[r.get("name")] = [r.get("teacher_id")]
            
            # Get unique teacher IDs and build display name map
            teacher_ids = list(set(tid for tids in row_teachers_map.values() for tid in tids))
            teacher_user_map = {}
            
            if teacher_ids:
                teachers = frappe.get_all(
                    "SIS Teacher",
                    fields=["name", "user_id"],
                    filters={"name": ["in", teacher_ids]},
                )
                user_ids = [t.user_id for t in teachers if t.get("user_id")]
                user_display_map = {}
                if user_ids:
                    for u in frappe.get_all(
                        "User",
                        fields=["name", "full_name", "first_name", "middle_name", "last_name"],
                        filters={"name": ["in", user_ids]},
                    ):
                        display = u.get("full_name")
                        if not display:
                            parts = [u.get("first_name"), u.get("middle_name"), u.get("last_name")]
                            display = " ".join([p for p in parts if p]) or u.get("name")
                        user_display_map[u.name] = display
                for t in teachers:
                    teacher_user_map[t.name] = user_display_map.get(t.get("user_id")) or t.get("user_id") or t.get("name")

            # Enrich rows with subject titles and teacher names
            for r in rows:
                # Prefer Timetable Subject title if linked via SIS Subject
                subj_id = r.get("subject_id")
                ts_id = timetable_subject_by_subject.get(subj_id)
                ts_title = timetable_subject_title_map.get(ts_id) if ts_id else None
                default_title = subject_title_map.get(subj_id) or r.get("subject_title") or r.get("subject_name") or ""
                r["subject_title"] = ts_title or default_title
                
                # Build teacher_names from child table
                row_id = r.get("name")
                teacher_ids_for_row = row_teachers_map.get(row_id, [])
                teacher_names_list = [teacher_user_map.get(tid) for tid in teacher_ids_for_row if tid in teacher_user_map]
                r["teacher_names"] = ", ".join([n for n in teacher_names_list if n])

            # ⚡ BULK: Enrich with room information (batch query instead of N+1)
            try:
                # Collect unique class_ids for bulk query
                class_ids = list({r.get("class_id") for r in rows if r.get("class_id")})
                room_map = {}  # {class_id: {room_id, room_name, room_type}}
                
                if class_ids:
                    # Query all rooms for these classes at once
                    class_rooms = frappe.db.sql("""
                        SELECT c.name as class_id, r.name as room_id, r.room_name, r.room_type
                        FROM `tabSIS Class` c
                        LEFT JOIN `tabSIS Room` r ON c.default_room_id = r.name
                        WHERE c.name IN %s
                    """, (class_ids,), as_dict=True)
                    
                    for cr in class_rooms:
                        room_map[cr.class_id] = {
                            "room_id": cr.room_id,
                            "room_name": cr.room_name or "Chưa có phòng",
                            "room_type": cr.room_type
                        }
                
                # Apply room info to rows
                for r in rows:
                    class_id = r.get("class_id")
                    if class_id and class_id in room_map:
                        r["room_id"] = room_map[class_id].get("room_id")
                        r["room_name"] = room_map[class_id].get("room_name")
                        r["room_type"] = room_map[class_id].get("room_type")
                    else:
                        r["room_id"] = None
                        r["room_name"] = "Chưa có phòng"
                        r["room_type"] = None
            except Exception as room_error:
                frappe.logger().warning(f"Failed to bulk load room info: {str(room_error)}")
                for r in rows:
                    r["room_id"] = None
                    r["room_name"] = "Chưa có phòng"
                    r["room_type"] = None
        except Exception as enrich_error:
            frappe.logger().error(f"Error in enrichment section: {str(enrich_error)}")
            import traceback
            frappe.logger().error(f"Enrichment error traceback: {traceback.format_exc()}")
            # Still try to add room info even if other enrichment failed
            try:
                from erp.api.erp_administrative.room import get_room_for_class_subject
                for r in rows:
                    if not r.get("room_id"):
                        try:
                            room_info = get_room_for_class_subject(r.get("class_id"), r.get("subject_title"))
                            r["room_id"] = room_info.get("room_id")
                            r["room_name"] = room_info.get("room_name")
                            r["room_type"] = room_info.get("room_type")
                        except Exception:
                            r["room_id"] = None
                            r["room_name"] = "Chưa có phòng"
                            r["room_type"] = None
            except Exception:
                pass

        entries = _build_entries(rows, ws)
        
        # Apply timetable overrides for date-specific changes (PRIORITY 3)
        week_end = _add_days(ws, 6)
        entries_with_overrides = _apply_timetable_overrides(entries, "Teacher", resolved_teacher_ids, ws, week_end)
        
        # ⚡ CACHE: Store result in Redis (5 min = 300 sec)
        try:
            frappe.cache().set_value(cache_key, entries_with_overrides, expires_in_sec=300)
            frappe.logger().info(f"✅ Cached teacher_week for {teacher_id} (key: {cache_key})")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache write failed: {cache_error}")
        
        return list_response(entries_with_overrides, "Teacher week fetched successfully")
    except Exception as e:

        return error_response(f"Error fetching teacher week: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_class_week():
    """Return class weekly timetable entries.
    
    ⚡ Performance: Cached for 5 minutes per class/week
    """
    try:
        # Get parameters from frappe request
        class_id = frappe.local.form_dict.get("class_id") or frappe.request.args.get("class_id")
        week_start = frappe.local.form_dict.get("week_start") or frappe.request.args.get("week_start")
        week_end = frappe.local.form_dict.get("week_end") or frappe.request.args.get("week_end")

        if not class_id:
            return validation_error_response("Validation failed", {"class_id": ["Class is required"]})
        if not week_start:
            return validation_error_response("Validation failed", {"week_start": ["Week start is required"]})

        # ⚡ CACHE: Check Redis cache first (5 min TTL)
        campus_id = get_current_campus_from_context()
        cache_key = f"class_week:{class_id}:{week_start}:{week_end or 'default'}:{campus_id or 'none'}"
        
        try:
            cached_data = frappe.cache().get_value(cache_key)
            if cached_data:
                frappe.logger().info(f"✅ Cache HIT for class_week {class_id} (week {week_start})")
                return list_response(
                    data=cached_data,
                    message="Class week fetched successfully (cached)"
                )
        except Exception as cache_error:
            frappe.logger().warning(f"Cache read failed: {cache_error}")
        
        frappe.logger().info(f"❌ Cache MISS for class_week {class_id} (week {week_start}) - fetching from DB")

        ws = _parse_iso_date(week_start)
        we = _parse_iso_date(week_end) if week_end else _add_days(ws, 6)

        # 1) Find timetable instances for this class that overlap the requested week
        # Apply date filtering to get only instances that are valid for the requested week
        instance_filters = {"class_id": class_id}
        date_conditions = []

        # Add date range filtering: instances must be active during the requested week
        if ws and we:
            # Instance must start before or on the week end date
            # AND end after or on the week start date
            date_conditions.append(["start_date", "<=", we])
            date_conditions.append(["end_date", ">=", ws])

        if date_conditions:
            # Combine class filter with date filters
            instance_filters.update({
                "start_date": ["<=", we],
                "end_date": [">=", ws]
            })

        try:
            instances = frappe.get_all(
                "SIS Timetable Instance",
                fields=["name", "class_id", "start_date", "end_date"],
                filters=instance_filters,
                order_by="start_date asc"
            )
        except Exception as e:
            return error_response(f"Failed to query instances: {str(e)}")

        if not instances:
            return list_response([], "Class week fetched successfully")

        instance_ids = [i.name for i in instances if i.name]
        instances_map = {i.name: i for i in instances}

        # 2) Load child rows belonging to these instances
        try:
            # Query both pattern rows (weekly_pattern) and override rows (date_overrides)
            # We need to query separately because parentfield is different
            pattern_filters = {
                "parent": ["in", instance_ids],
                "parenttype": "SIS Timetable Instance",
                "parentfield": "weekly_pattern",
            }
            override_filters = {
                "parent": ["in", instance_ids],
                "parenttype": "SIS Timetable Instance",
                "parentfield": "date_overrides",
            }
            
            # Query pattern rows
            pattern_rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=[
                    "name",
                    "parent",
                    "day_of_week",
                    "date",
                    "timetable_column_id",
                    "subject_id",
                ],
                filters=pattern_filters,
                order_by="day_of_week asc",
            )
            
            # Query override rows
            override_rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=[
                    "name",
                    "parent",
                    "day_of_week",
                    "date",
                    "timetable_column_id",
                    "subject_id",
                ],
                filters=override_filters,
                order_by="date asc, day_of_week asc",
            )
            
            # Combine both
            rows = pattern_rows + override_rows
            frappe.logger().info(f"📊 get_class_week: Found {len(pattern_rows)} pattern rows + {len(override_rows)} override rows = {len(rows)} total rows")
            
            # 🔍 DEBUG: Log rows for troubleshooting
            frappe.logger().info(f"📊 get_class_week: Found {len(rows)} rows for class {class_id}")
            # Fallback: some rows may have been created via explicit link field
            if not rows:
                alt_rows = frappe.get_all(
                    "SIS Timetable Instance Row",
                    fields=[
                        "name",
                        "parent_timetable_instance",
                        "day_of_week",
                        "date",  # ✅ ADD: Support date-specific override rows
                        "timetable_column_id",
                        "subject_id",
                    ],
                    filters={"parent_timetable_instance": ["in", instance_ids]},
                    order_by="day_of_week asc",
                )
                # Normalize to same shape
                for r in alt_rows:
                    r["parent"] = r.get("parent_timetable_instance")
                rows = alt_rows
            # Final fallback: direct SQL in case get_all filters behave differently
            if not rows:
                placeholders = ",".join(["%s"] * len(instance_ids))
                sql = f"""
                    SELECT name, parent_timetable_instance, day_of_week, date, timetable_column_id, subject_id
                    FROM `tabSIS Timetable Instance Row`
                    WHERE parent_timetable_instance IN ({placeholders})
                """
                sql_rows = frappe.db.sql(sql, instance_ids, as_dict=True)
                rows = sql_rows or []
        except Exception as e:
            return error_response(f"Failed to query instance rows: {str(e)}")

        # 3) Attach class_id to rows for FE and builder
        for r in rows:
            parent = r.get("parent")
            r["class_id"] = instances_map.get(parent, {}).get("class_id")

        # 4) Enrich subject_title and teacher_names
        try:
            subject_ids = list({r.get("subject_id") for r in rows if r.get("subject_id")})

            subject_title_map = {}
            timetable_subject_by_subject = {}
            timetable_subject_title_map = {}
            if subject_ids:
                subj_rows = frappe.get_all(
                    "SIS Subject",
                    fields=["name", "title", "timetable_subject_id"],
                    filters={"name": ["in", subject_ids]},
                )
                for s in subj_rows:
                    subject_title_map[s.name] = s.title
                    if s.get("timetable_subject_id"):
                        timetable_subject_by_subject[s.name] = s.get("timetable_subject_id")
                ts_ids = list({ts for ts in timetable_subject_by_subject.values() if ts})
                if ts_ids:
                    ts_rows = frappe.get_all(
                        "SIS Timetable Subject",
                        fields=["name", "title_vn", "title_en"],
                        filters={"name": ["in", ts_ids]},
                    )
                    for ts in ts_rows:
                        timetable_subject_title_map[ts.name] = ts.title_vn or ts.title_en or ""

            # Get row IDs to query teachers from child table
            row_ids = [r.get("name") for r in rows if r.get("name")]
            row_teachers_map = {}  # row_id -> list of teacher_ids
            
            if row_ids:
                # Query child table for teachers
                teacher_children = frappe.get_all(
                    "SIS Timetable Instance Row Teacher",
                    fields=["parent", "teacher_id", "sort_order"],
                    filters={"parent": ["in", row_ids]},
                    order_by="parent asc, sort_order asc"
                )
                
                # Group by parent (row_id)
                for child in teacher_children:
                    row_id = child.parent
                    if row_id not in row_teachers_map:
                        row_teachers_map[row_id] = []
                    row_teachers_map[row_id].append(child.teacher_id)
            
            # Get unique teacher IDs and build display name map
            teacher_ids = list(set(tid for tids in row_teachers_map.values() for tid in tids))
            teacher_user_map = {}
            
            if teacher_ids:
                teachers = frappe.get_all(
                    "SIS Teacher",
                    fields=["name", "user_id"],
                    filters={"name": ["in", teacher_ids]},
                )
                user_ids = [t.user_id for t in teachers if t.get("user_id")]
                user_display_map = {}
                if user_ids:
                    for u in frappe.get_all(
                        "User",
                        fields=["name", "full_name", "first_name", "middle_name", "last_name"],
                        filters={"name": ["in", user_ids]},
                    ):
                        display = u.get("full_name")
                        if not display:
                            parts = [u.get("first_name"), u.get("middle_name"), u.get("last_name")]
                            display = " ".join([p for p in parts if p]) or u.get("name")
                        user_display_map[u.name] = display
                for t in teachers:
                    teacher_user_map[t.name] = user_display_map.get(t.get("user_id")) or t.get("user_id") or t.get("name")

            # Enrich rows with subject titles and teacher names
            for r in rows:
                subj_id = r.get("subject_id")
                
                # Debug logging for override rows without subject_id
                if r.get("date") and not subj_id:
                    frappe.logger().warning(f"⚠️  Override row {r.get('name')} missing subject_id!")
                
                ts_id = timetable_subject_by_subject.get(subj_id)
                ts_title = timetable_subject_title_map.get(ts_id) if ts_id else None
                default_title = subject_title_map.get(subj_id) or r.get("subject_title") or r.get("subject_name") or ""
                r["subject_title"] = ts_title or default_title
                
                # If still no subject_title, mark it clearly for debugging
                if not r["subject_title"]:
                    r["subject_title"] = f"[Missing Subject] Row: {r.get('name')}"
                    frappe.logger().warning(f"⚠️  Row {r.get('name')} has no subject_title after enrich")
                
                # Build teacher_names from child table
                row_id = r.get("name")
                teacher_ids_for_row = row_teachers_map.get(row_id, [])
                teacher_names_list = [teacher_user_map.get(tid) for tid in teacher_ids_for_row if tid in teacher_user_map]
                r["teacher_names"] = ", ".join([n for n in teacher_names_list if n])

            # ⚡ BULK: Enrich with room information (batch query instead of N+1)
            try:
                class_ids = list({r.get("class_id") for r in rows if r.get("class_id")})
                room_map = {}
                
                if class_ids:
                    class_rooms = frappe.db.sql("""
                        SELECT c.name as class_id, r.name as room_id, r.room_name, r.room_type
                        FROM `tabSIS Class` c
                        LEFT JOIN `tabSIS Room` r ON c.default_room_id = r.name
                        WHERE c.name IN %s
                    """, (class_ids,), as_dict=True)
                    
                    for cr in class_rooms:
                        room_map[cr.class_id] = {
                            "room_id": cr.room_id,
                            "room_name": cr.room_name or "Chưa có phòng",
                            "room_type": cr.room_type
                        }
                
                for r in rows:
                    class_id = r.get("class_id")
                    if class_id and class_id in room_map:
                        r["room_id"] = room_map[class_id].get("room_id")
                        r["room_name"] = room_map[class_id].get("room_name")
                        r["room_type"] = room_map[class_id].get("room_type")
                    else:
                        r["room_id"] = None
                        r["room_name"] = "Chưa có phòng"
                        r["room_type"] = None
            except Exception as room_error:
                frappe.logger().warning(f"Failed to bulk load room info: {str(room_error)}")
                for r in rows:
                    r["room_id"] = None
                    r["room_name"] = "Chưa có phòng"
                    r["room_type"] = None
        except Exception as enrich_error:
            frappe.logger().error(f"Error in enrichment section: {str(enrich_error)}")
            for r in rows:
                r["room_id"] = None
                r["room_name"] = "Chưa có phòng"
                r["room_type"] = None

        entries = _build_entries(rows, ws)
        
        # Apply timetable overrides for date-specific changes (PRIORITY 3)
        entries_with_overrides = _apply_timetable_overrides(entries, "Class", class_id, ws, we)
        
        # ⚡ CACHE: Store result in Redis (5 min = 300 sec)
        try:
            frappe.cache().set_value(cache_key, entries_with_overrides, expires_in_sec=300)
            frappe.logger().info(f"✅ Cached class_week for {class_id} (key: {cache_key})")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache write failed: {cache_error}")
        
        return list_response(entries_with_overrides, "Class week fetched successfully")
    except Exception as e:

        return error_response(f"Error fetching class week: {str(e)}")

