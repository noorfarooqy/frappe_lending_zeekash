"""The financing error model. A BridgeError serializes to zeekash's error envelope
`{error_code, message, ...extra}` at the mapped HTTP status. The connector branches on
`error_code`, not the status, so the code strings must be exact."""


class BridgeError(Exception):
	def __init__(self, error_code, message, http_status=400, **extra):
		super().__init__(message)
		self.error_code = error_code
		self.message = message
		self.http_status = http_status
		self.extra = extra

	def body(self):
		payload = {"error_code": self.error_code, "message": self.message}
		payload.update(self.extra)
		return payload


# Canonical status codes (from docs/openapi/financing.yaml) for the codes we emit.
def not_found(code, message):
	return BridgeError(code, message, 404)


def ownership_violation(missing_step, message):
	return BridgeError("OWNERSHIP_SEQUENCE_VIOLATION", message, 409, missing_step=missing_step)


def contract_not_active(message):
	return BridgeError("CONTRACT_NOT_ACTIVE", message, 409)


def supplier_not_verified(message):
	return BridgeError("SUPPLIER_NOT_VERIFIED", message, 409)


def offer_expired(message):
	return BridgeError("OFFER_EXPIRED", message, 410)


def unsupported(message):
	return BridgeError("UNSUPPORTED_OPERATION", message, 501)


def validation_error(message, errors=None):
	return BridgeError("VALIDATION_ERROR", message, 422, errors=errors or {})
