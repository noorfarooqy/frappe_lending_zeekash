"""The financier logic: zeekash's canonical Murabaha contract, backed by Frappe Lending.

Each function here is one endpoint. Requests arrive already authenticated and routed by
router.py; money arrives as numbers and leaves as 2dp strings (settings.money). The
Murabaha markup is Frappe's — read from the Loan Product's rate via the repayment
schedule — never computed here. State Frappe Lending doesn't model (supplier/asset, the
ownership-sequence timestamps, the offer snapshot) lives on the `Zeekash Murabaha` doc.
"""

import json

import frappe
from frappe.utils import add_to_date, flt, getdate, now_datetime

from frappe_lending_zeekash import settings, webhooks
from frappe_lending_zeekash.errors import (
	BridgeError,
	contract_not_active,
	not_found,
	offer_expired,
	ownership_violation,
	supplier_not_verified,
)

MONTHS = {"monthly": 1}


# ---------------------------------------------------------------- helpers

def _iso(dt):
	return dt.isoformat() if dt else None


def _normalize_phone(phone):
	if not phone:
		return None
	phone = str(phone).strip()
	return phone if phone.startswith("+") else "+" + phone


def _company_currency(company):
	if settings.currency_override():
		return settings.currency_override()
	if not company:
		return "KES"
	return frappe.db.get_value("Company", company, "default_currency") or "KES"


def _resolve_product(slug):
	name = frappe.db.get_value("Loan Product", {"product_code": slug}, "name") or slug
	row = frappe.db.get_value(
		"Loan Product",
		name,
		["name", "rate_of_interest", "is_term_loan", "maximum_loan_amount", "company"],
		as_dict=True,
	)
	if not row:
		raise not_found("PRODUCT_NOT_FOUND", f"Loan Product {slug} not found.")
	return row


def _bridge_by_app(external_ref):
	name = frappe.db.get_value("Zeekash Murabaha", {"external_ref": external_ref})
	if not name:
		raise not_found("APPLICATION_NOT_FOUND", f"Application {external_ref} not found.")
	return frappe.get_doc("Zeekash Murabaha", name)


def _bridge_by_contract(contract_ref):
	name = frappe.db.get_value("Zeekash Murabaha", {"contract_ref": contract_ref})
	if not name:
		raise not_found("CONTRACT_NOT_FOUND", f"Contract {contract_ref} not found.")
	return frappe.get_doc("Zeekash Murabaha", name)


def _build_offer(bridge):
	"""Read the Murabaha terms from Frappe's schedule and shape a reconciling offer.

	Rounding is folded so that financed == cost - down, total == financed + markup, and
	Σ schedule == total, exactly (zeekash rejects an offer that does not reconcile)."""
	financed = flt(bridge.financed_amount, 2)
	product = _resolve_product(bridge.product_slug)
	rate = flt(product.rate_of_interest)
	tenor = int(bridge.tenor_months or 0)
	first_due = add_to_date(getdate(), months=1)

	rows = []
	if product.is_term_loan and tenor > 0:
		schedule = frappe.new_doc("Loan Repayment Schedule")
		schedule.loan_product = product.name
		schedule.repayment_frequency = "Monthly"
		schedule.repayment_method = "Repay Over Number of Periods"
		schedule.repayment_periods = tenor
		schedule.rate_of_interest = rate
		schedule.posting_date = getdate()
		schedule.repayment_start_date = first_due
		schedule.loan_amount = financed
		schedule.current_principal_amount = financed
		schedule.moratorium_tenure = 0
		schedule.moratorium_type = ""
		schedule.repayment_schedule_type = product.get("repayment_schedule_type") or frappe.db.get_value(
			"Loan Product", product.name, "repayment_schedule_type"
		)
		schedule.validate()
		for r in schedule.get("repayment_schedule"):
			amount = flt(r.total_payment, 2)
			cost = flt(r.principal_amount, 2)
			rows.append({"date": getdate(r.payment_date), "amount": amount, "cost": cost})
	else:
		# Demand / interest-free product: a single bullet payment of the financed amount.
		rows.append({"date": first_due, "amount": financed, "cost": financed})

	total = flt(sum(r["amount"] for r in rows), 2)
	markup = flt(total - financed, 2)

	schedule_out = []
	for i, r in enumerate(rows, start=1):
		markup_component = flt(r["amount"] - r["cost"], 2)
		schedule_out.append(
			{
				"sequence": i,
				"due_date": str(r["date"]),
				"amount": settings.money(r["amount"]),
				"cost_component": settings.money(r["cost"]),
				"markup_component": settings.money(markup_component),
			}
		)

	return {
		"offer_ref": "FLZOFF-" + (bridge.external_ref or bridge.name),
		"currency": bridge.currency,
		"cost_price": settings.money(financed),
		"down_payment": settings.money(0),
		"financed_amount": settings.money(financed),
		"markup_amount": settings.money(markup),
		"total_price": settings.money(total),
		"tenor_months": tenor,
		"payment_frequency": "monthly",
		"instalment_amount": schedule_out[0]["amount"] if schedule_out else settings.money(0),
		"first_due_date": str(rows[0]["date"]),
		"schedule": schedule_out,
		"expires_at": _iso(add_to_date(now_datetime(), hours=settings.offer_ttl_hours())),
	}


