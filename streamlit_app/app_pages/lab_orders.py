import streamlit as st

import api
from ui import LAB_ORDER, fmt_datetime, go, load, open_selector, pager, status_label

TABS = {"Awaiting sample": "ordered", "Results to enter": "sample_collected,in_progress", "Completed": "completed", "All": ""}
tab = st.segmented_control("Worklist", list(TABS), default="Awaiting sample", key="lab_tab") or "Awaiting sample"
PAGE_SIZE = 20
result = load(lambda: api.get("/lab/orders", status=TABS[tab] or None, page=st.session_state.get("lab_page", 1),
                              page_size=PAGE_SIZE))
items = result["items"]
st.caption(f"{result['total']} order(s)")
st.dataframe([{"#": o["id"], "Ordered": fmt_datetime(o["created_at"]),
               "Patient": f"{o['patient']['full_name']} ({o['patient']['patient_code']})", "Test": o["test"]["name"],
               "Priority": o["priority"].upper(), "Doctor": o["doctor"]["full_name"], "Status": status_label(o["status"]),
               "Report": status_label(o["report"]["status"]) if o.get("report") else "—"} for o in items],
             hide_index=True, alt="Lab orders")
pager("lab_page", result["total"], PAGE_SIZE)
chosen = open_selector("Open order", items, "lab_open",
                       lambda o: f"#{o['id']} · {o['test']['name']} · {o['patient']['full_name']}")
if chosen:
    go(LAB_ORDER, id=chosen["id"])
