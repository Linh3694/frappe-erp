"""
Backfill is_submitted cho sổ đầu bài đã ghi trước khi có cơ chế nháp/nộp.

Trước đây "hoàn thành" được suy ra từ (lesson_name + lesson_score) hoặc is_practise_test.
Đánh dấu đúng tập đó là đã nộp để trạng thái trên lưới TKB không đổi sau khi deploy.
"""

import frappe


def execute():
	if not frappe.db.table_exists("tabSIS Class Log Subject"):
		frappe.logger().info("Table tabSIS Class Log Subject does not exist, skipping backfill")
		return

	updated = frappe.db.sql(
		"""
		UPDATE `tabSIS Class Log Subject`
		SET is_submitted = 1
		WHERE IFNULL(is_submitted, 0) = 0
		  AND (
		    IFNULL(is_practise_test, 0) = 1
		    OR (
		      TRIM(IFNULL(lesson_name, '')) != ''
		      AND TRIM(IFNULL(lesson_score, '')) != ''
		    )
		  )
		"""
	)
	frappe.db.commit()
	frappe.logger().info(f"Backfilled is_submitted for class log subjects: {updated}")
