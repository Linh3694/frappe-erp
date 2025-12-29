import frappe
from frappe import _
import json
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    paginated_response,
    single_item_response,
    validation_error_response,
    not_found_response
)


# ============================================
# HELPER FUNCTIONS
# ============================================

def _convert_student_entry_activities(entry_data: dict) -> dict:
    """
    Convert activities arrays to JSON strings for student entry
    DocType expects Small Text field with JSON string, not array
    """
    if 'activities_vn' in entry_data and isinstance(entry_data['activities_vn'], list):
        entry_data['activities_vn'] = json.dumps(entry_data['activities_vn'], ensure_ascii=False)
    if 'activities_en' in entry_data and isinstance(entry_data['activities_en'], list):
        entry_data['activities_en'] = json.dumps(entry_data['activities_en'], ensure_ascii=False)
    return entry_data


def _process_student_entries(entries: list) -> list:
    """
    Process list of student entries, converting activities arrays to JSON strings
    """
    if not entries:
        return []
    return [_convert_student_entry_activities(dict(entry)) for entry in entries]


# ============================================
# PUBLIC APIs (allow_guest=True)
# ============================================

@frappe.whitelist(allow_guest=True)
def get_award_categories(campus_id: str = None, is_active: int = 1):
    """
    Get all award categories for public display
    Allow guest access for public Hall of Honor page
    """
    try:
        filters = {}
        
        if campus_id:
            filters['campus_id'] = campus_id
        
        if is_active is not None:
            filters['is_active'] = int(is_active)
        
        categories = frappe.get_all(
            'SIS Award Category',
            filters=filters,
            fields=[
                'name',
                'title_vn',
                'title_en',
                'description_vn',
                'description_en',
                'cover_image',
                'recipient_type',
                'is_active',
                'campus_id'
            ],
            order_by='modified desc'
        )
        
        # Populate sub_categories for each category
        for category in categories:
            category['sub_categories'] = frappe.get_all(
                'SIS Award Sub Category',
                filters={'parent': category['name']},
                fields=[
                    'type',
                    'label',
                    'label_en',
                    'description',
                    'description_en',
                    'school_year_id',
                    'semester',
                    'month',
                    'priority',
                    'cover_image'
                ],
                order_by='priority asc, idx asc'
            )
        
        return success_response(
            data=categories,
            message="Lấy danh sách loại vinh danh thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting award categories: {str(e)}")
        return error_response(
            message="Lỗi khi lấy danh sách loại vinh danh",
            code="GET_CATEGORIES_ERROR"
        )


