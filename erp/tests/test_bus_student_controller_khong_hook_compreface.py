# -*- coding: utf-8 -*-
"""Chặn hồi quy: controller SIS Bus Student không còn hook CompreFace.

Trước đây after_insert/on_update/after_delete đều enqueue job đẩy ảnh học
sinh lên CompreFace. Gỡ rồi thì controller chỉ còn validate.
"""

import ast
import os
import unittest

DUONG_DAN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "sis",
    "doctype",
    "sis_bus_student",
    "sis_bus_student.py",
)

HOOK_PHAI_BIEN_MAT = ["after_insert", "on_update", "after_delete"]
METHOD_PHAI_GIU = ["validate", "validate_unique_fields", "validate_references_exist"]


def _doc():
    with open(DUONG_DAN, encoding="utf-8") as f:
        nguon = f.read()
    return nguon, ast.parse(nguon)


def _class_controller(cay):
    for node in cay.body:
        if isinstance(node, ast.ClassDef) and node.name == "SISBusStudent":
            return node
    return None


class TestControllerKhongHookCompreface(unittest.TestCase):
    def test_khong_con_chu_compreface(self):
        nguon, _ = _doc()
        self.assertNotIn("compreface", nguon.lower())

    def test_khong_con_hook_document(self):
        """Không còn after_insert/on_update/after_delete."""
        _, cay = _doc()
        lop = _class_controller(cay)
        self.assertIsNotNone(lop, "Không tìm thấy class SISBusStudent")
        ten_method = [
            n.name for n in lop.body if isinstance(n, ast.FunctionDef)
        ]
        for hook in HOOK_PHAI_BIEN_MAT:
            self.assertNotIn(
                hook,
                ten_method,
                f"Hook {hook} vẫn còn — nó chỉ tồn tại để sync CompreFace",
            )

    def test_van_con_validate(self):
        """Gỡ CompreFace không được làm mất validate nghiệp vụ."""
        _, cay = _doc()
        lop = _class_controller(cay)
        ten_method = [
            n.name for n in lop.body if isinstance(n, ast.FunctionDef)
        ]
        for method in METHOD_PHAI_GIU:
            self.assertIn(
                method,
                ten_method,
                f"Method {method} bị xóa oan — validate trùng mã HS sẽ mất",
            )

    def test_khong_con_ham_cap_module(self):
        """Hai background job cấp module phải biến mất."""
        _, cay = _doc()
        ham_module = [
            n.name for n in cay.body if isinstance(n, ast.FunctionDef)
        ]
        self.assertEqual(
            ham_module,
            [],
            f"Còn hàm cấp module: {ham_module}",
        )


if __name__ == "__main__":
    unittest.main()
