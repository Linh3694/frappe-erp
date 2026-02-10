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
    if hasattr(frappe.request, 'is_json') and frappe.request.is_json:
        data = frappe.request.json or {}
    else:
        data = {}
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
        
        if not data and frappe.local.form_dict:
            data = dict(frappe.local.form_dict)
    
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
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        student_id = data.get("student_id")
        class_id = data.get("class_id")
        reason = data.get("reason")
        leave_class_time = data.get("leave_class_time") or nowtime()
        
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
        class_info = frappe.db.get_value("SIS Class", class_id, ["title"], as_dict=True)
        
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
        frappe.db.commit()
        
        return success_response(
            data={"name": visit.name, "status": visit.status},
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
        - symptoms: Triệu chứng/Thăm khám (required)
        - diagnosis: Chẩn đoán (optional)
        - treatment: Xử lý/Dặn dò (optional)
        - outcome: Kết quả (optional)
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        visit_id = data.get("visit_id")
        symptoms = data.get("symptoms")
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
            "diagnosis": diagnosis,
            "treatment": treatment,
            "outcome": outcome,
            "examined_by": examined_by_user,
            "examined_by_name": examined_by_name
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
        - symptoms: Triệu chứng/Thăm khám (optional)
        - diagnosis: Chẩn đoán (optional)
        - treatment: Xử lý/Dặn dò (optional)
        - outcome: Kết quả (optional)
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        exam_id = data.get("exam_id")
        symptoms = data.get("symptoms")
        diagnosis = data.get("diagnosis")
        treatment = data.get("treatment")
        outcome = data.get("outcome")
        
        if not exam_id:
            return validation_error_response("exam_id là bắt buộc", {"exam_id": ["exam_id là bắt buộc"]})
        
        # Lấy examination
        exam = frappe.get_doc("SIS Health Examination", exam_id)
        
        # Cập nhật các trường
        if symptoms is not None:
            exam.symptoms = symptoms
        if diagnosis is not None:
            exam.diagnosis = diagnosis
        if treatment is not None:
            exam.treatment = treatment
        if outcome is not None:
            exam.outcome = outcome
        
        exam.save()
        frappe.db.commit()
        
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
                "treatment", "outcome", "examined_by_name", "creation"
            ],
            order_by="examination_date desc, creation desc",
            limit=limit
        )
        
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
