import streamlit as st

import api
from ui import (CONSULTATION, can, fhir_button, fmt_datetime, format_range, load, patient_banner, query_id, reason_dialog, run,
                status_badge, user)

FLAG = {"N": "Normal", "L": "Low", "H": "High", "A": "Abnormal"}

order_id = query_id()
o = load(lambda: api.get(f"/lab/orders/{order_id}"))
report = o.get("report")
can_enter = (can("lab:result") and o["status"] in ("sample_collected", "in_progress")
             and (not report or report["status"] in ("draft", "rejected")))
can_approve = can("lab:approve") and bool(user().get("doctor_id")) and (report or {}).get("status") == "pending_approval"

with st.container(horizontal=True, vertical_alignment="center"):
    status_badge(o["status"])
    if (report or {}).get("status") == "approved":
        fhir_button("lab_order", order_id, "lab_fhir")
    if can("clinical:read"):
        st.page_link(CONSULTATION, label="Open consultation", query_params={"id": str(o["encounter_id"])},
                     icon=":material/assignment:")
    if can("lab:order") and o["status"] in ("ordered", "sample_collected") and st.button("Cancel order", icon=":material/cancel:"):
        reason_dialog("Cancel order", f"/lab/orders/{order_id}/cancel", "Order cancelled.")
if o["status"] == "cancelled":
    st.warning(f"Cancelled: {o['status_reason']}")
if (report or {}).get("status") == "rejected":
    st.warning(f"Report returned for correction: {report['status_reason']}")
patient_banner(o["patient"])

c1, c2, c3 = st.columns(3)
with c1, st.container(border=True):
    st.caption("Test")
    st.markdown(f"**{o['test']['name']}**  \nPriority: {o['priority'].upper()}")
with c2, st.container(border=True):
    st.caption("Ordered by")
    st.markdown(f"{o['doctor']['full_name']}  \n{fmt_datetime(o['created_at'])}"
                + (f"  \nNotes: {o['clinical_notes']}" if o.get("clinical_notes") else ""))
with c3, st.container(border=True):
    st.caption(f"Sample ({o['test']['sample_type']})")
    if o["sample_status"] == "collected":
        st.markdown(f"{o['sample_barcode']}  \nCollected {fmt_datetime(o['sample_collected_at'])} by {o['sample_collected_by_name']}")
    else:
        st.markdown(f"Rejected: {o['sample_notes']}" if o["sample_status"] == "rejected" else "Not collected")

if o["status"] == "ordered" and can("lab:sample"):
    with st.form(f"sample_{order_id}", border=True):
        st.markdown("**Collect sample**")
        c1, c2 = st.columns(2)
        barcode = c1.text_input("Sample barcode (blank = auto)")
        notes = c2.text_input("Notes")
        if st.form_submit_button("Mark collected", type="primary", icon=":material/colorize:"):
            run(lambda: api.post(f"/lab/orders/{order_id}/sample", {"sample_barcode": barcode.strip() or None,
                                                                    "notes": notes.strip() or None}), "Sample collected.")
            st.rerun()

if can_enter:
    saved = {r["code"]: r for r in (report or {}).get("results", [])}
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown("**Enter results**")
            if o["status"] == "sample_collected" and can("lab:sample") and st.button("Reject sample", icon=":material/block:"):
                reason_dialog("Reject sample", f"/lab/orders/{order_id}/sample/reject", "Sample rejected.")
        with st.form(f"results_{order_id}", border=False):
            values = {}
            for p in o["test"]["parameters"]:
                numeric = p.get("ref_low") is not None or p.get("ref_high") is not None
                c1, c2, c3 = st.columns([2, 2, 1])
                value = c1.text_input(f"{p['name']}" + (f" ({p['unit']})" if p.get("unit") else ""),
                                      saved.get(p["code"], {}).get("value") or "", key=f"res_{order_id}_{p['code']}",
                                      help=f"Reference: {format_range(p) or '—'}")
                c2.caption(f"Reference range: {format_range(p) or '—'}")
                if numeric:
                    flag = saved.get(p["code"], {}).get("interpretation")
                    c3.caption(FLAG.get(flag, "") if flag else "")
                    interpretation = None
                else:
                    current = saved.get(p["code"], {}).get("interpretation") or ""
                    interpretation = c3.selectbox("Flag", ["", "N", "A"], index=["", "N", "A"].index(current) if current in ("", "N", "A") else 0,
                                                  format_func=lambda f: FLAG.get(f, "—"), key=f"flag_{order_id}_{p['code']}")
                values[p["code"]] = (value.strip() or None, interpretation or None)
            conclusion = st.text_area("Conclusion / remarks", (report or {}).get("conclusion") or "")
            st.caption("Numeric results are flagged against the reference range when saved.")
            with st.container(horizontal=True):
                save = st.form_submit_button("Save draft", icon=":material/save:")
                submit = st.form_submit_button("Submit for approval", type="primary", icon=":material/send:")

    def save_results():
        return api.put(f"/lab/orders/{order_id}/report", {
            "conclusion": conclusion.strip() or None,
            "results": [{"code": code, "value": v, "interpretation": i} for code, (v, i) in values.items()]})

    if save:
        run(save_results, "Results saved as draft.")
        st.rerun()
    if submit:
        if run(save_results):
            run(lambda: api.post(f"/lab/orders/{order_id}/report/submit"), "Report submitted for approval.")
        st.rerun()
elif report:
    with st.container(border=True):
        st.markdown("**Results**")
        st.dataframe([{"Parameter": r["name"], "Result": r["value"], "Unit": r.get("unit") or "",
                       "Reference range": format_range(r), "Flag": FLAG.get(r.get("interpretation") or "", "")}
                      for r in report["results"]], hide_index=True, alt="Laboratory results")
        if report.get("conclusion"):
            st.markdown(f"**Conclusion:** {report['conclusion']}")
        st.caption(f"Results entered by {report['created_by_name']} on {fmt_datetime(report['updated_at'])}."
                   + (f" Approved by {report['approved_by_name']} on {fmt_datetime(report['approved_at'])}."
                      if report.get("approved_by_name") else ""))
        if can_approve:
            with st.container(horizontal=True):
                if st.button("Return for correction", icon=":material/undo:"):
                    reason_dialog("Return report for correction", f"/lab/orders/{order_id}/report/reject", "Report returned.")
                if st.button("Approve report", type="primary", icon=":material/verified:"):
                    run(lambda: api.post(f"/lab/orders/{order_id}/report/approve"), "Report approved and released.")
                    st.rerun()
