"""
CRM PIC Assignment API — can bang tai (least-loaded) cho 2 doi:
  - pic_sales: assign_pic_sales_weight_balance      (nguon: CRM Sales Team Member)
  - pic_care : assign_pic_sales_care_weight_balance (nguon: CRM Sales Care Member theo khoi)

Khong con round-robin: he cu (assign_pic_internal + CRM PIC Config, chon theo con tro
current_index) da chet va duoc xoa cung dot tach pic -> pic_sales/pic_care.
"""

import frappe
from erp.utils.api_response import (
    success_response, error_response,
    validation_error_response, not_found_response,
)
from erp.api.crm.utils import (
    check_crm_permission,
    get_request_data,
    CRM_LEAD_PIC_ELIGIBLE_ROLES,
)
from erp.crm.doctype.crm_lead.crm_lead import PIC_CARE_ALLOWED_STEPS

# Chi role nay moi doi duoc cot tuong ung (quyet dinh 2.5 — danh sach DONG,
# moi role khac deu khong doi duoc, ke ca System Manager).
PIC_FIELD_EDIT_ROLE = {
    "pic_sales": "SIS Sales Admin",
    "pic_care": "SIS Sales Care Admin",
}

# Buoc con tinh vao "tai dang chay" cua tung doi — HAI DOI KHAC NHAU, khong dung chung.
#
# Bat buoc phai loc theo buoc: pic_sales/pic_care nay giu ho so VINH VIEN (khong con bi
# ghi de khi Enrolled), neu dem het thi tai chi tang khong bao gio giam => least-loaded
# ngung chia lead cho nguoi lam lau nam, don het cho nguoi moi.
#
# Sales lam viec o giai doan TRUOC ban giao; Enrolled/Nghi hoc coi nhu xong.
_SALES_ACTIVE_STEPS = ("Draft", "Verify", "Lead", "QLead")
# Care chi cham soc ho so DA nhap hoc; Nghi hoc coi nhu ket thuc.
# (Neu dung chung bo loc voi Sales thi moi nguoi Care deu ra 0 => min() luon chon theo
#  alphabet => can bang tai chet.)
_CARE_ACTIVE_STEPS = ("Enrolled",)


def _running_load(pic_field: str, active_steps, user: str, campus_id=None) -> int:
    """So ho so DANG CHAY ma `user` phu trach o cot `pic_field`."""
    filters = {
        pic_field: user,
        "docstatus": ["<", 2],
        "step": ["in", list(active_steps)],
    }
    if campus_id:
        filters["campus_id"] = campus_id
    return frappe.db.count("CRM Lead", filters=filters)


def _get_active_sis_sales_user_names():
    """Danh sach User (name) co role SIS Sales va enabled=1."""
    rows = frappe.db.sql(
        """
        SELECT u.name FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name AND r.parenttype = 'User'
        WHERE r.role = 'SIS Sales' AND IFNULL(u.enabled, 0) = 1
        ORDER BY u.name
        """
    )
    return [r[0] for r in rows] if rows else []


def _get_active_sis_sales_care_user_names():
    """Danh sach User (name) co role SIS Sales Care va enabled=1."""
    rows = frappe.db.sql(
        """
        SELECT u.name FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name AND r.parenttype = 'User'
        WHERE r.role = 'SIS Sales Care' AND IFNULL(u.enabled, 0) = 1
        ORDER BY u.name
        """
    )
    return [r[0] for r in rows] if rows else []


def _get_active_users_with_role(role):
    """Danh sach User (name) co role chi dinh va enabled=1."""
    rows = frappe.db.sql(
        """
        SELECT u.name FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name AND r.parenttype = 'User'
        WHERE r.role = %s AND IFNULL(u.enabled, 0) = 1
        ORDER BY u.name
        """,
        (role,),
    )
    return [r[0] for r in rows] if rows else []


def _get_lead_receiver_user_names():
    """Nhom user nhan lead cho auto-assign.

    Nguon chinh: bang cau hinh CRM Sales Team Member (is_active=1) — chi user con enabled.
    Fallback khi bang rong (chua cau hinh): user co role SIS Sales Admin va enabled=1.
    """
    rows = frappe.db.sql(
        """
        SELECT m.user FROM `tabCRM Sales Team Member` m
        INNER JOIN `tabUser` u ON u.name = m.user
        WHERE IFNULL(m.is_active, 0) = 1 AND IFNULL(u.enabled, 0) = 1
        ORDER BY m.user
        """
    )
    users = [r[0] for r in rows] if rows else []
    if users:
        return users
    # Chua cau hinh nhom nhan lead -> fallback ve SIS Sales Admin
    return _get_active_users_with_role("SIS Sales Admin")


def assign_pic_sales_weight_balance(lead_name, campus_id=None):
    """
    Gan PIC Sales mac dinh: user dang dam nhan it ho so CRM Lead nhat (can bang tai / least-loaded).
    Khong ghi de neu ho so da co pic_sales. campus_id: chi dem ho so cung campus khi co gia tri.
    Chi tra ve email duoc chon — goi doc.pic_sales = pic roi save, hoac set_value sau insert
    (khong set_value trong ham).
    """
    existing = frappe.db.get_value("CRM Lead", lead_name, "pic_sales")
    if existing:
        return None

    users = _get_lead_receiver_user_names()
    if not users:
        return None

    counts = {u: _running_load("pic_sales", _SALES_ACTIVE_STEPS, u, campus_id) for u in users}

    # Chon user co count nho nhat; hoa: sap xep theo name
    chosen = min(users, key=lambda x: (counts.get(x, 0), x))
    # Khong frappe.db.set_value o day: neu goi truoc doc.save() se lam lech modified -> TimestampMismatch.
    # Luu qua doc.pic_sales + save (pipeline/merge) hoac set_value sau insert (lead.py).
    return chosen


