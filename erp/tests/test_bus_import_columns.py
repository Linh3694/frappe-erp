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
        self.assertEqual(values["gender"], "Male")
        self.assertEqual(values["status"], "Active")

    def test_thieu_gia_tri_bat_buoc(self):
        spec = bic.BUS_IMPORT_SPECS["driver"]
        values, err = bic.parse_row(spec, self._row(**{"CCCD": ""}), 5)
        self.assertIsNone(values)
        self.assertIn("Dòng 5", err)
        self.assertIn("CCCD", err)

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


class TestParseRowRoute(unittest.TestCase):
    def _row(self, **override):
        row = {
            "Tên tuyến": "Ecopark 1",
            "Mã xe": "12",
            "Biển số": "29B-173.96",
            "CCCD tài xế": "001234567890",
            "CCCD giám sát 1": "001234567891",
            "CCCD giám sát 2": "",
            "Trạng thái": "",
        }
        row.update(override)
        return row

    def test_dong_hop_le_giam_sat_2_de_trong(self):
        spec = bic.BUS_IMPORT_SPECS["route"]
        values, err = bic.parse_row(spec, self._row(), 2)
        self.assertIsNone(err)
        self.assertEqual(values["route_name"], "Ecopark 1")
        self.assertEqual(values["vehicle_code"], "12")
        self.assertEqual(values["monitor2_citizen_id"], "")
        self.assertEqual(values["status"], "Active")

    def test_thieu_bien_so(self):
        spec = bic.BUS_IMPORT_SPECS["route"]
        values, err = bic.parse_row(spec, self._row(**{"Biển số": ""}), 4)
        self.assertIsNone(values)
        self.assertIn("Biển số", err)


class TestRouteStudentWeeklyConfig(unittest.TestCase):
    """Cấu hình chung cả tuần: lượt suy từ cột địa điểm nào được điền."""

    def test_dien_ca_hai_cot_thi_di_ca_hai_luot(self):
        trips, err = bic.weekly_trip_types(
            {"pickup_location": "12 Lê Lợi", "drop_off_location": "12 Lê Lợi"}, 2
        )
        self.assertIsNone(err)
        self.assertEqual(trips, ("Đón", "Trả"))

    def test_chi_dien_diem_don_thi_chi_co_luot_don(self):
        trips, err = bic.weekly_trip_types(
            {"pickup_location": "12 Lê Lợi", "drop_off_location": "  "}, 2
        )
        self.assertIsNone(err)
        self.assertEqual(trips, ("Đón",))

    def test_chi_dien_diem_tra_thi_chi_co_luot_tra(self):
        trips, err = bic.weekly_trip_types({"drop_off_location": "12 Lê Lợi"}, 2)
        self.assertIsNone(err)
        self.assertEqual(trips, ("Trả",))

    def test_de_trong_ca_hai_thi_bao_loi(self):
        trips, err = bic.weekly_trip_types({}, 9)
        self.assertIsNone(trips)
        self.assertIn("Dòng 9", err)

    def test_tra_tuyen_theo_ma_tuyen_khong_theo_ten(self):
        spec = bic.BUS_IMPORT_SPECS["route_student"]
        values, err = bic.parse_row(
            spec,
            {"Mã tuyến": "12", "Mã học sinh": "WS12345", "Thứ tự đón": "1", "Điểm đón": "12 Lê Lợi"},
            2,
        )
        self.assertIsNone(err)
        self.assertEqual(values["vehicle_code"], "12")
        self.assertNotIn("route_name", values)

    def test_thieu_ma_tuyen_thi_bao_loi(self):
        spec = bic.BUS_IMPORT_SPECS["route_student"]
        values, err = bic.parse_row(spec, {"Mã học sinh": "WS12345", "Thứ tự đón": "1"}, 4)
        self.assertIsNone(values)
        self.assertIn("Mã tuyến", err)

    def test_tuan_hoc_la_thu_2_den_thu_6(self):
        self.assertEqual(bic.BUS_WEEKDAYS, ("Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6"))

    def test_thu_tu_don_phai_la_so_duong(self):
        self.assertEqual(bic.parse_pickup_order("3", 2), (3, None))
        self.assertEqual(bic.parse_pickup_order(" 4 ", 2), (4, None))
        order, err = bic.parse_pickup_order("abc", 5)
        self.assertIsNone(order)
        self.assertIn("Thứ tự đón", err)
        order, err = bic.parse_pickup_order("0", 6)
        self.assertIsNone(order)
        self.assertIn("Dòng 6", err)


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
            "Duplicate entry 'full_name' for key 'citizen_id'", spec, 8
        )
        self.assertIn("Dòng 8", msg)
        self.assertIn("CCCD", msg)
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
