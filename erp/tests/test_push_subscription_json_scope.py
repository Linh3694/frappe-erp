"""Chan hoi quy: `import json` trong ham lam `json` thanh bien local va gay
UnboundLocalError o duong di pho bien nhat (2.036 loi tren prod tinh den 03/08/2026).

Test tinh bang AST — module push_notification.py import frappe nen khong nap truc tiep duoc.
"""

import ast
import os
import unittest

_API_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "api",
    "parent_portal",
)
_MODULE_PATH = os.path.join(_API_DIR, "push_notification.py")


def _load_tree(path):
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _imported_names_inside(func_node):
    """Ten duoc import BEN TRONG than ham — moi ten nhu vay thanh bien local."""
    names = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


class TestJsonKhongBiShadow(unittest.TestCase):
    def setUp(self):
        self.tree = _load_tree(_MODULE_PATH)

    def test_json_duoc_import_o_cap_module(self):
        top_level = set()
        for node in self.tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level.add((alias.asname or alias.name).split(".")[0])
        self.assertIn("json", top_level, "push_notification.py phai import json o cap module")

    def test_save_push_subscription_khong_import_json_ben_trong(self):
        func = _find_function(self.tree, "save_push_subscription")
        self.assertIsNotNone(func, "khong tim thay ham save_push_subscription")
        self.assertNotIn(
            "json",
            _imported_names_inside(func),
            "import json ben trong ham lam json thanh bien local -> UnboundLocalError",
        )

    def test_khong_ham_nao_trong_file_import_json_ben_trong(self):
        vi_pham = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and "json" in _imported_names_inside(node):
                vi_pham.append(node.name)
        self.assertEqual(vi_pham, [], f"cac ham sau import json ben trong: {vi_pham}")


if __name__ == "__main__":
    unittest.main()
