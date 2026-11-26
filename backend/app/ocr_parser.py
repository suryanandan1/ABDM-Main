"""Rule-based extraction of clinical fields from OCR text (used when no AI model is configured).

Works on the line/tab layout OCR.space returns. Every value keeps the OCR line it came from as evidence, and a
confidence: values read after a clear label ("Date:", "Diagnosis:") score high; values guessed from layout or
corrected OCR mistakes score low, so the review page marks them for checking.
"""
import re

SURE, LIKELY, GUESS = 0.9, 0.82, 0.6

# Labels that start a "key: value" segment inside a line. Longer / more specific spellings first.
LABELS = [
    ("patient_id", r"patient\s*id|uhid|mrn|reg(?:istration)?\.?\s*no\.?\s*\(patient\)"),
    ("ip_no", r"ip\s*no\.?"),
    ("age_sex", r"age\s*/\s*sex|age\s*/\s*gender"),
    ("patient", r"patient(?:'s)?\s*name|patient|name"),
    ("age", r"age"),
    ("gender", r"sex|gender"),
    ("dob", r"d\.?o\.?b\.?|date\s*of\s*birth"),
    ("mobile", r"mobile|mob\.?|contact\s*no\.?"),
    ("abha", r"abha(?:\s*(?:no\.?|number|address|id))?"),
    ("admitted", r"admitted(?:\s*on)?|date\s*of\s*admission|admission\s*date|d\.?o\.?a\.?"),
    ("discharged", r"discharged(?:\s*on)?|date\s*of\s*discharge|discharge\s*date|d\.?o\.?d\.?"),
    ("collected", r"collected(?:\s*on)?"),
    ("reported", r"reported(?:\s*on)?"),
    ("date", r"visit\s*date|date"),
    ("complaint", r"chief\s*complaints?|presenting\s*complaints?|complaints?|c/o"),
    ("history", r"history(?:\s*of\s*present\s*illness)?|h/o"),
    ("findings", r"examination|o/e|on\s*examination|findings|clinical\s*findings"),
    ("vitals", r"vitals?|vital\s*signs"),
    ("diagnosis", r"final\s*diagnosis|provisional\s*diagnosis|diagnosis|dx|diagnoses"),
    ("allergy", r"allerg(?:y|ies)|known\s*allerg(?:y|ies)"),
    ("investigations", r"investigations?|tests?\s*advised"),
    ("advice", r"advice|instructions?"),
    ("follow_up", r"follow[\s-]*up|review|next\s*visit"),
    ("course", r"course\s*in\s*(?:the\s*)?hospital|hospital\s*course"),
    ("condition", r"condition\s*(?:at|on)\s*discharge"),
    ("conclusion", r"impression|conclusion|remarks?|interpretation"),
    ("doctor", r"ref(?:erred)?\.?\s*by|consultant|treating\s*doctor|doctor"),
    ("reg", r"reg(?:istration)?\.?\s*(?:no\.?|number)?"),
    ("ignore", r"ward|bed|sample|barcode|hfr\s*id|ph(?:one)?|tel|email|e-mail|fax|website|gstin|time"),
]
LABEL_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(f"(?P<{k}{i}>{p})" for i, (k, p) in enumerate(LABELS)) + r")\s*[:：]\s*",
                      re.I)
# Section headings: a line that is only one of these words, the following lines belong to it
HEADINGS = {
    "diagnosis": r"(final|provisional)?\s*diagnos[ie]s",
    "complaint": r"(chief|presenting)\s*complaints?",
    "history": r"history(\s*of\s*present\s*illness)?",
    "findings": r"(on\s*)?examination|clinical\s*findings",
    "course": r"course\s*in\s*(the\s*)?hospital|hospital\s*course",
    "condition": r"condition\s*(at|on)\s*discharge",
    "meds": r"rx|r/x|medicines?(\s*(on|at)\s*discharge)?|medications?(\s*(on|at)\s*discharge)?|treatment|discharge\s*medications?",
    "advice": r"advice(\s*(and|&)\s*follow[\s-]*up)?|instructions",
    "conclusion": r"impression|conclusion|remarks",
    "investigations": r"investigations?",
}
HEADING_RE = {k: re.compile(rf"^\s*(?:{p})\s*[:.]?\s*$", re.I) for k, p in HEADINGS.items()}

