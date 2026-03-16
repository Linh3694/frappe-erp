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


def _recalculate_admission_profile_completion(doc):
    """
    Tu dong tinh ngay hoan thien ho so nhap hoc khi tat ca ProfileTypes
    (theo target_grade) da co it nhat 1 tai lieu co attachment.
    """
    target_grade = doc.get("target_grade")
    if not target_grade or not str(target_grade).replace(" ", "").isdigit():
        return
    try:
        import json
        n = int(str(target_grade).strip())
        if n < 1 or n > 12:
            return
        khoi = f"Khối {n}"
        profile_types = frappe.get_all(
            "CRM Admission Profile Type",
            fields=["name", "profile_type", "applicable_grades"],
        )
        required = []
        for pt in profile_types:
            grades = []
            if pt.get("applicable_grades"):
                try:
                    grades = json.loads(pt["applicable_grades"])
                except Exception:
                    pass
            if isinstance(grades, list) and khoi in grades:
                required.append(pt.get("profile_type") or pt.get("name"))
        if not required:
            return
        # Chi tinh hoan thien khi user da check (is_submitted=1) cho tat ca profile types
        docs_checked = set()
        for d in doc.get("enrollment_documents") or []:
            name = (d.get("document_name") or "").strip()
            if name and (d.get("attachment") or "").strip() and d.get("is_submitted") == 1:
                docs_checked.add(name)
        all_done = all(n in docs_checked for n in required)
        if all_done:
            from datetime import date
            doc.admission_profile_completion_date = date.today().isoformat()
    except Exception:
        pass


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
    # per_page=0: lấy tất cả (unlimited) - dùng cho dialog thêm học sinh event/course
    if per_page <= 0:
        per_page = 0
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
    
    offset = 0 if per_page == 0 else (page - 1) * per_page
    page_length = 0 if per_page == 0 else per_page  # 0 = unlimited trong Frappe get_all

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
        page_length=page_length
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
    
    # per_page=0: tra ve all, truyen total de paginated_response tinh total_pages=1
    resp_per_page = total if per_page == 0 else per_page
    return paginated_response(leads, 1 if per_page == 0 else page, total, resp_per_page)


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
            "student_name", "student_gender", "student_dob", "student_code",
            "current_grade", "target_grade", "current_school", "student_note",
            "tuition_fee_pct", "service_fee_pct", "dev_fee_pct", "ksdv_pct",
            "guardian_name", "relationship", "guardian_email", "guardian_id_number",
            "guardian_occupation", "guardian_position", "guardian_workplace",
            "guardian_address", "guardian_nationality", "guardian_note", "guardian_dob",
            "target_academic_year", "target_semester", "referrer",
            "reject_reason", "reject_detail", "enrollment_date",
            "admission_profile_deadline", "admission_profile_completion_date"
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
        
        # Tu dong tinh ngay hoan thien ho so khi tat ca tai lieu da co file
        _recalculate_admission_profile_completion(doc)
        
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


# === Lead Family / Guardian APIs ===

def _get_guardian_phones(guardian_doc):
    """Lay danh sach so dien thoai tu CRM Guardian. Ưu tiên phone_numbers, fallback phone_number."""
    g = guardian_doc
    phones = []
    # Ưu tiên child table phone_numbers
    phone_rows = getattr(g, "phone_numbers", None) or []
    if phone_rows:
        for row in phone_rows:
            pn = row.get("phone_number") or ""
            if pn:
                phones.append({
                    "phone_number": pn,
                    "is_primary": 1 if row.get("is_primary") else 0,
                    "name": row.get("name"),
                })
    # Fallback: phone_number cu (1 so, mac dinh la chinh)
    if not phones and getattr(g, "phone_number", None):
        phones.append({"phone_number": g.phone_number, "is_primary": 1})
    return phones


def _guardian_to_member_dict(guardian_doc, relationship_type=None, is_primary_contact=False):
    """Chuyen CRM Guardian doc thanh dict cho LeadFamilyMember."""
    g = guardian_doc
    phones = _get_guardian_phones(g)
    return {
        "guardian": {
            "name": g.name,
            "guardian_id": getattr(g, "guardian_id", None),
            "guardian_name": getattr(g, "guardian_name", None),
            "phone_number": getattr(g, "phone_number", None),
            "email": getattr(g, "email", None),
            "id_number": getattr(g, "id_number", None),
            "occupation": getattr(g, "occupation", None),
            "position": getattr(g, "position", None),
            "workplace": getattr(g, "workplace", None),
            "address": getattr(g, "address", None),
            "nationality": getattr(g, "nationality", None),
            "note": getattr(g, "note", None),
            "dob": str(g.dob) if getattr(g, "dob", None) else None,
        },
        "relationship_type": relationship_type or "",
        "is_primary_contact": bool(is_primary_contact),
        "phones": phones,
    }


