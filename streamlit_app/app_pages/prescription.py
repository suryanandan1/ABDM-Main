import pandas as pd
import streamlit as st

import api
from ui import (CONSULTATION, PRESCRIPTION, fhir_button, fmt_date, fmt_datetime, go, load, patient_banner, reason_dialog,
                run, status_badge, terminology, user)

COLUMNS = ["medicine_name", "dosage", "route", "frequency", "duration_days", "quantity", "instructions"]
terms = terminology()
routes = {r["key"]: r["label"] for r in terms["routes"]}
frequencies = {f["key"]: f["label"] for f in terms["frequencies"]}

pid, encounter_param = st.query_params.get("id"), st.query_params.get("encounter")
if pid and str(pid).isdigit():
    rx = load(lambda: api.get(f"/prescriptions/{pid}"))
    encounter = None
elif encounter_param and str(encounter_param).isdigit():
    rx = None
    encounter = load(lambda: api.get(f"/consultations/{encounter_param}"))
else:
    st.warning("Nothing selected. Open a prescription from its list or a consultation.")
    st.stop()

is_new = rx is None
patient = rx["patient"] if rx else encounter["patient"]
status = rx["status"] if rx else "draft"
prescriber = is_new or user().get("doctor_id") == rx["doctor"]["id"]
editable = prescriber and status in ("draft", "rejected")

with st.container(horizontal=True, vertical_alignment="center"):
    st.subheader("New prescription" if is_new else f"Prescription #{rx['id']}", anchor=False)
    status_badge(status)
    if status == "approved":
        fhir_button("prescription", rx["id"], "rx_fhir")
    if rx:
        st.page_link(CONSULTATION, label="Open consultation", query_params={"id": str(rx["encounter_id"])},
                     icon=":material/assignment:")
    if prescriber and rx and status != "cancelled" and st.button("Cancel", icon=":material/cancel:"):
        reason_dialog("Cancel prescription", f"/prescriptions/{rx['id']}/cancel", "Prescription cancelled.")
if rx and rx.get("status_reason"):
    st.warning(f"{'Rejected' if status == 'rejected' else 'Cancelled'}: {rx['status_reason']}")
patient_banner(patient)

if editable:
    items = rx["items"] if rx else [{"medicine_name": "", "dosage": "", "route": "oral", "frequency": "BD", "duration_days": 5,
                                     "quantity": None, "instructions": None}]
    with st.form(f"rx_form_{pid or 'new'}"):
        edited = st.data_editor(
            pd.DataFrame([{k: i.get(k) for k in COLUMNS} for i in items], columns=COLUMNS),
            num_rows="dynamic", hide_index=True, key=f"rx_items_{pid or encounter_param}",
            column_config={
                "medicine_name": st.column_config.TextColumn("Medicine", required=True, width="large"),
                "dosage": st.column_config.TextColumn("Dosage", required=True, help="For example 1 tablet"),
                "route": st.column_config.SelectboxColumn("Route", options=list(routes), default="oral", required=True),
                "frequency": st.column_config.SelectboxColumn("Frequency", options=list(frequencies), default="BD", required=True,
                                                              help=" · ".join(f"{k} = {v}" for k, v in frequencies.items())),
                "duration_days": st.column_config.NumberColumn("Days", min_value=1, max_value=365, default=5, required=True),
                "quantity": st.column_config.NumberColumn("Qty", min_value=1),
                "instructions": st.column_config.TextColumn("Instructions", help="For example After food")})
        notes = st.text_area("Notes / advice", (rx or {}).get("notes") or "")
        with st.container(horizontal=True):
            save = st.form_submit_button("Save draft", icon=":material/save:")
            submit = st.form_submit_button("Submit for approval", type="primary", disabled=is_new, icon=":material/send:")

    def body() -> dict:
        rows = []
        for r in edited.to_dict("records"):
            if not str(r.get("medicine_name") or "").strip():
                continue
            rows.append({"medicine_name": str(r["medicine_name"]).strip(), "dosage": str(r.get("dosage") or "").strip(),
                         "route": r.get("route") or "oral", "frequency": r.get("frequency") or "BD",
                         "duration_days": int(r["duration_days"]) if pd.notna(r.get("duration_days")) else 1,
                         "quantity": int(r["quantity"]) if pd.notna(r.get("quantity")) else None,
                         "instructions": (str(r["instructions"]).strip() or None) if pd.notna(r.get("instructions")) and r.get("instructions") else None})
        return {"items": rows, "notes": notes.strip() or None}

    if save:
        if is_new:
            created = run(lambda: api.post("/prescriptions", {**body(), "encounter_id": int(encounter_param)}), "Draft saved.")
            if isinstance(created, dict):
                go(PRESCRIPTION, id=created["id"])
        else:
            run(lambda: api.put(f"/prescriptions/{rx['id']}", body()), "Draft saved.")
        st.rerun()
    if submit:
        if run(lambda: api.put(f"/prescriptions/{rx['id']}", body())):
            run(lambda: api.post(f"/prescriptions/{rx['id']}/submit"), "Submitted. Review the prescription below and approve it.")
        st.rerun()
    st.stop()

# Read-only view (printable layout in React)
with st.container(border=True):
    with st.container(horizontal=True):
        st.markdown(f"**{user().get('hospital_name') or ''}**  \n{rx['doctor']['full_name']}"
                    + (f", {rx['doctor']['qualification']}" if rx["doctor"].get("qualification") else "")
                    + f"  \nReg. no. {rx['doctor']['registration_number']}"
                    + (f" · {rx['doctor']['specialization']}" if rx["doctor"].get("specialization") else ""))
        st.markdown(f"Date: {fmt_date(rx['prescription_date'])}  \nConsultation #{rx['encounter_id']}")
    st.dataframe([{"#": n + 1, "Medicine": i["medicine_name"], "Dosage": i["dosage"], "Route": routes.get(i["route"], i["route"]),
                   "Frequency": f"{i['frequency']} ({frequencies.get(i['frequency'], '')})", "Duration": f"{i['duration_days']} days",
                   "Qty": i.get("quantity") or "", "Instructions": i.get("instructions") or ""}
                  for n, i in enumerate(rx["items"])], hide_index=True, alt="Prescribed medicines")
    if rx.get("notes"):
        st.markdown(f"**Advice:** {rx['notes']}")
    st.caption(f"Approved by {rx['approved_by_name']} on {fmt_datetime(rx['approved_at'])}" if status == "approved"
               else f"Created by {rx['created_by_name']} on {fmt_datetime(rx['created_at'])}")

if status == "pending_approval" and prescriber:
    with st.container(border=True):
        reviewed = st.checkbox("I have reviewed every medicine, dose, frequency and duration for this patient.")
        with st.container(horizontal=True):
            if st.button("Reject and revise", icon=":material/undo:"):
                reason_dialog("Reject prescription", f"/prescriptions/{rx['id']}/reject",
                              "Rejected. Edit the prescription and submit again.")
            if st.button("Approve prescription", type="primary", disabled=not reviewed, icon=":material/verified:"):
                run(lambda: api.post(f"/prescriptions/{rx['id']}/approve"), "Prescription approved.")
                st.rerun()
