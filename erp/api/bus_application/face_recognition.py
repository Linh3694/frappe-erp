# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.rate_limiter import rate_limit
import json
import base64
from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)
from erp.api.bus_application.bus_monitor import get_request_param
from erp.utils.compreFace_service import compreFace_service


@frappe.whitelist(allow_guest=False)
@rate_limit(limit=100, seconds=600)  # 100 recognitions per 10 minutes
def recognize_student_face():
    """
    Recognize student face from base64 image
    Expected parameters (JSON):
    - image: Base64 encoded image data
    - campus_id: Campus ID for filtering
    - school_year_id: School year ID for filtering
    - trip_id: Optional trip ID to check if student belongs to trip
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get request data
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict

        image_b64 = data.get('image')
        campus_id = data.get('campus_id')
        school_year_id = data.get('school_year_id')
        trip_id = data.get('trip_id')

        if not image_b64:
            return validation_error_response({"image": ["Image data is required"]})

        if not campus_id:
            return validation_error_response({"campus_id": ["Campus ID is required"]})

        if not school_year_id:
            return validation_error_response({"school_year_id": ["School year ID is required"]})

        # Verify monitor has access to this campus
        # Extract monitor_code from email (format: monitor_code@busmonitor.wellspring.edu.vn)
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return error_response("Invalid user account format", code="INVALID_USER")

        monitor_code = user_email.split("@")[0]

        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active", "campus_id": campus_id},
            fields=["name"]
        )

        if not monitors:
            return forbidden_response("Access denied to this campus")

        # Send image to CompreFace for recognition
        recognition_result = compreFace_service.recognize_face(image_b64, limit=1)

        if not recognition_result.get("success"):
            return error_response(
                f"Face recognition failed: {recognition_result.get('message', 'Unknown error')}"
            )

        # Process recognition results
        recognition_data = recognition_result.get("data", {})
        recognized_faces = recognition_data.get("result", [])

        if not recognized_faces:
            return single_item_response({
                "recognized": False,
                "message": "No faces recognized in the image"
            }, "No faces detected")

        # Get the best match (highest similarity)
        best_match = None
        best_similarity = 0

        for face in recognized_faces:
            subjects = face.get("subjects", [])
            if subjects:
                subject = subjects[0]  # Get top match for this face
                similarity = subject.get("similarity", 0)

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = {
                        "student_code": subject.get("subject"),
                        "similarity": similarity,
                        "face_box": face.get("box", {})
                    }

        if not best_match or best_similarity < 0.7:  # Minimum similarity threshold
            # Log failed recognition attempt
            frappe.get_doc({
                "doctype": "Activity Log",
                "subject": f"FACE_RECOGNITION_FAILED: No matching student found",
                "communication_date": now_datetime(),
                "full_communication_content": json.dumps({
                    "monitor_id": monitors[0].name,
                    "trip_id": trip_id,
                    "campus_id": campus_id,
                    "school_year_id": school_year_id,
                    "best_similarity": best_similarity if best_match else 0,
                    "threshold": 0.7,
                    "recognized": False,
                    "faces_detected": len(recognized_faces),
                    "timestamp": now_datetime().isoformat()
                })
            }).insert(ignore_permissions=True)

            return single_item_response({
                "recognized": False,
                "message": "No matching student found",
                "similarity": best_similarity if best_match else 0
            }, "Student not recognized")

        # Get student information
        student_code = best_match["student_code"]
        bus_students = frappe.get_all(
            "SIS Bus Student",
            filters={
                "student_code": student_code,
                "campus_id": campus_id,
                "school_year_id": school_year_id,
                "status": "Active"
            },
            fields=["name", "full_name", "student_code", "class_id", "route_id"]
        )

        if not bus_students:
            return single_item_response({
                "recognized": False,
                "message": "Student not found in bus system",
                "student_code": student_code
            }, "Student not in bus system")

        bus_student = bus_students[0]

        # Get additional student information
        student_info = None
        try:
            student_info = frappe.get_doc("CRM Student", bus_student.name)
        except frappe.DoesNotExistError:
            pass

        # Check if student belongs to current trip (if trip_id provided)
        trip_student_status = None
        if trip_id:
            trip_students = frappe.get_all(
                "SIS Bus Daily Trip Student",
                filters={
                    "daily_trip_id": trip_id,
                    "student_id": bus_student.name
                },
                fields=["name", "student_status", "boarding_time", "drop_off_time"]
            )

            if trip_students:
                trip_student_status = trip_students[0]

        # Get class information
        class_info = None
        try:
            class_info = frappe.get_doc("SIS Class", bus_student.class_id)
        except frappe.DoesNotExistError:
            pass

        # Prepare response
        result = {
            "recognized": True,
            "student": {
                "id": bus_student.name,
                "student_code": bus_student.student_code,
                "full_name": bus_student.full_name,
                "class_id": bus_student.class_id,
                "class_name": class_info.title if class_info else None,
                "route_id": bus_student.route_id,
                "photo_url": student_info.user_image if student_info else None,
                "dob": student_info.dob if student_info else None,
                "gender": student_info.gender if student_info else None
            },
            "recognition": {
                "similarity": best_match["similarity"],
                "face_box": best_match["face_box"]
            },
            "trip_status": trip_student_status
        }

        # Log face recognition attempt
        frappe.get_doc({
            "doctype": "Activity Log",
            "subject": f"FACE_RECOGNITION: Student {bus_student.full_name} recognized in trip {trip_id}",
            "communication_date": now_datetime(),
            "full_communication_content": json.dumps({
                "monitor_id": monitors[0].name,
                "student_code": bus_student.student_code,
                "student_id": bus_student.name,
                "trip_id": trip_id,
                "similarity": best_match["similarity"],
                "confidence": "high" if best_match["similarity"] >= 0.95 else "medium",
                "face_box": best_match["face_box"],
                "recognized": True,
                "in_trip": trip_id is not None,
                "timestamp": now_datetime().isoformat()
            })
        }).insert(ignore_permissions=True)

        return single_item_response(result, f"Student {bus_student.full_name} recognized")

    except Exception as e:
        frappe.log_error(f"Error in face recognition: {str(e)}")
        return error_response(f"Face recognition error: {str(e)}")


@frappe.whitelist(allow_guest=False)
def check_student_in_trip():
    """
    Check-in a student to a trip (via face recognition or manual)
    Expected parameters (JSON):
    - student_id: Student ID
    - trip_id: Daily trip ID
    - method: "face_recognition" or "manual"
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get current monitor
        # Extract monitor_code from email (format: monitor_code@busmonitor.wellspring.edu.vn)
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return error_response("Invalid user account format", code="INVALID_USER")

        monitor_code = user_email.split("@")[0]

        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found")

        monitor_id = monitors[0].name

        # Get request data
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict

        student_id = data.get('student_id')
        trip_id = data.get('trip_id')
        method = data.get('method', 'manual')

        if not student_id:
            return validation_error_response({"student_id": ["Student ID is required"]})

        if not trip_id:
            return validation_error_response({"trip_id": ["Trip ID is required"]})

        # Verify monitor has access to this trip
        trip = frappe.get_doc("SIS Bus Daily Trip", trip_id)

        if trip.monitor1_id != monitor_id and trip.monitor2_id != monitor_id:
            return forbidden_response("Access denied to this trip")

        # Find the trip student record
        trip_students = frappe.get_all(
            "SIS Bus Daily Trip Student",
            filters={
                "daily_trip_id": trip_id,
                "student_id": student_id
            },
            fields=["name", "student_status"]
        )

        if not trip_students:
            return not_found_response("Student not assigned to this trip")

        trip_student = frappe.get_doc("SIS Bus Daily Trip Student", trip_students[0].name)

        # Update status based on trip type
        current_time = now_datetime()

        if trip.trip_type == "Đón":  # Pickup trip
            if trip_student.student_status == "Boarded":
                return validation_error_response({"student_id": ["Student already checked in"]})

            trip_student.student_status = "Boarded"
            trip_student.boarding_time = current_time
            trip_student.boarding_method = method

        elif trip.trip_type == "Trả":  # Drop-off trip
            if trip_student.student_status == "Dropped Off":
                return validation_error_response({"student_id": ["Student already checked out"]})

            trip_student.student_status = "Dropped Off"
            trip_student.drop_off_time = current_time
            trip_student.drop_off_method = method

        # Save with Administrator permissions
        frappe.set_user("Administrator")
        try:
            trip_student.flags.ignore_permissions = True
            trip_student.save(ignore_permissions=True)
            frappe.db.commit()
        finally:
            frappe.set_user("Guest")

        # Update trip statistics
        _update_trip_statistics(trip_id)

        # Log action
        frappe.get_doc({
            "doctype": "Activity Log",
            "subject": f"{method.upper()}: Student {student_id} checked in trip {trip_id}",
            "communication_date": now_datetime(),
            "full_communication_content": json.dumps({
                "monitor_id": monitor_id,
                "student_id": student_id,
                "trip_id": trip_id,
                "method": method,
                "status": trip_student.student_status,
                "timestamp": now_datetime().isoformat()
            })
        }).insert(ignore_permissions=True)

        return single_item_response({
            "student_id": student_id,
            "trip_id": trip_id,
            "status": trip_student.student_status,
            "timestamp": current_time,
            "method": method
        }, f"Student checked in successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Trip or student not found")
    except Exception as e:
        frappe.log_error(f"Error checking student in: {str(e)}")
        return error_response(f"Check-in error: {str(e)}")


