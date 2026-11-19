from datetime import date

import pytest
from sqlalchemy import select

from app import hip
from app.database import SessionLocal
from app.models import FhirRecord, Hospital
from init_db import seed_network
from tests.conftest import login
from tests.test_clinical import MEDICINES, start_consultation

TODAY = date.today().isoformat()


@pytest.fixture()
def network(client):
    hip.sim_reset()
    with SessionLocal() as db:
        seed_network(db, db.scalar(select(Hospital).where(Hospital.code == "TST")))
    yield client
    hip.sim_reset()


def patient(client, headers, query):
    return client.get("/api/patients", params={"q": query}, headers=headers).json()["items"][0]


def verify_and_link(client, hims, p):
    assert client.post(f"/api/hip/patients/{p['id']}/link-token", headers=hims).json()["status"] == "verified"
    overview = client.get(f"/api/hip/patients/{p['id']}", headers=hims).json()
    if ids := [c["id"] for c in overview["care_contexts"]]:
        client.post(f"/api/hip/patients/{p['id']}/care-contexts/link", headers=hims, json={"care_context_ids": ids})


def shareable_record_at_green_valley(client):
    doctor, hims = login(client, "gvh.shetty"), login(client, "gvh.hims")
    surya = patient(client, hims, "Surya")
    assert surya["abha_address"] == "surya@abdm" and surya["patient_code"].startswith("GVH-")
    consult = start_consultation(client, doctor, surya["id"])
    rx = client.post("/api/prescriptions", headers=doctor, json={"encounter_id": consult["id"], "items": MEDICINES}).json()
    client.post(f"/api/prescriptions/{rx['id']}/submit", headers=doctor)
    client.post(f"/api/prescriptions/{rx['id']}/approve", headers=doctor)
    record = client.post("/api/fhir/records", headers=hims, json={"source_type": "prescription", "source_id": rx["id"]}).json()
    with SessionLocal() as db:
        db.get(FhirRecord, record["id"]).validation_status = "valid"
        db.commit()
    verify_and_link(client, hims, surya)


def test_each_hospital_has_its_own_abdm_identity(network):
    client = network
    staff = {"hims": "TST", "gvh.hims": "GVH", "rmc.hims": "RMC"}
    for username, code in staff.items():
        status = client.get("/api/hip/status", headers=login(client, username)).json()
        assert status["hip_id"] == f"SIM_HIP_{code}" and status["hiu_id"] == f"SIM_HIU_{code}"
    hospitals = client.get("/api/hip/network", headers=login(client, "gvh.hims")).json()["hospitals"]
    assert [(h["code"], h["hip_id"], h["this_hospital"]) for h in hospitals] == [
        ("TST", "SIM_HIP_TST", False), ("GVH", "SIM_HIP_GVH", True), ("RMC", "SIM_HIP_RMC", False)]
    for username in staff:
        assert patient(client, login(client, username), "Surya")["abha_address"] == "surya@abdm"
    clash = client.put("/api/hospital", headers=login(client, "gvh.admin"), json={"abdm_hip_id": "SIM_HIP_RMC"})
    assert clash.status_code == 409


def test_records_flow_from_one_hospital_to_another(network):
    client = network
    shareable_record_at_green_valley(client)
    doctor, hims = login(client, "dr.mehta"), login(client, "hims")
    surya = patient(client, hims, "Surya")
    verify_and_link(client, hims, surya)
    request = client.post("/api/hiu/requests", headers=doctor, json={
        "patient_id": surya["id"], "purpose_code": "CAREMGT", "hi_types": ["Prescription", "DiagnosticReport"],
        "date_from": "2024-01-01", "date_to": TODAY}).json()
    assert request["status"] == "pending_consent"

    granted = client.post(f"/api/hiu/simulate/requests/{request['id']}/decide", headers=doctor, json={"grant": True}).json()
    assert granted["status"] == "received", granted
    detail = client.get(f"/api/hiu/requests/{request['id']}", headers=doctor).json()
    assert [(a["hip_id"], a["hip_name"], a["status"]) for a in detail["artefacts"]] == [
        ("SIM_HIP_GVH", "Green Valley Multispeciality Hospital", "valid")]
    records = client.get(f"/api/hiu/patients/{surya['id']}/records", headers=doctor).json()["records"]
    assert [(r["source_hip_id"], r["source_name"], r["category"], r["checksum_ok"]) for r in records] == [
        ("SIM_HIP_GVH", "Green Valley Multispeciality Hospital", "Prescription", True)]

    gvh = login(client, "gvh.hims")
    consent = client.get("/api/hip/consents", headers=gvh).json()["items"][0]
    assert consent["status"] == "GRANTED" and consent["abha_address"] == "surya@abdm"
    assert consent["hiu_id"] == "SIM_HIU_TST" and consent["hiu_name"] == "Test Hospital"
    assert client.get("/api/hip/consents", headers=login(client, "rmc.hims")).json()["items"] == []

    revoked = client.post(f"/api/hiu/simulate/requests/{request['id']}/revoke", headers=doctor).json()
    assert revoked["status"] == "revoked"
    assert client.get("/api/hip/consents", headers=gvh).json()["items"][0]["status"] == "REVOKED"
    assert client.get(f"/api/hiu/patients/{surya['id']}/records", headers=doctor).json()["records"] == []


def test_grant_needs_records_at_another_hospital(network):
    client = network
    doctor, hims = login(client, "dr.mehta"), login(client, "hims")
    arjun = patient(client, hims, "Arjun")
    verify_and_link(client, hims, arjun)
    request = client.post("/api/hiu/requests", headers=doctor, json={
        "patient_id": arjun["id"], "purpose_code": "CAREMGT", "hi_types": ["Prescription"],
        "date_from": "2024-01-01", "date_to": TODAY}).json()
    refused = client.post(f"/api/hiu/simulate/requests/{request['id']}/decide", headers=doctor, json={"grant": True})
    assert refused.status_code == 409 and "arjun.singh@abdm" in refused.json()["detail"]
