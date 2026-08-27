"""Outbound webhooks (financier -> zeekash), delivered through a persistent outbox.

Every event is written to a `Zeekash Webhook Delivery` row and delivered immediately.
If zeekash is unreachable the row stays `Pending` and the scheduler (`flush_outbox`,
every 5 min) redelivers it with exponential backoff until zeekash acks or it is marked
`Dead`. A retry reuses the same `event_id` and the byte-identical body, so zeekash —
which dedupes on `event_id` — treats a redelivery as the same event, never a second one.

zeekash verifies `X-Signature: base64(HMAC_SHA256(raw_body, webhook_secret))`; we sign
the exact stored bytes with the current secret on every attempt.
"""

import base64
import hashlib
import hmac
import json

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from frappe_lending_zeekash import settings

DOCTYPE = "Zeekash Webhook Delivery"
DEFAULT_MAX_ATTEMPTS = 8

# Delay before the Nth retry (1-indexed by the number of attempts already made):
# 1m, 5m, 30m, 2h, 6h, 12h, 24h. After DEFAULT_MAX_ATTEMPTS the row is marked Dead.
BACKOFF_SECONDS = [60, 300, 1800, 7200, 21600, 43200, 86400]


def send(event_type, data):
	"""Record an event in the outbox and try to deliver it once, now.

	Returns the HTTP response of the immediate attempt (or None when no webhook URL is
	configured or the attempt raised). A None is not a lost event: the row persists and
	the scheduler retries it — this return exists only so recovery tooling can report the
	first attempt's status.
	"""
	url = settings.conf("zeekash_webhook_url")
	if not url:
		return None

	body = json.dumps(
		{
			"event_id": "flz_" + frappe.generate_hash(length=16),
			"type": event_type,
			"occurred_at": now_datetime().isoformat(),
			"data": data,
		},
		separators=(",", ":"),
	)
	envelope = json.loads(body)

	delivery = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"event_id": envelope["event_id"],
			"event_type": event_type,
			"contract_ref": (data or {}).get("contract_ref"),
			"status": "Pending",
			"attempts": 0,
			"max_attempts": DEFAULT_MAX_ATTEMPTS,
			"next_attempt_at": now_datetime(),
			"target_url": url,
			"target_host": settings.conf("zeekash_webhook_host"),
			"body": body,
		}
	)
	delivery.insert(ignore_permissions=True)
	frappe.db.commit()

	return _attempt(delivery)


def _attempt(delivery):
	"""One delivery attempt. Moves the row to Delivered, or Pending with a backoff, or
	Dead once the attempts are exhausted. Returns the HTTP response (or None)."""
	body_bytes = (delivery.body or "").encode()

	headers = {"Content-Type": "application/json"}
	secret = settings.conf("zeekash_webhook_secret")
	if secret:
		headers["X-Signature"] = base64.b64encode(
			hmac.new(secret.encode(), body_bytes, hashlib.sha256).digest()
		).decode()
	# zeekash routes by Host; inside Docker we reach the host via host.docker.internal,
	# so an optional Host override lets the request resolve to the right vhost.
	if delivery.target_host:
		headers["Host"] = delivery.target_host

	resp = None
	code = None
	error = None
	try:
		import requests

		resp = requests.post(delivery.target_url, data=body_bytes, headers=headers, timeout=10)
		code = resp.status_code
	except Exception as exc:
		error = str(exc)[:500]

	attempts = cint(delivery.attempts) + 1

	if code is not None and 200 <= code < 300:
		frappe.db.set_value(
			DOCTYPE,
			delivery.name,
			{
				"status": "Delivered",
				"attempts": attempts,
				"last_status_code": code,
				"last_error": None,
				"delivered_at": now_datetime(),
				"next_attempt_at": None,
			},
		)
	else:
		max_attempts = cint(delivery.max_attempts) or DEFAULT_MAX_ATTEMPTS
		dead = attempts >= max_attempts
		if error is None:
			error = f"HTTP {code}: {(resp.text or '')[:300]}" if resp is not None else "no response"
		frappe.db.set_value(
			DOCTYPE,
			delivery.name,
			{
				"status": "Dead" if dead else "Pending",
				"attempts": attempts,
				"last_status_code": code,
				"last_error": error,
				"next_attempt_at": None if dead else _next_attempt_at(attempts),
			},
		)
		if dead:
			frappe.log_error(
				f"zeekash webhook {delivery.event_type} ({delivery.event_id}) dead after "
				f"{attempts} attempts: {error}",
				"Zeekash Bridge Webhook Dead",
			)

	frappe.db.commit()
	return resp


def _next_attempt_at(attempts):
	"""Backoff time for the next try, given how many attempts have already been made."""
	idx = min(cint(attempts), len(BACKOFF_SECONDS)) - 1
	return add_to_date(now_datetime(), seconds=BACKOFF_SECONDS[idx])


def flush_outbox():
	"""Scheduler task: redeliver every Pending row whose backoff has elapsed.

	Idempotent and self-limiting — Delivered/Dead rows are never selected, and a row
	that succeeds this pass drops out of the next one.
	"""
	due = frappe.get_all(
		DOCTYPE,
		filters={"status": "Pending", "next_attempt_at": ["<=", now_datetime()]},
		fields=["name"],
		order_by="next_attempt_at asc",
		limit=100,
	)
	for row in due:
		_attempt(frappe.get_doc(DOCTYPE, row.name))


def requeue(event_id):
	"""Manually put a delivery (typically a Dead one) back in line and retry it now.

	    bench --site <site> execute frappe_lending_zeekash.webhooks.requeue --kwargs '{"event_id": "flz_..."}'
	"""
	frappe.db.set_value(DOCTYPE, event_id, {"status": "Pending", "next_attempt_at": now_datetime()})
	frappe.db.commit()
	resp = _attempt(frappe.get_doc(DOCTYPE, event_id))
	print(f"REQUEUED {event_id} -> HTTP {getattr(resp, 'status_code', None)}")
	return getattr(resp, "status_code", None)
