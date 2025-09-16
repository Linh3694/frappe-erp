import frappe
from erp.utils.api_response import success_response, error_response, list_response, single_item_response, validation_error_response, not_found_response
from erp.utils.campus_utils import get_current_campus_from_context


@frappe.whitelist(allow_guest=False)
def get_all():
    try:
        campus_id = get_current_campus_from_context() or "campus-1"
        items = frappe.get_all(
            "SIS Subject Department",
            fields=["name", "title_vn", "title_en", "campus_id", "education_stage_id", "creation", "modified"],
            filters={"campus_id": campus_id},
            order_by="title_vn asc",
        )
        return list_response(data=items, message="Fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error get_all subject_department: {str(e)}")
        return error_response(message="Error fetching subject departments", code="FETCH_ERROR")


@frappe.whitelist(allow_guest=False)
def get_by_id(id=None):
    try:
        # Accept multiple sources and keys for robustness (align with update())
        if not id and frappe.form_dict:
            id = (
                frappe.form_dict.get("id")
                or frappe.form_dict.get("name")
                or frappe.form_dict.get("subject_department_id")
            )

        if not id and hasattr(frappe.request, 'args') and frappe.request.args:
            for key in ["id", "name", "subject_department_id"]:
                if key in frappe.request.args and frappe.request.args[key]:
                    id = frappe.request.args[key]
                    break

        if not id and frappe.request.data:
            # Try urlencoded first
            try:
                from urllib.parse import parse_qs
                data_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                if data_str.strip():
                    parsed = parse_qs(data_str, keep_blank_values=True)
                    for key in ["id", "name", "subject_department_id"]:
                        if key in parsed and parsed[key]:
                            id = parsed[key][0]
                            break
            except Exception:
                pass

        if not id and frappe.request.data:
            # Fallback to JSON
            try:
                import json
                json_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                if json_str.strip():
                    data = json.loads(json_str)
                    for key in ["id", "name", "subject_department_id"]:
                        if key in data and data[key]:
                            id = data[key]
                            break
            except Exception:
                pass

        if not id:
            return validation_error_response(message="ID is required", errors={"id": ["Required"]})

        doc = frappe.get_doc("SIS Subject Department", id)
        return single_item_response(
            data={
                "name": doc.name,
                "title_vn": doc.title_vn,
                "title_en": doc.title_en,
                "campus_id": doc.campus_id,
                "education_stage_id": getattr(doc, "education_stage_id", None),
            },
            message="Fetched successfully",
        )
    except frappe.DoesNotExistError:
        return not_found_response(message="Subject Department not found", code="NOT_FOUND")
    except Exception as e:
        frappe.log_error(f"Error get_by_id subject_department: {str(e)}")
        return error_response(message="Error fetching subject department", code="FETCH_ERROR")


