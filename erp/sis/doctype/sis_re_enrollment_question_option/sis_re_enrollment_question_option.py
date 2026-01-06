# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISReenrollmentQuestionOption(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		option_en: DF.Data
		option_vn: DF.Data
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		sort_order: DF.Int
	# end: auto-generated types
	pass

