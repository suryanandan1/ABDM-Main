import base64
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import demo
from app.config import settings
from app.models import CareContext, FhirRecord, HipConsent, HipPatientLink, Hospital, Patient, User, utcnow
from app.services import audit

MODE = "simulation"
HI_TYPES = {"OPConsultRecord": "OPConsultation", "PrescriptionRecord": "Prescription",
            "DiagnosticReportRecord": "DiagnosticReport", "DischargeSummaryRecord": "DischargeSummary",
            "ImmunizationRecord": "ImmunizationRecord", "WellnessRecord": "WellnessRecord",
            "HealthDocumentRecord": "HealthDocumentRecord"}
HI_LABELS = {"OPConsultation": "OP consultation", "Prescription": "Prescription", "DiagnosticReport": "Lab report",
             "DischargeSummary": "Discharge summary", "ImmunizationRecord": "Immunization",
             "WellnessRecord": "Wellness record", "HealthDocumentRecord": "Health document"}
registry: dict[str, dict] = demo.abha_accounts()


class HipError(Exception):
    pass


def require_staff_consent_simulation() -> None:
    """Consent is the patient's decision: staff may only act as the patient when explicitly allowed (tests/demos)."""
    from fastapi import HTTPException
    from app.config import settings
    if not settings.allow_staff_consent_simulation:
        raise HTTPException(403, "Only the patient can give, deny or revoke consent. They do this after signing in "
                                 "with their ABHA address (Consent requests).")


def sim_reset() -> None:
    registry.clear()
    registry.update(demo.abha_accounts())


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def new_keys() -> dict:
    private = X25519PrivateKey.generate()
    return {"private": private, "public": b64(private.public_key().public_bytes_raw()), "nonce": b64(secrets.token_bytes(32))}


def session_cipher(keys: dict, peer_public: str, peer_nonce: str) -> tuple[AESGCM, bytes]:
    shared = keys["private"].exchange(X25519PublicKey.from_public_bytes(base64.b64decode(peer_public)))
    xor = bytes(a ^ b for a, b in zip(base64.b64decode(keys["nonce"]), base64.b64decode(peer_nonce)))
    return AESGCM(HKDF(algorithm=hashes.SHA256(), length=32, salt=xor[:20], info=None).derive(shared)), xor[-12:]


def encrypt(text: str, keys: dict, peer_public: str, peer_nonce: str) -> str:
    cipher, iv = session_cipher(keys, peer_public, peer_nonce)
    return b64(cipher.encrypt(iv, text.encode(), None))


def decrypt(data: str, keys: dict, peer_public: str, peer_nonce: str) -> str:
    cipher, iv = session_cipher(keys, peer_public, peer_nonce)
    return cipher.decrypt(iv, base64.b64decode(data), None).decode()


def hip_id(hospital: Hospital) -> str:
    return hospital.abdm_hip_id or settings.abdm_hip_id or "SIM_HIP_001"


def hiu_id(hospital: Hospital) -> str:
    return hospital.abdm_hiu_id or settings.abdm_hiu_id or "SIM_HIU_LOCAL"


def hospital_names(db: Session, role: str) -> dict[str, str]:
    return {(hip_id if role == "hip" else hiu_id)(h): h.name for h in db.scalars(select(Hospital).order_by(Hospital.id.desc()))}


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def sync_care_contexts(db: Session, patient: Patient) -> list[CareContext]:
    existing = {c.fhir_record_id for c in db.scalars(select(CareContext).where(CareContext.patient_id == patient.id))}
    code = db.get(Hospital, patient.hospital_id).code
    for rec in db.scalars(select(FhirRecord).where(FhirRecord.patient_id == patient.id)):
        if rec.id not in existing and rec.hip_eligible:
            hi_type, when = HI_TYPES[rec.record_type], parse_time(rec.bundle["entry"][0]["resource"].get("date")) or rec.generated_at
            db.add(CareContext(hospital_id=patient.hospital_id, patient_id=patient.id, fhir_record_id=rec.id, hi_type=hi_type,
                               reference=f"{code}-{rec.source_type.upper().replace('_', '-')}-{rec.source_id}",
                               display=f"{HI_LABELS[hi_type]} · {when:%d %b %Y}", record_date=when))
    db.flush()
    return db.scalars(select(CareContext).where(CareContext.patient_id == patient.id).order_by(CareContext.id)).all()


