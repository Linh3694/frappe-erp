"""Kiem tra phan thuan logic cua bo ky chung.

Ba rang buoc cua regex tung lam vo production nen moi rang buoc co mot test rieng.
"""

import unittest
from unittest import mock

from erp.common import cdn_sign, files_cdn, student_photo_cdn


def _domain(keys, prefix="student-photos", key_from_url=None):
    return {
        "name": "test",
        "prefix": prefix,
        "keys": set(keys),
        "key_from_url": key_from_url or student_photo_cdn.key_from_url,
    }


class TestFilesRegex(unittest.TestCase):
    def _match(self, text):
        return [m.group(0) for m in files_cdn.FILES_RE.finditer(text)]

    def test_bat_url_tuong_doi(self):
        self.assertEqual(self._match('"/files/WS123.jpg"'), ["/files/WS123.jpg"])

    def test_nuot_ca_origin(self):
        text = '"https://prod.sis.wellspring.edu.vn/files/WS123.jpg"'
        self.assertEqual(
            self._match(text),
            ["https://prod.sis.wellspring.edu.vn/files/WS123.jpg"],
        )

    def test_ten_file_duoc_chua_dau_cach(self):
        self.assertEqual(self._match('"/files/Lop 1A1.jpg"'), ["/files/Lop 1A1.jpg"])

    def test_van_ban_truoc_co_dau_cach_khong_bi_nuot(self):
        # Khoa \s trong lop ky tu cua nhom origin ((?:https?://[^"\\\s]*?)?).
        # Neu thieu \s, regex bat dau tu http dung truoc va nuot ca khoang trang
        # sang URL /files/ ke sau — match thanh mot chuoi dai sai.
        # URL tuong doi thuan ("... /files/...") khong khoa duoc: match bat dau
        # ngay tai /files/, van ban dung truoc khong bao gio vao nhom origin.
        text = (
            "https://evil.example/path with space "
            "https://prod.sis.wellspring.edu.vn/files/WS123.jpg"
        )
        self.assertEqual(
            self._match(text),
            ["https://prod.sis.wellspring.edu.vn/files/WS123.jpg"],
        )
        text2 = "see https://a.example/foo bar/files/WS123.jpg"
        self.assertEqual(self._match(text2), ["/files/WS123.jpg"])

    def test_bat_duoc_duong_dan_co_thu_muc_con(self):
        self.assertEqual(
            self._match('"/files/News_Articles/content/x.png"'),
            ["/files/News_Articles/content/x.png"],
        )

    def test_hai_url_lien_nhau_khong_bi_nuot_thanh_mot(self):
        text = '"/files/a.jpg","/files/b.jpg"'
        self.assertEqual(self._match(text), ["/files/a.jpg", "/files/b.jpg"])


class TestSignText(unittest.TestCase):
    def test_chi_thay_ten_nam_trong_allowlist(self):
        text = '{"a":"/files/WS1.jpg","b":"/files/KHONG.jpg"}'
        out = files_cdn.sign_text(
            text, [_domain(["WS1.jpg"])], signer=lambda p, expires=None: f"https://cdn{p}?e=1&s=x"
        )
        self.assertIn("https://cdn/student-photos/WS1.jpg?e=1&s=x", out)
        self.assertIn("/files/KHONG.jpg", out)

    def test_thay_ca_origin_khong_de_lai_hai_origin(self):
        text = '{"a":"https://prod.sis.wellspring.edu.vn/files/WS1.jpg"}'
        out = files_cdn.sign_text(
            text, [_domain(["WS1.jpg"])], signer=lambda p, expires=None: f"https://cdn{p}?e=1&s=x"
        )
        self.assertNotIn("prod.sis.wellspring.edu.vn", out)

    def test_domain_thu_hai_dung_khoa_duong_dan_day_du(self):
        import urllib.parse

        d = _domain(
            ["Menu_Categories/SUON19.jpg"],
            prefix="sis-content",
            key_from_url=lambda raw: urllib.parse.unquote(raw),
        )
        text = '{"a":"/files/Menu_Categories/SUON19.jpg","b":"/files/SUON19.jpg"}'
        out = files_cdn.sign_text(text, [d], signer=lambda p, expires=None: f"https://cdn{p}?e=1&s=x")
        self.assertIn("https://cdn/sis-content/Menu_Categories/SUON19.jpg", out)
        # Ban o goc `files/` la file KHAC, khong duoc ky lay
        self.assertIn('"b":"/files/SUON19.jpg"', out)


