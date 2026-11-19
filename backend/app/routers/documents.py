import logging
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.extraction import (DOCX_TYPE, ExtractionError, ReviewedRecord, blank_record, document_text, extract,
                            iter_fields, refresh_status, value)
from app.models import ClinicalDocument, Doctor, FhirRecord, Patient, User
from app.routers.fhir import store_record
from app.schemas import DocumentOut, DocumentSummary, DocumentUpdate, Page, ReasonRequest
from app.security import require
from app.services import (audit, commit, current_doctor, get_or_404, mark_approved, name_similarity, paginate,
                          require_status)

router = APIRouter(tags=["documents"])
log = logging.getLogger(__name__)

FILE_TYPES = {
    ".pdf": ("application/pdf", b"%PDF"), ".png": ("image/png", b"\x89PNG"), ".jpg": ("image/jpeg", b"\xff\xd8"),
    ".jpeg": ("image/jpeg", b"\xff\xd8"), ".gif": ("image/gif", b"GIF8"), ".webp": ("image/webp", b"RIFF"),
    ".docx": (DOCX_TYPE, b"PK"), ".txt": ("text/plain", b""),
}


def run_extraction(document_id: int, user_id: int) -> None:
    with SessionLocal() as db:
        doc = db.get(ClinicalDocument, document_id)
        try:
            record = extract((settings.upload_dir / doc.storage_name).read_bytes(), doc.content_type, doc.file_name)
            doc.ai_output = doc.data = record.model_dump(mode="json")
            doc.document_type, doc.extraction_status, doc.extraction_error = record.document_type, "completed", None
            doc.ai_model = settings.ai_model
        except Exception as exc:
            if not isinstance(exc, ExtractionError):
                log.exception("Unexpected extraction failure for document %s", document_id)
            doc.extraction_status, doc.extraction_error = "failed", str(exc)[:500]
            doc.data = doc.data or blank_record(doc.document_type).model_dump(mode="json")
        audit(db, db.get(User, user_id), "document.extract", "document", doc.id,
              {"status": doc.extraction_status, "model": settings.ai_model})
        db.commit()


def requirements(doc: ClinicalDocument, record: ReviewedRecord | None) -> list[str]:
    needs = []
    if doc.patient_id is None:
        needs.append("Link the document to a registered patient")
    if doc.author_doctor_id is None:
        needs.append("Select the doctor responsible for this record")
    if record is None:
        return needs + ["Wait for extraction to finish"]
    uncertain = [p for p, f in iter_fields(record) if f.status == "uncertain" and f.review == "pending"]
    if uncertain:
        needs.append(f"Accept, edit or reject {len(uncertain)} low-confidence field(s)")
    iso = r"\d{4}-\d{2}-\d{2}"
    kind, enc = doc.document_type, record.encounter
    if kind == "prescription" and not any(value(m.name) and (value(m.dosage) or value(m.frequency)) for m in record.medications):
        needs.append("Add at least one medicine with its dosage or frequency")
    if kind == "lab_report":
        if not any(value(r.test_name) and value(r.value) for r in record.lab_results):
            needs.append("Add at least one laboratory result with a value")
        if not value(record.report_conclusion):
            needs.append("Enter the report conclusion (required by the ABDM DiagnosticReport profile)")
    if kind == "opd_consultation" and not re.fullmatch(iso, value(enc.visit_date) or value(record.document_date) or ""):
        needs.append("Enter the visit date as YYYY-MM-DD")
    if kind == "discharge_summary" and not re.fullmatch(iso, value(enc.admission_date) or ""):
        needs.append("Enter the admission date as YYYY-MM-DD")
    if kind == "immunization" and not any(value(i.vaccine) and re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", value(i.date) or "")
                                          for i in record.immunizations):
        needs.append("Add at least one vaccine with a date (YYYY, YYYY-MM or YYYY-MM-DD)")
    if kind == "wellness" and not any(value(v.name) and value(v.value) for v in record.vitals):
        needs.append("Add at least one measurement")
    return needs


def patient_warnings(doc: ClinicalDocument, record: ReviewedRecord | None) -> list[str]:
    if not (record and doc.patient):
        return []
    warnings, p = [], record.patient
    if value(p.name) and name_similarity(value(p.name), doc.patient.full_name) < 0.85:
        warnings.append(f"Name on document '{value(p.name)}' differs from the registered patient '{doc.patient.full_name}'")
    mobile = re.sub(r"\D", "", value(p.mobile) or "")[-10:]
    if mobile and mobile != doc.patient.mobile:
        warnings.append(f"Mobile on document {mobile} differs from the registered {doc.patient.mobile}")
    gender = (value(p.gender) or "").strip().upper()[:1]
    if gender in ("M", "F") and gender != doc.patient.gender:
        warnings.append(f"Gender on document '{value(p.gender)}' differs from the registered patient")
    return warnings