def _contract_dict(bridge):
	return {
		"contract_ref": bridge.contract_ref,
		"status": bridge.status,
		"currency": bridge.currency,
		"total_price": settings.money(bridge.total_price),
		"amount_paid": settings.money(bridge.amount_paid),
		"outstanding": settings.money(bridge.outstanding),
		"purchase_order_at": _iso(bridge.po_at),
		"supplier_paid_at": _iso(bridge.supplier_paid_at),
		"activated_at": _iso(bridge.activated_at),
		"settled_at": _iso(bridge.settled_at),
		"matures_at": None,
		"schedule": json.loads(bridge.offer_json or "{}").get("schedule", []),
	}


# ---------------------------------------------------------------- endpoints

def products():
	filters = {"disabled": 0}
	if settings.loan_category():
		filters["loan_category"] = settings.loan_category()

	rows = frappe.get_all(
		"Loan Product",
		filters=filters,
		fields=["name", "product_code", "product_name", "maximum_loan_amount", "rate_of_interest", "company"],
	)
	currency = _company_currency(settings.company())
	out = []
	for r in rows:
		max_amount = flt(r.maximum_loan_amount)
		out.append(
			{
				"slug": r.product_code or r.name,
				"name": r.product_name or r.name,
				"description": None,
				"type": "murabaha_asset",
				"currency": currency,
				"min_amount": settings.money(0),
				"max_amount": settings.money(max_amount if max_amount > 0 else 1_000_000_000),
				"tenor_options": settings.tenor_options(),
				"down_payment_percent": settings.down_payment_percent(),
				"markup_basis": {"type": "flat_per_annum", "rate": round(flt(r.rate_of_interest) / 100, 6)},
				"eligible_categories": [],
				"required_documents": [],
				"late_policy": {"type": "none"},
			}
		)
	return {"products": out}


def submit_application(payload):
	product = _resolve_product(payload.get("product_slug"))
	financed = flt(payload.get("financed_amount") or (flt(payload.get("cost_price")) - flt(payload.get("down_payment"))), 2)
	tenor = int(payload.get("tenor_months") or 0)
	customer = payload.get("customer") or {}
	currency = _company_currency(product.company or settings.company())

	max_amount = flt(product.maximum_loan_amount)
	declined = max_amount > 0 and financed > max_amount

	bridge = frappe.new_doc("Zeekash Murabaha")
	bridge.application_ref = payload.get("application_ref")
	bridge.product_slug = payload.get("product_slug")
	bridge.currency = currency
	bridge.cost_price = financed
	bridge.down_payment = 0
	bridge.financed_amount = financed
	bridge.tenor_months = tenor
	bridge.supplier_json = json.dumps(payload.get("supplier") or {})
	bridge.asset_json = json.dumps(payload.get("asset") or {})
	bridge.customer_json = json.dumps(customer)

	if declined:
		bridge.status = "declined"
		bridge.decline_reason = "exceeds_maximum_exposure"
		bridge.external_ref = "FLZAPP-" + frappe.generate_hash(length=10)
		bridge.insert(ignore_permissions=True)
		frappe.db.commit()
		return {"application_ref": bridge.external_ref, "status": "declined", "decline_reason": "exceeds_maximum_exposure"}

	is_term = bool(product.is_term_loan)
	la = frappe.new_doc("Loan Application")
	la.applicant_type = "Customer"
	la.company = product.company or settings.company()
	la.loan_product = product.name
	la.posting_date = getdate()
	la.loan_amount = financed
	la.rate_of_interest = flt(product.rate_of_interest)
	la.is_term_loan = 1 if is_term else 0
	if is_term:
		la.repayment_method = "Repay Over Number of Periods"
		la.repayment_periods = tenor
	la.applicant_name = customer.get("name")
	la.applicant_email_address = customer.get("email")
	la.applicant_phone_number = _normalize_phone(customer.get("phone"))
	la.insert(ignore_permissions=True)

	bridge.loan_application = la.name
	bridge.external_ref = la.name
	bridge.markup_amount = 0
	bridge.total_price = financed
	bridge.status = "offered"
	bridge.insert(ignore_permissions=True)

	offer = _build_offer(bridge)
	bridge.markup_amount = flt(offer["markup_amount"], 2)
	bridge.total_price = flt(offer["total_price"], 2)
	bridge.outstanding = bridge.total_price
	bridge.offer_json = json.dumps(offer)
	bridge.save(ignore_permissions=True)
	frappe.db.commit()

	return {"application_ref": bridge.external_ref, "status": "offered", "offer": offer}