@frappe.whitelist()
def get_lead_family():
    """Lay thong tin gia dinh cua lead: members (guardian + relationship + phones), family_code."""
    check_crm_permission()
    # GET: params trong query string (request.args). POST: trong body (get_request_data).
    data = get_request_data() or {}
    if hasattr(frappe.request, "args") and frappe.request.args:
        data = dict(frappe.request.args)
    name = data.get("name") or data.get("lead_name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    members = []
    family_code = None

    # Che do B: co linked_family
    if getattr(doc, "linked_family", None):
        fam = frappe.db.get_value("CRM Family", doc.linked_family, "family_code", as_dict=True)
        if fam:
            family_code = fam.get("family_code")
        rels = frappe.get_all(
            "CRM Family Relationship",
            filters={"parent": doc.linked_family},
            fields=["student", "guardian", "relationship_type", "key_person", "access"],
        )
        guardian_ids = list({r["guardian"] for r in rels if r.get("guardian")})
        guardians_by_id = {}
        for gid in guardian_ids:
            g_doc = frappe.get_doc("CRM Guardian", gid)
            guardians_by_id[gid] = g_doc
        for r in rels:
            if not r.get("guardian"):
                continue
            g_doc = guardians_by_id.get(r["guardian"])
            if g_doc:
                phones = _get_guardian_phones(g_doc)
                members.append({
                    "guardian": {
                        "name": g_doc.name,
                        "guardian_id": getattr(g_doc, "guardian_id", None),
                        "guardian_name": getattr(g_doc, "guardian_name", None),
                        "phone_number": getattr(g_doc, "phone_number", None),
                        "email": getattr(g_doc, "email", None),
                        "id_number": getattr(g_doc, "id_number", None),
                        "occupation": getattr(g_doc, "occupation", None),
                        "position": getattr(g_doc, "position", None),
                        "workplace": getattr(g_doc, "workplace", None),
                        "address": getattr(g_doc, "address", None),
                        "nationality": getattr(g_doc, "nationality", None),
                        "note": getattr(g_doc, "note", None),
                        "dob": str(g_doc.dob) if getattr(g_doc, "dob", None) else None,
                    },
                    "relationship_type": r.get("relationship_type", ""),
                    "is_primary_contact": bool(r.get("key_person")),
                    "phones": phones,
                })

    # Che do A: lead_guardians child table (chua co linked_family)
    elif getattr(doc, "lead_guardians", None) and len(doc.lead_guardians) > 0:
        for lg in doc.lead_guardians:
            if not lg.get("guardian"):
                continue
            if not frappe.db.exists("CRM Guardian", lg.guardian):
                continue
            g_doc = frappe.get_doc("CRM Guardian", lg.guardian)
            members.append(_guardian_to_member_dict(
                g_doc,
                relationship_type=lg.get("relationship_type"),
                is_primary_contact=lg.get("is_primary_contact"),
            ))

    # Fallback: flat fields
    else:
        has_guardian = (
            doc.guardian_name or doc.guardian_email or doc.guardian_id_number
            or doc.relationship or doc.guardian_occupation
        )
        if has_guardian or (doc.phone_numbers and len(doc.phone_numbers) > 0):
            phones = []
            for p in (doc.phone_numbers or []):
                phones.append({
                    "phone_number": p.get("phone_number", ""),
                    "is_primary": p.get("is_primary", 0),
                })
            members.append({
                "guardian": {
                    "name": None,
                    "guardian_id": None,
                    "guardian_name": doc.guardian_name,
                    "phone_number": (doc.phone_numbers[0].get("phone_number") if doc.phone_numbers else None),
                    "email": doc.guardian_email,
                    "id_number": doc.guardian_id_number,
                    "occupation": doc.guardian_occupation,
                    "position": doc.guardian_position,
                    "workplace": doc.guardian_workplace,
                    "address": doc.guardian_address,
                    "nationality": doc.guardian_nationality,
                    "note": doc.guardian_note,
                    "dob": str(doc.guardian_dob) if getattr(doc, "guardian_dob", None) else None,
                },
                "relationship_type": doc.relationship or "",
                "is_primary_contact": True,
                "phones": phones,
            })

    return single_item_response({
        "members": members,
        "family_code": family_code,
        "linked_family": getattr(doc, "linked_family", None),
    })


@frappe.whitelist(methods=["POST"])
def add_lead_guardian():
    """Them phu huynh vao lead. mode='new' tao CRM Guardian moi, mode='existing' chon CRM Guardian co san."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    mode = data.get("mode", "new")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    guardian_name_doc = None

    if mode == "new":
        guardian_data = data.get("guardian_data") or data
        g_name = guardian_data.get("guardian_name") or guardian_data.get("guardianName") or guardian_data.get("name")
        phone = guardian_data.get("phone_number") or guardian_data.get("phoneNumber") or ""
        email = guardian_data.get("email") or ""
        if not g_name:
            return validation_error_response("guardian_name bat buoc", {"guardian_name": ["Required"]})
        # Tao CRM Guardian moi
        from erp.api.erp_sis.guardian import validate_vietnamese_phone_number
        formatted_phone = ""
        if phone:
            try:
                formatted_phone = validate_vietnamese_phone_number(phone)
            except ValueError as ve:
                return validation_error_response(str(ve), {"phone_number": [str(ve)]})
        if formatted_phone and frappe.db.exists("CRM Guardian", {"phone_number": formatted_phone}):
            return validation_error_response(
                f"So dien thoai '{formatted_phone}' da duoc su dung boi phu huynh khac",
                {"phone_number": ["Duplicate"]}
            )
        import re
        import time
        base_id = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', (g_name or "").lower())
        base_id = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', base_id)
        base_id = re.sub(r'[ìíịỉĩ]', 'i', base_id)
        base_id = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', base_id)
        base_id = re.sub(r'[ùúụủũưừứựửữ]', 'u', base_id)
        base_id = re.sub(r'[ỳýỵỷỹ]', 'y', base_id)
        base_id = base_id.replace('đ', 'd')
        base_id = re.sub(r'[^a-z0-9]', '-', base_id)
        base_id = re.sub(r'-+', '-', base_id).strip('-') or "guardian"
        base_id = base_id[:40]
        guardian_id = f"{base_id}-{int(time.time() * 1000) % 1000000}"
        while frappe.db.exists("CRM Guardian", {"guardian_id": guardian_id}):
            guardian_id = f"{base_id}-{int(time.time() * 1000) % 1000000}"
        guardian_doc = frappe.get_doc({
            "doctype": "CRM Guardian",
            "guardian_id": guardian_id,
            "guardian_name": g_name,
            "phone_number": formatted_phone,
            "email": email or "",
            "id_number": guardian_data.get("id_number", ""),
            "occupation": guardian_data.get("occupation", ""),
            "position": guardian_data.get("position", ""),
            "workplace": guardian_data.get("workplace", ""),
            "address": guardian_data.get("address", ""),
            "nationality": guardian_data.get("nationality", ""),
            "note": guardian_data.get("note", ""),
            "dob": guardian_data.get("dob"),
        })
        guardian_doc.flags.ignore_validate = True
        guardian_doc.insert(ignore_permissions=True)
        guardian_name_doc = guardian_doc.name
        relationship_type = guardian_data.get("relationship_type", "")
    else:
        # mode = existing
        existing = data.get("existing_guardian") or data.get("guardian")
        if not existing:
            return validation_error_response("existing_guardian bat buoc khi mode=existing", {"existing_guardian": ["Required"]})
        if not frappe.db.exists("CRM Guardian", existing):
            return not_found_response(f"Khong tim thay CRM Guardian {existing}")
        guardian_name_doc = existing
        relationship_type = data.get("relationship_type", "")

    if not guardian_name_doc:
        return error_response("Khong tao/chon duoc guardian")

    # Kiem tra da ton tai trong lead_guardians chua
    lead_guardians = getattr(doc, "lead_guardians", None) or []
    for lg in lead_guardians:
        if lg.get("guardian") == guardian_name_doc:
            return validation_error_response("Phu huynh nay da duoc them vao ho so", {"guardian": ["Duplicate"]})

    # Them vao lead_guardians
    is_first = len(lead_guardians) == 0
    doc.append("lead_guardians", {
        "guardian": guardian_name_doc,
        "relationship_type": relationship_type,
        "is_primary_contact": 1 if is_first else 0,
    })
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)

    # Sync flat fields neu la primary
    if is_first:
        g_doc = frappe.get_doc("CRM Guardian", guardian_name_doc)
        doc.guardian_name = g_doc.guardian_name
        doc.guardian_email = g_doc.email or ""
        doc.guardian_id_number = getattr(g_doc, "id_number", None) or ""
        doc.relationship = relationship_type or ""
        doc.guardian_occupation = getattr(g_doc, "occupation", None) or ""
        doc.guardian_position = getattr(g_doc, "position", None) or ""
        doc.guardian_workplace = getattr(g_doc, "workplace", None) or ""
        doc.guardian_address = getattr(g_doc, "address", None) or ""
        doc.guardian_nationality = getattr(g_doc, "nationality", None) or ""
        doc.guardian_note = getattr(g_doc, "note", None) or ""
        doc.guardian_dob = getattr(g_doc, "dob", None)
        if g_doc.phone_number:
            # Cap nhat phone_numbers neu chua co
            if not doc.phone_numbers or len(doc.phone_numbers) == 0:
                doc.append("phone_numbers", {"phone_number": g_doc.phone_number, "is_primary": 1})
        doc.save(ignore_permissions=True)

    # Neu co linked_family + linked_student -> them CRM Family Relationship
    if getattr(doc, "linked_family", None) and doc.linked_student:
        family_doc = frappe.get_doc("CRM Family", doc.linked_family)
        family_doc.append("relationships", {
            "student": doc.linked_student,
            "guardian": guardian_name_doc,
            "relationship_type": relationship_type or "other",
            "key_person": 1 if is_first else 0,
            "access": 1,
        })
        family_doc.flags.ignore_validate = True
        family_doc.save(ignore_permissions=True)
        # Cap nhat CRM Guardian family_code
        frappe.db.set_value("CRM Guardian", guardian_name_doc, "family_code", family_doc.family_code)
        # Cap nhat CRM Student family_relationships
        student_doc = frappe.get_doc("CRM Student", doc.linked_student)
        student_doc.append("family_relationships", {
            "student": doc.linked_student,
            "guardian": guardian_name_doc,
            "relationship_type": relationship_type or "other",
            "key_person": 1 if is_first else 0,
            "access": 1,
        })
        student_doc.flags.ignore_validate = True
        student_doc.save(ignore_permissions=True)
        # Cap nhat CRM Guardian student_relationships
        guardian_doc = frappe.get_doc("CRM Guardian", guardian_name_doc)
        guardian_doc.append("student_relationships", {
            "student": doc.linked_student,
            "guardian": guardian_name_doc,
            "relationship_type": relationship_type or "other",
            "key_person": 1 if is_first else 0,
            "access": 1,
        })
        guardian_doc.flags.ignore_validate = True
        guardian_doc.save(ignore_permissions=True)

    frappe.db.commit()
    return single_item_response({"guardian": guardian_name_doc}, "Them phu huynh thanh cong")


@frappe.whitelist(methods=["POST"])
def update_lead_guardian():
    """Cap nhat thong tin CRM Guardian. Neu la primary contact thi sync flat fields ve CRM Lead."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    guardian_name = data.get("guardian_name") or data.get("guardian")
    updates = data.get("updates") or data
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not guardian_name:
        return validation_error_response("Thieu tham so guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}")

    # Cap nhat CRM Guardian truc tiep
    guardian_fields = (
        "guardian_name", "phone_number", "email", "id_number", "occupation",
        "position", "workplace", "address", "nationality", "note", "dob"
    )
    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    for k in guardian_fields:
        if k in updates:
            g_doc.set(k, updates[k])
    # Cap nhat phone_numbers neu co (danh sach {phone_number, is_primary})
    if "phone_numbers" in updates:
        phone_list = updates.get("phone_numbers") or []
        if isinstance(phone_list, list):
            from erp.api.erp_sis.guardian import validate_vietnamese_phone_number
            g_doc.set("phone_numbers", [])
            has_primary = False
            for p in phone_list:
                pn = (p.get("phone_number") or p.get("phone") or "").strip()
                if not pn:
                    continue
                try:
                    pn = validate_vietnamese_phone_number(pn)
                except ValueError:
                    continue
                is_prim = 1 if p.get("is_primary") else 0
                if is_prim:
                    has_primary = True
                g_doc.append("phone_numbers", {"phone_number": pn, "is_primary": is_prim})
            # Dam bao co dung 1 so chinh
            if g_doc.phone_numbers:
                if not has_primary:
                    g_doc.phone_numbers[0].is_primary = 1
                elif sum(1 for r in g_doc.phone_numbers if r.get("is_primary")) > 1:
                    for i, r in enumerate(g_doc.phone_numbers):
                        r.is_primary = 1 if i == 0 else 0
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)

    # Cap nhat relationship_type trong lead_guardians neu co
    doc = frappe.get_doc("CRM Lead", name)
    relationship_type = updates.get("relationship_type")
    if relationship_type is not None:
        lead_guardians = getattr(doc, "lead_guardians", None) or []
        for lg in lead_guardians:
            if lg.get("guardian") == guardian_name:
                lg.relationship_type = relationship_type
                break
        doc.flags.ignore_validate = True
        doc.save(ignore_permissions=True)
        doc = frappe.get_doc("CRM Lead", name)

    # Cap nhat relationship_type trong CRM Family Relationship neu co linked_family
    if relationship_type is not None and getattr(doc, "linked_family", None):
        rels = frappe.get_all(
            "CRM Family Relationship",
            filters={"parent": doc.linked_family, "guardian": guardian_name},
            fields=["name"],
        )
        for r in rels:
            rel_doc = frappe.get_doc("CRM Family Relationship", r["name"])
            rel_doc.relationship_type = relationship_type
            rel_doc.flags.ignore_validate = True
            rel_doc.save(ignore_permissions=True)

    # Sync flat fields neu guardian nay la primary contact
    is_primary = False
    lead_guardians = getattr(doc, "lead_guardians", None) or []
    for lg in lead_guardians:
        if lg.get("guardian") == guardian_name and lg.get("is_primary_contact"):
            is_primary = True
            break
    if not is_primary and getattr(doc, "linked_family", None):
        rels = frappe.get_all("CRM Family Relationship", filters={"parent": doc.linked_family, "guardian": guardian_name}, fields=["key_person"])
        if rels and rels[0].get("key_person"):
            is_primary = True

    if is_primary:
        g_doc = frappe.get_doc("CRM Guardian", guardian_name)
        doc.guardian_name = g_doc.guardian_name
        doc.guardian_email = g_doc.email or ""
        doc.guardian_id_number = getattr(g_doc, "id_number", None) or ""
        doc.guardian_occupation = getattr(g_doc, "occupation", None) or ""
        doc.guardian_position = getattr(g_doc, "position", None) or ""
        doc.guardian_workplace = getattr(g_doc, "workplace", None) or ""
        doc.guardian_address = getattr(g_doc, "address", None) or ""
        doc.guardian_nationality = getattr(g_doc, "nationality", None) or ""
        doc.guardian_note = getattr(g_doc, "note", None) or ""
        doc.guardian_dob = getattr(g_doc, "dob", None)
        doc.save(ignore_permissions=True)

    frappe.db.commit()
    return single_item_response({"guardian": guardian_name}, "Cap nhat phu huynh thanh cong")


