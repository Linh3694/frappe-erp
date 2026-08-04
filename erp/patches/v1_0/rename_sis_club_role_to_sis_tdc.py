# -*- coding: utf-8 -*-
"""Doi ten role `SIS Club` -> `SIS TDC` (doi van hanh Cau lac bo). Idempotent.

Vi sao phai rename thay vi tao role moi: quyen module CLB gan vao TEN role, ma
`tabHas Role` cung luu ten role. Neu chi them `SIS TDC` vao permissions cua ba
doctype CLB thi moi nhan su dang giu `SIS Club` mat quyen ngay sau khi deploy,
phai gan lai tay tung nguoi. `rename_doc` cap nhat luon cac Link field tro toi
Role (`Has Role.role`, `DocPerm.role`, `Custom DocPerm.role`...) nen nhan su giu
nguyen quyen.

Truong hop ca hai role cung ton tai (ai do da tao tay `SIS TDC` truoc): dung
`merge=True` de gop `SIS Club` vao `SIS TDC` roi xoa role cu.

Chay o [post_model_sync]: permissions moi trong file .json cua doctype da duoc
sync truoc do, nen sau patch nay ban ghi `tabHas Role` va `tabDocPerm` khop nhau.
"""

import frappe

OLD_ROLE = "SIS Club"
NEW_ROLE = "SIS TDC"


def _log(msg: str) -> None:
    print(f"[rename_sis_club_role_to_sis_tdc] {msg}")
    frappe.logger().info(f"[rename_sis_club_role_to_sis_tdc] {msg}")


def execute():
    if not frappe.db.exists("Role", OLD_ROLE):
        _log(f"Khong co role `{OLD_ROLE}` — bo qua")
        return

    holders = frappe.db.count("Has Role", {"role": OLD_ROLE})
    merge = bool(frappe.db.exists("Role", NEW_ROLE))

    try:
        frappe.rename_doc("Role", OLD_ROLE, NEW_ROLE, merge=merge, force=True)
    except Exception as e:  # noqa: BLE001 — mot loi doi ten khong duoc chan ca migrate
        _log(f"LOI khi doi ten `{OLD_ROLE}` -> `{NEW_ROLE}`: {e}")
        return

    frappe.db.commit()
    _log(
        f"Da {'gop' if merge else 'doi ten'} `{OLD_ROLE}` -> `{NEW_ROLE}` "
        f"({holders} tai khoan giu role nay)"
    )
