"""Application exceptions that map cleanly onto the JSON error envelope."""
from __future__ import annotations


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class NotFoundError(AppError):
    def __init__(self, message: str = "Patient not found"):
        super().__init__(404, "not_found", message)


class DuplicatePatientError(AppError):
    """Raised only when a caller asked us not to create duplicates (voice flow)."""

    def __init__(self, existing):
        super().__init__(409, "duplicate_phone", "An active patient with this phone number already exists")
        self.existing = existing


class DatabaseError(AppError):
    def __init__(self):
        super().__init__(500, "database_error", "A database error occurred. Please try again.")