@frappe.whitelist(allow_guest=True)
def get_award_records(
    award_category: str = None,
    school_year_id: str = None,
    sub_category_type: str = None,
    sub_category_label: str = None,
    semester: int = None,
    month: int = None,
    campus_id: str = None
):
    """
    Get award records with filters - OPTIMIZED VERSION
    Allow guest access for public Hall of Honor page
    Returns populated student and class data using batch queries
    """
    try:
        # Lấy params từ nhiều nguồn để đảm bảo nhận được giá trị
        award_category = (award_category or 
                         frappe.form_dict.get('award_category') or 
                         frappe.local.request.args.get('award_category'))
        school_year_id = (school_year_id or 
                         frappe.form_dict.get('school_year_id') or
                         frappe.local.request.args.get('school_year_id'))
        sub_category_type = (sub_category_type or 
                            frappe.form_dict.get('sub_category_type') or
                            frappe.local.request.args.get('sub_category_type'))
        sub_category_label = (sub_category_label or 
                             frappe.form_dict.get('sub_category_label') or
                             frappe.local.request.args.get('sub_category_label'))
        semester = (semester if semester is not None else 
                   frappe.form_dict.get('semester') or
                   frappe.local.request.args.get('semester'))
        month = (month if month is not None else 
                frappe.form_dict.get('month') or
                frappe.local.request.args.get('month'))
        campus_id = (campus_id or 
                    frappe.form_dict.get('campus_id') or
                    frappe.local.request.args.get('campus_id'))
        
        filters = {}
        
        if award_category:
            filters['award_category'] = award_category
        
        if school_year_id:
            filters['school_year_id'] = school_year_id
        
        if sub_category_type:
            filters['sub_category_type'] = sub_category_type
        
        if sub_category_label:
            filters['sub_category_label'] = sub_category_label
        
        if semester is not None:
            filters['semester'] = int(semester)
        
        if month is not None:
            filters['month'] = int(month)
        
        if campus_id:
            filters['campus_id'] = campus_id
        
        print("=" * 80)
        print("🔍 [GET_AWARD_RECORDS] Filters:", filters)
        print("=" * 80)
        
        records = frappe.get_all(
            'SIS Award Record',
            filters=filters,
            fields=[
                'name',
                'award_category',
                'school_year_id',
                'sub_category_type',
                'sub_category_label',
                'semester',
                'month',
                'priority',
                'is_active',
                'campus_id'
            ],
            order_by='priority asc, modified desc'
        )
        
        if not records:
            return success_response(data=[], message="Không có bản ghi vinh danh nào")
        
        print(f"📋 [GET_AWARD_RECORDS] Tìm thấy {len(records)} records")
        
        # ========== BATCH QUERIES để tối ưu performance ==========
        record_names = [r['name'] for r in records]
        
        # 1. Batch lấy tất cả student entries
        all_student_entries = frappe.db.sql("""
            SELECT 
                se.parent, se.student_id, se.note_vn, se.note_en,
                se.activities_vn, se.activities_en, se.exam, se.score,
                s.name as student_name_id, s.student_name, s.student_code
            FROM `tabSIS Award Student Entry` se
            LEFT JOIN `tabCRM Student` s ON s.name = se.student_id
            WHERE se.parent IN %(record_names)s
        """, {'record_names': record_names}, as_dict=True)
        
        # 2. Batch lấy tất cả class entries
        all_class_entries = frappe.db.sql("""
            SELECT 
                ce.parent, ce.class_id, ce.note_vn, ce.note_en,
                c.name as class_name, c.short_title as class_title
            FROM `tabSIS Award Class Entry` ce
            LEFT JOIN `tabSIS Class` c ON c.name = ce.class_id
            WHERE ce.parent IN %(record_names)s
        """, {'record_names': record_names}, as_dict=True)
        
        # 3. Lấy tất cả student_ids và school_year_ids để batch query photos và classes
        student_ids = list(set([e['student_id'] for e in all_student_entries if e.get('student_id')]))
        class_ids = list(set([e['class_id'] for e in all_class_entries if e.get('class_id')]))
        school_year_ids = list(set([r['school_year_id'] for r in records if r.get('school_year_id')]))
        
        # 4. Batch lấy student photos
        student_photos = {}
        if student_ids and school_year_ids:
            photos = frappe.db.sql("""
                SELECT sp.name as photo_name, sp.student_id, sp.school_year_id, sp.photo, sp.description
                FROM `tabSIS Photo` sp
                WHERE sp.student_id IN %(student_ids)s
                AND sp.school_year_id IN %(school_year_ids)s
                AND sp.type = 'student'
                ORDER BY sp.upload_date DESC
            """, {'student_ids': student_ids, 'school_year_ids': school_year_ids}, as_dict=True)
            
            # Recover từ File attachment nếu photo field là None
            photo_names_to_recover = [p['photo_name'] for p in photos if not p.get('photo') and p.get('photo_name')]
            file_attachments = {}
            if photo_names_to_recover:
                files = frappe.db.sql("""
                    SELECT attached_to_name, file_url, file_name, is_private
                    FROM `tabFile`
                    WHERE attached_to_doctype = 'SIS Photo'
                    AND attached_to_name IN %(names)s
                    ORDER BY creation DESC
                """, {'names': photo_names_to_recover}, as_dict=True)
                for f in files:
                    if f['attached_to_name'] not in file_attachments:
                        file_attachments[f['attached_to_name']] = f
            
            for p in photos:
                key = (p['student_id'], p['school_year_id'])
                if key not in student_photos:
                    photo_url = p.get('photo')
                    
                    # Recover từ File attachment nếu photo field là None
                    if not photo_url and p.get('photo_name') in file_attachments:
                        f = file_attachments[p['photo_name']]
                        photo_url = f.get('file_url')
                        if not photo_url:
                            is_priv = bool(f.get('is_private'))
                            base_path = '/private/files' if is_priv else '/files'
                            photo_url = f"{base_path}/{f.get('file_name')}"
                    
                    if photo_url:
                        student_photos[key] = photo_url
        
        # 5. Batch lấy class photos - lấy photo mới nhất của mỗi class (không filter school_year)
        class_photos = {}
        if class_ids:
            photos = frappe.db.sql("""
                SELECT sp.name as photo_name, sp.class_id, sp.photo, sp.description
                FROM `tabSIS Photo` sp
                WHERE sp.class_id IN %(class_ids)s
                AND sp.type = 'class'
                ORDER BY sp.upload_date DESC
            """, {'class_ids': class_ids}, as_dict=True)
            
            # Nếu photo field là None, thử recover từ File attachment
            photo_names_to_recover = [p['photo_name'] for p in photos if not p.get('photo') and p.get('photo_name')]
            file_attachments = {}
            if photo_names_to_recover:
                files = frappe.db.sql("""
                    SELECT attached_to_name, file_url, file_name, is_private
                    FROM `tabFile`
                    WHERE attached_to_doctype = 'SIS Photo'
                    AND attached_to_name IN %(names)s
                    ORDER BY creation DESC
                """, {'names': photo_names_to_recover}, as_dict=True)
                for f in files:
                    if f['attached_to_name'] not in file_attachments:
                        file_attachments[f['attached_to_name']] = f
            
            for p in photos:
                # Chỉ lấy photo đầu tiên (mới nhất) cho mỗi class
                if p['class_id'] not in class_photos:
                    photo_url = p.get('photo')
                    
                    # Recover từ File attachment nếu photo field là None
                    if not photo_url and p.get('photo_name') in file_attachments:
                        f = file_attachments[p['photo_name']]
                        photo_url = f.get('file_url')
                        if not photo_url:
                            is_priv = bool(f.get('is_private'))
                            base_path = '/private/files' if is_priv else '/files'
                            photo_url = f"{base_path}/{f.get('file_name')}"
                    
                    # Fallback: recover từ description
                    if not photo_url and p.get('description'):
                        desc = p.get('description', '')
                        if ':' in desc:
                            candidate = desc.split(':', 1)[1].strip()
                            if candidate:
                                import os
                                import unicodedata
                                normalized = unicodedata.normalize('NFC', candidate)
                                public_path = frappe.get_site_path("public", "files", normalized)
                                if os.path.exists(public_path):
                                    photo_url = f"/files/{normalized}"
                    
                    if photo_url:
                        class_photos[p['class_id']] = photo_url
        
        # 6. Batch lấy current class cho students
        student_classes = {}
        if student_ids and school_year_ids:
            enrollments = frappe.db.sql("""
                SELECT cs.student_id, cs.school_year_id, cs.class_id, c.short_title
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                WHERE cs.student_id IN %(student_ids)s
                AND cs.school_year_id IN %(school_year_ids)s
                AND c.class_type = 'regular'
            """, {'student_ids': student_ids, 'school_year_ids': school_year_ids}, as_dict=True)
            
            for e in enrollments:
                key = (e['student_id'], e['school_year_id'])
                if key not in student_classes:
                    student_classes[key] = {'name': e['class_id'], 'title': e['short_title']}
        
        # 7. Batch lấy category info (chỉ cần lấy 1 lần nếu filter theo category)
        category_cache = {}
        category_ids = list(set([r['award_category'] for r in records]))
        for cat_id in category_ids:
            try:
                cat = frappe.get_doc('SIS Award Category', cat_id)
                # Build sub_category label_en map
                label_en_map = {}
                for sub in cat.sub_categories:
                    key = (sub.type, sub.label)
                    label_en_map[key] = sub.label_en or sub.label
                
                category_cache[cat_id] = {
                    'info': {
                        'name': cat.name,
                        'title_vn': cat.title_vn,
                        'title_en': cat.title_en
                    },
                    'label_en_map': label_en_map
                }
            except Exception as e:
                print(f"⚠️ Could not load category {cat_id}: {str(e)}")
        
        # ========== Gắn data vào records ==========
        # Group student entries by parent
        student_entries_by_record = {}
        for entry in all_student_entries:
            parent = entry['parent']
            if parent not in student_entries_by_record:
                student_entries_by_record[parent] = []
            student_entries_by_record[parent].append(entry)
        
        # Group class entries by parent
        class_entries_by_record = {}
        for entry in all_class_entries:
            parent = entry['parent']
            if parent not in class_entries_by_record:
                class_entries_by_record[parent] = []
            class_entries_by_record[parent].append(entry)
        
        # Populate records
        for record in records:
            school_year_id = record['school_year_id']
            
            # Process student entries
            students = []
            for entry in student_entries_by_record.get(record['name'], []):
                student_data = {
                    'student_id': entry['student_id'],
                    'note_vn': entry.get('note_vn'),
                    'note_en': entry.get('note_en'),
                    'exam': entry.get('exam'),
                    'score': entry.get('score'),
                    'student': {
                        'name': entry['student_name_id'],
                        'student_name': entry['student_name'],
                        'student_code': entry['student_code']
                    }
                }
                
                # Add current class
                class_key = (entry['student_id'], school_year_id)
                if class_key in student_classes:
                    student_data['current_class'] = student_classes[class_key]
                
                # Add photo
                photo_key = (entry['student_id'], school_year_id)
                if photo_key in student_photos:
                    student_data['photo'] = {'photoUrl': student_photos[photo_key]}
                
                # Parse activities
                if entry.get('activities_vn'):
                    try:
                        student_data['activities_vn'] = json.loads(entry['activities_vn'])
                    except:
                        pass
                if entry.get('activities_en'):
                    try:
                        student_data['activities_en'] = json.loads(entry['activities_en'])
                    except:
                        pass
                
                students.append(student_data)
            
            record['students'] = students
            
            # Process class entries
            classes = []
            for entry in class_entries_by_record.get(record['name'], []):
                class_data = {
                    'class_id': entry['class_id'],
                    'note_vn': entry.get('note_vn'),
                    'note_en': entry.get('note_en'),
                    'classInfo': {
                        'name': entry['class_name'],
                        'title': entry['class_title']
                    }
                }
                
                # Add class photo - dùng class_id làm key
                if entry['class_id'] in class_photos:
                    class_data['classImage'] = class_photos[entry['class_id']]
                
                classes.append(class_data)
            
            record['awardClasses'] = classes
            
            # Add category info
            cat_id = record['award_category']
            if cat_id in category_cache:
                record['awardCategory'] = category_cache[cat_id]['info']
                
                # Get label_en
                label_key = (record['sub_category_type'], record['sub_category_label'])
                label_en = category_cache[cat_id]['label_en_map'].get(label_key, record['sub_category_label'])
            else:
                record['awardCategory'] = {'name': cat_id, 'title_vn': '', 'title_en': ''}
                label_en = record['sub_category_label']
            
            record['subAward'] = {
                'type': record['sub_category_type'],
                'label': record['sub_category_label'],
                'label_en': label_en,
                'schoolYear': record['school_year_id'],
                'semester': record.get('semester'),
                'month': record.get('month'),
                'priority': record.get('priority', 0)
            }
        
        print(f"✅ [GET_AWARD_RECORDS] Done processing {len(records)} records")
        print("=" * 80)
        
        return success_response(
            data=records,
            message="Lấy danh sách bản ghi vinh danh thành công"
        )
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        frappe.log_error(f"Error getting award records: {str(e)}\n{error_details}")
        print("=" * 80)
        print(f"❌ [GET_AWARD_RECORDS] Error: {str(e)}")
        print(error_details)
        print("=" * 80)
        return error_response(
            message=f"Lỗi khi lấy danh sách bản ghi vinh danh: {str(e)}",
            code="GET_RECORDS_ERROR"
        )


