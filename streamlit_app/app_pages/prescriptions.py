import streamlit as st

import api
from ui import PRESCRIPTION, fmt_date, go, load, open_selector, pager, status_label

STATUSES = ["draft", "pending_approval", "approved", "rejected", "cancelled"]
status = st.selectbox("Status", ["", *STATUSES], format_func=lambda s: status_label(s) if s else "All", key="rx_status")
PAGE_SIZE = 20
result = load(lambda: api.get("/prescriptions", status=status or None, page=st.session_state.get("rx_page", 1),
                              page_size=PAGE_SIZE))
items = result["items"]
st.caption(f"{result['total']} prescription(s)")
st.dataframe([{"#": p["id"], "Date": fmt_date(p["prescription_date"]),
               "Patient": f"{p['patient']['full_name']} ({p['patient']['patient_code']})", "Doctor": p["doctor"]["full_name"],
               "Medicines": ", ".join(i["medicine_name"] for i in p["items"]), "Status": status_label(p["status"])}
              for p in items], hide_index=True, alt="Prescriptions")
pager("rx_page", result["total"], PAGE_SIZE)
chosen = open_selector("Open prescription", items, "rx_open",
                       lambda p: f"#{p['id']} · {p['patient']['full_name']} · {fmt_date(p['prescription_date'])}")
if chosen:
    go(PRESCRIPTION, id=chosen["id"])
