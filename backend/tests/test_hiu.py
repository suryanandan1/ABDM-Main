import uuid
from datetime import date, timedelta

import pytest

from app import hip, hiu
from app.database import SessionLocal
from app.models import HiuConsentRequest, RetrievedRecord, utcnow
from app.routers.fhir import validator_available
from tests.conftest import login
from tests.test_hip import register_abha

TODAY = date.today().isoformat()


@pytest.fixture(autouse=True)
def hiu_env():
    hip.sim_reset()
    yield
    hip.sim_reset()


def verified_patient(client):
    hims = login(client, "hims")
    patient = client.get("/api/patients?q=ramesh", headers=hims).json()["items"][0]
    client.patch(f"/api/patients/{patient['id']}", headers=login(client, "reception"), json={"abha_address": "ramesh.k@sbx"})
    register_abha(client, hims, patient, "ramesh.k@sbx")
    client.post(f"/api/hip/patients/{patient['id']}/link-token", headers=hims)
    return client.get(f"/api/patients/{patient['id']}", headers=hims).json()


def submit(client, headers, patient, **changes):
    body = {"patient_id": patient["id"], "purpose_code": "CAREMGT", "hi_types": ["DiagnosticReport", "Prescription"],
            "date_from": "2024-01-01", "date_to": TODAY, "reason": "Assess diabetes control", **changes}
    return client.post("/api/hiu/requests", headers=headers, json=body)


def decide(client, headers, request, **body):
    return client.post(f"/api/hiu/simulate/requests/{request['id']}/decide", headers=headers, json=body)


def test_complete_hiu_workflow(client):
    doctor, hims = login(client, "dr.mehta"), login(client, "hims")
    patient = verified_patient(client)
    assert patient["abha_verified"] and patient["abha_verification_method"] == "abdm_link_token"

    request = submit(client, doctor, patient).json()
    assert request["status"] == "pending_consent"
    granted = decide(client, doctor, request, grant=True, hi_types=["DiagnosticReport"]).json()
    assert granted["status"] == "received" and granted["status_message"].startswith("2 record(s)")
    detail = client.get(f"/api/hiu/requests/{request['id']}", headers=hims).json()
    [artefact] = detail["artefacts"]
    assert artefact["status"] == "valid" and artefact["hi_types"] == ["DiagnosticReport"] and artefact["hip_id"] == "SIM_EXT_HIP_01"
    assert detail["requester"] == "Dr. Anil Mehta" and detail["data_requests"][0]["status"] == "received"

    with SessionLocal() as db:
        rows = db.query(RetrievedRecord).all()
        assert len(rows) == 2 and {r.category for r in rows} == {"Lab report"}
        assert all(r.checksum_ok and "HbA1c" not in r.content for r in rows)
        original = hiu.bundle_json(rows[0])
        assert original["resourceType"] == "Bundle" and original["type"] == "document"

    view = client.get(f"/api/hiu/patients/{patient['id']}/records", headers=doctor).json()
    assert {r["validation_status"] for r in view["records"]} == {"not_validated"}
    assert [r["source_name"] for r in view["records"]] == ["Sunrise Clinic (SIMULATED)"] * 2
    [trend] = view["lab_trends"]
    assert trend["test"] == "HbA1c" and trend["comparable"] and trend["change"] == -0.9
    assert [p["value"] for p in trend["points"]] == [8.1, 7.2] and len(view["timeline"]) == 2
    one = client.get(f"/api/hiu/records/{view['records'][0]['id']}", headers=doctor).json()
    assert one["facts"]["reports"][0]["name"] == "HbA1c" and one["original"]["entry"][0]["resource"]["resourceType"] == "Composition"
    assert client.get(f"/api/hiu/patients/{patient['id']}/records", headers=hims).status_code == 403
    assert client.get("/api/hiu/requests", headers=login(client, "reception")).status_code == 403
    audit = client.get("/api/audit-logs?action=hiu.record", headers=login(client, "admin", "Admin1234")).json()
    assert {i["action"] for i in audit["items"]} == {"hiu.records_view", "hiu.record_view"}
    dashboard = client.get("/api/hiu/dashboard", headers=hims).json()
    assert dashboard["requests"] == {"received": 1} and dashboard["records"] == 2


def test_request_rules(client):
    doctor, hims = login(client, "dr.mehta"), login(client, "hims")
    unverified = client.get("/api/patients?q=sita", headers=doctor).json()["items"][0]
    refused = submit(client, doctor, unverified)
    assert refused.status_code == 422 and "verified" in refused.json()["detail"]
    patient = verified_patient(client)
    assert submit(client, doctor, patient, hi_types=["Everything"]).status_code == 422
    assert submit(client, doctor, patient, date_from="2030-01-01", date_to="2031-01-01").status_code == 422
    assert submit(client, hims, patient).status_code == 403
    on_behalf = submit(client, hims, patient, requester_doctor_id=2).json()
    assert client.get(f"/api/hiu/requests/{on_behalf['id']}", headers=hims).json()["requester"] == "Dr. Sunita Rao"


