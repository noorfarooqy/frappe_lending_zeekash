"""Configuration + wire helpers for the zeekash bridge.

Non-secret + secret config is read from the Frappe site config (set with
`bench --site <site> set-config <key> <value>`), so nothing is hard-coded and the
`lending` app is never touched:

    zeekash_client_id       - OAuth2 client id the connector authenticates with
    zeekash_client_secret   - OAuth2 client secret
    zeekash_webhook_secret  - HMAC secret for signing outbound webhooks
    zeekash_webhook_url     - where to POST webhooks (zeekash's financing webhook)
    zeekash_company         - the ERPNext Company loans are booked against
    zeekash_loan_category   - only Loan Products in this category are Murabaha (optional)
    zeekash_currency        - override reported currency (optional; else Company currency)
"""

import frappe


def conf(key, default=None):
	return frappe.conf.get(key, default)


def company():
	return conf("zeekash_company") or ""


def loan_category():
	return conf("zeekash_loan_category")


def currency_override():
	return conf("zeekash_currency")


def tenor_options():
	return conf("zeekash_tenor_options") or [3, 6, 9, 12]


def down_payment_percent():
	return float(conf("zeekash_down_payment_percent") or 0)


def offer_ttl_hours():
	return int(conf("zeekash_offer_ttl_hours") or 72)


def money(value):
	"""Wire format: a decimal string with exactly two places, e.g. 29440.00."""
	return f"{float(value or 0):.2f}"
