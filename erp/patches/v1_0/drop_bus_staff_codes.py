# -*- coding: utf-8 -*-
"""Bo `driver_code` / `monitor_code`, lay CCCD lam dinh danh duy nhat cua nhan su Bus. Idempotent.

Truoc day moi nguoi co ba truong unique (ma noi bo, CCCD, so dien thoai). Nay chi con
CCCD la khoa nghiep vu; ma noi bo bo han khoi man hinh, form va nhap Excel.

DIEM QUAN TRONG — app Monitor: tai khoan Frappe cua giam sat duoc dat ten theo
`{monitor_code}@busmonitor.wellspring.edu.vn`, va moi API cua app tach nguoc email nay
ra de tim giam sat. Doi dinh danh sang CCCD nen phai co tai khoan theo CCCD, neu khong
giam sat dang dung app se khong tra ra ban ghi nao sau khi deploy.

Patch TAO TAI KHOAN MOI thay vi doi ten tai khoan cu — xem chu thich o
`_migrate_monitor_users` de biet vi sao (`rename_doc` tren User mat 5-15 phut/tai khoan).

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


def _copy_roles(old_email: str, new_user) -> None:
    """Sao chep danh sach role tu tai khoan cu sang tai khoan moi."""
    roles = frappe.get_all("Has Role", filters={"parent": old_email}, pluck="role")
    for role in roles:
        new_user.append("roles", {"role": role})


def _migrate_monitor_users() -> None:
    """Tao tai khoan app Monitor theo CCCD, vo hieu hoa tai khoan cu theo ma giam sat.

    KHONG dung `frappe.rename_doc`: `User.after_rename` quet MOI bang trong DB roi
    `UPDATE ... SET owner/modified_by`, ma hai cot nay khong co index — moi tai khoan
    mat 5-15 phut tren prod (rieng `tabVersion` da 40-210 giay moi cau). Tao tai khoan
    moi la O(1); lich su `owner`/`modified_by` van tro ve tai khoan cu, vo hai.
    """
    if not frappe.db.has_column(_MONITOR_DT, "monitor_code"):
        _log("Bang giam sat khong con cot monitor_code — bo qua buoc chuyen tai khoan")
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

    created = 0
    skipped = 0
    for row in rows:
        old_email = f"{row.code}{_MONITOR_EMAIL_DOMAIN}"
        new_email = f"{row.citizen_id}{_MONITOR_EMAIL_DOMAIN}"
        if old_email == new_email:
            continue
        if frappe.db.exists("User", new_email):
            # Da co tai khoan theo CCCD (chay lai patch, hoac tao tay) — khong ghi de
            continue
        if not frappe.db.exists("User", old_email):
            continue

        try:
            old_user = frappe.get_doc("User", old_email)
            new_user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": new_email,
                    "first_name": old_user.first_name or old_user.full_name or new_email,
                    "user_type": old_user.user_type or "Website User",
                    "enabled": 1,
                    "send_welcome_email": 0,
                }
            )
            _copy_roles(old_email, new_user)
            new_user.flags.no_welcome_mail = True
            new_user.insert(ignore_permissions=True)

            # Vo hieu hoa tai khoan cu — dung set_value de khong keo theo hook cua User
            frappe.db.set_value("User", old_email, "enabled", 0, update_modified=False)
            created += 1
        except Exception as e:  # noqa: BLE001 — mot tai khoan hong khong duoc chan ca migrate
            _log(f"LOI khi tao {new_email} tu {old_email}: {e}")
            skipped += 1

    _log(f"Tai khoan app Monitor: tao moi {created} theo CCCD, bo qua {skipped}")


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

    _migrate_monitor_users()

    _drop_unique_index(_MONITOR_DT, "monitor_code")
    _drop_unique_index(_DRIVER_DT, "driver_code")

    frappe.db.commit()
    _log("Xong")
