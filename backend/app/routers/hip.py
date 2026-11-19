import hashlib
import json
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import hip
from app.database import get_db
from app.models import CareContext, HipConsent, HipPatientLink, Hospital, Patient, User
from app.routers.fhir import validator_available
from app.schemas import ORMModel, Page, PatientSummary, UTCDateTime
from app.security import require
from app.services import get_or_404, paginate

router = APIRouter(prefix="/hip", tags=["hip"])


class CareContextOut(ORMModel):
    id: int
    patient_id: int
    reference: str
    display: str
    hi_type: str
    record_date: UTCDateTime
    link_status: str
    linked_abha_address: str | None
    link_method: str | None
    linked_at: UTCDateTime | None
    fhir_record_id: int


class ConsentOut(ORMModel):
    consent_id: str
    status: str
    status_reason: str | None
    patient: PatientSummary | None
    abha_address: str | None
    hiu_id: str | None
    hiu_name: str | None = None
    purpose: str | None
    hi_types: list
    care_contexts: list
    date_from: UTCDateTime | None
    date_to: UTCDateTime | None
    data_erase_at: UTCDateTime | None
    created_at: UTCDateTime


def consents_out(db: Session, rows) -> list[dict]:
    names = hip.hospital_names(db, "hiu")
    return [{**ConsentOut.model_validate(c).model_dump(), "hiu_name": names.get(c.hiu_id)} for c in rows]


def run(action):
    try:
        return action()
    except hip.HipError as exc:
        raise HTTPException(422, str(exc))


@router.get("/status")
def hip_status(user: User = Depends(require("hip:read")), db: Session = Depends(get_db)):
    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(model.hospital_id == user.hospital_id, *where))

    return {"mode": hip.MODE, "hip_id": hip.hip_id(user.hospital), "hiu_id": hip.hiu_id(user.hospital),
            "fhir_validator": validator_available(), "counts": {
                "verified_links": count(HipPatientLink, HipPatientLink.status == "verified"),
                "care_contexts": count(CareContext),
                "linked_care_contexts": count(CareContext, CareContext.link_status == "linked"),
                "active_consents": count(HipConsent, HipConsent.status == "GRANTED")}}


@router.get("/network")
def network(user: User = Depends(require("hip:read")), db: Session = Depends(get_db)):
    return {"hospitals": [{"id": h.id, "name": h.name, "code": h.code, "city": h.city, "state": h.state,
                           "hip_id": hip.hip_id(h), "hiu_id": hip.hiu_id(h), "this_hospital": h.id == user.hospital_id}
                          for h in db.scalars(select(Hospital).where(Hospital.is_active.is_(True)).order_by(Hospital.id))]}


@router.get("/patients/{patient_id}")
def patient_overview(patient_id: int, user: User = Depends(require("hip:read")), db: Session = Depends(get_db)):
    patient = get_or_404(db, Patient, patient_id, user.hospital_id)
    contexts = hip.sync_care_contexts(db, patient)
    db.commit()
    link = db.scalar(select(HipPatientLink).where(HipPatientLink.patient_id == patient.id))
    consents = db.scalars(select(HipConsent).where(HipConsent.patient_id == patient.id).order_by(HipConsent.id.desc()))
    return {"patient": PatientSummary.model_validate(patient).model_dump(),
            "abha_verification_method": patient.abha_verification_method,
            "link": link and {"abha_address": link.abha_address, "status": link.status, "message": link.message},
            "care_contexts": [CareContextOut.model_validate(c).model_dump() for c in contexts],
            "consents": consents_out(db, consents)}


@router.post("/patients/{patient_id}/link-token")
def verify_abha(patient_id: int, user: User = Depends(require("hip:manage")), db: Session = Depends(get_db)):
    patient = get_or_404(db, Patient, patient_id, user.hospital_id)
    link = run(lambda: hip.verify_abha(db, user, patient))
    db.commit()
    return {"status": link.status, "message": link.message}


class LinkSelection(BaseModel):
    care_context_ids: list[int]


@router.post("/patients/{patient_id}/care-contexts/link")
def link_care_contexts(patient_id: int, body: LinkSelection, user: User = Depends(require("hip:manage")),
                       db: Session = Depends(get_db)):
    patient = get_or_404(db, Patient, patient_id, user.hospital_id)
    contexts = db.scalars(select(CareContext).where(CareContext.id.in_(body.care_context_ids),
                                                    CareContext.patient_id == patient.id)).all()
    if len(contexts) != len(set(body.care_context_ids)) or any(c.link_status == "linked" for c in contexts):
        raise HTTPException(422, "Select unlinked care contexts of this patient")
    message = run(lambda: hip.link_care_contexts(db, user, patient, contexts))
    db.commit()
    return {"status": "linked", "message": message}


