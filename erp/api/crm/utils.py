"""
CRM Utils - Tien ich dung chung cho CRM module
"""

import frappe
import re
from typing import List, Optional, Dict


CRM_STEPS = [
    "Draft", "Verify", "Lead", "QLead", "Test",
    "Deal", "Enrolled", "Re-Enroll", "Withdraw", "Graduated"
]

STEP_STATUSES: Dict[str, List[str]] = {
    "Draft": [],
    "Verify": ["Can kiem tra", "Trung"],
    "Lead": ["Moi", "Khong nghe may", "Hen gap lai", "Khong nghe may nhieu lan", "Khong co nhu cau", "Sau thong tin", "Trung Lead", "Lost"],
    "QLead": ["Moi", "Follow Up", "Pre-Event", "Event", "Pre-school Tour/ School Tour", "Lost"],
    "Test": ["Pre-test", "Test", "Offered", "Failed", "Retake", "Lost"],
    "Deal": ["Booked", "Deposit", "Lost", "Refund", "Reserved", "Paid"],
    "Enrolled": ["Dang hoc"],
    "Re-Enroll": ["Unpaid", "Considering", "Paid"],
    "Withdraw": ["Chuyen truong", "Bao luu"],
    "Graduated": ["Tot nghiep"],
}

VALID_STEP_TRANSITIONS = {
    "Draft": ["Lead", "Verify"],
    "Verify": ["Lead"],
    "Lead": ["QLead"],
    "QLead": ["Test"],
    "Test": ["Deal"],
    "Deal": ["Enrolled"],
    "Enrolled": ["Re-Enroll", "Withdraw", "Graduated"],
    "Re-Enroll": ["Enrolled"],
    "Graduated": ["Re-Enroll"],
}

ALLOWED_ROLES = ["System Manager", "SIS Manager", "Registrar", "SIS Sales"]


def check_crm_permission(required_roles: Optional[List[str]] = None) -> bool:
    """Kiem tra quyen truy cap CRM"""
    roles = required_roles or ALLOWED_ROLES
    user_roles = frappe.get_roles(frappe.session.user)
    if not any(role in user_roles for role in roles):
        frappe.throw("Khong co quyen truy cap CRM", frappe.PermissionError)
    return True


def validate_phone_number(phone: str) -> bool:
    """Validate dinh dang SDT Viet Nam: +84xxxxxxxxx, 0xxxxxxxxx, hoac xxxxxxxxx"""
    if not phone:
        return False
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    pattern = r'^(\+84|0)?\d{9,10}$'
    return bool(re.match(pattern, cleaned))


def normalize_phone_number(phone: str) -> str:
    """Chuan hoa SDT ve dinh dang 0xxxxxxxxx"""
    if not phone:
        return ""
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("+84"):
        cleaned = "0" + cleaned[3:]
    elif not cleaned.startswith("0") and len(cleaned) >= 9:
        cleaned = "0" + cleaned
    return cleaned


def get_valid_statuses_for_step(step: str) -> List[str]:
    """Tra ve danh sach trang thai hop le cho 1 buoc"""
    return STEP_STATUSES.get(step, [])


def validate_step_transition(current_step: str, target_step: str) -> bool:
    """Validate chuyen buoc hop le"""
    valid_targets = VALID_STEP_TRANSITIONS.get(current_step, [])
    if target_step not in valid_targets:
        frappe.throw(
            f"Khong the chuyen tu {current_step} sang {target_step}. "
            f"Cac buoc hop le: {', '.join(valid_targets)}",
            frappe.ValidationError
        )
    return True


def generate_crm_code() -> str:
    """Sinh ma CRM tu dong theo format CRM-00001, tang dan"""
    last = frappe.db.sql(
        "SELECT crm_code FROM `tabCRM Lead` "
        "WHERE crm_code IS NOT NULL AND crm_code != '' "
        "ORDER BY crm_code DESC LIMIT 1"
    )
    if last and last[0][0]:
        num = int(last[0][0].replace("CRM-", "")) + 1
    else:
        num = 1
    return f"CRM-{num:05d}"


def get_request_data() -> dict:
    """Lay data tu request (JSON hoac form_dict)"""
    if frappe.request and frappe.request.is_json:
        return frappe.request.json or {}
    return dict(frappe.form_dict)
