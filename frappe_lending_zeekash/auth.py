"""OAuth2 client-credentials (the shape CanonicalFinancingConnector expects) + bearer
validation for the /financing/* surface.

The connector does `POST /oauth/token` with HTTP Basic (client_id:client_secret) and a
form body `grant_type=client_credentials`, reads `access_token`, then sends it as
`Authorization: Bearer <token>` on every call. We issue a deterministic, stateless
token = HMAC-SHA256(client_id, client_secret) so it survives restarts with no server
state, and validate the bearer by recomputing it.

If no client credentials are configured on the site, auth is skipped (dev fail-open,
matching the reference sandbox bank) so the bridge is usable before secrets are set.
"""

import base64
import hashlib
import hmac

import frappe

from frappe_lending_zeekash import settings
from frappe_lending_zeekash.errors import BridgeError


def _expected_token(client_id, client_secret):
	return hmac.new(client_secret.encode(), client_id.encode(), hashlib.sha256).hexdigest()


def issue_token():
	"""Handle POST /oauth/token. Returns the OAuth token response dict, or raises."""
	client_id = settings.conf("zeekash_client_id")
	client_secret = settings.conf("zeekash_client_secret")

	# No credentials configured → issue a dev token so the flow works pre-setup.
	if not client_id or not client_secret:
		return {"access_token": "dev-open", "token_type": "Bearer", "expires_in": 3000}

	given_id, given_secret = _basic_auth()
	if not hmac.compare_digest(given_id or "", client_id) or not hmac.compare_digest(
		given_secret or "", client_secret
	):
		raise BridgeError("UNAUTHORIZED", "Invalid client credentials.", 401)

	return {
		"access_token": _expected_token(client_id, client_secret),
		"token_type": "Bearer",
		"expires_in": 3000,
		"scope": "financing:read financing:write financing:servicing",
	}


def require_bearer():
	"""Validate the inbound bearer on a /financing/* call, or raise UNAUTHORIZED."""
	client_id = settings.conf("zeekash_client_id")
	client_secret = settings.conf("zeekash_client_secret")

	# Fail-open in dev when no credentials are configured.
	if not client_id or not client_secret:
		return

	token = _bearer_token()
	if not token or not hmac.compare_digest(token, _expected_token(client_id, client_secret)):
		raise BridgeError("UNAUTHORIZED", "Missing or invalid bearer token.", 401)


def _basic_auth():
	header = frappe.get_request_header("Authorization") or ""
	if not header.lower().startswith("basic "):
		return None, None
	try:
		raw = base64.b64decode(header.split(" ", 1)[1]).decode()
		client_id, _, client_secret = raw.partition(":")
		return client_id, client_secret
	except Exception:
		return None, None


def _bearer_token():
	header = frappe.get_request_header("Authorization") or ""
	if header.lower().startswith("bearer "):
		return header.split(" ", 1)[1].strip()
	return None
