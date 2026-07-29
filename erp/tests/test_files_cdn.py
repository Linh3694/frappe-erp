"""Kiem tra phan thuan logic cua bo ky chung.

Ba rang buoc cua regex tung lam vo production nen moi rang buoc co mot test rieng.
"""

import unittest

from erp.common import files_cdn


def _domain(keys, prefix="student-photos", key_from_url=None):
    import os
    import urllib.parse

    return {
        "name": "test",
        "prefix": prefix,
        "keys": set(keys),
        "key_from_url": key_from_url
        or (lambda raw: os.path.basename(urllib.parse.unquote(raw))),
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


if __name__ == "__main__":
    unittest.main()