@frappe.whitelist(methods=["POST"])
def remove_lead_guardian():
    """Xoa phu huynh khoi lead."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    guardian_name = data.get("guardian_name") or data.get("guardian")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not guardian_name:
        return validation_error_response("Thieu tham so guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    was_primary = False
    new_lead_guardians = []
    for lg in (getattr(doc, "lead_guardians", None) or []):
        if lg.get("guardian") == guardian_name:
            was_primary = lg.get("is_primary_contact")
            continue
        new_lead_guardians.append(lg)

    doc.set("lead_guardians", new_lead_guardians)
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)

    # Neu co linked_family -> xoa CRM Family Relationship
    if getattr(doc, "linked_family", None):
        frappe.db.sql(
            "DELETE FROM `tabCRM Family Relationship` WHERE parent=%s AND guardian=%s",
            (doc.linked_family, guardian_name)
        )
        # Kiem tra guardian con o family nao khac khong
        other_fam = frappe.db.sql(
            "SELECT 1 FROM `tabCRM Family Relationship` WHERE guardian=%s LIMIT 1",
            (guardian_name,)
        )
        if not other_fam:
            frappe.db.set_value("CRM Guardian", guardian_name, "family_code", None)
        # Cap nhat student_relationships tren CRM Student
        if doc.linked_student:
            student_doc = frappe.get_doc("CRM Student", doc.linked_student)
            student_doc.set("family_relationships", [r for r in (student_doc.family_relationships or []) if r.guardian != guardian_name])
            student_doc.flags.ignore_validate = True
            student_doc.save(ignore_permissions=True)
        # Cap nhat guardian student_relationships
        guardian_doc = frappe.get_doc("CRM Guardian", guardian_name)
        guardian_doc.set("student_relationships", [])
        guardian_doc.flags.ignore_validate = True
        guardian_doc.save(ignore_permissions=True)

    # Sync flat fields neu da xoa primary -> lay tu guardian tiep theo
    if was_primary and new_lead_guardians:
        next_primary = new_lead_guardians[0]
        g_doc = frappe.get_doc("CRM Guardian", next_primary.get("guardian"))
        doc.guardian_name = g_doc.guardian_name
        doc.guardian_email = g_doc.email or ""
        doc.guardian_id_number = getattr(g_doc, "id_number", None) or ""
        doc.relationship = next_primary.get("relationship_type", "")
        doc.guardian_occupation = getattr(g_doc, "occupation", None) or ""
        doc.guardian_position = getattr(g_doc, "position", None) or ""
        doc.guardian_workplace = getattr(g_doc, "workplace", None) or ""
        doc.guardian_address = getattr(g_doc, "address", None) or ""
        doc.guardian_nationality = getattr(g_doc, "nationality", None) or ""
        doc.guardian_note = getattr(g_doc, "note", None) or ""
        doc.guardian_dob = getattr(g_doc, "dob", None)
        doc.save(ignore_permissions=True)
    elif was_primary and not new_lead_guardians:
        # Xoa het flat fields
        doc.guardian_name = ""
        doc.guardian_email = ""
        doc.guardian_id_number = ""
        doc.relationship = ""
        doc.guardian_occupation = ""
        doc.guardian_position = ""
        doc.guardian_workplace = ""
        doc.guardian_address = ""
        doc.guardian_nationality = ""
        doc.guardian_note = ""
        doc.guardian_dob = None
        doc.save(ignore_permissions=True)

    frappe.db.commit()
    return success_response(message="Da xoa phu huynh khoi ho so")


# === Lead Siblings (Anh/Chị/Em) APIs ===

@frappe.whitelist(methods=["POST"])
def add_lead_sibling():
    """Them anh/chi/em vao lead. mode='new' nhap thong tin moi, mode='existing' chon CRM Student co san."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    mode = data.get("mode", "new")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    lead_siblings = getattr(doc, "lead_siblings", None) or []

    if mode == "existing":
        # Lay tu CRM Student - school mac dinh Wellspring Ha Noi
        student_id = data.get("student_id") or data.get("existing_student")
        if not student_id:
            return validation_error_response("student_id bat buoc khi mode=existing", {"student_id": ["Required"]})
        if not frappe.db.exists("CRM Student", student_id):
            return not_found_response(f"Khong tim thay CRM Student {student_id}")
        student = frappe.get_doc("CRM Student", student_id)
        # Lấy từ hệ thống: trường mặc định Wellspring Hà Nội (text)
        doc.append("lead_siblings", {
            "sibling_name": student.student_name,
            "student_code": student.student_code or "",
            "relationship_type": data.get("relationship_type", ""),
            "dob": str(student.dob) if student.dob else None,
            "school": "Wellspring Hà Nội",
        })
    else:
        # Thêm mới - 5 field, sibling_name required
        sibling_data = data.get("sibling_data") or data
        s_name = sibling_data.get("sibling_name") or sibling_data.get("student_name")
        if not s_name:
            return validation_error_response("sibling_name (Họ tên) bat buoc", {"sibling_name": ["Required"]})
        doc.append("lead_siblings", {
            "sibling_name": s_name,
            "student_code": sibling_data.get("student_code", ""),
            "relationship_type": sibling_data.get("relationship_type", ""),
            "dob": sibling_data.get("dob"),
            "school": sibling_data.get("school", ""),
        })

    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return single_item_response({"siblings": [r.as_dict() for r in doc.lead_siblings]}, "Da them anh/chi/em")


