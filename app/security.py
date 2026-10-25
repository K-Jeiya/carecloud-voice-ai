"""Tiny auth helpers: optional API key for /patients, shared secret for the voice webhook."""
from __future__ import annotations

import hmac

from fastapi import Header

from app.config import get_settings
from app.errors import AppError


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if not expected:
        return  # API left open (documented trade-off for the demo)
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise AppError(401, "unauthorized", "Missing or invalid API key")


def verify_vapi_secret(
    x_vapi_secret: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Vapi can send the server secret as X-Vapi-Secret; a Bearer token is accepted as well."""
    expected = get_settings().vapi_server_secret
    if not expected:
        return
    supplied = x_vapi_secret or ""
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()

    if not supplied or not hmac.compare_digest(supplied, expected):
        raise AppError(401, "unauthorized", "Invalid webhook secret")
