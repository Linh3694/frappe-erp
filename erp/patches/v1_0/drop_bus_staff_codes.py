# -*- coding: utf-8 -*-
"""Bo `driver_code` / `monitor_code`, lay CCCD lam dinh danh duy nhat cua nhan su Bus. Idempotent.

Truoc day moi nguoi co ba truong unique (ma noi bo, CCCD, so dien thoai). Nay chi con
CCCD la khoa nghiep vu; ma noi bo bo han khoi man hinh, form va nhap Excel.

DIEM QUAN TRONG — app Monitor: tai khoan Frappe cua giam sat duoc dat ten theo
`{monitor_code}@busmonitor.wellspring.edu.vn`, va moi API cua app tach nguoc email nay
ra de tim giam sat. Doi dinh danh sang CCCD nen phai DOI TEN luon cac User da co,
neu khong giam sat dang dung app se khong tra ra ban ghi nao sau khi deploy.

Patch chay o [post_model_sync]: Frappe KHONG drop cot khi field bi xoa khoi JSON nen
cot cu van doc duoc bang `frappe.db.sql` raw (`frappe.get_all` se bao loi vi fieldname
khong con trong meta). Cot cu duoc giu lai mot release lam duong lui.
"""

import frappe

_MONITOR_DT = "SIS Bus Monitor"
_DRIVER_DT = "SIS Bus Driver"
_MONITOR_EMAIL_DOMAIN = "@busmonitor.wellspring.edu.vn"


def _log(msg: str) -> None:
    """In ra log migrate — de ops thay ket qua ngay khi chay bench migrate."""
    print(f"[drop_bus_staff_codes] {msg}")
    frappe.logger().info(f"[drop_bus_staff_codes] {msg}")


def _rename_monitor_users() -> None:
    """Doi email tai khoan app Monitor tu ma giam sat sang CCCD."""
    if not frappe.db.has_column(_MONITOR_DT, "monitor_code"):
        _log("Bang giam sat khong con cot monitor_code — bo qua buoc doi ten User")
        return

    rows = frappe.db.sql(
        f"""
        SELECT TRIM(`monitor_code`) AS code, TRIM(`citizen_id`) AS citizen_id
        FROM `tab{_MONITOR_DT}`
        WHERE IFNULL(TRIM(`monitor_code`), '') <> ''
          AND IFNULL(TRIM(`citizen_id`), '') <> ''
        """,
        as_dict=True,
    )

    renamed = 0
    skipped = 0
    for row in rows:
        old_email = f"{row.code}{_MONITOR_EMAIL_DOMAIN}"
        new_email = f"{row.citizen_id}{_MONITOR_EMAIL_DOMAIN}"
        if old_email == new_email:
            continue
        if not frappe.db.exists("User", old_email):
            continue
        if frappe.db.exists("User", new_email):
            # Da co tai khoan theo CCCD (chay lai patch, hoac tao tay) — khong ghi de
            _log(f"Bo qua {old_email}: {new_email} da ton tai")
            skipped += 1
            continue
        try:
            frappe.rename_doc("User", old_email, new_email, force=True, show_alert=False)
            renamed += 1
        except Exception as e:  # noqa: BLE001 — mot tai khoan hong khong duoc chan ca migrate
            _log(f"LOI khi doi ten {old_email} -> {new_email}: {e}")
            skipped += 1

    _log(f"Tai khoan app Monitor: doi ten {renamed}, bo qua {skipped}")


def _drop_unique_index(doctype: str, column: str) -> None:
    """Drop UNIQUE index mo coi con lai tren cot da bo.

    BAT BUOC: cot cu van giu UNIQUE index. Ban ghi moi khong set gia tri nua => MariaDB
    dung DEFAULT cua cot (thuong la ''), ban ghi thu hai se loi "Duplicate entry ''".
    """
    try:
        idx = frappe.db.sql(f"SHOW INDEX FROM `tab{doctype}` WHERE Key_name = %s", (column,))
        if not idx:
            _log(f"{doctype}: khong con index `{column}` — bo qua")
            return
        # sql_ddl commit truoc khi chay DDL — `frappe.db.sql` se chan neu transaction
        # hien tai da co lenh ghi (buoc doi ten User o tren).
        frappe.db.sql_ddl(f"ALTER TABLE `tab{doctype}` DROP INDEX `{column}`")
        _log(f"{doctype}: da drop UNIQUE index `{column}`")
    except Exception as e:  # noqa: BLE001
        _log(f"{doctype}: LOI khi drop index `{column}`: {e}")


def execute():
    if not frappe.db.table_exists(_MONITOR_DT) or not frappe.db.table_exists(_DRIVER_DT):
        _log(f"Bo qua — chua co bang {_MONITOR_DT} / {_DRIVER_DT}")
        return

    _rename_monitor_users()

    _drop_unique_index(_MONITOR_DT, "monitor_code")
    _drop_unique_index(_DRIVER_DT, "driver_code")

    frappe.db.commit()
    _log("Xong")
