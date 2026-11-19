import base64
import json
import uuid

import pytest

from app import hip
from app.database import SessionLocal
from app.models import FhirRecord, HipPatientLink, Hospital
from tests.conftest import login
from tests.test_clinical import MEDICINES, start_consultation


@pytest.fixture(autouse=True)
def clean_hip():
    hip.sim_reset()
    yield
    hip.sim_reset()


def shareable_prescription(client, abha_address=None):
    doctor, hims = login(client, "dr.mehta"), login(client, "hims")
    patient = client.get("/api/patients?q=ramesh", headers=hims).json()["items"][0]
    if abha_address:
        client.patch(f"/api/patients/{patient['id']}", headers=login(client, "reception"), json={"abha_address": abha_address})
    consult = start_consultation(client, doctor, patient["id"])
    rx = client.post("/api/prescriptions", headers=doctor, json={"encounter_id": consult["id"], "items": MEDICINES}).json()
    client.post(f"/api/prescriptions/{rx['id']}/submit", headers=doctor)
    client.post(f"/api/prescriptions/{rx['id']}/approve", headers=doctor)
    record = client.post("/api/fhir/records", headers=hims, json={"source_type": "prescription", "source_id": rx["id"]}).json()
    with SessionLocal() as db:
        db.get(FhirRecord, record["id"]).validation_status = "valid"
        db.commit()
    return patient, record, hims


def register_abha(client, hims, patient, address, **changes):
    account = {"abha_address": address, "name": patient["full_name"], "gender": patient["gender"],
               "year_of_birth": patient["year_of_birth"], "abha_number": "91123456789012", **changes}
    assert client.post("/api/hip/simulate/abha", headers=hims, json=account).status_code == 200


def link_via_token(client, hims, patient):
    client.post(f"/api/hip/patients/{patient['id']}/link-token", headers=hims)
    overview = client.get(f"/api/hip/patients/{patient['id']}", headers=hims).json()
    ids = [c["id"] for c in overview["care_contexts"]]
    assert client.post(f"/api/hip/patients/{patient['id']}/care-contexts/link", headers=hims,
                       json={"care_context_ids": ids}).status_code == 200
    return client.get(f"/api/hip/patients/{patient['id']}", headers=hims).json()


def test_hip_status(client):
    hims = login(client, "hims")
    status = client.get("/api/hip/status", headers=hims).json()
    assert status["mode"] == "simulation" and status["hip_id"] == "SIM_HIP_001" and status["hiu_id"] == "SIM_HIU_LOCAL"
    assert client.get("/api/hip/status", headers=login(client, "reception")).status_code == 403


def test_abha_verification(client):
    patient, _, hims = shareable_prescription(client, abha_address="ramesh.k@sbx")
    url = f"/api/hip/patients/{patient['id']}"
    assert client.get(f"/api/patients/{patient['id']}", headers=hims).json()["abha_verified"] is False

    assert client.post(f"{url}/link-token", headers=hims).json()["status"] == "failed"
    register_abha(client, hims, patient, "ramesh.k@sbx", year_of_birth=1990)
    failed = client.post(f"{url}/link-token", headers=hims).json()
    assert failed["status"] == "failed" and "do not match" in failed["message"]
    assert client.get(f"/api/patients/{patient['id']}", headers=hims).json()["abha_verified"] is False

    register_abha(client, hims, patient, "ramesh.k@sbx")
    assert client.post(f"{url}/link-token", headers=hims).json()["status"] == "verified"
    overview = client.get(url, headers=hims).json()
    with SessionLocal() as db:
        token = db.query(HipPatientLink).filter_by(patient_id=patient["id"]).one().link_token
    assert overview["link"]["status"] == "verified" and token and token not in json.dumps(overview)
    registered = client.get(f"/api/patients/{patient['id']}", headers=hims).json()
    assert registered["abha_verified"] is True and registered["abha_verification_method"] == "abdm_link_token"
    assert registered["abha_number"] == "91123456789012"


def test_care_context_creation_and_linking(client):
    patient, record, hims = shareable_prescription(client, abha_address="ramesh.k@sbx")
    url = f"/api/hip/patients/{patient['id']}"
    [context] = client.get(url, headers=hims).json()["care_contexts"]
    assert context["reference"] == f"TST-PRESCRIPTION-{record['source_id']}" and context["hi_type"] == "Prescription"
    assert context["display"].startswith("Prescription · ") and "Metformin" not in context["display"]
    assert context["link_status"] == "not_linked" and context["fhir_record_id"] == record["id"]

    blocked = client.post(f"{url}/care-contexts/link", headers=hims, json={"care_context_ids": [context["id"]]})
    assert blocked.status_code == 422 and "link token" in blocked.json()["detail"]

    register_abha(client, hims, patient, "ramesh.k@sbx")
    linked = link_via_token(client, hims, patient)["care_contexts"][0]
    assert linked["link_status"] == "linked" and linked["linked_abha_address"] == "ramesh.k@sbx"
    assert linked["link_method"] == "hip_initiated"


