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
