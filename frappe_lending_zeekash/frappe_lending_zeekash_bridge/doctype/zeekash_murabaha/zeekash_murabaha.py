# Copyright (c) 2026, Captain and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ZeekashMurabaha(Document):
	"""Bridge record correlating a zeekash Murabaha application/contract with the Frappe
	Loan lifecycle, and holding the Murabaha state vanilla Frappe Lending does not model
	(supplier/asset snapshots, the ownership-sequence timestamps, the cached offer)."""

	pass
