import streamlit as st

import api
from ui import can, fmt_datetime, load, run

FIELDS = [("name", "Hospital name *"), ("facility_type", "Facility type"), ("hfr_id", "HFR ID"),
          ("abdm_hip_id", "ABDM HIP ID"), ("abdm_hiu_id", "ABDM HIU ID"), ("address", "Address"), ("city", "City"),
          ("state", "State"), ("pincode", "Pincode"), ("phone", "Phone"), ("email", "Email")]

h = load(lambda: api.get("/hospital"))
editable = can("hospital:update")
st.caption(f"Code {h['code']} (patient ID prefix) · created {fmt_datetime(h['created_at'])}")
with st.form("hospital_profile"):
    cols = st.columns(2)
    values = {key: cols[i % 2].text_input(label, h.get(key) or "", disabled=not editable) for i, (key, label) in enumerate(FIELDS)}
    saved = st.form_submit_button("Save", type="primary", disabled=not editable)
if saved:
    run(lambda: api.put("/hospital", {k: (v.strip() or None) for k, v in values.items()}), "Hospital profile saved.")
    st.rerun()