def application_status(ref):
	bridge = _bridge_by_app(ref)
	out = {"application_ref": ref, "status": bridge.status}
	if bridge.decline_reason:
		out["decline_reason"] = bridge.decline_reason
	if bridge.status == "offered" and bridge.offer_json:
		out["offer"] = json.loads(bridge.offer_json)
	return out


def withdraw(ref, reason=None):
	name = frappe.db.get_value("Zeekash Murabaha", {"external_ref": ref})
	if name:
		bridge = frappe.get_doc("Zeekash Murabaha", name)
		bridge.status = "withdrawn"
		bridge.decline_reason = reason
		bridge.save(ignore_permissions=True)
		if bridge.loan_application:
			doc = frappe.get_doc("Loan Application", bridge.loan_application)
			if doc.docstatus == 1:
				doc.cancel()
		frappe.db.commit()
	return {"application_ref": ref, "status": "withdrawn"}


def offer(ref):
	bridge = _bridge_by_app(ref)
	if not bridge.offer_json:
		raise not_found("OFFER_NOT_FOUND", f"No offer for {ref}.")
	data = json.loads(bridge.offer_json)
	expires = data.get("expires_at")
	if expires and getdate(expires) < getdate():
		raise offer_expired("This offer has expired.")
	return data


def accept_offer(ref, acceptance):
	bridge = _bridge_by_app(ref)
	if not bridge.offer_json:
		raise not_found("OFFER_NOT_FOUND", f"No offer for {ref}.")

	from lending.loan_management.doctype.loan_application.loan_application import create_loan

	la = frappe.get_doc("Loan Application", bridge.loan_application)
	if la.docstatus == 0:
		la.submit()

	loan = create_loan(source_name=bridge.loan_application, submit=1)

	bridge.contract_ref = loan.name
	bridge.loan = loan.name
	bridge.status = "pending_disbursement"
	bridge.amount_paid = 0
	bridge.outstanding = bridge.total_price
	bridge.acceptance_json = json.dumps(acceptance or {})
	bridge.save(ignore_permissions=True)
	frappe.db.commit()

	return _contract_dict(bridge)


def purchase_order(contract_ref):
	bridge = _bridge_by_contract(contract_ref)
	supplier = json.loads(bridge.supplier_json or "{}")
	if not supplier.get("is_verified"):
		raise supplier_not_verified("The supplier has not been verified and cannot be paid.")

	if not bridge.po_ref:
		bridge.po_ref = "FLZPO-" + frappe.generate_hash(length=10)
		bridge.po_at = now_datetime()
		bridge.save(ignore_permissions=True)
		frappe.db.commit()

	return {
		"purchase_order_ref": bridge.po_ref,
		"issued_at": _iso(bridge.po_at),
		"currency": bridge.currency,
		"amount": settings.money(bridge.cost_price),
		"supplier": supplier,
		"asset": json.loads(bridge.asset_json or "{}"),
	}


def disburse(contract_ref, idempotency_key=None):
	bridge = _bridge_by_contract(contract_ref)
	if not bridge.po_ref:
		raise ownership_violation("purchase_order", "A purchase order must be issued before disbursement.")

	if not bridge.supplier_paid_at:
		loan = frappe.get_doc("Loan", bridge.loan)
		disb = frappe.new_doc("Loan Disbursement")
		disb.against_loan = bridge.loan
		disb.company = loan.company
		disb.applicant_type = loan.applicant_type
		disb.applicant = loan.applicant
		disb.disbursement_date = getdate()
		disb.disbursed_amount = flt(loan.loan_amount)
		disb.insert(ignore_permissions=True)
		disb.submit()
		bridge.supplier_paid_at = now_datetime()
		bridge.save(ignore_permissions=True)
		frappe.db.commit()

	return {
		"disbursement_ref": "FLZDIS-" + frappe.generate_hash(length=10),
		"mode": "direct",
		"status": "completed",
		"currency": bridge.currency,
		"amount": settings.money(bridge.cost_price),
		"paid_at": _iso(bridge.supplier_paid_at),
		"supplier_receipt_ref": bridge.po_ref,
	}


