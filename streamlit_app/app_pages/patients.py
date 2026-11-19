import streamlit as st

import api
from ui import GENDERS, PATIENT, age_of, can, fmt_date, go, load, open_selector, pager

with st.container(horizontal=True, vertical_alignment="bottom"):
    query = st.text_input("Search", key="patients_q", placeholder="Name, patient ID, mobile or ABHA address")
    verified = st.segmented_control("ABHA", ["All", "Verified", "Not verified"], default="All", key="patients_abha")
    if can("patient:create") and st.button("Register patient", icon=":material/person_add:", type="primary"):
        go("app_pages/patient_register.py")

PAGE_SIZE = 20
page = st.session_state.get("patients_page", 1)
abha = {"Verified": True, "Not verified": False}.get(verified or "All")
result = load(lambda: api.get("/patients", q=query.strip() or None, abha_verified=abha, page=page, page_size=PAGE_SIZE))
items = result["items"]
st.caption(f"{result['total']} patient(s)")
st.dataframe(
    [{"Patient ID": p["patient_code"], "Name": p["full_name"], "Age / gender": f"{age_of(p)} / {GENDERS.get(p['gender'])}",
      "Mobile": p["mobile"], "ABHA address": p["abha_address"] or "", "ABHA verified": p["abha_verified"],
      "Registered": fmt_date(p["created_at"])} for p in items],
    hide_index=True, alt="Patients matching the search")
pager("patients_page", result["total"], PAGE_SIZE)

chosen = open_selector("Open patient", items, "patients_open",
                       lambda p: f"{p['full_name']} · {p['patient_code']} · {p['mobile']}")
if chosen:
    go(PATIENT, id=chosen["id"])
