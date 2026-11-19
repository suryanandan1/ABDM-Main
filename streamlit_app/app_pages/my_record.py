import streamlit as st

import api
from ui import GENDERS, fmt_date, fmt_datetime, show_error

VITALS = {"temperature": "Temperature (°C)", "pulse": "Pulse (/min)", "systolic_bp": "BP systolic",
          "diastolic_bp": "BP diastolic", "spo2": "SpO₂ (%)", "weight": "Weight (kg)", "height": "Height (cm)",
          "respiratory_rate": "Resp. rate (/min)"}

try:
    data = api.get("/portal/me")
except api.ApiError as exc:
    show_error(exc)
    st.stop()

st.caption(f"ABHA address **{data['abha_address']}** · only records your doctors have approved are shown.")
if not data["hospitals"]:
    st.info(f"No hospital has verified your ABHA address yet. When a hospital registers you with "
            f"{data['abha_address']} and verifies it, your records from that hospital appear here.", icon=":material/info:")
    st.stop()

for record in data["hospitals"]:
    p = record["profile"]
    st.header(record["hospital_name"], anchor=False, divider="gray")

    with st.expander("My details", icon=":material/person:"):
        st.table({
            "Name": p["full_name"], "Patient ID": p["patient_code"], "Gender": GENDERS.get(p["gender"], p["gender"]),
            "Date of birth": fmt_date(p["date_of_birth"]) if p["date_of_birth"] else str(p["year_of_birth"]),
            "Mobile": p["mobile"],
            "Address": ", ".join(x for x in (p["address_line"], p["city"], p["state"], p["pincode"]) if x) or "—",
            "ABHA number": p["abha_number"] or "—",
            "ABHA address": f"{p['abha_address']} ({'verified' if p['abha_verified'] else 'not verified'})",
            "Emergency contact": " · ".join(x for x in (p["emergency_contact_name"], p["emergency_contact_relation"],
                                                         p["emergency_contact_phone"]) if x) or "—",
        }, alt="Patient details")

    st.subheader("Visits", anchor=False)
    if not record["visits"]:
        st.caption("No approved visits.")
    for v in record["visits"]:
        with st.container(border=True):
            st.markdown(f"**{fmt_datetime(v['visit_at'])}** · {v['doctor']['full_name']}")
            if v["conditions"]:
                with st.container(horizontal=True):
                    for c in v["conditions"]:
                        st.badge(f"{c['display']} ({c['code']})" if c.get("code") else c["display"], color="violet")
            for label, key in (("Complaint", "chief_complaint"), ("Findings", "clinical_findings"),
                               ("Plan", "treatment_plan"), ("Follow-up", "follow_up_instructions")):
                if v.get(key):
                    st.markdown(f"**{label}:** {v[key]}")
            if v.get("follow_up_date"):
                st.markdown(f"**Follow-up date:** {fmt_date(v['follow_up_date'])}")
            if v.get("vitals"):
                st.caption(" · ".join(f"{VITALS.get(k, k)}: {val}" for k, val in v["vitals"].items() if val is not None))

    st.subheader("Prescriptions", anchor=False)
    if not record["prescriptions"]:
        st.caption("No approved prescriptions.")
    for rx in record["prescriptions"]:
        with st.container(border=True):
            st.markdown(f"**{fmt_date(rx['prescription_date'])}** · {rx['doctor']['full_name']}")
            st.dataframe([{"Medicine": i["medicine_name"], "Dose": f"{i['dosage']} ({i['route']})",
                           "How often": i["frequency"], "Days": i["duration_days"], "Instructions": i["instructions"] or ""}
                          for i in rx["items"]], hide_index=True, alt="Prescribed medicines")
            if rx.get("notes"):
                st.caption(rx["notes"])

    st.subheader("Lab reports", anchor=False)
    if not record["lab_reports"]:
        st.caption("No approved lab reports.")
    for r in record["lab_reports"]:
        with st.container(border=True):
            st.markdown(f"**{r['test_name']}** · {fmt_date(r['approved_at'] or r['ordered_at'])}")
            st.dataframe([{
                "Test": x["name"], "Result": f"{x['value']} {x['unit'] or ''}".strip(),
                "Normal range": x["ref_text"] or " – ".join(str(n) for n in (x["ref_low"], x["ref_high"]) if n is not None),
                "Flag": {"H": "High", "L": "Low"}.get(x["interpretation"] or "", "")} for x in r["results"]],
                hide_index=True, alt=f"{r['test_name']} results")
            if r.get("conclusion"):
                st.markdown(f"**Conclusion:** {r['conclusion']}")
