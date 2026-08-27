"""One-off maintenance helpers for the bridge.

`dedupe_customers` cleans up the Customers duplicated by the old auto-create behaviour
(before we started reusing one Customer per zeekash user). It groups Customers that match
exactly on (customer_name, email_id, mobile_no) and merges the newer ones into the oldest,
so all their applications/loans move onto a single Customer.

Preview (default):
    bench --site <site> execute frappe_lending_zeekash.maintenance.dedupe_customers
Apply:
    bench --site <site> execute frappe_lending_zeekash.maintenance.dedupe_customers --kwargs '{"apply": 1}'
"""

import frappe
from frappe.utils import flt

from frappe_lending_zeekash import settings, webhooks


def resync_loan(loan, apply=0):
	"""Re-deliver the status webhooks zeekash may have missed for a loan.

	If a webhook was emitted while delivery was misconfigured (e.g. no `zeekash_webhook_url`),
	zeekash never saw it. A loan whose `contract.activated` was lost stays at
	`pending_disbursement` on zeekash — which is not collectable — so every later
	`repayment.posted` is rejected (HTTP 500) and the outstanding never moves.

	This reconstructs the true state from Frappe (disbursed? which repayments?) and
	re-fires the matching webhooks, in order, with a correct running `outstanding_after`.
	It changes nothing in Frappe; it only re-sends to zeekash.

	Run ONCE per loan — event ids are freshly generated, so zeekash will not dedupe a
	second run and would double-count. Preview first:
	    bench --site <site> execute frappe_lending_zeekash.maintenance.resync_loan --kwargs '{"loan": "ACC-LOAN-2026-00001"}'
	Apply:
	    ... --kwargs '{"loan": "ACC-LOAN-2026-00001", "apply": 1}'
	"""
	b = frappe.db.get_value(
		"Zeekash Murabaha",
		{"contract_ref": loan},
		["name", "status", "total_price", "amount_paid", "outstanding"],
		as_dict=True,
	)
	if not b:
		print(f"NO_BRIDGE: no Zeekash Murabaha for {loan} — not a zeekash-originated loan")
		return {"error": "no bridge", "loan": loan}

	disbursed = bool(frappe.db.exists("Loan Disbursement", {"against_loan": loan, "docstatus": 1}))
	reps = frappe.get_all(
		"Loan Repayment",
		filters={"against_loan": loan, "docstatus": 1},
		fields=["name", "amount_paid"],
		order_by="creation asc",
	)

	total = flt(b.total_price)
	plan = []
	if disbursed:
		plan.append(("contract.activated", {"contract_ref": loan, "status": "active"}))

	paid = 0.0
	for r in reps:
		paid = flt(paid) + flt(r.amount_paid)
		outstanding = max(0.0, total - paid)
		plan.append((
			"repayment.posted",
			{
				"contract_ref": loan,
				"repayment_ref": r.name,
				"amount": settings.money(r.amount_paid),
				"outstanding_after": settings.money(outstanding),
				"source": "direct_to_bank",
			},
		))
	if reps and max(0.0, total - paid) <= 0:
		plan.append(("contract.settled", {"contract_ref": loan, "status": "settled"}))

	summary = {
		"loan": loan,
		"disbursed": disbursed,
		"repayments": len(reps),
		"total_paid": round(paid, 2),
		"outstanding": round(max(0.0, total - paid), 2),
		"events": len(plan),
	}

	if not int(apply or 0):
		for event_type, data in plan:
			print(f"WOULD SEND {event_type}: {data}")
		print("RESYNC_PREVIEW:", summary)
		return summary

	results = []
	for event_type, data in plan:
		resp = webhooks.send(event_type, data)
		code = getattr(resp, "status_code", None)
		results.append({"type": event_type, "http": code})
		print(f"SENT {event_type} -> HTTP {code}: {(getattr(resp, 'text', '') or '')[:120]}")

	print("RESYNC_DONE:", {**summary, "results": results})
	return {**summary, "results": results}


def dedupe_customers(apply=0):
	groups = frappe.db.sql(
		"""
		SELECT customer_name,
		       GROUP_CONCAT(name ORDER BY creation SEPARATOR '||') AS names,
		       COUNT(*) AS n
		FROM `tabCustomer`
		GROUP BY customer_name, IFNULL(email_id, ''), IFNULL(mobile_no, '')
		HAVING n > 1
		""",
		as_dict=True,
	)

	plan = [{"name": g.customer_name, "keep": g.names.split("||")[0], "merge": g.names.split("||")[1:]} for g in groups]

	if not int(apply or 0):
		for p in plan:
			print(f"WOULD MERGE {p['merge']} -> {p['keep']}  ({p['name']})")
		print("DEDUPE_PREVIEW:", {"groups": len(plan), "duplicates": sum(len(p["merge"]) for p in plan)})
		return {"groups": len(plan), "duplicates": sum(len(p["merge"]) for p in plan)}

	merged, skipped = 0, []
	for p in plan:
		for dup in p["merge"]:
			try:
				frappe.rename_doc("Customer", dup, p["keep"], merge=True, force=True)
				merged += 1
				print(f"merged {dup} -> {p['keep']}")
			except Exception as exc:
				skipped.append(f"{dup}: {exc}")
				print(f"SKIP {dup}: {exc}")

	frappe.db.commit()
	print("DEDUPE_DONE:", {"groups": len(plan), "merged": merged, "skipped": len(skipped)})
	return {"groups": len(plan), "merged": merged, "skipped": skipped}
