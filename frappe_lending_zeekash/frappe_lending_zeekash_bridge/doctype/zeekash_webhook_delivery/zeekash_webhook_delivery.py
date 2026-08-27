# Copyright (c) 2026, Captain and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ZeekashWebhookDelivery(Document):
	"""One outbound webhook to zeekash: the exact signed body, its delivery status, and
	its retry bookkeeping. Written and driven by frappe_lending_zeekash.webhooks."""

	pass
