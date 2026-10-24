"""Pure validation/normalization functions (no framework imports).

They are shared by the REST API (via Pydantic), the voice-tool handlers, and the tests, so the
backend is the single authority on what counts as valid data. Each function either returns the
normalized value or raises ValueError with a caller-friendly message.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from functools import partial
from typing import Any, Callable

SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")

STATE_NAMES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA",
    "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR",
    "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA",
    "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "PUERTO RICO": "PR", "GUAM": "GU", "US VIRGIN ISLANDS": "VI", "AMERICAN SAMOA": "AS",
    "NORTHERN MARIANA ISLANDS": "MP",
}
US_STATES = frozenset(STATE_NAMES.values())

_LETTER = r"[^\W\d_]"  # any unicode letter
NAME_RE = re.compile(rf"^{_LETTER}+(?:[ '\-]{_LETTER}+)*$")
CITY_RE = re.compile(rf"^{_LETTER}(?:{_LETTER}|[ .'\-])*$")
LANGUAGE_RE = re.compile(rf"^{_LETTER}+(?:[ \-]{_LETTER}+)*$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
MEMBER_ID_RE = re.compile(r"^[A-Za-z0-9]+$")

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_DOB_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y")


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


# --------------------------------------------------------------------------- helpers
def clean_text(value: Any) -> str:
    """Basic sanitization: to str, drop control chars and angle brackets, normalize quotes/spaces."""
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("must be text")
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = _CONTROL_RE.sub(" ", text).replace("<", "").replace(">", "")
    return re.sub(r"\s+", " ", text).strip()


def _fix_case(text: str) -> str:
    """'davis' / 'DAVIS' -> 'Davis'; leave mixed case ('McDonald', 'De La Cruz') alone."""
    return text.title() if (text.islower() or text.isupper()) else text


def _text(value: Any, label: str, *, required: bool, max_len: int) -> str | None:
    text = clean_text(value)
    if not text:
        if required:
            raise ValueError(f"{label} is required")
        return None
    if len(text) > max_len:
        raise ValueError(f"{label} must be at most {max_len} characters")
    return text


# --------------------------------------------------------------------------- field normalizers
def normalize_name(value: Any, label: str, *, required: bool = True, max_len: int = 50) -> str | None:
    text = _text(value, label, required=required, max_len=max_len)
    if text is None:
        return None
    if not NAME_RE.match(text):
        raise ValueError(f"{label} may only contain letters, spaces, hyphens and apostrophes")
    return _fix_case(text)


def normalize_dob(value: Any) -> date:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = clean_text(value)
        if not text:
            raise ValueError("date of birth is required")
        if re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2}$", text):
            raise ValueError("date of birth needs a four-digit year (MM/DD/YYYY)")
        parsed = None
        for fmt in _DOB_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError("date of birth must be a real calendar date in MM/DD/YYYY format")
    if parsed > today_utc():
        raise ValueError("date of birth cannot be in the future")
    if parsed.year < 1900:
        raise ValueError("date of birth cannot be before 1900")
    return parsed


_SEX_ALIASES = {
    "male": "Male", "m": "Male", "man": "Male", "boy": "Male",
    "female": "Female", "f": "Female", "woman": "Female", "girl": "Female",
    "other": "Other", "non-binary": "Other", "nonbinary": "Other", "non binary": "Other",
    "decline to answer": "Decline to Answer", "decline": "Decline to Answer",
    "prefer not to say": "Decline to Answer", "prefer not to answer": "Decline to Answer",
    "rather not say": "Decline to Answer", "rather not answer": "Decline to Answer",
}


def normalize_sex(value: Any) -> str:
    text = clean_text(value)
    if not text:
        raise ValueError("sex is required")
    result = _SEX_ALIASES.get(text.lower())
    if not result:
        raise ValueError("sex must be one of: Male, Female, Other, Decline to Answer")
    return result


def normalize_phone(value: Any, label: str = "phone number", *, required: bool = True) -> str | None:
    text = clean_text(value)
    if not text:
        if required:
            raise ValueError(f"{label} is required")
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError(f"{label} must be a valid US 10-digit phone number (got {len(digits)} digits)")
    if digits[0] in "01":
        raise ValueError(f"{label} has an invalid area code")
    return digits


def normalize_email(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = text.replace(" ", "")
    if len(text) > 254 or ".." in text or not EMAIL_RE.match(text):
        raise ValueError("email is not a valid email address")
    return text.lower()


def normalize_address_line(value: Any, label: str, *, required: bool) -> str | None:
    text = _text(value, label, required=required, max_len=100)
    if text is not None and not re.search(r"[A-Za-z0-9]", text):
        raise ValueError(f"{label} must contain letters or numbers")
    return text


def normalize_city(value: Any) -> str:
    text = _text(value, "city", required=True, max_len=100)
    assert text is not None
    if not CITY_RE.match(text):
        raise ValueError("city may only contain letters, spaces, periods, hyphens and apostrophes")
    return _fix_case(text)


def normalize_state(value: Any) -> str:
    text = clean_text(value).upper().replace(".", "")
    if not text:
        raise ValueError("state is required")
    if text in STATE_NAMES:  # caller said "California" -> CA
        return STATE_NAMES[text]
    if text not in US_STATES:
        raise ValueError("state must be a valid two-letter US state abbreviation (e.g. CA, NY)")
    return text


def normalize_zip(value: Any) -> str:
    text = clean_text(value).replace(" ", "")
    if not text:
        raise ValueError("zip code is required")
    if re.fullmatch(r"\d{9}", text):
        text = f"{text[:5]}-{text[5:]}"
    if not ZIP_RE.match(text):
        raise ValueError("zip code must be 5 digits or ZIP+4 (12345 or 12345-6789)")
    return text


def normalize_optional_text(value: Any, label: str, max_len: int = 100) -> str | None:
    return _text(value, label, required=False, max_len=max_len)


def normalize_member_id(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"[\s\-]", "", text).upper()
    if len(text) > 50 or not MEMBER_ID_RE.match(text):
        raise ValueError("insurance member ID must be alphanumeric (max 50 characters)")
    return text


def normalize_language(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return "English"
    if len(text) > 50 or not LANGUAGE_RE.match(text):
        raise ValueError("preferred language must be a language name such as English or Spanish")
    return _fix_case(text)


# --------------------------------------------------------------------------- registry
REQUIRED_FIELDS: tuple[str, ...] = (
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
)
OPTIONAL_FIELDS: tuple[str, ...] = (
    "email", "address_line_2", "insurance_provider", "insurance_member_id",
    "preferred_language", "emergency_contact_name", "emergency_contact_phone",
)
ALL_FIELDS: tuple[str, ...] = REQUIRED_FIELDS + OPTIONAL_FIELDS

NORMALIZERS: dict[str, Callable[[Any], Any]] = {
    "first_name": partial(normalize_name, label="first name"),
    "last_name": partial(normalize_name, label="last name"),
    "date_of_birth": normalize_dob,
    "sex": normalize_sex,
    "phone_number": partial(normalize_phone, label="phone number", required=True),
    "email": normalize_email,
    "address_line_1": partial(normalize_address_line, label="address line 1", required=True),
    "address_line_2": partial(normalize_address_line, label="address line 2", required=False),
    "city": normalize_city,
    "state": normalize_state,
    "zip_code": normalize_zip,
    "insurance_provider": partial(normalize_optional_text, label="insurance provider"),
    "insurance_member_id": normalize_member_id,
    "preferred_language": normalize_language,
    "emergency_contact_name": partial(normalize_name, label="emergency contact name", required=False, max_len=100),
    "emergency_contact_phone": partial(normalize_phone, label="emergency contact phone", required=False),
}
