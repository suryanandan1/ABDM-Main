from datetime import date, datetime, timezone
from html import escape
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel

from app.models import Doctor, Hospital, Patient
from app.schemas import FREQUENCIES, ROUTES, VITAL_SIGNS

FHIR_VERSION, IG_PACKAGE = "4.0.1", "ndhm.in#6.5.0"
NRCES = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/"
SNOMED, LOINC, UCUM = "http://snomed.info/sct", "http://loinc.org", "http://unitsofmeasure.org"
ICD10, HL7 = "http://hl7.org/fhir/sid/icd-10", "http://terminology.hl7.org/CodeSystem/"

LOINC_DISPLAY = {"2708-6": "Oxygen saturation in Arterial blood", "85354-9": "Blood pressure panel with all children optional"}
RecordType = Literal["OPConsultRecord", "PrescriptionRecord", "DiagnosticReportRecord", "DischargeSummaryRecord",
                     "ImmunizationRecord", "WellnessRecord", "HealthDocumentRecord"]


class ClinicalContent(BaseModel):
    record_type: RecordType
    key: str
    title: str
    date: datetime
    encounter: dict | None = None
    conditions: list[dict] = []
    allergies: list[dict] = []
    observations: list[dict] = []
    medications: list[dict] = []
    orders: list[dict] = []
    reports: list[dict] = []
    immunizations: list[dict] = []
    attachment: dict | None = None
    text: dict = {}


def uid(kind: str, key) -> str:
    return str(uuid5(NAMESPACE_URL, f"abdm-hospital/{kind}/{key}"))


def ref(res: dict, display: str | None = None, typed: bool = False) -> dict:
    out = {"reference": f"urn:uuid:{res['id']}", "type": res["resourceType"] if typed else None, "display": display}
    return {k: v for k, v in out.items() if v}


def coded(system: str, code: str, display: str, text: str | None = None) -> dict:
    return {"coding": [{"system": system, "code": code, "display": display}], "text": text or display}


def iso(value) -> str | None:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")
    return value.isoformat() if isinstance(value, date) else value


