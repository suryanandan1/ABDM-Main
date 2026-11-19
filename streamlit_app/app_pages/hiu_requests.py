import streamlit as st

import api
from ui import fmt_date, fmt_datetime, hi_labels, patient_banner, show_error, status_badge

try:
    dash = api.get("/hiu/dashboard")
except api.ApiError as exc:
    show_error(exc)
    st.stop()

if dash["mode"] == "simulation":
    st.caption("Simulation: the ABDM consent manager is simulated. Records come from the other hospitals on this "
               "network that linked records to the patient's ABHA address.")
c = dash["counts"]
with st.container(horizontal=True):
    st.metric("New today", c["new_today"], border=True)
    st.metric("Waiting for patient", c["pending_consent"], border=True)
    st.metric("Records received", c["received"], border=True)
    st.metric("Denied", c["denied"], border=True)
    st.metric("Failed / ended", c["failed"], border=True)
    st.metric("Stored records", c["records"], border=True)

if note := st.session_state.pop("hiu_note", None):
    (st.success if note[0] else st.error)(note[1])

status_filter = st.segmented_control(
    "Show", ["All", "Waiting for patient", "Received", "Denied / ended"], default="All", key="hiu_filter")
statuses = {"Waiting for patient": "pending_consent", "Received": "received",
            "Denied / ended": "denied,revoked,failed,expired"}.get(status_filter or "All")
try:
    items = api.get("/hiu/requests", status=statuses, page_size=100)["items"]
except api.ApiError as exc:
    show_error(exc)
    st.stop()
if not items:
    st.info("No requests yet. Create one on **New request**.", icon=":material/info:")
    st.stop()

st.dataframe(
    [{"Created": fmt_datetime(r["created_at"]), "Patient": r["patient"]["full_name"], "ABHA": r["abha_address"],
      "Records requested": hi_labels(r["hi_types"]), "Purpose": dash["purposes"].get(r["purpose_code"], r["purpose_code"]),
      "Status": r["status"].replace("_", " "), "What is happening": r["status_message"] or ""} for r in items],
    hide_index=True, alt="Consent requests sent")

by_id = {r["id"]: r for r in items}
request_id = st.selectbox(
    "Open request", list(by_id), key="hiu_open",
    format_func=lambda i: f"#{i} · {by_id[i]['patient']['full_name']} · {fmt_datetime(by_id[i]['created_at'])} · "
                          f"{by_id[i]['status'].replace('_', ' ')}")
try:
    detail = api.get(f"/hiu/requests/{request_id}")
except api.ApiError as exc:
    show_error(exc)
    st.stop()
r = detail["request"]


st.subheader("Request detail", anchor=False)
patient_banner(r["patient"])
with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="center"):
        status_badge(r["status"])
        st.markdown(r["status_message"] or "")
    st.markdown(f"Requested by **{detail['requester']}** · {hi_labels(r['hi_types'])} · "
                f"{fmt_date(r['date_from'])} – {fmt_date(r['date_to'])} · data deleted {fmt_date(r['data_erase_at'])}")
    if r.get("reason"):
        st.markdown(f"**Reason:** {r['reason']}")
    # Consent is the patient's decision: staff cannot grant, deny or revoke it (the backend refuses too).
    if r["status"] == "pending_consent":
        st.info(f"Waiting for the patient. Only the patient can approve or deny this: they sign in with their ABHA "
                f"address ({r['abha_address']}) and open Consent requests.", icon=":material/lock_person:")

left, right = st.columns(2)
with left, st.container(border=True):
    st.markdown("**Consent artefacts**")
    if not detail["artefacts"]:
        st.caption("None yet. Nothing can be retrieved until the patient grants consent.")
    for a in detail["artefacts"]:
        with st.container(horizontal=True, vertical_alignment="center"):
            status_badge(a["status"])
            st.markdown(f"**{a['hip_name'] or a['hip_id']}** · {hi_labels(a['hi_types'])} · {a['care_contexts']} record(s)")
with right, st.container(border=True):
    st.markdown("**Timeline**")
    for t in detail["timeline"]:
        icon = {"success": ":material/check_circle:", "failed": ":material/cancel:"}.get(t["status"], ":material/pending:")
        st.markdown(f"{icon} {fmt_datetime(t['at'])} · {t['message']}")
