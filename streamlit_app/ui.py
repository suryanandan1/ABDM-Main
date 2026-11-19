"""Display and navigation helpers shared by the pages."""
from datetime import date, datetime
from typing import Any, Callable

import streamlit as st

import api

HI_LABEL = {
    "OPConsultation": "OPD consultation", "Prescription": "Prescription", "DiagnosticReport": "Laboratory report",
    "DischargeSummary": "Discharge summary", "ImmunizationRecord": "Immunization",
    "HealthDocumentRecord": "Health document", "WellnessRecord": "Wellness record",
}
STATUS = {  # label, badge colour
    # clinical records
    "draft": ("Draft", "gray"), "pending_approval": ("Pending approval", "orange"), "approved": ("Approved", "green"),
    "rejected": ("Rejected", "red"), "cancelled": ("Cancelled", "gray"),
    # lab orders
    "ordered": ("Ordered", "blue"), "sample_collected": ("Sample collected", "blue"),
    "in_progress": ("Results in progress", "orange"), "completed": ("Completed", "green"),
    # consent / exchange
    "pending_consent": ("Waiting for patient", "orange"), "requested": ("Requested", "blue"),
    "granted": ("Granted", "blue"), "retrieving": ("Retrieving", "blue"), "received": ("Received", "green"),
    "denied": ("Denied", "red"), "revoked": ("Revoked", "gray"), "expired": ("Expired", "gray"),
    "failed": ("Failed", "red"), "GRANTED": ("Granted", "green"), "REVOKED": ("Revoked", "gray"),
    "EXPIRED": ("Expired", "gray"), "DENIED": ("Denied", "red"),
    # validation / linking
    "valid": ("Valid", "green"), "invalid": ("Invalid", "red"), "not_validated": ("Not validated", "gray"),
    "error": ("Validator error", "orange"), "linked": ("Linked", "green"), "not_linked": ("Not linked", "gray"),
    "verified": ("Verified", "green"),
}
GENDERS = {"M": "Male", "F": "Female", "O": "Other", "U": "Undisclosed"}
DOCUMENT_TYPES = {
    "prescription": "Prescription", "lab_report": "Lab report", "opd_consultation": "OPD consultation",
    "discharge_summary": "Discharge summary", "immunization": "Immunization", "wellness": "Wellness record",
    "clinical_note": "Clinical note", "other": "Other",
}

# Hidden detail pages, opened with an ?id= like the React routes (/patients/5, /consultations/12, ...)
PATIENT, PATIENT_HISTORY, ASSISTANT = "app_pages/patient.py", "app_pages/patient_history.py", "app_pages/assistant.py"
CONSULTATION, PRESCRIPTION, LAB_ORDER = "app_pages/consultation.py", "app_pages/prescription.py", "app_pages/lab_order.py"
DOCUMENT, FHIR_RECORD, NETWORK_HOSPITAL = "app_pages/document.py", "app_pages/fhir_record.py", "app_pages/network_hospital.py"


# ---------- session / permissions ----------
def can(permission: str) -> bool:
    auth = st.session_state.get("auth")
    return bool(auth) and permission in auth["user"]["permissions"]


def user() -> dict:
    return st.session_state.auth["user"]


def go(page: str, **params) -> None:
    st.switch_page(page, query_params={k: str(v) for k, v in params.items()})


def query_id(name: str = "id") -> int:
    value = st.query_params.get(name)
    if not value or not str(value).isdigit():
        st.warning("Nothing selected. Open this page from its list.", icon=":material/info:")
        st.stop()
    return int(value)


# ---------- messages ----------
def flash(message: str, ok: bool = True) -> None:
    st.session_state.setdefault("flash", []).append((ok, message))


def show_flash() -> None:
    for ok, message in st.session_state.pop("flash", []):
        if ok:
            st.success(message, icon=":material/check_circle:")
        else:
            st.error(message, icon=":material/error:")


def show_error(exc: api.ApiError) -> None:
    st.error(str(exc), icon=":material/error:")


def run(fn: Callable[[], Any], done: str = "") -> Any:
    """Call the API; on success queue `done` as a message, on failure queue the error. Returns the result or None."""
    try:
        result = fn()
    except api.ApiError as exc:
        flash(str(exc), ok=False)
        return None
    if done:
        flash(done)
    return result if result is not None else True


def load(fn: Callable[[], Any]) -> Any:
    """Fetch data for a page; show the error and stop the page if it fails."""
    try:
        return fn()
    except api.ApiError as exc:
        show_error(exc)
        st.stop()


@st.dialog("Give a reason")
def reason_dialog(title: str, path: str, done: str) -> None:
    st.markdown(f"**{title}**")
    reason = st.text_area("Reason", key=f"reason_{path}")
    if st.button("Confirm", type="primary", icon=":material/check:", disabled=len(reason.strip()) < 3, key=f"reason_ok_{path}"):
        try:
            api.post(path, {"reason": reason.strip()})
        except api.ApiError as exc:
            show_error(exc)
            return
        flash(done)
        st.rerun()


# ---------- formatting ----------
def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_date(value: str | None) -> str:
    parsed = _parse(value)
    return parsed.strftime("%d %b %Y") if parsed else (value or "")


