"""Staff account management shared by Staff (hospital admin) and Hospitals (network admin) pages."""
import streamlit as st

import api
from ui import fmt_datetime, load, pager, run, user


def staff_section(list_url: str, create_url: str, item_url: str, roles: list[dict], can_manage: bool, key: str) -> None:
    role_names = {r["code"]: r["name"] for r in roles}

    @st.dialog("Staff account", width="large")
    def staff_dialog(staff: dict | None) -> None:
        is_self = bool(staff) and staff["id"] == user()["id"]
        with st.form(f"{key}_staff_form", border=False):
            username = st.text_input("Username *", (staff or {}).get("username", ""), disabled=bool(staff),
                                     help="3-50 letters, digits, dot, dash or underscore")
            full_name = st.text_input("Full name *", (staff or {}).get("full_name", ""))
            c1, c2 = st.columns(2)
            email = c1.text_input("Email", (staff or {}).get("email") or "")
            phone = c2.text_input("Phone", (staff or {}).get("phone") or "")
            codes = list(role_names)
            role = st.selectbox("Role *", codes, index=codes.index(staff["role_code"]) if staff and staff["role_code"] in codes else None,
                                format_func=role_names.get, disabled=is_self, placeholder="Choose…",
                                help="You cannot change your own role" if is_self else None)
            password = st.text_input("New password (leave blank to keep)" if staff else "Password *", type="password",
                                     help="At least 8 characters with letters and digits")
            active = st.toggle("Active", (staff or {}).get("is_active", True), disabled=is_self) if staff else True
            saved = st.form_submit_button("Save", type="primary")
        if staff and staff.get("mfa_enabled") and not is_self and st.button("Reset two-step sign-in", icon=":material/lock_reset:"):
            if run(lambda: api.delete(f"{item_url}/{staff['id']}/mfa"), "Two-step sign-in reset."):
                st.rerun()
        if saved:
            body = {"full_name": full_name.strip(), "email": email.strip() or None, "phone": phone.strip() or None}
            if not is_self:
                body["role"] = role
            if staff:
                if not is_self:
                    body["is_active"] = active
                if password:
                    body["password"] = password
                ok = run(lambda: api.patch(f"{item_url}/{staff['id']}", body), "Staff account updated.")
            else:
                ok = run(lambda: api.post(create_url, {**body, "username": username.strip(), "password": password, "role": role}),
                         "Staff account created.")
            if ok:
                st.rerun()
        for good, msg in st.session_state.pop("flash", []):
            (st.success if good else st.error)(msg)

    with st.container(horizontal=True, vertical_alignment="bottom"):
        q = st.text_input("Search", key=f"{key}_q", placeholder="Name, username or email")
        role_filter = st.selectbox("Role", ["", *role_names], format_func=lambda c: role_names.get(c, "All roles"), key=f"{key}_role")
        if can_manage and st.button("Add staff", type="primary", icon=":material/person_add:"):
            staff_dialog(None)
    result = load(lambda: api.get(list_url, q=q.strip() or None, role=role_filter or None,
                                  page=st.session_state.get(f"{key}_page", 1), page_size=50))
    items = result["items"]
    st.dataframe([{"Name": u["full_name"], "Username": u["username"], "Role": u["role_name"], "Email": u.get("email") or "",
                   "Phone": u.get("phone") or "", "Active": u["is_active"], "2-step": u.get("mfa_enabled", False),
                   "Last sign-in": fmt_datetime(u.get("last_login_at"))} for u in items], hide_index=True, alt="Staff accounts")
    pager(f"{key}_page", result["total"], 50)
    if can_manage and items:
        by_id = {u["id"]: u for u in items}
        with st.container(horizontal=True, vertical_alignment="bottom"):
            chosen = st.selectbox("Edit account", list(by_id), index=None, placeholder="Choose…", key=f"{key}_edit",
                                  format_func=lambda i: f"{by_id[i]['full_name']} ({by_id[i]['username']})")
            if st.button("Edit", icon=":material/edit:", disabled=chosen is None, key=f"{key}_edit_go"):
                staff_dialog(by_id[chosen])
