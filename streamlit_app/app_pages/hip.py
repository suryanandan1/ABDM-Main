import streamlit as st

import api
from ui import (can, fmt_date, fmt_datetime, hi_labels, load, pager, patient_banner, patient_picker, run,
                status_label)

status = load(lambda: api.get("/hip/status"))
manage = can("hip:manage")

with st.container(horizontal=True, vertical_alignment="center"):
    st.badge(status["mode"].upper(), color="blue")
    st.badge(f"HIP {status['hip_id']}", color="gray")
    st.badge(f"HIU {status['hiu_id']}", color="gray")
    st.badge("HL7 validator installed" if status.get("fhir_validator") else "HL7 validator missing",
             color="green" if status.get("fhir_validator") else "orange")
c = status["counts"]
with st.container(horizontal=True):
    st.metric("Verified ABHA links", c["verified_links"], border=True)
    st.metric("Shareable records", c["care_contexts"], border=True)
    st.metric("Linked records", c["linked_care_contexts"], border=True)
    st.metric("Active consents", c["active_consents"], border=True)

tab = st.segmented_control("Section", ["Patient linking", "Linked records", "Consents", "Network"], default="Patient linking",
                           key="hip_tab") or "Patient linking"

if tab == "Network":
    network = load(lambda: api.get("/hip/network"))["hospitals"]
    st.caption("Hospitals on this simulated ABDM network. Each one is a HIP (shares records) and a HIU (requests records).")
    st.dataframe([{"Hospital": h["name"] + (" (this hospital)" if h["this_hospital"] else ""), "Code": h["code"],
                   "City": f"{h.get('city') or ''}, {h.get('state') or ''}".strip(", "), "HIP ID": h["hip_id"], "HIU ID": h["hiu_id"]}
                  for h in network], hide_index=True, alt="Hospitals on the network")

elif tab == "Linked records":
    link_status = st.selectbox("Status", ["", "linked", "not_linked"], format_func=lambda s: status_label(s) if s else "All",
                               key="hip_cc_status")
    result = load(lambda: api.get("/hip/care-contexts", link_status=link_status or None,
                                  page=st.session_state.get("hip_cc_page", 1), page_size=50))
    st.caption(f"{result['total']} record(s). Only HL7-validated FHIR records can be shared.")
    st.dataframe([{"Reference": cc["reference"], "Record": cc["display"], "Type": hi_labels([cc["hi_type"]]),
                   "Date": fmt_date(cc["record_date"]), "Status": status_label(cc["link_status"]),
                   "ABHA": cc.get("linked_abha_address") or "", "Linked": fmt_datetime(cc.get("linked_at"))}
                  for cc in result["items"]], hide_index=True, alt="Care contexts")
    pager("hip_cc_page", result["total"], 50)

elif tab == "Consents":
    result = load(lambda: api.get("/hip/consents", page=st.session_state.get("hip_consent_page", 1), page_size=50))
    st.caption("Consents other hospitals received from patients to fetch records from this hospital.")
    st.dataframe([{"Received": fmt_datetime(x["created_at"]), "Status": status_label(x["status"]),
                   "Patient": (x.get("patient") or {}).get("full_name", ""), "ABHA": x.get("abha_address") or "",
                   "Requested by (HIU)": x.get("hiu_name") or x.get("hiu_id") or "", "Purpose": x.get("purpose") or "",
                   "Records": hi_labels(x.get("hi_types")), "Care contexts": len(x.get("care_contexts") or []),
                   "From": fmt_date(x.get("date_from")), "To": fmt_date(x.get("date_to")),
                   "Erase on": fmt_date(x.get("data_erase_at"))} for x in result["items"]], hide_index=True, alt="Consents")
    pager("hip_consent_page", result["total"], 50)

else:
    patient = patient_picker("hip_patient")
    if patient is None:
        st.stop()
    overview = load(lambda: api.get(f"/hip/patients/{patient['id']}"))
    p = overview["patient"]
    patient_banner(p)
    link = overview.get("link")
    with st.container(border=True):
        st.markdown("**1. Verify ABHA with ABDM**")
        if link:
            st.markdown(f"{status_label(link['status'])} · {link.get('abha_address') or ''} · {link.get('message') or ''}")
        else:
            st.caption("Not verified with ABDM yet.")
        if manage and p.get("abha_address") and st.button("Verify ABHA and get link token", icon=":material/verified:"):
            run(lambda: api.post(f"/hip/patients/{p['id']}/link-token"), "Verification requested.")
            st.rerun()
        if not p.get("abha_address"):
            st.warning("Enter the patient's ABHA address on the patient record first.")

    contexts = overview.get("care_contexts", [])
    with st.container(border=True):
        st.markdown("**2. Link records to the ABHA address**")
        st.caption("Each record is an HL7-validated FHIR document. Linked records can be shared when the patient consents.")
        if not contexts:
            st.caption("No shareable records. Approve a record and validate its FHIR document first.")
        else:
            st.dataframe([{"Reference": cc["reference"], "Record": cc["display"], "Status": status_label(cc["link_status"]),
                           "Linked": fmt_datetime(cc.get("linked_at"))} for cc in contexts], hide_index=True, alt="Patient records")
            unlinked = [cc for cc in contexts if cc["link_status"] != "linked"]
            if manage and unlinked:
                chosen = st.multiselect("Records to link", [cc["id"] for cc in unlinked],
                                        default=[cc["id"] for cc in unlinked],
                                        format_func=lambda i: next(cc["display"] for cc in unlinked if cc["id"] == i))
                verified = bool(link and link.get("status") == "verified")
                if st.button("Link selected records", type="primary", disabled=not chosen or not verified, icon=":material/link:"):
                    run(lambda: api.post(f"/hip/patients/{p['id']}/care-contexts/link", {"care_context_ids": chosen}),
                        "Records linked.")
                    st.rerun()
                if not verified:
                    st.caption("Verify the ABHA address first.")

    if manage and status["mode"] == "simulation":
        with st.expander("Simulator: ABHA account in the simulated ABHA app", icon=":material/science:"):
            st.caption("Simulation only. Creates the patient's ABHA account so ABDM can verify it. Consent is never given "
                       "here: only the patient can grant it, after signing in with their ABHA address.")
            abha = st.text_input("Patient's ABHA address (in the simulated ABHA app)", p.get("abha_address") or "")
            if st.button("Create simulated ABHA account", icon=":material/person_add:", disabled=not abha.strip()):
                run(lambda: api.post("/hip/simulate/abha", {"abha_address": abha.strip(), "name": p["full_name"],
                                                            "gender": p["gender"], "year_of_birth": p["year_of_birth"],
                                                            "abha_number": p.get("abha_number")}),
                    "Simulated ABHA account created.")
                st.rerun()
