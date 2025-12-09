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
                    'priority'
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
    Get award records with filters
    Allow guest access for public Hall of Honor page
    Returns populated student and class data
    """
    try:
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
        
        # Populate full data for each record
        for record in records:
            # Get student entries with populated data
            student_entries = frappe.get_all(
                'SIS Award Student Entry',
                filters={'parent': record['name']},
                fields=[
                    'student_id',
                    'note_vn',
                    'note_en',
                    'activities_vn',
                    'activities_en',
                    'exam',
                    'score'
                ]
            )
            
            # Populate student data
            for entry in student_entries:
                student = frappe.get_doc('CRM Student', entry['student_id'])
                entry['student'] = {
                    'name': student.name,
                    'student_name': student.student_name,
                    'student_code': student.student_code,
                    'email': student.email
                }
                
                # Get current class from SIS Class Student
                class_enrollment = frappe.get_all(
                    'SIS Class Student',
                    filters={
                        'student_id': entry['student_id'],
                        'school_year_id': record['school_year_id']
                    },
                    fields=['class_id'],
                    limit=1
                )
                
                if class_enrollment:
                    class_doc = frappe.get_doc('SIS Class', class_enrollment[0]['class_id'])
                    entry['current_class'] = {
                        'name': class_doc.name,
                        'title': class_doc.title
                    }
                
                # Get photo
                photo = frappe.get_all(
                    'SIS Photo',
                    filters={
                        'student_id': entry['student_id'],
                        'school_year_id': record['school_year_id'],
                        'type': 'student'
                    },
                    fields=['photo'],
                    order_by='upload_date desc',
                    limit=1
                )
                
                if photo:
                    entry['photo'] = {'photoUrl': photo[0]['photo']}
                
                # Parse JSON arrays for activities
                if entry.get('activities_vn'):
                    try:
                        entry['activities_vn'] = json.loads(entry['activities_vn'])
                    except:
                        pass
                
                if entry.get('activities_en'):
                    try:
                        entry['activities_en'] = json.loads(entry['activities_en'])
                    except:
                        pass
            
            record['students'] = student_entries
            
            # Get class entries with populated data
            class_entries = frappe.get_all(
                'SIS Award Class Entry',
                filters={'parent': record['name']},
                fields=[
                    'class_id',
                    'note_vn',
                    'note_en'
                ]
            )
            
            # Populate class data
            for entry in class_entries:
                class_doc = frappe.get_doc('SIS Class', entry['class_id'])
                entry['classInfo'] = {
                    'name': class_doc.name,
                    'title': class_doc.title
                }
                
                # Get class photo
                photo = frappe.get_all(
                    'SIS Photo',
                    filters={
                        'class_id': entry['class_id'],
                        'school_year_id': record['school_year_id'],
                        'type': 'class'
                    },
                    fields=['photo'],
                    order_by='upload_date desc',
                    limit=1
                )
                
                if photo:
                    entry['classImage'] = photo[0]['photo']
            
            record['awardClasses'] = class_entries
            
            # Get category info
            category = frappe.get_doc('SIS Award Category', record['award_category'])
            record['awardCategory'] = {
                'name': category.name,
                'title_vn': category.title_vn,
                'title_en': category.title_en
            }
            
            # Get school year info
            school_year = frappe.get_doc('SIS School Year', record['school_year_id'])
            record['subAward'] = {
                'type': record['sub_category_type'],
                'label': record['sub_category_label'],
                'schoolYear': record['school_year_id'],
                'semester': record.get('semester'),
                'month': record.get('month'),
                'priority': record.get('priority', 0)
            }
        
        return success_response(
            data=records,
            message="Lấy danh sách bản ghi vinh danh thành công"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting award records: {str(e)}")
        return error_response(
            message="Lỗi khi lấy danh sách bản ghi vinh danh",
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
            
            # Get current class
            class_enrollment = frappe.get_all(
                'SIS Class Student',
                filters={
                    'student_id': entry.student_id,
                    'school_year_id': record.school_year_id
                },
                fields=['class_id'],
                limit=1
            )
            
            if class_enrollment:
                class_doc = frappe.get_doc('SIS Class', class_enrollment[0]['class_id'])
                populated_entry['current_class'] = {
                    'name': class_doc.name,
                    'title': class_doc.title
                }
            
            # Get photo
            photo = frappe.get_all(
                'SIS Photo',
                filters={
                    'student_id': entry.student_id,
                    'school_year_id': record.school_year_id,
                    'type': 'student'
                },
                fields=['photo'],
                order_by='upload_date desc',
                limit=1
            )
            
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
                    'title': class_doc.title
                },
                'note_vn': entry.note_vn,
                'note_en': entry.note_en
            }
            
            # Get class photo
            photo = frappe.get_all(
                'SIS Photo',
                filters={
                    'class_id': entry.class_id,
                    'school_year_id': record.school_year_id,
                    'type': 'class'
                },
                fields=['photo'],
                order_by='upload_date desc',
                limit=1
            )
            
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
def create_award_record(data: dict):
    """Create a new award record"""
    try:
        if isinstance(data, str):
            data = json.loads(data)
        
        # Get current campus
        campus_id = data.get('campus_id') or get_current_campus_from_context()
        
        if not campus_id:
            return validation_error_response(
                errors={'campus_id': ['Campus is required']}
            )
        
        # Validate required fields
        required_fields = ['award_category', 'school_year_id', 'sub_category_type', 'sub_category_label']
        errors = {}
        for field in required_fields:
            if not data.get(field):
                errors[field] = [f'{field} is required']
        
        if errors:
            return validation_error_response(errors=errors)
        
        # Check for duplicate records
        existing = frappe.get_all(
            'SIS Award Record',
            filters={
                'award_category': data['award_category'],
                'school_year_id': data['school_year_id'],
                'sub_category_type': data['sub_category_type'],
                'sub_category_label': data['sub_category_label'],
                'semester': data.get('semester'),
                'month': data.get('month')
            },
            limit=1
        )
        
        if existing:
            return error_response(
                message="Bản ghi vinh danh này đã tồn tại",
                code="DUPLICATE_RECORD"
            )
        
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
            'student_entries': data.get('student_entries', []),
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
def update_award_record(name: str, data: dict):
    """Update an existing award record"""
    try:
        if isinstance(data, str):
            data = json.loads(data)
        
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
            for entry_data in data['student_entries']:
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
def delete_award_record(name: str):
    """Delete an award record"""
    try:
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
def bulk_import_students(award_category: str, sub_category_data: dict, students_data: list):
    """
    Bulk import students for an award
    Creates individual records for each student to avoid duplicate issues
    """
    try:
        if isinstance(sub_category_data, str):
            sub_category_data = json.loads(sub_category_data)
        
        if isinstance(students_data, str):
            students_data = json.loads(students_data)
        
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            return validation_error_response(
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
                # Check if student exists in CRM Student
                if not frappe.db.exists('CRM Student', student_data.get('student_id')):
                    results['errors'].append({
                        'student': student_data,
                        'error': 'Không tìm thấy học sinh trong hệ thống'
                    })
                    results['summary']['failed'] += 1
                    continue
                
                # Check for duplicate
                existing = frappe.get_all(
                    'SIS Award Record',
                    filters={
                        'award_category': award_category,
                        'school_year_id': sub_category_data['school_year_id'],
                        'sub_category_type': sub_category_data['type'],
                        'sub_category_label': sub_category_data['label']
                    }
                )
                
                # Check if student already exists in any of these records
                duplicate_found = False
                for rec in existing:
                    rec_doc = frappe.get_doc('SIS Award Record', rec['name'])
                    for entry in rec_doc.student_entries:
                        if entry.student_id == student_data.get('student_id'):
                            duplicate_found = True
                            break
                    if duplicate_found:
                        break
                
                if duplicate_found:
                    results['errors'].append({
                        'student': student_data,
                        'error': 'Học sinh đã có trong danh sách vinh danh này'
                    })
                    results['summary']['failed'] += 1
                    continue
                
                # Create new record for this student
                doc = frappe.get_doc({
                    'doctype': 'SIS Award Record',
                    'campus_id': campus_id,
                    'award_category': award_category,
                    'school_year_id': sub_category_data['school_year_id'],
                    'sub_category_type': sub_category_data['type'],
                    'sub_category_label': sub_category_data['label'],
                    'semester': sub_category_data.get('semester'),
                    'month': sub_category_data.get('month'),
                    'priority': sub_category_data.get('priority', 0),
                    'student_entries': [student_data]
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
        frappe.log_error(f"Error bulk importing students: {str(e)}")
        return error_response(
            message="Lỗi khi import hàng loạt học sinh",
            code="BULK_IMPORT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def bulk_import_classes(award_category: str, sub_category_data: dict, classes_data: list):
    """
    Bulk import classes for an award
    Creates individual records for each class
    """
    try:
        if isinstance(sub_category_data, str):
            sub_category_data = json.loads(sub_category_data)
        
        if isinstance(classes_data, str):
            classes_data = json.loads(classes_data)
        
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            return validation_error_response(
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
                # Check if class exists
                if not frappe.db.exists('SIS Class', class_data.get('class_id')):
                    results['errors'].append({
                        'class': class_data,
                        'error': 'Không tìm thấy lớp trong hệ thống'
                    })
                    results['summary']['failed'] += 1
                    continue
                
                # Check for duplicate
                existing = frappe.get_all(
                    'SIS Award Record',
                    filters={
                        'award_category': award_category,
                        'school_year_id': sub_category_data['school_year_id'],
                        'sub_category_type': sub_category_data['type'],
                        'sub_category_label': sub_category_data['label']
                    }
                )
                
                # Check if class already exists
                duplicate_found = False
                for rec in existing:
                    rec_doc = frappe.get_doc('SIS Award Record', rec['name'])
                    for entry in rec_doc.class_entries:
                        if entry.class_id == class_data.get('class_id'):
                            duplicate_found = True
                            break
                    if duplicate_found:
                        break
                
                if duplicate_found:
                    results['errors'].append({
                        'class': class_data,
                        'error': 'Lớp đã có trong danh sách vinh danh này'
                    })
                    results['summary']['failed'] += 1
                    continue
                
                # Create new record for this class
                doc = frappe.get_doc({
                    'doctype': 'SIS Award Record',
                    'campus_id': campus_id,
                    'award_category': award_category,
                    'school_year_id': sub_category_data['school_year_id'],
                    'sub_category_type': sub_category_data['type'],
                    'sub_category_label': sub_category_data['label'],
                    'semester': sub_category_data.get('semester'),
                    'month': sub_category_data.get('month'),
                    'priority': sub_category_data.get('priority', 0),
                    'class_entries': [class_data]
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


@frappe.whitelist(allow_guest=False)
def get_school_years():
    """Get all school years for dropdown"""
    try:
        campus_id = get_current_campus_from_context()
        
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
