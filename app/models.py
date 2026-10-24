"""SQLAlchemy models. Constraints are enforced in the DB as well as in Pydantic."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    sex: Mapped[str] = mapped_column(String(20), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(10), nullable=False)  # 10 digits, normalized
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    address_line_1: Mapped[str] = mapped_column(String(100), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False)
    insurance_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    insurance_member_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(50), nullable=False, default="English")
    emergency_contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("length(first_name) BETWEEN 1 AND 50", name="ck_patients_first_name_len"),
        CheckConstraint("length(last_name) BETWEEN 1 AND 50", name="ck_patients_last_name_len"),
        CheckConstraint(
            "sex IN ('Male', 'Female', 'Other', 'Decline to Answer')", name="ck_patients_sex"
        ),
        CheckConstraint("length(phone_number) = 10", name="ck_patients_phone_len"),
        CheckConstraint("length(state) = 2", name="ck_patients_state_len"),
        CheckConstraint("length(city) BETWEEN 1 AND 100", name="ck_patients_city_len"),
        CheckConstraint("length(address_line_1) >= 1", name="ck_patients_addr1_len"),
        CheckConstraint(
            "emergency_contact_phone IS NULL OR length(emergency_contact_phone) = 10",
            name="ck_patients_ec_phone_len",
        ),
        Index("ix_patients_last_name", "last_name"),
        Index("ix_patients_phone_number", "phone_number"),
        Index("ix_patients_date_of_birth", "date_of_birth"),
        Index("ix_patients_deleted_at", "deleted_at"),
    )


class CallLog(Base):
    """Bonus: one row per voice call (summary + transcript), linked to the patient it created/updated."""

    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    patient_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("patients.patient_id"), nullable=True, index=True
    )
    action: Mapped[str | None] = mapped_column(String(20), nullable=True)  # created | updated
    ended_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
