import streamlit as st

import api
from patient_form import patient_form
from ui import (ASSISTANT, CONSULTATION, GENDERS, PATIENT_HISTORY, abha_badge, age_of, can, fmt_date, fmt_datetime,
                go, load, query_id, run, user)

VERIFY_METHODS = {"physical_abha_card": "Physical ABHA card checked", "abha_app_profile": "ABHA app profile shown by patient"}

patient_id = query_id()
patient = load(lambda: api.get(f"/patients/{patient_id}"))


@st.dialog("Edit patient", width="large")
def edit_dialog() -> None:
    payload = patient_form(f"edit_patient_{patient_id}", patient, "Save changes")
    if payload:
        if run(lambda: api.patch(f"/patients/{patient_id}", payload), "Patient details updated."):
            st.rerun()
        show_flash_inline()


@st.dialog("Record ABHA verification")
def verify_dialog() -> None:
    st.info("Only record verification after confirming the ABHA number/address belongs to this patient.",
            icon=":material/info:")
    method = st.selectbox("How was it verified?", list(VERIFY_METHODS), format_func=VERIFY_METHODS.get)
    note = st.text_area("Note (what was checked)", help="At least 5 characters")
    if st.button("Mark as verified", type="primary", disabled=len(note.strip()) < 5):
        if run(lambda: api.post(f"/patients/{patient_id}/abha/verify", {"method": method, "note": note.strip()}),
               "ABHA verification recorded."):
            st.rerun()
        show_flash_inline()


def show_flash_inline() -> None:
    for ok, message in st.session_state.pop("flash", []):
        (st.success if ok else st.error)(message)


with st.container(horizontal=True, vertical_alignment="center"):
    st.subheader(patient["full_name"], anchor=False)
    abha_badge(patient)
with st.container(horizontal=True):
    if can("clinical:read"):
        st.page_link(PATIENT_HISTORY, label="Medical history", query_params={"id": str(patient_id)}, icon=":material/history:")
        st.page_link(ASSISTANT, label="Patient assistant", query_params={"id": str(patient_id)}, icon=":material/auto_awesome:")
    if can("consultation:write") and user().get("doctor_id"):
        if st.button("Start consultation", icon=":material/assignment_add:"):
            encounter = run(lambda: api.post("/consultations", {"patient_id": patient_id}))
            if isinstance(encounter, dict):
                go(CONSULTATION, id=encounter["id"])
            st.rerun()
    if can("patient:update") and st.button("Edit details", icon=":material/edit:", type="primary"):
        edit_dialog()

left, right = st.columns([2, 1])
with left, st.container(border=True):
    st.markdown("**Patient details**")
    st.table({
        "Patient ID": patient["patient_code"], "Gender": GENDERS.get(patient["gender"], patient["gender"]),
        "Age": age_of(patient),
        "Date of birth": fmt_date(patient["date_of_birth"]) if patient["date_of_birth"]
        else f"Unknown (year ~{patient['year_of_birth']})",
        "Mobile": patient["mobile"],
        "Registered": fmt_datetime(patient["created_at"]) + (f" by {patient['registered_by_name']}"
                                                             if patient.get("registered_by_name") else ""),
        "Address": ", ".join(x for x in (patient["address_line"], patient["city"], patient["state"], patient["pincode"]) if x) or "—",
        "Emergency contact": (f"{patient['emergency_contact_name']}" + (f" ({patient['emergency_contact_relation']})"
                              if patient["emergency_contact_relation"] else "")) if patient["emergency_contact_name"] else "—",
        "Emergency phone": patient["emergency_contact_phone"] or "—",
    }, alt="Patient details")

with right, st.container(border=True):
    st.markdown("**ABHA**")
    st.markdown(f"ABHA number: {patient['abha_number'] or '—'}  \nABHA address: {patient['abha_address'] or '—'}")
    has_abha = bool(patient["abha_number"] or patient["abha_address"])
    if patient["abha_verified"]:
        st.success(f"Verified {fmt_datetime(patient['abha_verified_at'])}"
                   + (f" by {patient['abha_verified_by_name']}" if patient.get("abha_verified_by_name") else "")
                   + f"  \nMethod: {VERIFY_METHODS.get(patient['abha_verification_method'], patient['abha_verification_method'])}")
    elif has_abha:
        st.warning("Not verified. Do not rely on these identifiers until verified.")
    if can("abha:verify") and has_abha:
        if patient["abha_verified"]:
            if st.button("Revoke verification", icon=":material/remove_moderator:"):
                run(lambda: api.delete(f"/patients/{patient_id}/abha/verify"), "ABHA verification revoked.")
                st.rerun()
        elif st.button("Record verification", icon=":material/verified:"):
            verify_dialog()

if can("clinical:read"):
    with st.container(border=True):
        st.markdown("**Assistant briefing**")
        try:
            overview = api.get(f"/assistant/patients/{patient_id}/overview")
        except api.ApiError as exc:
            st.warning(str(exc))
        else:
            b = overview["briefing"]
            st.caption(f"Documented history you can access ({', '.join(b['scope'])}). Not a diagnosis.")
            cols = st.columns(2)
            sections = [
                ("Active conditions", b["active_conditions"],
                 lambda l: l["text"] + (f" ({l['certainty']})" if l.get("certainty") != "confirmed" else "")),
                ("Recent consultations", b["recent_consultations"],
                 lambda l: f"{fmt_date(l['date'])}: {l['text']}" + (f" — {', '.join(l['diagnoses'])}" if l.get("diagnoses") else "")),
                ("Previous prescriptions", b["previous_prescriptions"], lambda l: f"{fmt_date(l['date'])}: {l['text']}"),
                ("Recent laboratory results", b["recent_lab_results"], lambda l: f"{fmt_date(l['date'])}: {l['text']}"),
                ("External records", b["external_records"], lambda l: f"{fmt_date(l['date'])}: {l['text']}"),
            ]
            for i, (title, lines, render) in enumerate(sections):
                with cols[i % 2]:
                    st.markdown(f"**{title}**")
                    if not lines:
                        st.caption("None recorded.")
                    for line in lines:
                        st.markdown(f"- {render(line)} `{line['source_id']}`")
            if b["missing_information"]:
                st.info("Missing: " + "; ".join(b["missing_information"]))

if can("audit:read"):
    with st.container(border=True):
        st.markdown("**Record history**")
        history = load(lambda: api.get("/audit-logs", entity_type="patient", entity_id=patient_id, page_size=20))["items"]
        st.dataframe([{"When": fmt_datetime(h["created_at"]), "Action": h["action"], "By": h.get("user_name") or "Unknown user"}
                      for h in history], hide_index=True, alt="Changes to this patient record")