@router.get("/care-contexts", response_model=Page[CareContextOut])
def list_care_contexts(link_status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                       user: User = Depends(require("hip:read")), db: Session = Depends(get_db)):
    query = select(CareContext).where(CareContext.hospital_id == user.hospital_id).order_by(CareContext.id.desc())
    return paginate(db, query.where(CareContext.link_status == link_status) if link_status else query, page, page_size)


@router.get("/consents", response_model=Page[ConsentOut])
def list_consents(status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  user: User = Depends(require("hip:read")), db: Session = Depends(get_db)):
    query = select(HipConsent).where(HipConsent.hospital_id == user.hospital_id).order_by(HipConsent.id.desc())
    result = paginate(db, query.where(HipConsent.status == status) if status else query, page, page_size)
    return {**result, "items": consents_out(db, result["items"])}


class SimAbha(BaseModel):
    abha_address: str
    name: str
    gender: str
    year_of_birth: int
    abha_number: str | None = None


@router.post("/simulate/abha")
def simulate_abha(body: SimAbha, _: User = Depends(require("hip:manage"))):
    hip.registry[body.abha_address.lower()] = {"name": body.name, "gender": body.gender, "yearOfBirth": body.year_of_birth,
                                               "abhaNumber": body.abha_number}
    return {"message": f"Simulated ABHA account {body.abha_address} created"}


class SimConsent(BaseModel):
    patient_id: int
    care_context_ids: list[int] | None = None
    hi_types: list[str] | None = None
    date_from: date
    date_to: date
    erase_at: datetime
    status: str = "GRANTED"
    consent_id: str | None = None


@router.post("/simulate/consent")
def simulate_consent(body: SimConsent, user: User = Depends(require("hip:manage")), db: Session = Depends(get_db)):
    hip.require_staff_consent_simulation()
    patient = get_or_404(db, Patient, body.patient_id, user.hospital_id)
    contexts = [c for c in db.scalars(select(CareContext).where(CareContext.patient_id == patient.id))
                if c.link_status == "linked" and (body.care_context_ids is None or c.id in body.care_context_ids)]
    if not contexts and body.status == "GRANTED":
        raise HTTPException(422, "The patient has no linked care contexts to consent to")
    consent_id = body.consent_id or str(uuid.uuid4())
    detail = {"consentId": consent_id, "hip": {"id": hip.hip_id(user.hospital)}, "hiu": {"id": "SIM_HIU_001"},
              "patient": {"id": contexts[0].linked_abha_address if contexts else patient.abha_address or ""},
              "careContexts": [{"patientReference": patient.patient_code, "careContextReference": c.reference} for c in contexts],
              "purpose": {"text": "Care Management", "code": "CAREMGT"}, "hiTypes": body.hi_types or sorted({c.hi_type for c in contexts}),
              "permission": {"accessMode": "VIEW", "dateRange": {"from": f"{body.date_from}T00:00:00Z", "to": f"{body.date_to}T23:59:59Z"},
                             "dataEraseAt": body.erase_at.isoformat() + ("Z" if body.erase_at.tzinfo is None else "")}}
    consent = hip.consent_notify(db, user.hospital, consent_id, body.status.upper(), detail)
    db.commit()
    return {"consent_id": consent_id, "status": consent.status if consent else body.status.upper(),
            "status_reason": consent.status_reason if consent else None}


class SimRequest(BaseModel):
    consent_id: str
    date_from: date
    date_to: date


@router.post("/simulate/health-information")
def simulate_health_information(body: SimRequest, user: User = Depends(require("hip:manage")), db: Session = Depends(get_db)):
    keys = hip.new_keys()
    reply = hip.share(db, user.hospital, body.consent_id, f"{body.date_from}T00:00:00Z", f"{body.date_to}T23:59:59Z", keys)
    db.commit()
    received = []
    for entry in reply["entries"]:
        material = reply["keyMaterial"]
        content = hip.decrypt(entry["content"], keys, material["dhPublicKey"]["keyValue"], material["nonce"])
        bundle = json.loads(content)
        received.append({"careContextReference": entry["careContextReference"],
                         "checksum_ok": hashlib.md5(content.encode()).hexdigest() == entry["checksum"],
                         "profile": bundle["entry"][0]["resource"]["meta"]["profile"][0].rsplit("/", 1)[-1],
                         "resources": len(bundle["entry"])})
    return {"error": reply.get("error"), "message": reply.get("message"), "session_status": reply.get("sessionStatus"),
            "status_responses": reply["statusResponses"], "received_by_hiu": received}
