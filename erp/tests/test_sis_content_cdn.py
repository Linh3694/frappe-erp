"""Kiem tra phan thuan logic cua nhom noi dung SIS."""

import unittest

from erp.common import files_cdn, sis_content_cdn


def _fake_signer(path, expires=None):
    # `expires` bat buoc trong chu ky de khop files_cdn.sign_text -> signer(...)
    return f"https://cdn{path}?e=1&s=x"


def _sis_domain(keys):
    return {
        "name": "sis-content",
        "prefix": sis_content_cdn.PREFIX,
        "keys": set(keys),
        "key_from_url": sis_content_cdn.key_from_url,
    }


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


class TestKeyFromCollectedUrl(unittest.TestCase):
    """Phong ve khi collect_urls (module khac) tra ve URL khong dung dang."""

    def test_url_dung_dang(self):
        self.assertEqual(
            sis_content_cdn.key_from_collected_url("/files/Menu_Categories/SUON19.jpg"),
            "Menu_Categories/SUON19.jpg",
        )

    def test_bo_qua_url_tuyet_doi(self):
        # Cat cung se sinh khoa rac bat dau bang `/` hoac host — allowlist sai am tham.
        self.assertIsNone(
            sis_content_cdn.key_from_collected_url(
                "https://prod.sis.wellspring.edu.vn/files/Menu_Categories/SUON19.jpg"
            )
        )

    def test_bo_qua_thieu_dau_gach_cheo_dau(self):
        # `files/Menu...`[len("/files/"):] -> `enu_Categories/...` — khoa rac.
        self.assertIsNone(
            sis_content_cdn.key_from_collected_url("files/Menu_Categories/SUON19.jpg")
        )

    def test_bo_qua_none_va_rong(self):
        self.assertIsNone(sis_content_cdn.key_from_collected_url(None))
        self.assertIsNone(sis_content_cdn.key_from_collected_url(""))


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


class TestSignTextKhoaDayDu(unittest.TestCase):
    """Tich hop qua files_cdn.sign_text + key_from_url that cua sis_content_cdn.

    Rui ro lon nhat: hai anh trung basename o thu muc khac nhau bi dam vao nhau
    neu khoa chi la basename. Dot nen 2026-07-29 da dinh dung loi nay.
    """

    def test_hai_anh_trung_ten_khac_thu_muc_khong_dam_nhau(self):
        # Allowlist chi co ban trong Menu_Categories — ban o goc phai giu nguyen.
        domain = _sis_domain(["Menu_Categories/SUON19.jpg"])
        text = (
            '{"a":"/files/Menu_Categories/SUON19.jpg",'
            '"b":"/files/SUON19.jpg"}'
        )
        out = files_cdn.sign_text(text, [domain], signer=_fake_signer)
        self.assertIn(
            "https://cdn/sis-content/Menu_Categories/SUON19.jpg?e=1&s=x", out
        )
        self.assertIn('"b":"/files/SUON19.jpg"', out)

    def test_keys_rong_khong_ky_url_nao(self):
        # Bao ve: ky anh chua co tren CDN se vo anh dang hien thi tot.
        domain = _sis_domain([])
        text = (
            '{"a":"/files/Menu_Categories/SUON19.jpg",'
            '"b":"/files/SUON19.jpg"}'
        )
        out = files_cdn.sign_text(text, [domain], signer=_fake_signer)
        self.assertEqual(out, text)


if __name__ == "__main__":
    unittest.main()
