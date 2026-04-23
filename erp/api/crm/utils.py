"""
CRM Utils - Tien ich dung chung cho CRM module
"""

import frappe
import re
from typing import List, Optional, Dict


CRM_STEPS = [
    "Draft", "Verify", "Lead", "QLead",
    "Enrolled", "Nghi hoc",
]

STEP_STATUSES: Dict[str, List[str]] = {
    "Draft": [],
    "Verify": [
        "Can kiem tra",
        "Trung",
        "Da kiem tra - Gop ho so",
        "Da kiem tra - Bao trung",
        "Da kiem tra - Trung hoc sinh",
    ],
    "Lead": ["Moi", "Khong nghe may", "Hen gap lai", "Khong nghe may nhieu lan", "Khong co nhu cau", "Sau thong tin", "Trung Lead", "Lost"],
    # Trang thai chinh buoc QLead (dong bo frontend STEP_STATUSES)
    "QLead": [
        "Dang cham soc",
        "Dat lich hen",
        "Thoa thuan",
        "Khao sat dau vao",
        "Lost",
    ],
    # Cho xep lop dat dau: default import Excel khi doi step khong kem status
    "Enrolled": ["Cho xep lop", "Dang hoc", "Dinh chi hoc"],
    # Gop Withdraw + Graduated: Tốt nghiệp, Bảo lưu, Chuyển trường
    "Nghi hoc": ["Tot nghiep", "Bao luu", "Chuyen truong"],
}

# Sub-status QLead: khao sat dau vao / thoa thuan (truong test_status, deal_status)
QLEAD_TEST_STATUSES = ["Dat lich", "Tham gia", "De xuat", "Thi lai", "Tu choi"]
QLEAD_DEAL_STATUSES = ["Dat cho", "Dat coc", "Dong phi", "Hoan phi", "Bao luu/Chuyen", "Tu choi"]

VALID_STEP_TRANSITIONS = {
    "Draft": ["Lead", "Verify"],
    "Verify": ["Lead"],
    "Lead": ["QLead", "Verify"],
    "QLead": ["Enrolled"],
    "Enrolled": ["Nghi hoc"],
    "Nghi hoc": ["Enrolled"],
}

ALLOWED_ROLES = [
    "System Manager",
    "SIS Manager",
    "Registrar",
    "SIS Sales",
    "SIS Sales Care",
    "SIS Sales Care Admin",
    "SIS Sales Admin",
    "SIS BOD",
]

# PIC CRM Lead khi chon thu cong + validate reassign_pic (dong bo DIRECT_ISSUE_ROLES trong issue.py)
CRM_LEAD_PIC_ELIGIBLE_ROLES = frozenset(
    {
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales",
        "SIS Sales Admin",
    }
)


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
    """
    Sinh ma CRM tu dong theo format CRM-00001, tang dan.

    - Sort theo gia tri SO (CAST) thay vi chuoi de tranh bug khi vuot CRM-99999
      (vi CRM-9999 > CRM-10000 khi so sanh chuoi).
    - Dung FOR UPDATE de lock row khi transaction dang mo, giam race condition
      khi co nhieu request tao Lead dong thoi (migration + UI).
    - Retry toi da 5 lan neu unique constraint bi trung (edge case khi 2 worker
      doc cung 1 "last" giua 2 transaction).
    - Format: CRM-{N:05d} voi N >= 1; neu N > 99999 se tu nhien tang do rong (vd CRM-100000).
    """
    for _ in range(5):
        last = frappe.db.sql(
            """
            SELECT crm_code
            FROM `tabCRM Lead`
            WHERE crm_code IS NOT NULL AND crm_code != ''
            ORDER BY CAST(REPLACE(crm_code, 'CRM-', '') AS UNSIGNED) DESC
            LIMIT 1
            FOR UPDATE
            """
        )
        if last and last[0][0]:
            try:
                num = int(last[0][0].replace("CRM-", "")) + 1
            except ValueError:
                num = 1
        else:
            num = 1
        candidate = f"CRM-{num:05d}"
        # Kiem tra lai de chac chan chua co ai chen cung ma (truong hop FOR UPDATE
        # khong block do transaction khac da commit truoc). Neu trung, thu lai.
        if not frappe.db.exists("CRM Lead", {"crm_code": candidate}):
            return candidate
    # Fallback cuoi cung: dung timestamp de tranh deadlock vong lap
    import time
    return f"CRM-{int(time.time() * 1000) % 10**8:08d}"


def get_request_data() -> dict:
    """Lay data tu request (JSON hoac form_dict)"""
    if frappe.request and frappe.request.is_json:
        return frappe.request.json or {}
    return dict(frappe.form_dict)
