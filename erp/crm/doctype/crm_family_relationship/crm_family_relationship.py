# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMFamilyRelationship(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		access: DF.Check
		guardian: DF.Link | None
		key_person: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		relationship_type: DF.Data
		student: DF.Link | None
	# end: auto-generated types

	pass
