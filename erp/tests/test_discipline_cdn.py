"""Kiem tra phan thuan logic cua nhom anh ho so ky luat (CDN-STATUS.md §7c).

Ten file dung trong test lay tu du lieu THAT tren prod (do 2026-07-30), gom ca
hai ho: UUID va `<ngay>_BB <ten hoc sinh> <lop>.jpg`. Ho thu hai co dau cach va
tieng Viet co dau — dung hai thu tung lam vo production o §7b.
"""

import unittest

from erp.common import cdn_sign, discipline_cdn, discipline_store, files_cdn, student_photo_cdn

# Ten that tren prod, giu nguyen de test bam vao dung hinh dang du lieu that
UUID_NAME = "04FF7FA9-EAE9-42B6-8375-2AA32145B15E.jpg"
VN_NAME = "070526_BB Minh Quân 10AB3.jpg"


def _fake_signer(path, expires=None):
    # `expires` bat buoc trong chu ky de khop files_cdn.sign_text -> signer(...)
    return f"https://cdn{path}?e=1&s=x"


def _disc_domain(keys):
    return {
        "name": "discipline",
        "prefix": discipline_cdn.PREFIX,
        "keys": set(keys),
        "key_from_url": discipline_cdn.key_from_url,
    }


def _photo_domain(keys):
    return {
        "name": "student-photos",
        "prefix": student_photo_cdn.PREFIX,
        "keys": set(keys),
        "key_from_url": student_photo_cdn.key_from_url,
    }


class TestKeyFromUrl(unittest.TestCase):
    def test_ten_uuid(self):
        self.assertEqual(discipline_cdn.key_from_url(UUID_NAME), UUID_NAME)

    def test_ten_co_dau_cach_va_tieng_viet(self):
        self.assertEqual(discipline_cdn.key_from_url(VN_NAME), VN_NAME)

    def test_giai_ma_percent_encoding(self):
        self.assertEqual(
            discipline_cdn.key_from_url("070526_BB%20Minh%20Qu%C3%A2n%2010AB3.jpg"),
            VN_NAME,
        )

    def test_tu_choi_duong_dan_co_thu_muc_con(self):
        # Da do tren prod: ca 68 URL deu o goc files/. Nhan them thu muc con se
        # cho phep cuop khoa cua nhom noi dung SIS.
        self.assertIsNone(discipline_cdn.key_from_url("Menu_Categories/SUON19.jpg"))

    def test_chan_duong_dan_thoat_thu_muc(self):
        self.assertIsNone(discipline_cdn.key_from_url("../../etc/passwd.jpg"))

    def test_chuoi_rong(self):
        self.assertIsNone(discipline_cdn.key_from_url(""))

    def test_none(self):
        self.assertIsNone(discipline_cdn.key_from_url(None))


class TestSignText(unittest.TestCase):
    """Ky o ranh gioi response — dung bo may chung cua files_cdn."""

    def test_ky_url_tuong_doi(self):
        out = files_cdn.sign_text(
            f'{{"image": "/files/{UUID_NAME}"}}',
            [_disc_domain([UUID_NAME])],
            signer=_fake_signer,
        )
        self.assertIn(f"https://cdn/discipline/{UUID_NAME}?e=1&s=x", out)
        self.assertNotIn("/files/", out)

    def test_ky_url_co_dau_cach_va_tieng_viet(self):
        # Rang buoc #2 cua FILES_RE: ten file DUOC chua dau cach. Sua nham cho
        # nay tung lam anh lop khong duoc ky (§7b).
        out = files_cdn.sign_text(
            f'{{"image": "/files/{VN_NAME}"}}',
            [_disc_domain([VN_NAME])],
            signer=_fake_signer,
        )
        self.assertIn(f"https://cdn/discipline/{VN_NAME}?e=1&s=x", out)

    def test_ky_url_day_du_nuot_ca_origin(self):
        # frappe.utils.get_url() sinh URL day du. Regex phai nuot ca origin, neu
        # khong ket qua thanh `https://prod...https://cdn...` — URL vo (§7b).
        raw = f'{{"image": "https://prod.sis.wellspring.edu.vn/files/{UUID_NAME}"}}'
        out = files_cdn.sign_text(raw, [_disc_domain([UUID_NAME])], signer=_fake_signer)
        self.assertNotIn("prod.sis.wellspring.edu.vn", out)
        self.assertIn(f"https://cdn/discipline/{UUID_NAME}", out)

    def test_khong_ky_khoa_ngoai_allowlist(self):
        # Ky bua mot URL chua co tren CDN se lam vo anh dang chay tot.
        raw = f'{{"image": "/files/{UUID_NAME}"}}'
        out = files_cdn.sign_text(raw, [_disc_domain(["khac.jpg"])], signer=_fake_signer)
        self.assertEqual(out, raw)

    def test_ky_nhieu_anh_trong_mot_response(self):
        raw = f'{{"proof_images": [{{"image": "/files/{UUID_NAME}"}}, ' \
              f'{{"image": "/files/{VN_NAME}"}}]}}'
        out = files_cdn.sign_text(
            raw, [_disc_domain([UUID_NAME, VN_NAME])], signer=_fake_signer
        )
        self.assertNotIn("/files/", out)
        self.assertEqual(out.count("https://cdn/discipline/"), 2)


