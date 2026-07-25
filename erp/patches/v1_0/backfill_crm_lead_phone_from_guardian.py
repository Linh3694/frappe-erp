# -*- coding: utf-8 -*-
"""Backfill CRM Lead.phone_numbers tu CRM Guardian (qua lead_guardians / CRM Family). Idempotent.

Van de: `CRM Lead.phone_numbers` la child table `reqd: 1` nhung nhieu ho so cu
(import/migrate) khong co dong nao. CRM Lead KHONG co field SDT phang nen khong tu
bootstrap duoc nhu CRM Guardian lam trong `_migrate_flat_contacts_if_needed`.
Hau qua: MOI `doc.save()` len cac ho so do deu throw MandatoryError
"Du lieu bi mat trong bang: Phone Numbers" — khong chuyen buoc, khong sua, khong luu duoc.

Nguon lay SDT, theo thu tu uu tien:
  1. `CRM Lead.lead_guardians` -> CRM Guardian   (uu tien is_primary_contact, roi display_order)
  2. `CRM Lead.linked_student` -> `CRM Family Relationship` -> CRM Guardian
                                                  (uu tien key_person, roi display_order)
Voi moi guardian: lay `CRM Guardian Phone` (uu tien is_primary) truoc, khong co thi
dung field phang `CRM Guardian.phone_number`.

SDT duoc chuan hoa ve +84xxxxxxxxx bang erp.api.crm.utils.normalize_phone_number —
dung dinh dang ma he thong dang luu + dedup.

CHI them dong cho ho so dang KHONG CO dong nao -> chay lai lan 2 la no-op, va khong
bao gio ghi de SDT da co.

Ghi thang bang raw INSERT thay vi doc.save(): tranh chay lai toan bo hook cua CRM Lead
(sync CRM Student, tinh enrollment_status...) cho hang nghin ho so, va giu nguyen
`modified` cua lead.
"""

import frappe

_BATCH = 500


def _log(msg: str) -> None:
    print(f"[backfill_crm_lead_phone_from_guardian] {msg}")
    frappe.logger().info(f"[backfill_crm_lead_phone_from_guardian] {msg}")


def _leads_without_phone():
    """Ten cac CRM Lead chua co dong nao trong CRM Lead Phone."""
    return frappe.db.sql_list(
        """
        SELECT l.`name`
        FROM `tabCRM Lead` l
        WHERE NOT EXISTS (
            SELECT 1 FROM `tabCRM Lead Phone` p WHERE p.`parent` = l.`name`
        )
        """
    )


def _guardians_by_lead(lead_names):
    """{lead: [guardian, ...]} theo thu tu uu tien, gop ca 2 duong, da bo trung."""
    out = {}

    def _add(lead, guardian):
        if not lead or not guardian:
            return
        lst = out.setdefault(lead, [])
        if guardian not in lst:
            lst.append(guardian)

    # Duong 1: lead_guardians (truc tiep tren ho so)
    rows = frappe.db.sql(
        """
        SELECT lg.`parent` AS lead, lg.`guardian`
        FROM `tabCRM Lead Guardian` lg
        WHERE lg.`parenttype` = 'CRM Lead' AND lg.`parent` IN %(leads)s
        ORDER BY lg.`parent`, lg.`is_primary_contact` DESC,
                 lg.`display_order` ASC, lg.`idx` ASC
        """,
        {"leads": lead_names},
        as_dict=True,
    )
    for r in rows:
        _add(r["lead"], r["guardian"])

    # Duong 2: qua hoc sinh lien ket -> quan he gia dinh.
    # CRM Family Relationship la child table dung chung duoi nhieu parent (CRM Family,
    # CRM Guardian, CRM Student) nen 1 cap (student, guardian) co the lap lai -> _add() lo trung.
    rows = frappe.db.sql(
        """
        SELECT l.`name` AS lead, fr.`guardian`
        FROM `tabCRM Lead` l
        INNER JOIN `tabCRM Family Relationship` fr ON fr.`student` = l.`linked_student`
        WHERE l.`name` IN %(leads)s
          AND IFNULL(TRIM(l.`linked_student`), '') <> ''
        ORDER BY l.`name`, fr.`key_person` DESC, fr.`display_order` ASC
        """,
        {"leads": lead_names},
        as_dict=True,
    )
    for r in rows:
        _add(r["lead"], r["guardian"])

    return out


