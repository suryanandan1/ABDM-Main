import streamlit as st

import api
from ui import CONSULTATION, can, fmt_datetime, go, load, open_selector, pager, patient_picker, run, status_label, user

is_doctor = user()["role_code"] == "doctor"


@st.dialog("New consultation")
def new_consultation() -> None:
    patient = patient_picker("newcons")
    if st.button("Start consultation", type="primary", disabled=patient is None):
        encounter = run(lambda: api.post("/consultations", {"patient_id": patient["id"]}))
        if isinstance(encounter, dict):
            go(CONSULTATION, id=encounter["id"])
        st.rerun()


with st.container(horizontal=True, vertical_alignment="bottom"):
    status = st.segmented_control("Status", ["All", "Draft", "Finalized", "Cancelled"], default="All", key="cons_status")
    mine = st.toggle("My patients", value=is_doctor, key="cons_mine") if is_doctor else False
    if can("consultation:write") and user().get("doctor_id") and st.button("New consultation", type="primary",
                                                                           icon=":material/add:"):
        new_consultation()

PAGE_SIZE = 20
result = load(lambda: api.get("/consultations", status={"Draft": "draft", "Finalized": "approved", "Cancelled": "cancelled"}
                              .get(status or "All"), mine=mine or None, page=st.session_state.get("cons_page", 1),
                              page_size=PAGE_SIZE))
items = result["items"]
st.caption(f"{result['total']} consultation(s)")
st.dataframe([{"#": e["id"], "Visit": fmt_datetime(e["visit_at"]), "Patient": f"{e['patient']['full_name']} ({e['patient']['patient_code']})",
               "Doctor": e["doctor"]["full_name"], "Chief complaint": e["chief_complaint"] or "",
               "Diagnosis": ", ".join(c["display"] for c in e["conditions"]),
               "Status": status_label(e["status"], "Finalized")} for e in items], hide_index=True, alt="Consultations")
pager("cons_page", result["total"], PAGE_SIZE)
chosen = open_selector("Open consultation", items, "cons_open",
                       lambda e: f"#{e['id']} · {e['patient']['full_name']} · {fmt_datetime(e['visit_at'])}")
if chosen:
    go(CONSULTATION, id=chosen["id"])