def document_out(db: Session, doc: ClinicalDocument) -> dict:
    record = ReviewedRecord.model_validate(doc.data) if doc.data else None
    fields = [f for _, f in iter_fields(record)] if record else []
    counts = {
        "with_value": sum(f.value is not None and f.review != "rejected" for f in fields),
        "ai": sum(f.source == "ai" and f.value is not None for f in fields),
        "manual": sum(f.source == "manual" and f.value is not None for f in fields),
        "uncertain_pending": sum(f.status == "uncertain" and f.review == "pending" for f in fields),
        "rejected": sum(f.review == "rejected" for f in fields),
    }
    fhir_id = db.scalar(select(FhirRecord.id).where(FhirRecord.source_type == "document", FhirRecord.source_id == doc.id))
    out = DocumentOut.model_validate(doc).model_dump()
    return {**out, "requirements": requirements(doc, record), "review_counts": counts, "fhir_record_id": fhir_id,
            "warnings": patient_warnings(doc, record)}


def apply_provenance(doc: ClinicalDocument, record: ReviewedRecord) -> ReviewedRecord:
    original = dict(iter_fields(ReviewedRecord.model_validate(doc.ai_output))) if doc.ai_output else {}
    for path, f in iter_fields(record):
        ai = original.get(path)
        if f.source == "ai" and (ai is None or ai.value != f.value):
            f.source, f.confidence, f.evidence = "manual", None, None
        if f.source == "manual" and f.value is not None and f.review != "rejected":
            f.review = "edited"
    return refresh_status(record)


@router.get("/documents", response_model=Page[DocumentSummary])
def list_documents(status: str | None = None, patient_id: int | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   user: User = Depends(require("document:read")), db: Session = Depends(get_db)):
    query = select(ClinicalDocument).where(ClinicalDocument.hospital_id == user.hospital_id) \
        .order_by(ClinicalDocument.id.desc())
    if status:
        query = query.where(ClinicalDocument.status.in_(status.split(",")))
    if patient_id:
        query = query.where(ClinicalDocument.patient_id == patient_id)
    return paginate(db, query, page, page_size)


@router.post("/documents", response_model=DocumentOut, status_code=201)
def upload_document(background: BackgroundTasks, request: Request, file: UploadFile = File(...),
                    patient_id: int | None = Form(None), user: User = Depends(require("document:write")),
                    db: Session = Depends(get_db)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in FILE_TYPES:
        raise HTTPException(415, "Supported files: PDF (including scanned), JPG, PNG, GIF, WEBP, DOCX and TXT")
    content_type, magic = FILE_TYPES[suffix]
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Files must be {settings.max_upload_mb} MB or smaller")
    if not data or not data.startswith(magic):
        raise HTTPException(415, f"The file content does not look like a {suffix} file")
    try:
        text = document_text(data, content_type)
    except Exception:
        raise HTTPException(415, "The DOCX file could not be read")
    if patient_id:
        get_or_404(db, Patient, patient_id, user.hospital_id)
    storage_name = f"{uuid4().hex}{suffix}"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / storage_name).write_bytes(data)
    doc = ClinicalDocument(hospital_id=user.hospital_id, patient_id=patient_id, file_name=Path(file.filename).name[:255],
                           content_type=content_type, file_size=len(data), storage_name=storage_name, text=text,
                           created_by_id=user.id, status="draft")
    db.add(doc)
    db.flush()
    audit(db, user, "document.upload", "document", doc.id, {"type": suffix, "size": len(data)}, request)
    db.commit()
    background.add_task(run_extraction, doc.id, user.id)
    return document_out(db, doc)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, request: Request, user: User = Depends(require("document:read")),
                 db: Session = Depends(get_db)):
    doc = get_or_404(db, ClinicalDocument, document_id, user.hospital_id)
    audit(db, user, "document.view", "document", doc.id, request=request)
    db.commit()
    return document_out(db, doc)


@router.get("/documents/{document_id}/file")
def document_file(document_id: int, user: User = Depends(require("document:read")), db: Session = Depends(get_db)):
    doc = get_or_404(db, ClinicalDocument, document_id, user.hospital_id)
    return FileResponse(settings.upload_dir / doc.storage_name, media_type=doc.content_type, filename=doc.file_name,
                        content_disposition_type="inline")


