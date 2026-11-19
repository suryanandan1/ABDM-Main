import streamlit as st

import api
from ui import HI_LABEL, fmt_date, show_error, status_badge

if note := st.session_state.pop("consent_note", None):
    st.success(note, icon=":material/check_circle:")

try:
    consents = api.get("/portal/consents")
except api.ApiError as exc:
    show_error(exc)
    st.stop()

if not consents:
    st.info("No hospital has asked to see your records.", icon=":material/info:")
    st.stop()


def act(consent_id: int, action: str, body: dict | None, done: str) -> None:
    try:
        api.post(f"/portal/consents/{consent_id}/{action}", body)
    except api.ApiError as exc:
        st.session_state.consent_error = str(exc)
    else:
        st.session_state.consent_note = done


@st.dialog("Revoke consent?")
def confirm_revoke(consent: dict) -> None:
    st.write(f"{consent['hospital_name']}'s copy of your records will be erased. This cannot be undone.")
    if st.button("Revoke consent", type="primary", icon=":material/block:", key="revoke_confirm"):
        act(consent["id"], "revoke", None, "Consent revoked. The hospital's copy of your records was erased.")
        st.rerun()


if error := st.session_state.pop("consent_error", None):
    st.error(error, icon=":material/error:")

pending = [c for c in consents if c["status"] == "pending_consent"]
st.caption(f"{len(pending)} waiting for your decision · {len(consents)} in total")

for c in consents:
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{c['hospital_name']}**")
            status_badge(c["status"])
        st.markdown(
            f"**Requested by:** {c['requester']} · {fmt_date(c['created_at'])}  \n"
            f"**Purpose:** {c['purpose']}{' — ' + c['reason'] if c.get('reason') else ''}  \n"
            f"**Records:** {', '.join(HI_LABEL.get(t, t) for t in c['hi_types'])}  \n"
            f"**From** {fmt_date(c['date_from'])} **to** {fmt_date(c['date_to'])} · "
            f"**they may keep it until** {fmt_date(c['data_erase_at'])}")
        if c.get("status_message"):
            st.caption(c["status_message"])

        if c["status"] == "pending_consent":
            with st.container(horizontal=True):
                st.button("Approve", type="primary", icon=":material/check:", key=f"approve_{c['id']}",
                          on_click=act, args=(c["id"], "decide", {"grant": True},
                                              "Consent given. Your records have been shared."))
                if len(c["hi_types"]) > 1:
                    for t in c["hi_types"]:
                        st.button(f"Only {HI_LABEL.get(t, t)}", key=f"only_{c['id']}_{t}", on_click=act,
                                  args=(c["id"], "decide", {"grant": True, "hi_types": [t]},
                                        f"Consent given for {HI_LABEL.get(t, t)} only."))
                st.button("Deny", icon=":material/close:", key=f"deny_{c['id']}", on_click=act,
                          args=(c["id"], "decide", {"grant": False}, "Request denied. Nothing was shared."))
        elif c["status"] in ("granted", "retrieving", "received"):
            if st.button("Revoke consent", icon=":material/block:", key=f"revoke_{c['id']}"):
                confirm_revoke(c)