def fmt_datetime(value: str | None) -> str:
    parsed = _parse(value)
    if not parsed:
        return value or ""
    return (parsed.astimezone() if parsed.tzinfo else parsed).strftime("%d %b %Y, %H:%M")


def to_date(value: str | None) -> date | None:
    parsed = _parse(value)
    return parsed.date() if parsed else None


def age_of(p: dict) -> str:
    born = to_date(p.get("date_of_birth"))
    if born:
        today = date.today()
        return f"{today.year - born.year - ((today.month, today.day) < (born.month, born.day))} y"
    return f"~{date.today().year - p['year_of_birth']} y"


def status_label(status: str, final_label: str | None = None) -> str:
    if status == "approved" and final_label:
        return final_label
    return STATUS.get(status, (status.replace("_", " ").capitalize(), "gray"))[0]


def status_badge(status: str, final_label: str | None = None) -> None:
    label, color = STATUS.get(status, (status.replace("_", " ").capitalize(), "gray"))
    st.badge(final_label if status == "approved" and final_label else label, color=color)


def hi_labels(types: list[str] | None) -> str:
    return ", ".join(HI_LABEL.get(t, t) for t in types or [])


def abha_badge(patient: dict) -> None:
    if not patient.get("abha_number") and not patient.get("abha_address"):
        st.badge("No ABHA", color="gray")
    elif not patient["abha_verified"]:
        st.badge(f"{patient.get('abha_address') or 'ABHA'} · unverified", color="orange", icon=":material/warning:")
    else:
        st.badge(patient.get("abha_address") or "ABHA verified", color="green", icon=":material/verified:")


def format_range(p: dict) -> str:
    if p.get("ref_text"):
        return p["ref_text"]
    low, high = p.get("ref_low"), p.get("ref_high")
    if low is not None and high is not None:
        return f"{low:g} – {high:g}"
    if low is not None:
        return f"≥ {low:g}"
    if high is not None:
        return f"≤ {high:g}"
    return ""


# ---------- shared widgets ----------
def patient_banner(patient: dict, link: bool = True) -> None:
    with st.container(border=True, horizontal=True, vertical_alignment="center"):
        if link and can("patient:read"):
            st.page_link(PATIENT, label=f"**{patient['full_name']}**", query_params={"id": str(patient["id"])},
                         icon=":material/person:")
        else:
            st.markdown(f"**{patient['full_name']}**")
        st.markdown(f"{patient['patient_code']} · {age_of(patient)} · {GENDERS.get(patient['gender'], patient['gender'])}"
                    f" · {patient['mobile']}")
        abha_badge(patient)


def patient_picker(key: str, label: str = "Find patient") -> dict | None:
    """Search this hospital's patients and pick one."""
    query = st.text_input(label, key=f"{key}_q", placeholder="Name, patient ID, mobile or ABHA")
    if len(query.strip()) < 2:
        st.caption("Type at least two characters to search.")
        return None
    try:
        items = api.get("/patients", q=query.strip(), page_size=20)["items"]
    except api.ApiError as exc:
        show_error(exc)
        return None
    if not items:
        st.info("No patient matches that search.")
        return None
    options = {p["id"]: p for p in items}
    chosen = st.selectbox(
        "Patient", list(options), key=f"{key}_pick",
        format_func=lambda pid: f"{options[pid]['full_name']} · {options[pid]['patient_code']} · {options[pid]['mobile']}"
                                f" · {options[pid]['abha_address'] or 'no ABHA'}")
    return options[chosen]


def pager(key: str, total: int, page_size: int) -> int:
    """Page number selector for paginated lists; returns the 1-based page."""
    pages = max(1, -(-total // page_size))
    if pages == 1:
        return 1
    return st.number_input(f"Page (of {pages})", min_value=1, max_value=pages, value=1, step=1, key=key)


def open_selector(label: str, rows: list[dict], key: str, describe: Callable[[dict], str]) -> dict | None:
    """Pick one row of a list to open (the React app opens a row by clicking it)."""
    if not rows:
        return None
    by_id = {r["id"]: r for r in rows}
    with st.container(horizontal=True, vertical_alignment="bottom"):
        chosen = st.selectbox(label, list(by_id), index=None, key=key, placeholder="Choose…",
                              format_func=lambda i: describe(by_id[i]))
        opened = st.button("Open", icon=":material/open_in_new:", key=f"{key}_go", disabled=chosen is None)
    return by_id[chosen] if opened and chosen is not None else None


@st.cache_data(ttl=3600)
def _terminology(token: str) -> dict:
    return api.get("/terminology")


def terminology() -> dict:
    return _terminology(st.session_state.auth["token"])


def fhir_button(source_type: str, source_id: int, key: str) -> None:
    """Open (generating if needed) the FHIR document of an approved record, for users allowed to generate one."""
    if can("fhir:generate") and st.button("View FHIR", icon=":material/data_object:", key=key):
        record = run(lambda: api.post("/fhir/records", {"source_type": source_type, "source_id": source_id}))
        if isinstance(record, dict):
            go(FHIR_RECORD, id=record["id"])
        st.rerun()