def narrative(text: str) -> dict:
    lines = "".join(f"<p>{escape(line)}</p>" for line in text.splitlines() if line.strip()) or "<p/>"
    return {"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{lines}</div>'}


def resource(rtype: str, rid: str, profile: str | None, summary: str, **fields) -> dict:
    res = {"resourceType": rtype, "id": rid, "meta": {"profile": [NRCES + profile]} if profile else None,
           "text": narrative(summary), **fields}
    return {k: v for k, v in res.items() if v not in (None, "", [], {})}


def identifier(code: str, display: str, system: str, value: str, code_system: str = HL7 + "v2-0203") -> dict:
    return {"type": {"coding": [{"system": code_system, "code": code, "display": display}]}, "system": system, "value": value}


def local(h: Hospital, what: str) -> str:
    return f"urn:abdm-hospital:{h.code.lower()}:{what}"


def organization(h: Hospital) -> dict:
    ident = (identifier("PRN", "Provider number", "https://facility.ndhm.gov.in", h.hfr_id) if h.hfr_id
             else identifier("XX", "Organization identifier", local(h, "organization"), h.code))
    return resource("Organization", uid("organization", h.id), "Organization", h.name, identifier=[ident], name=h.name,
                    telecom=[{"system": "phone", "value": h.phone, "use": "work"}] if h.phone else None)


def patient(p: Patient, h: Hospital) -> dict:
    ids = [identifier("MR", "Medical record number", local(h, "patient"), p.patient_code)]
    if p.abha_verified and p.abha_number:
        n = p.abha_number
        ids.append(identifier("ABHA", "Ayushman Bharat Health Account (ABHA) ID", "https://healthid.ndhm.gov.in",
                              f"{n[:2]}-{n[2:6]}-{n[6:10]}-{n[10:]}",
                              "https://nrces.in/ndhm/fhir/r4/CodeSystem/ndhm-identifier-type-code"))
    return resource("Patient", uid("patient", p.id), "Patient", f"{p.full_name}, {p.patient_code}", identifier=ids,
                    name=[{"text": p.full_name}], telecom=[{"system": "phone", "value": f"+91{p.mobile}", "use": "mobile"}],
                    gender={"M": "male", "F": "female", "O": "other", "U": "unknown"}[p.gender],
                    birthDate=iso(p.date_of_birth) or str(p.year_of_birth))


def practitioner(d: Doctor, h: Hospital) -> dict:
    ids = [identifier("MD", "Medical License number", "https://doctor.ndhm.gov.in", d.hpr_id)] if d.hpr_id else []
    ids.append(identifier("MD", "Medical License number", local(h, "medical-registration"), d.registration_number))
    return resource("Practitioner", uid("practitioner", d.id), "Practitioner", d.full_name, identifier=ids,
                    name=[{"text": d.full_name}], qualification=[{"code": {"text": d.qualification}}] if d.qualification else None)


class Builder:
    def __init__(self, c: ClinicalContent, p: Patient, h: Hospital, author: Doctor, doctors: list[Doctor]):
        self.c, self.h, self.resources, self.encounter = c, h, [], None
        self.org, self.patient = organization(h), patient(p, h)
        self.doctors = {d.id: practitioner(d, h) for d in [author, *doctors]}
        self.author, self.author_name = self.doctors[author.id], author.full_name
        self.role = resource("PractitionerRole", uid("practitioner-role", author.id), "PractitionerRole",
                             f"{author.full_name} at {h.name}", practitioner=ref(self.author, author.full_name),
                             organization=ref(self.org, h.name),
                             specialty=[{"text": author.specialization}] if author.specialization else None)
        if e := c.encounter:
            kind = ("IMP", "inpatient encounter") if e.get("inpatient") else ("AMB", "ambulatory")
            self.encounter = self.add(
                "Encounter", "encounter", 0, "Encounter", "Inpatient visit" if e.get("inpatient") else "Outpatient visit",
                identifier=[{"system": local(h, "encounter"), "value": c.key}], status=e.get("status", "finished"),
                **{"class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": kind[0], "display": kind[1]}},
                **self.subject(), participant=[{"individual": ref(self.role, author.full_name)}],
                period={k: iso(e[k]) for k in ("start", "end") if e.get(k)}, serviceProvider=ref(self.org, h.name),
                reasonCode=[{"text": e["reason"]}] if e.get("reason") else None)

    def add(self, rtype: str, kind: str, index, profile: str | None, summary: str, **fields) -> dict:
        self.resources.append(resource(rtype, uid(kind, f"{self.c.key}/{index}"), profile, summary, **fields))
        return self.resources[-1]

    def subject(self, field: str = "subject") -> dict:
        about = {field: ref(self.patient, self.patient["name"][0]["text"])}
        return {**about, "encounter": ref(self.encounter)} if self.encounter else about

    def conditions(self) -> list[dict]:
        result = []
        for i, x in enumerate(self.c.conditions):
            clinical, verification = x.get("clinical_status", "active"), x.get("verification", "provisional")
            icd = [{"system": ICD10, "code": x["icd10"][0], "display": x["icd10"][1]}] if x.get("icd10") else []
            result.append(self.add(
                "Condition", "condition", i, "Condition", x["text"], **self.subject(), recordedDate=iso(self.c.date),
                clinicalStatus=coded(HL7 + "condition-clinical", clinical, clinical.capitalize()),
                verificationStatus=coded(HL7 + "condition-ver-status", verification, verification.capitalize()),
                code={"coding": icd, "text": x["text"]} if icd else {"text": x["text"]},
                onsetDateTime=iso(x.get("onset")), note=[{"text": x["note"]}] if x.get("note") else None))
        return result

    def allergies(self) -> list[dict]:
        return [self.add("AllergyIntolerance", "allergy", i, "AllergyIntolerance", a["text"], **self.subject("patient"),
                         clinicalStatus=coded(HL7 + "allergyintolerance-clinical", "active", "Active"),
                         verificationStatus=coded(HL7 + "allergyintolerance-verification", "unconfirmed", "Unconfirmed"),
                         code={"text": a["text"]}, recordedDate=iso(self.c.date), recorder=ref(self.author),
                         reaction=[{"manifestation": [{"text": a["reaction"]}]}] if a.get("reaction") else None)
                for i, a in enumerate(self.c.allergies)]

    def observations(self, wellness: bool = False) -> list[dict]:
        when = iso(self.c.encounter["start"] if self.c.encounter else self.c.date)
        vitals = {o["key"]: o for o in self.c.observations if o.get("key") in VITAL_SIGNS and o.get("value") is not None}
        def quantity(key: str) -> dict:
            return {"value": vitals[key]["value"], "unit": VITAL_SIGNS[key][2], "system": UCUM, "code": VITAL_SIGNS[key][2]}

        def vital(key: str, name: str, loinc: str, **value) -> dict:
            profile = ("ObservationBodyMeasurement" if key in ("weight", "height") else "ObservationVitalSigns") \
                if wellness else "Observation"
            return self.add("Observation", "vital", key, profile, name, status="final", **self.subject(),
                            category=[coded(HL7 + "observation-category", "vital-signs", "Vital Signs")],
                            code=coded(LOINC, loinc, LOINC_DISPLAY.get(loinc, name), name), effectiveDateTime=when,
                            performer=[ref(self.author)], **value)

        result = [vital(k, name, loinc, valueQuantity=quantity(k)) for k, (name, loinc, *_) in VITAL_SIGNS.items()
                  if k in vitals and not k.endswith("_bp")]
        if bp := [k for k in ("systolic_bp", "diastolic_bp") if k in vitals]:
            result.append(vital("bp", "Blood pressure", "85354-9", component=[
                {"code": coded(LOINC, VITAL_SIGNS[k][1], VITAL_SIGNS[k][0]), "valueQuantity": quantity(k)} for k in bp]))
        for i, o in enumerate(o for o in self.c.observations if o.get("key") not in vitals):
            value = ({"valueQuantity": {"value": o["value"], **({"unit": o["unit"]} if o.get("unit") else {})}}
                     if o.get("value") is not None else {"valueString": o.get("value_text")})
            result.append(self.add("Observation", "observation", i, "Observation", o["name"], status="final",
                                   code={"text": o["name"]}, **self.subject(), effectiveDateTime=when,
                                   performer=[ref(self.author)], **value))
        return result

    def medications(self) -> list[dict]:
        result = []
        for i, m in enumerate(self.c.medications):
            freq, days = FREQUENCIES.get(m.get("frequency")), m.get("duration_days")
            parts = [m.get("dosage"), freq[0].lower() if freq else m.get("frequency_text"),
                     f"for {days} days" if days else m.get("duration_text")]
            dosage = {"text": " ".join(filter(None, parts)) or m.get("instructions") or m["name"]}
            if freq and freq[1] is None:
                dosage["asNeededBoolean"] = True
            elif freq:
                bounds = {"boundsDuration": {"value": days, "unit": "days", "system": UCUM, "code": "d"}} if days else {}
                dosage["timing"] = {"repeat": {**freq[1], **bounds}}
            if route := ROUTES.get(m.get("route")):
                dosage["route"] = coded(SNOMED, route[1], route[2], route[0])
            dosage.update({"patientInstruction": m["instructions"]} if m.get("instructions") else {})
            result.append(self.add(
                "MedicationRequest", "medication", i, "MedicationRequest", f"{m['name']}: {dosage['text']}",
                status="active", intent="order", medicationCodeableConcept={"text": m["name"]},
                **self.subject(), authoredOn=iso(self.c.date.date()), requester=ref(self.author, self.author_name),
                dosageInstruction=[dosage], dispenseRequest={"quantity": {"value": m["quantity"]}} if m.get("quantity") else None))
        return result

    def orders(self) -> list[dict]:
        def requester(doctor_id) -> dict:
            doctor = self.doctors.get(doctor_id, self.author)
            return ref(doctor, doctor["name"][0]["text"])

        return [self.add("ServiceRequest", "order", i, "ServiceRequest", o["name"], status=o.get("status", "active"),
                         intent="order", priority=o.get("priority", "routine"), code={"text": o["name"]}, **self.subject(),
                         authoredOn=iso(o.get("authored")), requester=requester(o.get("requester")),
                         note=[{"text": o["note"]}] if o.get("note") else None) for i, o in enumerate(self.c.orders)]

    def reports(self, orders: list[dict]) -> list[dict]:
        flags, result = {"N": "Normal", "L": "Low", "H": "High", "A": "Abnormal"}, []
        for i, r in enumerate(self.c.reports):
            observations = []
            for j, x in enumerate(r["results"]):
                unit = {"unit": x["unit"]} if x.get("unit") else {}
                limits = {k: {"value": x[f"ref_{k}"], **unit} for k in ("low", "high") if x.get(f"ref_{k}") is not None}
                limits.update({"text": x["ref_text"]} if x.get("ref_text") else {})
                flag = x.get("interpretation")
                observations.append(self.add(
                    "Observation", "lab-result", f"{i}/{j}", "Observation", f"{x['name']}: {x['value']} {x.get('unit') or ''}",
                    status="final", category=[coded(HL7 + "observation-category", "laboratory", "Laboratory")],
                    code={"coding": [x["loinc"]], "text": x["name"]} if x.get("loinc") else {"text": x["name"]},
                    **self.subject(), effectiveDateTime=iso(r.get("effective")), performer=[ref(self.org, self.h.name)],
                    **({"valueQuantity": {"value": x["value_num"], **unit}} if x.get("value_num") is not None
                       else {"valueString": x["value"]}),
                    interpretation=[coded(HL7 + "v3-ObservationInterpretation", flag, flags[flag])] if flag else None,
                    referenceRange=[limits] if limits else None))
            interpreter = self.doctors.get(r.get("interpreter"))
            result.append(self.add(
                "DiagnosticReport", "diagnostic-report", i, "DiagnosticReportLab", r["name"], status="final",
                basedOn=[ref(o) for o in orders], category=[coded(SNOMED, "15220000", "Laboratory test")],
                code={"coding": [r["loinc"]], "text": r["name"]} if r.get("loinc") else {"text": r["name"]},
                **self.subject(), effectiveDateTime=iso(r.get("effective")), issued=iso(r.get("issued")),
                performer=[ref(self.org, self.h.name)], result=[ref(o) for o in observations], conclusion=r.get("conclusion"),
                resultsInterpreter=[ref(interpreter, interpreter["name"][0]["text"])] if interpreter else None))
        return result

    def immunizations(self) -> list[dict]:
        return [self.add("Immunization", "immunization", i, "Immunization", im["vaccine"], status="completed",
                         vaccineCode={"text": im["vaccine"]}, **self.subject("patient"), occurrenceDateTime=im.get("occurrence"),
                         primarySource=False, lotNumber=im.get("lot_number"),
                         protocolApplied=[{"doseNumberPositiveInt": im["dose_number"]}] if im.get("dose_number") else None)
                for i, im in enumerate(self.c.immunizations)]

    def attachment(self, binary: bool = False) -> list[dict]:
        if not (a := self.c.attachment):
            return []
        if binary:
            self.resources.append({"resourceType": "Binary", "id": uid("binary", f"{self.c.key}/0"),
                                   "meta": {"profile": [NRCES + "Binary"]}, "contentType": a["content_type"], "data": a["data"]})
            return [self.resources[-1]]
        return [self.add("DocumentReference", "document-reference", 0, "DocumentReference", a["title"], status="current",
                         docStatus="final", type={"text": a["title"]}, subject=self.subject()["subject"], date=iso(self.c.date),
                         author=[ref(self.author)], custodian=ref(self.org),
                         content=[{"attachment": {"contentType": a["content_type"], "data": a["data"], "title": a["title"]}}],
                         context={"encounter": [ref(self.encounter)]} if self.encounter else None)]


