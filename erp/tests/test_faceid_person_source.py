"""Test phan thuan logic cua person_source (khong can Frappe runtime).

school_label quyet dinh "phong ban = Truong" cua hoc sinh tren FaceID Person.
Sai theo huong nao cung lam van hanh phan nham danh sach theo truong,
nen chot bang test: uu tien title cua SIS Education Stage, fallback grade_code.
"""

import importlib.util
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.join(_HERE, "..", "api", "faceid", "person_source.py")


def _load_person_source():
    if "frappe" not in sys.modules:
        frappe = types.ModuleType("frappe")
        frappe.utils = types.ModuleType("frappe.utils")
        frappe.utils.now = lambda: "2026-08-05 00:00:00"
        frappe.utils.today = lambda: "2026-08-05"
        frappe.utils.cint = lambda v: int(v or 0)
        sys.modules["frappe"] = frappe
        sys.modules["frappe.utils"] = frappe.utils
    else:
        if not hasattr(sys.modules["frappe"].utils, "cint"):
            sys.modules["frappe"].utils.cint = lambda v: int(v or 0)
    # photo.py can Frappe that — stub du 3 ham person_source dung
    if "erp.api.faceid.photo" not in sys.modules:
        for pkg in ("erp", "erp.api", "erp.api.faceid"):
            sys.modules.setdefault(pkg, types.ModuleType(pkg))
        photo = types.ModuleType("erp.api.faceid.photo")
        photo.get_guardian_photo_url = lambda name: ""
        photo.get_student_photo_url = lambda name: ""
        photo.get_user_photo_url = lambda name: ""
        sys.modules["erp.api.faceid.photo"] = photo
    spec = importlib.util.spec_from_file_location("faceid_person_source", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ps = _load_person_source()


class TestSchoolLabel(unittest.TestCase):
    def test_stage_title_tieng_viet(self):
        self.assertEqual(ps.school_label(None, "Tiểu học"), ps.SCHOOL_PRIMARY)
        self.assertEqual(ps.school_label(None, "Trung học Cơ sở"), ps.SCHOOL_MIDDLE)
        self.assertEqual(ps.school_label(None, "Trung học Phổ thông"), ps.SCHOOL_HIGH)

    def test_stage_title_tieng_anh(self):
        self.assertEqual(ps.school_label(None, "Elementary"), ps.SCHOOL_PRIMARY)
        self.assertEqual(ps.school_label(None, "Primary"), ps.SCHOOL_PRIMARY)
        self.assertEqual(ps.school_label(None, "Middle School"), ps.SCHOOL_MIDDLE)
        self.assertEqual(ps.school_label(None, "Secondary"), ps.SCHOOL_MIDDLE)
        self.assertEqual(ps.school_label(None, "High School"), ps.SCHOOL_HIGH)

    def test_stage_title_viet_tat(self):
        self.assertEqual(ps.school_label(None, "THCS"), ps.SCHOOL_MIDDLE)
        self.assertEqual(ps.school_label(None, "THPT"), ps.SCHOOL_HIGH)

    def test_fallback_grade_code(self):
        # Stage khong khop keyword → suy tu so khoi
        self.assertEqual(ps.school_label("1"), ps.SCHOOL_PRIMARY)
        self.assertEqual(ps.school_label("5"), ps.SCHOOL_PRIMARY)
        self.assertEqual(ps.school_label("6"), ps.SCHOOL_MIDDLE)
        self.assertEqual(ps.school_label("9"), ps.SCHOOL_MIDDLE)
        self.assertEqual(ps.school_label("10"), ps.SCHOOL_HIGH)
        self.assertEqual(ps.school_label("12"), ps.SCHOOL_HIGH)

    def test_stage_title_thang_grade_code(self):
        # Title stage dang tin hon so khoi khi ca hai cung co
        self.assertEqual(ps.school_label("3", "THPT"), ps.SCHOOL_HIGH)

    def test_khong_suy_duoc(self):
        self.assertEqual(ps.school_label(None, None), "")
        self.assertEqual(ps.school_label("", ""), "")
        self.assertEqual(ps.school_label("K"), "")
        self.assertEqual(ps.school_label("13"), "")
        self.assertEqual(ps.school_label(None, "Khoi la"), "")


if __name__ == "__main__":
    unittest.main()
