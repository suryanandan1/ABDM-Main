import pandas as pd
import streamlit as st

import api
from ui import can, format_range, load, run

PARAM_COLUMNS = ["code", "name", "unit", "ref_low", "ref_high", "ref_text"]
can_edit = can("lab:catalog")
tests = load(lambda: api.get("/lab/tests"))


@st.dialog("Lab test", width="large")
def test_dialog(test: dict | None) -> None:
    with st.form("lab_test_form", border=False):
        c1, c2 = st.columns([1, 3])
        code = c1.text_input("Code *", (test or {}).get("code", ""), disabled=bool(test), help="2-30 letters, digits, - or _")
        name = c2.text_input("Test name *", (test or {}).get("name", ""))
        c1, c2 = st.columns(2)
        category = c1.text_input("Category", (test or {}).get("category") or "")
        sample_type = c2.text_input("Sample type *", (test or {}).get("sample_type", ""))
        st.markdown("**Parameters**")
        st.caption("Numeric results are flagged against low/high. Use reference text (e.g. Negative) for non-numeric results. "
                   "Edits apply to new results only; existing reports keep the values they were issued with.")
        params = st.data_editor(
            pd.DataFrame((test or {}).get("parameters") or [{"code": "", "name": "", "unit": None, "ref_low": None,
                                                              "ref_high": None, "ref_text": None}], columns=PARAM_COLUMNS),
            num_rows="dynamic", hide_index=True,
            column_config={"code": st.column_config.TextColumn("Code", required=True),
                           "name": st.column_config.TextColumn("Name", required=True, width="medium"),
                           "unit": "Unit", "ref_low": st.column_config.NumberColumn("Low"),
                           "ref_high": st.column_config.NumberColumn("High"), "ref_text": "Reference text"})
        active = st.toggle("Active (can be ordered)", (test or {}).get("is_active", True)) if test else True
        saved = st.form_submit_button("Save", type="primary")
    if saved:
        clean = lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "" else v
        body = {"code": code.strip(), "name": name.strip(), "category": category.strip() or None,
                "sample_type": sample_type.strip(), "is_active": active,
                "parameters": [{k: clean(r.get(k)) for k in PARAM_COLUMNS} for r in params.to_dict("records")
                               if clean(r.get("code")) or clean(r.get("name"))]}
        ok = run(lambda: api.put(f"/lab/tests/{test['id']}", body) if test else api.post("/lab/tests", body), "Test saved.")
        if ok:
            st.rerun()
        for good, msg in st.session_state.pop("flash", []):
            (st.success if good else st.error)(msg)


if can_edit and st.button("Add test", type="primary", icon=":material/add:"):
    test_dialog(None)

st.dataframe([{"Code": t["code"], "Test": t["name"], "Category": t.get("category") or "", "Sample": t["sample_type"],
               "Parameters (unit, reference range)": "; ".join(
                   f"{p['name']}{' (' + p['unit'] + ')' if p.get('unit') else ''}: {format_range(p) or '—'}" for p in t["parameters"]),
               "Active": t["is_active"]} for t in tests], hide_index=True, alt="Laboratory test catalogue")

if can_edit and tests:
    by_id = {t["id"]: t for t in tests}
    with st.container(horizontal=True, vertical_alignment="bottom"):
        chosen = st.selectbox("Edit test", list(by_id), index=None, placeholder="Choose…",
                              format_func=lambda i: f"{by_id[i]['code']} · {by_id[i]['name']}")
        if st.button("Edit", icon=":material/edit:", disabled=chosen is None):
            test_dialog(by_id[chosen])
