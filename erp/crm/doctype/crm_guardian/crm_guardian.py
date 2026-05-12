# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMGuardian(Document):
    def before_save(self):
        """Chỉ set relationship nếu field tồn tại; đồng bộ legacy phone/email vào child nếu còn trống"""
        # Chỉ set relationship nếu field tồn tại
        if hasattr(self, 'relationship') and not self.relationship:
            self.relationship = "other"
        self._migrate_flat_contacts_if_needed()

    def _migrate_flat_contacts_if_needed(self):
        """Nếu chưa có dòng trong child table nhưng field phẳng có giá trị — bootstrap 1 row primary"""
        phones = list(getattr(self, 'phone_numbers', None) or [])
        if not phones and getattr(self, 'phone_number', None):
            pn = (self.phone_number or '').strip()
            if pn:
                self.append('phone_numbers', {'phone_number': pn, 'is_primary': 1})

        emails = list(getattr(self, 'emails', None) or [])
        if not emails and getattr(self, 'email', None):
            em = (self.email or '').strip()
            if em:
                self.append('emails', {'email_address': em, 'is_primary': 1})

    def validate(self):
        """Validate guardian data + đảm bảo đúng 1 primary mỗi bảng, sync field legacy"""
        # Chỉ validate nếu các fields tồn tại
        key_person = getattr(self, 'key_person', None)
        parent_account = getattr(self, 'parent_account', None)
        if key_person and parent_account:
            frappe.throw("A guardian cannot be both key person and parent account")

        self._dedupe_child_emails_case_insensitive()
        self._enforce_single_primary('phone_numbers', 'phone_number', 'phone')
        self._enforce_single_primary('emails', 'email_address', 'email')

    def _dedupe_child_emails_case_insensitive(self):
        rows = getattr(self, 'emails', None) or []
        if not rows:
            return
        seen = set()
        to_remove_idx = []
        for i, r in enumerate(rows):
            addr = (getattr(r, 'email_address', None) or (r.get('email_address') if isinstance(r, dict) else '') or '').strip().lower()
            if not addr:
                to_remove_idx.append(i)
                continue
            if addr in seen:
                to_remove_idx.append(i)
                continue
            seen.add(addr)
        for i in reversed(sorted(set(to_remove_idx))):
            self.remove(self.emails[i])

    def _enforce_single_primary(self, table_field: str, value_attr: str, legacy_field: str):
        rows = getattr(self, table_field, None) or []
        if not rows:
            if hasattr(self, legacy_field):
                setattr(self, legacy_field, getattr(self, legacy_field, '') or '')
            return

        primary_idx = None
        primary_count = 0
        for i, row in enumerate(rows):
            prim = getattr(row, 'is_primary', None) if hasattr(row, 'is_primary') else row.get('is_primary')
            if prim in (1, True):
                primary_count += 1
                if primary_idx is None:
                    primary_idx = i

        if primary_count != 1:
            for row in rows:
                if hasattr(row, 'is_primary'):
                    row.is_primary = 0
                else:
                    row['is_primary'] = 0
            target_row = rows[primary_idx if primary_idx is not None else 0]
            if hasattr(target_row, 'is_primary'):
                target_row.is_primary = 1
            else:
                target_row['is_primary'] = 1

        # Sync legacy field tu primary row
        for row in rows:
            prim = getattr(row, 'is_primary', None) if hasattr(row, 'is_primary') else row.get('is_primary')
            if prim in (1, True):
                val = getattr(row, value_attr, None) if hasattr(row, value_attr) else row.get(value_attr)
                if hasattr(self, legacy_field):
                    setattr(self, legacy_field, val or '')
                break
