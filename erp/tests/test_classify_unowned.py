"""Test phan thuan logic cua classify-unowned-files.py.

Script nam trong scripts/cdn/ (khong phai package) nen nap bang importlib.
Chi test phan KHONG can Frappe: nhan dang nhay cam, duoi file, da_bao_ve.

Vi sao dang test: phan loai sai theo huong "khong nhay cam" la im lang bo qua
file can bao ve — dung kieu loi ma hai lo hong truoc da mac phai.
"""

import importlib.util
import os
import unicodedata
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

    def test_anh_lop_mot_chu_so_dau(self):
        for ten in ["5A5.jpg", "9AB4.jpg", "1A1.jpg"]:
            self.assertIn("anh lop (ten = ma lop)",
                          classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

    def test_anh_lop_khoi_10_12_va_lop_khong_co_so_cuoi(self):
        # Mau ban dau `^\d?[A-Z]{1,3}\d{1,2}$` truot het nhung ten nay, nen 28 anh
        # lop ~2 MB van tra 200 sau dot niem 2026-07-30. Xem CDN-STATUS.md §18.
        for ten in ["10AB3.jpg", "12ADN1.jpg", "11AI.jpg", "6AD.jpg", "9MT.jpg"]:
            self.assertIn("anh lop (ten = ma lop)",
                          classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

    def test_ten_thuong_khong_bi_nhan_nham_la_anh_lop(self):
        # Noi mau thi phai chac no khong nuot ten binh thuong.
        # `8gqe.jpg` la anh minh hoa cua SIS Library Book Introduction — tung bi
        # nhan nham la ma lop vi mau dung re.I. Ma lop luon la CHU HOA.
        for ten in ["logo.png", "banner2026.jpg", "IMG_1868.png", "avatar.webp",
                    "ABCDE12.jpg", "123.jpg", "8gqe.jpg", "1a.jpg", "12q.jpg"]:
            self.assertNotIn("anh lop (ten = ma lop)",
                             classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

    def test_anh_nhan_vien_theo_ma_nhan_vien(self):
        # Do tren prod 2026-07-30: 319 file, 316 khop mot employee_code co that.
        for ten in ["WF01HC.jpg", "WF56KT.jpg", "WT17GE.jpg", "WT87PR.png",
                    "WT136PR.jpg", "WF02IT.JPG"]:
            self.assertIn("anh nhan vien (ten = ma nhan vien)",
                          classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

    def test_ten_khac_khong_bi_nhan_nham_la_anh_nhan_vien(self):
        # Ma nhan vien la CHU HOA; chu thuong toan la rac. Va `WS<so>` phai roi
        # vao nhan "ma hoc sinh" chu khong phai nhan nay.
        for ten in ["wf01hc.jpg", "WS11710352.JPG", "W01HC.jpg", "WFHC.jpg",
                    "WF1HC.jpg", "banner.jpg", "WF01HC.pdf"]:
            self.assertNotIn("anh nhan vien (ten = ma nhan vien)",
                             classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

    def test_anh_nhan_vien_co_hau_to_hex(self):
        # Frappe them hau to hex khi trung ten. Bo qua la sot 5 file tren prod.
        for ten in ["WT08EMa801b5.jpg", "WF03IT453d82.jpg", "WF02IT6a3ea2.png",
                    "WFT61PR.jpg"]:
            self.assertIn("anh nhan vien (ten = ma nhan vien)",
                          classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

    def test_anh_lop_co_tien_to_lop(self):
        for ten in ["Lớp 5A5.jpg", "Lớp 6AB4.jpg", "Lớp 3A5e06ddd.jpg", "lớp 1A2.png"]:
            self.assertIn("anh lop (tien to 'Lop')",
                          classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

    def test_ten_NFD_van_khop(self):
        # Ten tren dia o dang NFD (`ơ` + dau sac roi). Khong chuan hoa thi mau
        # "co dau" im lang khong khop gi — 27 anh lop lot luoi vi dung ly do nay.
        nfd = unicodedata.normalize("NFD", "Lớp 5A5.jpg")
        self.assertNotEqual(nfd, "Lớp 5A5.jpg", "chuoi thu phai that su la NFD")
        self.assertIn("anh lop (tien to 'Lop')",
                      classify.nhan_dang_nhay_cam(f"/files/{nfd}"))

    def test_bien_ban_ky_luat(self):
        for ten in ["130326_BB Khánh Chi 11ab3.jpg", "Khôi Minh_BB.jpg"]:
            self.assertIn("bien ban ky luat (BB)",
                          classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

    def test_BB_khong_bat_tran_lan(self):
        for ten in ["ABBA.jpg", "BBQ.png", "bb.jpg", "clubbing.jpg"]:
            self.assertNotIn("bien ban ky luat (BB)",
                             classify.nhan_dang_nhay_cam(f"/files/{ten}"), ten)

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
        # `Lớp 1A1.jpg` TUNG nam trong danh sach nay — khang dinh sai, va chinh no
        # hop thuc hoa diem mu de 27 anh lop tra 200 den 2026-07-30. Anh chup ca
        # lop la du lieu tre em, khong phai anh trang tri.
        for ten in ["banner-tet.png", "logo.svg", "menu-thu-hai.jpg", "book-cover.jpg"]:
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
