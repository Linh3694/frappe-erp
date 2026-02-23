# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Daily Health Visit API for SIS
Handles student visits to health clinic
"""

import frappe
from frappe import _
from frappe.utils import today, now, get_datetime, nowtime
import json
from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response
)


def _check_teacher_permission():
    """Check if user has teacher permission"""
    user_roles = frappe.get_roles()
    allowed_roles = ["System Manager", "SIS Manager", "SIS Teacher", "SIS Administrative"]

    if not any(role in allowed_roles for role in user_roles):
        frappe.throw(_("Bạn không có quyền truy cập API này"), frappe.PermissionError)


def _get_request_data():
    """Get request data from various sources"""
    data = {}
    
    # Luôn lấy form_dict trước (query params và form data)
    if frappe.local.form_dict:
        data = dict(frappe.local.form_dict)
    
    # Sau đó merge với JSON body nếu có
    if hasattr(frappe.request, 'is_json') and frappe.request.is_json:
        json_data = frappe.request.json or {}
        data.update(json_data)
    else:
        try:
            if hasattr(frappe.request, 'data') and frappe.request.data:
                raw = frappe.request.data
                body = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw
                if body:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict):
                        data.update(parsed)
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    
    return data


@frappe.whitelist(allow_guest=False)
def report_student_to_clinic():
    """
    Giáo viên báo cáo học sinh xuống Y tế
    Params:
        - student_id: ID học sinh (required)
        - class_id: ID lớp (required)
        - reason: Lý do xuống Y tế (required)
        - leave_class_time: Thời gian rời lớp (optional, default: now)
        - period: Tên tiết học (optional) - nếu có sẽ tự động cập nhật attendance thành excused
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        student_id = data.get("student_id")
        class_id = data.get("class_id")
        reason = data.get("reason")
        leave_class_time = data.get("leave_class_time") or nowtime()
        period = data.get("period")  # Tên tiết học (optional)
        
        # Validation
        errors = {}
        if not student_id:
            errors["student_id"] = ["student_id là bắt buộc"]
        if not class_id:
            errors["class_id"] = ["class_id là bắt buộc"]
        if not reason:
            errors["reason"] = ["reason là bắt buộc"]
        
        if errors:
            return validation_error_response("Dữ liệu không hợp lệ", errors)
        
        # Lấy thông tin student và class
        student = frappe.db.get_value("CRM Student", student_id, ["student_name", "student_code"], as_dict=True)
        class_info = frappe.db.get_value("SIS Class", class_id, ["title", "campus_id"], as_dict=True)
        
        if not student:
            return validation_error_response("Học sinh không tồn tại", {"student_id": ["Học sinh không tồn tại"]})
        if not class_info:
            return validation_error_response("Lớp không tồn tại", {"class_id": ["Lớp không tồn tại"]})
        
        # Lấy thông tin user
        reported_by_user = frappe.session.user
        reported_by_name = ""
        try:
            user = frappe.db.get_value("User", frappe.session.user, ["full_name"], as_dict=True)
            if user:
                reported_by_name = user.get("full_name") or frappe.session.user
        except:
            reported_by_name = frappe.session.user
        
        # Tạo bản ghi visit
        visit = frappe.get_doc({
            "doctype": "SIS Daily Health Visit",
            "student_id": student_id,
            "student_name": student.get("student_name"),
            "student_code": student.get("student_code"),
            "class_id": class_id,
            "class_name": class_info.get("title"),
            "visit_date": today(),
            "reason": reason,
            "leave_class_time": leave_class_time,
            "status": "left_class",
            "reported_by": reported_by_user,
            "reported_by_name": reported_by_name
        })
        visit.insert()
        
        # Nếu có period, tự động cập nhật attendance thành excused
        attendance_updated = False
        if period:
            try:
                existing_attendance = frappe.db.exists(
                    "SIS Class Attendance",
                    {
                        "student_id": student_id,
                        "class_id": class_id,
                        "date": today(),
                        "period": period
                    }
                )
                
                if existing_attendance:
                    # Cập nhật attendance hiện có thành excused
                    frappe.db.set_value(
                        "SIS Class Attendance",
                        existing_attendance,
                        "status",
                        "excused"
                    )
                    attendance_updated = True
                else:
                    # Tạo mới attendance với status excused
                    attendance = frappe.get_doc({
                        "doctype": "SIS Class Attendance",
                        "student_id": student_id,
                        "student_code": student.get("student_code"),
                        "student_name": student.get("student_name"),
                        "class_id": class_id,
                        "date": today(),
                        "period": period,
                        "status": "excused",
                        "remarks": f"Xuống Y tế: {reason}",
                        "campus_id": class_info.get("campus_id"),
                        "recorded_by": reported_by_user
                    })
                    attendance.insert()
                    attendance_updated = True
                    
                frappe.logger().info(f"[report_student_to_clinic] Updated attendance to excused for student {student_id}, period {period}")
            except Exception as att_err:
                # Không fail toàn bộ request nếu không thể cập nhật attendance
                frappe.logger().warning(f"[report_student_to_clinic] Could not update attendance: {str(att_err)}")
        
        frappe.db.commit()
        
        return success_response(
            data={
                "name": visit.name,
                "status": visit.status,
                "attendance_updated": attendance_updated
            },
            message="Đã báo cáo học sinh xuống Y tế"
        )
    
    except frappe.ValidationError as e:
        return validation_error_response(str(e), {})
    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Error reporting student to clinic: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        return error_response(
            message=f"Lỗi khi báo cáo học sinh xuống Y tế: {str(e)}",
            code="REPORT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_daily_health_visits():
    """
    Lấy danh sách học sinh đang ở/đã ở Y tế (cho trang DailyHealth)
    Params:
        - date: Ngày (optional, default: today)
        - campus: Campus filter (optional)
        - status: Filter theo status (optional)
        - search: Tìm kiếm theo tên/mã học sinh/lớp (optional)
    """
    try:
        _check_teacher_permission()
        
        data = frappe.local.form_dict
        request_args = frappe.request.args
        
        visit_date = data.get("date") or request_args.get("date") or today()
        campus = data.get("campus") or request_args.get("campus")
        status_filter = data.get("status") or request_args.get("status")
        search = data.get("search") or request_args.get("search")
        
        # Build filters
        filters = {"visit_date": visit_date}
        if status_filter:
            filters["status"] = status_filter
        
        # Nếu có campus filter, lấy danh sách class_id
        if campus:
            campus_class_ids = frappe.get_all(
                "SIS Class",
                filters={"campus_id": campus},
                pluck="name"
            )
            if campus_class_ids:
                filters["class_id"] = ["in", campus_class_ids]
            else:
                return success_response(
                    data={"data": [], "total": 0},
                    message="Lấy danh sách học sinh xuống Y tế thành công"
                )
        
        # Query visits
        visits = frappe.get_all(
            "SIS Daily Health Visit",
            filters=filters,
            fields=[
                "name", "student_id", "student_name", "student_code",
                "class_id", "class_name", "visit_date", "reason",
                "leave_class_time", "arrive_clinic_time", "leave_clinic_time",
                "status", "reported_by", "reported_by_name",
                "received_by", "received_by_name", "creation"
            ],
            order_by="leave_class_time desc"
        )
        
        # Filter theo search term
        if search:
            search_lower = search.lower()
            visits = [v for v in visits if 
                     search_lower in (v.get("student_name") or "").lower() or
                     search_lower in (v.get("student_code") or "").lower() or
                     search_lower in (v.get("class_name") or "").lower()]
        
        # Lấy ảnh học sinh cho mỗi visit
        current_school_year = frappe.db.get_value(
            "SIS School Year",
            {"is_enable": 1},
            "name"
        )
        
        for visit in visits:
            student_photo = None
            try:
                # Ưu tiên lấy ảnh theo năm học hiện tại
                if current_school_year:
                    photos = frappe.get_all(
                        "SIS Photo",
                        filters={
                            "student_id": visit.get("student_id"),
                            "school_year_id": current_school_year
                        },
                        fields=["photo"],
                        order_by="creation desc",
                        limit=1
                    )
                    if photos and photos[0].get("photo"):
                        student_photo = photos[0]["photo"]
                
                # Fallback - lấy ảnh mới nhất nếu không có ảnh năm học
                if not student_photo:
                    photos = frappe.get_all(
                        "SIS Photo",
                        filters={"student_id": visit.get("student_id")},
                        fields=["photo"],
                        order_by="creation desc",
                        limit=1
                    )
                    if photos and photos[0].get("photo"):
                        student_photo = photos[0]["photo"]
            except Exception as photo_err:
                frappe.logger().warning(f"Error fetching photo for student {visit.get('student_id')}: {str(photo_err)}")
            
            visit["student_photo"] = student_photo
        
        return success_response(
            data={"data": visits, "total": len(visits)},
            message="Lấy danh sách học sinh xuống Y tế thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error getting daily health visits: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách xuống Y tế: {str(e)}",
            code="GET_VISITS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def receive_student_at_clinic():
    """
    Nhân viên Y tế tiếp nhận học sinh
    Params:
        - visit_id: ID của visit (required)
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        visit_id = data.get("visit_id")
        
        if not visit_id:
            return validation_error_response("visit_id là bắt buộc", {"visit_id": ["visit_id là bắt buộc"]})
        
        # Lấy visit
        visit = frappe.get_doc("SIS Daily Health Visit", visit_id)
        
        # Lấy thông tin user
        received_by_user = frappe.session.user
        received_by_name = ""
        try:
            user = frappe.db.get_value("User", frappe.session.user, ["full_name"], as_dict=True)
            if user:
                received_by_name = user.get("full_name") or frappe.session.user
        except:
            received_by_name = frappe.session.user
        
        # Cập nhật visit
        visit.status = "at_clinic"
        visit.arrive_clinic_time = nowtime()
        visit.received_by = received_by_user
        visit.received_by_name = received_by_name
        visit.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": visit.name, "status": visit.status},
            message="Đã tiếp nhận học sinh tại phòng Y tế"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Bản ghi xuống Y tế không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Error receiving student at clinic: {str(e)}")
        return error_response(
            message=f"Lỗi khi tiếp nhận học sinh: {str(e)}",
            code="RECEIVE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def start_examination():
    """
    Bắt đầu khám - chuyển status sang examining
    Params:
        - visit_id: ID của visit (required)
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        visit_id = data.get("visit_id")
        
        if not visit_id:
            return validation_error_response("visit_id là bắt buộc", {"visit_id": ["visit_id là bắt buộc"]})
        
        # Lấy visit
        visit = frappe.get_doc("SIS Daily Health Visit", visit_id)
        
        # Chỉ cho phép start examination khi status là at_clinic
        if visit.status not in ["at_clinic", "examining"]:
            return error_response(
                message="Chỉ có thể bắt đầu khám khi học sinh đã được tiếp nhận",
                code="INVALID_STATUS"
            )
        
        # Cập nhật visit status sang examining
        visit.status = "examining"
        visit.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": visit.name, "status": visit.status},
            message="Đã bắt đầu khám"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Bản ghi xuống Y tế không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Error starting examination: {str(e)}")
        return error_response(
            message=f"Lỗi khi bắt đầu khám: {str(e)}",
            code="START_EXAM_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_health_examination():
    """
    Tạo hồ sơ khám mới
    Params:
        - visit_id: ID của visit (required)
        - symptoms: Triệu chứng (required)
        - images: List of image URLs (optional) - should be uploaded via upload_file first
        - disease_classification: Phân loại bệnh (optional)
        - examination_notes: Kết quả thăm khám (optional)
        - treatment_type: Loại điều trị (optional): medication/rest/other
        - treatment_details: Chi tiết điều trị (optional)
        - diagnosis: Chẩn đoán (optional) - deprecated
        - treatment: Xử lý/Dặn dò (optional) - deprecated
        - outcome: Kết quả (optional)
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        visit_id = data.get("visit_id")
        symptoms = data.get("symptoms")
        images = data.get("images", [])  # List of {image: url, description: text}
        disease_classification = data.get("disease_classification", "")
        examination_notes = data.get("examination_notes", "")
        treatment_type = data.get("treatment_type", "")
        treatment_details = data.get("treatment_details", "")
        
        # Backward compatibility
        diagnosis = data.get("diagnosis", "")
        treatment = data.get("treatment", "")
        outcome = data.get("outcome")
        
        # Validation
        errors = {}
        if not visit_id:
            errors["visit_id"] = ["visit_id là bắt buộc"]
        if not symptoms:
            errors["symptoms"] = ["symptoms là bắt buộc"]
        
        if errors:
            return validation_error_response("Dữ liệu không hợp lệ", errors)
        
        # Lấy visit để lấy thông tin student
        visit = frappe.get_doc("SIS Daily Health Visit", visit_id)
        
        # Lấy thông tin user
        examined_by_user = frappe.session.user
        examined_by_name = ""
        try:
            user = frappe.db.get_value("User", frappe.session.user, ["full_name"], as_dict=True)
            if user:
                examined_by_name = user.get("full_name") or frappe.session.user
        except:
            examined_by_name = frappe.session.user
        
        # Tạo examination
        exam = frappe.get_doc({
            "doctype": "SIS Health Examination",
            "student_id": visit.student_id,
            "student_name": visit.student_name,
            "student_code": visit.student_code,
            "examination_date": today(),
            "visit_id": visit_id,
            "symptoms": symptoms,
            "disease_classification": disease_classification,
            "examination_notes": examination_notes,
            "treatment_type": treatment_type,
            "treatment_details": treatment_details,
            "diagnosis": diagnosis,  # Deprecated
            "treatment": treatment,  # Deprecated
            "outcome": outcome,
            "examined_by": examined_by_user,
            "examined_by_name": examined_by_name
        })
        
        # Add images as child table if provided
        if images and isinstance(images, list):
            for img_data in images:
                if isinstance(img_data, dict) and img_data.get("image"):
                    exam.append("images", {
                        "image": img_data.get("image"),
                        "description": img_data.get("description", "")
                    })
        
        exam.insert()
        frappe.db.commit()
        
        return success_response(
            data={"name": exam.name},
            message="Tạo hồ sơ khám thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Bản ghi xuống Y tế không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Error creating health examination: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        return error_response(
            message=f"Lỗi khi tạo hồ sơ khám: {str(e)}",
            code="CREATE_EXAM_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_health_examination():
    """
    Cập nhật hồ sơ khám
    Params:
        - exam_id: ID của examination (required)
        - symptoms: Triệu chứng (optional)
        - images: List of image URLs (optional) - replaces existing images
        - disease_classification: Phân loại bệnh (optional)
        - examination_notes: Kết quả thăm khám (optional)
        - treatment_type: Loại điều trị (optional)
        - treatment_details: Chi tiết điều trị (optional)
        - diagnosis: Chẩn đoán (optional) - deprecated
        - treatment: Xử lý/Dặn dò (optional) - deprecated
        - outcome: Kết quả (optional)
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        frappe.logger().info(f"[update_health_examination] Received data: {data}")
        
        exam_id = data.get("exam_id")
        symptoms = data.get("symptoms")
        images = data.get("images")  # List of {image: url, description: text} or None
        disease_classification = data.get("disease_classification")
        examination_notes = data.get("examination_notes")
        treatment_type = data.get("treatment_type")
        treatment_details = data.get("treatment_details")
        
        # Backward compatibility
        diagnosis = data.get("diagnosis")
        treatment = data.get("treatment")
        outcome = data.get("outcome")
        
        if not exam_id:
            return validation_error_response("exam_id là bắt buộc", {"exam_id": ["exam_id là bắt buộc"]})
        
        # Lấy examination
        exam = frappe.get_doc("SIS Health Examination", exam_id)
        
        frappe.logger().info(f"[update_health_examination] Found exam: {exam.name}")
        
        # Cập nhật các trường (cho phép empty string để clear field)
        if symptoms is not None:
            exam.symptoms = symptoms
        if disease_classification is not None:
            exam.disease_classification = disease_classification if disease_classification else None
        if examination_notes is not None:
            exam.examination_notes = examination_notes if examination_notes else None
        if treatment_type is not None:
            exam.treatment_type = treatment_type if treatment_type else None
        if treatment_details is not None:
            exam.treatment_details = treatment_details if treatment_details else None
        if diagnosis is not None:
            exam.diagnosis = diagnosis if diagnosis else None
        if treatment is not None:
            exam.treatment = treatment if treatment else None
        if outcome is not None:
            exam.outcome = outcome
        
        # Update images if provided (cho phép empty array để clear tất cả)
        if images is not None and isinstance(images, list):
            frappe.logger().info(f"[update_health_examination] Updating images: {images}")
            # Clear existing images
            exam.images = []
            # Add new images
            for img_data in images:
                if isinstance(img_data, dict) and img_data.get("image"):
                    exam.append("images", {
                        "image": img_data.get("image"),
                        "description": img_data.get("description", "")
                    })
        
        exam.save()
        frappe.db.commit()
        
        frappe.logger().info(f"[update_health_examination] Successfully updated exam: {exam.name}")
        
        return success_response(
            data={"name": exam.name},
            message="Cập nhật hồ sơ khám thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Hồ sơ khám không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Error updating health examination: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        return error_response(
            message=f"Lỗi khi cập nhật hồ sơ khám: {str(e)}",
            code="UPDATE_EXAM_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_student_examination_history():
    """
    Lấy lịch sử khám của học sinh
    Params:
        - student_id: ID học sinh (required)
        - limit: Số lượng record (optional, default: 50)
    """
    try:
        _check_teacher_permission()
        
        data = frappe.local.form_dict
        request_args = frappe.request.args
        
        student_id = data.get("student_id") or request_args.get("student_id")
        limit = int(data.get("limit") or request_args.get("limit") or 50)
        
        if not student_id:
            return validation_error_response("student_id là bắt buộc", {"student_id": ["student_id là bắt buộc"]})
        
        # Lấy lịch sử khám
        exams = frappe.get_all(
            "SIS Health Examination",
            filters={"student_id": student_id},
            fields=[
                "name", "examination_date", "symptoms", "diagnosis",
                "treatment", "outcome", "examined_by_name", "creation", "modified",
                "visit_id", "disease_classification", "examination_notes",
                "treatment_type", "treatment_details"
            ],
            order_by="examination_date desc, creation desc",
            limit=limit
        )
        
        # Lấy images cho mỗi examination
        for exam in exams:
            exam_images = frappe.get_all(
                "SIS Examination Image",
                filters={"parent": exam.get("name")},
                fields=["image", "description"],
                order_by="idx"
            )
            exam["images"] = exam_images
        
        return success_response(
            data={"data": exams, "total": len(exams)},
            message="Lấy lịch sử khám thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error getting student examination history: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy lịch sử khám: {str(e)}",
            code="GET_HISTORY_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_students_at_clinic():
    """
    Lấy danh sách học sinh đang ở Y tế cho một lớp (cho LessonLog điểm danh)
    Params:
        - class_id: ID lớp (required)
        - date: Ngày (optional, default: today)
        - current_time: Thời gian hiện tại (optional, để check xem học sinh đã về chưa)
    """
    try:
        _check_teacher_permission()
        
        data = frappe.local.form_dict
        request_args = frappe.request.args
        
        class_id = data.get("class_id") or request_args.get("class_id")
        visit_date = data.get("date") or request_args.get("date") or today()
        current_time = data.get("current_time") or request_args.get("current_time")
        
        if not class_id:
            return validation_error_response("class_id là bắt buộc", {"class_id": ["class_id là bắt buộc"]})
        
        # Lấy danh sách học sinh của lớp đang ở Y tế
        # Status: left_class hoặc at_clinic
        # Nếu đã returned/picked_up/transferred và có leave_clinic_time, check xem đã quay về chưa
        visits = frappe.get_all(
            "SIS Daily Health Visit",
            filters={
                "class_id": class_id,
                "visit_date": visit_date
            },
            fields=[
                "name", "student_id", "status", 
                "leave_class_time", "leave_clinic_time"
            ]
        )
        
        # Filter học sinh đang ở Y tế
        students_at_clinic = {}
        for visit in visits:
            # Nếu status là left_class hoặc at_clinic -> đang ở Y tế
            if visit.status in ["left_class", "at_clinic"]:
                students_at_clinic[visit.student_id] = {
                    "visit_id": visit.name,
                    "status": visit.status,
                    "leave_class_time": visit.leave_class_time
                }
            # Nếu đã về nhưng chưa check thời gian
            elif visit.status in ["returned", "picked_up", "transferred"]:
                # Nếu có current_time và leave_clinic_time, check xem đã về chưa
                if current_time and visit.leave_clinic_time:
                    if visit.leave_clinic_time > current_time:
                        # Chưa về, vẫn còn ở Y tế
                        students_at_clinic[visit.student_id] = {
                            "visit_id": visit.name,
                            "status": visit.status,
                            "leave_class_time": visit.leave_class_time
                        }
        
        return success_response(
            data={"students": students_at_clinic},
            message="Lấy danh sách học sinh ở Y tế thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error getting students at clinic: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách học sinh ở Y tế: {str(e)}",
            code="GET_STUDENTS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def complete_health_visit():
    """
    Hoàn thành lượt xuống Y tế (học sinh rời phòng Y tế)
    Params:
        - visit_id: ID của visit (required)
        - outcome: Kết quả (required): returned/picked_up/transferred
        - leave_clinic_time: Thời gian rời Y tế (optional, default: now)
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        visit_id = data.get("visit_id")
        outcome = data.get("outcome")
        leave_clinic_time = data.get("leave_clinic_time") or nowtime()
        
        # Validation
        errors = {}
        if not visit_id:
            errors["visit_id"] = ["visit_id là bắt buộc"]
        if not outcome:
            errors["outcome"] = ["outcome là bắt buộc"]
        elif outcome not in ["returned", "picked_up", "transferred"]:
            errors["outcome"] = ["outcome phải là returned, picked_up, hoặc transferred"]
        
        if errors:
            return validation_error_response("Dữ liệu không hợp lệ", errors)
        
        # Lấy visit
        visit = frappe.get_doc("SIS Daily Health Visit", visit_id)
        
        # Cập nhật visit
        visit.status = outcome
        visit.leave_clinic_time = leave_clinic_time
        visit.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": visit.name, "status": visit.status},
            message="Đã hoàn thành lượt xuống Y tế"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Bản ghi xuống Y tế không tồn tại",
            code="NOT_FOUND"
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Error completing health visit: {str(e)}")
        return error_response(
            message=f"Lỗi khi hoàn thành lượt xuống Y tế: {str(e)}",
            code="COMPLETE_ERROR"
        )


def _get_period_times(class_id, period_name, visit_date):
    """
    Lấy thời gian bắt đầu và kết thúc của tiết học từ Schedule Group.
    Returns: (start_time, end_time) hoặc (None, None) nếu không tìm thấy
    """
    try:
        # Lấy education_stage_id từ class
        class_doc = frappe.db.get_value("SIS Class", class_id, ["education_stage_id"], as_dict=True)
        if not class_doc or not class_doc.get("education_stage_id"):
            frappe.logger().warning(f"[get_period_times] Cannot find education_stage_id for class {class_id}")
            return None, None
        
        education_stage_id = class_doc.get("education_stage_id")
        
        # Tìm Schedule Group đang active cho education_stage và date
        schedule_group = frappe.db.sql("""
            SELECT name FROM `tabSIS Schedule Group`
            WHERE education_stage_id = %s
              AND is_active = 1
              AND start_date <= %s
              AND end_date >= %s
            ORDER BY start_date DESC
            LIMIT 1
        """, (education_stage_id, visit_date, visit_date), as_dict=True)
        
        if not schedule_group:
            frappe.logger().warning(f"[get_period_times] Cannot find active schedule group for education_stage {education_stage_id} on {visit_date}")
            return None, None
        
        schedule_group_id = schedule_group[0].get("name")
        
        # Tìm Period với period_name khớp
        period = frappe.db.get_value(
            "SIS Timetable Column",
            {
                "schedule_id": schedule_group_id,
                "period_name": period_name
            },
            ["start_time", "end_time"],
            as_dict=True
        )
        
        if not period:
            frappe.logger().warning(f"[get_period_times] Cannot find period '{period_name}' in schedule group {schedule_group_id}")
            return None, None
        
        return period.get("start_time"), period.get("end_time")
    
    except Exception as e:
        frappe.logger().error(f"[get_period_times] Error: {str(e)}")
        return None, None


def _time_to_seconds(time_val):
    """
    Chuyển đổi time value (có thể là timedelta hoặc string) sang seconds
    """
    if time_val is None:
        return None
    
    # Nếu là timedelta (từ database)
    if hasattr(time_val, 'total_seconds'):
        return time_val.total_seconds()
    
    # Nếu là string (HH:MM hoặc HH:MM:SS)
    if isinstance(time_val, str):
        parts = time_val.split(':')
        if len(parts) >= 2:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2]) if len(parts) > 2 else 0
            return hours * 3600 + minutes * 60 + seconds
    
    return None


@frappe.whitelist(allow_guest=False)
def get_health_status_for_period():
    """
    Lấy trạng thái Y tế của học sinh theo tiết học (cho LessonLog).
    Kiểm tra thời gian rời lớp/rời Y tế với thời gian tiết học để xác định chính xác.
    
    Params:
        - class_id: ID lớp (required)
        - date: Ngày (required)
        - period: Tên tiết học, VD: "Tiết 1" (required)
    
    Returns:
        students: Record<student_id, {visit_id, status, leave_class_time, leave_clinic_time}>
        
    Logic:
        - Học sinh được coi là "ở Y tế" trong tiết nếu:
          1. leave_class_time < period_end_time (rời lớp trước khi tiết kết thúc)
          2. AND (leave_clinic_time IS NULL OR leave_clinic_time > period_start_time) (chưa về hoặc về sau khi tiết bắt đầu)
        - Nếu không tìm được thông tin tiết học, fallback về logic cũ (chỉ check status)
    """
    try:
        _check_teacher_permission()
        
        data = frappe.local.form_dict
        request_args = frappe.request.args
        
        class_id = data.get("class_id") or request_args.get("class_id")
        visit_date = data.get("date") or request_args.get("date")
        period_name = data.get("period") or request_args.get("period")
        
        # Validation
        errors = {}
        if not class_id:
            errors["class_id"] = ["class_id là bắt buộc"]
        if not visit_date:
            errors["date"] = ["date là bắt buộc"]
        if not period_name:
            errors["period"] = ["period là bắt buộc"]
        
        if errors:
            return validation_error_response("Dữ liệu không hợp lệ", errors)
        
        # Lấy thời gian tiết học
        period_start, period_end = _get_period_times(class_id, period_name, visit_date)
        period_start_sec = _time_to_seconds(period_start)
        period_end_sec = _time_to_seconds(period_end)
        
        has_period_times = period_start_sec is not None and period_end_sec is not None
        
        if not has_period_times:
            frappe.logger().warning(f"[get_health_status_for_period] Cannot get period times for {period_name}, using fallback logic")
        
        # Query tất cả visits trong ngày của lớp
        visits = frappe.get_all(
            "SIS Daily Health Visit",
            filters={
                "class_id": class_id,
                "visit_date": visit_date
            },
            fields=[
                "name", "student_id", "status",
                "leave_class_time", "leave_clinic_time"
            ],
            order_by="leave_class_time desc"
        )
        
        # Filter học sinh ở Y tế theo logic thời gian
        students_at_clinic = {}
        
        for visit in visits:
            student_id = visit.student_id
            
            # Nếu student đã có trong result (ưu tiên visit mới nhất), skip
            if student_id in students_at_clinic:
                continue
            
            leave_class_sec = _time_to_seconds(visit.leave_class_time)
            leave_clinic_sec = _time_to_seconds(visit.leave_clinic_time)
            
            is_at_clinic = False
            
            if has_period_times and leave_class_sec is not None:
                # Logic có thời gian tiết học:
                # 1. Học sinh rời lớp trước khi tiết kết thúc
                # 2. AND (chưa về OR về sau khi tiết bắt đầu)
                left_before_period_end = leave_class_sec < period_end_sec
                not_returned_or_returned_after_period_start = (
                    leave_clinic_sec is None or 
                    leave_clinic_sec > period_start_sec
                )
                
                if left_before_period_end and not_returned_or_returned_after_period_start:
                    is_at_clinic = True
            else:
                # Fallback: không có thông tin tiết học, chỉ check status
                # Status đang ở Y tế: left_class, at_clinic, examining
                if visit.status in ["left_class", "at_clinic", "examining"]:
                    is_at_clinic = True
            
            if is_at_clinic:
                students_at_clinic[student_id] = {
                    "visit_id": visit.name,
                    "status": visit.status,
                    "leave_class_time": str(visit.leave_class_time) if visit.leave_class_time else None,
                    "leave_clinic_time": str(visit.leave_clinic_time) if visit.leave_clinic_time else None
                }
        
        return success_response(
            data={"students": students_at_clinic},
            message="Lấy trạng thái Y tế theo tiết học thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error getting health status for period: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        return error_response(
            message=f"Lỗi khi lấy trạng thái Y tế theo tiết học: {str(e)}",
            code="GET_HEALTH_STATUS_ERROR"
        )


# ==================== DISEASE CLASSIFICATION CRUD ====================

@frappe.whitelist()
def get_disease_classifications(campus: str = None):
    """
    Lấy danh sách phân loại bệnh theo campus
    """
    try:
        filters = {"enabled": 1}
        if campus:
            filters["campus"] = campus
        
        classifications = frappe.get_all(
            "SIS Disease Classification",
            filters=filters,
            fields=["name", "code", "title", "campus", "enabled", "creation", "modified"],
            order_by="code asc"
        )
        
        return success_response(
            data={"data": classifications, "total": len(classifications)},
            message="Lấy danh sách phân loại bệnh thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error getting disease classifications: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách phân loại bệnh: {str(e)}",
            code="GET_DISEASE_CLASSIFICATIONS_ERROR"
        )


@frappe.whitelist()
def create_disease_classification(code: str = None, title: str = None, campus: str = None):
    """
    Tạo mới phân loại bệnh
    """
    try:
        # Lấy dữ liệu từ form_dict hoặc request JSON
        import json
        if not code and frappe.request and frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
                code = data.get('code')
                title = data.get('title')
                campus = data.get('campus')
            except json.JSONDecodeError:
                pass
        
        code = code or frappe.form_dict.get('code')
        title = title or frappe.form_dict.get('title')
        campus = campus or frappe.form_dict.get('campus')
        
        if not code or not title or not campus:
            return error_response(
                message="Mã bệnh, tên phân loại và trường học là bắt buộc",
                code="MISSING_REQUIRED_FIELDS"
            )
        
        # Kiểm tra trùng mã trong cùng campus
        existing = frappe.get_all(
            "SIS Disease Classification",
            filters={"code": code, "campus": campus},
            limit=1
        )
        if existing:
            return error_response(
                message="Mã bệnh này đã tồn tại",
                code="DUPLICATE_CODE"
            )
        
        doc = frappe.get_doc({
            "doctype": "SIS Disease Classification",
            "code": code,
            "title": title,
            "campus": campus,
            "enabled": 1
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={"name": doc.name, "code": doc.code, "title": doc.title},
            message="Tạo phân loại bệnh thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error creating disease classification: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo phân loại bệnh: {str(e)}",
            code="CREATE_DISEASE_CLASSIFICATION_ERROR"
        )


@frappe.whitelist()
def update_disease_classification(name: str = None, code: str = None, title: str = None, enabled: int = None):
    """
    Cập nhật phân loại bệnh
    """
    try:
        # Lấy dữ liệu từ request JSON
        import json
        data = {}
        if frappe.request and frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
            except json.JSONDecodeError:
                pass
        
        name = name or data.get('name') or frappe.form_dict.get('name')
        code = code if code is not None else data.get('code') or frappe.form_dict.get('code')
        title = title if title is not None else data.get('title') or frappe.form_dict.get('title')
        enabled_val = data.get('enabled') or frappe.form_dict.get('enabled')
        if enabled is None and enabled_val is not None:
            enabled = int(enabled_val) if enabled_val not in [None, ''] else None
        
        if not name:
            return error_response(
                message="ID phân loại bệnh là bắt buộc",
                code="MISSING_REQUIRED_FIELDS"
            )
        
        doc = frappe.get_doc("SIS Disease Classification", name)
        
        if code is not None:
            # Kiểm tra trùng mã trong cùng campus (trừ chính nó)
            existing = frappe.get_all(
                "SIS Disease Classification",
                filters={"code": code, "campus": doc.campus, "name": ["!=", name]},
                limit=1
            )
            if existing:
                return error_response(
                    message="Mã bệnh này đã tồn tại",
                    code="DUPLICATE_CODE"
                )
            doc.code = code
        
        if title is not None:
            doc.title = title
        
        if enabled is not None:
            doc.enabled = enabled
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={"name": doc.name, "code": doc.code, "title": doc.title},
            message="Cập nhật phân loại bệnh thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy phân loại bệnh",
            code="CLASSIFICATION_NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error updating disease classification: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật phân loại bệnh: {str(e)}",
            code="UPDATE_DISEASE_CLASSIFICATION_ERROR"
        )


@frappe.whitelist()
def delete_disease_classification(name: str = None):
    """
    Xóa phân loại bệnh
    """
    try:
        import json
        data = {}
        if frappe.request and frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
            except json.JSONDecodeError:
                pass
        
        name = name or data.get('name') or frappe.form_dict.get('name')
        
        if not name:
            return error_response(
                message="ID phân loại bệnh là bắt buộc",
                code="MISSING_REQUIRED_FIELDS"
            )
        
        frappe.delete_doc("SIS Disease Classification", name, ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={"name": name},
            message="Xóa phân loại bệnh thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy phân loại bệnh",
            code="CLASSIFICATION_NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error deleting disease classification: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa phân loại bệnh: {str(e)}",
            code="DELETE_DISEASE_CLASSIFICATION_ERROR"
        )


# ==================== MEDICINE CRUD ====================

@frappe.whitelist()
def get_medicines(campus: str = None):
    """
    Lấy danh sách thuốc theo campus
    """
    try:
        filters = {"enabled": 1}
        if campus:
            filters["campus"] = campus
        
        medicines = frappe.get_all(
            "SIS Medicine",
            filters=filters,
            fields=["name", "title", "unit", "description", "campus", "enabled", "creation", "modified"],
            order_by="title asc"
        )
        
        return success_response(
            data={"data": medicines, "total": len(medicines)},
            message="Lấy danh sách thuốc thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error getting medicines: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách thuốc: {str(e)}",
            code="GET_MEDICINES_ERROR"
        )


@frappe.whitelist()
def create_medicine(title: str = None, campus: str = None, unit: str = None, description: str = None):
    """
    Tạo mới thuốc
    """
    try:
        # Lấy dữ liệu từ request JSON
        import json
        data = {}
        if frappe.request and frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
            except json.JSONDecodeError:
                pass
        
        title = title or data.get('title') or frappe.form_dict.get('title')
        campus = campus or data.get('campus') or frappe.form_dict.get('campus')
        unit = unit or data.get('unit') or frappe.form_dict.get('unit')
        description = description or data.get('description') or frappe.form_dict.get('description')
        
        if not title or not campus:
            return error_response(
                message="Tên thuốc và trường học là bắt buộc",
                code="MISSING_REQUIRED_FIELDS"
            )
        
        # Kiểm tra trùng tên trong cùng campus
        existing = frappe.get_all(
            "SIS Medicine",
            filters={"title": title, "campus": campus},
            limit=1
        )
        if existing:
            return error_response(
                message="Thuốc này đã tồn tại",
                code="DUPLICATE_MEDICINE"
            )
        
        doc = frappe.get_doc({
            "doctype": "SIS Medicine",
            "title": title,
            "unit": unit,
            "description": description,
            "campus": campus,
            "enabled": 1
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={"name": doc.name, "title": doc.title},
            message="Tạo thuốc thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error creating medicine: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo thuốc: {str(e)}",
            code="CREATE_MEDICINE_ERROR"
        )


@frappe.whitelist()
def update_medicine(name: str = None, title: str = None, unit: str = None, description: str = None, enabled: int = None):
    """
    Cập nhật thuốc
    """
    try:
        # Lấy dữ liệu từ request JSON
        import json
        data = {}
        if frappe.request and frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
            except json.JSONDecodeError:
                pass
        
        name = name or data.get('name') or frappe.form_dict.get('name')
        title = title if title is not None else data.get('title') or frappe.form_dict.get('title')
        unit = unit if unit is not None else data.get('unit') or frappe.form_dict.get('unit')
        description = description if description is not None else data.get('description') or frappe.form_dict.get('description')
        enabled_val = data.get('enabled') or frappe.form_dict.get('enabled')
        if enabled is None and enabled_val is not None:
            enabled = int(enabled_val) if enabled_val not in [None, ''] else None
        
        if not name:
            return error_response(
                message="ID thuốc là bắt buộc",
                code="MISSING_REQUIRED_FIELDS"
            )
        
        doc = frappe.get_doc("SIS Medicine", name)
        
        if title is not None:
            # Kiểm tra trùng tên trong cùng campus (trừ chính nó)
            existing = frappe.get_all(
                "SIS Medicine",
                filters={"title": title, "campus": doc.campus, "name": ["!=", name]},
                limit=1
            )
            if existing:
                return error_response(
                    message="Thuốc này đã tồn tại",
                    code="DUPLICATE_MEDICINE"
                )
            doc.title = title
        
        if unit is not None:
            doc.unit = unit
        
        if description is not None:
            doc.description = description
        
        if enabled is not None:
            doc.enabled = enabled
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={"name": doc.name, "title": doc.title},
            message="Cập nhật thuốc thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy thuốc",
            code="MEDICINE_NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error updating medicine: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật thuốc: {str(e)}",
            code="UPDATE_MEDICINE_ERROR"
        )


@frappe.whitelist()
def delete_medicine(name: str = None):
    """
    Xóa thuốc
    """
    try:
        import json
        data = {}
        if frappe.request and frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
            except json.JSONDecodeError:
                pass
        
        name = name or data.get('name') or frappe.form_dict.get('name')
        
        if not name:
            return error_response(
                message="ID thuốc là bắt buộc",
                code="MISSING_REQUIRED_FIELDS"
            )
        
        frappe.delete_doc("SIS Medicine", name, ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={"name": name},
            message="Xóa thuốc thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy thuốc",
            code="MEDICINE_NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error deleting medicine: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa thuốc: {str(e)}",
            code="DELETE_MEDICINE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def import_disease_classifications_excel(campus=None):
    """
    Import phân loại bệnh từ file Excel.
    Cột A: Mã bệnh, Cột B: Tên phân loại
    """
    try:
        import openpyxl
        import io

        # Đọc campus từ nhiều nguồn: tham số hàm, form_dict, query string
        campus = (
            campus
            or frappe.form_dict.get('campus')
            or (frappe.request.args.get('campus') if frappe.request else None)
        )
        if not campus:
            return error_response(
                message="Thiếu thông tin trường học",
                code="MISSING_CAMPUS"
            )

        # Kiểm tra campus tồn tại
        if not frappe.db.exists("SIS Campus", campus):
            return error_response(
                message=f"Không tìm thấy trường học: {campus}",
                code="CAMPUS_NOT_FOUND"
            )

        # Lấy file từ request
        file_obj = frappe.request.files.get('file')
        if not file_obj:
            return error_response(
                message="Không tìm thấy file",
                code="MISSING_FILE"
            )

        file_data = file_obj.read()
        wb = openpyxl.load_workbook(io.BytesIO(file_data), read_only=True, data_only=True)
        ws = wb.active

        success_count = 0
        error_list = []
        total_count = 0

        # Tải trước danh sách mã đã có để kiểm tra trùng nhanh (so sánh uppercase)
        existing_codes = set(
            r.code.strip().upper()
            for r in frappe.get_all("SIS Disease Classification", filters={"campus": campus}, fields=["code"])
            if r.code
        )
        # Theo dõi mã trong file Excel để phát hiện trùng nội bộ
        seen_in_file = set()

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            # Bỏ qua dòng rỗng hoàn toàn
            if not any(row):
                continue

            code = str(row[0]).strip() if row[0] is not None else ''
            title = str(row[1]).strip() if row[1] is not None else ''
            total_count += 1

            # Validate dữ liệu bắt buộc
            if not code:
                error_list.append(f"Dòng {row_idx}: Mã bệnh không được để trống")
                continue
            if not title:
                error_list.append(f"Dòng {row_idx}: Tên phân loại không được để trống")
                continue

            code_upper = code.upper()

            # Kiểm tra trùng trong cùng file Excel
            if code_upper in seen_in_file:
                error_list.append(f"Dòng {row_idx}: Mã bệnh '{code}' bị trùng trong file Excel")
                continue

            # Kiểm tra trùng mã với dữ liệu đã có trong hệ thống
            if code_upper in existing_codes:
                error_list.append(f"Dòng {row_idx}: Mã bệnh '{code}' đã tồn tại trong hệ thống")
                continue

            try:
                doc = frappe.get_doc({
                    "doctype": "SIS Disease Classification",
                    "code": code,
                    "title": title,
                    "campus": campus,
                    "enabled": 1
                })
                doc.insert(ignore_permissions=True)
                success_count += 1
                seen_in_file.add(code_upper)
                existing_codes.add(code_upper)
            except Exception as e:
                error_list.append(f"Dòng {row_idx}: {str(e)}")

        frappe.db.commit()

        message = f"Import phân loại bệnh hoàn tất"
        return success_response(
            data={
                "success_count": success_count,
                "total_count": total_count,
                "errors": error_list,
                "message": message
            },
            message=message
        )

    except Exception as e:
        frappe.logger().error(f"Error importing disease classifications: {str(e)}")
        return error_response(
            message=f"Lỗi khi import phân loại bệnh: {str(e)}",
            code="IMPORT_DISEASE_CLASSIFICATION_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def import_medicines_excel(campus=None):
    """
    Import thuốc từ file Excel.
    Cột A: Tên thuốc, Cột B: Đơn vị (tùy chọn), Cột C: Mô tả (tùy chọn)
    """
    try:
        import openpyxl
        import io

        # Đọc campus từ nhiều nguồn: tham số hàm, form_dict, query string
        campus = (
            campus
            or frappe.form_dict.get('campus')
            or (frappe.request.args.get('campus') if frappe.request else None)
        )
        if not campus:
            return error_response(
                message="Thiếu thông tin trường học",
                code="MISSING_CAMPUS"
            )

        # Kiểm tra campus tồn tại
        if not frappe.db.exists("SIS Campus", campus):
            return error_response(
                message=f"Không tìm thấy trường học: {campus}",
                code="CAMPUS_NOT_FOUND"
            )

        # Lấy file từ request
        file_obj = frappe.request.files.get('file')
        if not file_obj:
            return error_response(
                message="Không tìm thấy file",
                code="MISSING_FILE"
            )

        file_data = file_obj.read()
        wb = openpyxl.load_workbook(io.BytesIO(file_data), read_only=True, data_only=True)
        ws = wb.active

        success_count = 0
        error_list = []
        total_count = 0

        # Tải trước danh sách tên thuốc đã có để kiểm tra trùng nhanh (so sánh lowercase)
        existing_titles = set(
            r.title.strip().lower()
            for r in frappe.get_all("SIS Medicine", filters={"campus": campus}, fields=["title"])
            if r.title
        )
        # Theo dõi tên trong file Excel để phát hiện trùng nội bộ
        seen_in_file = set()

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            # Bỏ qua dòng rỗng hoàn toàn
            if not any(row):
                continue

            title = str(row[0]).strip() if row[0] is not None else ''
            unit = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ''
            description = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ''
            total_count += 1

            # Validate dữ liệu bắt buộc
            if not title:
                error_list.append(f"Dòng {row_idx}: Tên thuốc không được để trống")
                continue

            title_lower = title.lower()

            # Kiểm tra trùng trong cùng file Excel
            if title_lower in seen_in_file:
                error_list.append(f"Dòng {row_idx}: Tên thuốc '{title}' bị trùng trong file Excel")
                continue

            # Kiểm tra trùng với dữ liệu đã có trong hệ thống
            if title_lower in existing_titles:
                error_list.append(f"Dòng {row_idx}: Tên thuốc '{title}' đã tồn tại trong hệ thống")
                continue

            try:
                doc = frappe.get_doc({
                    "doctype": "SIS Medicine",
                    "title": title,
                    "unit": unit or None,
                    "description": description or None,
                    "campus": campus,
                    "enabled": 1
                })
                doc.insert(ignore_permissions=True)
                success_count += 1
                # Thêm vào tập đã xử lý để tránh trùng các dòng sau trong file
                seen_in_file.add(title_lower)
                existing_titles.add(title_lower)
            except Exception as e:
                error_list.append(f"Dòng {row_idx}: {str(e)}")

        frappe.db.commit()

        message = f"Import thuốc hoàn tất"
        return success_response(
            data={
                "success_count": success_count,
                "total_count": total_count,
                "errors": error_list,
                "message": message
            },
            message=message
        )

    except Exception as e:
        frappe.logger().error(f"Error importing medicines: {str(e)}")
        return error_response(
            message=f"Lỗi khi import thuốc: {str(e)}",
            code="IMPORT_MEDICINE_ERROR"
        )


# ========================================================================================
# TEACHER HEALTH APIs - Cho giáo viên xem hồ sơ thăm khám và gửi đến phụ huynh
# ========================================================================================

@frappe.whitelist(allow_guest=False)
def get_class_health_examinations():
    """
    Lấy danh sách hồ sơ thăm khám của học sinh trong lớp theo ngày.
    Dành cho giáo viên chủ nhiệm xem.
    
    Params:
        - class_id: ID lớp (required)
        - date: Ngày cần lấy dữ liệu (optional, default: today)
    
    Returns:
        - data: Danh sách học sinh có hồ sơ thăm khám, grouped theo student
    """
    try:
        _check_teacher_permission()
        
        # Ưu tiên đọc từ form_dict (GET query params) trước
        class_id = frappe.form_dict.get("class_id")
        date = frappe.form_dict.get("date") or today()
        
        # Nếu không có trong form_dict, thử đọc từ request body (POST)
        if not class_id:
            data = _get_request_data()
            class_id = data.get("class_id")
            date = data.get("date") or date
        
        if not class_id:
            return validation_error_response("Thiếu class_id", {"class_id": ["class_id là bắt buộc"]})
        
        # Lấy danh sách student_id trong lớp
        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"parent": class_id},
            fields=["student_id"]
        )
        student_ids = [cs.student_id for cs in class_students]
        
        if not student_ids:
            return success_response(data={"data": []}, message="Không có học sinh trong lớp")
        
        # Lấy tất cả Daily Health Visits của các học sinh trong ngày
        visits = frappe.get_all(
            "SIS Daily Health Visit",
            filters={
                "student_id": ["in", student_ids],
                "visit_date": date
            },
            fields=[
                "name", "student_id", "student_name", "student_code",
                "visit_date", "reason", "leave_class_time", "arrive_clinic_time",
                "leave_clinic_time", "status", "reported_by_name", "received_by_name"
            ],
            order_by="creation desc"
        )
        
        # Lấy tất cả Health Examinations của các học sinh trong ngày
        examinations = frappe.get_all(
            "SIS Health Examination",
            filters={
                "student_id": ["in", student_ids],
                "examination_date": date
            },
            fields=[
                "name", "student_id", "student_name", "student_code",
                "examination_date", "visit_id", "symptoms", "disease_classification",
                "examination_notes", "treatment_type", "treatment_details",
                "outcome", "examined_by_name", "sent_to_parent", "sent_to_parent_at",
                "creation", "modified"
            ],
            order_by="creation desc"
        )
        
        # Lấy thông tin ảnh học sinh
        student_photos = {}
        if student_ids:
            students_info = frappe.get_all(
                "CRM Student",
                filters={"name": ["in", student_ids]},
                fields=["name", "student_photo"]
            )
            student_photos = {s.name: s.student_photo for s in students_info}
        
        # Group theo student
        student_data = {}
        
        # Thêm visits
        for visit in visits:
            sid = visit.student_id
            if sid not in student_data:
                student_data[sid] = {
                    "student_id": sid,
                    "student_name": visit.student_name,
                    "student_code": visit.student_code,
                    "student_photo": student_photos.get(sid, ""),
                    "visits": [],
                    "examinations": []
                }
            student_data[sid]["visits"].append(visit)
        
        # Thêm examinations
        for exam in examinations:
            sid = exam.student_id
            if sid not in student_data:
                student_data[sid] = {
                    "student_id": sid,
                    "student_name": exam.student_name,
                    "student_code": exam.student_code,
                    "student_photo": student_photos.get(sid, ""),
                    "visits": [],
                    "examinations": []
                }
            
            # Lấy images cho exam
            images = frappe.get_all(
                "SIS Examination Image",
                filters={"parent": exam.name},
                fields=["image", "description"]
            )
            exam["images"] = images
            
            student_data[sid]["examinations"].append(exam)
        
        # Convert dict to list và sắp xếp theo tên
        result = sorted(student_data.values(), key=lambda x: x.get("student_name", ""))
        
        return success_response(
            data={"data": result},
            message=f"Lấy danh sách thăm khám thành công ({len(result)} học sinh)"
        )
        
    except frappe.PermissionError as e:
        return error_response(message=str(e), code="PERMISSION_DENIED")
    except Exception as e:
        frappe.logger().error(f"Error getting class health examinations: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        return error_response(
            message=f"Lỗi khi lấy danh sách thăm khám: {str(e)}",
            code="GET_CLASS_HEALTH_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def send_exam_to_parent():
    """
    Gửi hồ sơ thăm khám đến phụ huynh qua notification.
    
    Params:
        - exam_ids: Danh sách ID hồ sơ thăm khám cần gửi (required)
    
    Returns:
        - success: True/False
        - message: Thông báo kết quả
        - sent_count: Số lượng đã gửi thành công
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        exam_ids = data.get("exam_ids") or []
        
        if not exam_ids:
            return validation_error_response("Thiếu exam_ids", {"exam_ids": ["exam_ids là bắt buộc"]})
        
        if isinstance(exam_ids, str):
            exam_ids = [exam_ids]
        
        # Lấy thông tin các exam
        exams = frappe.get_all(
            "SIS Health Examination",
            filters={"name": ["in", exam_ids]},
            fields=["name", "student_id", "student_name", "student_code", "disease_classification", "sent_to_parent"]
        )
        
        if not exams:
            return validation_error_response("Không tìm thấy hồ sơ thăm khám", {"exam_ids": ["Không tìm thấy hồ sơ"]})
        
        # Lọc chỉ những exam chưa gửi
        exams_to_send = [e for e in exams if not e.sent_to_parent]
        
        if not exams_to_send:
            return success_response(
                data={"sent_count": 0},
                message="Tất cả hồ sơ đã được gửi trước đó"
            )
        
        # Import notification handler
        from erp.utils.notification_handler import send_bulk_parent_notifications
        
        # Group exams theo student để gửi notification gộp
        student_exams = {}
        for exam in exams_to_send:
            sid = exam.student_id
            if sid not in student_exams:
                student_exams[sid] = {
                    "student_name": exam.student_name,
                    "student_code": exam.student_code,
                    "exams": []
                }
            student_exams[sid]["exams"].append(exam)
        
        sent_count = 0
        notification_results = []
        
        for student_id, info in student_exams.items():
            student_name = info["student_name"]
            exam_names = [e.name for e in info["exams"]]
            
            # Chuẩn bị notification
            title = {
                "vi": f"Học sinh {student_name} có cập nhật mới về sức khỏe",
                "en": f"Student {student_name} has health update"
            }
            
            body = {
                "vi": f"Phòng Y tế đã ghi nhận thông tin thăm khám cho {student_name}. Nhấn để xem chi tiết.",
                "en": f"Health clinic has recorded examination information for {student_name}. Tap to view details."
            }
            
            try:
                result = send_bulk_parent_notifications(
                    recipient_type="health_examination",
                    recipients_data={"student_ids": [student_id]},
                    title=title,
                    body=body,
                    icon="/health-icon.png",
                    data={
                        "type": "health_examination",
                        "student_id": student_id,
                        "student_name": student_name,
                        "exam_ids": exam_names
                    }
                )
                
                notification_results.append({
                    "student_id": student_id,
                    "success": result.get("success", False),
                    "message": result.get("message", "")
                })
                
                if result.get("success"):
                    # Cập nhật sent_to_parent cho các exams
                    for exam_name in exam_names:
                        frappe.db.set_value(
                            "SIS Health Examination",
                            exam_name,
                            {
                                "sent_to_parent": 1,
                                "sent_to_parent_at": now()
                            },
                            update_modified=False
                        )
                        sent_count += 1
                        
            except Exception as notif_err:
                frappe.logger().error(f"Error sending notification for student {student_id}: {str(notif_err)}")
                notification_results.append({
                    "student_id": student_id,
                    "success": False,
                    "message": str(notif_err)
                })
        
        frappe.db.commit()
        
        return success_response(
            data={
                "sent_count": sent_count,
                "total_requested": len(exams_to_send),
                "results": notification_results
            },
            message=f"Đã gửi {sent_count}/{len(exams_to_send)} hồ sơ thăm khám đến phụ huynh"
        )
        
    except frappe.PermissionError as e:
        return error_response(message=str(e), code="PERMISSION_DENIED")
    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Error sending exam to parent: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        return error_response(
            message=f"Lỗi khi gửi hồ sơ đến phụ huynh: {str(e)}",
            code="SEND_EXAM_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def recall_exam_from_parent():
    """
    Thu hồi hồ sơ thăm khám đã gửi đến phụ huynh.
    Xóa notifications và cập nhật trạng thái sent_to_parent = 0.
    
    Params:
        - exam_ids: Danh sách ID hồ sơ thăm khám cần thu hồi (required)
    
    Returns:
        - success: True/False
        - message: Thông báo kết quả
        - recalled_count: Số lượng đã thu hồi thành công
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        exam_ids = data.get("exam_ids") or []
        
        if not exam_ids:
            return validation_error_response("Thiếu exam_ids", {"exam_ids": ["exam_ids là bắt buộc"]})
        
        if isinstance(exam_ids, str):
            exam_ids = [exam_ids]
        
        # Lấy thông tin các exam đã gửi
        exams = frappe.get_all(
            "SIS Health Examination",
            filters={
                "name": ["in", exam_ids],
                "sent_to_parent": 1
            },
            fields=["name", "student_id"]
        )
        
        if not exams:
            return success_response(
                data={"recalled_count": 0},
                message="Không có hồ sơ nào cần thu hồi"
            )
        
        recalled_count = 0
        
        for exam in exams:
            exam_id = exam.name
            
            # Tìm và xóa notifications liên quan
            # Pattern: Tìm notifications có type health_examination và chứa exam_id trong data
            notifications = frappe.db.sql("""
                SELECT name FROM `tabERP Notification`
                WHERE notification_type = 'health_examination'
                AND (
                    data LIKE %(pattern1)s
                    OR data LIKE %(pattern2)s
                )
            """, {
                "pattern1": f'%"{exam_id}"%',
                "pattern2": f'%\'{exam_id}\'%'
            }, as_dict=True)
            
            for notif in notifications:
                try:
                    frappe.delete_doc("ERP Notification", notif.name, force=True, ignore_permissions=True)
                except Exception as del_err:
                    frappe.logger().warning(f"Could not delete notification {notif.name}: {str(del_err)}")
            
            # Cập nhật trạng thái exam
            frappe.db.set_value(
                "SIS Health Examination",
                exam_id,
                {
                    "sent_to_parent": 0,
                    "sent_to_parent_at": None
                },
                update_modified=False
            )
            recalled_count += 1
        
        frappe.db.commit()
        
        return success_response(
            data={"recalled_count": recalled_count},
            message=f"Đã thu hồi {recalled_count} hồ sơ thăm khám"
        )
        
    except frappe.PermissionError as e:
        return error_response(message=str(e), code="PERMISSION_DENIED")
    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Error recalling exam from parent: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        return error_response(
            message=f"Lỗi khi thu hồi hồ sơ: {str(e)}",
            code="RECALL_EXAM_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_parent_health_records():
    """
    API dành cho Parent Portal: Lấy danh sách hồ sơ thăm khám đã được gửi đến phụ huynh.
    
    Params:
        - student_id: ID học sinh (required)
    
    Returns:
        - data: Danh sách hồ sơ thăm khám grouped theo ngày
    """
    try:
        data = _get_request_data()
        student_id = data.get("student_id") or frappe.form_dict.get("student_id")
        
        if not student_id:
            return validation_error_response("Thiếu student_id", {"student_id": ["student_id là bắt buộc"]})
        
        # Lấy tất cả examinations đã gửi đến parent
        examinations = frappe.get_all(
            "SIS Health Examination",
            filters={
                "student_id": student_id,
                "sent_to_parent": 1
            },
            fields=[
                "name", "student_id", "student_name", "student_code",
                "examination_date", "visit_id", "symptoms", "disease_classification",
                "examination_notes", "treatment_type", "treatment_details",
                "outcome", "examined_by_name", "sent_to_parent_at",
                "creation", "modified"
            ],
            order_by="examination_date desc, creation desc"
        )
        
        # Lấy images cho từng exam
        for exam in examinations:
            images = frappe.get_all(
                "SIS Examination Image",
                filters={"parent": exam.name},
                fields=["image", "description"]
            )
            exam["images"] = images
        
        # Group theo ngày
        grouped = {}
        for exam in examinations:
            date_key = str(exam.examination_date)
            if date_key not in grouped:
                grouped[date_key] = []
            grouped[date_key].append(exam)
        
        # Convert to list sorted by date desc
        result = [
            {"date": date, "examinations": exams}
            for date, exams in sorted(grouped.items(), reverse=True)
        ]
        
        return success_response(
            data={"data": result, "total": len(examinations)},
            message=f"Lấy {len(examinations)} hồ sơ thăm khám thành công"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error getting parent health records: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        return error_response(
            message=f"Lỗi khi lấy hồ sơ thăm khám: {str(e)}",
            code="GET_PARENT_HEALTH_ERROR"
        )
