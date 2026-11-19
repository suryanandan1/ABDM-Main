import streamlit as st

import api
from ui import PATIENT, abha_badge, can, fmt_datetime, load

data = load(lambda: api.get("/dashboard"))
s = data["stats"]
with st.container(horizontal=True):
    st.metric("Patients", s["total_patients"], border=True)
    st.metric("Registered today", s["patients_today"], border=True)
    st.metric("ABHA verified", s["abha_verified_patients"], border=True)
    st.metric("Active doctors", s["active_doctors"], border=True)
with st.container(horizontal=True):
    st.metric("Active staff", s["active_staff"], border=True)
    st.metric("Consultations today", s["consultations_today"], border=True)
    st.metric("Open lab orders", s["lab_orders_open"], border=True)
    st.metric("Reports awaiting approval", s["lab_reports_awaiting_approval"], border=True)

left, right = st.columns(2)
with left, st.container(border=True):
    st.markdown("**Recent patients**")
    if not data.get("recent_patients"):
        st.caption("No patients yet.")
    for p in data.get("recent_patients", []):
        with st.container(horizontal=True, vertical_alignment="center"):
            if can("patient:read"):
                st.page_link(PATIENT, label=f"{p['full_name']} · {p['patient_code']}", query_params={"id": str(p["id"])},
                             icon=":material/person:")
            else:
                st.markdown(f"{p['full_name']} · {p['patient_code']}")
            abha_badge(p)
with right, st.container(border=True):
    st.markdown("**Recent activity**")
    if not data.get("recent_activity"):
        st.caption("No activity you can see.")
    for a in data.get("recent_activity", []):
        st.markdown(f"{fmt_datetime(a['created_at'])} · **{a['action']}** · {a.get('user_name') or 'Unknown user'}")
