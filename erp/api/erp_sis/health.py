# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Health Report API for SIS
Handles health reports from homeroom teachers and porridge registration
"""

import frappe
from frappe import _
from frappe.utils import today, now, get_datetime
import json
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
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
def get_class_health_reports():
    """
    Lấy danh sách báo cáo y tế theo lớp
    Params:
        - class_id: ID lớp (required)
        - date: Ngày báo cáo (optional, default: today)
    """
    try:
        _check_teacher_permission()
        
        data = frappe.local.form_dict
        request_args = frappe.request.args
        
        class_id = data.get("class_id") or request_args.get("class_id")
        report_date = data.get("date") or request_args.get("date") or today()
        
        if not class_id:
            return validation_error_response("class_id là bắt buộc", {"class_id": ["class_id là bắt buộc"]})
        
        # Lấy danh sách báo cáo
        reports = frappe.get_all(
            "SIS Health Report",
            filters={
                "class_id": class_id,
                "report_date": report_date
            },
            fields=[
                "name", "student_id", "student_name", "student_code",
                "class_id", "class_name", "description",
                "porridge_registration", "report_date",
                "created_by_user", "created_by_name", "creation"
            ],
            order_by="creation desc"
        )
        
        # Lấy porridge_dates cho mỗi report
        for report in reports:
            porridge_dates = frappe.get_all(
                "SIS Health Report Porridge",
                filters={"parent": report["name"]},
                fields=["date", "breakfast", "lunch", "afternoon"],
                order_by="date asc"
            )
            report["porridge_dates"] = porridge_dates
            report["created_at"] = str(report.get("creation", ""))
        
        return success_response(
            data={
                "data": reports,
                "total": len(reports)
            },
            message="Lấy danh sách báo cáo y tế thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error getting class health reports: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách báo cáo: {str(e)}",
            code="LIST_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_health_report():
    """
    Tạo báo cáo y tế mới
    Params:
        - student_id: ID học sinh (required)
        - class_id: ID lớp (required)
        - description: Mô tả sức khỏe (required)
        - porridge_registration: Đăng ký ăn cháo (boolean)
        - porridge_dates: JSON string chứa danh sách ngày ăn cháo
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        student_id = data.get("student_id")
        class_id = data.get("class_id")
        description = data.get("description")
        porridge_registration = data.get("porridge_registration", False)
        porridge_dates_str = data.get("porridge_dates")
        
        # Validation
        errors = {}
        if not student_id:
            errors["student_id"] = ["student_id là bắt buộc"]
        if not class_id:
            errors["class_id"] = ["class_id là bắt buộc"]
        if not description:
            errors["description"] = ["description là bắt buộc"]
        
        if errors:
            return validation_error_response("Dữ liệu không hợp lệ", errors)
        
        # Parse porridge_dates
        porridge_dates = []
        if porridge_dates_str:
            try:
                if isinstance(porridge_dates_str, str):
                    porridge_dates = json.loads(porridge_dates_str)
                else:
                    porridge_dates = porridge_dates_str
            except json.JSONDecodeError:
                return validation_error_response("porridge_dates không hợp lệ", {"porridge_dates": ["Định dạng JSON không hợp lệ"]})
        
        # Convert porridge_registration to boolean
        if isinstance(porridge_registration, str):
            porridge_registration = porridge_registration.lower() in ["true", "1", "yes"]
        
        # Tạo document
        doc = frappe.get_doc({
            "doctype": "SIS Health Report",
            "student_id": student_id,
            "class_id": class_id,
            "description": description,
            "porridge_registration": 1 if porridge_registration else 0,
            "report_date": today()
        })
        
        # Thêm porridge_dates
        if porridge_registration and porridge_dates:
            for pd in porridge_dates:
                doc.append("porridge_dates", {
                    "date": pd.get("date"),
                    "breakfast": 1 if pd.get("breakfast") else 0,
                    "lunch": 1 if pd.get("lunch") else 0,
                    "afternoon": 1 if pd.get("afternoon") else 0
                })
        
        doc.insert()
        frappe.db.commit()
        
        return success_response(
            data={"name": doc.name},
            message="Tạo báo cáo y tế thành công"
        )
    
    except frappe.ValidationError as e:
        return validation_error_response(str(e), {})
    except Exception as e:
        frappe.logger().error(f"Error creating health report: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo báo cáo: {str(e)}",
            code="CREATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_health_report():
    """
    Cập nhật báo cáo y tế
    Params:
        - report_id: ID báo cáo (required)
        - description: Mô tả sức khỏe
        - porridge_registration: Đăng ký ăn cháo (boolean)
        - porridge_dates: JSON string chứa danh sách ngày ăn cháo
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        
        report_id = data.get("report_id")
        description = data.get("description")
        porridge_registration = data.get("porridge_registration")
        porridge_dates_str = data.get("porridge_dates")
        
        if not report_id:
            return validation_error_response("report_id là bắt buộc", {"report_id": ["report_id là bắt buộc"]})
        
        # Lấy document
        doc = frappe.get_doc("SIS Health Report", report_id)
        
        # Cập nhật các trường
        if description is not None:
            doc.description = description
        
        if porridge_registration is not None:
            if isinstance(porridge_registration, str):
                porridge_registration = porridge_registration.lower() in ["true", "1", "yes"]
            doc.porridge_registration = 1 if porridge_registration else 0
        
        # Cập nhật porridge_dates
        if porridge_dates_str is not None:
            try:
                if isinstance(porridge_dates_str, str):
                    porridge_dates = json.loads(porridge_dates_str)
                else:
                    porridge_dates = porridge_dates_str
                
                # Xóa các porridge_dates cũ
                doc.porridge_dates = []
                
                # Thêm các porridge_dates mới
                if doc.porridge_registration and porridge_dates:
                    for pd in porridge_dates:
                        doc.append("porridge_dates", {
                            "date": pd.get("date"),
                            "breakfast": 1 if pd.get("breakfast") else 0,
                            "lunch": 1 if pd.get("lunch") else 0,
                            "afternoon": 1 if pd.get("afternoon") else 0
                        })
            except json.JSONDecodeError:
                return validation_error_response("porridge_dates không hợp lệ", {"porridge_dates": ["Định dạng JSON không hợp lệ"]})
        
        doc.save()
        frappe.db.commit()
        
        return success_response(
            data={"name": doc.name},
            message="Cập nhật báo cáo y tế thành công"
        )
    
    except frappe.DoesNotExistError:
        return error_response(
            message="Báo cáo y tế không tồn tại",
            code="NOT_FOUND"
        )
    except frappe.ValidationError as e:
        return validation_error_response(str(e), {})
    except Exception as e:
        frappe.logger().error(f"Error updating health report: {str(e)}")
        return error_response(
            message=f"Lỗi khi cập nhật báo cáo: {str(e)}",
            code="UPDATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_health_report():
    """
    Xóa báo cáo y tế
    Params:
        - report_id: ID báo cáo (required)
    """
    try:
        _check_teacher_permission()
        
        data = _get_request_data()
        request_args = frappe.request.args
        
        report_id = data.get("report_id") or request_args.get("report_id")
        
        if not report_id:
            return validation_error_response("report_id là bắt buộc", {"report_id": ["report_id là bắt buộc"]})
        
        # Kiểm tra tồn tại
        if not frappe.db.exists("SIS Health Report", report_id):
            return error_response(
                message="Báo cáo y tế không tồn tại",
                code="NOT_FOUND"
            )
        
        # Xóa document
        frappe.delete_doc("SIS Health Report", report_id, force=True)
        frappe.db.commit()
        
        return success_response(
            data={"name": report_id},
            message="Xóa báo cáo y tế thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error deleting health report: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa báo cáo: {str(e)}",
            code="DELETE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_daily_health_summary():
    """
    Lấy tổng hợp báo cáo y tế toàn trường (cho Operation)
    Params:
        - date: Ngày báo cáo (required)
        - campus: Campus filter (optional)
        - search: Tìm kiếm theo tên/mã học sinh (optional)
        - page: Trang (default: 1)
        - page_length: Số lượng mỗi trang (default: 50)
    """
    try:
        _check_teacher_permission()
        
        data = frappe.local.form_dict
        request_args = frappe.request.args
        
        report_date = data.get("date") or request_args.get("date") or today()
        campus = data.get("campus") or request_args.get("campus")
        search = data.get("search") or request_args.get("search")
        page = int(data.get("page") or request_args.get("page") or 1)
        page_length = int(data.get("page_length") or request_args.get("page_length") or 50)
        
        offset = (page - 1) * page_length
        
        # Build filters
        filters = {"report_date": report_date}
        if campus:
            filters["campus"] = campus
        
        # Search filters
        or_filters = None
        if search:
            or_filters = [
                ["student_name", "like", f"%{search}%"],
                ["student_code", "like", f"%{search}%"],
                ["class_name", "like", f"%{search}%"]
            ]
        
        # Lấy danh sách báo cáo
        reports = frappe.get_all(
            "SIS Health Report",
            filters=filters,
            or_filters=or_filters,
            fields=[
                "name", "student_id", "student_name", "student_code",
                "class_id", "class_name", "campus", "description",
                "porridge_registration", "report_date",
                "created_by_user", "created_by_name", "creation"
            ],
            order_by="creation desc",
            limit=page_length,
            limit_start=offset
        )
        
        # Lấy porridge_dates cho mỗi report
        for report in reports:
            porridge_dates = frappe.get_all(
                "SIS Health Report Porridge",
                filters={"parent": report["name"]},
                fields=["date", "breakfast", "lunch", "afternoon"],
                order_by="date asc"
            )
            report["porridge_dates"] = porridge_dates
            report["created_at"] = str(report.get("creation", ""))
        
        # Lấy tổng số
        total = frappe.db.count("SIS Health Report", filters=filters)
        
        return success_response(
            data={
                "data": reports,
                "total": total,
                "page": page,
                "page_length": page_length
            },
            message="Lấy tổng hợp báo cáo y tế thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error getting daily health summary: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy tổng hợp báo cáo: {str(e)}",
            code="SUMMARY_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_porridge_list():
    """
    Lấy danh sách học sinh ăn cháo (cho TrackingMeal)
    Params:
        - date: Ngày (required)
        - campus: Campus filter (optional)
        - search: Tìm kiếm theo tên/mã học sinh (optional)
    """
    try:
        _check_teacher_permission()
        
        data = frappe.local.form_dict
        request_args = frappe.request.args
        
        target_date = data.get("date") or request_args.get("date") or today()
        campus = data.get("campus") or request_args.get("campus")
        search = data.get("search") or request_args.get("search")
        
        # Query để lấy danh sách học sinh có đăng ký cháo cho ngày này
        # Sử dụng SQL để join với child table
        query = """
            SELECT DISTINCT
                hr.student_id,
                hr.student_name,
                hr.student_code,
                hr.class_id,
                hr.class_name,
                hr.campus,
                hrp.breakfast,
                hrp.lunch,
                hrp.afternoon
            FROM `tabSIS Health Report` hr
            INNER JOIN `tabSIS Health Report Porridge` hrp ON hrp.parent = hr.name
            WHERE hr.porridge_registration = 1
                AND hrp.date = %s
                AND (hrp.breakfast = 1 OR hrp.lunch = 1 OR hrp.afternoon = 1)
        """
        params = [target_date]
        
        if campus:
            query += " AND hr.campus = %s"
            params.append(campus)
        
        if search:
            query += " AND (hr.student_name LIKE %s OR hr.student_code LIKE %s OR hr.class_name LIKE %s)"
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])
        
        query += " ORDER BY hr.student_name ASC"
        
        results = frappe.db.sql(query, params, as_dict=True)
        
        # Tính thống kê
        total = len(results)
        total_breakfast = sum(1 for r in results if r.get("breakfast"))
        total_lunch = sum(1 for r in results if r.get("lunch"))
        total_afternoon = sum(1 for r in results if r.get("afternoon"))
        
        return success_response(
            data={
                "data": results,
                "total": total,
                "total_breakfast": total_breakfast,
                "total_lunch": total_lunch,
                "total_afternoon": total_afternoon
            },
            message="Lấy danh sách ăn cháo thành công"
        )
    
    except Exception as e:
        frappe.logger().error(f"Error getting porridge list: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách ăn cháo: {str(e)}",
            code="PORRIDGE_LIST_ERROR"
        )
