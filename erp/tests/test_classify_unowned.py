"""Test phan thuan logic cua classify-unowned-files.py.

Script nam trong scripts/cdn/ (khong phai package) nen nap bang importlib.
Chi test phan KHONG can Frappe: nhan dang nhay cam, duoi file, da_bao_ve.

Vi sao dang test: phan loai sai theo huong "khong nhay cam" la im lang bo qua
file can bao ve — dung kieu loi ma hai lo hong truoc da mac phai.
"""

import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(_HERE, "..", "..", "scripts", "cdn", "classify-unowned-files.py")

_spec = importlib.util.spec_from_file_location("classify_unowned", _SCRIPT)
classify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(classify)


class TestNhanDangNhayCam(unittest.TestCase):
    def test_ma_hoc_sinh(self):
        self.assertIn("ma hoc sinh", classify.nhan_dang_nhay_cam("/files/WS11420471.jpg"))
        self.assertIn("ma hoc sinh", classify.nhan_dang_nhay_cam("/files/ws12407002_v2.jpg"))

    def test_ma_ngan_khong_bi_nhan_nham(self):
        # WS + 3 so la ma lop/phong, khong phai ma hoc sinh 8 so
        self.assertEqual(classify.nhan_dang_nhay_cam("/files/WS123.jpg"), [])

    def test_giay_to_tuy_than(self):
        for ten in ["CCCD_NguyenVanA.pdf", "cmnd-scan.jpg", "ho_chieu_2026.pdf", "can-cuoc.png"]:
            self.assertTrue(classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

    def test_ket_qua_hoc_tap(self):
        for ten in ["hoc_ba_4A6.pdf", "Report Card 2026.pdf", "bang-diem.xlsx", "transcript.pdf"]:
            self.assertTrue(classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

    def test_suc_khoe_va_ho_tich(self):
        self.assertTrue(classify.nhan_dang_nhay_cam("/files/health_check_2026.pdf"))
        self.assertTrue(classify.nhan_dang_nhay_cam("/files/khai_sinh_ABC.jpg"))

    def test_anh_thuong_khong_bao_dong_gia(self):
        for ten in ["banner-tet.png", "logo.svg", "Lớp 1A1.jpg", "menu-thu-hai.jpg", "book-cover.jpg"]:
            self.assertEqual(classify.nhan_dang_nhay_cam(f"/files/{ten}"), [], ten)

    def test_nhieu_dau_hieu_cung_luc(self):
        ly_do = classify.nhan_dang_nhay_cam("/files/WS11420471_hoc_ba.pdf")
        self.assertIn("ma hoc sinh", ly_do)
        self.assertIn("ket qua hoc tap", ly_do)

    def test_chi_xet_ten_file_khong_xet_thu_muc(self):
        # thu muc ten "hocba" khong duoc bien file anh thuong thanh nhay cam
        self.assertEqual(classify.nhan_dang_nhay_cam("/files/hoc_ba/banner.png"), [])


class TestDaBaoVe(unittest.TestCase):
    def test_avatar_va_hoc_bong_duoc_loai(self):
        self.assertTrue(classify.da_bao_ve("/files/Avatar/abc.png"))
        self.assertTrue(classify.da_bao_ve("/files/Home/Scholarship/x.jpg"))

    def test_file_thuong_khong_bi_loai(self):
        self.assertFalse(classify.da_bao_ve("/files/banner.png"))


class TestDuoi(unittest.TestCase):
    def test_lay_duoi_chuan_hoa_chu_thuong(self):
        self.assertEqual(classify.duoi("a.JPG"), ".jpg")
        self.assertEqual(classify.duoi("a.tar.gz"), ".gz")

    def test_khong_co_duoi(self):
        self.assertEqual(classify.duoi("README"), "")
        # dau cham dau ten khong tinh la duoi
        self.assertEqual(classify.duoi(".gitignore"), "")


class TestPhanNhomDungBucket(unittest.TestCase):
    """Duoi file quyet dinh nhom mo coi — anh va tai lieu tach rieng vi muc do
    rui ro khac han: mot PDF mo coi 3 MB dang ngo hon mot PNG banner."""

    def test_duoi_tai_lieu_va_anh_khong_giao_nhau(self):
        self.assertFalse(classify.DUOI_ANH & classify.DUOI_TAILIEU)

    def test_pdf_la_tai_lieu(self):
        self.assertIn(".pdf", classify.DUOI_TAILIEU)

    def test_heic_duoc_tinh_la_anh(self):
        # anh iPhone — bo sot thi roi vao "khac_mo_coi" va bi xem nhe
        self.assertIn(".heic", classify.DUOI_ANH)


if __name__ == "__main__":
    unittest.main()
