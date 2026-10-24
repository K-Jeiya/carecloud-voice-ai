from datetime import timedelta

import pytest

from app.validators import (
    normalize_dob, normalize_email, normalize_member_id, normalize_name, normalize_phone,
    normalize_sex, normalize_state, normalize_zip, today_utc, clean_text,
)


@pytest.mark.parametrize("raw,expected", [("davis", "Davis"), ("O'Brien", "O'Brien"),
                                           ("Mary-Jane", "Mary-Jane"), ("McDonald", "McDonald"),
                                           ("  Anne   Marie ", "Anne Marie"), ("o\u2019neil", "O'Neil")])
def test_valid_names(raw, expected):
    assert normalize_name(raw, "first name") == expected


@pytest.mark.parametrize("raw", ["", "   ", "J4ne", "Jane!", "a" * 51, "-Jane", "Jane_"])
def test_invalid_names(raw):
    with pytest.raises(ValueError):
        normalize_name(raw, "first name")


def test_dob_formats_and_rules():
    assert normalize_dob("03/04/1990").isoformat() == "1990-03-04"
    assert normalize_dob("1990-03-04").isoformat() == "1990-03-04"
    with pytest.raises(ValueError, match="future"):
        normalize_dob((today_utc() + timedelta(days=1)).strftime("%m/%d/%Y"))
    with pytest.raises(ValueError):
        normalize_dob("02/30/1990")
    with pytest.raises(ValueError, match="four-digit"):
        normalize_dob("03/04/90")
    with pytest.raises(ValueError):
        normalize_dob("")
    with pytest.raises(ValueError, match="1900"):
        normalize_dob("01/01/1850")


@pytest.mark.parametrize("raw", ["(202) 555-0101", "202-555-0101", "+1 202 555 0101", "12025550101", "2025550101"])
def test_phone_normalization(raw):
    assert normalize_phone(raw) == "2025550101"


@pytest.mark.parametrize("raw", ["123", "202555010", "202555010199", "0025550101", "abc", ""])
def test_invalid_phone(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_optional_phone_blank_is_none():
    assert normalize_phone("", required=False) is None
    assert normalize_phone(None, required=False) is None


def test_state():
    assert normalize_state("ca") == "CA"
    assert normalize_state("California") == "CA"
    for bad in ["XX", "C", "", "USA"]:
        with pytest.raises(ValueError):
            normalize_state(bad)


@pytest.mark.parametrize("raw,expected", [("12345", "12345"), ("12345-6789", "12345-6789"), ("123456789", "12345-6789")])
def test_zip_ok(raw, expected):
    assert normalize_zip(raw) == expected


@pytest.mark.parametrize("raw", ["1234", "123456", "ABCDE", "12345-67", ""])
def test_zip_bad(raw):
    with pytest.raises(ValueError):
        normalize_zip(raw)


def test_email():
    assert normalize_email("Jane.Doe@Example.com") == "jane.doe@example.com"
    assert normalize_email("") is None
    for bad in ["jane", "jane@", "@example.com", "jane@example", "a..b@example.com", "jane@exa mple..com"]:
        with pytest.raises(ValueError):
            normalize_email(bad)


def test_sex_aliases():
    assert normalize_sex("female") == "Female"
    assert normalize_sex("prefer not to say") == "Decline to Answer"
    with pytest.raises(ValueError):
        normalize_sex("robot")


def test_member_id():
    assert normalize_member_id("abc-123 456") == "ABC123456"
    assert normalize_member_id("") is None
    with pytest.raises(ValueError):
        normalize_member_id("abc$123")


def test_sanitization_strips_markup_and_control_chars():
    assert clean_text("<script>alert(1)</script>\x00 hi") == "scriptalert(1)/script hi"