@frappe.whitelist(allow_guest=False)
def mark_student_absent():
    """
    Mark a student as absent for a trip
    Expected parameters (JSON):
    - student_id: Student ID
    - trip_id: Daily trip ID
    - reason: Absent reason (Nghỉ học, Nghỉ ốm, Nghỉ phép, Lý do khác)
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get current monitor
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return error_response("Invalid user account format", code="INVALID_USER")

        monitor_code = user_email.split("@")[0]

        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found")

        monitor_id = monitors[0].name

        # Get request data
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict

        student_id = data.get('student_id')
        trip_id = data.get('trip_id')
        reason = data.get('reason', 'Lý do khác')

        if not student_id:
            return validation_error_response({"student_id": ["Student ID is required"]})

        if not trip_id:
            return validation_error_response({"trip_id": ["Trip ID is required"]})

        # Verify monitor has access to this trip
        trip = frappe.get_doc("SIS Bus Daily Trip", trip_id)

        if trip.monitor1_id != monitor_id and trip.monitor2_id != monitor_id:
            return forbidden_response("Access denied to this trip")

        # Find the trip student record
        trip_students = frappe.get_all(
            "SIS Bus Daily Trip Student",
            filters={
                "daily_trip_id": trip_id,
                "student_id": student_id
            },
            fields=["name"]
        )

        if not trip_students:
            return not_found_response("Student not assigned to this trip")

        trip_student = frappe.get_doc("SIS Bus Daily Trip Student", trip_students[0].name)

        # Mark as absent (with Administrator permissions)
        trip_student.student_status = "Absent"
        trip_student.absent_reason = reason

        frappe.set_user("Administrator")
        try:
            trip_student.flags.ignore_permissions = True
            trip_student.save(ignore_permissions=True)
            frappe.db.commit()
        finally:
            frappe.set_user("Guest")

        # Update trip statistics
        _update_trip_statistics(trip_id)

        # Log action
        frappe.get_doc({
            "doctype": "Activity Log",
            "subject": f"ABSENT: Student {student_id} marked absent in trip {trip_id}",
            "communication_date": now_datetime(),
            "full_communication_content": json.dumps({
                "monitor_id": monitor_id,
                "student_id": student_id,
                "trip_id": trip_id,
                "reason": reason,
                "status": "Absent",
                "timestamp": now_datetime().isoformat()
            })
        }).insert(ignore_permissions=True)

        return single_item_response({
            "student_id": student_id,
            "trip_id": trip_id,
            "status": "Absent",
            "reason": reason
        }, "Student marked as absent")

    except frappe.DoesNotExistError:
        return not_found_response("Trip or student not found")
    except Exception as e:
        frappe.log_error(f"Error marking student absent: {str(e)}")
        return error_response(f"Absent marking error: {str(e)}")


def _update_trip_statistics(trip_id):
    """
    Update trip statistics (checked_in_count, checked_out_count)
    """
    try:
        # Count boarded students (for pickup trips)
        boarded_count = frappe.db.sql("""
            SELECT COUNT(*) FROM `tabSIS Bus Daily Trip Student`
            WHERE daily_trip_id = %s AND student_status = 'Boarded'
        """, (trip_id,))[0][0]

        # Count dropped off students (for drop-off trips)
        dropped_count = frappe.db.sql("""
            SELECT COUNT(*) FROM `tabSIS Bus Daily Trip Student`
            WHERE daily_trip_id = %s AND student_status = 'Dropped Off'
        """, (trip_id,))[0][0]

        # Update trip
        frappe.db.set_value("SIS Bus Daily Trip", trip_id, {
            "checked_in_count": boarded_count,
            "checked_out_count": dropped_count
        })
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Error updating trip statistics: {str(e)}")


@frappe.whitelist(allow_guest=False)
@rate_limit(limit=100, seconds=600)
def verify_and_checkin():
    """
    Verify student face and automatically check them in if recognized.
    Combines recognize_student_face and check_student_in_trip in one call.
    
    Expected parameters (JSON):
    - image: Base64 encoded image data
    - trip_id: Daily trip ID (required)
    - auto_checkin: Boolean, if true automatically checks in on successful recognition (default: true)
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get current monitor
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return error_response("Invalid user account format", code="INVALID_USER")

        monitor_code = user_email.split("@")[0]

        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name", "campus_id", "school_year_id"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found")

        monitor = monitors[0]
        monitor_id = monitor.name

        # Get request data
        data = {}
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict

        image_b64 = data.get('image')
        trip_id = data.get('trip_id')
        auto_checkin = data.get('auto_checkin', True)

        if not image_b64:
            return validation_error_response({"image": ["Image data is required"]})

        if not trip_id:
            return validation_error_response({"trip_id": ["Trip ID is required"]})

        # Verify monitor has access to this trip
        trip = frappe.get_doc("SIS Bus Daily Trip", trip_id)

        if trip.monitor1_id != monitor_id and trip.monitor2_id != monitor_id:
            return forbidden_response("Access denied to this trip")

        # Send image to CompreFace for recognition
        frappe.logger().info(f"[FaceRecognition] Sending image to CompreFace for recognition")
        frappe.logger().info(f"[FaceRecognition] Image data length: {len(image_b64) if image_b64 else 0}")
        
        recognition_result = compreFace_service.recognize_face(image_b64, limit=1)
        
        frappe.logger().info(f"[FaceRecognition] CompreFace result: {json.dumps(recognition_result, default=str)[:500]}")

        if not recognition_result.get("success"):
            error_detail = recognition_result.get('error', 'Unknown error')
            error_msg = recognition_result.get('message', 'Unknown error')
            frappe.logger().error(f"[FaceRecognition] Recognition failed: {error_detail} - {error_msg}")
            return error_response(
                f"Nhận diện khuôn mặt thất bại: {error_msg}. Chi tiết: {error_detail}"
            )

        # Process recognition results
        recognition_data = recognition_result.get("data", {})
        recognized_faces = recognition_data.get("result", [])
        
        frappe.logger().info(f"[FaceRecognition] Recognition data: {json.dumps(recognition_data, default=str)[:500]}")
        frappe.logger().info(f"[FaceRecognition] Number of faces detected: {len(recognized_faces)}")

        if not recognized_faces:
            # Check if the response has no faces at all
            frappe.logger().warning(f"[FaceRecognition] No faces in response. Full data: {json.dumps(recognition_data, default=str)}")
            return single_item_response({
                "recognized": False,
                "checked_in": False,
                "message": "Không phát hiện khuôn mặt trong ảnh. Hãy đảm bảo khuôn mặt rõ ràng và đủ ánh sáng."
            }, "Không phát hiện khuôn mặt")

        # Get the best match
        best_match = None
        best_similarity = 0

        for face in recognized_faces:
            subjects = face.get("subjects", [])
            frappe.logger().info(f"[FaceRecognition] Face subjects: {json.dumps(subjects, default=str)[:200]}")
            
            if subjects:
                subject = subjects[0]
                similarity = subject.get("similarity", 0)
                frappe.logger().info(f"[FaceRecognition] Subject: {subject.get('subject')}, similarity: {similarity}")

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = {
                        "student_code": subject.get("subject"),
                        "similarity": similarity,
                        "face_box": face.get("box", {})
                    }
            else:
                frappe.logger().warning(f"[FaceRecognition] Face detected but no matching subjects. Box: {face.get('box', {})}")

        frappe.logger().info(f"[FaceRecognition] Best match: {best_match}, similarity: {best_similarity}")

        if not best_match or best_similarity < 0.7:
            if not best_match:
                message = "Phát hiện khuôn mặt nhưng không tìm thấy học sinh nào khớp trong hệ thống"
            else:
                message = f"Độ tương đồng quá thấp ({best_similarity:.0%}). Học sinh gần nhất: {best_match.get('student_code')}. Yêu cầu >= 70%"
            
            frappe.logger().warning(f"[FaceRecognition] Low similarity: {best_similarity}, match: {best_match}")
            
            return single_item_response({
                "recognized": False,
                "checked_in": False,
                "similarity": best_similarity if best_match else 0,
                "best_match": best_match.get('student_code') if best_match else None,
                "message": message
            }, message)

        student_code = best_match["student_code"]

        # Find student in this trip
        trip_students = frappe.db.sql("""
            SELECT dts.name, dts.student_id, dts.student_name, dts.student_status,
                   dts.class_name, dts.student_code
            FROM `tabSIS Bus Daily Trip Student` dts
            WHERE dts.daily_trip_id = %s AND dts.student_code = %s
        """, (trip_id, student_code), as_dict=True)

        if not trip_students:
            return single_item_response({
                "recognized": True,
                "checked_in": False,
                "student_code": student_code,
                "similarity": best_similarity,
                "message": "Học sinh không thuộc chuyến xe này"
            }, "Học sinh không thuộc chuyến xe này")

        trip_student_record = trip_students[0]

        result = {
            "recognized": True,
            "student": {
                "student_id": trip_student_record.student_id,
                "student_code": trip_student_record.student_code,
                "student_name": trip_student_record.student_name,
                "class_name": trip_student_record.class_name,
                "current_status": trip_student_record.student_status
            },
            "recognition": {
                "similarity": best_similarity,
                "confidence": "high" if best_similarity >= 0.95 else "medium" if best_similarity >= 0.85 else "low"
            }
        }

        # Auto check-in if enabled
        if auto_checkin:
            trip_student = frappe.get_doc("SIS Bus Daily Trip Student", trip_student_record.name)
            current_time = now_datetime()

            if trip.trip_type == "Đón":  # Pickup
                if trip_student.student_status != "Boarded":
                    trip_student.student_status = "Boarded"
                    trip_student.boarding_time = current_time
                    trip_student.boarding_method = "face_recognition"
                    
                    # Save with Administrator permissions
                    frappe.set_user("Administrator")
                    try:
                        trip_student.flags.ignore_permissions = True
                        trip_student.save(ignore_permissions=True)
                        frappe.db.commit()
                    finally:
                        frappe.set_user("Guest")
                    
                    _update_trip_statistics(trip_id)
                    result["checked_in"] = True
                    result["new_status"] = "Boarded"
                    result["message"] = f"Đã điểm danh {trip_student_record.student_name} lên xe"
                else:
                    result["checked_in"] = False
                    result["message"] = f"{trip_student_record.student_name} đã điểm danh rồi"
            else:  # Drop-off
                if trip_student.student_status != "Dropped Off":
                    trip_student.student_status = "Dropped Off"
                    trip_student.drop_off_time = current_time
                    trip_student.drop_off_method = "face_recognition"
                    
                    # Save with Administrator permissions
                    frappe.set_user("Administrator")
                    try:
                        trip_student.flags.ignore_permissions = True
                        trip_student.save(ignore_permissions=True)
                        frappe.db.commit()
                    finally:
                        frappe.set_user("Guest")
                    
                    _update_trip_statistics(trip_id)
                    result["checked_in"] = True
                    result["new_status"] = "Dropped Off"
                    result["message"] = f"Đã điểm danh {trip_student_record.student_name} xuống xe"
                else:
                    result["checked_in"] = False
                    result["message"] = f"{trip_student_record.student_name} đã xuống xe rồi"
        else:
            result["checked_in"] = False
            result["message"] = f"Nhận diện thành công: {trip_student_record.student_name}"

        return single_item_response(result, result.get("message", "Success"))

    except frappe.DoesNotExistError:
        return not_found_response("Trip not found")
    except Exception as e:
        frappe.log_error(f"Error in verify_and_checkin: {str(e)}")
        return error_response(f"Lỗi điểm danh: {str(e)}")


