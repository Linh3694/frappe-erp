"""Kiem tra phan thuan logic cua nhom noi dung SIS."""

import unittest

from erp.common import sis_content_cdn


class TestKeyFromUrl(unittest.TestCase):
    def test_giu_duong_dan_tuong_doi_day_du(self):
        self.assertEqual(
            sis_content_cdn.key_from_url("Menu_Categories/SUON19.jpg"),
            "Menu_Categories/SUON19.jpg",
        )

    def test_giai_ma_percent_encoding(self):
        self.assertEqual(
            sis_content_cdn.key_from_url("News_Articles/a%20b.png"),
            "News_Articles/a b.png",
        )

    def test_chan_duong_dan_thoat_thu_muc(self):
        self.assertIsNone(sis_content_cdn.key_from_url("../../etc/passwd.png"))

    def test_chuoi_rong(self):
        self.assertIsNone(sis_content_cdn.key_from_url(""))


class TestEnabledGroups(unittest.TestCase):
    def test_doc_danh_sach_ngan_cach_bang_dau_phay(self):
        self.assertEqual(
            sis_content_cdn.parse_groups("news, menu"), ["news", "menu"]
        )

    def test_rong_thi_khong_nhom_nao(self):
        self.assertEqual(sis_content_cdn.parse_groups(""), [])
        self.assertEqual(sis_content_cdn.parse_groups(None), [])

    def test_bo_qua_ten_nhom_la(self):
        self.assertEqual(sis_content_cdn.parse_groups("news,khong-co"), ["news"])


if __name__ == "__main__":
    unittest.main()
