# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

# Bien the gioi tinh tu nhap tay / import -> gia tri canonical cua field student_gender (Nam/Nu).
# Khop sau khi .strip().lower() nen phu duoc "NU", "Nữ", "female", "F"...
GENDER_VARIANT_TO_CANONICAL = {
    "nam": "Nam",
    "male": "Nam",
    "m": "Nam",
    "nu": "Nu",
    "nữ": "Nu",
    "female": "Nu",
    "f": "Nu",
}

# Buoc duoc phep co PIC Care. Care chi nhan ban giao tu QLead -> Enrolled; 'Nghi hoc'
# giu nguyen PIC dang co nen van nam trong danh sach.
PIC_CARE_ALLOWED_STEPS = ("Enrolled", "Nghi hoc")


class CRMLead(Document):
    def after_insert(self):
        """Dong bo Student neu Lead moi duoc tao kem linked_student (hiem)."""
        from erp.api.crm.lead_student_sync import sync_linked_crm_student_from_lead

        sync_linked_crm_student_from_lead(self)

    def on_update(self):
        """Moi lan cap nhat Lead: day ho so hoc sinh sang CRM Student da lien ket."""
        from erp.api.crm.lead_student_sync import sync_linked_crm_student_from_lead

        sync_linked_crm_student_from_lead(self)

    def before_save(self):
        """Bootstrap emails child tu guardian_email phang neu chua co dong nao."""
        rows = getattr(self, 'emails', None) or []
        legacy = getattr(self, 'guardian_email', None) or ''
        if not rows and legacy and str(legacy).strip():
            self.append('emails', {'email_address': str(legacy).strip(), 'is_primary': 1})

    def _normalize_student_gender(self):
        """Gioi tinh: chuan hoa moi bien the (Nu/nu/Nữ/female/F...) ve canonical Nam/Nu.

        Choke point chung cho moi luong save chay validate (create/update_lead, import,
        bulk...) — file import co the ghi "Nữ" theo nhan hien thi thay vi gia tri "Nu".
        Gia tri khong khop bien the nao thi giu nguyen de validate Select bao loi nhu cu.
        """
        raw = self.get("student_gender")
        if not raw:
            return
        canonical = GENDER_VARIANT_TO_CANONICAL.get(str(raw).strip().lower())
        if canonical and canonical != raw:
            self.set("student_gender", canonical)

    def _normalize_nationalities(self):
        """Quoc tich (HS + PH) la Link -> Country: ep ve ten Country hop le hoac rong.

        Choke point chung cho moi luong save chay validate (create/update_lead, bulk...),
        tranh LinkValidationError voi gia tri tu do / khong khop.
        """
        from erp.utils.country import to_country_or_blank

        for field in ("student_nationality", "guardian_nationality"):
            val = self.get(field)
            if val:
                self.set(field, to_country_or_blank(val))

    def validate(self):
        """Moi guardian lead: chi 1 dong primary trong emails neu co du lieu."""
        self._normalize_student_gender()
        self._normalize_nationalities()
        self._validate_bank_accounts_max_two()
        self._validate_pic_care_step()
        self._dedupe_lead_emails()
        rows = getattr(self, 'emails', None) or []
        if not rows:
            return

        primaries = []
        for i, row in enumerate(rows):
            prim = getattr(row, 'is_primary', None) if hasattr(row, 'is_primary') else row.get('is_primary')
            if prim in (1, True):
                primaries.append(i)

        if len(primaries) != 1:
            for row in rows:
                if hasattr(row, 'is_primary'):
                    row.is_primary = 0
                else:
                    row['is_primary'] = 0
            idx = primaries[0] if primaries else 0
            target = rows[idx]
            if hasattr(target, 'is_primary'):
                target.is_primary = 1
            else:
                target['is_primary'] = 1

        # Dong bo guardian_email = email primary (tuong thích)
        for row in rows:
            prim = getattr(row, 'is_primary', None) if hasattr(row, 'is_primary') else row.get('is_primary')
            if prim in (1, True):
                addr = getattr(row, 'email_address', None) if hasattr(row, 'email_address') else row.get('email_address')
                if addr and hasattr(self, 'guardian_email'):
                    self.guardian_email = str(addr).strip()
                break

    def _dedupe_lead_emails(self):
        rows = getattr(self, 'emails', None) or []
        if not rows:
            return
        seen = set()
        to_remove = []
        for i, r in enumerate(rows):
            addr = (getattr(r, 'email_address', None) or (r.get('email_address') if isinstance(r, dict) else '') or '').strip().lower()
            if not addr:
                to_remove.append(i)
                continue
            if addr in seen:
                to_remove.append(i)
                continue
            seen.add(addr)
        for i in reversed(sorted(set(to_remove))):
            self.remove(self.emails[i])

    def _validate_bank_accounts_max_two(self):
        rows = getattr(self, 'bank_accounts', None) or []
        if len(rows) > 2:
            frappe.throw("Toi da 2 tai khoan thanh toan tren ho so")

    def _validate_pic_care_step(self):
        """PIC Care chi ton tai tu buoc Hoc sinh chinh thuc (Enrolled) tro di.

        Choke point chung cho moi luong ghi (form, API, import, reassign) — dat o
        validate() thay vi chan rieng tung luong.
        """
        if self.get("pic_care") and self.get("step") not in PIC_CARE_ALLOWED_STEPS:
            frappe.throw(
                "Khong the gan PIC Care khi ho so chua o buoc Hoc sinh chinh thuc "
                f"(buoc hien tai: {self.get('step') or '-'})"
            )
