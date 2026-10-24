"""Business logic shared by the REST API and the voice-agent tool handlers."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date
from typing import Iterator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import crud
from app.errors import AppError, DatabaseError, DuplicatePatientError, NotFoundError
from app.models import Patient
from app.schemas import PatientCreate, PatientUpdate
from app.validators import normalize_dob, normalize_phone

logger = logging.getLogger("carecloud.service")


@contextmanager
def _db_guard(db: Session) -> Iterator[None]:
    """Turn any SQLAlchemy failure into a clean DatabaseError (and roll back the session)."""
    try:
        yield
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database operation failed")
        raise DatabaseError()


def get_patient(db: Session, patient_id: str) -> Patient:
    with _db_guard(db):
        patient = crud.get_active(db, patient_id)
    if patient is None:
        raise NotFoundError()
    return patient


def find_active_by_phone(db: Session, phone: str) -> Patient | None:
    with _db_guard(db):
        return crud.find_active_by_phone(db, phone)


def list_patients(
    db: Session,
    *,
    last_name: str | None,
    date_of_birth: str | None,
    phone_number: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Patient], int]:
    dob: date | None = None
    phone: str | None = None
    try:
        if date_of_birth:
            dob = normalize_dob(date_of_birth)
        if phone_number:
            phone = normalize_phone(phone_number)
    except ValueError as exc:
        raise AppError(400, "bad_filter", f"Invalid filter: {exc}")
    with _db_guard(db):
        return crud.list_active(
            db,
            last_name=(last_name or "").strip() or None,
            date_of_birth=dob,
            phone_number=phone,
            limit=limit,
            offset=offset,
        )


def create_patient(db: Session, data: PatientCreate, *, allow_duplicate: bool = True) -> Patient:
    """Create a patient. The voice flow passes allow_duplicate=False to avoid silent duplicates."""
    with _db_guard(db):
        if not allow_duplicate:
            existing = crud.find_active_by_phone(db, data.phone_number)
            if existing is not None:
                raise DuplicatePatientError(existing)
        return crud.create(db, data.model_dump())


def update_patient(db: Session, patient_id: str, data: PatientUpdate) -> Patient:
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise AppError(400, "empty_update", "No fields were provided to update")
    patient = get_patient(db, patient_id)
    with _db_guard(db):
        return crud.update(db, patient, changes)


def soft_delete_patient(db: Session, patient_id: str) -> Patient:
    patient = get_patient(db, patient_id)
    with _db_guard(db):
        return crud.soft_delete(db, patient)
