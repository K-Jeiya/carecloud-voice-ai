"""Vapi integration: system prompt, tool schemas, and the webhook message handler.

Vapi contract used here (see https://docs.vapi.ai/tools/custom-tools):
  * Vapi POSTs  {"message": {"type": "tool-calls", "toolCallList": [{"id", "name", "arguments"}], "call": {"id": ...}}}
    to the tool's server URL.
  * We must answer HTTP 200 with  {"results": [{"toolCallId": "<same id>", "result": "<single-line string>"}]}
    (results in the same order as the calls; the toolCallId must match exactly).
  * At the end of the call Vapi POSTs {"message": {"type": "end-of-call-report", ...}} to the assistant's
    Server URL; we store the summary/transcript and log the outcome.

Design rule: the LLM never validates. Every tool funnels into app.validators / Pydantic, and the
handlers ALWAYS return a result string (never raise), so the caller never hears silence.

Run `python -m app.integrations.voice_provider` to print the prompt + tool definitions for pasting
into the Vapi dashboard.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import crud
from app.models import CallLog
from app.errors import AppError, DuplicatePatientError, NotFoundError
from app.logging_utils import mask_patient_payload
from app.schemas import PatientCreate, PatientUpdate
from app.services import patient_service as service
from app.validators import ALL_FIELDS, NORMALIZERS, REQUIRED_FIELDS, normalize_phone

logger = logging.getLogger("carecloud.voice")

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "patient_registration.txt"
SYSTEM_PROMPT: str = PROMPT_PATH.read_text(encoding="utf-8")

FIRST_MESSAGE = (
    "Hi there, thanks for calling! I'm Riley, the patient registration assistant. Just so you know, "
    "this is a demonstration, so please don't share any real personal or medical information. "
    "Made-up details are perfect. Let's get started. What's your first and last name?"
)

# --------------------------------------------------------------------------- tool schemas
_FIELD_PROPS: dict[str, dict[str, Any]] = {
    "first_name": {"type": "string", "description": "Patient first name."},
    "last_name": {"type": "string", "description": "Patient last name."},
    "date_of_birth": {"type": "string", "description": "Date of birth as MM/DD/YYYY with a four-digit year."},
    "sex": {"type": "string", "description": "One of: Male, Female, Other, Decline to Answer."},
    "phone_number": {"type": "string", "description": "US phone number, digits only is fine."},
    "email": {"type": "string", "description": "Optional email address, e.g. name@example.com."},
    "address_line_1": {"type": "string", "description": "Street address, e.g. 123 Main Street."},
    "address_line_2": {"type": "string", "description": "Optional apartment/suite/unit."},
    "city": {"type": "string", "description": "City."},
    "state": {"type": "string", "description": "Two-letter US state abbreviation (a full state name is also accepted)."},
    "zip_code": {"type": "string", "description": "5-digit ZIP or ZIP+4."},
    "insurance_provider": {"type": "string", "description": "Optional insurance company name."},
    "insurance_member_id": {"type": "string", "description": "Optional alphanumeric member/subscriber ID."},
    "preferred_language": {"type": "string", "description": "Optional preferred language; defaults to English."},
    "emergency_contact_name": {"type": "string", "description": "Optional emergency contact full name."},
    "emergency_contact_phone": {"type": "string", "description": "Optional emergency contact US phone number."},
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "lookup_patient_by_phone",
        "description": (
            "Check whether an active patient record already exists for a phone number. Call as soon as "
            "the caller has given their phone number."
        ),
        "parameters": {
            "type": "object",
            "properties": {"phone_number": _FIELD_PROPS["phone_number"]},
            "required": ["phone_number"],
        },
    },
    {
        "name": "validate_patient_fields",
        "description": (
            "Validate and normalize patient details collected so far (send ALL fields collected so far; "
            "omit fields not yet collected). Returns per-field errors, missing required fields, and "
            "ready_to_confirm. Call after every new or corrected detail and before reading back."
        ),
        "parameters": {"type": "object", "properties": dict(_FIELD_PROPS), "required": []},
    },
    {
        "name": "register_patient",
        "description": (
            "Save a NEW patient. Only call after the caller explicitly said yes to the full read-back. "
            "Set caller_confirmed=true. Send all collected fields."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                **_FIELD_PROPS,
                "caller_confirmed": {
                    "type": "boolean",
                    "description": "true only if the caller explicitly confirmed the read-back.",
                },
                "allow_shared_phone": {
                    "type": "boolean",
                    "description": "true only if the caller said a different person already registered with this number.",
                },
            },
            "required": [*REQUIRED_FIELDS, "caller_confirmed"],
        },
    },
    {
        "name": "update_existing_patient",
        "description": (
            "Update an EXISTING patient found by lookup_patient_by_phone. Send only the fields that "
            "change. Only call after the caller explicitly confirmed the changes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "patient_id returned by lookup_patient_by_phone."},
                **_FIELD_PROPS,
                "caller_confirmed": {
                    "type": "boolean",
                    "description": "true only if the caller explicitly confirmed the changes.",
                },
            },
            "required": ["patient_id", "caller_confirmed"],
        },
    },
]


def build_vapi_tool(defn: dict[str, Any], webhook_url: str) -> dict[str, Any]:
    """Shape of a Vapi 'function' tool pointing at our webhook (for reference / dashboard paste)."""
    return {
        "type": "function",
        "function": {k: defn[k] for k in ("name", "description", "parameters")},
        "server": {"url": webhook_url, "timeoutSeconds": 20},
    }


# --------------------------------------------------------------------------- helpers
def _dump(obj: dict[str, Any]) -> str:
    """Vapi wants a single-line string; json.dumps never emits raw newlines."""
    return json.dumps(obj, default=str, ensure_ascii=True)


def _field_args(args: dict[str, Any]) -> dict[str, Any]:
    """Keep only known patient fields; drop null/blank values the LLM sometimes sends."""
    return {k: v for k, v in args.items() if k in ALL_FIELDS and v is not None and str(v).strip() != ""}


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _pydantic_errors(exc: ValidationError) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in exc.errors():
        field = str(e["loc"][0]) if e.get("loc") else "request"
        message = str(e.get("msg", "invalid")).removeprefix("Value error, ")
        if e.get("type") == "missing":
            message = f"{field.replace('_', ' ')} is required"
        out[field] = message
    return out


def _display_dob(iso_or_date: Any) -> str:
    text = str(iso_or_date)
    return f"{text[5:7]}/{text[8:10]}/{text[0:4]}" if len(text) == 10 and text[4] == "-" else text


# --------------------------------------------------------------------------- tool handlers
def tool_lookup_patient_by_phone(db: Session, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    try:
        phone = normalize_phone(args.get("phone_number"))
    except ValueError as exc:
        return {"found": False, "valid_phone": False, "error": str(exc),
                "instruction": "Ask the caller to repeat the phone number."}
    existing = service.find_active_by_phone(db, phone)  # type: ignore[arg-type]
    if existing is None:
        return {"found": False, "valid_phone": True}
    return {
        "found": True, "valid_phone": True, "patient_id": existing.patient_id,
        "first_name": existing.first_name, "last_name": existing.last_name,
        "instruction": "Tell the caller we already have a record and offer to update it instead.",
    }


def tool_validate_patient_fields(db: Session, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    fields = _field_args(args)
    errors: dict[str, str] = {}
    normalized: dict[str, Any] = {}
    for key, value in fields.items():
        try:
            result = NORMALIZERS[key](value)
        except ValueError as exc:
            errors[key] = str(exc)
            continue
        if result is not None:
            normalized[key] = _display_dob(result.isoformat()) if key == "date_of_birth" else result
    missing = [f for f in REQUIRED_FIELDS if f not in normalized and f not in errors]
    ready = not errors and not missing
    if errors:
        instruction = "Re-ask the caller ONLY for these fields: " + ", ".join(errors) + "."
    elif missing:
        instruction = "Still missing required fields: " + ", ".join(missing) + ". Ask for them naturally."
    else:
        instruction = "All required details are valid. Offer optional fields, then read everything back and ask for confirmation."
    return {"valid": not errors, "ready_to_confirm": ready, "errors": errors,
            "missing_required_fields": missing, "normalized": normalized, "instruction": instruction}


def tool_register_patient(db: Session, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    if not _truthy(args.get("caller_confirmed")):
        return {"success": False, "error_code": "not_confirmed", "retryable": False,
                "instruction": "Read all the details back and get an explicit yes from the caller first."}
    try:
        data = PatientCreate(**_field_args(args))
    except ValidationError as exc:
        return {"success": False, "error_code": "validation_error", "retryable": False,
                "errors": _pydantic_errors(exc),
                "instruction": "Ask the caller again ONLY for the fields listed in errors, then re-confirm."}
    try:
        patient = service.create_patient(db, data, allow_duplicate=_truthy(args.get("allow_shared_phone")))
    except DuplicatePatientError as dup:
        return {"success": False, "error_code": "duplicate_phone", "retryable": False,
                "patient_id": dup.existing.patient_id,
                "existing_first_name": dup.existing.first_name,
                "existing_last_name": dup.existing.last_name,
                "instruction": "Offer to update the existing record instead, or ask if this is a different person sharing the number."}
    except AppError as exc:
        logger.error("call=%s registration FAILED code=%s", call_id, exc.code)
        return {"success": False, "error_code": exc.code, "retryable": True,
                "instruction": "Apologize, say there was a technical problem saving, and retry once."}
    except Exception:
        logger.exception("call=%s registration crashed", call_id)
        return {"success": False, "error_code": "internal_error", "retryable": True,
                "instruction": "Apologize, say there was a technical problem saving, and retry once."}

    logger.info("call=%s REGISTERED patient=%s payload=%s", call_id, patient.patient_id,
                mask_patient_payload(data.model_dump()))
    _link_call(db, call_id, patient.patient_id, "created")
    return {"success": True, "patient_id": patient.patient_id, "first_name": patient.first_name,
            "instruction": "Say 'You're all set, <first name>.' then end the call politely."}


def tool_update_existing_patient(db: Session, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    if not _truthy(args.get("caller_confirmed")):
        return {"success": False, "error_code": "not_confirmed", "retryable": False,
                "instruction": "Read back the changes and get an explicit yes first."}
    patient_id = str(args.get("patient_id") or "").strip()
    changes = _field_args(args)
    if not changes:
        return {"success": False, "error_code": "no_changes", "retryable": False,
                "instruction": "Ask which details the caller wants to change."}
    try:
        update = PatientUpdate(**changes)
    except ValidationError as exc:
        return {"success": False, "error_code": "validation_error", "retryable": False,
                "errors": _pydantic_errors(exc),
                "instruction": "Ask again ONLY for the fields listed in errors."}
    try:
        patient = service.update_patient(db, patient_id, update)
    except NotFoundError:
        return {"success": False, "error_code": "not_found", "retryable": False,
                "instruction": "Apologize; the record could not be found. Offer a new registration."}
    except AppError as exc:
        logger.error("call=%s update FAILED code=%s", call_id, exc.code)
        return {"success": False, "error_code": exc.code, "retryable": exc.status_code >= 500,
                "instruction": "Apologize for the technical problem; retry once if retryable."}
    except Exception:
        logger.exception("call=%s update crashed", call_id)
        return {"success": False, "error_code": "internal_error", "retryable": True,
                "instruction": "Apologize for the technical problem; retry once."}

    logger.info("call=%s UPDATED patient=%s changes=%s", call_id, patient.patient_id,
                mask_patient_payload(update.model_dump(exclude_unset=True)))
    _link_call(db, call_id, patient.patient_id, "updated")
    return {"success": True, "patient_id": patient.patient_id, "first_name": patient.first_name,
            "instruction": "Confirm the record was updated, say goodbye, and end the call."}


def _link_call(db: Session, call_id: str, patient_id: str, action: str) -> None:
    """Best-effort bookkeeping; must never break the caller-facing result."""
    if call_id == "unknown":
        return
    try:
        crud.upsert_call_log(db, call_id, patient_id=patient_id, action=action)
    except Exception:
        db.rollback()
        logger.exception("call=%s could not link call log", call_id)


TOOL_HANDLERS = {
    "lookup_patient_by_phone": tool_lookup_patient_by_phone,
    "validate_patient_fields": tool_validate_patient_fields,
    "register_patient": tool_register_patient,
    "update_existing_patient": tool_update_existing_patient,
}


# --------------------------------------------------------------------------- webhook dispatch
def _parse_tool_calls(message: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    raw = message.get("toolCallList") or message.get("toolCalls") or []
    calls: list[tuple[str, str, dict[str, Any]]] = []
    for item in raw:
        fn = item.get("function") or {}
        name = item.get("name") or fn.get("name") or ""
        args = item.get("arguments", fn.get("arguments", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {}
        calls.append((str(item.get("id", "")), name, args if isinstance(args, dict) else {}))
    return calls


def _handle_end_of_call(db: Session, message: dict[str, Any], call_id: str) -> None:
    summary = message.get("summary") or (message.get("analysis") or {}).get("summary")
    transcript = message.get("transcript")
    ended = message.get("endedReason")
    logger.info("call=%s ENDED reason=%s transcript_chars=%d", call_id, ended, len(transcript or ""))
    if call_id == "unknown":
        return
    try:
        existing = db.query(CallLog).filter_by(call_id=call_id).first()
        crud.upsert_call_log(
            db, call_id, ended_reason=str(ended)[:100] if ended else None,
            summary=summary, transcript=(transcript or "")[:20000] or None,
        )
        if existing is None or existing.patient_id is None:
            logger.warning("call=%s ended WITHOUT a saved registration (caller dropped or declined)", call_id)
    except Exception:
        db.rollback()
        logger.exception("call=%s could not store end-of-call report", call_id)


def handle_vapi_message(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message", payload)
    msg_type = message.get("type")
    call_id = str((message.get("call") or {}).get("id") or "unknown")

    if msg_type == "tool-calls":
        results = []
        for tool_call_id, name, args in _parse_tool_calls(message):
            handler = TOOL_HANDLERS.get(name)
            if handler is None:
                out: dict[str, Any] = {"success": False, "error_code": "unknown_tool"}
            else:
                try:
                    out = handler(db, args, call_id)
                except Exception:  # last line of defence: never leave the caller in silence
                    logger.exception("call=%s tool=%s crashed", call_id, name)
                    db.rollback()
                    out = {"success": False, "error_code": "internal_error", "retryable": True,
                           "instruction": "Apologize for a technical problem and retry once."}
            logger.info("call=%s tool=%s ok=%s", call_id, name, out.get("success", out.get("valid", out.get("found"))))
            results.append({"toolCallId": tool_call_id, "result": _dump(out)})
        return {"results": results}

    if msg_type == "end-of-call-report":
        _handle_end_of_call(db, message, call_id)
    else:
        logger.debug("call=%s ignoring message type=%s", call_id, msg_type)
    return {"ok": True}


# --------------------------------------------------------------------------- CLI helper
if __name__ == "__main__":
    from app.config import get_settings

    base = get_settings().public_base_url
    url = f"{base}/voice/webhook"
    print("=== FIRST MESSAGE ===\n" + FIRST_MESSAGE)
    print("\n=== SYSTEM PROMPT ===\n" + SYSTEM_PROMPT)
    print(f"\n=== SERVER URL (assistant + every tool) ===\n{url}")
    for d in TOOL_DEFINITIONS:
        print(f"\n=== TOOL: {d['name']} ===\nDescription: {d['description']}\nParameters JSON:")
        print(json.dumps(d["parameters"], indent=2))
    print("\n=== FULL TOOL OBJECTS (reference) ===")
    print(json.dumps([build_vapi_tool(d, url) for d in TOOL_DEFINITIONS], indent=2))