@frappe.whitelist(methods=["POST"])
def update_lead_sibling():
    """Cap nhat thong tin anh/chi/em."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    row_name = data.get("row_name") or data.get("sibling_row_name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not row_name:
        return validation_error_response("Thieu row_name", {"row_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    for row in (getattr(doc, "lead_siblings", None) or []):
        if row.get("name") == row_name:
            updates = data.get("updates") or data
            if "sibling_name" in updates:
                row.sibling_name = updates["sibling_name"]
            if "student_code" in updates:
                row.student_code = updates.get("student_code", "")
            if "relationship_type" in updates:
                row.relationship_type = updates.get("relationship_type", "")
            if "dob" in updates:
                row.dob = updates.get("dob")
            if "school" in updates:
                row.school = updates.get("school", "")
            doc.flags.ignore_validate = True
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            return single_item_response(row.as_dict(), "Da cap nhat")
    return not_found_response(f"Khong tim thay dong anh/chi/em {row_name}")


@frappe.whitelist(methods=["POST"])
def remove_lead_sibling():
    """Xoa anh/chi/em khoi lead."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    row_name = data.get("row_name") or data.get("sibling_row_name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not row_name:
        return validation_error_response("Thieu row_name", {"row_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = frappe.get_doc("CRM Lead", name)
    new_siblings = [r for r in (getattr(doc, "lead_siblings", None) or []) if r.get("name") != row_name]
    doc.set("lead_siblings", new_siblings)
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return success_response(message="Da xoa anh/chi/em khoi ho so")


@frappe.whitelist(methods=["POST"])
def set_primary_contact():
    """Dat guardian lam nguoi lien lac chinh."""
    check_crm_permission()
    data = get_request_data()
    name = data.get("name") or data.get("lead_name")
    guardian_name = data.get("guardian_name") or data.get("guardian")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    if not guardian_name:
        return validation_error_response("Thieu tham so guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}")

    doc = frappe.get_doc("CRM Lead", name)

    # Cap nhat lead_guardians
    for lg in (getattr(doc, "lead_guardians", None) or []):
        lg.is_primary_contact = 1 if lg.get("guardian") == guardian_name else 0
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)

    # Neu co linked_family -> cap nhat key_person trong CRM Family Relationship
    if getattr(doc, "linked_family", None):
        frappe.db.sql(
            "UPDATE `tabCRM Family Relationship` SET key_person=0 WHERE parent=%s",
            (doc.linked_family,)
        )
        frappe.db.sql(
            "UPDATE `tabCRM Family Relationship` SET key_person=1 WHERE parent=%s AND guardian=%s",
            (doc.linked_family, guardian_name)
        )
        # Cap nhat student_relationships va guardian student_relationships
        for rel in frappe.get_all("CRM Family Relationship", filters={"parent": doc.linked_family}, fields=["name", "student", "guardian", "relationship_type", "key_person", "access"]):
            if rel["guardian"] == guardian_name:
                rel["key_person"] = 1
            else:
                rel["key_person"] = 0
        # Reload va save student + guardian
        if doc.linked_student:
            student_doc = frappe.get_doc("CRM Student", doc.linked_student)
            student_doc.set("family_relationships", [])
            for rel in frappe.get_all("CRM Family Relationship", filters={"parent": doc.linked_family, "student": doc.linked_student}, fields=["student", "guardian", "relationship_type", "key_person", "access"]):
                student_doc.append("family_relationships", rel)
            student_doc.flags.ignore_validate = True
            student_doc.save(ignore_permissions=True)
        for gid in {r["guardian"] for r in frappe.get_all("CRM Family Relationship", filters={"parent": doc.linked_family}, fields=["guardian"]) if r.get("guardian")}:
            guardian_doc = frappe.get_doc("CRM Guardian", gid)
            guardian_doc.set("student_relationships", [])
            for rel in frappe.get_all("CRM Family Relationship", filters={"parent": doc.linked_family, "guardian": gid}, fields=["student", "guardian", "relationship_type", "key_person", "access"]):
                guardian_doc.append("student_relationships", rel)
            guardian_doc.flags.ignore_validate = True
            guardian_doc.save(ignore_permissions=True)

    # Sync flat fields
    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    doc.guardian_name = g_doc.guardian_name
    doc.guardian_email = g_doc.email or ""
    doc.guardian_id_number = getattr(g_doc, "id_number", None) or ""
    doc.relationship = ""
    for lg in (getattr(doc, "lead_guardians", None) or []):
        if lg.get("guardian") == guardian_name:
            doc.relationship = lg.get("relationship_type", "")
            break
    if getattr(doc, "linked_family", None):
        rel = frappe.db.get_value("CRM Family Relationship", {"parent": doc.linked_family, "guardian": guardian_name}, "relationship_type")
        if rel:
            doc.relationship = rel
    doc.guardian_occupation = getattr(g_doc, "occupation", None) or ""
    doc.guardian_position = getattr(g_doc, "position", None) or ""
    doc.guardian_workplace = getattr(g_doc, "workplace", None) or ""
    doc.guardian_address = getattr(g_doc, "address", None) or ""
    doc.guardian_nationality = getattr(g_doc, "nationality", None) or ""
    doc.guardian_note = getattr(g_doc, "note", None) or ""
    doc.guardian_dob = getattr(g_doc, "dob", None)
    doc.save(ignore_permissions=True)

    frappe.db.commit()
    return single_item_response({"guardian": guardian_name}, "Da dat nguoi lien lac chinh")


# === Guardian Phone APIs (nhiều số/guardian, 1 số chính) ===

@frappe.whitelist(methods=["POST"])
def add_guardian_phone():
    """Them so dien thoai cho Guardian. Neu la so dau tien thi tu dong la so chinh."""
    check_crm_permission()
    data = get_request_data()
    guardian_name = data.get("guardian_name") or data.get("guardian")
    phone_number = data.get("phone_number") or data.get("phone") or ""
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}")
    if not phone_number or not str(phone_number).strip():
        return validation_error_response("Thieu so dien thoai", {"phone_number": ["Bat buoc"]})

    from erp.api.erp_sis.guardian import validate_vietnamese_phone_number
    try:
        formatted = validate_vietnamese_phone_number(phone_number)
    except ValueError as ve:
        return validation_error_response(str(ve), {"phone_number": [str(ve)]})

    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    existing = getattr(g_doc, "phone_numbers", None) or []
    # Migration: neu co phone_number cu nhung chua co phone_numbers -> them vao truoc
    if not existing and getattr(g_doc, "phone_number", None):
        g_doc.append("phone_numbers", {"phone_number": g_doc.phone_number, "is_primary": 1})
        g_doc.flags.ignore_validate = True
        g_doc.save(ignore_permissions=True)
        g_doc.reload()
        existing = getattr(g_doc, "phone_numbers", None) or []
    # Kiem tra trung trong phone_numbers cua guardian nay
    for row in existing:
        if (row.get("phone_number") or "").replace(" ", "") == (formatted or "").replace(" ", ""):
            return validation_error_response(f"So '{formatted}' da ton tai", {"phone_number": ["Trung"]})
    # Kiem tra trung voi guardian khac (phone_number cu hoac phone_numbers)
    if frappe.db.exists("CRM Guardian", {"phone_number": formatted, "name": ["!=", guardian_name]}):
        return validation_error_response(f"So '{formatted}' da duoc su dung boi phu huynh khac", {"phone_number": ["Trung"]})
    dup = frappe.db.sql(
        "SELECT 1 FROM `tabCRM Guardian Phone` WHERE phone_number=%s AND parent!=%s LIMIT 1",
        (formatted, guardian_name),
    )
    if dup:
        return validation_error_response(f"So '{formatted}' da duoc su dung boi phu huynh khac", {"phone_number": ["Trung"]})

    is_first = len(existing) == 0
    g_doc.append("phone_numbers", {"phone_number": formatted, "is_primary": 1 if is_first else 0})
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Tra ve row moi (co name)
    new_rows = getattr(g_doc, "phone_numbers", None) or []
    added = next((r for r in new_rows if r.get("phone_number") == formatted), None)
    return single_item_response({
        "guardian": guardian_name,
        "phone": {"phone_number": formatted, "is_primary": 1 if is_first else 0, "name": added.get("name") if added else None},
    }, "Da them so dien thoai")


