"""Test lop thuan cua cau hinh cot import Excel Bus — chay duoc bang python3, khong can frappe."""

import importlib.util
import os
import unittest

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "api",
    "erp_sis",
    "bus_import_columns.py",
)
_spec = importlib.util.spec_from_file_location("bus_import_columns", _MODULE_PATH)
bic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bic)


class TestNormalizeCell(unittest.TestCase):
    def test_bo_khoang_trang_thua(self):
        self.assertEqual(bic.normalize_cell("  Nguyen Van A  "), "Nguyen Van A")

    def test_o_trong_thanh_chuoi_rong(self):
        self.assertEqual(bic.normalize_cell(None), "")
        self.assertEqual(bic.normalize_cell("nan"), "")

    def test_so_nguyen_khong_co_duoi_thap_phan(self):
        self.assertEqual(bic.normalize_cell(1234567890.0), "1234567890")
        self.assertEqual(bic.normalize_cell(42), "42")


class TestMissingHeaders(unittest.TestCase):
    def test_du_cot_bat_buoc(self):
        spec = bic.BUS_IMPORT_SPECS["transportation"]
        headers = ["Biển số", "Loại xe", "Trạng thái"]
        self.assertEqual(bic.missing_headers(spec, headers), [])

    def test_thieu_cot_bat_buoc_tra_ve_ten_cot(self):
        spec = bic.BUS_IMPORT_SPECS["transportation"]
        headers = ["Trạng thái"]
        self.assertEqual(bic.missing_headers(spec, headers), ["Biển số", "Loại xe"])

    def test_cot_khong_bat_buoc_thieu_van_hop_le(self):
        spec = bic.BUS_IMPORT_SPECS["pickup_point"]
        headers = ["Tên điểm đón", "Loại điểm"]
        self.assertEqual(bic.missing_headers(spec, headers), [])


class TestParseRowDriver(unittest.TestCase):
    def _row(self, **override):
        row = {
            "Họ tên": "Nguyễn Văn A",
            "Mã tài xế": "TX001",
            "Giới tính": "Nam",
            "CCCD": "001234567890",
            "Số điện thoại": "0901234567",
            "Nhà thầu": "Công ty X",
            "Địa chỉ": "12 Lê Lợi",
            "Trạng thái": "Đang hoạt động",
        }
        row.update(override)
        return row

    def test_dong_hop_le(self):
        spec = bic.BUS_IMPORT_SPECS["driver"]
        values, err = bic.parse_row(spec, self._row(), 2)
        self.assertIsNone(err)
        self.assertEqual(values["full_name"], "Nguyễn Văn A")
        self.assertEqual(values["driver_code"], "TX001")
        self.assertEqual(values["gender"], "Male")
        self.assertEqual(values["status"], "Active")

    def test_thieu_gia_tri_bat_buoc(self):
        spec = bic.BUS_IMPORT_SPECS["driver"]
        values, err = bic.parse_row(spec, self._row(**{"Mã tài xế": ""}), 5)
        self.assertIsNone(values)
        self.assertIn("Dòng 5", err)
        self.assertIn("Mã tài xế", err)

    def test_gioi_tinh_khong_hop_le(self):
        spec = bic.BUS_IMPORT_SPECS["driver"]
        values, err = bic.parse_row(spec, self._row(**{"Giới tính": "Nam nữ"}), 7)
        self.assertIsNone(values)
        self.assertIn("Dòng 7", err)
        self.assertIn("Giới tính", err)

    def test_gia_tri_tieng_anh_va_khong_dau_deu_nhan(self):
        spec = bic.BUS_IMPORT_SPECS["driver"]
        values, _ = bic.parse_row(spec, self._row(**{"Giới tính": "female"}), 2)
        self.assertEqual(values["gender"], "Female")
        values, _ = bic.parse_row(spec, self._row(**{"Trạng thái": "ngung hoat dong"}), 2)
        self.assertEqual(values["status"], "Inactive")

    def test_trang_thai_de_trong_lay_mac_dinh(self):
        spec = bic.BUS_IMPORT_SPECS["driver"]
        values, err = bic.parse_row(spec, self._row(**{"Trạng thái": ""}), 2)
        self.assertIsNone(err)
        self.assertEqual(values["status"], "Active")


class TestParseRowOtherSpecs(unittest.TestCase):
    def test_diem_don_loai_diem(self):
        spec = bic.BUS_IMPORT_SPECS["pickup_point"]
        values, err = bic.parse_row(
            spec,
            {"Tên điểm đón": "Ngã tư Sở", "Loại điểm": "đón", "Mô tả": ""},
            3,
        )
        self.assertIsNone(err)
        self.assertEqual(values["point_type"], "Đón")
        self.assertEqual(values["point_name"], "Ngã tư Sở")
        self.assertEqual(values["description"], "")

    def test_diem_don_loai_diem_sai(self):
        spec = bic.BUS_IMPORT_SPECS["pickup_point"]
        values, err = bic.parse_row(spec, {"Tên điểm đón": "A", "Loại điểm": "đi"}, 4)
        self.assertIsNone(values)
        self.assertIn("Loại điểm", err)

    def test_hoc_sinh_chi_can_ma_hoc_sinh(self):
        spec = bic.BUS_IMPORT_SPECS["student"]
        values, err = bic.parse_row(spec, {"Mã học sinh": "WS12345", "Tên tuyến": ""}, 2)
        self.assertIsNone(err)
        self.assertEqual(values["student_code"], "WS12345")
        self.assertEqual(values["route_name"], "")
        self.assertEqual(values["status"], "Active")


class TestFriendlyUniqueError(unittest.TestCase):
    def test_nhan_ra_truong_bi_trung(self):
        spec = bic.BUS_IMPORT_SPECS["driver"]
        msg = bic.friendly_unique_error(
            "Duplicate entry '0901234567' for key 'phone_number'", spec, 6
        )
        self.assertIn("Dòng 6", msg)
        self.assertIn("Số điện thoại", msg)

    def test_loi_khac_tra_ve_none(self):
        spec = bic.BUS_IMPORT_SPECS["driver"]
        self.assertIsNone(bic.friendly_unique_error("Some other error", spec, 6))

    def test_gia_tri_trung_chua_ten_truong_khac_khong_bao_nham(self):
        """Giá trị trùng chứa tên trường khác — vẫn báo đúng cột theo tên khóa."""
        spec = bic.BUS_IMPORT_SPECS["driver"]
        msg = bic.friendly_unique_error(
            "Duplicate entry 'full_name' for key 'driver_code'", spec, 8
        )
        self.assertIn("Dòng 8", msg)
        self.assertIn("Mã tài xế", msg)
        self.assertNotIn("Họ tên", msg)

    def test_ten_khoa_co_tien_to_bang(self):
        spec = bic.BUS_IMPORT_SPECS["driver"]
        msg = bic.friendly_unique_error(
            "Duplicate entry 'X' for key 'tabSIS Bus Driver.phone_number'", spec, 9
        )
        self.assertIn("Dòng 9", msg)
        self.assertIn("Số điện thoại", msg)


if __name__ == "__main__":
    unittest.main()
