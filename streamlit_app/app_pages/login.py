import streamlit as st

import api

_, middle, _ = st.columns([1, 2, 1])
with middle:
    st.title("ABDM Hospital", anchor=False)
    st.caption("Staff sign in with their username. Patients sign in with their ABHA address, for example name@abdm.")
    if reason := st.session_state.pop("signed_out_reason", None):
        st.info(reason, icon=":material/schedule:")

    needs_code = st.session_state.get("login_needs_code", False)
    with st.form("login"):
        username = st.text_input("Username or ABHA address", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        otp = st.text_input("6-digit code from your authenticator app", key="login_otp", max_chars=6) if needs_code else None
        submitted = st.form_submit_button("Sign in", type="primary", icon=":material/login:", width="stretch")

    if submitted:
        try:
            result = api.login(username.strip(), password, otp)
        except api.ApiError as exc:
            if exc.code in ("mfa_required", "mfa_invalid"):
                st.session_state.login_needs_code = True
                if exc.code == "mfa_required":
                    st.rerun()
            st.error(str(exc), icon=":material/error:")
        else:
            st.session_state.auth = {"token": result["access_token"], "user": result["user"]}
            st.session_state.login_needs_code = False
            st.rerun()
