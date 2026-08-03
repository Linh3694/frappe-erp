"""Chan hoi quy: khong DDL trong duong di request, khong goi ham nang o cap module.

Prod 03/08/2026: `ALTER TABLE tabMobile Device Token ADD COLUMN IF NOT EXISTS`
chay ~575 lan moi 20-40 phut (co luc 61 lan/phut) vi dieu kien kiem tra dua vao
frappe.get_meta() (DocField) trong khi ban sua lai la ALTER TABLE (column SQL),
nen dieu kien mai mai dung -> vong lap vo han. Da kiem chung tren prod:
app_type/device_id/bundle_id deu meta=False, sql=True.
"""

import ast
import os
import unittest

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "api",
    "erp_sis",
    "mobile_push_notification.py",
)


def _doc():
    with open(_MODULE_PATH, encoding="utf-8") as fh:
        return fh.read()


def _ten_ham_duoc_goi(node):
    f = node.func
    return getattr(f, "id", None) or getattr(f, "attr", None)


class TestKhongVongLapDDL(unittest.TestCase):
    def setUp(self):
        self.src = _doc()
        self.tree = ast.parse(self.src)

    def test_khong_con_alter_table(self):
        """Chi xet string literal that su duoc thuc thi.

        Quet ca file bang chuoi se bat luon comment giai thich vi sao bo ALTER
        TABLE, nen dung AST: comment khong ton tai trong AST, chi con literal.
        """
        vi_pham = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "ALTER TABLE" in node.value.upper():
                    vi_pham.append(node.lineno)
        self.assertEqual(
            vi_pham,
            [],
            f"con string literal ALTER TABLE (se duoc thuc thi) o dong: {vi_pham}",
        )

    def test_khong_goi_ensure_o_cap_module(self):
        goi_cap_module = []
        for node in self.tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                ten = _ten_ham_duoc_goi(node.value)
                if ten:
                    goi_cap_module.append(ten)
        self.assertNotIn(
            "ensure_mobile_device_token_doctype",
            goi_cap_module,
            "goi o cap module -> chay lai moi lan worker nap module",
        )

    def test_ham_van_ton_tai_de_goi_thu_cong(self):
        ten_ham = [n.name for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)]
        self.assertIn("ensure_mobile_device_token_doctype", ten_ham)

    def test_khong_con_goi_ham_nao_o_cap_module(self):
        """Cap module chi duoc dinh nghia, khong duoc lam viec nang."""
        for node in self.tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                ten = _ten_ham_duoc_goi(node.value)
                self.assertIn(
                    ten,
                    (None, "frozenset"),
                    f"cap module goi {ten}() — se chay lai moi lan nap module",
                )


if __name__ == "__main__":
    unittest.main()