DATE_RE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})\b")
ICD_RE = re.compile(r"\(\s*([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?)\s*\)")
ICD_OCR_RE = re.compile(r"\(\s*([1l|])([0-9]{2}(?:\.[0-9]{1,4})?)\s*\)")  # I10 read as (110) / (l10)
QUALIFICATIONS = r"MBBS|BAMS|BHMS|BDS|MDS|MD|MS|DM|MCh|DNB|DCH|DGO|DA|DOMS|DLO|FRCS|MRCP|FCPS|PhD|MPH|Dip\.?\s*\w+"
QUAL_RE = re.compile(rf"\b({QUALIFICATIONS})\b")
REG_RE = re.compile(r"reg(?:istration)?\.?\s*(?:no\.?|number)?\s*[:.]?\s*([A-Z]{2,}[A-Z0-9/-]*\d[A-Z0-9/-]*)", re.I)
AGE_SEX_RE = re.compile(r"(\d{1,3}(?:\.\d)?)\s*(y(?:rs?|ears?)?|m(?:onths?|os?)|d(?:ays?)?)\.?\b\s*[/,]?\s*(male|female|m|f|o)?\b", re.I)
GENDERS = {"m": "M", "male": "M", "f": "F", "female": "F", "o": "O"}

FORMS = r"tab(?:let)?s?|cap(?:sule)?s?|syp|syrup|susp(?:ension)?|inj(?:ection)?|drops?|oint(?:ment)?|cream|gel|lotion|" \
        r"inhaler|neb(?:uli[sz]ation)?|sachet|ors|powder|spray|patch|supp(?:ository)?"
STRENGTH = r"\d+(?:\.\d+)?\s*(?:mg|mcg|µg|ug|g|gm|ml|iu|units?|%)(?:\s*/\s*\d*(?:\.\d+)?\s*(?:ml|g))?"
MED_START_RE = re.compile(rf"^\s*(?:\d{{1,2}}\s*[.)]\s*|\d{{1,2}}\s+)?((?:{FORMS})\b.*|[A-Za-z][\w-]*(?:\s+[\w-]+){{0,4}}\s+{STRENGTH}.*)$", re.I)
NUMBER_PREFIX_RE = re.compile(r"^\s*\d{1,2}\s*[.)]?\s+(?=\D)")
FREQ_PATTERNS = [
    (r"\b1\s*-\s*1\s*-\s*1\s*-\s*1\b", "QID"), (r"\b1\s*-\s*1\s*-\s*1\b", "TDS"), (r"\b1\s*-\s*0\s*-\s*1\b", "BD"),
    (r"\b1\s*-\s*0\s*-\s*0\b", "OD"), (r"\b0\s*-\s*0\s*-\s*1\b", "HS"), (r"\b0\s*-\s*1\s*-\s*0\b", "OD"),
    (r"\b1\s*-\s*1\s*-\s*0\b", "BD"), (r"\b0\s*-\s*1\s*-\s*1\b", "BD"),
    (r"\b(?:qid|four\s*times\s*(?:a\s*)?day)\b", "QID"), (r"\b(?:tds|tid|thrice\s*(?:a\s*)?daily|three\s*times\s*(?:a\s*)?day)\b", "TDS"),
    (r"\b(?:bd|bid|twice\s*(?:a\s*)?daily|twice\s*a\s*day)\b", "BD"), (r"\b(?:od|once\s*(?:a\s*)?daily|once\s*a\s*day)\b", "OD"),
    (r"\b(?:hs|at\s*bedtime)\b", "HS"), (r"\b(?:sos|prn|as\s*needed|if\s*needed)\b", "SOS"), (r"\bstat\b", "STAT"),
    (r"\bq\s*6\s*h\b", "Q6H"), (r"\bq\s*8\s*h\b", "Q8H"), (r"\b(?:weekly|once\s*a\s*week)\b", "WEEKLY"),
]
DURATION_RE = re.compile(r"(?:x|×|for|\S)?\s*\b(\d{1,3})\s*(days?|d|weeks?|wks?|months?|mo)\b", re.I)
DOSE_RE = re.compile(r"\b(\d+(?:\.\d+)?\s*(?:tablets?|tabs?|caps?(?:ules?)?|ml|drops?|sachets?|nebs?|puffs?|units?|tsp|tbsp))\b", re.I)
INSTRUCTION_RE = re.compile(r"\b(?:after|before|with|empty)\s+(?:food|meals?|stomach|breakfast|lunch|dinner)\b|\bat\s+night\b|"
                            r"\bin\s+\d+(?:\.\d+)?\s*(?:l|ml|litres?|glass)\s*(?:of\s*)?water\b|\beach\s+nostril\b|\bif\s+fever[^,;]*", re.I)
