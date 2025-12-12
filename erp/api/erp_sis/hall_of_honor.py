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
                    'student_code': student.student_code
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
            
        award_category = form_data.get('award_category')
        sub_category_data = form_data.get('sub_category_data')
        students_data = form_data.get('students_data')
        
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
