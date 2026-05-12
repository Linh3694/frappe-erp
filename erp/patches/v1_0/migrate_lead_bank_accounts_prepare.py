# -*- coding: utf-8 -*-
"""
CRM Lead — Backup 5 cot tai khoan phang tra khi dong bo sang child table.

Chay trong [pre_model_sync]: TRUOC khi JSON xoa cot khoi tabCRM Lead.
"""

import frappe


def execute():
	if not frappe.db.has_table("tabCRM Lead"):
		return

	required_cols = [
		"student_account_holder_relationship",
		"student_bank_account_name",
		"student_bank_account_number",
		"student_bank_name",
		"student_bank_branch",
	]
	for col in required_cols:
		if not frappe.db.has_column("tabCRM Lead", col):
			return

	frappe.db.sql_ddl(
		"""
		CREATE TABLE IF NOT EXISTS `_erp_crm_lead_bank_flat_backup` (
		  `lead` VARCHAR(140) NOT NULL PRIMARY KEY,
		  `student_account_holder_relationship` TEXT,
		  `student_bank_account_name` TEXT,
		  `student_bank_account_number` TEXT,
		  `student_bank_name` TEXT,
		  `student_bank_branch` TEXT
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
		"""
	)
	frappe.db.sql("TRUNCATE TABLE `_erp_crm_lead_bank_flat_backup`")

	frappe.db.sql(
		"""
		INSERT INTO `_erp_crm_lead_bank_flat_backup`
		  (lead, student_account_holder_relationship, student_bank_account_name,
		   student_bank_account_number, student_bank_name, student_bank_branch)
		SELECT
		  `name`,
		  IFNULL(`student_account_holder_relationship`, ''),
		  IFNULL(`student_bank_account_name`, ''),
		  IFNULL(`student_bank_account_number`, ''),
		  IFNULL(`student_bank_name`, ''),
		  IFNULL(`student_bank_branch`, '')
		FROM `tabCRM Lead`
		WHERE IFNULL(TRIM(`student_account_holder_relationship`), '') <> ''
		   OR IFNULL(TRIM(`student_bank_account_name`), '') <> ''
		   OR IFNULL(TRIM(`student_bank_account_number`), '') <> ''
		   OR IFNULL(TRIM(`student_bank_name`), '') <> ''
		   OR IFNULL(TRIM(`student_bank_branch`), '') <> ''
		"""
	)
	frappe.db.commit()
