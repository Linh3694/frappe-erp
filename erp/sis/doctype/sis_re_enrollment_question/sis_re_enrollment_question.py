# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISReenrollmentQuestion(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from erp.sis.doctype.sis_re_enrollment_question_option.sis_re_enrollment_question_option import SISReenrollmentQuestionOption

		is_required: DF.Check
		options: DF.Table[SISReenrollmentQuestionOption]
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		question_en: DF.SmallText
		question_type: DF.Literal["single_choice", "multiple_choice"]
		question_vn: DF.SmallText
		sort_order: DF.Int
	# end: auto-generated types
	pass

