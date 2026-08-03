"""Chan hoi quy: get_class_log tu tao khung SIS Class Log Subject thi phai
ignore_permissions.

Doctype chi cho System Manager va SIS Teacher quyen create, nen nguoi dung hop le
khong mang role SIS Teacher bi PermissionError khi chi dang XEM. Prod 03/08/2026:
48 loi `get_class_log error:` trong tabError Log, traceback dung o doc.insert().
"""

import ast
import json
import os
import unittest

_ERP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODULE_PATH = os.path.join(_ERP_DIR, "api", "erp_sis", "class_log.py")
_DOCTYPE_PATH = os.path.join(
    _ERP_DIR, "sis", "doctype", "sis_class_log_subject", "sis_class_log_subject.json"
)


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


class TestTuTaoKhungKhongVuongQuyen(unittest.TestCase):
    def setUp(self):
        with open(_MODULE_PATH, encoding="utf-8") as fh:
            self.src = fh.read()
        self.tree = ast.parse(self.src)

    def test_moi_insert_trong_get_class_log_deu_ignore_permissions(self):
        func = _find_function(self.tree, "get_class_log")
        self.assertIsNotNone(func, "khong tim thay ham get_class_log")

        thieu = []
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "insert":
                co_co = any(kw.arg == "ignore_permissions" for kw in node.keywords)
                if not co_co:
                    thieu.append(node.lineno)
        self.assertEqual(thieu, [], f"insert() thieu ignore_permissions o dong: {thieu}")

    def test_doctype_khong_bi_mo_rong_quyen(self):
        """Sua o tang API, KHONG duoc noi long quyen tren doctype."""
        with open(_DOCTYPE_PATH, encoding="utf-8") as fh:
            dt = json.load(fh)
        roles_co_create = sorted(p["role"] for p in dt["permissions"] if p.get("create"))
        self.assertEqual(roles_co_create, ["SIS Teacher", "System Manager"])


if __name__ == "__main__":
    unittest.main()