COMPOSITION_TYPES = {
    "OPConsultRecord": ("371530004", "Clinical consultation report"), "PrescriptionRecord": ("440545006", "Prescription record"),
    "DiagnosticReportRecord": ("721981007", "Diagnostic studies report"), "DischargeSummaryRecord": ("373942005", "Discharge summary"),
    "ImmunizationRecord": ("41000179103", "Immunization record"), "HealthDocumentRecord": ("419891008", "Record artifact")}
LABELS = {"chief_complaint": "Chief complaint", "history": "History", "plan": "Plan", "follow_up": "Follow-up",
          "notes": "Notes", "hospital_course": "Hospital course"}


def section(title: str, code: tuple | None, entries: list | None = None, text: str | None = None) -> dict | None:
    out = {"title": title, "code": {"coding": [{"system": SNOMED, "code": code[0], "display": code[1]}]} if code else None,
           "entry": [ref(e, typed=True) for e in entries or []], "text": narrative(text) if text else None}
    return {k: v for k, v in out.items() if v} if entries or text else None


def build_sections(b: Builder) -> list[dict | None]:
    c, kind = b.c, b.c.record_type

    def text(*keys: str) -> str | None:
        return "\n".join(f"{LABELS[k]}: {c.text[k]}" for k in keys if c.text.get(k)) or None

    if kind in ("OPConsultRecord", "DischargeSummaryRecord"):
        op = kind == "OPConsultRecord"
        orders = b.orders() if op else []
        return [section("Chief complaints", ("422843007", "Chief complaint section"), b.conditions(),
                        text("chief_complaint", "history") if op else text("chief_complaint")),
                section("Allergies", ("722446000", "Allergy record"), b.allergies()),
                None if op else section("Medical history", ("1003642006", "Past medical history section"), None,
                                        c.text.get("history")),
                section("Physical examination", ("425044008", "Physical exam section"), b.observations(), c.text.get("findings")),
                section("Investigation advice", ("721963009", "Order document"), orders) if op else
                section("Investigations", ("721981007", "Diagnostic studies report"), b.reports([])),
                section("Medications", ("721912009", "Medication summary document") if op else
                        ("1003606003", "Medication history section"), b.medications()),
                section("Follow up", ("390906007", "Follow-up encounter"), None, text("plan", "follow_up", "notes")) if op else
                section("Care plan", ("734163000", "Care plan"), None, text("hospital_course", "plan", "follow_up", "notes")),
                section("Document reference", COMPOSITION_TYPES[kind], b.attachment())]
    if kind == "WellnessRecord":
        observations = b.observations(wellness=True)

        def group(end: str) -> list[dict]:
            return [o for o in observations if o["meta"]["profile"][0].endswith(end)]

        return [section("Vital Signs", None, group("VitalSigns")), section("Body Measurement", None, group("BodyMeasurement")),
                section("Other Observations", None, group("/Observation"), c.text.get("notes")),
                section("Document Reference", None, b.attachment())]
    entries = {"PrescriptionRecord": lambda: b.medications() + b.attachment(binary=True),
               "DiagnosticReportRecord": lambda: b.reports(b.orders()) + b.attachment(),
               "ImmunizationRecord": lambda: b.immunizations() + b.attachment(),
               "HealthDocumentRecord": b.attachment}[kind]()
    notes = c.text.get("notes") if kind == "PrescriptionRecord" or not c.attachment else None
    return [section(COMPOSITION_TYPES[kind][1], COMPOSITION_TYPES[kind], entries,
                    None if kind in ("DiagnosticReportRecord", "ImmunizationRecord") else notes)]


