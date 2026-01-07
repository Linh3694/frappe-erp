"""
Parent Portal Re-enrollment API
Handles re-enrollment submission for parent portal

API endpoints cho phụ huynh nộp đơn tái ghi danh qua Parent Portal.
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, now
import json
from erp.utils.api_response import (
    validation_error_response, 
    list_response, 
    error_response, 
    success_response, 
    single_item_response,
    not_found_response
)

# Decision types cho tái ghi danh
DECISION_TYPES = ['re_enroll', 'considering', 'not_re_enroll']


def _get_current_parent():
    """Lấy thông tin phụ huynh đang đăng nhập"""
    user_email = frappe.session.user
    if user_email == "Guest":
        return None

    # Format email: guardian_id@parent.wellspring.edu.vn
    if "@parent.wellspring.edu.vn" not in user_email:
        return None

    guardian_id = user_email.split("@")[0]

    # Lấy guardian name từ guardian_id
    guardian = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
    return guardian


def _get_parent_students(parent_id):
    """
    Lấy danh sách học sinh của phụ huynh.
    Trả về list các student với thông tin lớp hiện tại.
    Loại bỏ duplicate students.
    """
    if not parent_id:
        return []
    
    # Query CRM Family Relationship để lấy danh sách học sinh
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": parent_id},
        fields=["student", "relationship_type", "key_person"]
    )
    
    # Dùng dict để loại bỏ duplicate theo student ID
    students_dict = {}
    for rel in relationships:
        # Bỏ qua nếu đã có student này
        if rel.student in students_dict:
            continue
            
        try:
            student = frappe.get_doc("CRM Student", rel.student)
            
            # Lấy lớp hiện tại
            current_class = _get_student_current_class(student.name, student.campus_id)
            
            # Lấy ảnh học sinh từ SIS Photo (giống logic trong otp_auth.py)
            sis_photo = None
            try:
                # Lấy năm học hiện tại đang active
                current_school_year = frappe.db.get_value(
                    "SIS School Year",
                    {"is_enable": 1},
                    "name",
                    order_by="start_date desc"
                )
                
                # Ưu tiên: 1) Năm học hiện tại trước, 2) Upload date mới nhất, 3) Creation mới nhất
                sis_photos = frappe.db.sql("""
                    SELECT photo, title, upload_date, school_year_id
                    FROM `tabSIS Photo`
                    WHERE student_id = %s
                        AND type = 'student'
                        AND status = 'Active'
                    ORDER BY 
                        CASE WHEN school_year_id = %s THEN 0 ELSE 1 END,
                        upload_date DESC,
                        creation DESC
                    LIMIT 1
                """, (student.name, current_school_year), as_dict=True)

                if sis_photos:
                    sis_photo = sis_photos[0]["photo"]
            except Exception as photo_err:
                frappe.logger().error(f"Error getting sis_photo for {student.name}: {str(photo_err)}")
            
            students_dict[student.name] = {
                "name": student.name,
                "student_name": student.student_name,
                "student_code": student.student_code,
                "campus_id": student.campus_id,
                "current_class": current_class.get("class_title") if current_class else None,
                "current_class_id": current_class.get("class_id") if current_class else None,
                "relationship_type": rel.relationship_type,
                "is_key_person": rel.key_person,
                "sis_photo": sis_photo
            }
        except Exception as e:
            frappe.logger().error(f"Error getting student {rel.student}: {str(e)}")
            continue
    
    return list(students_dict.values())


def _get_student_current_class(student_id, campus_id=None):
    """Lấy lớp hiện tại của học sinh"""
    if not student_id:
        return None
    
    # Lấy campus_id nếu chưa có
    if not campus_id:
        campus_id = frappe.db.get_value("CRM Student", student_id, "campus_id")
    
    if not campus_id:
        return None
    
    # Lấy năm học hiện tại (đang active)
    current_school_year = frappe.db.get_value(
        "SIS School Year",
        {"is_enable": 1, "campus_id": campus_id},
        "name",
        order_by="start_date desc"
    )
    
    if not current_school_year:
        return None
    
    # Tìm lớp regular của học sinh
    class_student = frappe.db.sql("""
        SELECT cs.class_id, c.title as class_title
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
        WHERE cs.student_id = %s
        AND cs.school_year_id = %s
        AND (c.class_type = 'regular' OR c.class_type IS NULL OR c.class_type = '')
        LIMIT 1
    """, (student_id, current_school_year), as_dict=True)
    
    if class_student:
        return {
            "class_id": class_student[0].class_id,
            "class_title": class_student[0].class_title
        }
    
    return None


@frappe.whitelist()
def get_active_config():
    """
    Lấy cấu hình tái ghi danh đang mở cho campus của phụ huynh.
    Trả về config với đầy đủ thông tin bao gồm bảng ưu đãi.
    """
    logs = []
    
    try:
        logs.append("Đang lấy cấu hình tái ghi danh đang mở")
        
        # Lấy thông tin phụ huynh
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent ID: {parent_id}")
        
        # Lấy danh sách học sinh của phụ huynh
        students = _get_parent_students(parent_id)
        if not students:
            return error_response("Không tìm thấy học sinh", logs=logs)
        
        # Lấy campus_id từ học sinh đầu tiên
        campus_id = students[0].get("campus_id") if students else None
        
        if not campus_id:
            return error_response("Không xác định được campus", logs=logs)
        
        logs.append(f"Campus: {campus_id}")
        
        # Tìm config đang active cho campus này
        config = frappe.db.get_value(
            "SIS Re-enrollment Config",
            {
                "is_active": 1,
                "campus_id": campus_id
            },
            ["name", "title", "school_year_id", "campus_id", "start_date", "end_date",
             "service_document", "service_document_images", "agreement_text", "agreement_text_en"],
            as_dict=True
        )
        
        if not config:
            logs.append("Không có đợt tái ghi danh nào đang mở")
            return success_response(
                data=None,
                message="Không có đợt tái ghi danh nào đang mở",
                logs=logs
            )
        
        # Kiểm tra thời gian
        today = getdate(nowdate())
        start_date = getdate(config.start_date) if config.start_date else None
        end_date = getdate(config.end_date) if config.end_date else None
        
        if start_date and today < start_date:
            logs.append(f"Chưa đến thời gian tái ghi danh. Bắt đầu: {config.start_date}")
            return success_response(
                data={
                    "status": "not_started",
                    "start_date": str(config.start_date),
                    "message": f"Đợt tái ghi danh sẽ bắt đầu từ ngày {config.start_date}"
                },
                message="Chưa đến thời gian tái ghi danh",
                logs=logs
            )
        
        if end_date and today > end_date:
            logs.append(f"Đã hết thời gian tái ghi danh. Kết thúc: {config.end_date}")
            return success_response(
                data={
                    "status": "ended",
                    "end_date": str(config.end_date),
                    "message": f"Đợt tái ghi danh đã kết thúc ngày {config.end_date}"
                },
                message="Đã hết thời gian tái ghi danh",
                logs=logs
            )
        
        # Lấy bảng ưu đãi
        discounts = frappe.get_all(
            "SIS Re-enrollment Discount",
            filters={"parent": config.name},
            fields=["name", "deadline", "description", "annual_discount", "semester_discount"],
            order_by="deadline asc"
        )
        
        # Lấy câu hỏi khảo sát
        questions = []
        question_rows = frappe.get_all(
            "SIS Re-enrollment Question",
            filters={"parent": config.name},
            fields=["name", "question_vn", "question_en", "question_type", "is_required", "sort_order", "options_json"],
            order_by="sort_order asc"
        )
        
        for q in question_rows:
            # Parse options từ JSON
            options = []
            if q.options_json:
                try:
                    options = json.loads(q.options_json)
                except json.JSONDecodeError:
                    options = []
            
            questions.append({
                "name": q.name,
                "question_vn": q.question_vn,
                "question_en": q.question_en,
                "question_type": q.question_type,
                "is_required": q.is_required,
                "sort_order": q.sort_order,
                "options": options
            })
        
        # Parse service_document_images từ JSON
        service_document_images = []
        if config.service_document_images:
            try:
                service_document_images = json.loads(config.service_document_images)
            except json.JSONDecodeError:
                service_document_images = []
        
        # Lấy tên năm học
        school_year_name = frappe.db.get_value(
            "SIS School Year", 
            config.school_year_id, 
            ["title_vn", "title_en"],
            as_dict=True
        )
        
        # Tìm mức ưu đãi hiện tại
        current_discount = None
        for discount in discounts:
            if today <= getdate(discount.deadline):
                current_discount = discount
                break
        
        # Kiểm tra xem các học sinh đã nộp đơn chưa
        # Lưu ý: Bản ghi SIS Re-enrollment được tạo sẵn khi admin tạo đợt
        # PHHS "đã nộp" khi họ điền form và submit -> có submitted_at
        logs.append(f"Checking submissions for {len(students)} students, config: {config.name}")
        for student in students:
            # Tìm bản ghi của học sinh
            existing = frappe.db.get_value(
                "SIS Re-enrollment",
                {
                    "student_id": student["name"],
                    "config_id": config.name
                },
                ["name", "decision", "payment_type", "status", "submitted_at"],
                as_dict=True
            )
            
            if existing:
                # Đã nộp = có submitted_at (PHHS đã điền form)
                student["has_submitted"] = bool(existing.submitted_at)
                student["submission"] = existing if existing.submitted_at else None
                student["re_enrollment_id"] = existing.name  # ID để update khi submit
                logs.append(f"Student {student['name']} - record: {existing.name}, submitted_at: {existing.submitted_at}")
            else:
                student["has_submitted"] = False
                student["submission"] = None
                student["re_enrollment_id"] = None
                logs.append(f"Student {student['name']} - no record found")
        
        logs.append(f"Tìm thấy config: {config.name}")
        
        return success_response(
            data={
                "config": {
                    "name": config.name,
                    "title": config.title,
                    "school_year_id": config.school_year_id,
                    "school_year_name_vn": school_year_name.title_vn if school_year_name else None,
                    "school_year_name_en": school_year_name.title_en if school_year_name else None,
                    "start_date": str(config.start_date),
                    "end_date": str(config.end_date),
                    "service_document": config.service_document,
                    "service_document_images": service_document_images,
                    "agreement_text": config.agreement_text,
                    "agreement_text_en": config.agreement_text_en
                },
                "discounts": discounts,
                "current_discount": current_discount,
                "questions": questions,
                "students": students,
                "status": "open"
            },
            message="Lấy cấu hình tái ghi danh thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Re-enrollment Config Error")
        return error_response(
            message=f"Lỗi khi lấy cấu hình tái ghi danh: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_student_re_enrollment(student_id=None):
    """
    Lấy đơn tái ghi danh của học sinh (nếu có).
    Dùng để kiểm tra học sinh đã nộp đơn chưa.
    """
    logs = []
    
    try:
        # Lấy student_id từ query params nếu không truyền vào
        if not student_id:
            student_id = frappe.request.args.get('student_id')
        
        if not student_id:
            return validation_error_response(
                "Thiếu student_id", 
                {"student_id": ["Student ID là bắt buộc"]}
            )
        
        logs.append(f"Kiểm tra đơn tái ghi danh cho học sinh: {student_id}")
        
        # Kiểm tra phụ huynh có quyền xem không
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        # Kiểm tra học sinh có thuộc phụ huynh này không
        relationship = frappe.db.exists(
            "CRM Family Relationship",
            {"guardian": parent_id, "student": student_id}
        )
        
        if not relationship:
            return error_response("Bạn không có quyền xem thông tin học sinh này", logs=logs)
        
        # Tìm config đang active
        campus_id = frappe.db.get_value("CRM Student", student_id, "campus_id")
        config = frappe.db.get_value(
            "SIS Re-enrollment Config",
            {"is_active": 1, "campus_id": campus_id},
            "name"
        )
        
        if not config:
            return success_response(
                data=None,
                message="Không có đợt tái ghi danh nào đang mở",
                logs=logs
            )
        
        # Tìm đơn đã nộp
        submission = frappe.db.get_value(
            "SIS Re-enrollment",
            {"student_id": student_id, "config_id": config},
            ["name", "decision", "payment_type", "not_re_enroll_reason", 
             "status", "submitted_at", "current_class"],
            as_dict=True
        )
        
        if not submission:
            return success_response(
                data=None,
                message="Học sinh chưa nộp đơn tái ghi danh",
                logs=logs
            )
        
        logs.append(f"Tìm thấy đơn: {submission.name}")
        
        return single_item_response(
            data=submission,
            message="Lấy thông tin đơn tái ghi danh thành công"
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get Student Re-enrollment Error")
        return error_response(
            message=f"Lỗi khi lấy thông tin đơn tái ghi danh: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def submit_re_enrollment():
    """
    Nộp đơn tái ghi danh cho học sinh.
    Phụ huynh gọi API này để submit form tái ghi danh.
    """
    logs = []
    
    try:
        # Lấy data từ request
        if frappe.request.is_json:
            data = frappe.request.json or {}
        else:
            data = frappe.form_dict
        
        logs.append(f"Nhận request submit tái ghi danh: {json.dumps(data, default=str)}")
        
        # Validate required fields
        required_fields = ['student_id', 'decision']
        for field in required_fields:
            if field not in data or data[field] is None:
                return validation_error_response(
                    f"Thiếu trường bắt buộc: {field}",
                    {field: [f"Trường {field} là bắt buộc"]}
                )
        
        student_id = data['student_id']
        decision = data['decision']
        agreement_accepted = data.get('agreement_accepted', False)
        
        # Validate decision
        if decision not in DECISION_TYPES:
            return validation_error_response(
                "Quyết định không hợp lệ",
                {"decision": [f"Quyết định phải là một trong: {', '.join(DECISION_TYPES)}"]}
            )
        
        # Validate agreement chỉ bắt buộc cho re_enroll
        if decision == 're_enroll' and not agreement_accepted:
            return validation_error_response(
                "Bạn cần đồng ý với điều khoản",
                {"agreement_accepted": ["Vui lòng đọc và đồng ý với điều khoản"]}
            )
        
        # Validate conditional fields
        if decision == 're_enroll':
            if 'payment_type' not in data or not data['payment_type']:
                return validation_error_response(
                    "Vui lòng chọn phương thức thanh toán",
                    {"payment_type": ["Phương thức thanh toán là bắt buộc khi tái ghi danh"]}
                )
            if data['payment_type'] not in ['annual', 'semester']:
                return validation_error_response(
                    "Phương thức thanh toán không hợp lệ",
                    {"payment_type": ["Phương thức phải là 'annual' hoặc 'semester'"]}
                )
        
        # Validate reason cho considering và not_re_enroll
        if decision in ['considering', 'not_re_enroll']:
            reason = data.get('reason') or data.get('not_re_enroll_reason') or ''
            if not reason.strip():
                return validation_error_response(
                    "Vui lòng nhập lý do",
                    {"reason": ["Lý do là bắt buộc"]}
                )
        
        # Get current parent
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent: {parent_id}")
        
        # Kiểm tra học sinh thuộc phụ huynh này
        relationship = frappe.db.exists(
            "CRM Family Relationship",
            {"guardian": parent_id, "student": student_id}
        )
        
        if not relationship:
            return error_response(
                "Bạn không có quyền nộp đơn cho học sinh này",
                logs=logs
            )
        
        # Lấy thông tin học sinh và campus
        student = frappe.get_doc("CRM Student", student_id)
        campus_id = student.campus_id
        
        # Tìm config đang active
        config = frappe.db.get_value(
            "SIS Re-enrollment Config",
            {"is_active": 1, "campus_id": campus_id},
            ["name", "start_date", "end_date"],
            as_dict=True
        )
        
        if not config:
            return error_response(
                "Không có đợt tái ghi danh nào đang mở",
                logs=logs
            )
        
        # Kiểm tra thời gian
        today = getdate(nowdate())
        if config.start_date and today < getdate(config.start_date):
            return error_response(
                f"Chưa đến thời gian tái ghi danh. Bắt đầu: {config.start_date}",
                logs=logs
            )
        
        if config.end_date and today > getdate(config.end_date):
            return error_response(
                f"Đã hết thời gian tái ghi danh. Kết thúc: {config.end_date}",
                logs=logs
            )
        
        logs.append(f"Config: {config.name}")
        
        # Tìm bản ghi tái ghi danh đã được tạo sẵn cho học sinh
        existing_record = frappe.db.get_value(
            "SIS Re-enrollment",
            {"student_id": student_id, "config_id": config.name},
            ["name", "submitted_at"],
            as_dict=True
        )
        
        if not existing_record:
            return error_response(
                "Không tìm thấy bản ghi tái ghi danh cho học sinh này. Vui lòng liên hệ nhà trường.",
                logs=logs
            )
        
        # Kiểm tra đã nộp chưa (submitted_at có giá trị = đã nộp)
        if existing_record.submitted_at:
            return error_response(
                f"Học sinh đã nộp đơn tái ghi danh. Mã đơn: {existing_record.name}",
                logs=logs
            )
        
        logs.append(f"Found existing record: {existing_record.name}")
        
        # Lấy lớp hiện tại
        current_class_info = _get_student_current_class(student_id, campus_id)
        current_class = current_class_info.get("class_title") if current_class_info else None
        
        # Xử lý answers nếu có
        answers_json = None
        if decision == 're_enroll' and 'answers' in data:
            answers_data = data['answers']
            if isinstance(answers_data, str):
                answers_json = answers_data
            else:
                answers_json = json.dumps(answers_data)
        
        # Lấy lý do từ request
        reason_value = data.get('reason') or data.get('not_re_enroll_reason') or None
        
        # Cập nhật bản ghi hiện có (không tạo mới)
        re_enrollment_doc = frappe.get_doc("SIS Re-enrollment", existing_record.name)
        re_enrollment_doc.guardian_id = parent_id
        re_enrollment_doc.current_class = current_class
        re_enrollment_doc.decision = decision
        re_enrollment_doc.payment_type = data.get('payment_type') if decision == 're_enroll' else None
        re_enrollment_doc.selected_discount_id = data.get('selected_discount_id') if decision == 're_enroll' else None
        re_enrollment_doc.not_re_enroll_reason = reason_value if decision in ['considering', 'not_re_enroll'] else None
        re_enrollment_doc.agreement_accepted = 1 if agreement_accepted else 0
        re_enrollment_doc.submitted_at = now()  # Đánh dấu đã nộp
        
        # Save với bypass permission
        re_enrollment_doc.flags.ignore_permissions = True
        re_enrollment_doc.save()
        
        frappe.db.commit()
        
        logs.append(f"Đã cập nhật đơn: {re_enrollment_doc.name}")
        
        # Chuẩn bị response
        decision_display_map = {
            're_enroll': 'Tái ghi danh',
            'considering': 'Đang cân nhắc',
            'not_re_enroll': 'Không tái ghi danh'
        }
        decision_display = decision_display_map.get(decision, decision)
        payment_display = ""
        if decision == 're_enroll':
            payment_display = "Đóng theo năm" if data.get('payment_type') == 'annual' else "Đóng theo kỳ"
        
        return success_response(
            data={
                "id": re_enrollment_doc.name,
                "student_id": student_id,
                "student_name": student.student_name,
                "decision": decision,
                "decision_display": decision_display,
                "payment_type": data.get('payment_type'),
                "payment_display": payment_display,
                "submitted_at": str(re_enrollment_doc.submitted_at)
            },
            message=f"Đã gửi đăng ký tái ghi danh thành công cho {student.student_name}",
            logs=logs
        )
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Submit Re-enrollment Error")
        return error_response(
            message=f"Lỗi khi nộp đơn tái ghi danh: {str(e)}",
            logs=logs
        )


@frappe.whitelist()
def get_my_re_enrollments():
    """
    Lấy danh sách tất cả đơn tái ghi danh của phụ huynh.
    Dùng để hiển thị lịch sử đơn đã nộp.
    """
    logs = []
    
    try:
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response("Không tìm thấy thông tin phụ huynh", logs=logs)
        
        logs.append(f"Parent: {parent_id}")
        
        # Lấy tất cả học sinh của phụ huynh
        relationships = frappe.get_all(
            "CRM Family Relationship",
            filters={"guardian": parent_id},
            fields=["student"]
        )
        student_ids = [rel.student for rel in relationships]
        
        if not student_ids:
            return list_response([])
        
        # Lấy tất cả đơn tái ghi danh
        submissions = frappe.get_all(
            "SIS Re-enrollment",
            filters={"student_id": ["in", student_ids]},
            fields=[
                "name", "config_id", "student_id", "student_name", "student_code",
                "current_class", "decision", "payment_type", "not_re_enroll_reason",
                "status", "submitted_at"
            ],
            order_by="submitted_at desc"
        )
        
        # Thêm thông tin config cho mỗi đơn
        for submission in submissions:
            config_info = frappe.db.get_value(
                "SIS Re-enrollment Config",
                submission.config_id,
                ["title", "school_year_id"],
                as_dict=True
            )
            submission["config_title"] = config_info.title if config_info else None
            
            # Display values
            decision_display_map = {
                're_enroll': 'Tái ghi danh',
                'considering': 'Đang cân nhắc',
                'not_re_enroll': 'Không tái ghi danh'
            }
            submission["decision_display"] = decision_display_map.get(submission.decision, submission.decision)
            if submission.payment_type:
                submission["payment_display"] = "Đóng theo năm" if submission.payment_type == 'annual' else "Đóng theo kỳ"
            
            # Status display
            status_map = {
                "pending": "Chờ xử lý",
                "approved": "Đã duyệt",
                "rejected": "Từ chối"
            }
            submission["status_display"] = status_map.get(submission.status, submission.status)
        
        logs.append(f"Tìm thấy {len(submissions)} đơn")
        
        return list_response(submissions)
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Parent Portal Get My Re-enrollments Error")
        return error_response(
            message=f"Lỗi khi lấy danh sách đơn tái ghi danh: {str(e)}",
            logs=logs
        )

