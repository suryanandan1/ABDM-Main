import streamlit as st

import api
from ui import can, load, pager, run

can_manage = can("doctor:manage")


@st.dialog("Doctor", width="large")
def doctor_dialog(doctor: dict | None) -> None:
    accounts = load(lambda: api.get("/staff", role="doctor", is_active=True, page_size=100))["items"] if can("staff:read") else []
    d = doctor or {}
    with st.form("doctor_form", border=False):
        c1, c2 = st.columns(2)
        full_name = c1.text_input("Full name *", d.get("full_name", ""))
        registration = c2.text_input("Registration number *", d.get("registration_number", ""))
        c1, c2 = st.columns(2)
        hpr = c1.text_input("HPR ID", d.get("hpr_id") or "")
        specialization = c2.text_input("Specialization", d.get("specialization") or "")
        c1, c2 = st.columns(2)
        qualification = c1.text_input("Qualification", d.get("qualification") or "")
        department = c2.text_input("Department", d.get("department") or "")
        c1, c2 = st.columns(2)
        phone = c1.text_input("Phone", d.get("phone") or "")
        email = c2.text_input("Email", d.get("email") or "")
        ids = [None, *[a["id"] for a in accounts]]
        if d.get("user_id") and d["user_id"] not in ids:
            ids.append(d["user_id"])
        user_id = st.selectbox("Linked login account", ids, index=ids.index(d.get("user_id")) if d.get("user_id") in ids else 0,
                               format_func=lambda i: "None" if i is None else next(
                                   (f"{a['full_name']} ({a['username']})" for a in accounts if a["id"] == i), d.get("username") or f"#{i}"),
                               help="Optional: a staff account with the Doctor role")
        active = st.toggle("Active", d.get("is_active", True)) if doctor else True
        saved = st.form_submit_button("Save", type="primary")
    if saved:
        body = {"full_name": full_name.strip(), "registration_number": registration.strip(), "hpr_id": hpr.strip() or None,
                "specialization": specialization.strip() or None, "qualification": qualification.strip() or None,
                "department": department.strip() or None, "phone": phone.strip() or None, "email": email.strip() or None,
                "user_id": user_id}
        if doctor:
            body["is_active"] = active
        if run(lambda: api.patch(f"/doctors/{doctor['id']}", body) if doctor else api.post("/doctors", body), "Doctor saved."):
            st.rerun()
        for good, msg in st.session_state.pop("flash", []):
            (st.success if good else st.error)(msg)


with st.container(horizontal=True, vertical_alignment="bottom"):
    q = st.text_input("Search", key="doctors_q", placeholder="Name, registration number or specialization")
    active = st.segmented_control("Status", ["Active", "Inactive", "All"], default="Active", key="doctors_active")
    if can_manage and st.button("Add doctor", type="primary", icon=":material/add:"):
        doctor_dialog(None)

result = load(lambda: api.get("/doctors", q=q.strip() or None, is_active={"Active": True, "Inactive": False}.get(active or "Active"),
                              page=st.session_state.get("doctors_page", 1), page_size=50))
items = result["items"]
st.dataframe([{"Name": d["full_name"], "Registration": d["registration_number"], "HPR ID": d.get("hpr_id") or "",
               "Specialization": d.get("specialization") or "", "Department": d.get("department") or "",
               "Login account": d.get("username") or "—", "Active": d["is_active"]} for d in items], hide_index=True, alt="Doctors")
pager("doctors_page", result["total"], 50)
if can_manage and items:
    by_id = {d["id"]: d for d in items}
    with st.container(horizontal=True, vertical_alignment="bottom"):
        chosen = st.selectbox("Edit doctor", list(by_id), index=None, placeholder="Choose…",
                              format_func=lambda i: f"{by_id[i]['full_name']} ({by_id[i]['registration_number']})")
        if st.button("Edit", icon=":material/edit:", disabled=chosen is None):
            doctor_dialog(by_id[chosen])
