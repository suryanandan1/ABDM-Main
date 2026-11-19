import streamlit as st

import api
from staff_admin import staff_section
from ui import load, query_id, run

FIELDS = [("name", "Hospital name *"), ("facility_type", "Facility type"), ("hfr_id", "HFR ID"), ("abdm_hip_id", "ABDM HIP ID"),
          ("abdm_hiu_id", "ABDM HIU ID"), ("address", "Address"), ("city", "City"), ("state", "State"),
          ("pincode", "Pincode"), ("phone", "Phone"), ("email", "Email")]

hospital_id = query_id()
h = load(lambda: api.get(f"/network/hospitals/{hospital_id}"))

with st.container(horizontal=True, vertical_alignment="center"):
    st.subheader(f"{h['name']} ({h['code']})", anchor=False)
    st.badge("Active" if h["is_active"] else "Deactivated", color="green" if h["is_active"] else "gray")
    if st.button("Deactivate hospital" if h["is_active"] else "Activate hospital", icon=":material/power_settings_new:"):
        run(lambda: api.patch(f"/network/hospitals/{hospital_id}", {"is_active": not h["is_active"]}),
            "Hospital deactivated." if h["is_active"] else "Hospital activated.")
        st.rerun()
if not h["is_active"]:
    st.info("Deactivated: its staff cannot sign in and the network stops routing consent and record requests to it. "
            "Its data is kept.")
s = h["stats"]
with st.container(horizontal=True):
    st.metric("Staff", s["staff"], border=True)
    st.metric("Active staff", s["active_staff"], border=True)
    st.metric("Doctors", s["doctors"], border=True)
    st.metric("Patients", s["patients"], border=True)
    st.metric("Shared records", s["shared_records"], border=True)

with st.expander("Profile and ABDM IDs", icon=":material/edit:"):
    with st.form(f"network_hospital_{hospital_id}", border=False):
        cols = st.columns(2)
        values = {k: cols[i % 2].text_input(label, h.get(k) or "") for i, (k, label) in enumerate(FIELDS)}
        if st.form_submit_button("Save", type="primary"):
            run(lambda: api.patch(f"/network/hospitals/{hospital_id}", {k: (v.strip() or None) for k, v in values.items()}),
                "Hospital saved.")
            st.rerun()

st.subheader("Staff accounts", anchor=False)
roles = load(lambda: api.get("/network/roles"))
staff_section(f"/network/hospitals/{hospital_id}/staff", f"/network/hospitals/{hospital_id}/staff", "/network/staff",
              roles, True, f"net_staff_{hospital_id}")
