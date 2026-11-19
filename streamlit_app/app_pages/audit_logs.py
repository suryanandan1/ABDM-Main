import json

import streamlit as st

import api
from ui import fmt_datetime, load, pager

with st.container(horizontal=True, vertical_alignment="bottom"):
    action = st.text_input("Action starts with", key="audit_action", placeholder="for example auth. or patient.")
    entity = st.text_input("Entity type", key="audit_entity", placeholder="for example patient")
PAGE_SIZE = 50
result = load(lambda: api.get("/audit-logs", action=action.strip() or None, entity_type=entity.strip() or None,
                              page=st.session_state.get("audit_page", 1), page_size=PAGE_SIZE))
st.caption(f"{result['total']} event(s)")
st.dataframe([{"When": fmt_datetime(a["created_at"]), "User": a.get("user_name") or "—", "Action": a["action"],
               "Entity": f"{a.get('entity_type') or ''} {a.get('entity_id') or ''}".strip(),
               "Details": json.dumps(a["details"]) if a.get("details") else "", "IP": a.get("ip_address") or ""}
              for a in result["items"]], hide_index=True, alt="Audit log")
pager("audit_page", result["total"], PAGE_SIZE)
