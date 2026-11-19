import pandas as pd
import streamlit as st

import api
from ui import (LAB_ORDER, PRESCRIPTION, can, fhir_button, fmt_date, fmt_datetime, load, patient_banner, query_id,
                reason_dialog, run, status_badge, status_label, terminology, to_date, user)

TEXT_TOP = [("chief_complaint", "Chief complaint"), ("history_present_illness", "History of present illness"),
            ("clinical_findings", "Clinical findings / examination")]
TEXT_BOTTOM = [("treatment_plan", "Treatment plan"), ("follow_up_instructions", "Follow-up instructions"),
               ("doctor_notes", "Doctor notes (internal)")]
CERTAINTY = ["provisional", "confirmed", "differential"]
CLINICAL = ["active", "recurrence", "inactive", "resolved"]

encounter_id = query_id()
e = load(lambda: api.get(f"/consultations/{encounter_id}"))
terms = terminology()
own = user().get("doctor_id") == e["doctor"]["id"]
editable = own and e["status"] == "draft"
active = e["status"] != "cancelled"


@st.dialog("Order laboratory tests")
def order_tests() -> None:
    tests = load(lambda: api.get("/lab/tests", active_only=True))
    if not tests:
        st.caption("The lab catalogue is empty.")
        return
    chosen = st.multiselect("Tests", [t["id"] for t in tests],
                            format_func=lambda i: next(f"{t['name']} ({t['sample_type']})" for t in tests if t["id"] == i))
    priority = st.segmented_control("Priority", ["routine", "urgent", "stat"], default="routine",
                                    format_func=lambda p: p.upper() if p == "stat" else p.capitalize())
    notes = st.text_input("Clinical notes for the lab")
    if st.button(f"Order {len(chosen) or ''} test{'s' if len(chosen) != 1 else ''}", type="primary", disabled=not chosen):
        if run(lambda: api.post("/lab/orders", {"encounter_id": encounter_id, "test_ids": chosen, "priority": priority or "routine",
                                                "clinical_notes": notes or None}), "Tests ordered."):
            st.rerun()
        for ok, msg in st.session_state.pop("flash", []):
            (st.success if ok else st.error)(msg)


with st.container(horizontal=True, vertical_alignment="center"):
    status_badge(e["status"], "Finalized")
    if e["status"] == "approved":
        fhir_button("consultation", encounter_id, "cons_fhir")
    if editable and st.button("Cancel visit", icon=":material/cancel:"):
        reason_dialog("Cancel consultation", f"/consultations/{encounter_id}/cancel", "Consultation cancelled.")
patient_banner(e["patient"])
if e["status"] == "cancelled":
    st.warning(f"Cancelled: {e['status_reason']}")
if e["status"] == "draft" and not own:
    st.info(f"Only {e['doctor']['full_name']} can edit this consultation.")

