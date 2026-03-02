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
    "Draft": ["New"],
    "Verify": ["New"],
    "Lead": ["Moi", "KNM", "HGL", "KNM nhieu lan", "KCNC", "Sai thong tin", "Trung Lead", "Lost"],
    "QLead": ["Follow up", "Pre-Event", "Event", "Pre-school tour", "School tour", "Lost"],
    "Test": ["Pre-test", "Test", "Offered", "Retake", "Fail", "Lost"],
    "Deal": ["Booked", "Deposit", "Paid", "Lost"],
    "Enrolled": ["Enrolled"],
    "Re-Enroll": ["Paid", "Unpaid"],
    "Withdraw": ["Withdraw"],
    "Graduated": ["Graduated"],
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


def get_request_data() -> dict:
    """Lay data tu request (JSON hoac form_dict)"""
    if frappe.request and frappe.request.is_json:
        return frappe.request.json or {}
    return dict(frappe.form_dict)
