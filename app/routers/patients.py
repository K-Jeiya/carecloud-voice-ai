"""REST endpoints for patients. Thin: parse input -> call service -> wrap in envelope."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.errors import AppError, DatabaseError
from app.schemas import (
    CallLogOut, DeleteResult, Envelope, ListEnvelope, PageMeta, PatientCreate, PatientOut, PatientUpdate,
)
from app.security import require_api_key
from app.services import patient_service as service

router = APIRouter(prefix="/patients", tags=["patients"], dependencies=[Depends(require_api_key)])


def _valid_uuid(patient_id: str) -> str:
    try:
        return str(uuid.UUID(patient_id))
    except ValueError:
        raise AppError(400, "invalid_id", "patient_id must be a valid UUID")


@router.get("", response_model=ListEnvelope[PatientOut], summary="List/search active patients")
def list_patients(
    last_name: Optional[str] = Query(None, description="Case-insensitive 'contains' match"),
    date_of_birth: Optional[str] = Query(None, description="MM/DD/YYYY or YYYY-MM-DD"),
    phone_number: Optional[str] = Query(None, description="Any US format; normalized to 10 digits"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    items, total = service.list_patients(
        db, last_name=last_name, date_of_birth=date_of_birth, phone_number=phone_number,
        limit=limit, offset=offset,
    )
    return ListEnvelope[PatientOut](
        data=[PatientOut.model_validate(p) for p in items],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


@router.post("", response_model=Envelope[PatientOut], status_code=201, summary="Create a patient")
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    patient = service.create_patient(db, payload, allow_duplicate=True)
    return Envelope[PatientOut](data=PatientOut.model_validate(patient))


@router.get("/{patient_id}", response_model=Envelope[PatientOut], summary="Get one patient")
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    patient = service.get_patient(db, _valid_uuid(patient_id))
    return Envelope[PatientOut](data=PatientOut.model_validate(patient))


@router.put("/{patient_id}", response_model=Envelope[PatientOut], summary="Partially update a patient")
def update_patient(patient_id: str, payload: PatientUpdate, db: Session = Depends(get_db)):
    patient = service.update_patient(db, _valid_uuid(patient_id), payload)
    return Envelope[PatientOut](data=PatientOut.model_validate(patient))


@router.delete("/{patient_id}", response_model=Envelope[DeleteResult], summary="Soft-delete a patient")
def delete_patient(patient_id: str, db: Session = Depends(get_db)):
    patient = service.soft_delete_patient(db, _valid_uuid(patient_id))
    return Envelope[DeleteResult](data=DeleteResult(patient_id=patient.patient_id, deleted_at=patient.deleted_at))


@router.get("/{patient_id}/calls", response_model=ListEnvelope[CallLogOut], summary="Call summaries/transcripts")
def patient_calls(patient_id: str, db: Session = Depends(get_db)):
    pid = _valid_uuid(patient_id)
    service.get_patient(db, pid)  # 404 if missing/deleted
    try:
        logs = crud.list_call_logs_for_patient(db, pid)
    except Exception:
        raise DatabaseError()
    return ListEnvelope[CallLogOut](
        data=[CallLogOut.model_validate(x) for x in logs],
        meta=PageMeta(total=len(logs), limit=len(logs), offset=0),
    )
