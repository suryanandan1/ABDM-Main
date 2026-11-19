from datetime import date, timedelta

import streamlit as st

import api
from ui import HI_LABEL, patient_banner, patient_picker, show_error, user

if done := st.session_state.pop("hiu_new_done", None):
    st.success(f"Consent request sent to {done}. Follow it on **Consent requests sent**.", icon=":material/send:")

try:
    dash = api.get("/hiu/dashboard")
    doctors = api.get("/doctors", is_active=True, page_size=100)["items"]
except api.ApiError as exc:
    show_error(exc)
    st.stop()

patient = patient_picker("hiu_new")
if patient is None:
    st.stop()
patient_banner(patient)
if not patient.get("abha_address") or not patient["abha_verified"]:
    st.warning("This patient's ABHA address is not verified. Verify it on the ABDM HIP page before requesting records.",
               icon=":material/warning:")
    st.stop()

doctor_ids = [d["id"] for d in doctors]
own = user().get("doctor_id")
with st.form("hiu_new_form"):
    doctor = st.selectbox("Requesting doctor", doctor_ids, index=doctor_ids.index(own) if own in doctor_ids else 0,
                          format_func=lambda i: next(f"{d['full_name']} ({d['registration_number']})" for d in doctors if d["id"] == i))
    reason = st.text_area("Clinical reason (why the records are needed)", max_chars=500)
    purpose = st.selectbox("Purpose", list(dash["purposes"]), format_func=lambda k: dash["purposes"][k])
    hi_types = st.pills("Record categories", dash["hi_types"], selection_mode="multi",
                        default=["OPConsultation", "Prescription", "DiagnosticReport"],
                        format_func=lambda t: HI_LABEL.get(t, t))
    with st.container(horizontal=True):
        date_from = st.date_input("Records from", date.today() - timedelta(days=365 * 3))
        date_to = st.date_input("Records to", date.today())
        erase_at = st.date_input("Delete received data on", date.today() + timedelta(days=30))
    submitted = st.form_submit_button("Send consent request to the patient", type="primary", icon=":material/send:")

if submitted:
    if not hi_types:
        st.error("Choose at least one record category.")
    elif date_from > date_to:
        st.error("'Records from' must be on or before 'Records to'.")
    else:
        try:
            api.post("/hiu/requests", {
                "patient_id": patient["id"], "requester_doctor_id": doctor, "purpose_code": purpose, "hi_types": hi_types,
                "date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "erase_at": erase_at.isoformat(),
                "reason": reason.strip() or None})
        except api.ApiError as exc:
            show_error(exc)
        else:
            st.session_state.hiu_new_done = patient["abha_address"]
            st.rerun()
