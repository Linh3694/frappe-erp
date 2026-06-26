"""Hooks enqueue sync job khi DocType FaceID thay đổi."""

from __future__ import annotations

import frappe


def _enqueue(job_type: str, ref_doctype: str, ref_name: str, payload: dict | None = None):
    frappe.enqueue(
        "erp.api.faceid.sync_worker.create_device_sync_job",
        queue="short",
        enqueue_after_commit=True,
        job_type=job_type,
        ref_doctype=ref_doctype,
        ref_name=ref_name,
        payload=payload or {},
    )


def on_person_changed(doc, method=None, job_type="upsert_person"):
    _enqueue(job_type, doc.doctype, doc.name)


def on_work_shift_changed(doc, method=None):
    _enqueue("sync_shift", doc.doctype, doc.name)


def on_pickup_auth_changed(doc, method=None, job_type="upsert_pickup"):
    _enqueue(job_type, doc.doctype, doc.name)
