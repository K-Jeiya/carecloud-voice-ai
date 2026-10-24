"""Logging setup + PII masking so logs stay useful without leaking full patient details."""
from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, get_settings().log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )


def _mask_phone(value: str | None) -> str | None:
    return f"***-***-{value[-4:]}" if value else value


def _mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return value
    local, domain = value.split("@", 1)
    return f"{local[:1]}***@{domain}"


def mask_patient_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a log-safe copy: initials, birth year, last-4 of phones, no street address/member ID."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if value in (None, ""):
            continue
        if key in ("first_name", "last_name", "emergency_contact_name"):
            out[key] = f"{str(value)[:1]}***"
        elif key == "date_of_birth":
            out[key] = f"{str(value)[:4]}-**-**"
        elif key in ("phone_number", "emergency_contact_phone"):
            out[key] = _mask_phone(str(value))
        elif key == "email":
            out[key] = _mask_email(str(value))
        elif key in ("address_line_1", "address_line_2", "insurance_member_id"):
            out[key] = "[redacted]"
        elif key == "zip_code":
            out[key] = f"{str(value)[:3]}**"
        else:  # sex, city, state, insurance_provider, preferred_language
            out[key] = value
    return out