@router.post("/documents/{document_id}/extract", response_model=DocumentOut)
def retry_extraction(document_id: int, background: BackgroundTasks, user: User = Depends(require("document:write")),
                     db: Session = Depends(get_db)):
    doc = get_or_404(db, ClinicalDocument, document_id, user.hospital_id)
    require_status(doc, "draft", "rejected", action="extract again")
    if doc.ai_output and doc.data != doc.ai_output:
        raise HTTPException(409, "The record has already been reviewed; re-extracting would discard those changes")
    doc.extraction_status, doc.extraction_error, doc.data, doc.ai_output = "pending", None, None, None
    db.commit()
    background.add_task(run_extraction, doc.id, user.id)
    return document_out(db, doc)


@router.put("/documents/{document_id}", response_model=DocumentOut)
def save_review(document_id: int, body: DocumentUpdate, request: Request,
                user: User = Depends(require("document:write")), db: Session = Depends(get_db)):
    doc = get_or_404(db, ClinicalDocument, document_id, user.hospital_id)
    require_status(doc, "draft", "rejected", action="edit document")
    changes = sorted(body.model_fields_set)
    if "patient_id" in body.model_fields_set:
        doc.patient_id = body.patient_id and get_or_404(db, Patient, body.patient_id, user.hospital_id).id
    if "author_doctor_id" in body.model_fields_set:
        doc.author_doctor_id = body.author_doctor_id and get_or_404(db, Doctor, body.author_doctor_id, user.hospital_id).id
    if body.document_type:
        doc.document_type = body.document_type
    if body.data is not None:
        record = apply_provenance(doc, ReviewedRecord.model_validate(body.data))
        record.document_type = doc.document_type
        doc.data = record.model_dump(mode="json")
    doc.status = "draft"
    audit(db, user, "document.review", "document", doc.id, {"changed": changes}, request)
    return document_out(db, commit(db, doc))


@router.post("/documents/{document_id}/submit", response_model=DocumentOut)
def submit_document(document_id: int, request: Request, user: User = Depends(require("document:write")),
                    db: Session = Depends(get_db)):
    doc = get_or_404(db, ClinicalDocument, document_id, user.hospital_id)
    require_status(doc, "draft", "rejected", action="submit document")
    needs = requirements(doc, ReviewedRecord.model_validate(doc.data) if doc.data else None)
    if needs:
        raise HTTPException(422, {"message": "The document is not ready for approval", "requirements": needs})
    doc.status, doc.status_reason = "pending_approval", None
    audit(db, user, "document.submit", "document", doc.id, request=request)
    db.commit()
    return document_out(db, doc)


@router.post("/documents/{document_id}/approve", response_model=DocumentOut)
def approve_document(document_id: int, request: Request, user: User = Depends(require("document:approve")),
                     db: Session = Depends(get_db)):
    doc = get_or_404(db, ClinicalDocument, document_id, user.hospital_id)
    require_status(doc, "pending_approval", action="approve document")
    doctor = current_doctor(db, user)
    mark_approved(doc, user)
    doc.approved_by_doctor = doctor
    db.flush()
    audit(db, user, "document.approve", "document", doc.id, request=request)
    store_record(db, user, "document", doc.id, request)
    db.commit()
    return document_out(db, doc)


@router.post("/documents/{document_id}/reject", response_model=DocumentOut)
def reject_document(document_id: int, body: ReasonRequest, request: Request,
                    user: User = Depends(require("document:approve")), db: Session = Depends(get_db)):
    doc = get_or_404(db, ClinicalDocument, document_id, user.hospital_id)
    require_status(doc, "pending_approval", action="reject document")
    current_doctor(db, user)
    doc.status, doc.status_reason = "rejected", body.reason
    audit(db, user, "document.reject", "document", doc.id, {"reason": body.reason}, request)
    db.commit()
    return document_out(db, doc)


@router.post("/documents/{document_id}/cancel", response_model=DocumentOut)
def cancel_document(document_id: int, body: ReasonRequest, request: Request,
                    user: User = Depends(require("document:write")), db: Session = Depends(get_db)):
    doc = get_or_404(db, ClinicalDocument, document_id, user.hospital_id)
    require_status(doc, "draft", "pending_approval", "rejected", action="cancel document")
    doc.status, doc.status_reason = "cancelled", body.reason
    audit(db, user, "document.cancel", "document", doc.id, {"reason": body.reason}, request)
    db.commit()
    return document_out(db, doc)
