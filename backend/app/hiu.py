import base64
import hashlib
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import hip
from app.config import settings
from app.database import SessionLocal
from app.models import Doctor, HiuConsentArtefact, HiuConsentRequest, HiuDataRequest, Patient, RetrievedRecord, User, utcnow
from app.routers.fhir import prechecks, validate
from app.services import audit

PURPOSES = {"CAREMGT": "Care Management", "BTG": "Break the Glass", "PUBHLTH": "Public Health",
            "HPAYMT": "Healthcare Payment", "DSRCH": "Disease Specific Healthcare Research", "PATRQT": "Self Requested"}
HI_TYPES = list(hip.HI_TYPES.values())
CATEGORIES = {record_type: hip.HI_LABELS[hi_type] for record_type, hi_type in hip.HI_TYPES.items()}

class HiuError(Exception):
    pass

class SealingKeyMissing(RuntimeError):
    pass

def _derive(secret: str, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(secret.encode())

def _sealing_key(secret: str) -> tuple[str, bytes]:
    key = _derive(secret, b"abdm-hospital-record-sealing", b"v2")
    return hashlib.sha256(key).hexdigest()[:12], key

def active_key_id() -> str | None:
    return _sealing_key(settings.record_sealing_key)[0] if settings.record_sealing_key else None

def seal(text: str) -> str:
    nonce = os.urandom(12)
    if not settings.record_sealing_key:
        key = _derive(settings.jwt_secret, b"abdm-hospital-hiu-storage", b"v1")
        return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, text.encode(), None)).decode()
    key_id, key = _sealing_key(settings.record_sealing_key)
    return f"v2.{key_id}.{base64.b64encode(nonce + AESGCM(key).encrypt(nonce, text.encode(), None)).decode()}"

def unseal(sealed: str) -> str:
    if sealed.startswith("v2."):
        _, key_id, body = sealed.split(".", 2)
        keys = dict(_sealing_key(k) for k in [settings.record_sealing_key, *settings.record_sealing_old_key_list] if k)
        if key_id not in keys:
            raise SealingKeyMissing(f"Sealed with key {key_id}, which is not configured")
        key = keys[key_id]
    else:
        key, body = _derive(settings.jwt_secret, b"abdm-hospital-hiu-storage", b"v1"), sealed
    raw = base64.b64decode(body)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()

def needs_reseal(sealed: str) -> bool:
    key_id = active_key_id()
    return key_id is not None and not sealed.startswith(f"v2.{key_id}.")

def _text(concept: dict | None) -> str | None:
    return (concept or {}).get("text") or next((c["display"] for c in (concept or {}).get("coding", []) if c.get("display")), None)

def _code(concept: dict | None, system: str) -> str | None:
    return next((c.get("code") for c in (concept or {}).get("coding", []) if c.get("system", "").endswith(system)), None)

def _time(value: str | None) -> datetime:
    try:
        return hip.parse_time(value) or datetime.min
    except ValueError:
        return datetime.min

def bundle_json(record: RetrievedRecord) -> dict:
    return json.loads(unseal(record.content))

def describe(bundle: dict) -> dict:
    resources = [e.get("resource", {}) for e in bundle.get("entry", [])]

    def of(kind: str) -> list[dict]:
        return [r for r in resources if r.get("resourceType") == kind]

    def narrative(r: dict) -> str:
        return " ".join(re.sub(r"<[^>]+>", " ", (r.get("text") or {}).get("div", "")).split())

    composition = (of("Composition") or [{}])[0]
    profile = ((composition.get("meta") or {}).get("profile") or [""])[0].rsplit("/", 1)[-1]
    kind, when = profile if profile in CATEGORIES else None, composition.get("date")
    observations = []
    for o in of("Observation"):
        quantity, ref = o.get("valueQuantity") or {}, (o.get("referenceRange") or [{}])[0]
        observations.append({
            "name": _text(o.get("code")), "loinc": _code(o.get("code"), "loinc.org"), "value": quantity.get("value"),
            "category": _code((o.get("category") or [{}])[0], "observation-category"), "value_text": o.get("valueString"),
            "unit": quantity.get("unit") or quantity.get("code"), "date": o.get("effectiveDateTime") or when,
            "reference_range": ref.get("text") or " – ".join(str(ref[k]["value"]) for k in ("low", "high") if k in ref) or None,
            "interpretation": _code((o.get("interpretation") or [{}])[0], "v3-ObservationInterpretation"),
            "components": [{"name": _text(c.get("code")), **{k: (c.get("valueQuantity") or {}).get(k) for k in ("value", "unit")}}
                           for c in o.get("component", [])] or None})
    return {
        "record_type": kind, "category": CATEGORIES.get(kind, "Other record"), "date": when, "title": composition.get("title"),
        "source": next((o.get("name") for o in of("Organization")), None),
        "authors": [a.get("display") for a in composition.get("author", []) if a.get("display")],
        "conditions": [{"text": _text(c.get("code")), "icd10": _code(c.get("code"), "icd-10"),
                        "status": _code(c.get("clinicalStatus"), "condition-clinical")} for c in of("Condition")],
        "medications": [{"name": _text(m.get("medicationCodeableConcept")), "status": m.get("status"),
                         "dosage": ((m.get("dosageInstruction") or [{}])[0]).get("text")} for m in of("MedicationRequest")],
        "observations": observations,
        "reports": [{"name": _text(d.get("code")), "conclusion": d.get("conclusion")} for d in of("DiagnosticReport")],
        "immunizations": [{"vaccine": _text(i.get("vaccineCode")), "date": i.get("occurrenceDateTime")} for i in of("Immunization")],
        "allergies": [_text(a.get("code")) for a in of("AllergyIntolerance")],
        "sections": [{"title": s.get("title"), "text": narrative(s)} for s in composition.get("section", []) if narrative(s)]}

