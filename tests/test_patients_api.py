import uuid


def create(client, payload, **overrides):
    return client.post("/patients", json={**payload, **overrides})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"data": {"status": "ok", "database": "ok"}, "error": None}


def test_create_returns_201_and_normalized_envelope(client, valid_payload):
    r = create(client, valid_payload)
    assert r.status_code == 201
    body = r.json()
    assert body["error"] is None
    p = body["data"]
    assert uuid.UUID(p["patient_id"])
    assert p["phone_number"] == "2025550101"          # normalized
    assert p["state"] == "IL"                         # upper-cased
    assert p["date_of_birth"] == "1990-03-04"
    assert p["preferred_language"] == "English"       # default
    assert p["email"] is None and p["deleted_at"] is None
    assert p["created_at"].endswith("Z") and p["updated_at"].endswith("Z")


def test_optional_fields_can_be_provided(client, valid_payload):
    r = create(client, valid_payload, email="Jane@Example.com", insurance_provider="Demo Health",
               insurance_member_id="abc-123", emergency_contact_name="Joe Synthetic",
               emergency_contact_phone="202-555-0199", address_line_2="Apt 2", preferred_language="spanish")
    assert r.status_code == 201
    d = r.json()["data"]
    assert d["email"] == "jane@example.com" and d["insurance_member_id"] == "ABC123"
    assert d["emergency_contact_phone"] == "2025550199" and d["preferred_language"] == "Spanish"


def test_get_by_id_and_404s(client, valid_payload):
    pid = create(client, valid_payload).json()["data"]["patient_id"]
    assert client.get(f"/patients/{pid}").json()["data"]["first_name"] == "Jane"
    r = client.get(f"/patients/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.json()["data"] is None and r.json()["error"]["code"] == "not_found"


def test_invalid_uuid_is_400(client):
    r = client.get("/patients/not-a-uuid")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_id"


def test_validation_errors_are_422_with_details(client, valid_payload):
    bad = {**valid_payload, "phone_number": "123", "state": "XX", "zip_code": "1", "email": "nope",
           "date_of_birth": "01/01/2999", "sex": "robot"}
    r = create(client, bad)
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"phone_number", "state", "zip_code", "email", "date_of_birth", "sex"} <= fields
    assert "Traceback" not in r.text


def test_missing_required_field_is_422(client, valid_payload):
    valid_payload.pop("last_name")
    r = create(client, valid_payload)
    assert r.status_code == 422
    assert any(d["field"] == "last_name" for d in r.json()["error"]["details"])


def test_cannot_inject_server_managed_fields(client, valid_payload):
    r = create(client, valid_payload, patient_id=str(uuid.uuid4()), deleted_at="2020-01-01T00:00:00Z")
    assert r.status_code == 422


def test_malformed_json_is_400(client):
    r = client.post("/patients", content="{bad json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "malformed_json"


def test_list_filters_and_pagination(client, valid_payload):
    create(client, valid_payload)
    create(client, valid_payload, first_name="Bob", last_name="Smith", phone_number="3035550102",
           date_of_birth="01/02/1980")
    create(client, valid_payload, first_name="Ann", last_name="Smithers", phone_number="4045550103")

    allp = client.get("/patients").json()
    assert allp["meta"]["total"] == 3 and len(allp["data"]) == 3

    by_last = client.get("/patients", params={"last_name": "smith"}).json()["data"]
    assert {p["last_name"] for p in by_last} == {"Smith", "Smithers"}
    assert client.get("/patients", params={"last_name": "%"}).json()["meta"]["total"] == 0  # wildcard escaped

    by_dob = client.get("/patients", params={"date_of_birth": "01/02/1980"}).json()["data"]
    assert [p["first_name"] for p in by_dob] == ["Bob"]
    assert client.get("/patients", params={"date_of_birth": "1980-01-02"}).json()["meta"]["total"] == 1

    by_phone = client.get("/patients", params={"phone_number": "(303) 555-0102"}).json()["data"]
    assert [p["first_name"] for p in by_phone] == ["Bob"]

    page = client.get("/patients", params={"limit": 2, "offset": 2}).json()
    assert len(page["data"]) == 1 and page["meta"] == {"total": 3, "limit": 2, "offset": 2}

    assert client.get("/patients", params={"phone_number": "12"}).status_code == 400
    assert client.get("/patients", params={"date_of_birth": "garbage"}).status_code == 400
    assert client.get("/patients", params={"limit": 0}).status_code == 422


def test_partial_update(client, valid_payload):
    created = create(client, valid_payload).json()["data"]
    pid = created["patient_id"]
    r = client.put(f"/patients/{pid}", json={"city": "Chicago", "email": "new@example.com"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["city"] == "Chicago" and d["email"] == "new@example.com"
    assert d["first_name"] == "Jane"                       # untouched
    assert d["updated_at"] >= created["updated_at"]
    # optional field can be cleared with null
    d = client.put(f"/patients/{pid}", json={"email": None}).json()["data"]
    assert d["email"] is None


def test_update_validation_and_errors(client, valid_payload):
    pid = create(client, valid_payload).json()["data"]["patient_id"]
    assert client.put(f"/patients/{pid}", json={"zip_code": "abc"}).status_code == 422
    assert client.put(f"/patients/{pid}", json={"first_name": None}).status_code == 422  # required stays required
    assert client.put(f"/patients/{pid}", json={}).status_code == 400
    assert client.put(f"/patients/{uuid.uuid4()}", json={"city": "X"}).status_code == 404


def test_soft_delete_behaviour(client, valid_payload, session_factory):
    pid = create(client, valid_payload).json()["data"]["patient_id"]
    r = client.delete(f"/patients/{pid}")
    assert r.status_code == 200 and r.json()["data"]["patient_id"] == pid and r.json()["data"]["deleted_at"]
    assert client.get(f"/patients/{pid}").status_code == 404
    assert client.get("/patients").json()["meta"]["total"] == 0
    assert client.put(f"/patients/{pid}", json={"city": "X"}).status_code == 404
    assert client.delete(f"/patients/{pid}").status_code == 404
    # the row still exists in the database (never hard-deleted)
    from app.models import Patient
    with session_factory() as db:
        row = db.get(Patient, pid)
        assert row is not None and row.deleted_at is not None


def test_unhandled_error_returns_500_without_details(client, monkeypatch):
    from app.services import patient_service

    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(patient_service, "list_patients", boom)
    r = client.get("/patients")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in r.text


def test_database_error_is_500_envelope(client, valid_payload, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app import crud

    def fail(*a, **k):
        raise OperationalError("insert", {}, Exception("disk I/O error with /srv/path"))

    monkeypatch.setattr(crud, "create", fail)
    r = client.post("/patients", json=valid_payload)
    assert r.status_code == 500 and r.json()["error"]["code"] == "database_error"
    assert "/srv/path" not in r.text


def test_api_key_enforced_when_configured(client, monkeypatch, valid_payload):
    monkeypatch.setenv("API_KEY", "s3cret")
    assert client.get("/patients").status_code == 401
    assert client.get("/patients", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/patients", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # health stays open