def activate(contract_ref):
	bridge = _bridge_by_contract(contract_ref)
	if not bridge.supplier_paid_at:
		raise ownership_violation("supplier_paid", "The supplier must be paid before the sale is activated.")

	if not bridge.activated_at:
		bridge.activated_at = now_datetime()
		bridge.status = "active"
		bridge.save(ignore_permissions=True)
		frappe.db.commit()
		webhooks.send("contract.activated", {"contract_ref": contract_ref, "status": "active"})

	return _contract_dict(bridge)


def contract(contract_ref):
	return _contract_dict(_bridge_by_contract(contract_ref))


def report_repayment(contract_ref, amount, idempotency_key=None, context=None):
	bridge = _bridge_by_contract(contract_ref)
	if bridge.status not in ("active", "in_arrears"):
		raise contract_not_active("No instalment can be posted against a contract awaiting disbursement.")

	context = context or {}
	amount = flt(amount, 2)
	loan = frappe.get_doc("Loan", bridge.loan)
	rep = frappe.new_doc("Loan Repayment")
	rep.against_loan = bridge.loan
	rep.company = loan.company
	rep.applicant_type = loan.applicant_type
	rep.applicant = loan.applicant
	rep.posting_date = now_datetime()
	rep.value_date = getdate(context.get("collected_at")) if context.get("collected_at") else now_datetime()
	rep.amount_paid = amount
	rep.repayment_type = "Normal Repayment"
	rep.insert(ignore_permissions=True)
	rep.submit()

	bridge.amount_paid = flt(bridge.amount_paid) + amount
	bridge.outstanding = max(0, flt(bridge.total_price) - flt(bridge.amount_paid))
	if bridge.outstanding <= 0:
		bridge.status = "settled"
		bridge.settled_at = now_datetime()
	bridge.save(ignore_permissions=True)
	frappe.db.commit()

	if bridge.status == "settled":
		webhooks.send("contract.settled", {"contract_ref": contract_ref, "status": "settled"})

	return {
		"repayment_ref": rep.name,
		"status": "posted",
		"currency": bridge.currency,
		"amount": settings.money(amount),
		"outstanding_after": settings.money(bridge.outstanding),
		"posted_at": _iso(now_datetime()),
		"instalment_sequence": context.get("instalment_sequence"),
		"duplicate": False,
	}


def settlement_quote(contract_ref):
	bridge = _bridge_by_contract(contract_ref)
	if bridge.status not in ("active", "in_arrears"):
		raise contract_not_active("A settlement quote is only available on a live contract.")

	outstanding = flt(bridge.outstanding, 2)
	# Any rebate on the unearned markup is the bank's discretion (ibra'); never computed here.
	return {
		"quote_ref": "FLZSQ-" + frappe.generate_hash(length=10),
		"currency": bridge.currency,
		"outstanding": settings.money(outstanding),
		"rebate_amount": settings.money(0),
		"settlement_amount": settings.money(outstanding),
		"valid_until": _iso(add_to_date(now_datetime(), hours=24)),
		"rebate_is_discretionary": True,
	}


def settle(contract_ref, amount, idempotency_key=None):
	bridge = _bridge_by_contract(contract_ref)
	if bridge.status not in ("active", "in_arrears"):
		raise contract_not_active("Only a live contract can be settled early.")

	amount = flt(amount, 2)
	loan = frappe.get_doc("Loan", bridge.loan)
	rep = frappe.new_doc("Loan Repayment")
	rep.against_loan = bridge.loan
	rep.company = loan.company
	rep.applicant_type = loan.applicant_type
	rep.applicant = loan.applicant
	rep.posting_date = now_datetime()
	rep.value_date = now_datetime()
	rep.amount_paid = amount
	rep.repayment_type = "Loan Closure"
	rep.insert(ignore_permissions=True)
	rep.submit()

	bridge.amount_paid = flt(bridge.amount_paid) + amount
	bridge.outstanding = 0
	bridge.status = "settled_early"
	bridge.settled_at = now_datetime()
	bridge.save(ignore_permissions=True)
	frappe.db.commit()
	webhooks.send("contract.settled", {"contract_ref": contract_ref, "status": "settled_early"})

	return _contract_dict(bridge)
