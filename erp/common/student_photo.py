"""Quy tac chon anh hoc sinh — mot nguon su that duy nhat.

Van de da xay ra tren production (phat hien 2026-07-29, 1.338 hoc sinh bi sai)
--------------------------------------------------------------------------
Anh hoc sinh duoc luu theo tung nam hoc. Khi nam hoc moi vua mo va hoc sinh
chua co anh cua nam do, he thong phai lay anh cua nam GAN NHAT co anh.

Cac truy van cu dung:

    ORDER BY CASE WHEN school_year_id = %(sy)s THEN 0 ELSE 1 END,
             upload_date DESC, creation DESC

tuc lay `upload_date` lam dai dien cho "nam hoc moi nhat". Hai thu do KHONG
dong bien:

    2024-2025  start 2024-07-01   anh upload 2025-12-23   <- nhap bo sung MUON
    2025-2026  start 2025-07-01   anh upload 2025-09/10
    2026-2027  start 2026-07-01   dang mo, chua co anh

Anh nam 2024-2025 duoc nhap bo sung vao thang 12/2025, tuc SAU anh nam
2025-2026. Nen `upload_date DESC` chon dung anh CU NHAT — sai ca ve nghiep vu
lan ve truc quan (anh tre em cach day 2 nam).

Ten nam hoc cung khong sap theo thoi gian (`SIS_SCHOOL_YEAR-4370719` la
2024-2025 con `-00014` la 2025-2026), nen sap theo `school_year_id` cung sai.

Chi co `tabSIS School Year.start_date` moi la thu tu thoi gian dung.

Cach dung
---------
Truy van moi nen goi `get_photo_url()` / `get_photo_urls()`. Truy van SQL tho
san co thi thay khoi ORDER BY bang `PHOTO_ORDER_BY` va them `PHOTO_JOIN`.
"""

import frappe

# LEFT JOIN chu khong phai JOIN: anh co school_year_id khong khop ban ghi nam hoc
# nao (du lieu cu / da xoa nam hoc) van phai lay duoc, chi bi xep cuoi.
PHOTO_JOIN = "LEFT JOIN `tabSIS School Year` sy ON sy.name = p.school_year_id"

# Dung khi CO nam hoc uu tien. Tham so nam hoc phai ten la `sy_pref`.
# MySQL xep NULL cuoi cung voi DESC, nen anh mo coi (start_date NULL) tu dong
# thanh lua chon cuoi — dung y muon.
PHOTO_ORDER_BY = """
    ORDER BY
        CASE WHEN p.school_year_id = %(sy_pref)s THEN 0 ELSE 1 END,
        sy.start_date DESC,
        p.upload_date DESC,
        p.creation DESC
"""

# Dung khi KHONG co nam hoc uu tien — chi can anh moi nhat theo nam hoc.
PHOTO_ORDER_BY_NO_PREF = """
    ORDER BY
        sy.start_date DESC,
        p.upload_date DESC,
        p.creation DESC
"""

# Dang SUBQUERY, dung cho cac truy van SQL tho san co.
#
# Vi sao khong them JOIN vao tung query: nhieu query khong dat bi danh cho
# `tabSIS Photo`, co query da JOIN san bang khac — them JOIN se phai sua ca menh
# de SELECT/WHERE va rat de sai. Subquery tuong quan chi can chen DUNG MOT DONG
# vao ORDER BY, khong dung toi phan con lai cua query.
#
# Chi phi: mot lookup theo khoa chinh cho moi dong duoc sap xep. So anh moi hoc
# sinh chi vai ban ghi nen khong dang ke.
SCHOOL_YEAR_START_SUBQUERY = (
    "(SELECT sy.start_date FROM `tabSIS School Year` sy "
    "WHERE sy.name = school_year_id) DESC"
)


def get_current_school_year():
    return frappe.db.get_value("SIS School Year", {"is_enable": 1}, "name")


def get_photo_url(student_id, school_year_id=None):
    """Anh cua mot hoc sinh.

    Uu tien `school_year_id`; neu khong co anh nam do thi lay nam hoc gan nhat
    co anh (theo `start_date`, khong phai theo ngay upload).
    """
    if not student_id:
        return None
    rows = frappe.db.sql(
        f"""
        SELECT p.photo
        FROM `tabSIS Photo` p
        {PHOTO_JOIN}
        WHERE p.student_id = %(sid)s AND p.type = 'student' AND p.status = 'Active'
        {PHOTO_ORDER_BY}
        LIMIT 1
        """,
        {"sid": student_id, "sy_pref": school_year_id or ""},
        as_dict=True,
    )
    return rows[0].photo if rows and rows[0].photo else None


def get_photo_urls(student_ids, school_year_id=None):
    """Ban batch cua `get_photo_url` — tra ve {student_id: photo}.

    Dung mot query cho ca danh sach; voi moi hoc sinh lay dong dau tien theo
    dung thu tu uu tien o tren.
    """
    ids = [s for s in (student_ids or []) if s]
    if not ids:
        return {}
    rows = frappe.db.sql(
        f"""
        SELECT p.student_id, p.photo
        FROM `tabSIS Photo` p
        {PHOTO_JOIN}
        WHERE p.student_id IN %(ids)s AND p.type = 'student' AND p.status = 'Active'
        {PHOTO_ORDER_BY}
        """,
        {"ids": tuple(ids), "sy_pref": school_year_id or ""},
        as_dict=True,
    )
    out = {}
    for r in rows:
        # Dong dau tien cua moi hoc sinh la dong dung theo thu tu uu tien
        if r.student_id not in out and r.photo:
            out[r.student_id] = r.photo
    return out