def test_denied_consent_stops_everything(client):
    doctor = login(client, "dr.mehta")
    request = submit(client, doctor, verified_patient(client)).json()
    denied = decide(client, doctor, request, grant=False, reason="Not now").json()
    assert denied["status"] == "denied" and "Not now" in denied["status_message"]
    assert decide(client, doctor, request, grant=True).status_code == 409
    assert client.get(f"/api/hiu/requests/{request['id']}", headers=doctor).json()["artefacts"] == []
    with SessionLocal() as db:
        assert db.query(RetrievedRecord).count() == 0


def test_revocation_and_expiry_erase_records(client):
    doctor = login(client, "dr.mehta")
    patient = verified_patient(client)
    request = submit(client, doctor, patient).json()
    decide(client, doctor, request, grant=True)
    with SessionLocal() as db:
        assert db.query(RetrievedRecord).count() == 3
    revoked = client.post(f"/api/hiu/simulate/requests/{request['id']}/revoke", headers=doctor).json()
    assert revoked["status"] == "revoked"
    assert client.get(f"/api/hiu/patients/{patient['id']}/records", headers=doctor).json()["records"] == []

    second = submit(client, doctor, patient).json()
    decide(client, doctor, second, grant=True)
    with SessionLocal() as db:
        for row in db.query(RetrievedRecord).all():
            row.erase_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert client.get(f"/api/hiu/patients/{patient['id']}/records", headers=doctor).json()["records"] == []


def test_artefact_and_data_rules(client):
    doctor = login(client, "dr.mehta")
    request_out = submit(client, doctor, verified_patient(client)).json()
    with SessionLocal() as db:
        request = db.get(HiuConsentRequest, request_out["id"])
        good = {"hiu": {"id": "SIM_HIU_LOCAL"}, "patient": {"id": "ramesh.k@sbx"}, "hip": {"id": "H"}, "hiTypes": ["Prescription"],
                "purpose": {"code": "CAREMGT"}, "careContexts": [{"careContextReference": "c"}],
                "permission": {"dateRange": {"from": "2024-06-01T00:00:00Z", "to": f"{TODAY}T10:00:00Z"},
                               "dataEraseAt": "2099-01-01T00:00:00Z"}}
        accept = lambda **change: hiu.accept_artefact(db, request, {**good, "consentId": str(uuid.uuid4()), **change}, "H")
        artefact = accept()
        assert artefact.status == "valid"
        cases = {"it is for a different HIU": {"hiu": {"id": "OTHER"}},
                 "it is for a different patient": {"patient": {"id": "x@sbx"}},
                 "it covers types that were not requested": {"hiTypes": ["DischargeSummary"]},
                 "its purpose differs from the request": {"purpose": {"code": "BTG"}},
                 "its date range is wider than requested": {"permission": {**good["permission"], "dateRange": {
                     "from": "2010-01-01T00:00:00Z", "to": f"{TODAY}T00:00:00Z"}}},
                 "it has already expired": {"permission": {**good["permission"], "dataEraseAt": "2001-01-01T00:00:00Z"}}}
        for message, change in cases.items():
            assert accept(**change).status_message == f"Artefact not accepted: {message}"

        db.flush()
        foreign = {"transactionId": "t", "keyMaterial": {"dhPublicKey": {"keyValue": "AA=="}, "nonce": "AA=="},
                   "entries": [{"careContextReference": "NOT-IN-CONSENT", "content": "x", "checksum": "y"}]}
        received = hiu.request_data(db, artefact, lambda keys: foreign)
        assert received.status_message == "0 record(s) received and stored; 1 refused"
        failed = hiu.request_data(db, artefact, lambda keys: {"error": "Request refused: consent not active"})
        assert failed.status == "failed" and "consent not active" in failed.status_message
        assert db.query(RetrievedRecord).count() == 0
        db.rollback()


@pytest.mark.skipif(not validator_available(), reason="HL7 validator not installed")
def test_hl7_validation_of_retrieved_record(client):
    doctor = login(client, "dr.mehta")
    patient = verified_patient(client)
    request = submit(client, doctor, patient, hi_types=["DiagnosticReport"]).json()
    decide(client, doctor, request, grant=True)
    record = client.get(f"/api/hiu/patients/{patient['id']}/records", headers=doctor).json()["records"][0]
    validated = client.post(f"/api/hiu/records/{record['id']}/validate", headers=doctor).json()
    assert validated["validation_status"] == "valid"