ROUTE_HINTS = [(r"\b(?:tab|cap|syp|syrup|susp|sachet|ors)", "oral"), (r"\bi\.?v\b|intravenous", "iv"), (r"\bi\.?m\b|intramuscular", "im"),
               (r"\bnasal|nostril", "nasal"), (r"\bneb|inhal", "inhalation"), (r"\beye\b|ophth", "ophthalmic"),
               (r"\bear\b", "otic"), (r"\boint|cream|gel|lotion", "topical"), (r"\binj\b|injection", None)]

VITAL_PATTERNS = [
    ("Temperature", r"\b(?:temp(?:erature)?|t)\s*[:.]?\s*(\d{2,3}(?:\.\d)?)\s*°?\s*([FC])\b", None),
    ("Pulse", r"\b(?:pulse|pr|hr|heart\s*rate)\s*[:.]?\s*(\d{2,3})\s*(/\s*min|bpm)?", "/min"),
    ("Blood pressure", r"\b(?:bp|blood\s*pressure)\s*[:.]?\s*(\d{2,3}\s*/\s*\d{2,3})\s*(mm\s*hg)?", "mmHg"),
    ("SpO2", r"\bspo\s*2\s*[:.]?\s*(\d{2,3})\s*(%)?", "%"),
    ("Respiratory rate", r"\b(?:rr|resp(?:iratory)?\s*rate)\s*[:.]?\s*(\d{1,2})\s*(/\s*min)?", "/min"),
    ("Weight", r"\b(?:wt|weight)\s*[:.]?\s*(\d{1,3}(?:\.\d)?)\s*(kg)?", "kg"),
    ("Height", r"\b(?:ht|height)\s*[:.]?\s*(\d{2,3}(?:\.\d)?)\s*(cm)?", "cm"),
]
LAB_UNIT = r"(?:%|[a-zµ]*[g/]?/?d?[lL]|mg/[a-z]L|g/dL|mmol/L|µmol/L|umol/L|U/L|IU/L|mIU/L|µIU/mL|uIU/mL|ng/mL|pg/mL|" \
           r"10\^?\d+/[uµ]L|/[uµ]L|cells/[uµ]L|fL|pg|mEq/L|sec|ratio)"
LAB_RESULT_WORDS = r"negative|positive|reactive|non[\s-]*reactive|absent|present|nil|trace|normal|detected|not\s*detected"
LAB_ROW_RE = re.compile(rf"^(?P<name>[A-Za-z][A-Za-z0-9 ()./,'+-]*?)\s+(?P<value>\d+(?:\.\d+)?|{LAB_RESULT_WORDS})\s*(?P<flag>H|L|\*|High|Low)?"
                        rf"\s+(?P<unit>{LAB_UNIT}|-)?\s*(?P<range>(?:<|>|≤|≥)?\s*\d+(?:\.\d+)?(?:\s*(?:-|–|to)\s*\d+(?:\.\d+)?)?|{LAB_RESULT_WORDS})?\s*$",
                        re.I)
