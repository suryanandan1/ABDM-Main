import streamlit as st

import api
from patient_form import patient_form
from ui import GENDERS, PATIENT, age_of, flash, go, show_error

LEVEL = {"exact": "red", "likely": "orange", "possible": "blue"}


def register(payload: dict, confirm: bool = False) -> None:
    try:
        created = api.post("/patients", {**payload, "confirm_not_duplicate": confirm})
    except api.ApiError as exc:
        if isinstance(exc.detail, dict) and exc.detail.get("duplicates") is not None:
            st.session_state.register_pending = payload
            st.session_state.register_duplicates = exc.detail["duplicates"]
            st.rerun()
        show_error(exc)
        return
    st.session_state.pop("register_pending", None)
    st.session_state.pop("register_duplicates", None)
    flash("Patient registered successfully.")
    go(PATIENT, id=created["id"])


duplicates = st.session_state.get("register_duplicates")
if duplicates:
    exact = any(d["level"] == "exact" for d in duplicates)
    if exact:
        st.error("A patient with the same ABHA identifier already exists. Open the existing record instead of "
                 "registering again.", title="Patient already registered", icon=":material/error:")
    else:
        st.warning("These existing patients look similar. Check with the patient before creating a new record.",
                   title="Possible duplicate patients", icon=":material/warning:")
    for d in duplicates:
        p = d["patient"]
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            st.badge(d["level"], color=LEVEL.get(d["level"], "gray"))
            st.markdown(f"**{p['full_name']}** · {p['patient_code']} · {age_of(p)} / {GENDERS.get(p['gender'])} · "
                        f"{p['mobile']}  \n{', '.join(d['reasons'])}")
            st.page_link(PATIENT, label="Open", query_params={"id": str(p["id"])}, icon=":material/open_in_new:")
    with st.container(horizontal=True):
        if st.button("Back to form", icon=":material/arrow_back:"):
            st.session_state.pop("register_duplicates", None)
            st.rerun()
        if not exact and st.button("This is a different person — register", type="primary", icon=":material/person_add:"):
            st.session_state.pop("register_duplicates", None)
            register(st.session_state.register_pending, confirm=True)
    st.stop()

payload = patient_form("register_form", st.session_state.get("register_pending"), "Register patient")
if payload:
    register(payload)
