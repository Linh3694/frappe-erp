# -*- coding: utf-8 -*-
"""Chặn hồi quy: 4 endpoint CRUD học sinh bus không được gọi CompreFace.

Dùng AST đọc mã nguồn thay vì import module, vì import cần cả môi trường
Frappe. Test này chỉ soi cấu trúc cú pháp nên chạy được bằng pytest trần.
"""

import ast
import os
import unittest

DUONG_DAN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "api",
    "erp_sis",
    "bus_student.py",
)

CAC_ENDPOINT_CRUD = [
    "create_bus_student",
    "create_bus_student_from_sis",
    "update_bus_student",
    "delete_bus_student",
]


def _doc_cay_ast():
    with open(DUONG_DAN, encoding="utf-8") as f:
        nguon = f.read()
    return nguon, ast.parse(nguon)


def _tim_ham(cay, ten):
    for node in ast.walk(cay):
        if isinstance(node, ast.FunctionDef) and node.name == ten:
            return node
    return None


class TestBusStudentKhongConCompreface(unittest.TestCase):
    def test_bon_endpoint_van_ton_tai(self):
        """Gỡ CompreFace không được làm mất endpoint nghiệp vụ."""
        _, cay = _doc_cay_ast()
        for ten in CAC_ENDPOINT_CRUD:
            self.assertIsNotNone(
                _tim_ham(cay, ten),
                f"Endpoint {ten} bị mất — luồng thêm/sửa/xóa học sinh bus sẽ hỏng",
            )

    def test_bon_endpoint_khong_nhac_compreface(self):
        """Không còn tên CompreFace trong thân 4 endpoint."""
        nguon, cay = _doc_cay_ast()
        for ten in CAC_ENDPOINT_CRUD:
            ham = _tim_ham(cay, ten)
            than = ast.get_source_segment(nguon, ham) or ""
            self.assertNotIn(
                "compreface",
                than.lower(),
                f"{ten} vẫn còn tham chiếu CompreFace",
            )

    def test_bon_endpoint_khong_enqueue_job(self):
        """Không còn frappe.enqueue trong 4 endpoint.

        Trước đây mỗi lần tạo/sửa/xóa học sinh đều đẩy một job sync lên
        CompreFace. Gỡ rồi thì không còn job nào cần đẩy.
        """
        nguon, cay = _doc_cay_ast()
        for ten in CAC_ENDPOINT_CRUD:
            ham = _tim_ham(cay, ten)
            for node in ast.walk(ham):
                if isinstance(node, ast.Call):
                    goi = ast.get_source_segment(nguon, node.func) or ""
                    self.assertNotEqual(
                        goi.replace(" ", ""),
                        "frappe.enqueue",
                        f"{ten} vẫn enqueue job (dòng {node.lineno})",
                    )

    def test_bon_endpoint_khong_con_time_sleep(self):
        """Không còn time.sleep chặn worker gunicorn trong 4 endpoint.

        create_bus_student_from_sis từng có hai lời gọi time.sleep(2) ngay
        trong đường đi của web request để chờ CompreFace xử lý ảnh. Đó là
        cùng loại lỗi với sự cố hiệu năng 03/08/2026.
        """
        nguon, cay = _doc_cay_ast()
        for ten in CAC_ENDPOINT_CRUD:
            ham = _tim_ham(cay, ten)
            for node in ast.walk(ham):
                if isinstance(node, ast.Call):
                    goi = (ast.get_source_segment(nguon, node.func) or "").replace(" ", "")
                    self.assertNotIn(
                        "sleep",
                        goi,
                        f"{ten} còn lời gọi sleep ở dòng {node.lineno}",
                    )


    def test_toan_module_khong_con_compreface(self):
        """Cả module không còn dấu vết CompreFace, kể cả import."""
        nguon, _ = _doc_cay_ast()
        self.assertNotIn("compreface", nguon.lower())

    def test_toan_module_khong_con_sleep(self):
        """Không còn lời gọi sleep nào trong module.

        Bốn lời gọi time.sleep(2) cũ nằm trong create_bus_student_from_sis
        và sync_bus_student_to_compreface. Cả hai nhánh đã bị gỡ.
        """
        nguon, cay = _doc_cay_ast()
        for node in ast.walk(cay):
            if isinstance(node, ast.Call):
                goi = (ast.get_source_segment(nguon, node.func) or "").replace(" ", "")
                self.assertNotIn(
                    "sleep",
                    goi,
                    f"Còn lời gọi sleep ở dòng {node.lineno}",
                )

    def test_con_dung_muoi_ham_nghiep_vu(self):
        """Module còn đúng 10 hàm, không thừa không thiếu."""
        _, cay = _doc_cay_ast()
        ten = [n.name for n in cay.body if isinstance(n, ast.FunctionDef)]
        self.assertEqual(
            sorted(ten),
            sorted([
                "get_all_bus_students",
                "get_bus_student",
                "create_bus_student",
                "create_bus_student_from_sis",
                "update_bus_student",
                "delete_bus_student",
                "get_available_classes",
                "get_available_routes",
                "get_students_for_bus_selection",
                "migrate_route_students_to_bus_students",
            ]),
        )


if __name__ == "__main__":
    unittest.main()