LAB_INLINE_RE = re.compile(rf"\b([A-Z][A-Za-z0-9]{{1,12}}(?:\s+[A-Za-z0-9]{{1,12}}){{0,2}})\s*:\s*(\d+(?:\.\d+)?)\s*({LAB_UNIT})(?=\s|$)")
NOISE_RE = re.compile(r"sample\s*document|fictional\s*data|^page\s*\d+\s*(of\s*\d+)?$|^signature$|end\s*of\s*report|"
                      r"valid\s*for\s*\d+\s*days|^#?\s*medicine\b|^test\s+result|^[A-Z]\.\s*[A-Z][a-z]+$", re.I)


def field(value, confidence=SURE, evidence=None):
    if value is None or str(value).strip() == "":
        return {"value": None, "confidence": 0, "evidence": None}
    words = (evidence or "").split()
    return {"value": str(value).strip(" ,;:-"), "confidence": confidence,
            "evidence": " ".join(words[:20]) + (" …" if len(words) > 20 else "") or None}


EMPTY = field(None)


def iso_date(text: str):
    m = DATE_RE.search(text or "")
    if not m:
        return None
    d, mo, y = int(m[1]), int(m[2]), int(m[3])
    y += 2000 if y < 100 else 0
    if not (1 <= d <= 31 and 1 <= mo <= 12):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"  # Indian documents write day/month/year


def label_key(m: re.Match) -> str:
    return re.sub(r"\d+$", "", next(k for k, v in m.groupdict().items() if v is not None))


def segments(line: str):
    """Split "Patient: A  Age/Sex: 45 Y/M  Date: 1/2/2026" into [(None, text-before), ("patient", "A"), ...]."""
    out, pos, key = [], 0, None
    for m in LABEL_RE.finditer(line):
        if m.start() > pos or key is not None:
            out.append((key, line[pos:m.start()].strip()))
        key, pos = label_key(m), m.end()
    out.append((key, line[pos:].strip()))
    return [(k, v) for k, v in out if v or k]


def frequency(text: str):
    for pattern, code in FREQ_PATTERNS:
        if re.search(pattern, text, re.I):
            return code
    return None


def parse_age_sex(text: str):
    m = AGE_SEX_RE.search(text)
    if not m:
        g = re.search(r"\b(male|female|m|f)\b", text, re.I)
        return None, GENDERS.get(g[1].lower()) if g else None, text
    unit = m[2].lower()
    unit = "years" if unit.startswith("y") else "months" if unit.startswith("m") else "days"
    return f"{m[1]} {unit}", GENDERS.get((m[3] or "").lower()), text[:m.start()].strip()


def parse_doctor(line: str, record: dict, confidence=SURE):
    doc = record["doctor"]
    m = re.search(r"\bDr\.?\s*([A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*){0,3})", line)
    if m:
        name = "Dr. " + re.split(rf"\s*,|\s+(?:{QUALIFICATIONS})\b|\s*\(", m[1])[0].strip()
        if doc["name"]["value"] and doc["name"]["value"].split()[-1].lower() != name.split()[-1].lower():
            return  # another doctor on the document (pathologist, a colleague's signature)
        if not doc["name"]["value"]:
            doc["name"] = field(name, confidence, line)
    quals = QUAL_RE.findall(line)
    if quals and not doc["qualification"]["value"]:
        doc["qualification"] = field(", ".join(dict.fromkeys(q.strip() for q in quals)), confidence, line)
    spec = re.search(r"\(([A-Za-z][A-Za-z &]+)\)", line)
    if spec and not doc["specialization"]["value"] and not REG_RE.search(spec[1]):
        doc["specialization"] = field(spec[1], LIKELY, line)
    reg = REG_RE.search(line)
    if reg and not doc["registration_number"]["value"]:
        doc["registration_number"] = field(reg[1], confidence, line)


