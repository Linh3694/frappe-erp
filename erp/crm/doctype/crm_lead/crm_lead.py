# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


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

    def validate(self):
        """Moi guardian lead: chi 1 dong primary trong emails neu co du lieu."""
        self._validate_bank_accounts_max_two()
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
