import pytest

from app import hip
from app.database import SessionLocal
from app.routers.portal import create_patient_account
from tests.conftest import login
from tests.test_api import register
from tests.test_clinical import MEDICINES, start_consultation
from tests.test_hiu import submit, verified_patient

PASSWORD = "Patient@2003"
ABHA = "ramesh.k@sbx"  # the address verified_patient() registers and verifies


@pytest.fixture(autouse=True)
def sim_registry():
    hip.sim_reset()
    yield
    hip.sim_reset()


def make_account(abha: str, name: str = "Ramesh Kumar") -> None:
    with SessionLocal() as db:
        create_patient_account(db, abha, name, PASSWORD)
        db.commit()


def test_abha_sign_in_shows_only_own_approved_records(client, admin):
    reception, doctor = login(client, "reception"), login(client, "dr.mehta")
    patient = verified_patient(client)
    other = register(client, reception, full_name="Someone Else", mobile="9123456780", abha_number=None,
                     abha_address=None).json()
    make_account(ABHA.upper())  # stored lower-case; sign-in is case-insensitive

    consult = start_consultation(client, doctor, patient["id"])
    client.put(f"/api/consultations/{consult['id']}", headers=doctor, json={
        "chief_complaint": "Fever", "doctor_notes": "PRIVATE NOTE",
        "diagnoses": [{"display": "Viral infection", "code": "B34.9"}]})
    rx = client.post("/api/prescriptions", headers=doctor, json={"encounter_id": consult["id"], "items": MEDICINES}).json()
    me = login(client, "Ramesh.K@sbx", PASSWORD)

    empty = client.get("/api/portal/me", headers=me).json()
    assert empty["abha_address"] == ABHA
    [record] = empty["hospitals"]
    assert record["hospital_name"] == "Test Hospital" and record["profile"]["full_name"] == patient["full_name"]
    assert record["visits"] == [] and record["prescriptions"] == []  # drafts stay hidden

    client.post(f"/api/prescriptions/{rx['id']}/submit", headers=doctor)
    client.post(f"/api/prescriptions/{rx['id']}/approve", headers=doctor)
    client.post(f"/api/consultations/{consult['id']}/finalize", headers=doctor)
    data = client.get("/api/portal/me", headers=me)
    [record] = data.json()["hospitals"]
    assert [v["chief_complaint"] for v in record["visits"]] == ["Fever"]
    assert len(record["prescriptions"]) == 1 and "PRIVATE NOTE" not in data.text

    who = client.get("/api/auth/me", headers=me).json()
    assert who["role_code"] == "patient" and who["permissions"] == ["portal:view"] and who["hospital_id"] is None
    for path in ["/api/patients", f"/api/patients/{other['id']}", f"/api/patients/{patient['id']}", "/api/dashboard",
                 "/api/consultations", "/api/staff", "/api/hiu/dashboard", f"/api/patients/{other['id']}/history"]:
        assert client.get(path, headers=me).status_code == 403, path
    staff = client.get("/api/staff", headers=admin, params={"page_size": 100}).json()
    assert ABHA not in [u["username"] for u in staff["items"]]
    assert client.get(f"/api/staff/{who['id']}", headers=admin).status_code == 404


def test_unverified_abha_shows_nothing(client):
    reception = login(client, "reception")
    register(client, reception, full_name="Claimed Name", mobile="9000000002", abha_number=None,
             abha_address="claimed@sbx")  # registered but never verified with ABDM
    make_account("claimed@sbx", "Claimed Name")
    assert client.get("/api/portal/me", headers=login(client, "claimed@sbx", PASSWORD)).json()["hospitals"] == []


def test_accounts_are_unique_and_staff_have_no_portal(client, admin):
    assert client.get("/api/portal/me", headers=admin).status_code == 403
    make_account("first@sbx")
    with SessionLocal() as db:
        for bad in ("FIRST@sbx", "no-at-sign"):
            with pytest.raises(ValueError):
                create_patient_account(db, bad, "X", PASSWORD)


def test_patient_answers_consent_requests(client):
    doctor = login(client, "dr.mehta")
    patient = verified_patient(client)
    make_account(ABHA)
    me = login(client, ABHA, PASSWORD)

    first = submit(client, doctor, patient).json()
    second = submit(client, doctor, patient).json()
    listed = client.get("/api/portal/consents", headers=me).json()
    assert [c["status"] for c in listed] == ["pending_consent"] * 2
    assert listed[0]["requester"] == "Dr. Anil Mehta" and listed[0]["purpose"] == "Care Management"

    granted = client.post(f"/api/portal/consents/{first['id']}/decide", headers=me,
                          json={"grant": True, "hi_types": ["DiagnosticReport"]})
    assert granted.status_code == 200, granted.text
    assert granted.json()["status"] == "received" and granted.json()["status_message"].startswith("2 record(s)")
    assert client.post(f"/api/portal/consents/{second['id']}/decide", headers=me, json={"grant": False}).json()["status"] == "denied"
    assert client.post(f"/api/portal/consents/{second['id']}/decide", headers=me, json={"grant": True}).status_code == 409
    assert client.post(f"/api/portal/consents/{second['id']}/revoke", headers=me).status_code == 409

    assert client.post(f"/api/portal/consents/{first['id']}/revoke", headers=me).json()["status"] == "revoked"
    assert client.get(f"/api/hiu/patients/{patient['id']}/records", headers=doctor).json()["records"] == []

    make_account("stranger@sbx", "Stranger")
    stranger = login(client, "stranger@sbx", PASSWORD)
    assert client.get("/api/portal/consents", headers=stranger).json() == []
    third = submit(client, doctor, patient).json()
    assert client.post(f"/api/portal/consents/{third['id']}/decide", headers=stranger, json={"grant": True}).status_code == 404


def test_staff_cannot_decide_consent_for_the_patient(client, monkeypatch):
    """Default setting: only the patient (portal) can grant, deny or revoke; staff simulation endpoints refuse."""
    from app.config import settings
    monkeypatch.setattr(settings, "allow_staff_consent_simulation", False)
    doctor, hims = login(client, "dr.mehta"), login(client, "hims")
    patient = verified_patient(client)
    request = submit(client, doctor, patient).json()
    for headers in (doctor, hims, login(client, "admin", "Admin1234")):
        for path, body in ((f"/api/hiu/simulate/requests/{request['id']}/decide", {"grant": True}),
                           (f"/api/hiu/simulate/requests/{request['id']}/decide", {"grant": False}),
                           (f"/api/hiu/simulate/requests/{request['id']}/revoke", None)):
            response = client.post(path, headers=headers, json=body)
            assert response.status_code == 403 and "Only the patient" in response.json()["detail"], (path, response.text)
    assert client.post("/api/hip/simulate/consent", headers=hims, json={
        "patient_id": patient["id"], "date_from": "2020-01-01", "date_to": "2030-01-01",
        "erase_at": "2030-01-01T00:00:00"}).status_code == 403
    assert client.get(f"/api/hiu/requests/{request['id']}", headers=doctor).json()["request"]["status"] == "pending_consent"

    make_account(ABHA)  # the patient themself can still decide
    granted = client.post(f"/api/portal/consents/{request['id']}/decide", headers=login(client, ABHA, PASSWORD), json={"grant": True})
    assert granted.status_code == 200 and granted.json()["status"] == "received"
