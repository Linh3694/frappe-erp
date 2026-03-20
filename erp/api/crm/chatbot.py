"""
CRM Chatbot API - Endpoint cho AI chatbot tao lead va dat lich hen

API nay duoc goi tu ai-agent-backend, xac thuc bang X-Chatbot-API-Key.
Cau hinh chatbot_api_key trong site_config.json
"""
import frappe
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    validation_error_response, forbidden_response
)
from erp.api.crm.utils import (
    validate_phone_number, normalize_phone_number, generate_crm_code
)
from erp.api.crm.duplicate import _find_matching_leads


def _verify_chatbot_api_key() -> bool:
    """Kiem tra header X-Chatbot-API-Key khop voi site config"""
    api_key = frappe.request.headers.get("X-Chatbot-API-Key") or frappe.request.headers.get(
        "x-chatbot-api-key"
    )
    expected_key = frappe.conf.get("chatbot_api_key") or ""
    if not expected_key:
        return False
    return api_key == expected_key


def _get_request_data() -> dict:
    """Lay data tu request (JSON hoac form_dict)"""
    if frappe.request and getattr(frappe.request, "is_json", False):
        return frappe.request.json or {}
    return dict(frappe.form_dict or {})


@frappe.whitelist(allow_guest=True, methods=["POST"])
def create_lead_from_chatbot():
    """
    Tao lead tu AI chatbot va chuyen sang Step Lead.

    Input (bat buoc):
    - phone_number: str - So dien thoai (bat buoc)

    Input (optional):
    - guardian_name: str - Ten phu huynh
    - student_name: str - Ten hoc sinh
    - visit_preference: str - Ngay/gio mong muon tham quan (text tu do tu chatbot)

    Auth: Header X-Chatbot-API-Key phai khop voi chatbot_api_key trong site_config.json
    """
    # Xac thuc API key
    if not _verify_chatbot_api_key():
        return forbidden_response("API key khong hop le hoac chua cau hinh")

    data = _get_request_data()

    # Validate SDT bat buoc
    phone_number = data.get("phone_number", "").strip()
    if not phone_number:
        return validation_error_response(
            "So dien thoai la bat buoc",
            {"phone_number": ["Phai co so dien thoai"]}
        )

    if not validate_phone_number(phone_number):
        return validation_error_response(
            f"So dien thoai khong hop le: {phone_number}",
            {"phone_number": [f"SDT '{phone_number}' khong dung dinh dang Viet Nam"]}
        )

    guardian_name = (data.get("guardian_name") or "").strip() or None
    student_name = (data.get("student_name") or "").strip() or None
    visit_preference = (data.get("visit_preference") or "").strip() or None

    try:
        # 1. Tao CRM Lead o buoc Draft
        doc = frappe.new_doc("CRM Lead")
        doc.data_source = "AI Chatbot"
        doc.step = "Draft"
        doc.status = ""

        if guardian_name:
            doc.guardian_name = guardian_name
        if student_name:
            doc.student_name = student_name
        # Ghi nhan lich tham quan mong muon (chatbot) vao student_note de tuyen sinh xem tren CRM
        if visit_preference:
            prefix = "[Chatbot AI] Lịch tham quan mong muốn: "
            doc.student_note = (prefix + visit_preference).strip()

        doc.append("phone_numbers", {
            "phone_number": normalize_phone_number(phone_number),
            "is_primary": 1
        })

        doc.insert(ignore_permissions=True)

        # 2. Kiem tra trung lap SĐT voi ho so trong he thong (khong check voi Verify)
        raw_phones = [phone_number]
        matches = _find_matching_leads(
            raw_phones,
            doc.student_name,
            doc.guardian_name,
            exclude_draft=True,
            exclude_verify=True
        )
        matches = [m for m in matches if m["name"] != doc.name]

        doc.step = "Verify"
        doc.status = "Can kiem tra"

        doc.save(ignore_permissions=True)

        # 3. Advance sang Lead step (status = Moi)
        doc.step = "Lead"
        doc.status = "Moi"
        if not doc.crm_code:
            doc.crm_code = generate_crm_code()
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Ghi log lich su chuyen buoc
        try:
            old_status = "Can kiem tra"
            frappe.get_doc({
                "doctype": "CRM Lead Step History",
                "lead": doc.name,
                "old_step": "Verify",
                "new_step": "Lead",
                "old_status": old_status,
                "new_status": "Moi",
                "changed_by": frappe.session.user or "Guest",
                "changed_at": frappe.utils.now()
            }).insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Loi ghi log chuyen buoc chatbot: {str(e)}")

        # Response
        lead_data = doc.as_dict()
        response = single_item_response(lead_data, "Tao ho so va dat lich thanh cong")

        # Them duplicate warning neu SDT trung voi ho so trong he thong
        if matches:
            response["data"]["duplicate_warning"] = True
            response["data"]["duplicate_lead"] = matches[0]["name"]
            response["message"] = "Tao ho so thanh cong. Luu y: SDT co the trung voi ho so da ton tai."

        return response

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Loi tao CRM Lead tu chatbot: {str(e)}")
        return error_response(f"Loi tao ho so: {str(e)}")