def verify_abha(db: Session, user: User, patient: Patient) -> HipPatientLink:
    if not patient.abha_address:
        raise HipError("Enter the patient's ABHA address first")
    if patient.gender not in ("M", "F", "O"):
        raise HipError("ABDM linking needs gender M, F or O")
    link = db.scalar(select(HipPatientLink).where(HipPatientLink.patient_id == patient.id)) or \
        HipPatientLink(hospital_id=patient.hospital_id, patient_id=patient.id)
    link.abha_address, link.mode, link.request_id, link.link_token = patient.abha_address, MODE, str(uuid.uuid4()), None
    account = registry.get(patient.abha_address.lower())
    if account is None:
        link.status, link.message = "failed", f"ABDM could not verify {link.abha_address}: ABHA address not found"
    elif (account["name"].lower(), account["gender"], account["yearOfBirth"]) != \
            (patient.full_name.lower(), patient.gender, patient.year_of_birth):
        link.status = "failed"
        link.message = f"ABDM could not verify {link.abha_address}: demographic details do not match the ABHA account"
    else:
        link.status, link.link_token = "verified", secrets.token_urlsafe(32)
        link.message = "ABHA address verified by ABDM (demographic match); link token received"
        number = account.get("abhaNumber")
        if patient.abha_number and number and patient.abha_number != number:
            link.message += "; the ABHA number on file differs from ABDM's and was not marked verified"
        else:
            patient.abha_number = patient.abha_number or number
            patient.abha_verified, patient.abha_verified_at, patient.abha_verification_method = True, utcnow(), "abdm_link_token"
    db.add(link)
    audit(db, user, "hip.link_token_request", "patient", patient.id)
    return link


def link_care_contexts(db: Session, user: User, patient: Patient, contexts: list[CareContext]) -> str:
    link = db.scalar(select(HipPatientLink).where(HipPatientLink.patient_id == patient.id))
    if link is None or link.status != "verified" or not link.link_token:
        raise HipError("Verify the patient's ABHA address with ABDM (link token) first")
    if not contexts:
        raise HipError("No care contexts to link")
    for c in contexts:
        c.link_status, c.linked_abha_address, c.linked_at = "linked", link.abha_address, utcnow()
        c.link_method, c.message = "hip_initiated", "Linked by ABDM"
    audit(db, user, "hip.care_context_link", "patient", patient.id, {"care_contexts": [c.reference for c in contexts]})
    return f"{len(contexts)} care context(s) linked to {link.abha_address}"


def consent_problem(db: Session, hospital: Hospital, detail: dict) -> tuple[str | None, Patient | None]:
    if detail["hip"]["id"] != hip_id(hospital):
        return "Consent is for a different HIP", None
    refs, address = detail.get("careContexts") or [], detail["patient"]["id"].lower()
    contexts = db.scalars(select(CareContext).where(CareContext.hospital_id == hospital.id, CareContext.reference.in_(
        [r["careContextReference"] for r in refs]))).all()
    if not refs or len(contexts) != len(refs):
        return "Consent lists care contexts this HIP does not hold", None
    if any(c.link_status != "linked" or (c.linked_abha_address or "").lower() != address for c in contexts):
        return "Consent lists care contexts not linked to this ABHA address", None
    patient = db.get(Patient, contexts[0].patient_id)
    if any(c.patient_id != patient.id for c in contexts) or any(r["patientReference"] != patient.patient_code for r in refs):
        return "Consent mixes records of different patients", None
    start, end = (parse_time(detail["permission"]["dateRange"][k]) for k in ("from", "to"))
    if start > end or parse_time(detail["permission"]["dataEraseAt"]) < utcnow():
        return "Consent has expired (dataEraseAt passed) or its date range is invalid", patient
    if not detail.get("hiTypes") or not set(detail["hiTypes"]) <= set(HI_TYPES.values()):
        return "Consent contains unsupported health information types", patient
    return None, patient


