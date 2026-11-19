"""The patient's own portal.

A patient signs in with their ABHA address (the account's username). They see approved records from every hospital
whose patient record carries that ABHA address *and* has verified it with ABDM, and they answer consent requests
made for that ABHA address. They never see anyone else's data or any staff screen.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Encounter, HiuConsentRequest, Hospital, LabOrder, LabReport, Patient, Prescription, Role, User
from app.schemas import ConditionOut, DoctorBrief, LabResultOut, ORMModel, PrescriptionItemOut, UTCDateTime
from app.security import PATIENT, hash_password, require
from app.services import audit

router = APIRouter(prefix="/portal", tags=["portal"])
APPROVED = "approved"


class PortalProfile(ORMModel):
    patient_code: str
    full_name: str
    gender: str
    date_of_birth: date | None
    year_of_birth: int
    mobile: str
    address_line: str | None
    city: str | None
    state: str | None
    pincode: str | None
    abha_number: str | None
    abha_address: str | None
    abha_verified: bool
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    emergency_contact_relation: str | None


class PortalVisit(ORMModel):
    id: int
    visit_at: UTCDateTime
    doctor: DoctorBrief
    chief_complaint: str | None
    clinical_findings: str | None
    vitals: dict | None
    treatment_plan: str | None
    follow_up_instructions: str | None
    follow_up_date: date | None
    conditions: list[ConditionOut]


class PortalPrescription(ORMModel):
    id: int
    prescription_date: date
    doctor: DoctorBrief
    notes: str | None
    items: list[PrescriptionItemOut]


class PortalLabReport(ORMModel):
    id: int
    test_name: str
    ordered_at: UTCDateTime
    approved_at: UTCDateTime | None
    conclusion: str | None
    results: list[LabResultOut]


class ConsentOut(ORMModel):
    id: int
    hospital_name: str
    requester: str
    purpose: str
    hi_types: list[str]
    date_from: UTCDateTime
    date_to: UTCDateTime
    data_erase_at: UTCDateTime
    reason: str | None
    status: str
    status_message: str | None
    created_at: UTCDateTime


class ConsentDecision(BaseModel):
    grant: bool
    hi_types: list[str] | None = None


def create_patient_account(db: Session, abha_address: str, full_name: str, password: str) -> User:
    """One sign-in per ABHA address (the username), not tied to any single hospital."""
    username = abha_address.strip().lower()
    if "@" not in username:
        raise ValueError(f"{abha_address!r} is not an ABHA address")
    if db.scalar(select(User.id).where(User.username == username)):
        raise ValueError(f"An account for {username} already exists")
    role = db.scalar(select(Role).where(Role.code == PATIENT))
    if role is None:
        raise ValueError("The patient role is missing; run python init_db.py first")
    user = User(hospital_id=None, role_id=role.id, username=username, password_hash=hash_password(password),
                full_name=full_name)
    db.add(user)
    db.flush()
    return user


def abha_of(user: User = Depends(require("portal:view"))) -> str:
    if user.hospital_id is not None or "@" not in user.username:
        raise HTTPException(404, "This account is not linked to an ABHA address")
    return user.username


def my_patient_records(db: Session, abha: str) -> list[Patient]:
    return db.scalars(select(Patient).join(Hospital, Hospital.id == Patient.hospital_id).where(
        func.lower(Patient.abha_address) == abha, Patient.abha_verified.is_(True), Hospital.is_active.is_(True))
        .order_by(Hospital.name)).all()


def hospital_record(db: Session, patient: Patient) -> dict:
    visits = db.scalars(select(Encounter).where(Encounter.patient_id == patient.id, Encounter.status == APPROVED)
                        .order_by(Encounter.visit_at.desc())).all()
    prescriptions = db.scalars(select(Prescription).where(Prescription.patient_id == patient.id,
                                                          Prescription.status == APPROVED)
                               .order_by(Prescription.prescription_date.desc(), Prescription.id.desc())).all()
    reports = db.execute(select(LabOrder, LabReport).join(LabReport, LabReport.order_id == LabOrder.id).where(
        LabOrder.patient_id == patient.id, LabReport.status == APPROVED).order_by(LabOrder.created_at.desc())).all()
    return {
        "hospital_name": db.get(Hospital, patient.hospital_id).name,
        "profile": PortalProfile.model_validate(patient).model_dump(),
        "visits": [PortalVisit.model_validate(v).model_dump() for v in visits],
        "prescriptions": [PortalPrescription.model_validate(p).model_dump() for p in prescriptions],
        "lab_reports": [PortalLabReport(id=r.id, test_name=o.test.name, ordered_at=o.created_at, approved_at=r.approved_at,
                                        conclusion=r.conclusion,
                                        results=[LabResultOut.model_validate(x) for x in r.results]).model_dump()
                        for o, r in reports],
    }


@router.get("/me")
def my_record(abha: str = Depends(abha_of), db: Session = Depends(get_db)):
    return {"abha_address": abha, "hospitals": [hospital_record(db, p) for p in my_patient_records(db, abha)]}


# ---- Consent: the patient answers requests made for their ABHA address by any hospital on the network ----

def consent_out(r: HiuConsentRequest) -> dict:
    from app import hiu
    return ConsentOut.model_validate({
        "id": r.id, "hospital_name": r.hospital.name, "requester": r.requester_doctor.full_name,
        "purpose": hiu.PURPOSES.get(r.purpose_code, r.purpose_code), "hi_types": r.hi_types, "date_from": r.date_from,
        "date_to": r.date_to, "data_erase_at": r.data_erase_at, "reason": r.reason, "status": r.status,
        "status_message": r.status_message, "created_at": r.created_at}).model_dump()


def own_consent(db: Session, request_id: int, abha: str) -> HiuConsentRequest:
    consent = db.get(HiuConsentRequest, request_id)
    if consent is None or consent.abha_address.lower() != abha:
        raise HTTPException(404, "Consent request not found")
    return consent


@router.get("/consents")
def my_consents(abha: str = Depends(abha_of), db: Session = Depends(get_db)):
    return [consent_out(r) for r in db.scalars(select(HiuConsentRequest).where(
        func.lower(HiuConsentRequest.abha_address) == abha).order_by(HiuConsentRequest.id.desc()))]


@router.post("/consents/{request_id}/decide")
def decide_consent(request_id: int, body: ConsentDecision, request: Request, abha: str = Depends(abha_of),
                   user: User = Depends(require("portal:view")), db: Session = Depends(get_db)):
    from app.routers.hiu import Decision, decide
    consent = own_consent(db, request_id, abha)
    audit(db, user, "portal.consent_granted" if body.grant else "portal.consent_denied", "hiu_consent_request", consent.id,
          {"hi_types": body.hi_types}, request, hospital_id=consent.hospital_id)
    decision = Decision(grant=body.grant, hi_types=body.hi_types, reason=None if body.grant else "Declined by the patient")
    return consent_out(decide(db, consent, decision))


@router.post("/consents/{request_id}/revoke")
def revoke_consent(request_id: int, request: Request, abha: str = Depends(abha_of),
                   user: User = Depends(require("portal:view")), db: Session = Depends(get_db)):
    from app.routers.hiu import revoke
    consent = own_consent(db, request_id, abha)
    audit(db, user, "portal.consent_revoked", "hiu_consent_request", consent.id, request=request,
          hospital_id=consent.hospital_id)
    return consent_out(revoke(db, consent))