class TestTranhKhoaGiuaCacNhom(unittest.TestCase):
    """Do tren prod 2026-07-30: giao RONG. Test giu cho ket luan do khong am tham
    doi khi ai do sua `key_from_url` cua mot nhom."""

    def test_anh_hoc_sinh_duyet_truoc_thi_thang(self):
        # Neu mot ngay nao do hai nhom trung ten, nhom duyet TRUOC lay khoa.
        # Test nay ghi lai hanh vi do de no khong doi trong im lang.
        raw = '{"x": "/files/CHUNG.jpg"}'
        out = files_cdn.sign_text(
            raw,
            [_photo_domain(["CHUNG.jpg"]), _disc_domain(["CHUNG.jpg"])],
            signer=_fake_signer,
        )
        self.assertIn("/student-photos/CHUNG.jpg", out)
        self.assertNotIn("/discipline/", out)

    def test_ky_luat_van_duoc_ky_khi_khong_trung(self):
        raw = f'{{"x": "/files/{UUID_NAME}"}}'
        out = files_cdn.sign_text(
            raw,
            [_photo_domain(["WS11420471.jpg"]), _disc_domain([UUID_NAME])],
            signer=_fake_signer,
        )
        self.assertIn(f"/discipline/{UUID_NAME}", out)

    def test_domain_ky_luat_duoc_dang_ky_sau_cung(self):
        # Duyet sau cung => chi thua chu khong bao gio cuop khoa cua nhom khac.
        self.assertEqual(files_cdn._DOMAIN_SOURCES[-1], "erp.common.discipline_cdn")


class TestCoBatTat(unittest.TestCase):
    def setUp(self):
        self._conf = cdn_sign._conf_cache

    def tearDown(self):
        cdn_sign._conf_cache = self._conf

    def _set_conf(self, **extra):
        conf = {
            "CDN_LINK_SECRET": "x",
            "CDN_PUBLIC_URL": "https://cdn",
            "CDN_ENABLED": "true",
        }
        conf.update(extra)
        cdn_sign._conf_cache = conf

    def test_mac_dinh_tat(self):
        self._set_conf()
        self.assertFalse(discipline_cdn.is_enabled())

    def test_bat(self):
        self._set_conf(CDN_DISCIPLINE_ENABLED="true")
        self.assertTrue(discipline_cdn.is_enabled())

    def test_tat_cdn_tong_thi_tat_theo(self):
        self._set_conf(CDN_DISCIPLINE_ENABLED="true", CDN_ENABLED="false")
        self.assertFalse(discipline_cdn.is_enabled())

    def test_khong_bat_thi_khong_co_domain(self):
        self._set_conf()
        self.assertIsNone(discipline_cdn.get_domain())


class TestNameOf(unittest.TestCase):
    def test_url_hop_le(self):
        self.assertEqual(discipline_store._name_of(f"/files/{UUID_NAME}"), UUID_NAME)

    def test_giai_ma_percent_encoding(self):
        self.assertEqual(
            discipline_store._name_of("/files/070526_BB%20Minh%20Qu%C3%A2n%2010AB3.jpg"),
            VN_NAME,
        )

    def test_tu_choi_url_ngoai(self):
        self.assertIsNone(discipline_store._name_of("https://example.com/a.jpg"))

    def test_tu_choi_private(self):
        self.assertIsNone(discipline_store._name_of("/private/files/a.jpg"))

    def test_tu_choi_thoat_thu_muc(self):
        self.assertIsNone(discipline_store._name_of("/files/../../etc/passwd"))

    def test_tu_choi_thu_muc_con(self):
        # Signer tu choi path co `/`, nen store cung phai tu choi — neu khong,
        # store day len khoa `discipline/SUON19.jpg` ma khong ai ky duoc.
        self.assertIsNone(discipline_store._name_of("/files/Menu_Categories/SUON19.jpg"))

    def test_khoa_khop_signer(self):
        url = f"/files/{VN_NAME}"
        self.assertEqual(
            discipline_store._name_of(url),
            discipline_cdn.key_from_url(url[len("/files/"):]),
        )

    def test_tu_choi_gia_tri_khong_phai_chuoi(self):
        self.assertIsNone(discipline_store._name_of(None))
        self.assertIsNone(discipline_store._name_of(123))


class _Row:
    def __init__(self, image):
        self.image = image


class _Doc:
    def __init__(self, images):
        self.proof_images = [_Row(i) for i in images]


class TestImagesOf(unittest.TestCase):
    def test_lay_du_anh(self):
        doc = _Doc([f"/files/{UUID_NAME}", f"/files/{VN_NAME}"])
        self.assertEqual(len(discipline_store._images_of(doc)), 2)

    def test_bo_dong_rong(self):
        doc = _Doc([f"/files/{UUID_NAME}", "", None])
        self.assertEqual(discipline_store._images_of(doc), [f"/files/{UUID_NAME}"])

    def test_ho_so_khong_co_anh(self):
        self.assertEqual(discipline_store._images_of(_Doc([])), [])

    def test_doc_thieu_han_truong(self):
        class Trong:
            pass

        self.assertEqual(discipline_store._images_of(Trong()), [])


if __name__ == "__main__":
    unittest.main()
