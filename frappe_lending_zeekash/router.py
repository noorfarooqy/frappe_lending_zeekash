"""Page renderer that serves zeekash's canonical financier contract (/oauth/token and
/financing/*) directly from this Frappe site, so the stock CanonicalFinancingConnector
reaches Frappe Lending with no bespoke code in zeekash.

Frappe dispatches GET/HEAD/POST for non-/api paths through page renderers (see
frappe/app.py), so this handles the REST verbs and path params the connector uses,
returns JSON with contract-correct status codes, and honours Idempotency-Key.
"""

import hashlib
import json
import re

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer
from frappe.website.utils import build_response

from frappe_lending_zeekash import auth, bank
from frappe_lending_zeekash.errors import BridgeError

# (method, regex over the stripped path, handler name, sends_idempotency_key)
ROUTES = [
	("POST", r"^oauth/token$", "_token", False),
	("GET", r"^financing/products$", "products", False),
	("POST", r"^financing/prequalify$", "_prequalify", False),
	("POST", r"^financing/applications$", "submit_application", True),
	("GET", r"^financing/applications/(?P<ref>[^/]+)$", "application_status", False),
	("POST", r"^financing/applications/(?P<ref>[^/]+)/withdraw$", "withdraw", False),
	("GET", r"^financing/applications/(?P<ref>[^/]+)/offer$", "offer", False),
	("POST", r"^financing/applications/(?P<ref>[^/]+)/accept$", "accept_offer", True),
	("POST", r"^financing/contracts/(?P<ref>[^/]+)/purchase-order$", "purchase_order", True),
	("POST", r"^financing/contracts/(?P<ref>[^/]+)/disbursement$", "disburse", True),
	("POST", r"^financing/contracts/(?P<ref>[^/]+)/activate$", "activate", False),
	("GET", r"^financing/contracts/(?P<ref>[^/]+)/settlement-quote$", "settlement_quote", False),
	("POST", r"^financing/contracts/(?P<ref>[^/]+)/settle$", "settle", True),
	("POST", r"^financing/contracts/(?P<ref>[^/]+)/repayments$", "report_repayment", True),
	("GET", r"^financing/contracts/(?P<ref>[^/]+)$", "contract", False),
]

COMPILED = [(m, re.compile(p), h, idem) for (m, p, h, idem) in ROUTES]


class FinancingRouter(BaseRenderer):
	def can_render(self):
		return self.path == "oauth/token" or self.path.startswith("financing/")

	def render(self):
		method = frappe.local.request.method
		for route_method, pattern, handler, sends_idem in COMPILED:
			match = pattern.match(self.path)
			if not match:
				continue
			if method != route_method:
				continue
			return self._dispatch(handler, match.groupdict(), sends_idem)
		return self._json({"error_code": "NOT_FOUND", "message": "No such endpoint."}, 404)

	# ------------------------------------------------------------------

	def _dispatch(self, handler, params, sends_idem):
		try:
			if handler == "_token":
				return self._json(auth.issue_token(), 200)

			auth.require_bearer()
			frappe.set_user("Administrator")

			idem_key = frappe.get_request_header("Idempotency-Key") if sends_idem else None
			if idem_key:
				cached = self._replay(idem_key)
				if cached is not None:
					return self._json(cached["body"], cached["status"], replayed=True)

			body, status = self._call(handler, params)

			if idem_key and status < 400:
				self._store(idem_key, body, status)
			return self._json(body, status)

		except BridgeError as exc:
			return self._json(exc.body(), exc.http_status)
		except frappe.PermissionError as exc:
			frappe.db.rollback()
			return self._json({"error_code": "FORBIDDEN", "message": str(exc)}, 403)
		except Exception as exc:
			frappe.db.rollback()
			frappe.log_error(frappe.get_traceback(), "Zeekash Bridge error")
			return self._json({"error_code": "UNAVAILABLE", "message": str(exc)}, 502)

	def _call(self, handler, params):
		ref = params.get("ref")
		payload = self._payload()

		if handler == "products":
			return bank.products(), 200
		if handler == "_prequalify":
			return {"error_code": "UNSUPPORTED_OPERATION", "message": "Prequalification is not supported."}, 501
		if handler == "submit_application":
			return bank.submit_application(payload), 200
		if handler == "application_status":
			return bank.application_status(ref), 200
		if handler == "withdraw":
			return bank.withdraw(ref, (payload or {}).get("reason")), 200
		if handler == "offer":
			return bank.offer(ref), 200
		if handler == "accept_offer":
			return bank.accept_offer(ref, (payload or {}).get("acceptance") or {}), 201
		if handler == "purchase_order":
			return bank.purchase_order(ref), 200
		if handler == "disburse":
			return bank.disburse(ref, frappe.get_request_header("Idempotency-Key")), 200
		if handler == "activate":
			return bank.activate(ref), 200
		if handler == "contract":
			return bank.contract(ref), 200
		if handler == "report_repayment":
			return (
				bank.report_repayment(
					ref,
					(payload or {}).get("amount"),
					frappe.get_request_header("Idempotency-Key"),
					payload or {},
				),
				200,
			)
		if handler == "settlement_quote":
			return bank.settlement_quote(ref), 200
		if handler == "settle":
			return bank.settle(ref, (payload or {}).get("amount"), frappe.get_request_header("Idempotency-Key")), 200

		return {"error_code": "NOT_FOUND", "message": "Unhandled route."}, 404

	# ------------------------------------------------------------------

	def _payload(self):
		try:
			data = frappe.local.request.get_data()
			return json.loads(data) if data else {}
		except Exception:
			return {}

	def _idem_cache_key(self, key):
		return "flz:idem:" + hashlib.sha1(key.encode()).hexdigest()

	def _replay(self, key):
		raw = frappe.cache().get_value(self._idem_cache_key(key))
		return json.loads(raw) if raw else None

	def _store(self, key, body, status):
		frappe.cache().set_value(
			self._idem_cache_key(key), json.dumps({"body": body, "status": status}), expires_in_sec=43200
		)

	def _json(self, body, status, replayed=False):
		headers = {"Content-Type": "application/json"}
		if replayed:
			headers["Idempotent-Replayed"] = "true"
		return build_response(self.path, json.dumps(body), status, headers)
