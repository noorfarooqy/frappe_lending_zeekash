"""Outbound webhooks (financier -> zeekash).

zeekash verifies `X-Signature: base64(HMAC_SHA256(raw_body, webhook_secret))` over the
exact bytes we send, with the secret from its `fin_<slug>` config. We sign the same
serialized bytes. Delivery failures are logged and swallowed — a webhook must never
break the loan operation that triggered it. The zeekash side is dedup'd on `event_id`.
"""

import base64
import hashlib
import hmac
import json

import frappe

from frappe_lending_zeekash import settings


def send(event_type, data):
	url = settings.conf("zeekash_webhook_url")
	if not url:
		return

	body = json.dumps(
		{
			"event_id": "flz_" + frappe.generate_hash(length=16),
			"type": event_type,
			"occurred_at": frappe.utils.now_datetime().isoformat(),
			"data": data,
		},
		separators=(",", ":"),
	).encode()

	headers = {"Content-Type": "application/json"}
	secret = settings.conf("zeekash_webhook_secret")
	if secret:
		headers["X-Signature"] = base64.b64encode(
			hmac.new(secret.encode(), body, hashlib.sha256).digest()
		).decode()

	# Zeekash routes by Host; inside Docker we reach the host via host.docker.internal,
	# so an optional Host override lets the request resolve to the right vhost.
	host = settings.conf("zeekash_webhook_host")
	if host:
		headers["Host"] = host

	try:
		import requests

		# Returned so recovery tooling can inspect the delivery; normal callers ignore it.
		return requests.post(url, data=body, headers=headers, timeout=10)
	except Exception as exc:
		frappe.log_error(f"zeekash webhook {event_type} failed: {exc}", "Zeekash Bridge Webhook")
		return None