class TestStudentPhotoKhongTranhSisSubdir(unittest.TestCase):
    """Viec 3: nhom hoc sinh khong nhan path co thu muc con.

    Truoc day basename(`Menu_Categories/X.jpg`) = `X.jpg` trung allowlist hoc sinh
    thi ky nham sang kho student-photos. Anh hoc sinh o goc van ky binh thuong.
    """

    def test_path_co_thu_muc_con_bi_bo_qua(self):
        self.assertIsNone(student_photo_cdn.key_from_url("Menu_Categories/SameName.jpg"))
        self.assertIsNone(student_photo_cdn.key_from_url("Library/BookCover/a.jpg"))

    def test_anh_hoc_sinh_o_goc_van_nhan(self):
        self.assertEqual(student_photo_cdn.key_from_url("WS123.jpg"), "WS123.jpg")
        self.assertEqual(student_photo_cdn.key_from_url("Lop 1A1.jpg"), "Lop 1A1.jpg")

    def test_sis_subdir_trung_ten_khong_bi_hoc_sinh_ky(self):
        # Nhom hoc sinh dung TRUOC; neu con nhan basename thi se ky nham.
        student = _domain(["SameName.jpg"], prefix="student-photos")
        import urllib.parse

        sis = {
            "name": "sis-content",
            "prefix": "sis-content",
            "keys": {"Menu_Categories/SameName.jpg"},
            "key_from_url": lambda raw: urllib.parse.unquote(raw),
        }
        text = (
            '{"a":"/files/Menu_Categories/SameName.jpg",'
            '"b":"/files/WS123.jpg"}'
        )
        # Allowlist hoc sinh co SameName.jpg VA WS123.jpg
        student["keys"] = {"SameName.jpg", "WS123.jpg"}
        out = files_cdn.sign_text(
            text,
            [student, sis],
            signer=lambda p, expires=None: f"https://cdn{p}?e=1&s=x",
        )
        # SIS subdir di dung kho sis-content, khong bi student-photos nuot
        self.assertIn(
            "https://cdn/sis-content/Menu_Categories/SameName.jpg?e=1&s=x", out
        )
        self.assertNotIn("student-photos/SameName.jpg", out)
        # Anh hoc sinh o goc van ky nhu cu
        self.assertIn("https://cdn/student-photos/WS123.jpg?e=1&s=x", out)


class TestToFilesUrl(unittest.TestCase):
    """URL CDN da ky phai quy ve /files/ — tranh luu ?e=&s= vao DB."""

    def setUp(self):
        # reset cache regex/host giua cac test
        cdn_sign._media_text_re = None
        cdn_sign._media_text_re_hosts = None

    def test_signed_sis_content_ve_files(self):
        url = (
            "https://media.wellspring.edu.vn/sis-content/0582.webp"
            "?e=1785585600&s=yLaUddyQQvCqzVzTdULprw"
        )
        with mock.patch.object(cdn_sign, "load_conf", return_value=None):
            self.assertEqual(cdn_sign.to_files_url(url), "/files/0582.webp")

    def test_signed_menu_subdir(self):
        url = (
            "https://media.wellspring.edu.vn/sis-content/Menu_Categories/PHO19.jpg"
            "?e=1&s=x"
        )
        with mock.patch.object(cdn_sign, "load_conf", return_value=None):
            self.assertEqual(
                cdn_sign.to_files_url(url), "/files/Menu_Categories/PHO19.jpg"
            )

    def test_files_path_bo_query(self):
        self.assertEqual(
            cdn_sign.to_files_url("/files/0609.webp?e=1&s=x"), "/files/0609.webp"
        )

    def test_url_ngoai_giu_nguyen(self):
        url = "https://example.com/photo.jpg"
        self.assertEqual(cdn_sign.to_files_url(url), url)

    def test_media_urls_to_files_trong_html(self):
        html = (
            '<img src="https://media.wellspring.edu.vn/sis-content/a.webp?e=1&s=x">'
            '<p>ok</p>'
        )
        with mock.patch.object(cdn_sign, "load_conf", return_value=None):
            out = cdn_sign.media_urls_to_files(html)
        self.assertEqual(out, '<img src="/files/a.webp"><p>ok</p>')

    def test_sign_text_sau_khi_unsign_media(self):
        """Response con URL het han → unsign → ky lai chu ky moi."""
        import urllib.parse

        raw = (
            '{"cover":"https://media.wellspring.edu.vn/sis-content/0582.webp'
            '?e=1785585600&s=old"}'
        )
        with mock.patch.object(cdn_sign, "load_conf", return_value=None):
            normalized = cdn_sign.media_urls_to_files(raw)
        self.assertIn("/files/0582.webp", normalized)
        self.assertNotIn("media.wellspring", normalized)

        d = {
            "name": "sis-content",
            "prefix": "sis-content",
            "keys": {"0582.webp"},
            "key_from_url": lambda raw: urllib.parse.unquote(raw),
        }
        out = files_cdn.sign_text(
            normalized, [d], signer=lambda p, expires=None: f"https://cdn{p}?e=9&s=new"
        )
        self.assertIn("https://cdn/sis-content/0582.webp?e=9&s=new", out)


class TestSanitizeDoc(unittest.TestCase):
    def test_library_title_cover(self):
        doc = mock.Mock()
        doc.doctype = "SIS Library Title"
        doc.cover_image = (
            "https://media.wellspring.edu.vn/sis-content/0604.webp?e=1&s=x"
        )
        with mock.patch.object(cdn_sign, "load_conf", return_value=None):
            files_cdn.sanitize_doc(doc)
        self.assertEqual(doc.cover_image, "/files/0604.webp")


if __name__ == "__main__":
    unittest.main()