def consent_notify(db: Session, hospital: Hospital, consent_id: str, status: str, detail: dict | None = None) -> HipConsent:
    consent = db.scalar(select(HipConsent).where(HipConsent.hospital_id == hospital.id, HipConsent.consent_id == consent_id))
    if status != "GRANTED":
        if consent:
            consent.status, consent.status_reason = status, "Notified by the consent manager"
        return consent
    problem, patient = consent_problem(db, hospital, detail)
    permission = detail["permission"]
    consent = consent or HipConsent(hospital_id=hospital.id, consent_id=consent_id, mode=MODE)
    consent.patient_id, consent.abha_address, consent.hiu_id = patient and patient.id, detail["patient"]["id"], detail["hiu"]["id"]
    consent.purpose, consent.hi_types, consent.care_contexts = detail["purpose"]["code"], detail["hiTypes"], detail["careContexts"]
    consent.date_from, consent.date_to = (parse_time(permission["dateRange"][k]) for k in ("from", "to"))
    consent.data_erase_at, consent.artefact = parse_time(permission["dataEraseAt"]), detail
    consent.status, consent.status_reason = ("REJECTED", problem) if problem else ("GRANTED", None)
    db.add(consent)
    return consent


def share(db: Session, hospital: Hospital, consent_id: str, date_from: str, date_to: str, hiu_keys: dict) -> dict:
    consent = db.scalar(select(HipConsent).where(HipConsent.hospital_id == hospital.id, HipConsent.consent_id == consent_id))
    start, end, problem = parse_time(date_from), parse_time(date_to), None
    if consent is None or consent.status != "GRANTED":
        problem = "Consent not found or not active (granted)"
    elif consent.data_erase_at < utcnow():
        problem = "Consent EXPIRED: exceeded dataEraseAt"
    elif not (start and end and consent.date_from <= start <= end <= consent.date_to):
        problem = "Requested date range is outside the consented range"
    else:
        try:
            X25519PublicKey.from_public_bytes(base64.b64decode(hiu_keys["public"]))
            if len(base64.b64decode(hiu_keys["nonce"])) != 32:
                raise ValueError("the nonce must be 32 bytes")
        except (KeyError, ValueError) as exc:
            problem = f"Invalid key material: {exc}"
    if problem:
        return {"error": f"Request refused: {problem}", "entries": [], "statusResponses": []}

    own, entries, statuses = new_keys(), [], []
    refs = [r["careContextReference"] for r in consent.care_contexts]
    for c in db.scalars(select(CareContext).where(CareContext.hospital_id == hospital.id, CareContext.reference.in_(refs))):
        reason = ("HI type not covered by the consent" if c.hi_type not in consent.hi_types else
                  "Record date is outside the requested date range" if not start <= c.record_date <= end else
                  "Record is no longer validated for sharing" if not c.fhir_record.hip_eligible else None)
        if reason is None:
            content = json.dumps(c.fhir_record.bundle, separators=(",", ":"))
            entries.append({"content": encrypt(content, own, hiu_keys["public"], hiu_keys["nonce"]), "media": "application/fhir+json",
                            "checksum": hashlib.md5(content.encode()).hexdigest(), "careContextReference": c.reference})
        statuses.append({"careContextReference": c.reference, "hiStatus": "ERRORED" if reason else "DELIVERED",
                         "description": reason or "Done"})
    transaction_id = str(uuid.uuid4())
    audit(db, None, "hip.data_transfer", "consent", consent_id,
          {"transaction_id": transaction_id, "delivered": len(entries), "hiu": consent.hiu_id}, hospital_id=hospital.id)
    return {"transactionId": transaction_id, "sessionStatus": "TRANSFERRED" if entries else "FAILED", "hipId": hip_id(hospital),
            "message": f"{len(entries)} of {len(statuses)} record(s) encrypted and sent to {consent.hiu_id}",
            "entries": entries, "statusResponses": statuses,
            "keyMaterial": {"cryptoAlg": "ECDH", "curve": "Curve25519", "dhPublicKey": {"keyValue": own["public"]},
                            "nonce": own["nonce"]}}