def split_diagnoses(text: str, line: str, record: dict):
    for part in re.split(r";|\s+\d\.\s+|(?<=\))\s*,\s*", text):
        part = re.sub(r"^\s*\d{1,2}\s*[.)]\s*", "", part).strip(" ,.;-")
        if len(part) < 3:
            continue
        code, conf = None, SURE
        m = ICD_RE.search(part)
        if m:
            code = m[1]
        else:
            m = ICD_OCR_RE.search(part)
            if m:
                code, conf = "I" + m[2], GUESS  # OCR read the letter I as 1
        name = re.sub(r"\s*\([^)]*\)\s*", " ", part) if m else part
        name = re.sub(r"\s+-\s*known\s*case.*$", "", name, flags=re.I).strip(" ,.;-")
        record["diagnoses"].append({"text": field(name, SURE, line), "icd10_code": field(code, conf, line)})


def add_vitals(text: str, line: str, record: dict):
    seen = {v["name"]["value"] for v in record["vitals"]}
    for name, pattern, unit in VITAL_PATTERNS:
        m = re.search(pattern, text, re.I)
        if m and name not in seen:
            u = ("°" + m[2].upper()) if name == "Temperature" else unit
            record["vitals"].append({"name": field(name, SURE, line), "value": field(m[1].replace(" ", ""), SURE, line),
                                     "unit": field(u, SURE, line)})


def classify_med_cells(cells: list[str]):
    """Table row cells (in any order, some may be missing) -> medicine parts."""
    parts = {"name": None, "dosage": None, "frequency": None, "duration": None, "instructions": None}
    for c in cells:
        if re.fullmatch(r"\d{1,2}", c) and parts["name"] is None:
            continue  # row number
        if re.fullmatch(r"\d{1,3}", c):
            parts["duration"] = parts["duration"] or f"{c} days"
        elif parts["name"] is None and MED_START_RE.match(c):
            parts["name"] = NUMBER_PREFIX_RE.sub("", c)
        elif parts["dosage"] is None and DOSE_RE.fullmatch(c.strip()):
            parts["dosage"] = c
        elif parts["frequency"] is None and frequency(c):
            parts["frequency"] = c
        elif parts["name"] is None:
            parts["name"] = c
        else:
            parts["instructions"] = ((parts["instructions"] or "") + " " + c).strip()
    return parts


def build_med(text: str, cells: list[str], line: str) -> dict:
    conf = LIKELY
    if len(cells) >= 3:
        p = classify_med_cells(cells)
        name, dose, freq_text, duration, instr = p["name"], p["dosage"], p["frequency"] or "", p["duration"], p["instructions"]
    else:
        body = NUMBER_PREFIX_RE.sub("", text)
        sm = re.search(STRENGTH, body, re.I)
        name = body[:sm.end()] if sm else re.split(r"\s+\d", body)[0]
        rest = body[len(name):]
        dm = DOSE_RE.search(rest)
        dose = dm[1] if dm else None
        freq_text = rest
        dur = DURATION_RE.search(rest)
        duration = f"{dur[1]} {dur[2].lower().rstrip('s')}s" if dur else None
        im = INSTRUCTION_RE.findall(rest)
        instr = ", ".join(im) if im else None
    code = frequency(freq_text or "")
    route = next((r for pattern, r in ROUTE_HINTS if re.search(pattern, (name or "") + " " + text, re.I)), None)
    return {"name": field(name, conf, line), "dosage": field(dose, conf, line), "route": field(route, LIKELY, line),
            "frequency": field(code or (freq_text if len(cells) >= 3 else None), conf, line),
            "duration": field(duration, conf, line), "quantity": EMPTY, "instructions": field(instr, conf, line)}