def timeline(records: list[tuple[int, dict]]) -> list[dict]:
    def names(items: list[dict], key: str, n: int) -> list[str]:
        return [i[key] for i in items if i[key]][:n]

    entries = [{"record_id": rid, "date": f["date"], "category": f["category"], "source": f["source"], "highlights":
                names(f["conditions"], "text", 3) + names(f["medications"], "name", 3) + names(f["reports"], "name", 2)}
               for rid, f in records]
    return sorted(entries, key=lambda e: _time(e["date"]), reverse=True)

def lab_trends(records: list[tuple[int, dict]]) -> list[dict]:
    groups: dict[tuple, dict] = {}
    for rid, f in records:
        for o in f["observations"]:
            if o["category"] == "laboratory" and o["name"]:
                key = ("loinc", o["loinc"]) if o["loinc"] else ("name", o["name"].strip().lower())
                groups.setdefault(key, {"test": o["name"], "loinc": o["loinc"], "points": []})["points"].append(
                    {"record_id": rid, **{k: o[k] for k in ("date", "value", "value_text", "unit", "interpretation", "reference_range")}})
    trends = []
    for group in (g for g in groups.values() if len(g["points"]) > 1):
        points = sorted(group["points"], key=lambda p: _time(p["date"]))
        comparable = len({p["unit"] for p in points}) == 1 and all(isinstance(p["value"], (int, float)) for p in points)
        trends.append({**group, "points": points, "comparable": comparable,
                       "change": round(points[-1]["value"] - points[0]["value"], 3) if comparable else None,
                       "note": None if comparable else "Not compared: units differ or values are not numeric"})
    return sorted(trends, key=lambda t: t["test"].lower())

def create_consent_request(db: Session, user: User, patient: Patient, doctor: Doctor, purpose: str, hi_types: list[str],
                           date_from: datetime, date_to: datetime, erase_at: datetime, reason: str | None) -> HiuConsentRequest:
    if not (patient.abha_verified and patient.abha_address):
        raise HiuError("The patient's ABHA address must be verified with ABDM first (ABDM HIP page)")
    if purpose not in PURPOSES or not hi_types or not set(hi_types) <= set(HI_TYPES):
        raise HiuError("Choose a purpose of use and at least one supported record category")
    if not date_from <= date_to <= utcnow() + timedelta(days=1):
        raise HiuError("The date range must end today or earlier and start before it ends")
    if erase_at <= utcnow():
        raise HiuError("The data erase date must be in the future")
    if not doctor.is_active or doctor.hospital_id != patient.hospital_id:
        raise HiuError("Choose an active doctor of this hospital as the requester")
    request = HiuConsentRequest(
        hospital_id=patient.hospital_id, patient_id=patient.id, requested_by_id=user.id, requester_doctor_id=doctor.id,
        abha_address=patient.abha_address, purpose_code=purpose, hi_types=sorted(hi_types), date_from=date_from,
        date_to=date_to, data_erase_at=erase_at, reason=reason, request_id=str(uuid.uuid4()),
        consent_request_id=str(uuid.uuid4()), status="pending_consent", mode=hip.MODE,
        status_message="Waiting for the patient to grant or deny consent in their ABHA app")
    db.add(request)
    audit(db, user, "hiu.consent_request", "patient", patient.id,
          {"purpose": purpose, "hi_types": hi_types, "requester": doctor.full_name})
    return request

