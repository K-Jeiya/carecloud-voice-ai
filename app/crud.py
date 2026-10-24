"""Data access only: no business rules, no HTTP concerns."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CallLog, Patient


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_active(db: Session, patient_id: str) -> Patient | None:
    stmt = select(Patient).where(Patient.patient_id == patient_id, Patient.deleted_at.is_(None))
    return db.scalars(stmt).first()


def find_active_by_phone(db: Session, phone: str) -> Patient | None:
    stmt = (
        select(Patient)
        .where(Patient.phone_number == phone, Patient.deleted_at.is_(None))
        .order_by(Patient.created_at)
    )
    return db.scalars(stmt).first()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_active(
    db: Session,
    *,
    last_name: str | None = None,
    date_of_birth: date | None = None,
    phone_number: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Patient], int]:
    conditions = [Patient.deleted_at.is_(None)]
    if last_name:
        conditions.append(
            func.lower(Patient.last_name).like(f"%{_escape_like(last_name.lower())}%", escape="\\")
        )
    if date_of_birth:
        conditions.append(Patient.date_of_birth == date_of_birth)
    if phone_number:
        conditions.append(Patient.phone_number == phone_number)

    total = db.scalar(select(func.count()).select_from(Patient).where(*conditions)) or 0
    stmt = (
        select(Patient)
        .where(*conditions)
        .order_by(Patient.last_name, Patient.first_name, Patient.created_at)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all()), int(total)


def create(db: Session, values: dict[str, Any]) -> Patient:
    patient = Patient(**values)
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def update(db: Session, patient: Patient, changes: dict[str, Any]) -> Patient:
    for key, value in changes.items():
        setattr(patient, key, value)
    patient.updated_at = _now()
    db.commit()
    db.refresh(patient)
    return patient


def soft_delete(db: Session, patient: Patient) -> Patient:
    now = _now()
    patient.deleted_at = now
    patient.updated_at = now
    db.commit()
    db.refresh(patient)
    return patient


# ---- call logs (bonus) ------------------------------------------------------------------
def upsert_call_log(db: Session, call_id: str, **fields: Any) -> CallLog:
    log = db.scalars(select(CallLog).where(CallLog.call_id == call_id)).first()
    if log is None:
        log = CallLog(call_id=call_id)
        db.add(log)
    for key, value in fields.items():
        if value is not None:
            setattr(log, key, value)
    db.commit()
    db.refresh(log)
    return log


def list_call_logs_for_patient(db: Session, patient_id: str) -> list[CallLog]:
    stmt = select(CallLog).where(CallLog.patient_id == patient_id).order_by(CallLog.created_at.desc())
    return list(db.scalars(stmt).all())