@frappe.whitelist(allow_guest=False)
def test_compreface():
    """
    Test CompreFace connection and list available subjects
    Returns diagnostic information about CompreFace setup
    """
    try:
        user_email = frappe.session.user
        
        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")
        
        # Test API endpoints
        test_result = compreFace_service.test_api_endpoints()
        
        # Get subjects list
        subjects_result = compreFace_service.list_subjects()
        
        return single_item_response({
            "compreface_url": compreFace_service.base_url,
            "api_test": test_result,
            "subjects": {
                "success": subjects_result.get("success", False),
                "count": len(subjects_result.get("data", [])) if subjects_result.get("success") else 0,
                "sample": subjects_result.get("data", [])[:10] if subjects_result.get("success") else [],
                "error": subjects_result.get("error") if not subjects_result.get("success") else None
            }
        }, "CompreFace diagnostic complete")
    except Exception as e:
        frappe.log_error(f"Error in test_compreface: {str(e)}")
        return error_response(f"Error: {str(e)}")


@frappe.whitelist(allow_guest=False)
def check_trip_students_in_compreface():
    """
    Check which students in a trip are registered in CompreFace
    Expected parameters:
    - trip_id: Daily trip ID
    """
    try:
        user_email = frappe.session.user
        
        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")
        
        # Get trip_id from params
        trip_id = frappe.local.form_dict.get('trip_id')
        if not trip_id:
            return validation_error_response({"trip_id": ["Trip ID is required"]})
        
        # Get subjects from CompreFace
        subjects_result = compreFace_service.list_subjects()
        if not subjects_result.get("success"):
            return error_response(f"Cannot connect to CompreFace: {subjects_result.get('error')}")
        
        compreface_subjects = set(subjects_result.get("data", []))
        
        # Get students in trip
        trip_students = frappe.db.sql("""
            SELECT dts.student_code, dts.student_name, dts.student_status
            FROM `tabSIS Bus Daily Trip Student` dts
            WHERE dts.daily_trip_id = %s
        """, (trip_id,), as_dict=True)
        
        registered = []
        not_registered = []
        
        for student in trip_students:
            if student.student_code in compreface_subjects:
                registered.append({
                    "student_code": student.student_code,
                    "student_name": student.student_name,
                    "status": student.student_status
                })
            else:
                not_registered.append({
                    "student_code": student.student_code,
                    "student_name": student.student_name,
                    "status": student.student_status
                })
        
        return single_item_response({
            "trip_id": trip_id,
            "total_students": len(trip_students),
            "registered_in_compreface": len(registered),
            "not_registered": len(not_registered),
            "registered_students": registered,
            "not_registered_students": not_registered,
            "message": f"{len(registered)}/{len(trip_students)} học sinh đã có trong hệ thống nhận diện"
        }, f"Checked {len(trip_students)} students")
        
    except Exception as e:
        frappe.log_error(f"Error in check_trip_students_in_compreface: {str(e)}")
        return error_response(f"Error: {str(e)}")
