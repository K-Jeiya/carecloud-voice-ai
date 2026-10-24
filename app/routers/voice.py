"""Webhook endpoint that Vapi calls (tool calls + end-of-call report)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrations.voice_provider import handle_vapi_message
from app.security import verify_vapi_secret

router = APIRouter(prefix="/voice", tags=["voice"], dependencies=[Depends(verify_vapi_secret)])


@router.post("/webhook", summary="Vapi server URL (tool-calls, end-of-call-report)")
def vapi_webhook(payload: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    # Vapi expects HTTP 200 + {"results": [...]} for tool calls; other events just need a 200.
    return handle_vapi_message(db, payload)
