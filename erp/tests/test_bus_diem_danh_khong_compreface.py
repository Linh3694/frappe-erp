# -*- coding: utf-8 -*-
"""Chặn hồi quy cho module điểm danh chuyến xe bus.

Module tên là face_recognition.py nhưng sau khi gỡ dịch vụ nhận diện khuôn mặt
nó chỉ còn phần điểm danh thủ công. Test này giữ hai điều cùng lúc: không còn
dấu vết dịch vụ đó, và hai endpoint mà offline.py phụ thuộc vẫn còn nguyên.
"""

import ast
import os
import unittest

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUONG_DAN = os.path.join(GOC, "api", "bus_application", "face_recognition.py")
DUONG_DAN_OFFLINE = os.path.join(GOC, "api", "bus_application", "offline.py")

HAM_PHAI_GIU = ["check_student_in_trip", "mark_student_absent", "_update_trip_statistics"]
HAM_PHAI_XOA = [
    "recognize_student_face",
    "verify_and_checkin",
    "test_compreface",
    "check_trip_students_in_compreface",
]


def _doc(duong_dan):
    with open(duong_dan, encoding="utf-8") as f:
        nguon = f.read()
    return nguon, ast.parse(nguon)


class TestDiemDanhKhongCompreface(unittest.TestCase):
    def test_khong_con_chu_compreface(self):
        nguon, _ = _doc(DUONG_DAN)
        self.assertNotIn("compreface", nguon.lower())

    def test_bon_ham_nhan_dien_da_bi_xoa(self):
        _, cay = _doc(DUONG_DAN)
        ten = [n.name for n in cay.body if isinstance(n, ast.FunctionDef)]
        for h in HAM_PHAI_XOA:
            self.assertNotIn(h, ten, f"{h} vẫn còn")

    def test_ba_ham_diem_danh_van_con(self):
        """offline.py import hai trong ba hàm này — xóa là hỏng đồng bộ offline."""
        _, cay = _doc(DUONG_DAN)
        ten = [n.name for n in cay.body if isinstance(n, ast.FunctionDef)]
        for h in HAM_PHAI_GIU:
            self.assertIn(h, ten, f"{h} bị xóa oan — luồng điểm danh sẽ hỏng")

    def test_offline_van_import_duoc(self):
        """Kiểm tra offline.py vẫn trỏ vào tên hàm còn tồn tại."""
        _, cay_fr = _doc(DUONG_DAN)
        ten_co_san = {n.name for n in cay_fr.body if isinstance(n, ast.FunctionDef)}

        nguon_off, cay_off = _doc(DUONG_DAN_OFFLINE)
        for node in ast.walk(cay_off):
            if isinstance(node, ast.ImportFrom) and node.module and "face_recognition" in node.module:
                for alias in node.names:
                    self.assertIn(
                        alias.name,
                        ten_co_san,
                        f"offline.py:{node.lineno} import {alias.name} nhưng hàm đó không còn",
                    )

    def test_khong_con_import_service(self):
        _, cay = _doc(DUONG_DAN)
        for node in ast.walk(cay):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(
                    "compreFace_service",
                    node.module,
                    f"Còn import service ở dòng {node.lineno}",
                )


if __name__ == "__main__":
    unittest.main()