def _phone_by_guardian(guardian_names):
    """{guardian: sdt} — uu tien CRM Guardian Phone (is_primary), fallback field phang."""
    out = {}
    if not guardian_names:
        return out

    rows = frappe.db.sql(
        """
        SELECT gp.`parent` AS guardian, gp.`phone_number`
        FROM `tabCRM Guardian Phone` gp
        WHERE gp.`parenttype` = 'CRM Guardian' AND gp.`parent` IN %(gs)s
          AND IFNULL(TRIM(gp.`phone_number`), '') <> ''
        ORDER BY gp.`parent`, gp.`is_primary` DESC, gp.`idx` ASC
        """,
        {"gs": guardian_names},
        as_dict=True,
    )
    for r in rows:
        out.setdefault(r["guardian"], r["phone_number"])

    missing = [g for g in guardian_names if g not in out]
    if missing:
        rows = frappe.db.sql(
            """
            SELECT `name` AS guardian, `phone_number`
            FROM `tabCRM Guardian`
            WHERE `name` IN %(gs)s AND IFNULL(TRIM(`phone_number`), '') <> ''
            """,
            {"gs": missing},
            as_dict=True,
        )
        for r in rows:
            out.setdefault(r["guardian"], r["phone_number"])

    return out


def _insert_phone_rows(pairs):
    """pairs: [(lead, phone)] -> them 1 dong CRM Lead Phone is_primary=1 cho moi lead."""
    if not pairs:
        return
    from frappe.model.naming import make_autoname

    now = frappe.utils.now()
    user = frappe.session.user or "Administrator"
    values = []
    for lead, phone in pairs:
        # make_autoname("hash") — dung ham Frappe dung cho child row, khong tu sinh
        values.append(
            (make_autoname("hash", "CRM Lead Phone"), lead, phone, now, now, user, user)
        )
    frappe.db.sql(
        """
        INSERT INTO `tabCRM Lead Phone`
            (`name`, `parent`, `parenttype`, `parentfield`, `idx`, `docstatus`,
             `phone_number`, `is_primary`, `creation`, `modified`, `owner`, `modified_by`)
        VALUES
        """
        + ", ".join(
            ["(%s, %s, 'CRM Lead', 'phone_numbers', 1, 0, %s, 1, %s, %s, %s, %s)"] * len(values)
        ),
        [v for row in values for v in row],
    )


def execute():
    for dt in ("CRM Lead", "CRM Lead Phone", "CRM Guardian", "CRM Family Relationship"):
        if not frappe.db.table_exists(dt):
            _log(f"Bo qua — chua co bang {dt}")
            return

    from erp.api.crm.utils import normalize_phone_number

    leads = _leads_without_phone()
    if not leads:
        _log("Khong co CRM Lead nao thieu SDT — no-op")
        return
    _log(f"Bat dau: {len(leads)} ho so khong co dong nao trong CRM Lead Phone")

    filled = 0
    no_guardian = 0
    guardian_no_phone = 0

    for i in range(0, len(leads), _BATCH):
        chunk = leads[i : i + _BATCH]
        g_by_lead = _guardians_by_lead(chunk)

        all_guardians = sorted({g for gs in g_by_lead.values() for g in gs})
        phone_by_g = _phone_by_guardian(all_guardians)

        pairs = []
        for lead in chunk:
            guardians = g_by_lead.get(lead) or []
            if not guardians:
                no_guardian += 1
                continue
            phone = ""
            for g in guardians:  # guardian dau tien co SDT thi lay
                phone = normalize_phone_number(phone_by_g.get(g) or "")
                if phone:
                    break
            if not phone:
                guardian_no_phone += 1
                continue
            pairs.append((lead, phone))

        _insert_phone_rows(pairs)
        filled += len(pairs)
        frappe.db.commit()
        _log(f"...da xu ly {min(i + _BATCH, len(leads))}/{len(leads)} ho so, dien duoc {filled}")

    remain = len(_leads_without_phone())
    _log(
        f"Xong: dien SDT cho {filled} ho so; "
        f"{no_guardian} ho so khong co guardian nao, "
        f"{guardian_no_phone} ho so co guardian nhung guardian khong co SDT; "
        f"con {remain} ho so van thieu SDT"
    )