def extend_med(med: dict, text: str, line: str):
    """A continuation line under a medicine ("5 ml TDS x 5 days", a lone "30")."""
    if re.fullmatch(r"\d{1,3}", text.strip()):
        if not med["duration"]["value"]:
            med["duration"] = field(f"{text.strip()} days", GUESS, line)
        return
    if not med["dosage"]["value"] and (dm := DOSE_RE.search(text)):
        med["dosage"] = field(dm[1], LIKELY, line)
    if not med["frequency"]["value"] and (code := frequency(text)):
        med["frequency"] = field(code, LIKELY, line)
    if not med["duration"]["value"] and (dur := DURATION_RE.search(text)):
        med["duration"] = field(f"{dur[1]} {dur[2].lower().rstrip('s')}s", LIKELY, line)
    extra = INSTRUCTION_RE.findall(text)
    if extra:
        old = med["instructions"]["value"]
        med["instructions"] = field(", ".join([old, *extra] if old else extra), LIKELY, line)
    if med["route"]["value"] is None:
        route = next((r for pattern, r in ROUTE_HINTS if re.search(pattern, text, re.I)), None)
        if route:
            med["route"] = field(route, LIKELY, line)


def med_starts(line: str, cells: list[str]) -> bool:
    """New medicine: "1. Tab X", "3) Saline drops", a table row, "Budesonide 0.5 mg"; not "5 ml TDS x 5 days"."""
    body = " ".join(cells[1:]) if len(cells) >= 3 and re.fullmatch(r"\d{1,2}", cells[0]) else line
    if re.match(r"^\s*\d{1,2}\s*[.)]\s*[A-Za-z]", body):
        return True
    if re.match(r"^\s*\d", body):
        return False  # starts with a dose: continuation of the previous medicine
    return bool(re.match(rf"^\s*(?:{FORMS})\b", body, re.I)
                or re.match(rf"^\s*[A-Z][\w-]*(?:\s+[\w-]+){{0,4}}\s+{STRENGTH}", body))


def med_is_complete(med: dict) -> bool:
    return bool(med["frequency"]["value"] and (med["duration"]["value"] or med["dosage"]["value"]))


def lab_row(text: str, cells: list[str], line: str, panel: str | None):
    m = LAB_ROW_RE.match(text)
    if not m or re.search(r"\b(?:tab|cap|syp|mg\s+\d)", text, re.I) or frequency(text):
        return None
    if not (m["unit"] or m["range"]) and len(cells) < 3:
        return None
    flag = (m["flag"] or "").upper()[:1] or None
    unit = None if (m["unit"] or "-") == "-" else m["unit"]
    return {"test_name": field(m["name"], LIKELY, line), "value": field(m["value"], LIKELY, line),
            "unit": field(unit, LIKELY, line), "reference_range": field(m["range"], LIKELY, line),
            "flag": field(flag, LIKELY, line), "panel_name": field(panel, LIKELY, line) if panel else EMPTY}


def append_text(record: dict, path: tuple, text: str, line: str, confidence=SURE):
    target = record
    for p in path[:-1]:
        target = target[p]
    old = target[path[-1]]["value"]
    target[path[-1]] = field(f"{old} {text}".strip() if old else text, confidence, line if not old else
                             (target[path[-1]]["evidence"] or line))


TEXT_TARGETS = {"complaint": ("encounter", "chief_complaint"), "history": ("encounter", "history_of_present_illness"),
                "findings": ("encounter", "examination_findings"), "course": ("encounter", "hospital_course"),
                "advice": ("encounter", "instructions"), "follow_up": ("encounter", "follow_up"),
                "conclusion": ("report_conclusion",), "investigations": ("encounter", "treatment_plan"),
                "condition": ("notes",)}


