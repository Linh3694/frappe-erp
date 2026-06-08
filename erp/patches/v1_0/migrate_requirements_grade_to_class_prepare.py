# -*- coding: utf-8 -*-
"""
TKB requirements — backup ma trận khối×môn trước khi đổi sang lớp×môn.

Chạy trong [pre_model_sync]: TRƯỚC khi JSON xóa education_grade_id.
"""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.table_exists("tabSIS Timetable Generation Requirement"):
		return
	if not frappe.db.has_column("SIS Timetable Generation Requirement", "education_grade_id"):
		return

	frappe.db.sql_ddl(
		"""
		CREATE TABLE IF NOT EXISTS `_erp_tkb_req_grade_backup` (
		  `session_id` VARCHAR(140) NOT NULL,
		  `education_grade_id` VARCHAR(140) NOT NULL,
		  `timetable_subject_id` VARCHAR(140) NOT NULL,
		  `periods_per_week` INT NOT NULL DEFAULT 0,
		  `max_periods_per_day` INT NOT NULL DEFAULT 2,
		  `prefer_consecutive` INT NOT NULL DEFAULT 0,
		  `force_pair` INT NOT NULL DEFAULT 0,
		  `room_type_required` VARCHAR(140) DEFAULT '',
		  PRIMARY KEY (`session_id`, `education_grade_id`, `timetable_subject_id`)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
		"""
	)
	frappe.db.sql("TRUNCATE TABLE `_erp_tkb_req_grade_backup`")

	has_force_pair = frappe.db.has_column("SIS Timetable Generation Requirement", "force_pair")
	force_pair_sql = "COALESCE(r.force_pair, 0)" if has_force_pair else "0"

	frappe.db.sql(
		f"""
		INSERT INTO `_erp_tkb_req_grade_backup`
		  (session_id, education_grade_id, timetable_subject_id,
		   periods_per_week, max_periods_per_day, prefer_consecutive, force_pair, room_type_required)
		SELECT
		  r.session_id,
		  r.education_grade_id,
		  r.timetable_subject_id,
		  COALESCE(r.periods_per_week, 0),
		  COALESCE(r.max_periods_per_day, 2),
		  COALESCE(r.prefer_consecutive, 0),
		  {force_pair_sql},
		  IFNULL(r.room_type_required, '')
		FROM `tabSIS Timetable Generation Requirement` r
		WHERE r.periods_per_week > 0
		"""
	)
	frappe.db.commit()
