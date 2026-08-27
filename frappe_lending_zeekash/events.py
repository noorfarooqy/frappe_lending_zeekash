"""Financier-driven status updates.

isnaad operates the loan in its own system (the Frappe desk) — disburses, records
repayments, closes it. Each of those Frappe events fires a signed webhook to zeekash,
which merely reflects the status. zeekash never drives the ownership sequence; every
post-acceptance update flows from here.

Every handler is a no-op for loans that did not originate from zeekash (no matching
`Zeekash Murabaha` record), so ordinary Frappe loans are untouched.
"""

import frappe
from frappe.utils import flt, now_datetime

from frappe_lending_zeekash import settings, webhooks


def _bridge_for_loan(loan_name):
	"""The Zeekash Murabaha record behind a Frappe Loan, or None if the loan is not ours."""
	if not loan_name:
		return None
	return frappe.db.get_value(
		"Zeekash Murabaha",
		{"contract_ref": loan_name},
		["name", "status", "amount_paid", "total_price"],
		as_dict=True,
	)


def on_loan_disbursement_submit(doc, method=None):
	"""The bank paid out and the sale is executed → the contract is active."""
	b = _bridge_for_loan(doc.get("against_loan"))
	if not b or b.status in ("active", "settled", "settled_early", "defaulted"):
		return

	now = now_datetime()
	frappe.db.set_value(
		"Zeekash Murabaha",
		b.name,
		{"supplier_paid_at": now, "activated_at": now, "status": "active"},
	)
	frappe.db.commit()
	webhooks.send("contract.activated", {"contract_ref": doc.against_loan, "status": "active"})


def on_loan_repayment_submit(doc, method=None):
	"""The bank recorded a repayment → report it; if it clears the balance, settle."""
	b = _bridge_for_loan(doc.get("against_loan"))
	if not b:
		return

	amount = flt(doc.amount_paid)
	paid = flt(b.amount_paid) + amount
	outstanding = max(0.0, flt(b.total_price) - paid)
	settled = outstanding <= 0

	updates = {"amount_paid": paid, "outstanding": outstanding}
	if settled:
		updates["status"] = "settled"
		updates["settled_at"] = now_datetime()
	frappe.db.set_value("Zeekash Murabaha", b.name, updates)
	frappe.db.commit()

	webhooks.send(
		"repayment.posted",
		{
			"contract_ref": doc.against_loan,
			"repayment_ref": doc.name,
			"amount": settings.money(amount),
			"outstanding_after": settings.money(outstanding),
			"source": "direct_to_bank",
		},
	)
	if settled:
		webhooks.send("contract.settled", {"contract_ref": doc.against_loan, "status": "settled"})


def on_loan_repayment_cancel(doc, method=None):
	"""A recorded repayment was cancelled in Frappe → tell zeekash to unmake it.

	Frappe has already reversed the payment on its side; this rolls the bridge's own
	totals back and fires `repayment.reversed` so zeekash un-allocates the matching rows.
	If the payment had settled the loan, the bridge goes back to active.
	"""
	b = _bridge_for_loan(doc.get("against_loan"))
	if not b:
		return

	amount = flt(doc.amount_paid)
	paid = max(0.0, flt(b.amount_paid) - amount)
	outstanding = max(0.0, flt(b.total_price) - paid)

	updates = {"amount_paid": paid, "outstanding": outstanding}
	if b.status in ("settled", "settled_early") and outstanding > 0:
		updates["status"] = "active"
		updates["settled_at"] = None
	frappe.db.set_value("Zeekash Murabaha", b.name, updates)
	frappe.db.commit()

	webhooks.send(
		"repayment.reversed",
		{
			"contract_ref": doc.against_loan,
			"repayment_ref": doc.name,
			"amount": settings.money(amount),
			"outstanding_after": settings.money(outstanding),
			"source": "direct_to_bank",
		},
	)


def on_loan_cancel(doc, method=None):
	"""The loan was cancelled in Frappe before it went live (a customer's pre-activation
	cancel, actioned by the bank) → tell zeekash."""
	b = _bridge_for_loan(doc.name)
	if not b or b.status in ("active", "settled", "settled_early"):
		return
	frappe.db.set_value("Zeekash Murabaha", b.name, {"status": "cancelled"})
	frappe.db.commit()
	webhooks.send("contract.cancelled", {"contract_ref": doc.name, "status": "cancelled"})


def on_loan_update(doc, method=None):
	"""The bank moved the loan's state in Frappe (closed / written off)."""
	b = _bridge_for_loan(doc.name)
	if not b:
		return

	status = doc.get("status") or ""
	if status in ("Closed", "Settled") and b.status not in ("settled", "settled_early"):
		frappe.db.set_value(
			"Zeekash Murabaha", b.name, {"status": "settled", "settled_at": now_datetime()}
		)
		frappe.db.commit()
		webhooks.send("contract.settled", {"contract_ref": doc.name, "status": "settled"})
	elif status == "Written Off" and b.status != "defaulted":
		frappe.db.set_value("Zeekash Murabaha", b.name, {"status": "defaulted"})
		frappe.db.commit()
		webhooks.send("contract.defaulted", {"contract_ref": doc.name, "status": "defaulted"})