def _get_sales_care_users_for_grade(target_grade):
    """Nhom user cham soc cho auto-assign theo Lop du tuyen.

    Nguon chinh: CRM Sales Care Member (is_active=1, User enabled) co bang con
    target_grades chua dung lop du tuyen cua ho so.
    Fallback (khong cau hinh / khong ai phu trach lop nay / ho so thieu lop):
      user co role SIS Sales Care Admin va enabled=1.
    """
    grade = (str(target_grade).strip() if target_grade is not None else "")
    if grade:
        rows = frappe.db.sql(
            """
            SELECT DISTINCT m.user
            FROM `tabCRM Sales Care Member` m
            INNER JOIN `tabUser` u ON u.name = m.user
            INNER JOIN `tabCRM Sales Care Member Grade` g
                ON g.parent = m.name AND g.parenttype = 'CRM Sales Care Member'
            WHERE IFNULL(m.is_active, 0) = 1 AND IFNULL(u.enabled, 0) = 1
              AND g.target_grade = %s
            ORDER BY m.user
            """,
            (grade,),
        )
        users = [r[0] for r in rows] if rows else []
        if users:
            return users
    # Chua cau hinh / khong ai phu trach lop nay -> fallback SIS Sales Care Admin
    return _get_active_users_with_role("SIS Sales Care Admin")


def assign_pic_sales_care_weight_balance(lead_name, campus_id=None):
    """
    Khi QLead -> Enrolled: chon PIC Care theo Lop du tuyen cua ho so — trong nhom phu trach
    lop do, chon user dam nhan it ho so nhat (can bang tai).
    Chua cau hinh / khong ai phu trach -> fallback SIS Sales Care Admin.
    Khong ghi de neu ho so da co pic_care (vd. PIC chon tay) — doi xung voi
    assign_pic_sales_weight_balance; truoc day THIEU guard nay nen phan cong tay bi huy am tham.
    Tra ve email hoac None. Goi doc.pic_care = pic roi save, khong ghi DB trong ham
    (tranh TimestampMismatch).
    """
    existing = frappe.db.get_value("CRM Lead", lead_name, "pic_care")
    if existing:
        return None

    target_grade = frappe.db.get_value("CRM Lead", lead_name, "target_grade")
    users = _get_sales_care_users_for_grade(target_grade)
    if not users:
        return None

    counts = {u: _running_load("pic_care", _CARE_ACTIVE_STEPS, u, campus_id) for u in users}

    chosen = min(users, key=lambda x: (counts.get(x, 0), x))
    # Khong set_value truoc doc.save() (tranh TimestampMismatch) — giong assign_pic_sales_weight_balance
    return chosen


def _is_valid_crm_lead_pic_user(pic_email: str) -> bool:
    """User ton tai, enabled, co it nhat mot role trong CRM_LEAD_PIC_ELIGIBLE_ROLES."""
    if not pic_email or not frappe.db.exists("User", pic_email):
        return False
    if not frappe.db.get_value("User", pic_email, "enabled"):
        return False
    roles = set(frappe.get_roles(pic_email))
    return bool(roles & CRM_LEAD_PIC_ELIGIBLE_ROLES)


@frappe.whitelist(methods=["POST"])
def reassign_pic():
    """Chuyen PIC thu cong cho MOT cot cu the.

    `pic_field`: 'pic_sales' | 'pic_care'. Mac dinh 'pic_sales' de tuong thich client cu.
    Quyen (2.5): chi SIS Sales Admin doi duoc pic_sales, chi SIS Sales Care Admin doi duoc
    pic_care — moi role khac deu bi tu choi, KE CA System Manager.
    """
    check_crm_permission()
    data = get_request_data()

    lead_name = data.get("lead_name")
    new_pic = data.get("new_pic")
    pic_field = (data.get("pic_field") or "pic_sales").strip()

    if not lead_name or not new_pic:
        return validation_error_response("Thieu tham so", {
            "lead_name": ["Bat buoc"] if not lead_name else [],
            "new_pic": ["Bat buoc"] if not new_pic else []
        })

    if pic_field not in PIC_FIELD_EDIT_ROLE:
        return validation_error_response(
            "pic_field khong hop le",
            {"pic_field": ["Chi nhan 'pic_sales' hoac 'pic_care'"]},
        )

    required_role = PIC_FIELD_EDIT_ROLE[pic_field]
    if required_role not in set(frappe.get_roles()):
        return error_response(f"Chi role {required_role} moi duoc doi {pic_field}")

    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")

    if not _is_valid_crm_lead_pic_user(new_pic):
        return validation_error_response(
            "PIC khong hop le: can la user hoat dong va co mot trong cac role SIS Sales / SIS Sales Admin / SIS Sales Care / SIS Sales Care Admin",
            {"new_pic": ["User khong hop le hoac khong co quyen PIC CRM"]},
        )

    # set_value BO QUA validate() nen phai tu chan rang buoc 2.12 o day
    # (CRMLead._validate_pic_care_step se khong chay).
    if pic_field == "pic_care":
        step = frappe.db.get_value("CRM Lead", lead_name, "step")
        if step not in PIC_CARE_ALLOWED_STEPS:
            return error_response(
                "Khong the gan PIC Care khi ho so chua o buoc Hoc sinh chinh thuc "
                f"(buoc hien tai: {step or '-'})"
            )

    frappe.db.set_value("CRM Lead", lead_name, pic_field, new_pic)
    frappe.db.commit()

    return success_response({pic_field: new_pic}, f"Da chuyen {pic_field} sang {new_pic}")
