"""Tests for the Vapi tool-call webhook (the real integration path, no network needed)."""
import json


def call_tool(client, name, args, call_id="call-1", tool_call_id="tc-1"):
    payload = {"message": {"type": "tool-calls", "call": {"id": call_id},
                           "toolCallList": [{"id": tool_call_id, "name": name, "arguments": args}]}}
    r = client.post("/voice/webhook", json=payload)
    assert r.status_code == 200
    results = r.json()["results"]
    assert results[0]["toolCallId"] == tool_call_id
    assert "\n" not in results[0]["result"]            # Vapi wants a single-line string
    return json.loads(results[0]["result"])


FIELDS = {"first_name": "Jane", "last_name": "Synthetic", "date_of_birth": "03/04/1990", "sex": "female",
          "phone_number": "2025550101", "address_line_1": "100 Demo Street", "city": "Springfield",
          "state": "Illinois", "zip_code": "62701"}


def test_validate_reports_only_bad_and_missing_fields(client):
    out = call_tool(client, "validate_patient_fields",
                    {"first_name": "Jane", "date_of_birth": "01/01/2999", "phone_number": "123"})
    assert out["valid"] is False and out["ready_to_confirm"] is False
    assert set(out["errors"]) == {"date_of_birth", "phone_number"}
    assert "future" in out["errors"]["date_of_birth"]
    assert "last_name" in out["missing_required_fields"] and "first_name" not in out["missing_required_fields"]


def test_validate_ready_to_confirm(client):
    out = call_tool(client, "validate_patient_fields", FIELDS)
    assert out["ready_to_confirm"] is True and out["errors"] == {}
    assert out["normalized"]["state"] == "IL" and out["normalized"]["date_of_birth"] == "03/04/1990"


def test_register_requires_explicit_confirmation(client):
    out = call_tool(client, "register_patient", {**FIELDS, "caller_confirmed": False})
    assert out["success"] is False and out["error_code"] == "not_confirmed"
    assert client.get("/patients").json()["meta"]["total"] == 0


def test_register_success_persists_and_is_retrievable(client):
    out = call_tool(client, "register_patient", {**FIELDS, "caller_confirmed": True})
    assert out["success"] is True and out["first_name"] == "Jane"
    got = client.get(f"/patients/{out['patient_id']}").json()["data"]
    assert got["last_name"] == "Synthetic" and got["state"] == "IL"
    calls = client.get(f"/patients/{out['patient_id']}/calls").json()["data"]
    assert calls[0]["call_id"] == "call-1" and calls[0]["action"] == "created"


def test_register_invalid_data_is_rejected_by_backend(client):
    out = call_tool(client, "register_patient",
                    {**FIELDS, "phone_number": "12", "zip_code": "9", "caller_confirmed": True})
    assert out["success"] is False and out["error_code"] == "validation_error"
    assert set(out["errors"]) == {"phone_number", "zip_code"}


def test_duplicate_phone_detection_and_update_flow(client):
    first = call_tool(client, "register_patient", {**FIELDS, "caller_confirmed": True})
    pid = first["patient_id"]

    found = call_tool(client, "lookup_patient_by_phone", {"phone_number": "(202) 555-0101"})
    assert found["found"] is True and found["patient_id"] == pid and found["last_name"] == "Synthetic"
    assert call_tool(client, "lookup_patient_by_phone", {"phone_number": "3035550000"})["found"] is False
    assert call_tool(client, "lookup_patient_by_phone", {"phone_number": "12"})["valid_phone"] is False

    dup = call_tool(client, "register_patient", {**FIELDS, "first_name": "Other", "caller_confirmed": True})
    assert dup["success"] is False and dup["error_code"] == "duplicate_phone"
    assert client.get("/patients").json()["meta"]["total"] == 1

    shared = call_tool(client, "register_patient",
                       {**FIELDS, "first_name": "Other", "caller_confirmed": True, "allow_shared_phone": True})
    assert shared["success"] is True

    # update requires confirmation and never overwrites without it
    no = call_tool(client, "update_existing_patient", {"patient_id": pid, "city": "Chicago", "caller_confirmed": False})
    assert no["success"] is False
    assert client.get(f"/patients/{pid}").json()["data"]["city"] == "Springfield"
    yes = call_tool(client, "update_existing_patient", {"patient_id": pid, "city": "Chicago", "caller_confirmed": True})
    assert yes["success"] is True
    assert client.get(f"/patients/{pid}").json()["data"]["city"] == "Chicago"
    bad = call_tool(client, "update_existing_patient", {"patient_id": pid, "zip_code": "x", "caller_confirmed": True})
    assert bad["error_code"] == "validation_error"
    missing = call_tool(client, "update_existing_patient",
                        {"patient_id": "00000000-0000-0000-0000-000000000000", "city": "X", "caller_confirmed": True})
    assert missing["error_code"] == "not_found"


def test_failed_db_write_returns_graceful_retryable_error(client, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app import crud

    def fail(*a, **k):
        raise OperationalError("insert", {}, Exception("db down"))

    monkeypatch.setattr(crud, "create", fail)
    out = call_tool(client, "register_patient", {**FIELDS, "caller_confirmed": True})
    assert out["success"] is False and out["retryable"] is True and out["error_code"] == "database_error"
    assert "apologize" in out["instruction"].lower()


def test_unknown_tool_and_string_arguments_and_multiple_calls(client):
    payload = {"message": {"type": "tool-calls", "call": {"id": "c9"}, "toolCallList": [
        {"id": "a", "name": "nope", "arguments": {}},
        {"id": "b", "name": "validate_patient_fields", "arguments": json.dumps({"first_name": "Jo"})},
    ]}}
    results = client.post("/voice/webhook", json=payload).json()["results"]
    assert [r["toolCallId"] for r in results] == ["a", "b"]
    assert json.loads(results[0]["result"])["error_code"] == "unknown_tool"
    assert json.loads(results[1]["result"])["normalized"] == {"first_name": "Jo"}


def test_end_of_call_report_is_stored(client):
    out = call_tool(client, "register_patient", {**FIELDS, "caller_confirmed": True}, call_id="call-end")
    r = client.post("/voice/webhook", json={"message": {
        "type": "end-of-call-report", "call": {"id": "call-end"}, "endedReason": "customer-ended-call",
        "summary": "Registered a patient.", "transcript": "AI: Hi\nUser: Hello"}})
    assert r.status_code == 200
    log = client.get(f"/patients/{out['patient_id']}/calls").json()["data"][0]
    assert log["summary"] == "Registered a patient." and log["ended_reason"] == "customer-ended-call"


def test_other_message_types_are_acknowledged(client):
    assert client.post("/voice/webhook", json={"message": {"type": "status-update"}}).status_code == 200


def test_webhook_secret_enforced_when_configured(client, monkeypatch):
    monkeypatch.setenv("VAPI_SERVER_SECRET", "topsecret")
    body = {"message": {"type": "status-update"}}
    assert client.post("/voice/webhook", json=body).status_code == 401
    assert client.post("/voice/webhook", json=body, headers={"X-Vapi-Secret": "topsecret"}).status_code == 200
    assert client.post("/voice/webhook", json=body, headers={"Authorization": "Bearer topsecret"}).status_code == 200