@frappe.whitelist(allow_guest=False)
def create():
    try:
        title_vn = None
        title_en = None
        education_stage_id = None

        # Method 1: form_dict
        if frappe.form_dict:
            title_vn = frappe.form_dict.get("title_vn")
            title_en = frappe.form_dict.get("title_en")
            education_stage_id = frappe.form_dict.get("education_stage_id")

        # Method 2: local.form_dict
        if (not title_vn or not title_en) and hasattr(frappe.local, 'form_dict') and frappe.local.form_dict:
            title_vn = title_vn or frappe.local.form_dict.get("title_vn")
            title_en = title_en or frappe.local.form_dict.get("title_en")
            education_stage_id = education_stage_id or frappe.local.form_dict.get("education_stage_id")

        # Method 3: parse raw request data (urlencoded)
        if (not title_vn or not title_en) and frappe.request.data:
            try:
                from urllib.parse import parse_qs
                data_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                if data_str.strip():
                    parsed = parse_qs(data_str)
                    title_vn = title_vn or parsed.get('title_vn', [None])[0]
                    title_en = title_en or parsed.get('title_en', [None])[0]
                    education_stage_id = education_stage_id or parsed.get('education_stage_id', [None])[0]
            except Exception:
                pass

        # Method 4: JSON fallback
        if (not title_vn or not title_en) and frappe.request.data:
            try:
                import json
                json_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                if json_str.strip():
                    data = json.loads(json_str)
                    title_vn = title_vn or data.get('title_vn')
                    title_en = title_en or data.get('title_en')
                    education_stage_id = education_stage_id or data.get('education_stage_id')
            except Exception:
                pass

        # Normalize 'none' to None
        if isinstance(education_stage_id, str) and education_stage_id.lower() == 'none':
            education_stage_id = None

        if not title_vn or not title_en:
            return validation_error_response(
                message="title_vn and title_en are required",
                errors={"title_vn": ["Required"], "title_en": ["Required"]},
            )

        campus_id = get_current_campus_from_context() or "campus-1"
        doc = frappe.get_doc(
            {
                "doctype": "SIS Subject Department",
                "title_vn": title_vn,
                "title_en": title_en,
                "education_stage_id": education_stage_id,
                "campus_id": campus_id,
            }
        )
        doc.insert()
        frappe.db.commit()
        return single_item_response(
            data={
                "name": doc.name,
                "title_vn": doc.title_vn,
                "title_en": doc.title_en,
                "campus_id": doc.campus_id,
                "education_stage_id": getattr(doc, "education_stage_id", None),
            },
            message="Created successfully",
        )
    except Exception as e:
        frappe.log_error(f"Error create subject_department: {str(e)}")
        return error_response(message="Error creating subject department", code="CREATE_ERROR")