left, right = st.columns([2, 1])
with left:
    st.caption(f"{e['doctor']['full_name']} · visit {fmt_datetime(e['visit_at'])}"
               + (f" · finalized {fmt_datetime(e['approved_at'])}" if e.get("approved_at") else ""))
    with st.form(f"consultation_{encounter_id}", border=True):
        st.markdown("**Vital signs**")
        cols = st.columns(4)
        vitals = {}
        for i, v in enumerate(terms["vitals"]):
            current = (e.get("vitals") or {}).get(v["key"])
            vitals[v["key"]] = cols[i % 4].number_input(
                f"{v['label']} ({'°C' if v['unit'] == 'Cel' else v['unit']})", value=float(current) if current is not None else None,
                min_value=float(v["min"]) if v.get("min") is not None else None,
                max_value=float(v["max"]) if v.get("max") is not None else None, disabled=not editable, key=f"vital_{v['key']}")
        text = {k: st.text_area(label + (" *" if k == "chief_complaint" else ""), e.get(k) or "", disabled=not editable, height=80)
                for k, label in TEXT_TOP}

        st.markdown("**Diagnosis**")
        diagnoses = pd.DataFrame([{"display": c["display"], "code": c.get("code") or "", "verification_status": c["verification_status"],
                                   "clinical_status": c["clinical_status"]} for c in e["conditions"]],
                                 columns=["display", "code", "verification_status", "clinical_status"])
        edited = st.data_editor(
            diagnoses, num_rows="dynamic" if editable else "fixed", disabled=not editable, hide_index=True,
            key=f"diag_{encounter_id}",
            column_config={"display": st.column_config.TextColumn("Diagnosis", required=True, width="large"),
                           "code": st.column_config.TextColumn("ICD-10", help="For example E11.9"),
                           "verification_status": st.column_config.SelectboxColumn("Certainty", options=CERTAINTY, default="provisional"),
                           "clinical_status": st.column_config.SelectboxColumn("Status", options=CLINICAL, default="active")})

        text.update({k: st.text_area(label, e.get(k) or "", disabled=not editable, height=80) for k, label in TEXT_BOTTOM})
        follow_up = st.date_input("Follow-up date", to_date(e.get("follow_up_date")), disabled=not editable, format="DD/MM/YYYY")
        with st.container(horizontal=True):
            save = st.form_submit_button("Save draft", disabled=not editable, icon=":material/save:")
            finalize = st.form_submit_button("Finalize", type="primary", disabled=not editable, icon=":material/task_alt:")

    def payload() -> dict:
        rows = [r for r in edited.to_dict("records") if str(r.get("display") or "").strip()]
        return {**{k: (v.strip() or None) for k, v in text.items()},
                "follow_up_date": follow_up.isoformat() if follow_up else None,
                "vitals": {k: v for k, v in vitals.items()},
                "diagnoses": [{"display": r["display"].strip(), "code": (str(r.get("code") or "").strip().upper() or None),
                               "verification_status": r.get("verification_status") or "provisional",
                               "clinical_status": r.get("clinical_status") or "active"} for r in rows]}

    if save:
        run(lambda: api.put(f"/consultations/{encounter_id}", payload()), "Draft saved.")
        st.rerun()
    if finalize:
        st.session_state[f"confirm_finalize_{encounter_id}"] = payload()
    pending = st.session_state.get(f"confirm_finalize_{encounter_id}")
    if pending:
        st.warning("Finalize this consultation? It cannot be edited afterwards.")
        with st.container(horizontal=True):
            if st.button("Yes, finalize", type="primary"):
                st.session_state.pop(f"confirm_finalize_{encounter_id}")
                if run(lambda: api.put(f"/consultations/{encounter_id}", pending)):
                    run(lambda: api.post(f"/consultations/{encounter_id}/finalize"), "Consultation finalized.")
                st.rerun()
            if st.button("Keep editing"):
                st.session_state.pop(f"confirm_finalize_{encounter_id}")
                st.rerun()

    if own and e["status"] == "approved" and e["conditions"]:
        with st.container(border=True):
            st.markdown("**Update diagnosis status**")
            st.caption("After finalizing, you can still mark a diagnosis resolved or active again.")
            for c in e["conditions"]:
                with st.container(horizontal=True, vertical_alignment="bottom"):
                    new = st.selectbox(c["display"], CLINICAL, index=CLINICAL.index(c["clinical_status"]), key=f"cs_{c['id']}")
                    if new != c["clinical_status"] and st.button("Update", key=f"cs_go_{c['id']}"):
                        run(lambda cid=c["id"], value=new: api.patch(f"/conditions/{cid}", {"clinical_status": value}),
                            "Diagnosis status updated.")
                        st.rerun()

with right:
    prescriptions = load(lambda: api.get("/prescriptions", encounter_id=encounter_id, page_size=50))["items"]
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown("**Prescriptions**")
            if active and can("prescription:write") and user().get("doctor_id"):
                st.page_link(PRESCRIPTION, label="New", icon=":material/add:", query_params={"encounter": str(encounter_id)})
        if not prescriptions:
            st.caption("None yet.")
        for p in prescriptions:
            st.page_link(PRESCRIPTION, query_params={"id": str(p["id"])}, icon=":material/medication:",
                         label=f"{', '.join(i['medicine_name'] for i in p['items'])} · {fmt_date(p['prescription_date'])} · "
                               f"{status_label(p['status'])}")
    if can("lab:read"):
        orders = load(lambda: api.get("/lab/orders", encounter_id=encounter_id, page_size=50))["items"]
        with st.container(border=True):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown("**Lab orders**")
                if active and can("lab:order") and user().get("doctor_id") and st.button("Order tests", icon=":material/add:"):
                    order_tests()
            if not orders:
                st.caption("None yet.")
            for o in orders:
                st.page_link(LAB_ORDER, query_params={"id": str(o["id"])}, icon=":material/science:",
                             label=f"{o['test']['name']} · {o['priority']} · {fmt_date(o['created_at'])} · {status_label(o['status'])}")
