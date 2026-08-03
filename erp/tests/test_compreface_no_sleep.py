"""Chan hoi quy: khong duoc goi time.sleep trong web handler.

Prod chi co 18 worker gunicorn sync. Ngay 03/08/2026, check_compreface_subject
ngu 2s x 2 lan moi khi CompreFace khong tra loi, chay 3.076 lan trong 1,5 gio va
lam p95 toan he thong nhay tu 242ms len 2.937ms.

Test tinh bang AST — bus_student.py import frappe nen khong nap truc tiep duoc.
"""

import ast
import os
import unittest

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "api",
    "erp_sis",
    "bus_student.py",
)

# Cac ham chay dong bo trong web request — tuyet doi khong duoc ngu.
HAM_KHONG_DUOC_NGU = ("check_compreface_subject",)


def _load_tree():
    with open(_MODULE_PATH, encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _sleep_calls(func_node):
    """Tim moi loi goi sleep(...) hoac time.sleep(...) trong than ham."""
    found = []
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "sleep":
            found.append("{}.sleep".format(getattr(f.value, "id", "?")))
        elif isinstance(f, ast.Name) and f.id == "sleep":
            found.append("sleep")
    return found


def _dem_goi(func_node, ten_ham):
    n = 0
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == ten_ham:
                n += 1
            elif isinstance(f, ast.Name) and f.id == ten_ham:
                n += 1
    return n


class TestKhongNguTrongWebHandler(unittest.TestCase):
    def setUp(self):
        self.tree = _load_tree()

    def test_khong_co_sleep(self):
        for ten in HAM_KHONG_DUOC_NGU:
            func = _find_function(self.tree, ten)
            self.assertIsNotNone(func, f"khong tim thay ham {ten}")
            self.assertEqual(
                _sleep_calls(func), [], f"{ten} van con goi sleep trong web request"
            )

    def test_goi_compreface_dung_mot_lan(self):
        func = _find_function(self.tree, "check_compreface_subject")
        self.assertIsNotNone(func)
        self.assertEqual(
            _dem_goi(func, "check_subject_complete"),
            1,
            "chi duoc goi CompreFace mot lan trong web request, khong retry",
        )

    def test_khong_con_vong_lap_retry(self):
        func = _find_function(self.tree, "check_compreface_subject")
        self.assertIsNotNone(func)
        for node in ast.walk(func):
            if isinstance(node, ast.For):
                it = node.iter
                la_range = (
                    isinstance(it, ast.Call)
                    and isinstance(it.func, ast.Name)
                    and it.func.id == "range"
                )
                self.assertFalse(la_range, "van con vong lap retry `for ... in range(...)`")

    def test_van_giu_nhanh_fallback_theo_co_database(self):
        """Bo retry nhung PHAI giu duong rot ve co compreface_registered."""
        with open(_MODULE_PATH, encoding="utf-8") as fh:
            src_file = fh.read()
        src = ast.get_source_segment(src_file, _find_function(self.tree, "check_compreface_subject"))
        self.assertIn("compreface_registered", src)
        self.assertIn("no_subject", src)


if __name__ == "__main__":
    unittest.main()
