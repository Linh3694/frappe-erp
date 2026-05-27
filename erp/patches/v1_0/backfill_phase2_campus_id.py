"""
Patch backfill campus_id Phase 2 — chạy theo thứ tự đợt 0→6.
"""

from __future__ import annotations

import frappe

from erp.utils.campus_backfill import (
	apply_fallback,
	backfill_copy_field,
	backfill_crm_family,
	backfill_from_assignment_chain,
	backfill_from_coalesce_joins,
	backfill_from_join,
	backfill_guardian_from_family,
	backfill_it_ticket_from_creator,
	backfill_lms_quiz_attempt,
	backfill_from_student_code,
	report_backfill,
)
from erp.utils.campus_phase2_config import PHASE2_BACKFILL


def execute():
	"""Backfill campus_id cho toàn bộ DocType Phase 2."""
	all_reports: list[dict] = []

	for phase in ("dot0", "dot1", "dot2", "dot3", "dot4", "dot5", "dot6"):
		frappe.logger().info(f"Phase 2 backfill — {phase}")
		for doctype, kind, kwargs in PHASE2_BACKFILL.get(phase, []):
			try:
				report = _run_rule(doctype, kind, kwargs)
				if kind != "skip":
					fallback_n = apply_fallback(doctype)
					report["fallback"] = fallback_n
				all_reports.append(report)
			except Exception as e:
				frappe.log_error(
					title=f"phase2_backfill_{doctype}",
					message=str(e),
				)
				all_reports.append({"doctype": doctype, "error": str(e)})

	frappe.db.commit()
	_summary(all_reports)


def _run_rule(doctype: str, kind: str, kwargs: dict) -> dict:
	if kind == "join":
		return backfill_from_join(
			doctype,
			kwargs["link_field"],
			kwargs["parent_doctype"],
			kwargs.get("parent_campus_field", "campus_id"),
		)
	if kind == "coalesce":
		return backfill_from_coalesce_joins(doctype, kwargs["joins"])
	if kind == "copy":
		return backfill_copy_field(doctype, kwargs.get("source_field", "campus"))
	if kind == "assignment_chain":
		return backfill_from_assignment_chain(
			doctype,
			kwargs["assignment_field"],
			kwargs["assignment_doctype"],
			kwargs.get("section_field", "course_section"),
		)
	if kind == "student_code":
		return backfill_from_student_code(doctype, kwargs.get("student_code_field", "student_code"))
	if kind == "guardian_family":
		return backfill_guardian_from_family(doctype)
	if kind == "crm_family":
		return backfill_crm_family(doctype)
	if kind == "it_creator":
		return backfill_it_ticket_from_creator(doctype)
	if kind == "lms_quiz_attempt":
		return backfill_lms_quiz_attempt(doctype)
	if kind == "skip":
		return report_backfill(doctype)
	raise ValueError(f"Unknown backfill kind: {kind}")


def _summary(reports: list[dict]):
	missing_total = sum(r.get("missing", 0) for r in reports if "missing" in r)
	frappe.logger().info(
		f"phase2_campus_id backfill done: {len(reports)} doctypes, missing={missing_total}"
	)
	for r in reports:
		if r.get("missing"):
			frappe.log_error(
				title=f"phase2_backfill_missing_{r.get('doctype')}",
				message=str(r),
			)
