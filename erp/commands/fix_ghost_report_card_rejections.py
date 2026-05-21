# -*- coding: utf-8 -*-
"""
Dọn metadata trả về cũ (GHOST) trong báo cáo học tập.

Môn đã level_2_approved+ nhưng còn rejection_reason → UI L3 kẹt.

Chạy:
  bench --site SITE execute erp.commands.fix_ghost_report_card_rejections.run --kwargs "{'dry_run': True}"
  bench --site SITE execute erp.commands.fix_ghost_report_card_rejections.run --kwargs "{'dry_run': False, 'school_year': 'SIS_SCHOOL_YEAR-00014', 'semester_part': 'End Term 2', 'class_short_codes': ['3A1','3A2','3A3','4A5','5A4']}"
"""

from __future__ import annotations

import json
from collections import Counter

import frappe

from erp.api.erp_sis.report_card.approval_helpers.helpers import (
    REJECTION_METADATA_KEYS,
    L2_PASSED_CLEAR_REJECTION_STATUSES,
    clear_approval_rejection_metadata,
    compute_approval_counters,
    sync_data_json_with_db,
)


def _clear_ghost_approval(ap: dict) -> bool:
    if ap.get("status") not in L2_PASSED_CLEAR_REJECTION_STATUSES:
        return False
    if not (ap.get("rejection_reason") and ap.get("rejected_from_level")):
        return False
    clear_approval_rejection_metadata(ap)
    return True


def _patch_data_json(dj: dict) -> tuple[bool, int]:
    changed = False
    count = 0
    for section in ("scores", "subject_eval"):
        for _sid, subj in (dj.get(section) or {}).items():
            if not isinstance(subj, dict):
                continue
            ap = subj.get("approval")
            if isinstance(ap, dict) and _clear_ghost_approval(ap):
                changed = True
                count += 1
    for _sid, subj in (dj.get("intl_scores") or {}).items():
        if not isinstance(subj, dict):
            continue
        for section in ("main_scores", "ielts", "comments"):
            ap = subj.get(f"{section}_approval")
            if isinstance(ap, dict) and _clear_ghost_approval(ap):
                changed = True
                count += 1
    return changed, count


@frappe.whitelist()
def run(
    dry_run: bool = True,
    school_year: str | None = None,
    semester_part: str | None = None,
    class_short_codes: list | None = None,
    campus_id: str | None = None,
):
    filters = {}
    if school_year:
        filters["school_year"] = school_year
    if semester_part:
        filters["semester_part"] = semester_part
    if campus_id:
        filters["campus_id"] = campus_id

    if class_short_codes:
        class_ids = frappe.get_all(
            "SIS Class",
            filters={"short_title": ["in", class_short_codes], **(
                {"school_year_id": school_year} if school_year else {}
            )},
            pluck="name",
        )
        if not class_ids:
            return {"error": "no_classes", "class_short_codes": class_short_codes}
        filters["class_id"] = ["in", class_ids]

    reports = frappe.get_all(
        "SIS Student Report Card",
        filters=filters,
        fields=["name", "template_id", "data_json"],
        limit=0,
    )

    fixed_reports = 0
    fixed_subjects = 0
    by_section = Counter()

    for r in reports:
        try:
            dj = json.loads(r.data_json or "{}")
        except Exception:
            continue
        changed, n = _patch_data_json(dj)
        if not changed:
            continue
        fixed_reports += 1
        fixed_subjects += n
        if dry_run:
            continue
        template = frappe.get_doc("SIS Report Card Template", r.template_id)
        dj = sync_data_json_with_db(r.name, dj)
        counters = compute_approval_counters(dj, template)
        frappe.db.set_value(
            "SIS Student Report Card",
            r.name,
            {"data_json": json.dumps(dj, ensure_ascii=False), **counters},
            update_modified=True,
        )

    if not dry_run:
        frappe.db.commit()

    return {
        "dry_run": dry_run,
        "reports_scanned": len(reports),
        "reports_fixed": fixed_reports,
        "subjects_fixed": fixed_subjects,
        "filters": filters,
    }
