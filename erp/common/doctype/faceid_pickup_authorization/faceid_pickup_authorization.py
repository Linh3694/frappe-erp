# Copyright (c) 2026, WSHN and contributors
import frappe
from frappe.model.document import Document


class FaceIDPickupAuthorization(Document):
    def validate(self):
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            frappe.throw("valid_from phải <= valid_to")
        g_type = frappe.db.get_value("FaceID Person", self.guardian, "person_type")
        s_type = frappe.db.get_value("FaceID Person", self.student, "person_type")
        if g_type != "guardian":
            frappe.throw("Guardian phải là FaceID Person loại guardian")
        if s_type != "student":
            frappe.throw("Student phải là FaceID Person loại student")

    def after_insert(self):
        self._enqueue_sync("upsert_pickup")

    def on_update(self):
        if self.revoked:
            self._enqueue_sync("revoke_pickup")
        else:
            self._enqueue_sync("upsert_pickup")

    def on_trash(self):
        self._enqueue_sync("revoke_pickup")

    def _enqueue_sync(self, job_type):
        from erp.api.faceid.person_hooks import on_pickup_auth_changed

        on_pickup_auth_changed(self, job_type=job_type)