@frappe.whitelist(allow_guest=True)
def get_award_record_detail(name: str):
    """Get single award record detail by name"""
    try:
        if not frappe.db.exists('SIS Award Record', name):
            return not_found_response(message="Không tìm thấy bản ghi vinh danh")
        
        record = frappe.get_doc('SIS Award Record', name)
        
        # Build response similar to get_award_records but for single record
        data = record.as_dict()
        
        # Lấy năm học hiện tại để dùng cho cả student và class photo fallback
        current_school_year = frappe.db.get_value(
            "SIS School Year",
            {"is_enable": 1},
            "name",
            order_by="start_date desc"
        )
        
        # Populate student entries
        student_entries = []
        for entry in record.student_entries:
            student = frappe.get_doc('CRM Student', entry.student_id)
            populated_entry = {
                'student_id': entry.student_id,
                'student': {
                    'name': student.name,
                    'student_name': student.student_name,
                    'student_code': student.student_code
                },
                'note_vn': entry.note_vn,
                'note_en': entry.note_en,
                'exam': entry.exam,
                'score': entry.score
            }
            
            # Get current class (chỉ lấy lớp regular, không lấy mixed/club)
            class_enrollment = frappe.db.sql("""
                SELECT cs.class_id
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                WHERE cs.student_id = %s 
                AND cs.school_year_id = %s
                AND c.class_type = 'regular'
                LIMIT 1
            """, (entry.student_id, record.school_year_id), as_dict=True)
            
            if class_enrollment:
                class_doc = frappe.get_doc('SIS Class', class_enrollment[0]['class_id'])
                populated_entry['current_class'] = {
                    'name': class_doc.name,
                    'title': class_doc.short_title  # Sử dụng short_title thay vì title
                }
            
            # Get photo - Ưu tiên: 1) Năm học của record, 2) Năm học hiện tại, 3) Ảnh mới nhất
            photo = frappe.db.sql("""
                SELECT photo
                FROM `tabSIS Photo`
                WHERE student_id = %s
                    AND type = 'student'
                    AND status = 'Active'
                ORDER BY 
                    CASE WHEN school_year_id = %s THEN 0
                         WHEN school_year_id = %s THEN 1
                         ELSE 2 END,
                    upload_date DESC,
                    creation DESC
                LIMIT 1
            """, (entry.student_id, record.school_year_id, current_school_year), as_dict=True)
            
            if photo:
                populated_entry['photo'] = {'photoUrl': photo[0]['photo']}
            
            # Parse activities
            if entry.activities_vn:
                try:
                    populated_entry['activities_vn'] = json.loads(entry.activities_vn)
                except:
                    populated_entry['activities_vn'] = []
            
            if entry.activities_en:
                try:
                    populated_entry['activities_en'] = json.loads(entry.activities_en)
                except:
                    populated_entry['activities_en'] = []
            
            student_entries.append(populated_entry)
        
        data['students'] = student_entries
        
        # Populate class entries
        class_entries = []
        for entry in record.class_entries:
            class_doc = frappe.get_doc('SIS Class', entry.class_id)
            populated_entry = {
                'class_id': entry.class_id,
                'classInfo': {
                    'name': class_doc.name,
                    'title': class_doc.short_title  # Sử dụng short_title thay vì title
                },
                'note_vn': entry.note_vn,
                'note_en': entry.note_en
            }
            
            # Get class photo - Ưu tiên: 1) Năm học của record, 2) Năm học hiện tại, 3) Ảnh mới nhất
            # Sử dụng current_school_year đã lấy từ trên
            photo = frappe.db.sql("""
                SELECT photo
                FROM `tabSIS Photo`
                WHERE class_id = %s
                    AND type = 'class'
                    AND status = 'Active'
                ORDER BY 
                    CASE WHEN school_year_id = %s THEN 0
                         WHEN school_year_id = %s THEN 1
                         ELSE 2 END,
                    upload_date DESC,
                    creation DESC
                LIMIT 1
            """, (entry.class_id, record.school_year_id, current_school_year), as_dict=True)
            
            if photo:
                populated_entry['classImage'] = photo[0]['photo']
            
            class_entries.append(populated_entry)
        
        data['awardClasses'] = class_entries
        
        return success_response(
            data=data,
            message="Lấy chi tiết bản ghi vinh danh thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting award record detail: {str(e)}")
        return error_response(
            message="Lỗi khi lấy chi tiết bản ghi vinh danh",
            code="GET_RECORD_DETAIL_ERROR"
        )