def parse(text: str) -> dict:
    """OCR text -> dict shaped like extraction.Extraction[AIField]."""
    record = {
        "document_type": "other", "document_date": EMPTY,
        "patient": {k: EMPTY for k in ("name", "age", "gender", "date_of_birth", "mobile", "abha_number", "hospital_patient_id")},
        "doctor": {k: EMPTY for k in ("name", "registration_number", "qualification", "specialization", "facility_name")},
        "encounter": {k: EMPTY for k in ("visit_date", "admission_date", "discharge_date", "chief_complaint",
                                         "history_of_present_illness", "examination_findings", "hospital_course",
                                         "treatment_plan", "follow_up", "instructions")},
        "diagnoses": [], "allergies": [], "vitals": [], "medications": [], "lab_results": [], "immunizations": [],
        "report_conclusion": EMPTY, "notes": EMPTY,
    }
    raw_lines = [ln for ln in text.replace("\r", "").split("\n")]
    lines = []
    for raw in raw_lines:
        cells = [c.strip() for c in raw.split("\t") if c.strip()]
        joined = " ".join(cells)
        if joined and not NOISE_RE.search(joined):
            lines.append((joined, cells))
        elif joined and re.match(r"^#?\s*medicine\b", joined, re.I):
            lines.append(("Rx", ["Rx"]))  # a medicine table header starts the medicine section

    section, panel, current_med, seen_patient = None, None, None, False
    for i, (line, cells) in enumerate(lines):
        # facility = first line, before any doctor/patient line
        if i == 0 and not re.match(r"^\s*dr\.?\s", line, re.I):
            record["doctor"]["facility_name"] = field(re.split(r"\s+-\s+", line)[0], LIKELY, line)
            continue
        heading = next((k for k, rx in HEADING_RE.items() if rx.match(line)), None)
        if heading:
            section, current_med = heading, None
            continue
        if re.search(r"discharge\s*summary", line, re.I):
            record["document_type"] = "discharge_summary"
            continue  # the title, or a "Discharge summary (continued)" page header
        if re.fullmatch(r"[A-Z][A-Z0-9 /()&,-]{5,}", line) and not LABEL_RE.search(line):
            panel, section = line.strip(), "lab"  # an upper-case lab panel title
            continue
        if re.match(r"^\s*dr\.?\s", line, re.I) or (REG_RE.search(line) and not seen_patient):
            parse_doctor(line, record, SURE if not record["doctor"]["name"]["value"] else LIKELY)
            continue

        segs = segments(line)
        labelled = [s for s in segs if s[0]]
        if labelled and section in ("meds", "lab") and not any(k in ("advice", "follow_up", "investigations", "conclusion",
                                                                     "diagnosis") for k, _ in labelled):
            labelled = []  # e.g. "TSH: 8.9" inside a lab table stays a lab row
        if labelled:
            current_med = None
            for key, val in segs:
                if key is None:
                    if val and section in TEXT_TARGETS:
                        append_text(record, TEXT_TARGETS[section], val, line)
                    continue
                seen_patient = seen_patient or key in ("patient", "age_sex", "patient_id")
                section = key if key in TEXT_TARGETS or key in ("diagnosis",) else None
                if key == "patient":
                    age, gender, name = parse_age_sex(val)
                    record["patient"]["name"] = field(name or val, SURE if not age else LIKELY, line)
                    if age:
                        record["patient"]["age"] = field(age, LIKELY, line)
                    if gender:
                        record["patient"]["gender"] = field(gender, LIKELY, line)
                elif key in ("age_sex", "age", "gender"):
                    age, gender, _ = parse_age_sex(val)
                    if age:
                        record["patient"]["age"] = field(age, SURE, line)
                    if gender:
                        record["patient"]["gender"] = field(gender, SURE, line)
                elif key == "patient_id":
                    record["patient"]["hospital_patient_id"] = field(val.split()[0], SURE, line)
                elif key == "dob":
                    record["patient"]["date_of_birth"] = field(iso_date(val) or val, SURE, line)
                elif key == "mobile":
                    record["patient"]["mobile"] = field(val.split()[0], SURE, line)
                elif key == "abha":
                    record["patient"]["abha_number"] = field(val.split()[0], SURE, line)
                elif key in ("date", "reported", "collected"):
                    d = iso_date(val)
                    if d and (key != "collected" or not record["document_date"]["value"]):
                        record["document_date"] = field(d, LIKELY, line)
                        if key == "date":
                            record["encounter"]["visit_date"] = field(d, LIKELY, line)
                elif key == "admitted":
                    record["encounter"]["admission_date"] = field(iso_date(val) or val, LIKELY, line)
                elif key == "discharged":
                    record["encounter"]["discharge_date"] = field(iso_date(val) or val, LIKELY, line)
                    record["document_date"] = field(iso_date(val) or val, LIKELY, line)
                elif key == "doctor":
                    parse_doctor(val if val.lower().startswith("dr") else "Dr. " + val, record)
                elif key == "reg":
                    record["doctor"]["registration_number"] = field(val.split()[0], SURE, line)
                elif key == "diagnosis":
                    split_diagnoses(val, line, record)
                elif key == "vitals":
                    add_vitals(val, line, record)
                elif key == "allergy":
                    for a in re.split(r"[;,]", val):
                        if a.strip() and not re.fullmatch(r"\s*(nil|none|nkda|no known.*)\s*", a, re.I):
                            record["allergies"].append({"substance": field(a, SURE, line), "reaction": EMPTY})
                elif key in TEXT_TARGETS:
                    append_text(record, TEXT_TARGETS[key], val, line)
            add_vitals(line, line, record) if re.search(r"\b(temp|bp|pulse|spo\s*2|wt|weight)\b", line, re.I) else None
            for name, val, unit in LAB_INLINE_RE.findall(line):
                if not any(re.search(p, f"{name} {val}", re.I) for _, p, _ in VITAL_PATTERNS):
                    record["lab_results"].append({"test_name": field(name, LIKELY, line), "value": field(val, LIKELY, line),
                                                  "unit": field(unit, LIKELY, line), "reference_range": EMPTY,
                                                  "flag": EMPTY, "panel_name": EMPTY})
            continue

        # unlabelled lines: medicines, lab rows, vitals, or text of the current section
        if re.match(r"^\s*(?:r/?x)\b\s*$", line, re.I):
            section, current_med = "meds", None
            continue
        if section == "meds" or (section is None and MED_START_RE.match(line) and re.search(rf"\b(?:{FORMS})\b", line, re.I)):
            section = "meds"
            if med_starts(line, cells):
                current_med = build_med(line, cells, line)
                record["medications"].append(current_med)
                continue
            if current_med and (not med_is_complete(current_med) or re.match(r"^\s*\d", line)):
                extend_med(current_med, line, line)
                continue
            if len(line.split()) <= 2:
                continue  # leftovers of a split table header such as "Days"
            section = "advice"  # free text after the medicines, e.g. "Steam inhalation twice daily"
            if re.match(r"^\s*(review|repeat|follow)", line, re.I):
                append_text(record, ("encounter", "follow_up"), line, line, LIKELY)
            else:
                append_text(record, ("encounter", "instructions"), line, line, LIKELY)
            continue
        row = lab_row(line, cells, line, panel)
        if row:
            record["lab_results"].append(row)
            section = "lab"
            continue
        if re.search(r"\bc/o\b", line, re.I):
            append_text(record, ("encounter", "chief_complaint"), re.sub(r"^.*?c/o\s*", "", line, flags=re.I), line)
            continue
        if re.search(r"\b(temp|bp|pulse|spo\s*2|wt|weight)\b\s*[:.]?\s*\d", line, re.I) and section not in ("course",):
            add_vitals(line, line, record)
            if section != "condition":
                continue
        if section == "diagnosis":
            split_diagnoses(line, line, record)
        elif section == "advice" and re.match(r"^\s*(review|follow|repeat)", line, re.I):
            append_text(record, ("encounter", "follow_up"), line, line, LIKELY)
        elif section in TEXT_TARGETS:
            append_text(record, TEXT_TARGETS[section], line, line, LIKELY)
        elif re.match(r"^\s*(review|repeat|follow)", line, re.I):
            append_text(record, ("encounter", "follow_up"), line, line, LIKELY)

    # document type when no explicit title said so
    if record["document_type"] == "other":
        if len(record["lab_results"]) >= 2 and not record["medications"]:
            record["document_type"] = "lab_report"
        elif record["medications"]:
            record["document_type"] = "prescription"
        elif record["diagnoses"] or record["encounter"]["chief_complaint"]["value"]:
            record["document_type"] = "opd_consultation"
        elif any(v["value"] for v in record["encounter"].values()):
            record["document_type"] = "clinical_note"
    return record
