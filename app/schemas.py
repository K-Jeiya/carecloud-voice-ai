"""Pydantic request/response models. Validation is delegated to app.validators."""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from app.validators import ALL_FIELDS, NORMALIZERS


class Sex(str, Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    DECLINE = "Decline to Answer"


class _NormalizedInput(BaseModel):
    """Base for input models: every field runs through its normalizer before type coercion.

    extra="forbid" stops clients from injecting patient_id / created_at / deleted_at.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    @field_validator(*ALL_FIELDS, mode="before", check_fields=False)
    @classmethod
    def _normalize(cls, value: Any, info) -> Any:
        return NORMALIZERS[info.field_name](value)


class PatientCreate(_NormalizedInput):
    first_name: str
    last_name: str
    date_of_birth: date
    sex: Sex
    phone_number: str
    email: Optional[str] = None
    address_line_1: str
    address_line_2: Optional[str] = None
    city: str
    state: str
    zip_code: str
    insurance_provider: Optional[str] = None
    insurance_member_id: Optional[str] = None
    preferred_language: str = "English"
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class PatientUpdate(_NormalizedInput):
    """Partial update: only fields present in the request body are changed."""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    sex: Optional[Sex] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_member_id: Optional[str] = None
    preferred_language: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


def _as_utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:  # SQLite returns naive datetimes; we always store UTC
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: str
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: Optional[str] = None
    address_line_1: str
    address_line_2: Optional[str] = None
    city: str
    state: str
    zip_code: str
    insurance_provider: Optional[str] = None
    insurance_member_id: Optional[str] = None
    preferred_language: str
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    @field_serializer("created_at", "updated_at", "deleted_at")
    def _ser_dt(self, value: datetime | None) -> str | None:
        return _as_utc_iso(value)


class DeleteResult(BaseModel):
    patient_id: str
    deleted_at: datetime

    @field_serializer("deleted_at")
    def _ser_dt(self, value: datetime) -> str | None:
        return _as_utc_iso(value)


class CallLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    call_id: str
    patient_id: Optional[str] = None
    action: Optional[str] = None
    ended_reason: Optional[str] = None
    summary: Optional[str] = None
    transcript: Optional[str] = None
    created_at: datetime

    @field_serializer("created_at")
    def _ser_dt(self, value: datetime) -> str | None:
        return _as_utc_iso(value)


# ---- Response envelopes: {"data": ..., "error": null} -------------------------------------
T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[list[dict[str, str]]] = None


class Envelope(BaseModel, Generic[T]):
    data: Optional[T] = None
    error: Optional[ErrorBody] = None


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


class ListEnvelope(BaseModel, Generic[T]):
    data: list[T]
    error: Optional[ErrorBody] = None
    meta: PageMeta