# ============================================
# ADMIN APIs (require authentication)
# ============================================

@frappe.whitelist(allow_guest=False)
def create_award_record():
    """Create a new award record"""
    try:
        # Lấy data từ JSON body
        # Frappe API có thể gửi data qua form_dict hoặc request body
        if frappe.request.data:
            # Parse JSON từ request body
            data = json.loads(frappe.request.data.decode('utf-8'))
        else:
            # Fallback to form_dict
            data = frappe.form_dict
        
        if not data or not isinstance(data, dict):
            return validation_error_response(
                message='Dữ liệu không hợp lệ',
                errors={'data': ['Data is required']}
            )
        
        # Get current campus
        campus_id = data.get('campus_id') or get_current_campus_from_context()
        
        if not campus_id:
            return validation_error_response(
                message='Thiếu thông tin campus',
                errors={'campus_id': ['Campus is required']}
            )
        
        # Validate required fields
        required_fields = ['award_category', 'school_year_id', 'sub_category_type', 'sub_category_label']
        errors = {}
        for field in required_fields:
            if not data.get(field):
                errors[field] = [f'{field} is required']
        
        if errors:
            return validation_error_response(
                message='Thiếu thông tin bắt buộc',
                errors=errors
            )
        
        # NOTE: Removed duplicate check - allow multiple records
        
        # Process student entries - convert activities arrays to JSON strings
        student_entries = _process_student_entries(data.get('student_entries', []))
        
        # Create record
        doc = frappe.get_doc({
            'doctype': 'SIS Award Record',
            'campus_id': campus_id,
            'award_category': data['award_category'],
            'school_year_id': data['school_year_id'],
            'sub_category_type': data['sub_category_type'],
            'sub_category_label': data['sub_category_label'],
            'semester': data.get('semester'),
            'month': data.get('month'),
            'priority': data.get('priority', 0),
            'student_entries': student_entries,
            'class_entries': data.get('class_entries', [])
        })
        
        doc.insert()
        frappe.db.commit()
        
        return success_response(
            data={'name': doc.name},
            message="Tạo bản ghi vinh danh thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"Error creating award record: {str(e)}")
        return error_response(
            message=str(e) or "Lỗi khi tạo bản ghi vinh danh",
            code="CREATE_RECORD_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_award_record():
    """Update an existing award record"""
    try:
        # Lấy toàn bộ data từ JSON body
        if frappe.request.data:
            form_data = json.loads(frappe.request.data.decode('utf-8'))
        else:
            form_data = frappe.form_dict
        name = form_data.get('name')
        
        if not name:
            return validation_error_response(
                message='Dữ liệu không hợp lệ',
                errors={'name': ['Record name is required']}
            )
        
        # Extract data fields (bỏ qua 'name')
        data = {k: v for k, v in form_data.items() if k != 'name'}
        
        if not frappe.db.exists('SIS Award Record', name):
            return not_found_response(message="Không tìm thấy bản ghi vinh danh")
        
        doc = frappe.get_doc('SIS Award Record', name)
        
        # Update fields
        updateable_fields = [
            'sub_category_type',
            'sub_category_label',
            'semester',
            'month',
            'priority'
        ]
        
        for field in updateable_fields:
            if field in data:
                setattr(doc, field, data[field])
        
        # Update student entries if provided
        if 'student_entries' in data:
            doc.student_entries = []
            # Convert activities arrays to JSON strings
            processed_entries = _process_student_entries(data['student_entries'])
            for entry_data in processed_entries:
                doc.append('student_entries', entry_data)
        
        # Update class entries if provided
        if 'class_entries' in data:
            doc.class_entries = []
            for entry_data in data['class_entries']:
                doc.append('class_entries', entry_data)
        
        doc.save()
        frappe.db.commit()
        
        return success_response(
            data={'name': doc.name},
            message="Cập nhật bản ghi vinh danh thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"Error updating award record: {str(e)}")
        return error_response(
            message=str(e) or "Lỗi khi cập nhật bản ghi vinh danh",
            code="UPDATE_RECORD_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_award_record():
    """Delete an award record"""
    try:
        # Lấy name từ JSON body
        if frappe.request.data:
            form_data = json.loads(frappe.request.data.decode('utf-8'))
            name = form_data.get('name')
        else:
            name = frappe.form_dict.get('name')
        
        if not name:
            return validation_error_response(
                message='Dữ liệu không hợp lệ',
                errors={'name': ['Record name is required']}
            )
        
        if not frappe.db.exists('SIS Award Record', name):
            return not_found_response(message="Không tìm thấy bản ghi vinh danh")
        
        frappe.delete_doc('SIS Award Record', name)
        frappe.db.commit()
        
        return success_response(
            message="Xóa bản ghi vinh danh thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"Error deleting award record: {str(e)}")
        return error_response(
            message="Lỗi khi xóa bản ghi vinh danh",
            code="DELETE_RECORD_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def bulk_import_students():
    """
    Bulk import students for an award
    Creates individual records for each student to avoid duplicate issues
    """
    try:
        # Lấy data từ JSON body hoặc form_dict
        if frappe.request.data and len(frappe.request.data) > 0:
            try:
                form_data = json.loads(frappe.request.data.decode('utf-8'))
            except json.JSONDecodeError:
                form_data = frappe.form_dict
        else:
            form_data = frappe.form_dict
        
        # Debug log
        print("=" * 80)
        print("🔍 [BULK_IMPORT_STUDENTS] form_data keys:", form_data.keys() if isinstance(form_data, dict) else type(form_data))
        print("🔍 [BULK_IMPORT_STUDENTS] form_data:", form_data)
        print("=" * 80)
            
        award_category = form_data.get('award_category')
        sub_category_data = form_data.get('sub_category_data')
        students_data = form_data.get('students_data')
        
        # Validate required fields
        if not award_category:
            return validation_error_response(
                message='Thiếu thông tin bắt buộc',
                errors={'award_category': ['Award category is required']}
            )
        
        if not sub_category_data:
            return validation_error_response(
                message='Thiếu thông tin bắt buộc',
                errors={'sub_category_data': ['Sub category data is required']}
            )
        
        if not students_data or not isinstance(students_data, list):
            return validation_error_response(
                message='Thiếu thông tin bắt buộc',
                errors={'students_data': ['Students data is required and must be an array']}
            )
        
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            return validation_error_response(
                message='Thiếu thông tin campus',
                errors={'campus_id': ['Campus is required']}
            )
        
        results = {
            'success': [],
            'errors': [],
            'summary': {
                'total': len(students_data),
                'successful': 0,
                'failed': 0
            }
        }
        
        for student_data in students_data:
            try:
                # Lookup student by student_code
                student_code = student_data.get('student_id')  # Frontend gửi student_code trong field này
                if not student_code:
                    results['errors'].append({
                        'student': student_data,
                        'error': 'Thiếu mã học sinh (Code)'
                    })
                    results['summary']['failed'] += 1
                    continue
                
                # Find student by student_code
                student_id = frappe.db.get_value('CRM Student', {'student_code': student_code}, 'name')
                if not student_id:
                    results['errors'].append({
                        'student': student_data,
                        'error': f'Không tìm thấy học sinh với mã: {student_code}'
                    })
                    results['summary']['failed'] += 1
                    continue
                
                # Update student_data với student ID thực sự
                student_entry = dict(student_data)
                student_entry['student_id'] = student_id
                
                # Convert activities arrays to JSON strings (DocType expects Small Text with JSON)
                student_entry = _convert_student_entry_activities(student_entry)
                
                # NOTE: Removed duplicate check - allow multiple awards for same student
                
                # Create new record for this student
                doc = frappe.get_doc({
                    'doctype': 'SIS Award Record',
                    'campus_id': campus_id,
                    'award_category': award_category,
                    'school_year_id': sub_category_data['school_year_id'],
                    'sub_category_type': sub_category_data['type'],
                    'sub_category_label': sub_category_data['label'],
                    'priority': sub_category_data.get('priority', 0),
                    'student_entries': [student_entry]
                })
                
                doc.insert()
                
                results['success'].append({
                    'student': student_data,
                    'record_id': doc.name
                })
                results['summary']['successful'] += 1
                
            except Exception as e:
                results['errors'].append({
                    'student': student_data,
                    'error': str(e)
                })
                results['summary']['failed'] += 1
        
        frappe.db.commit()
        
        return success_response(
            data=results,
            message=f"Đã import {results['summary']['successful']}/{results['summary']['total']} học sinh"
        )
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        frappe.log_error(f"Error bulk importing students: {str(e)}\n{error_details}")
        print("=" * 80)
        print(f"❌ [BULK_IMPORT_STUDENTS] Error: {str(e)}")
        print(error_details)
        print("=" * 80)
        return error_response(
            message=f"Lỗi khi import hàng loạt học sinh: {str(e)}",
            code="BULK_IMPORT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def bulk_import_classes():
    """
    Bulk import classes for an award
    Creates individual records for each class
    """
    try:
        # Lấy data từ JSON body hoặc form_dict
        if frappe.request.data and len(frappe.request.data) > 0:
            try:
                form_data = json.loads(frappe.request.data.decode('utf-8'))
            except json.JSONDecodeError:
                form_data = frappe.form_dict
        else:
            form_data = frappe.form_dict
            
        award_category = form_data.get('award_category')
        sub_category_data = form_data.get('sub_category_data')
        classes_data = form_data.get('classes_data')
        
        # Validate required fields
        if not award_category:
            return validation_error_response(
                message='Thiếu thông tin bắt buộc',
                errors={'award_category': ['Award category is required']}
            )
        
        if not sub_category_data:
            return validation_error_response(
                message='Thiếu thông tin bắt buộc',
                errors={'sub_category_data': ['Sub category data is required']}
            )
        
        if not classes_data or not isinstance(classes_data, list):
            return validation_error_response(
                message='Thiếu thông tin bắt buộc',
                errors={'classes_data': ['Classes data is required and must be an array']}
            )
        
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            return validation_error_response(
                message='Thiếu thông tin campus',
                errors={'campus_id': ['Campus is required']}
            )
        
        results = {
            'success': [],
            'errors': [],
            'summary': {
                'total': len(classes_data),
                'successful': 0,
                'failed': 0
            }
        }
        
        for class_data in classes_data:
            try:
                # Lookup class by short_title
                class_short_title = class_data.get('class_id')  # Frontend gửi short_title trong field này
                if not class_short_title:
                    results['errors'].append({
                        'class': class_data,
                        'error': 'Thiếu mã lớp (Code)'
                    })
                    results['summary']['failed'] += 1
                    continue
                
                # Find class by short_title
                class_id = frappe.db.get_value('SIS Class', {'short_title': class_short_title}, 'name')
                if not class_id:
                    results['errors'].append({
                        'class': class_data,
                        'error': f'Không tìm thấy lớp với mã: {class_short_title}'
                    })
                    results['summary']['failed'] += 1
                    continue
                
                # Update class_data với class ID thực sự
                class_entry = dict(class_data)
                class_entry['class_id'] = class_id
                
                # NOTE: Removed duplicate check - allow multiple awards for same class
                
                # Create new record for this class
                doc = frappe.get_doc({
                    'doctype': 'SIS Award Record',
                    'campus_id': campus_id,
                    'award_category': award_category,
                    'school_year_id': sub_category_data['school_year_id'],
                    'sub_category_type': sub_category_data['type'],
                    'sub_category_label': sub_category_data['label'],
                    'priority': sub_category_data.get('priority', 0),
                    'class_entries': [class_entry]
                })
                
                doc.insert()
                
                results['success'].append({
                    'class': class_data,
                    'record_id': doc.name
                })
                results['summary']['successful'] += 1
                
            except Exception as e:
                results['errors'].append({
                    'class': class_data,
                    'error': str(e)
                })
                results['summary']['failed'] += 1
        
        frappe.db.commit()
        
        return success_response(
            data=results,
            message=f"Đã import {results['summary']['successful']}/{results['summary']['total']} lớp"
        )
        
    except Exception as e:
        frappe.log_error(f"Error bulk importing classes: {str(e)}")
        return error_response(
            message="Lỗi khi import hàng loạt lớp",
            code="BULK_IMPORT_CLASSES_ERROR"
        )


@frappe.whitelist(allow_guest=True)
def get_school_years():
    """Get all school years for dropdown - Allow guest access for public Hall of Honor page"""
    try:
        # Cố gắng lấy campus_id từ context, nhưng không bắt buộc (vì allow_guest=True)
        campus_id = None
        try:
            campus_id = get_current_campus_from_context()
        except:
            pass  # Guest không có campus context, lấy tất cả school years
        
        filters = {}
        if campus_id:
            filters['campus_id'] = campus_id
        
        school_years = frappe.get_all(
            'SIS School Year',
            filters=filters,
            fields=['name', 'title_vn', 'title_en', 'start_date', 'end_date', 'is_enable'],
            order_by='start_date desc'
        )
        
        return success_response(
            data=school_years,
            message="Lấy danh sách năm học thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting school years: {str(e)}")
        return error_response(
            message="Lỗi khi lấy danh sách năm học",
            code="GET_SCHOOL_YEARS_ERROR"
        )