def accept_artefact(db: Session, request: HiuConsentRequest, detail: dict, source: str) -> HiuConsentArtefact:
    permission, dates = detail["permission"], detail["permission"]["dateRange"]
    start, end, erase_at = hip.parse_time(dates["from"]), hip.parse_time(dates["to"]), hip.parse_time(permission["dataEraseAt"])
    checks = [(detail["hiu"]["id"] == hip.hiu_id(request.hospital), "it is for a different HIU"),
              (detail["patient"]["id"].lower() == request.abha_address.lower(), "it is for a different patient"),
              (bool(detail["hiTypes"]) and set(detail["hiTypes"]) <= set(request.hi_types), "it covers types that were not requested"),
              (detail["purpose"]["code"] == request.purpose_code, "its purpose differs from the request"),
              (request.date_from - timedelta(seconds=1) <= start <= end <= request.date_to + timedelta(seconds=1),
               "its date range is wider than requested"),
              (erase_at > utcnow(), "it has already expired"), (bool(detail["careContexts"]), "it lists no care contexts")]
    problem = next((message for ok, message in checks if not ok), None)
    artefact = HiuConsentArtefact(
        consent_request=request, artefact_id=detail["consentId"], hip_id=detail["hip"]["id"], detail=detail, fetched_at=utcnow(),
        hi_types=detail["hiTypes"], care_contexts=detail["careContexts"], date_from=start, date_to=end, data_erase_at=erase_at,
        status="invalid" if problem else "valid", status_message=f"Artefact not accepted: {problem}" if problem else
        f"Valid consent from {source} for {', '.join(detail['hiTypes'])}")
    db.add(artefact)
    return artefact

def request_data(db: Session, artefact: HiuConsentArtefact, send) -> HiuDataRequest:
    request, keys = artefact.consent_request, hip.new_keys()
    data_request = HiuDataRequest(artefact_id=artefact.id, request_id=str(uuid.uuid4()), push_token=secrets.token_urlsafe(32),
                                  status="requested", expires_at=utcnow() + timedelta(hours=24), pages_expected=1)
    db.add(data_request)
    db.flush()
    reply = send({"public": keys["public"], "nonce": keys["nonce"]})
    if reply.get("error"):
        data_request.status, data_request.status_message = "failed", f"The provider answered: {reply['error']}"
        return data_request
    material, allowed = reply["keyMaterial"], {c["careContextReference"] for c in artefact.care_contexts}
    stored, refused = 0, 0
    for entry in reply["entries"]:
        try:
            if entry["careContextReference"] not in allowed:
                raise ValueError("care context not covered by the consent")
            content = hip.decrypt(entry["content"], keys, material["dhPublicKey"]["keyValue"], material["nonce"])
            if (bundle := json.loads(content)).get("resourceType") != "Bundle":
                raise ValueError("content is not a FHIR Bundle")
        except Exception:
            refused += 1
            continue
        facts, stored = describe(bundle), stored + 1
        db.add(RetrievedRecord(
            hospital_id=request.hospital_id, patient_id=request.patient_id, data_request_id=data_request.id,
            consent_artefact_id=artefact.artefact_id, source_hip_id=artefact.hip_id, source_name=facts["source"],
            care_context_reference=entry["careContextReference"], record_type=facts["record_type"], category=facts["category"],
            record_date=hip.parse_time(facts["date"]), content=seal(content), mode=hip.MODE, erase_at=artefact.data_erase_at,
            checksum_ok=hashlib.md5(content.encode()).hexdigest() == entry.get("checksum"), validation_issues=prechecks(bundle)))
    data_request.status, data_request.transaction_id, data_request.pages_received = "received", reply["transactionId"], 1
    data_request.status_message = f"{stored} record(s) received and stored" + (f"; {refused} refused" if refused else "")
    audit(db, None, "hiu.data_received", "patient", request.patient_id, {"consent": artefact.artefact_id, "records": stored},
          hospital_id=request.hospital_id)
    return data_request

def enforce_retention(db: Session) -> None:
    for row in db.scalars(select(RetrievedRecord).where(RetrievedRecord.erase_at <= utcnow())):
        db.delete(row)
    db.commit()

def validate_record(record_id: int) -> None:
    with SessionLocal() as db:
        if row := db.get(RetrievedRecord, record_id):
            row.validation_status, row.validation_issues, _ = validate(bundle_json(row))
            db.commit()
