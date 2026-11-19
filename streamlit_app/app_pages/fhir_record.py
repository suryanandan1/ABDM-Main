import json
import re

import streamlit as st

import api
from ui import (CONSULTATION, DOCUMENT, FHIR_RECORD, LAB_ORDER, PRESCRIPTION, can, fmt_datetime, go, load, patient_banner,
                query_id, run, status_badge)

SOURCE_PAGE = {"consultation": CONSULTATION, "prescription": PRESCRIPTION, "lab_order": LAB_ORDER, "document": DOCUMENT}
CATEGORY = {"required": "Missing required data", "terminology": "Terminology", "reference": "Resource reference",
            "profile": "Profile rule", "structure": "Bundle structure", "data": "Source data", "validator": "Validator",
            "other": "Other"}

record_id = query_id()
r = load(lambda: api.get(f"/fhir/records/{record_id}"))


def issue_table(issues: list[dict], show_info: bool, alt: str) -> None:
    shown = [i for i in issues or [] if show_info or i.get("severity") != "information"]
    if not shown:
        st.caption("No issues.")
        return
    st.dataframe([{"Severity": i.get("severity"), "Category": CATEGORY.get(i.get("category"), i.get("category")),
                   "Location": i.get("location") or "—", "Message": i.get("message")} for i in shown], hide_index=True, alt=alt)


with st.container(horizontal=True, vertical_alignment="center"):
    st.subheader(r["record_type"], anchor=False)
    st.badge(f"v{r['version']}", color="gray")
    status_badge(r["validation_status"])
    if r["hip_eligible"]:
        st.badge("Eligible for HIP sharing", color="green")
with st.container(horizontal=True):
    st.page_link(SOURCE_PAGE[r["source_type"]], label="Open source record", query_params={"id": str(r["source_id"])},
                 icon=":material/open_in_new:")
    if can("fhir:generate") and st.button("Regenerate from source", icon=":material/refresh:"):
        new = run(lambda: api.post("/fhir/records", {"source_type": r["source_type"], "source_id": r["source_id"]}),
                  "Regenerated from the source record.")
        if isinstance(new, dict) and new["id"] != record_id:
            go(FHIR_RECORD, id=new["id"])
        st.rerun()
    st.download_button("Download JSON", lambda: api.get_bytes(f"/fhir/records/{record_id}/download"),
                       f"{r['record_type']}-{r['source_type']}-{r['source_id']}-v{r['version']}.json", "application/json",
                       icon=":material/download:", on_click="ignore")
    if can("fhir:generate") and st.button("Validate", type="primary", icon=":material/fact_check:"):
        with st.spinner("Running the HL7 FHIR validator with the ABDM implementation guide. This takes about a minute…"):
            run(lambda: api.post(f"/fhir/records/{record_id}/validate"), "Validation finished.")
        st.rerun()
patient_banner(r["patient"])

entries = (r.get("bundle") or {}).get("entry", [])
errors = sum(i.get("severity") == "error" for i in (r.get("validation_issues") or []) + (r.get("prechecks") or []))
view = st.segmented_control("View", [f"Validation{f' ({errors} errors)' if errors else ''}", f"Resources ({len(entries)})", "JSON"],
                            default=f"Validation{f' ({errors} errors)' if errors else ''}", key=f"fhir_view_{record_id}")

if view and view.startswith("Validation"):
    st.markdown("**Local pre-checks**")
    st.caption("Quick structural, reference and required-data checks done when the bundle was generated. "
               "These are not profile validation.")
    issue_table(r.get("prechecks"), True, "Local pre-check issues")
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown("**FHIR R4 and ABDM profile validation**")
        show_info = st.toggle("Show information messages", key=f"fhir_info_{record_id}")
    if r["validation_status"] == "not_validated":
        st.info("This version has not been validated yet. Run “Validate” to check it with the official HL7 FHIR validator.")
    else:
        st.caption(f"{r.get('validator') or ''} · {fmt_datetime(r.get('validated_at'))}")
        if r["validation_status"] == "invalid":
            st.error("Fix the source record (or its review), then use “Regenerate from source” and validate again.")
        issue_table(r.get("validation_issues"), show_info, "HL7 validation issues")
elif view and view.startswith("Resources"):
    st.dataframe([{"#": n, "Resource": e["resource"].get("resourceType"),
                   "Profile": ((e["resource"].get("meta") or {}).get("profile") or [""])[0].rsplit("/", 1)[-1],
                   "Summary": re.sub(r"<[^>]+>", " ", (e["resource"].get("text") or {}).get("div", "")).strip()[:160]}
                  for n, e in enumerate(entries)], hide_index=True, alt="Resources in the bundle")
elif view == "JSON":
    st.code(json.dumps(r.get("bundle"), indent=2), language="json", height=600)
