"""Kiem tra thu thap URL va nen anh — phan khong can DB."""

import io
import unittest

from erp.common import sis_content_store


class TestExtractHtmlUrls(unittest.TestCase):
    def test_bat_anh_nhung_trong_the_img(self):
        html = '<p>xin chao</p><img src="/files/News_Articles/content/a.png">'
        self.assertEqual(
            sis_content_store.extract_html_urls(html),
            {"/files/News_Articles/content/a.png"},
        )

    def test_bat_nhieu_anh(self):
        html = '<img src="/files/a.jpg"><img src="/files/b.webp">'
        self.assertEqual(
            sis_content_store.extract_html_urls(html),
            {"/files/a.jpg", "/files/b.webp"},
        )

    def test_duong_dan_co_dau_cach(self):
        html = '<img src="/files/News_Articles/Lop 1A1.jpg">'
        self.assertEqual(
            sis_content_store.extract_html_urls(html),
            {"/files/News_Articles/Lop 1A1.jpg"},
        )

    def test_nhay_don(self):
        html = "<img src='/files/a.png'>"
        self.assertEqual(sis_content_store.extract_html_urls(html), {"/files/a.png"})

    def test_bo_qua_url_ngoai(self):
        # URL mien ngoai CO chua /files/ — truoc day regex quet tu do se nhiem allowlist
        html = '<img src="https://example.com/files/x.jpg">'
        self.assertEqual(sis_content_store.extract_html_urls(html), set())

    def test_html_rong(self):
        self.assertEqual(sis_content_store.extract_html_urls(""), set())
        self.assertEqual(sis_content_store.extract_html_urls(None), set())

    def test_markdown_anh_nhung(self):
        md = "![anh](/files/News_Articles/a.jpg)"
        self.assertEqual(
            sis_content_store.extract_html_urls(md),
            {"/files/News_Articles/a.jpg"},
        )

    def test_markdown_mo_ta_rong(self):
        self.assertEqual(
            sis_content_store.extract_html_urls("![](/files/b.png)"),
            {"/files/b.png"},
        )

    def test_markdown_duong_dan_co_dau_cach(self):
        md = "![x](/files/News_Articles/Lop 1A1.jpg)"
        self.assertEqual(
            sis_content_store.extract_html_urls(md),
            {"/files/News_Articles/Lop 1A1.jpg"},
        )

    def test_markdown_co_tieu_de(self):
        # Tieu de tuy chon sau path khong duoc dinh vao ket qua
        md = '![x](/files/c.webp "tieu de cua anh")'
        self.assertEqual(
            sis_content_store.extract_html_urls(md),
            {"/files/c.webp"},
        )

    def test_markdown_bo_qua_url_mien_ngoai(self):
        md = "![x](https://example.com/files/x.jpg)"
        self.assertEqual(sis_content_store.extract_html_urls(md), set())

    def test_van_ban_tran_khong_quet_files(self):
        html = "<p>doan van co /files/a.jpg</p>"
        self.assertEqual(sis_content_store.extract_html_urls(html), set())

    def test_tron_html_src_va_markdown(self):
        mixed = '<img src="/files/a.jpg"> va ![x](/files/b.png)'
        self.assertEqual(
            sis_content_store.extract_html_urls(mixed),
            {"/files/a.jpg", "/files/b.png"},
        )

    def test_markdown_mo_ta_chua_ngoac_vuong_dong(self):
        # FE dung ten file lam mo ta; ten co `]` khong duoc lam mat anh
        self.assertEqual(
            sis_content_store.extract_html_urls("![photo].jpg](/files/x.jpg)"),
            {"/files/x.jpg"},
        )
        self.assertEqual(
            sis_content_store.extract_html_urls("![a[b].png](/files/y.jpg)"),
            {"/files/y.jpg"},
        )

    def test_markdown_mo_ta_ngoac_long_nhau(self):
        self.assertEqual(
            sis_content_store.extract_html_urls("![foo [bar]](/files/nested.jpg)"),
            {"/files/nested.jpg"},
        )

    def test_markdown_tieu_de_nhay_don(self):
        md = "![x](/files/d.jpg 'tieu de')"
        self.assertEqual(sis_content_store.extract_html_urls(md), {"/files/d.jpg"})

    def test_markdown_khoang_trang_quanh_duong_dan(self):
        md = "![x]( /files/a.jpg )"
        self.assertEqual(sis_content_store.extract_html_urls(md), {"/files/a.jpg"})

    def test_markdown_hai_anh_lien_nhau_mot_dong(self):
        md = "![a](/files/a.jpg)![b](/files/b.png)"
        self.assertEqual(
            sis_content_store.extract_html_urls(md),
            {"/files/a.jpg", "/files/b.png"},
        )


class TestShrink(unittest.TestCase):
    def _jpeg(self, w, h):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (w, h), (120, 30, 30)).save(buf, format="JPEG", quality=95)
        return buf.getvalue()

    def test_resize_ve_canh_dai_toi_da(self):
        from PIL import Image

        out = sis_content_store.shrink(self._jpeg(3000, 2000), 1024)
        self.assertIsNotNone(out)
        self.assertEqual(Image.open(io.BytesIO(out)).size[0], 1024)

    def test_ban_nen_phai_nho_hon_it_nhat_10_phan_tram(self):
        data = self._jpeg(3000, 2000)
        out = sis_content_store.shrink(data, 1024)
        self.assertLess(len(out), len(data) * 0.9)

    def test_tra_none_khi_khong_giam_duoc_it_nhat_10_phan_tram(self):
        # PNG nhieu ngau nhien: da o kich thuoc dich nen khong resize, va
        # `optimize=True` khong the nen nhieu ngau nhien nho them 10%.
        import os

        from PIL import Image

        buf = io.BytesIO()
        Image.frombytes("RGB", (64, 64), os.urandom(64 * 64 * 3)).save(
            buf, format="PNG", optimize=True
        )
        self.assertIsNone(sis_content_store.shrink(buf.getvalue(), 1024))

    def test_giu_nguyen_dinh_dang(self):
        from PIL import Image

        out = sis_content_store.shrink(self._jpeg(3000, 2000), 1024)
        self.assertEqual(Image.open(io.BytesIO(out)).format, "JPEG")

    def test_du_lieu_hong_tra_none_chu_khong_throw(self):
        self.assertIsNone(sis_content_store.shrink(b"khong phai anh", 1024))


if __name__ == "__main__":
    unittest.main()
