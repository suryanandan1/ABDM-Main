import pandas as pd
import streamlit as st

import api
from ui import fmt_date, fmt_datetime, patient_banner, patient_picker, show_error, status_badge

patient = patient_picker("hiu_records")
if patient is None:
    st.stop()

try:
    view = api.get(f"/hiu/patients/{patient['id']}/records")
except api.ApiError as exc:
    show_error(exc)
    st.stop()

patient_banner(view["patient"])
st.caption("Records received from other hospitals under the patient's consent. Originals are kept unmodified and "
           "deleted on the consent's erase date. Every view is logged.")
records = view["records"]
if not records:
    st.info("No records received for this patient. Send a consent request on **New request**.", icon=":material/info:")
    st.stop()

st.dataframe(
    [{"#": r["id"], "Source": r["source_name"] or r["source_hip_id"], "Category": r["category"],
      "Record date": fmt_date(r["record_date"]), "Received": fmt_datetime(r["received_at"]),
      "Validation": r["validation_status"].replace("_", " "), "Checksum OK": r["checksum_ok"],
      "Deleted on": fmt_date(r["erase_at"])} for r in records],
    hide_index=True, alt="Retrieved records")

left, right = st.columns(2)
with left, st.container(border=True):
    st.markdown("**Timeline**")
    for t in view["timeline"]:
        st.markdown(f"**{fmt_date(t['date'])}** · {t['category']} · {t['source']}")
        if t["highlights"]:
            st.caption(" · ".join(t["highlights"]))
with right, st.container(border=True):
    st.markdown("**Repeated laboratory tests**")
    if not view["lab_trends"]:
        st.caption("No test appears more than once.")
    for trend in view["lab_trends"]:
        unit = trend["points"][0].get("unit") or ""
        change = f" · change {trend['change']:+g} {unit}" if trend.get("comparable") else ""
        st.markdown(f"**{trend['test']}**{change}")
        if trend.get("comparable"):
            st.line_chart(pd.DataFrame({"Date": [pd.to_datetime(p["date"]) for p in trend["points"]],
                                        trend["test"]: [p["value"] for p in trend["points"]]}),
                          x="Date", y=trend["test"], height=160, alt=f"{trend['test']} over time")
        else:
            st.caption(" · ".join(f"{fmt_date(p['date'])}: {p.get('value') or p.get('value_text')} {p.get('unit') or ''}"
                                  for p in trend["points"]))

by_id = {r["id"]: r for r in records}
record_id = st.selectbox("Open record", list(by_id), key="hiu_record_open",
                         format_func=lambda i: f"#{i} · {by_id[i]['category']} · {by_id[i]['source_name']} · "
                                               f"{fmt_date(by_id[i]['record_date'])}")
try:
    opened = api.get(f"/hiu/records/{record_id}")
except api.ApiError as exc:
    show_error(exc)
    st.stop()
facts, rec = opened["facts"], opened["record"]

st.subheader(f"{facts['category']} · {rec['source_name']} · {fmt_date(rec['record_date'])}", anchor=False)
with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="center"):
        status_badge(rec["validation_status"])
        if st.button("Validate with HL7 validator", icon=":material/fact_check:", key=f"validate_{record_id}"):
            with st.spinner("Validating (this can take about a minute)..."):
                try:
                    api.post(f"/hiu/records/{record_id}/validate")
                except api.ApiError as exc:
                    show_error(exc)
                else:
                    st.rerun()
    if facts["conditions"]:
        st.markdown("**Conditions:** " + ", ".join(c["text"] for c in facts["conditions"] if c.get("text")))
    if facts["medications"]:
        st.markdown("**Medicines:** " + "; ".join(f"{m['name']} ({m.get('dosage') or ''})" for m in facts["medications"]))
    if facts["observations"]:
        st.markdown("**Results:** " + "; ".join(
            f"{o['name']} {o.get('value') if o.get('value') is not None else o.get('value_text') or ''} {o.get('unit') or ''}"
            for o in facts["observations"]))
    for r in facts["reports"]:
        if r.get("conclusion"):
            st.markdown(f"**{r['name']}:** {r['conclusion']}")
    for s in facts["sections"]:
        st.markdown(f"**{s['title']}:** {s['text']}")
    if opened.get("validation_issues"):
        with st.expander("Validation issues"):
            st.dataframe(opened["validation_issues"], hide_index=True, alt="HL7 validation issues")
    with st.expander("Original FHIR bundle (as received)", icon=":material/data_object:"):
        st.json(opened["original"], expanded=False)
    st.caption(f"Consent {rec['consent_artefact_id']} · care context {rec['care_context_reference']}")
