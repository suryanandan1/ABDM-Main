import streamlit as st

import api
from ui import fmt_datetime, run, show_error, user

u = user()
st.caption(f"{u['full_name']} · {u['username']} · {u['role_name']}" + (f" · {u['hospital_name']}" if u.get("hospital_name") else "")
           + (f" · last sign-in {fmt_datetime(u['last_login_at'])}" if u.get("last_login_at") else ""))

left, right = st.columns(2)
with left, st.container(border=True):
    st.markdown("**Change password**")
    with st.form("change_password", border=False, clear_on_submit=True):
        current = st.text_input("Current password", type="password")
        new = st.text_input("New password", type="password", help="At least 8 characters with letters and digits")
        repeat = st.text_input("Repeat new password", type="password")
        changed = st.form_submit_button("Change password", type="primary")
    if changed:
        if new != repeat:
            st.error("The two new passwords differ.")
        else:
            try:
                result = api.post("/auth/change-password", {"current_password": current, "new_password": new})
            except api.ApiError as exc:
                show_error(exc)
            else:
                # The backend ends every other session and issues a new token for this one.
                st.session_state.auth = {"token": result["access_token"], "user": result["user"]}
                st.success("Password changed. Other devices were signed out.")

with right, st.container(border=True):
    st.markdown("**Two-step sign-in**")
    if u.get("mfa_enabled"):
        st.success("On. Sign-in asks for a code from your authenticator app.", icon=":material/lock:")
        with st.form("mfa_disable", border=False):
            password = st.text_input("Password", type="password")
            code = st.text_input("Code from your app", max_chars=8)
            if st.form_submit_button("Turn off"):
                if run(lambda: api.post("/auth/mfa/disable", {"password": password, "code": code.strip()}),
                       "Two-step sign-in turned off."):
                    api.refresh_user()
                st.rerun()
    else:
        setup = st.session_state.get("mfa_setup")
        if not setup:
            st.caption("Protect your account with a 6-digit code from an authenticator app (Google/Microsoft Authenticator, FreeOTP).")
            if st.button("Set up", type="primary", icon=":material/qr_code_2:"):
                st.session_state.mfa_setup = run(lambda: api.post("/auth/mfa/setup"))
                st.rerun()
        else:
            st.markdown("Add this key to your authenticator app, then enter the code it shows.")
            st.code(setup["secret"], language=None)
            st.caption(f"Or open this link on your phone: {setup['otpauth_uri']}")
            with st.form("mfa_enable", border=False):
                code = st.text_input("Code", max_chars=8)
                if st.form_submit_button("Turn on", type="primary"):
                    if run(lambda: api.post("/auth/mfa/enable", {"code": code.strip()})):
                        st.session_state.pop("mfa_setup", None)
                        api.refresh_user()
                        st.session_state.setdefault("flash", []).append((True, "Two-step sign-in is on."))
                    st.rerun()

with st.container(border=True):
    st.markdown("**Sessions**")
    st.caption("Sign out of this app on every device and browser, including this one.")
    if st.button("Sign out everywhere", icon=":material/devices:"):
        api.logout(everywhere=True)
        st.rerun()
