# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISReenrollmentAnswer(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		question_id: DF.Data
		question_text_en: DF.SmallText | None
		question_text_vn: DF.SmallText | None
		selected_options: DF.JSON | None
		selected_options_text_en: DF.SmallText | None
		selected_options_text_vn: DF.SmallText | None
	# end: auto-generated types
	pass