def build_bundle(c: ClinicalContent, p: Patient, h: Hospital, author: Doctor, doctors=(), version: int = 1) -> dict:
    b = Builder(c, p, h, author, list(doctors))
    sections = [s for s in build_sections(b) if s]
    kind = COMPOSITION_TYPES.get(c.record_type)
    # A doctor no other resource points to (e.g. a different doctor approved the record) must still be linked from the
    # Composition, or the bundle fails validation ("isn't reachable ... from the Composition"): record them as attester.
    used = repr(b.resources)
    approvers = [{"mode": "professional", "time": iso(c.date), "party": ref(d, d["name"][0]["text"])}
                 for d in b.doctors.values() if d is not b.author and f"urn:uuid:{d['id']}" not in used]
    composition = resource(
        "Composition", uid("composition", c.key), c.record_type, c.title, status="final", title=c.title,
        identifier={"system": local(h, "document"), "value": uid("composition", c.key)}, date=iso(c.date),
        type=coded(SNOMED, *kind) if kind else {"text": "Wellness Record"}, subject=b.subject()["subject"],
        encounter=ref(b.encounter) if b.encounter else None, author=[ref(b.author, b.author_name)],
        attester=[{"mode": "legal", "time": iso(c.date), "party": ref(b.role, b.author_name)}, *approvers],
        custodian=ref(b.org, h.name), section=sections)
    now = iso(datetime.now(timezone.utc))
    entries = [composition, b.patient, *b.doctors.values(), b.role, b.org, *b.resources]
    return {"resourceType": "Bundle", "id": uid("bundle", c.key),
            "meta": {"versionId": str(version), "lastUpdated": now, "profile": [NRCES + "DocumentBundle"]},
            "identifier": {"system": local(h, "bundle"), "value": uid("bundle", c.key)}, "type": "document",
            "timestamp": now, "entry": [{"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in entries]}
