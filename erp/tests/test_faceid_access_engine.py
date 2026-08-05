"""Test phan thuan logic cua engine Access Group (khong can Frappe runtime).

Nap module bang importlib voi frappe gia lap: cac ham duoi day chi dung
frappe.utils.today/now nen stub la du.

Vi sao dang test: hop khung gio sai theo huong "rong hon" la mo cong cho HS ra
ngoai gio, con sai theo huong "hep hon" la khoa HS ngoai cong — ca hai deu la
su co van hanh, khong phai bug im lang.
"""

import datetime
import importlib.util
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.join(_HERE, "..", "api", "faceid", "access_engine.py")


def _load_engine():
    if "frappe" not in sys.modules:
        frappe = types.ModuleType("frappe")
        frappe.utils = types.ModuleType("frappe.utils")
        frappe.utils.now = lambda: "2026-08-05 00:00:00"
        frappe.utils.today = lambda: "2026-08-05"
        sys.modules["frappe"] = frappe
        sys.modules["frappe.utils"] = frappe.utils
    spec = importlib.util.spec_from_file_location("faceid_access_engine", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


engine = _load_engine()


class TestChuanHoaGio(unittest.TestCase):
    def test_timedelta_gio_mot_chu_so(self):
        # Time field cua Frappe la timedelta: str(timedelta(hours=6)) = '6:00:00'.
        # Cach cu str(...)[:5] cho ra '6:00:' lam controller parse loi -> ca sang
        # 6h (dung khung gio cong 2 dang dung) khong day duoc xuong may.
        self.assertEqual(engine.hhmm(datetime.timedelta(hours=6)), "06:00")
        self.assertEqual(engine.hhmm(datetime.timedelta(hours=7, minutes=30)), "07:30")

    def test_cac_kieu_dau_vao_khac(self):
        self.assertEqual(engine.hhmm("07:05:00"), "07:05")
        self.assertEqual(engine.hhmm(datetime.time(16, 30)), "16:30")
        self.assertEqual(engine.hhmm(None), "00:00")


class TestHopKhungGio(unittest.TestCase):
    def test_gop_doan_chong_lan_va_lien_ke(self):
        periods = [
            {"weekday": 1, "start_time": "06:00", "end_time": "07:00"},
            {"weekday": 1, "start_time": "06:30", "end_time": "07:30"},
            {"weekday": 1, "start_time": "07:30", "end_time": "08:00"},
        ]
        self.assertEqual(
            engine.merge_periods(periods),
            [{"weekday": 1, "start_time": "06:00", "end_time": "08:00"}],
        )

    def test_nhom_chong_nhau_cong_don_chu_khong_loai_tru(self):
        # HS thuoc ca nhom khoi (T2-T6) lan nhom hoc thu 7 -> phai giu ca hai,
        # khong duoc de nhom nao "thang" va nuot khung gio cua nhom kia.
        khoi = [
            {"weekday": d, "start_time": "06:00", "end_time": "07:00"} for d in range(1, 6)
        ]
        thu_bay = [{"weekday": 6, "start_time": "07:00", "end_time": "08:00"}]
        hop = engine.merge_periods(khoi + thu_bay)
        self.assertEqual(len(hop), 6)
        self.assertEqual([p["weekday"] for p in hop], [1, 2, 3, 4, 5, 6])

    def test_loai_doan_nguoc_hoac_rong(self):
        self.assertEqual(
            engine.merge_periods([{"weekday": 1, "start_time": "08:00", "end_time": "07:00"}]),
            [],
        )


class TestChuKyLich(unittest.TestCase):
    def test_bat_bien_theo_thu_tu_khai_bao(self):
        a = [
            {"weekday": 1, "start_time": "06:00", "end_time": "07:00"},
            {"weekday": 6, "start_time": "07:00", "end_time": "08:00"},
        ]
        self.assertEqual(engine.signature_of(a), engine.signature_of(list(reversed(a))))

    def test_lich_khac_nhau_thi_chu_ky_khac_nhau(self):
        a = [{"weekday": 1, "start_time": "06:00", "end_time": "07:00"}]
        b = [{"weekday": 1, "start_time": "06:00", "end_time": "07:30"}]
        self.assertNotEqual(engine.signature_of(a), engine.signature_of(b))

    def test_rong_la_24_7(self):
        self.assertEqual(engine.signature_of([]), engine.ALLDAY_SIGNATURE)


class TestHieuLuc(unittest.TestCase):
    def test_hop_hieu_luc_none_la_khong_gioi_han(self):
        self.assertIsNone(engine._union_from(None, "2026-09-01"))
        self.assertIsNone(engine._union_to("2027-05-31", None))

    def test_hop_lay_bien_rong_nhat(self):
        self.assertEqual(engine._union_from("2026-09-01", "2026-08-01"), "2026-08-01")
        self.assertEqual(engine._union_to("2026-12-31", "2027-05-31"), "2027-05-31")

    def test_giao_voi_hieu_luc_person_lay_bien_hep_nhat(self):
        self.assertEqual(engine._intersect_from("2026-08-01", "2026-09-01"), "2026-09-01")
        self.assertEqual(engine._intersect_to("2027-05-31", "2026-12-31"), "2026-12-31")


class TestGioiHanPhanCung(unittest.TestCase):
    def test_qua_8_doan_mot_ngay_bi_chan(self):
        periods = [
            {"weekday": 1, "start_time": f"{6 + i:02d}:00", "end_time": f"{6 + i:02d}:30"}
            for i in range(9)
        ]
        with self.assertRaises(engine.AccessConfigError):
            engine.validate_periods_fit(periods)

    def test_dung_8_doan_van_qua(self):
        periods = [
            {"weekday": 1, "start_time": f"{6 + i:02d}:00", "end_time": f"{6 + i:02d}:30"}
            for i in range(8)
        ]
        engine.validate_periods_fit(periods)  # khong raise


if __name__ == "__main__":
    unittest.main()
