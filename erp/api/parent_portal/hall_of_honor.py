"""
Parent Portal Hall of Honor API
Lấy danh sách vinh danh của học sinh, nhóm theo năm học
"""

import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response, validation_error_response


@frappe.whitelist()
def get_student_honors():
    """
    Lấy tất cả vinh danh của một học sinh, nhóm theo năm học.
    
    Args:
        student_id: CRM Student document name - truyền qua frappe.form_dict
        
    Returns:
        dict: Danh sách vinh danh nhóm theo năm học
        {
            "success": True,
            "data": [
                {
                    "school_year_id": "SY-2024-2025",
                    "school_year_title_vn": "Năm học 2024-2025",
                    "school_year_title_en": "Academic Year 2024-2025",
                    "honors": [
                        {
                            "category_name": "SIS-AWARD-CAT-00001",
                            "category_title_vn": "Học sinh giỏi",
                            "category_title_en": "Outstanding Student",
                            "sub_category_label": "Học kỳ 1",
                            "sub_category_label_en": "Semester 1",
                            "sub_category_type": "semester",
                            "note_vn": "...",
                            "note_en": "..."
                        }
                    ]
                }
            ]
        }
    """
    logs = []
    
    try:
        # Lấy student_id từ form_dict hoặc request args
        student_id = frappe.form_dict.get('student_id')
        
        if not student_id:
            student_id = frappe.request.args.get('student_id') if hasattr(frappe.request, 'args') else None
        
        if not student_id:
            return validation_error_response(
                "Student ID is required",
                {"student_id": ["Required"]}
            )
        
        logs.append(f"🔍 Đang lấy vinh danh cho học sinh: {student_id}")
        
        # Kiểm tra học sinh tồn tại
        if not frappe.db.exists('CRM Student', student_id):
            return error_response(
                message="Không tìm thấy học sinh",
                code="STUDENT_NOT_FOUND"
            )
        
        # Query tất cả vinh danh của học sinh
        # Join: SIS Award Student Entry -> SIS Award Record -> SIS Award Category
        honors_data = frappe.db.sql("""
            SELECT 
                se.student_id,
                se.note_vn,
                se.note_en,
                se.exam,
                se.score,
                ar.name as record_name,
                ar.school_year_id,
                ar.award_category,
                ar.sub_category_type,
                ar.sub_category_label,
                ar.priority,
                ac.title_vn as category_title_vn,
                ac.title_en as category_title_en,
                ac.name as category_name
            FROM `tabSIS Award Student Entry` se
            INNER JOIN `tabSIS Award Record` ar ON ar.name = se.parent
            INNER JOIN `tabSIS Award Category` ac ON ac.name = ar.award_category
            WHERE se.student_id = %(student_id)s
                AND ar.is_active = 1
                AND ac.is_active = 1
            ORDER BY ar.school_year_id DESC, ar.priority ASC, ac.title_vn ASC
        """, {"student_id": student_id}, as_dict=True)
        
        logs.append(f"✅ Tìm thấy {len(honors_data)} bản ghi vinh danh")
        
        if not honors_data:
            return success_response(
                data=[],
                message="Học sinh chưa có vinh danh nào"
            )
        
        # Lấy danh sách school_year_ids để batch query
        school_year_ids = list(set([h['school_year_id'] for h in honors_data if h.get('school_year_id')]))
        
        # Lấy thông tin năm học
        school_years_map = {}
        if school_year_ids:
            school_years = frappe.db.sql("""
                SELECT name, title_vn, title_en
                FROM `tabSIS School Year`
                WHERE name IN %(school_year_ids)s
            """, {"school_year_ids": school_year_ids}, as_dict=True)
            
            for sy in school_years:
                school_years_map[sy['name']] = {
                    'title_vn': sy['title_vn'],
                    'title_en': sy['title_en']
                }
        
        # Lấy sub_category label_en từ Award Category
        # Build map: (category_name, sub_category_type, sub_category_label) -> label_en
        category_names = list(set([h['category_name'] for h in honors_data]))
        sub_category_label_en_map = {}
        
        if category_names:
            sub_categories = frappe.db.sql("""
                SELECT 
                    parent,
                    type,
                    label,
                    label_en
                FROM `tabSIS Award Sub Category`
                WHERE parent IN %(category_names)s
            """, {"category_names": category_names}, as_dict=True)
            
            for sc in sub_categories:
                key = (sc['parent'], sc['type'], sc['label'])
                sub_category_label_en_map[key] = sc['label_en'] or sc['label']
        
        # Nhóm dữ liệu theo năm học
        grouped_data = {}
        
        for honor in honors_data:
            school_year_id = honor['school_year_id']
            
            if school_year_id not in grouped_data:
                sy_info = school_years_map.get(school_year_id, {})
                grouped_data[school_year_id] = {
                    'school_year_id': school_year_id,
                    'school_year_title_vn': sy_info.get('title_vn', school_year_id),
                    'school_year_title_en': sy_info.get('title_en', school_year_id),
                    'honors': []
                }
            
            # Lấy sub_category_label_en
            label_en_key = (honor['category_name'], honor['sub_category_type'], honor['sub_category_label'])
            sub_category_label_en = sub_category_label_en_map.get(label_en_key, honor['sub_category_label'])
            
            honor_item = {
                'category_name': honor['category_name'],
                'category_title_vn': honor['category_title_vn'],
                'category_title_en': honor['category_title_en'],
                'sub_category_label': honor['sub_category_label'],
                'sub_category_label_en': sub_category_label_en,
                'sub_category_type': honor['sub_category_type'],
                'note_vn': honor.get('note_vn'),
                'note_en': honor.get('note_en'),
                'exam': honor.get('exam'),
                'score': honor.get('score'),
                'priority': honor.get('priority', 0)
            }
            
            grouped_data[school_year_id]['honors'].append(honor_item)
        
        # Chuyển thành list, sắp xếp theo năm học giảm dần (năm mới nhất lên trước)
        result = list(grouped_data.values())
        result.sort(key=lambda x: x['school_year_id'], reverse=True)
        
        logs.append(f"✅ Đã nhóm thành {len(result)} năm học")
        
        return success_response(
            data=result,
            message=f"Lấy danh sách vinh danh thành công"
        )
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        frappe.log_error(f"Error getting student honors: {str(e)}\n{error_details}")
        logs.append(f"❌ Lỗi: {str(e)}")
        
        return error_response(
            message=f"Lỗi khi lấy danh sách vinh danh: {str(e)}",
            code="GET_STUDENT_HONORS_ERROR"
        )
