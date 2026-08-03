# -*- coding: utf-8 -*-
"""Chuyen `vehicle_code` (Ma xe) tu SIS Bus Transportation sang SIS Bus Route. Idempotent.

Ma xe von la nhan gan theo TUYEN CHAY trong mot nam hoc, khong phai thuoc tinh co huu
cua chiec xe. Sau thay doi nay man Quan ly xe chi con Bien so / Loai xe / Trang thai,
con ma xe nhap tay o form Tuyen duong (unique trong cung campus + nam hoc).

Patch chay o [post_model_sync] vi:
  - Truoc doctype sync thi cot `tabSIS Bus Route.vehicle_code` chua ton tai.
  - Frappe KHONG drop cot khi field bi xoa khoi JSON, nen cot cu
    `tabSIS Bus Transportation.vehicle_code` van con nguyen du lieu de doc.
Phai doc bang `frappe.db.sql` raw — `frappe.get_all` / `db.get_value` se bao loi
vi fieldname khong con trong meta.

Chi ghi len tuyen dang de TRONG `vehicle_code` => chay lai lan 2 la no-op.
Khong drop cot cu trong patch nay — giu mot release lam duong lui.
"""

import frappe

_VEHICLE_DT = "SIS Bus Transportation"
_ROUTE_DT = "SIS Bus Route"


def _log(msg: str) -> None:
    """In ra log migrate — de ops thay ket qua backfill ngay khi chay bench migrate."""
    print(f"[backfill_bus_route_vehicle_code] {msg}")
    frappe.logger().info(f"[backfill_bus_route_vehicle_code] {msg}")


def _backfill() -> int:
    """Gan route.vehicle_code = ma cua xe dang link. Tra ve so tuyen da gan."""
    where = """
        IFNULL(TRIM(r.`vehicle_code`), '') = ''
        AND IFNULL(TRIM(v.`vehicle_code`), '') <> ''
    """
    n = int(frappe.db.sql(f"""
        SELECT COUNT(*)
        FROM `tab{_ROUTE_DT}` r
        INNER JOIN `tab{_VEHICLE_DT}` v ON r.`vehicle_id` = v.`name`
        WHERE {where}
    """)[0][0])
    if not n:
        return 0

    frappe.db.sql(f"""
        UPDATE `tab{_ROUTE_DT}` r
        INNER JOIN `tab{_VEHICLE_DT}` v ON r.`vehicle_id` = v.`name`
        SET r.`vehicle_code` = TRIM(v.`vehicle_code`)
        WHERE {where}
    """)
    return n


def _log_duplicates() -> None:
    """Canh bao ma xe trung trong cung campus + nam hoc.

    Hien khong co rang buoc nao chan nhieu tuyen cung link mot `vehicle_id`, nen backfill
    co the sinh ra ma trung. CHI LOG, khong throw — throw se chan ca `bench migrate`.
    Controller chi validate luc save nen du lieu cu van nam im duoc, ops sua tay.
    """
    rows = frappe.db.sql(f"""
        SELECT
            IFNULL(`campus_id`, '') AS campus_id,
            IFNULL(`school_year_id`, '') AS school_year_id,
            LOWER(TRIM(`vehicle_code`)) AS code,
            COUNT(*) AS n,
            GROUP_CONCAT(`route_name` SEPARATOR ', ') AS routes
        FROM `tab{_ROUTE_DT}`
        WHERE IFNULL(TRIM(`vehicle_code`), '') <> ''
        GROUP BY 1, 2, 3
        HAVING n > 1
    """, as_dict=True)

    if not rows:
        return

    _log(f"CANH BAO — {len(rows)} nhom ma xe bi trung, ops can sua tay:")
    for row in rows:
        _log(f"  campus={row.campus_id} nam_hoc={row.school_year_id} "
             f"ma='{row.code}' ({row.n} tuyen): {row.routes}")


def _drop_legacy_unique_index() -> None:
    """Drop UNIQUE index mo coi tren `tabSIS Bus Transportation.vehicle_code`.

    BAT BUOC: cot cu van con va van giu UNIQUE index. Xe tao moi khong set gia tri nua
    => MariaDB dung DEFAULT cua cot (thuong la ''), xe thu hai se loi
    "Duplicate entry '' for key 'vehicle_code'" => chuc nang Them xe chet tren production.
    """
    try:
        idx = frappe.db.sql(
            f"SHOW INDEX FROM `tab{_VEHICLE_DT}` WHERE Key_name = 'vehicle_code'"
        )
        if not idx:
            _log("Khong con index `vehicle_code` tren bang xe — bo qua")
            return
        frappe.db.sql(f"ALTER TABLE `tab{_VEHICLE_DT}` DROP INDEX `vehicle_code`")
        _log("Da drop UNIQUE index `vehicle_code` tren bang xe")
    except Exception as e:
        _log(f"LOI khi drop index `vehicle_code`: {e}")


def execute():
    if not frappe.db.table_exists(_ROUTE_DT) or not frappe.db.table_exists(_VEHICLE_DT):
        _log(f"Bo qua — chua co bang {_ROUTE_DT} / {_VEHICLE_DT}")
        return

    if not frappe.db.has_column(_ROUTE_DT, "vehicle_code"):
        _log(f"Bo qua — {_ROUTE_DT} chua co cot vehicle_code (chay bench migrate truoc)")
        return

    if not frappe.db.has_column(_VEHICLE_DT, "vehicle_code"):
        _log(f"{_VEHICLE_DT} khong con cot vehicle_code — bo qua backfill")
        _drop_legacy_unique_index()
        frappe.db.commit()
        return

    updated = _backfill()
    _log(f"Da gan ma xe cho {updated} tuyen")

    _log_duplicates()
    _drop_legacy_unique_index()

    frappe.db.commit()

    remaining = int(frappe.db.sql(f"""
        SELECT COUNT(*) FROM `tab{_ROUTE_DT}`
        WHERE IFNULL(TRIM(`vehicle_code`), '') = ''
    """)[0][0])
    _log(f"Xong: {updated} tuyen da gan, {remaining} tuyen van chua co ma xe")
