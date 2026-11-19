import streamlit as st

import api
from ui import NETWORK_HOSPITAL, go, load, run

FIELDS = [("name", "Hospital name *"), ("facility_type", "Facility type"), ("hfr_id", "HFR ID"),
          ("address", "Address"), ("city", "City"), ("state", "State"), ("pincode", "Pincode"), ("phone", "Phone"),
          ("email", "Email")]


@st.dialog("Add hospital", width="large")
def add_hospital() -> None:
    with st.form("add_hospital", border=False):
        c1, c2 = st.columns([1, 2])
        code = c1.text_input("Code (patient ID prefix) *", help="2-10 letters/digits, e.g. LKH; cannot be changed later")
        cols = st.columns(2)
        values = {"name": c2.text_input("Hospital name *")}
        values.update({k: cols[i % 2].text_input(label) for i, (k, label) in enumerate(FIELDS[1:])})
        c1, c2 = st.columns(2)
        hip_id = c1.text_input("ABDM HIP ID", help="Blank in simulation: SIM_HIP_<code>")
        hiu_id = c2.text_input("ABDM HIU ID", help="Blank in simulation: SIM_HIU_<code>")
        st.markdown("**First administrator (optional)**")
        c1, c2, c3 = st.columns(3)
        admin_user = c1.text_input("Username")
        admin_name = c2.text_input("Full name")
        admin_password = c3.text_input("Password", type="password", help="At least 8 characters with letters and digits")
        saved = st.form_submit_button("Add hospital", type="primary")
    if saved:
        body = {**{k: (v.strip() or None) for k, v in values.items()}, "code": code.strip(),
                "abdm_hip_id": hip_id.strip() or None, "abdm_hiu_id": hiu_id.strip() or None,
                "admin": {"username": admin_user.strip(), "full_name": admin_name.strip(), "password": admin_password}
                if admin_user.strip() else None}
        created = run(lambda: api.post("/network/hospitals", body), "Hospital added.")
        if isinstance(created, dict):
            go(NETWORK_HOSPITAL, id=created["id"])
        for good, msg in st.session_state.pop("flash", []):
            (st.success if good else st.error)(msg)


hospitals = load(lambda: api.get("/network/hospitals"))
if st.button("Add hospital", type="primary", icon=":material/add:"):
    add_hospital()
st.dataframe([{"Hospital": h["name"], "Code": h["code"], "Active": h["is_active"], "City": h.get("city") or "",
               "HIP ID": h.get("abdm_hip_id") or "", "HIU ID": h.get("abdm_hiu_id") or "",
               "Administrators": ", ".join(a["username"] for a in h["admins"]), "Staff": h["stats"]["staff"],
               "Doctors": h["stats"]["doctors"], "Patients": h["stats"]["patients"],
               "Shared records": h["stats"]["shared_records"]} for h in hospitals], hide_index=True, alt="Hospitals")
by_id = {h["id"]: h for h in hospitals}
with st.container(horizontal=True, vertical_alignment="bottom"):
    chosen = st.selectbox("Open hospital", list(by_id), index=None, placeholder="Choose…",
                          format_func=lambda i: f"{by_id[i]['name']} ({by_id[i]['code']})")
    if st.button("Open", icon=":material/open_in_new:", disabled=chosen is None):
        go(NETWORK_HOSPITAL, id=chosen)