@frappe.whitelist(allow_guest=False)
def update():
    frappe.logger().info(f"🔧 ===== update_subject_department API STARTED =====")
    frappe.logger().info(f"🔧 Session user: {frappe.session.user}")
    frappe.logger().info(f"🔧 Form dict keys: {list(frappe.form_dict.keys()) if frappe.form_dict else 'None'}")
    frappe.logger().info(f"🔧 Request method: {frappe.request.method}")
    frappe.logger().info(f"🔧 Request content type: {frappe.request.content_type}")
    frappe.logger().info(f"🔧 Raw request data: {frappe.request.data}")

    debug_info = {
        "session_user": frappe.session.user,
        "session_sid": getattr(frappe.session, 'sid', None),
        "user_is_authenticated": bool(frappe.session.user and frappe.session.user != "Guest"),
        "form_dict_keys": list(frappe.form_dict.keys()) if frappe.form_dict else [],
        "request_method": frappe.request.method,
        "request_content_type": frappe.request.content_type,
        "raw_request_data": str(frappe.request.data) if frappe.request.data else None,
        "request_headers": dict(frappe.request.headers) if hasattr(frappe.request, 'headers') else None
    }

    # Check authentication
    if not frappe.session.user or frappe.session.user == "Guest":
        debug_info["auth_issue"] = "User not authenticated or is Guest"
        frappe.logger().warning(f"🔧 Unauthenticated request - user: {frappe.session.user}")
    else:
        debug_info["auth_issue"] = "User authenticated"
        frappe.logger().info(f"🔧 Authenticated request - user: {frappe.session.user}")

    try:
        frappe.logger().info(f"🔧 ===== update_subject_department API called =====")
        id = None
        # Accept multiple param names for compatibility
        candidate_keys = ["id", "subject_department_id"]

        # Update debug_info with initial state
        debug_info["candidate_keys"] = candidate_keys
        debug_info["attempt_order"] = ["form_dict", "request_args", "url_encoded", "json"]

        # First try: direct parameter from function call
        id = frappe.form_dict.get('id') or frappe.form_dict.get('subject_department_id')
        if id:
            frappe.logger().info(f"🔧 Found id from direct form_dict access: {id}")
            debug_info["id_source"] = "form_dict"
            debug_info["id_value"] = id
        else:
            frappe.logger().info(f"🔧 No id found in direct form_dict access")
            debug_info["id_source"] = "not_found_in_form_dict"

        # Second try: check URL query parameters for GET-style parameters
        if not id and hasattr(frappe.request, 'args') and frappe.request.args:
            frappe.logger().info(f"🔧 Checking request.args: {frappe.request.args}")
            debug_info["request_args"] = frappe.request.args
            for k in candidate_keys:
                if k in frappe.request.args and frappe.request.args[k]:
                    id = frappe.request.args[k]
                    frappe.logger().info(f"🔧 Found id from request.args: {id} (key: {k})")
                    debug_info["id_source"] = "request_args"
                    debug_info["id_value"] = id
                    break

        # Third try: parse from request.data for form-urlencoded data
        if not id and frappe.request.data:
            try:
                frappe.logger().info(f"🔧 Attempting to parse request.data")
                from urllib.parse import parse_qs
                data_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                frappe.logger().info(f"🔧 Raw request data: {data_str}")
                debug_info["raw_request_data"] = data_str

                if data_str.strip():
                    # First try: parse as URL-encoded form data
                    try:
                        parsed = parse_qs(data_str, keep_blank_values=True)
                        frappe.logger().info(f"🔧 Parsed as URL-encoded: {parsed}")
                        debug_info["parsed_url_encoded"] = parsed

                        for k in candidate_keys:
                            frappe.logger().info(f"🔧 Checking candidate key '{k}' in parsed data")
                            if k in parsed and parsed[k]:
                                id = parsed[k][0]  # parse_qs returns lists
                                frappe.logger().info(f"🔧 Found id from URL-encoded: {id} (key: {k})")
                                debug_info["id_source"] = "url_encoded"
                                debug_info["id_value"] = id
                                break
                            else:
                                frappe.logger().info(f"🔧 Key '{k}' not found or empty in parsed data")
                    except Exception as url_error:
                        frappe.logger().info(f"🔧 URL-encoded parsing failed: {str(url_error)}, trying JSON")
                        debug_info["url_encoded_error"] = str(url_error)

                    # Second try: parse as JSON if URL-encoded failed
                    if not id:
                        try:
                            import json
                            json_data = json.loads(data_str)
                            frappe.logger().info(f"🔧 Parsed as JSON: {json_data}")
                            debug_info["parsed_json"] = json_data

                            for k in candidate_keys:
                                if k in json_data and json_data[k]:
                                    id = json_data[k]
                                    frappe.logger().info(f"🔧 Found id from JSON: {id} (key: {k})")
                                    debug_info["id_source"] = "json"
                                    debug_info["id_value"] = id
                                    break
                        except Exception as json_error:
                            frappe.logger().info(f"🔧 JSON parsing also failed: {str(json_error)}")
                            debug_info["json_error"] = str(json_error)
            except Exception as e:
                frappe.logger().error(f"🔧 Error parsing request.data: {str(e)}")
                debug_info["parse_error"] = str(e)

        if not id:
            frappe.logger().error(f"🔧 No ID found in any source - returning validation error with debug info")
            debug_info["final_id"] = None
            debug_info["candidate_keys_tried"] = candidate_keys

            # Return validation error with debug information
            return validation_error_response(
                message="ID is required",
                errors={"id": ["Required"]},
                debug_info=debug_info
            )

        frappe.logger().info(f"🔧 Final ID used: {id}")
        debug_info["final_id"] = id
        debug_info["id_source"] = debug_info.get("id_source", "unknown")
        debug_info["id_value"] = id

        doc = frappe.get_doc("SIS Subject Department", id)

        # Read fields similarly from multiple sources
        def read_field(key: str):
            val = None
            if frappe.form_dict and key in frappe.form_dict:
                val = frappe.form_dict.get(key)
            if val is None and hasattr(frappe.local, 'form_dict') and frappe.local.form_dict and key in frappe.local.form_dict:
                val = frappe.local.form_dict.get(key)
            if val is None and frappe.request.data:
                try:
                    from urllib.parse import parse_qs
                    data_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                    if data_str.strip():
                        parsed = parse_qs(data_str)
                        val = parsed.get(key, [None])[0]
                except Exception:
                    pass
            if val is None and frappe.request.data:
                try:
                    import json
                    json_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                    if json_str.strip():
                        data = json.loads(json_str)
                        val = data.get(key)
                except Exception:
                    pass
            return val

        title_vn = read_field('title_vn')
        title_en = read_field('title_en')
        education_stage_id = read_field('education_stage_id')

        if isinstance(education_stage_id, str) and education_stage_id.lower() == 'none':
            education_stage_id = None

        changed = False
        if title_vn is not None:
            doc.title_vn = title_vn
            changed = True
        if title_en is not None:
            doc.title_en = title_en
            changed = True
        if education_stage_id is not None:
            doc.education_stage_id = education_stage_id
            changed = True

        if changed:
            doc.save()
            frappe.db.commit()

        # Include debug info in successful response for troubleshooting
        response_data = {
            "name": doc.name,
            "title_vn": doc.title_vn,
            "title_en": doc.title_en,
            "campus_id": doc.campus_id,
            "education_stage_id": getattr(doc, "education_stage_id", None),
            "_debug_info": debug_info  # Include debug info for troubleshooting
        }

        return single_item_response(
            data=response_data,
            message="Updated successfully",
        )
    except frappe.DoesNotExistError:
        debug_info["error_type"] = "DoesNotExistError"
        debug_info["error_message"] = "Subject Department not found"
        return error_response(message="Subject Department not found", code="NOT_FOUND", debug_info=debug_info)
    except Exception as e:
        frappe.log_error(f"Error update subject_department: {str(e)}")
        debug_info["error_type"] = "Exception"
        debug_info["error_message"] = str(e)
        return error_response(message="Error updating subject department", code="UPDATE_ERROR", debug_info=debug_info)


