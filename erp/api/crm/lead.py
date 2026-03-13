"""
CRM Lead API - CRUD Ho So Tuyen Sinh
"""

import frappe
from frappe import _
from erp.utils.api_response import (
    success_response, error_response, paginated_response,
    single_item_response, list_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import (
    check_crm_permission, get_request_data, validate_phone_number,
    normalize_phone_number, get_valid_statuses_for_step
)


def _get_full_image_url(user_image):
    """Chuyen user_image (path) thanh full URL de frontend hien thi avatar."""
    if not user_image:
        return None
    if user_image.startswith("http://") or user_image.startswith("https://"):
        return user_image
    path = user_image if user_image.startswith("/") else "/files/" + user_image
    return frappe.utils.get_url(path)


@frappe.whitelist()
def get_leads():
    """Lay danh sach leads voi filter + pagination"""
    check_crm_permission()
    
    step = frappe.request.args.get("step")
    status = frappe.request.args.get("status")
    search = frappe.request.args.get("search")
    campus_id = frappe.request.args.get("campus_id")
    pic = frappe.request.args.get("pic")
    page = int(frappe.request.args.get("page", 1))
    per_page = int(frappe.request.args.get("per_page", 20))
    sort_by = frappe.request.args.get("sort_by", "modified")
    sort_order = frappe.request.args.get("sort_order", "desc")
    
    filters = {}
    if step:
        filters["step"] = step
    if status:
        filters["status"] = status
    if campus_id:
        filters["campus_id"] = campus_id
    if pic:
        filters["pic"] = pic
    
    or_filters = {}
    if search:
        or_filters = {
            "student_name": ["like", f"%{search}%"],
            "guardian_name": ["like", f"%{search}%"],
            "name": ["like", f"%{search}%"],
            "student_code": ["like", f"%{search}%"],
            "crm_code": ["like", f"%{search}%"],
        }
    
    # Dem tong
    if search:
        total = frappe.db.sql("""
            SELECT COUNT(*) FROM `tabCRM Lead`
            WHERE ({conditions})
            AND (student_name LIKE %(search)s OR guardian_name LIKE %(search)s 
                 OR name LIKE %(search)s OR student_code LIKE %(search)s
                 OR crm_code LIKE %(search)s)
        """.format(conditions=" AND ".join([f"`{k}` = %({k})s" for k in filters]) if filters else "1=1"),
            {**filters, "search": f"%{search}%"}
        )[0][0]
    else:
        total = frappe.db.count("CRM Lead", filters=filters)
    
    offset = (page - 1) * per_page
    
    # Lay danh sach
    leads = frappe.get_all(
        "CRM Lead",
        filters=filters,
        or_filters=or_filters if search else None,
        fields=[
            "name", "step", "status", "crm_code", "student_name", "guardian_name",
            "student_code", "target_grade", "campus_id", "pic",
            "data_source", "modified", "creation", "duplicate_fields", "owner"
        ],
        order_by=f"{sort_by} {sort_order}",
        start=offset,
        page_length=per_page
    )
    
    # Lay phone number chinh cho moi lead
    for lead in leads:
        # Bo sung pic_info (full_name, user_image) de hien thi ten + avatar
        if lead.get("pic"):
            pic_user = frappe.db.get_value(
                "User", lead["pic"], ["full_name", "user_image"], as_dict=True
            )
            if pic_user:
                lead["pic_info"] = {
                    "full_name": pic_user.get("full_name") or lead["pic"],
                    "user_image": _get_full_image_url(pic_user.get("user_image")),
                }
        phone = frappe.db.get_value(
            "CRM Lead Phone",
            {"parent": lead["name"], "is_primary": 1},
            "phone_number"
        )
        if not phone:
            phone = frappe.db.get_value(
                "CRM Lead Phone",
                {"parent": lead["name"]},
                "phone_number",
                order_by="idx asc"
            )
        lead["primary_phone"] = phone or ""
    
    return paginated_response(leads, page, total, per_page)


@frappe.whitelist()
def get_lead():
    """Lay chi tiet 1 lead"""
    check_crm_permission()
    
    name = frappe.request.args.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    doc = frappe.get_doc("CRM Lead", name)
    lead_data = doc.as_dict()
    
    # Bo sung pic_info (full_name, user_image) de hien thi ten + avatar
    if doc.pic:
        pic_user = frappe.db.get_value(
            "User", doc.pic, ["full_name", "user_image"], as_dict=True
        )
        if pic_user:
            lead_data["pic_info"] = {
                "full_name": pic_user.get("full_name") or doc.pic,
                "user_image": _get_full_image_url(pic_user.get("user_image")),
            }
    
    # Lay ghi chu
    notes = frappe.get_all(
        "CRM Lead Note",
        filters={"lead": name},
        fields=["*"],
        order_by="creation desc"
    )
    lead_data["notes"] = notes
    
    return single_item_response(lead_data)


@frappe.whitelist(methods=["POST"])
def create_lead():
    """Tao lead moi"""
    check_crm_permission()
    data = get_request_data()
    
    # Validate SDT bat buoc
    phone_numbers = data.get("phone_numbers", [])
    if not phone_numbers:
        return validation_error_response(
            "So dien thoai la bat buoc",
            {"phone_numbers": ["Phai co it nhat 1 so dien thoai"]}
        )
    
    # Validate dinh dang SDT
    for phone_item in phone_numbers:
        phone = phone_item.get("phone_number", "")
        if not validate_phone_number(phone):
            return validation_error_response(
                f"So dien thoai khong hop le: {phone}",
                {"phone_numbers": [f"SDT '{phone}' khong dung dinh dang"]}
            )
    
    try:
        doc = frappe.new_doc("CRM Lead")
        
        # Set thong tin co ban
        simple_fields = [
            "data_source", "staff_code", "pic", "campus_id",
            "student_name", "student_gender", "student_dob", "student_code",
            "current_grade", "target_grade", "current_school", "student_note",
            "guardian_name", "relationship", "guardian_email", "guardian_id_number",
            "guardian_occupation", "guardian_position", "guardian_workplace",
            "guardian_address", "guardian_nationality", "guardian_note",
            "target_academic_year", "target_semester", "referrer"
        ]
        for field in simple_fields:
            if field in data and data[field]:
                doc.set(field, data[field])
        
        # Tao o buoc Draft, khong co status
        doc.step = "Draft"
        doc.status = ""
        
        # Set phone numbers
        for phone_item in phone_numbers:
            doc.append("phone_numbers", {
                "phone_number": normalize_phone_number(phone_item.get("phone_number", "")),
                "is_primary": phone_item.get("is_primary", 0)
            })
        
        # Set sources
        for source_item in data.get("sources", []):
            doc.append("source", {"source": source_item.get("source", "")})
        
        # Set events
        for event_item in data.get("events", []):
            doc.append("events", {"event_name": event_item.get("event_name", "")})
        
        # Set courses
        for course_item in data.get("courses", []):
            doc.append("courses", {
                "course_name": course_item.get("course_name", ""),
                "status": course_item.get("status", "")
            })
        
        doc.insert(ignore_permissions=True)
        
        # Tu dong kiem tra trung lap va chuyen sang Verify
        from erp.api.crm.duplicate import _find_matching_leads, _evaluate_duplicate_rules
        
        raw_phones = [p.get("phone_number", "") for p in phone_numbers]
        matches = _find_matching_leads(
            raw_phones,
            doc.student_name,
            doc.guardian_name,
            exclude_draft=True
        )
        # Loai bo chinh no
        matches = [m for m in matches if m["name"] != doc.name]
        
        doc.step = "Verify"
        
        if matches:
            matches.sort(key=lambda x: x.get("modified", ""), reverse=True)
            most_recent = matches[0]
            result = _evaluate_duplicate_rules(most_recent)
            
            if result.get("is_duplicate"):
                doc.status = "Trung"
                doc.duplicate_lead = most_recent["name"]
                doc.duplicate_fields = ", ".join(most_recent.get("matched_fields", []))
            else:
                doc.status = "Can kiem tra"
        else:
            doc.status = "Can kiem tra"
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(doc.as_dict(), "Tao ho so thanh cong")
    
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Loi tao CRM Lead: {str(e)}")
        return error_response(f"Loi tao ho so: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_lead():
    """Cap nhat thong tin lead"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    try:
        doc = frappe.get_doc("CRM Lead", name)
        
        updatable_fields = [
            "data_source", "staff_code", "pic", "campus_id",
            "student_name", "student_gender", "student_dob",
            "current_grade", "target_grade", "current_school", "student_note",
            "guardian_name", "relationship", "guardian_email", "guardian_id_number",
            "guardian_occupation", "guardian_position", "guardian_workplace",
            "guardian_address", "guardian_nationality", "guardian_note",
            "target_academic_year", "target_semester", "referrer",
            "reject_reason", "reject_detail", "enrollment_date"
        ]
        for field in updatable_fields:
            if field in data:
                doc.set(field, data[field])
        
        # Cap nhat phone numbers
        if "phone_numbers" in data:
            doc.set("phone_numbers", [])
            for phone_item in data["phone_numbers"]:
                phone = phone_item.get("phone_number", "")
                if phone and not validate_phone_number(phone):
                    return validation_error_response(
                        f"SDT khong hop le: {phone}",
                        {"phone_numbers": [f"SDT '{phone}' khong dung dinh dang"]}
                    )
                doc.append("phone_numbers", {
                    "phone_number": normalize_phone_number(phone),
                    "is_primary": phone_item.get("is_primary", 0)
                })
        
        # Cap nhat sources
        if "sources" in data:
            doc.set("source", [])
            for s in data["sources"]:
                doc.append("source", {"source": s.get("source", "")})
        
        # Cap nhat documents
        if "enrollment_documents" in data:
            doc.set("enrollment_documents", [])
            for d_item in data["enrollment_documents"]:
                doc.append("enrollment_documents", {
                    "document_name": d_item.get("document_name", ""),
                    "is_submitted": d_item.get("is_submitted", 0),
                    "attachment": d_item.get("attachment", "")
                })
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(doc.as_dict(), "Cap nhat ho so thanh cong")
    
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Loi cap nhat CRM Lead: {str(e)}")
        return error_response(f"Loi cap nhat ho so: {str(e)}")


@frappe.whitelist(methods=["POST"])
def delete_lead():
    """Xoa lead (chi cho phep o Draft)"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    step = frappe.db.get_value("CRM Lead", name, "step")
    if step != "Draft":
        return error_response(f"Chi co the xoa ho so o buoc Draft. Ho so hien tai o buoc {step}")
    
    try:
        frappe.delete_doc("CRM Lead", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message=f"Da xoa ho so {name}")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi xoa ho so: {str(e)}")


@frappe.whitelist()
def get_lead_summary():
    """Thong ke so luong lead theo status trong 1 step"""
    check_crm_permission()
    
    step = frappe.request.args.get("step")
    campus_id = frappe.request.args.get("campus_id")
    
    if not step:
        return validation_error_response("Thieu tham so step", {"step": ["Bat buoc"]})
    
    filters = {"step": step}
    if campus_id:
        filters["campus_id"] = campus_id
    
    # Dem so luong theo tung status
    summary = frappe.db.sql("""
        SELECT status, COUNT(*) as count
        FROM `tabCRM Lead`
        WHERE step = %(step)s
        {campus_filter}
        GROUP BY status
        ORDER BY count DESC
    """.format(
        campus_filter="AND campus_id = %(campus_id)s" if campus_id else ""
    ), filters, as_dict=True)
    
    total = sum(item["count"] for item in summary)
    
    return success_response({
        "step": step,
        "total": total,
        "by_status": summary
    })