def linked_patient(client):
    patient, record, hims = shareable_prescription(client, abha_address="ramesh.k@sbx")
    register_abha(client, hims, patient, "ramesh.k@sbx")
    return patient, link_via_token(client, hims, patient)["care_contexts"][0], hims


def consent(client, hims, patient, **changes):
    body = {"patient_id": patient["id"], "date_from": "2020-01-01", "date_to": "2030-12-31",
            "erase_at": "2099-01-01T00:00:00", **changes}
    return client.post("/api/hip/simulate/consent", headers=hims, json=body).json()


def test_consent_verification(client):
    patient, context, hims = linked_patient(client)
    granted = consent(client, hims, patient)
    assert granted["status"] == "GRANTED"
    stored = client.get("/api/hip/consents", headers=hims).json()["items"][0]
    assert stored["status"] == "GRANTED" and stored["hi_types"] == ["Prescription"] and stored["hiu_id"] == "SIM_HIU_001"

    def notify(**changes):
        detail = {"hip": {"id": "SIM_HIP_001"}, "hiu": {"id": "SIM_HIU_001"}, "patient": {"id": "ramesh.k@sbx"},
                  "careContexts": [{"patientReference": patient["patient_code"], "careContextReference": context["reference"]}],
                  "purpose": {"code": "CAREMGT"}, "hiTypes": ["Prescription"], "permission": {
                      "dateRange": {"from": "2020-01-01T00:00:00Z", "to": "2030-01-01T00:00:00Z"},
                      "dataEraseAt": "2099-01-01T00:00:00Z"}, **changes}
        with SessionLocal() as db:
            result = hip.consent_notify(db, db.get(Hospital, 1), str(uuid.uuid4()), "GRANTED", detail)
            db.commit()
            return result.status, result.status_reason

    assert notify(hip={"id": "OTHER_HIP"}) == ("REJECTED", "Consent is for a different HIP")
    assert "does not hold" in notify(careContexts=[{"patientReference": "x", "careContextReference": "TST-X-9"}])[1]
    assert "not linked to this ABHA address" in notify(patient={"id": "someone.else@sbx"})[1]
    assert "expired" in consent(client, hims, patient, erase_at="2001-01-01T00:00:00")["status_reason"]
    statuses = [c["status"] for c in client.get("/api/hip/consents", headers=hims).json()["items"]]
    assert statuses.count("REJECTED") == 4

    assert consent(client, hims, patient, status="REVOKED", consent_id=granted["consent_id"])["status"] == "REVOKED"
    stored = {c["consent_id"]: c["status"] for c in client.get("/api/hip/consents", headers=hims).json()["items"]}
    assert stored[granted["consent_id"]] == "REVOKED"


def test_health_information_sharing(client):
    patient, context, hims = linked_patient(client)
    granted = consent(client, hims, patient)

    def request(date_from="2020-01-01", date_to="2030-12-31"):
        return client.post("/api/hip/simulate/health-information", headers=hims, json={
            "consent_id": granted["consent_id"], "date_from": date_from, "date_to": date_to}).json()

    result = request()
    assert result["error"] is None and result["session_status"] == "TRANSFERRED"
    [received] = result["received_by_hiu"]
    assert received == {"careContextReference": context["reference"], "checksum_ok": True, "profile": "PrescriptionRecord",
                        "resources": received["resources"]}
    assert result["status_responses"] == [{"careContextReference": context["reference"], "hiStatus": "DELIVERED",
                                           "description": "Done"}]

    early = request(date_to="2020-12-31")
    assert early["received_by_hiu"] == [] and early["session_status"] == "FAILED"
    assert early["status_responses"][0]["hiStatus"] == "ERRORED"
    assert "outside the consented range" in request(date_from="2010-01-01")["error"]
    consent(client, hims, patient, status="REVOKED", consent_id=granted["consent_id"])
    assert "not active" in request()["error"]


def test_invalid_key_material_is_refused(client):
    patient, context, hims = linked_patient(client)
    granted = consent(client, hims, patient)
    with SessionLocal() as db:
        reply = hip.share(db, db.get(Hospital, 1), granted["consent_id"], "2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z",
                          {"public": base64.b64encode(b"\x01" * 31).decode(), "nonce": base64.b64encode(b"n" * 32).decode()})
    assert "Invalid key material" in reply["error"] and reply["entries"] == []


def test_encryption_round_trip():
    hip_keys, hiu_keys, stranger = hip.new_keys(), hip.new_keys(), hip.new_keys()
    secret = hip.encrypt("Bundle", hip_keys, hiu_keys["public"], hiu_keys["nonce"])
    assert hip.decrypt(secret, hiu_keys, hip_keys["public"], hip_keys["nonce"]) == "Bundle"
    with pytest.raises(Exception):
        hip.decrypt(secret, stranger, hip_keys["public"], hip_keys["nonce"])
