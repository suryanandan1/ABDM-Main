import streamlit as st

import api
from ui import CONSULTATION, LAB_ORDER, PRESCRIPTION, fmt_date, fmt_datetime, load, patient_banner, query_id, terminology

patient_id = query_id()
history = load(lambda: api.get(f"/patients/{patient_id}/history"))
terms = terminology()

patient_banner(history["patient"])
st.caption("Shows finalized consultations, approved prescriptions and approved laboratory reports only.")

left, right = st.columns([1, 2])
with left:
    with st.container(border=True):
        st.markdown("**Active conditions**")
        if not history["active_conditions"]:
            st.caption("None recorded.")
        with st.container(horizontal=True):
            for c in history["active_conditions"]:
                st.badge(c["display"] + (f" ({c['code']})" if c.get("code") else ""),
                         color="blue" if c["verification_status"] == "confirmed" else "gray")
    latest = next((c for c in history["consultations"] if c.get("vitals") and any(v is not None for v in c["vitals"].values())), None)
    if latest:
        with st.container(border=True):
            st.markdown("**Latest vitals**")
            st.caption(fmt_datetime(latest["visit_at"]))
            for t in terms["vitals"]:
                if latest["vitals"].get(t["key"]) is not None:
                    st.markdown(f"{t['label']}: {latest['vitals'][t['key']]} {'°C' if t['unit'] == 'Cel' else t['unit']}")

with right:
    with st.container(border=True):
        st.markdown("**Consultations**")
        if not history["consultations"]:
            st.caption("No finalized consultations.")
        for c in history["consultations"]:
            st.page_link(CONSULTATION, query_params={"id": str(c["id"])}, icon=":material/assignment:",
                         label=f"{fmt_date(c['visit_at'])} · {c['doctor']['full_name']} — {c['chief_complaint'] or ''}")
            extra = [", ".join(d["display"] for d in c["conditions"]), c.get("treatment_plan") or ""]
            if any(extra):
                st.caption(" · ".join(x for x in extra if x))
    with st.container(border=True):
        st.markdown("**Prescriptions**")
        if not history["prescriptions"]:
            st.caption("No approved prescriptions.")
        else:
            st.dataframe([{"Date": fmt_date(p["prescription_date"]), "Medicine": i["medicine_name"],
                           "Dose": f"{i['dosage']} {i['frequency']}", "Duration": f"{i['duration_days']} days",
                           "Doctor": p["doctor"]["full_name"], "Prescription": f"#{p['id']}"}
                          for p in history["prescriptions"] for i in p["items"]], hide_index=True, alt="Approved prescriptions")
            with st.container(horizontal=True):
                for p in history["prescriptions"]:
                    st.page_link(PRESCRIPTION, label=f"Prescription #{p['id']}", query_params={"id": str(p["id"])})
    with st.container(border=True):
        st.markdown("**Laboratory reports**")
        if not history["lab_orders"]:
            st.caption("No approved reports.")
        for o in history["lab_orders"]:
            st.page_link(LAB_ORDER, query_params={"id": str(o["id"])}, icon=":material/science:",
                         label=f"{o['test']['name']} · {fmt_date((o.get('report') or {}).get('approved_at') or o['created_at'])}")
            results = (o.get("report") or {}).get("results", [])
            st.markdown(" · ".join(
                (f":red[{r['name']}: {r['value']}{' ' + r['unit'] if r['unit'] else ''} ({r['interpretation']})]"
                 if r.get("interpretation") and r["interpretation"] != "N"
                 else f"{r['name']}: {r['value']}{' ' + r['unit'] if r['unit'] else ''}") for r in results))