@frappe.whitelist(methods=["POST"])
def remove_guardian_phone():
    """Xoa so dien thoai khoi Guardian. Neu xoa so chinh va con so khac -> dat so dau tien lam chinh."""
    check_crm_permission()
    data = get_request_data()
    guardian_name = data.get("guardian_name") or data.get("guardian")
    phone_row_name = data.get("phone_row_name") or data.get("phone_name") or data.get("name")
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}")
    if not phone_row_name:
        return validation_error_response("Thieu phone_row_name (name cua dong so)", {"phone_row_name": ["Bat buoc"]})

    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    rows = list(getattr(g_doc, "phone_numbers", None) or [])
    to_remove_idx = next((i for i, r in enumerate(rows) if r.get("name") == phone_row_name), None)
    if to_remove_idx is None:
        return not_found_response(f"Khong tim thay so dien thoai {phone_row_name}")

    was_primary = rows[to_remove_idx].get("is_primary")
    g_doc.remove(rows[to_remove_idx])
    # Neu xoa so chinh va con so khac -> dat so dau tien lam chinh
    if was_primary and g_doc.phone_numbers:
        g_doc.phone_numbers[0].is_primary = 1
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)
    frappe.db.commit()
    return success_response(message="Da xoa so dien thoai")


@frappe.whitelist(methods=["POST"])
def set_guardian_primary_phone():
    """Dat so dien thoai lam so chinh. Moi Guardian chi co 1 so chinh."""
    check_crm_permission()
    data = get_request_data()
    guardian_name = data.get("guardian_name") or data.get("guardian")
    phone_row_name = data.get("phone_row_name") or data.get("phone_name") or data.get("name")
    if not guardian_name:
        return validation_error_response("Thieu guardian_name", {"guardian_name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Guardian", guardian_name):
        return not_found_response(f"Khong tim thay CRM Guardian {guardian_name}")
    if not phone_row_name:
        return validation_error_response("Thieu phone_row_name", {"phone_row_name": ["Bat buoc"]})

    g_doc = frappe.get_doc("CRM Guardian", guardian_name)
    rows = getattr(g_doc, "phone_numbers", None) or []
    for r in rows:
        r.is_primary = 1 if r.get("name") == phone_row_name else 0
    g_doc.flags.ignore_validate = True
    g_doc.save(ignore_permissions=True)
    frappe.db.commit()
    return single_item_response({"guardian": guardian_name}, "Da dat so lien lac chinh")
