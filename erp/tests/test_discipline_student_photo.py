"""Batch display info ky luat phai chon anh theo nam hoc (start_date), khong theo upload_date.

Bug: nam hien tai chua co anh → fallback lay anh upload muon nhat (thuong la nam cu
nhap bo sung), thay vi nam gan nhat co anh. SSOT: erp.common.student_photo.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime
from unittest import mock


_HERE = os.path.dirname(os.path.abspath(__file__))
_DISCIPLINE_PATH = os.path.join(_HERE, "..", "api", "erp_sis", "discipline.py")

SY_CURRENT = "SY-2026-2027"
SY_NEAR = "SY-2025-2026"
SY_OLD = "SY-2024-2025"
STUDENT_ID = "CRM-STU-PHOTO-1"
PHOTO_NEAR = "/files/photo-2025.jpg"
PHOTO_OLD = "/files/photo-2024-late-upload.jpg"


def _ensure_frappe_stub():
    if "frappe" in sys.modules and hasattr(sys.modules["frappe"], "whitelist"):
        return sys.modules["frappe"]

    frappe = types.ModuleType("frappe")
    frappe.db = types.SimpleNamespace(
        exists=lambda *a, **k: True,
        get_value=lambda *a, **k: None,
        sql=lambda *a, **k: [],
        commit=lambda: None,
        rollback=lambda: None,
    )
    frappe.get_all = lambda *a, **k: []
    frappe.get_doc = lambda *a, **k: None
    frappe.whitelist = lambda *a, **k: (lambda f: f)
    frappe.log_error = lambda *a, **k: None
    frappe.local = types.SimpleNamespace(form_dict={})
    frappe.request = None
    frappe.utils = types.ModuleType("frappe.utils")
    frappe.utils.get_url = (
        lambda p: f"https://example.com{p}"
        if str(p).startswith("/")
        else f"https://example.com/{p}"
    )
    frappe.utils.get_datetime = lambda v: datetime.fromisoformat(
        str(v).replace(" ", "T")
    )
    sys.modules["frappe"] = frappe
    sys.modules["frappe.utils"] = frappe.utils
    return frappe


def _stub_discipline_deps():
    for name in (
        "erp.utils",
        "erp.utils.api_response",
        "erp.utils.search",
        "erp.sis",
        "erp.sis.discipline_record_permissions",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))
    ar = sys.modules["erp.utils.api_response"]
    ar.success_response = lambda *a, **k: {}
    ar.error_response = lambda *a, **k: {}
    ar.paginated_response = lambda *a, **k: {}
    search = sys.modules["erp.utils.search"]
    search.build_search_condition = lambda *a, **k: ""
    search.order_rows_by_names = lambda rows, *_a, **_k: rows
    search.search_names = lambda *a, **k: []
    perms = sys.modules["erp.sis.discipline_record_permissions"]
    perms.discipline_session_matches_owner = lambda *a, **k: True
    perms.user_can_create_discipline_record = lambda *a, **k: True
    perms.user_can_write_existing_discipline_record = lambda *a, **k: True


def _load_discipline():
    _ensure_frappe_stub()
    _stub_discipline_deps()
    # Tranh import package erp.api (keo family.py can frappe._)
    # Giữ erp / erp.common thật (PYTHONPATH=apps/erp) để import student_photo.
    sys.modules.setdefault("erp.api", types.ModuleType("erp.api"))
    sys.modules.setdefault("erp.api.erp_sis", types.ModuleType("erp.api.erp_sis"))
    # Load sẵn SSOT ảnh trước khi exec discipline
    import erp.common.student_photo  # noqa: F401

    # Reload module dưới test mỗi lần để bắt code mới
    name = "discipline_under_test_photo"
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _DISCIPLINE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestBatchStudentPhotoBySchoolYear(unittest.TestCase):
    """Nam hien tai chua anh → chon nam gan nhat theo start_date, khong theo upload muon."""

    def test_batch_uu_tien_nam_gan_nhat_khi_upload_nam_cu_muon_hon(self):
        frappe = _ensure_frappe_stub()
        disc = _load_discipline()

        # get_photo_urls SSOT: nam gan (2025) thang nam cu upload muon
        photo_rows_ordered = [
            types.SimpleNamespace(student_id=STUDENT_ID, photo=PHOTO_NEAR),
            types.SimpleNamespace(student_id=STUDENT_ID, photo=PHOTO_OLD),
        ]

        def fake_get_value(doctype, filters=None, fieldname=None, **kwargs):
            if doctype == "SIS School Year":
                return SY_CURRENT
            return None

        def fake_get_all(doctype, filters=None, fields=None, **kwargs):
            if doctype == "CRM Student":
                return [
                    {
                        "name": STUDENT_ID,
                        "student_name": "Nguyen Van A",
                        "student_code": "WS001",
                    }
                ]
            if doctype == "SIS Class Student":
                return []
            if doctype == "SIS Photo":
                # Du lieu bug: anh nam cu upload SAU anh nam gan
                return [
                    {
                        "student_id": STUDENT_ID,
                        "photo": PHOTO_OLD,
                        "school_year_id": SY_OLD,
                        "upload_date": "2025-12-23",
                        "creation": "2025-12-23 10:00:00",
                    },
                    {
                        "student_id": STUDENT_ID,
                        "photo": PHOTO_NEAR,
                        "school_year_id": SY_NEAR,
                        "upload_date": "2025-09-01",
                        "creation": "2025-09-01 10:00:00",
                    },
                ]
            return []

        def fake_sql(query, *args, **kwargs):
            q = str(query)
            # get_photo_urls: tra dung thu tu uu tien nam (SSOT)
            if "tabSIS Photo" in q:
                return photo_rows_ordered
            return []

        with mock.patch.object(frappe.db, "get_value", side_effect=fake_get_value), mock.patch.object(
            frappe, "get_all", side_effect=fake_get_all
        ), mock.patch.object(frappe.db, "sql", side_effect=fake_sql):
            out = disc._batch_get_student_display_info([STUDENT_ID])

        url = (out.get(STUDENT_ID) or {}).get("student_photo_url") or ""
        self.assertIn(
            "photo-2025.jpg",
            url,
            msg=(
                "Phai lay anh nam 2025-2026 (gan nhat), khong phai anh 2024-2025 "
                f"upload muon. Got: {url!r}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