@frappe.whitelist(allow_guest=False)
def delete():
    try:
        # Accept multiple sources and keys for robustness (align with get_by_id and update)
        id = None
        
        # Try from form_dict first
        if frappe.form_dict:
            id = (
                frappe.form_dict.get("id")
                or frappe.form_dict.get("name")
                or frappe.form_dict.get("subject_department_id")
            )

        # If not found, try from request args
        if not id and hasattr(frappe.request, 'args') and frappe.request.args:
            for key in ["id", "name", "subject_department_id"]:
                if key in frappe.request.args and frappe.request.args[key]:
                    id = frappe.request.args[key]
                    break

        # If not found, try from request data (urlencoded)
        if not id and frappe.request.data:
            try:
                from urllib.parse import parse_qs
                data_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                if data_str.strip():
                    parsed = parse_qs(data_str, keep_blank_values=True)
                    for key in ["id", "name", "subject_department_id"]:
                        if key in parsed and parsed[key]:
                            id = parsed[key][0]
                            break
            except Exception:
                pass

        # If not found, try from request data (JSON)
        if not id and frappe.request.data:
            try:
                import json
                json_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                if json_str.strip():
                    data = json.loads(json_str)
                    for key in ["id", "name", "subject_department_id"]:
                        if key in data and data[key]:
                            id = data[key]
                            break
            except Exception:
                pass

        if not id:
            return validation_error_response(message="ID is required", errors={"id": ["Required"]})

        frappe.delete_doc("SIS Subject Department", id)
        frappe.db.commit()
        return success_response(message="Deleted successfully")
    except frappe.DoesNotExistError:
        return not_found_response(message="Subject Department not found", code="NOT_FOUND")
    except Exception as e:
        frappe.log_error(f"Error delete subject_department: {str(e)}")
        return error_response(message="Error deleting subject department", code="DELETE_ERROR")


