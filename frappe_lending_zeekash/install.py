"""Schema this app adds to Frappe — without modifying the `lending` app.

A single custom field, `profit_rate`, on Loan Product: the flat Murabaha margin the
bridge prices with. `rate_of_interest` stays 0 (Murabaha carries no interest); this field
is applied once to the cost and folded into the sale price, never compounding.

Runs on every migrate (idempotent), so a fresh site or a rebuilt image always has it.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_migrate():
	create_custom_fields(
		{
			"Loan Product": [
				{
					"fieldname": "profit_rate",
					"label": "Murabaha Profit Rate (% p.a., flat)",
					"fieldtype": "Percent",
					"insert_after": "rate_of_interest",
					"description": (
						"Flat annual Murabaha profit, applied once to the cost and folded into the "
						"sale price — it never compounds, so it is profit on a sale, not interest. "
						"Keep Rate of Interest at 0."
					),
				}
			]
		}
	)
	frappe.db.commit()
