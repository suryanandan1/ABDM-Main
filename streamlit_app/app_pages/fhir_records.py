import streamlit as st

import api
from ui import FHIR_RECORD, fmt_datetime, go, load, open_selector, pager, status_label

VALIDATION = ["not_validated", "valid", "invalid", "error"]
status = st.selectbox("Validation", ["", *VALIDATION], format_func=lambda s: status_label(s) if s else "All", key="fhir_status")
PAGE_SIZE = 20
result = load(lambda: api.get("/fhir/records", validation_status=status or None, page=st.session_state.get("fhir_page", 1),
                              page_size=PAGE_SIZE))
items = result["items"]
if not items:
    st.info("No FHIR records yet. Approve a document or use “View FHIR” on an approved record.", icon=":material/info:")
    st.stop()
st.caption(f"{result['total']} record(s)")
st.dataframe([{"#": r["id"], "Generated": f"{fmt_datetime(r['generated_at'])} · v{r['version']}",
               "Patient": f"{r['patient']['full_name']} ({r['patient']['patient_code']})", "Record": r["record_type"],
               "Title": r["title"], "Source": f"{r['source_type'].replace('_', ' ')} #{r['source_id']}",
               "Validation": status_label(r["validation_status"]), "HIP eligible": r["hip_eligible"]} for r in items],
             hide_index=True, alt="FHIR records")
pager("fhir_page", result["total"], PAGE_SIZE)
chosen = open_selector("Open record", items, "fhir_open", lambda r: f"#{r['id']} · {r['record_type']} · {r['patient']['full_name']}")
if chosen:
    go(FHIR_RECORD, id=chosen["id"])
