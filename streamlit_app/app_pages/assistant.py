import pandas as pd
import streamlit as st

import api
from ui import fmt_date, load, patient_banner, query_id, show_error

QUESTIONS = ["What were the previous laboratory reports?", "What medicines were previously prescribed?",
             "Show the latest recorded consultation.", "Summarize the available medical history."]
SECTIONS = ["consultations", "conditions", "medications", "laboratory", "observations", "external_records"]

patient_id = query_id()
patient = load(lambda: api.get(f"/patients/{patient_id}"))
overview = load(lambda: api.get(f"/assistant/patients/{patient_id}/overview"))
answers_key, summary_key = f"assistant_answers_{patient_id}", f"assistant_summary_{patient_id}"
st.session_state.setdefault(answers_key, [])


def cite(ids: list[str], sources: dict) -> str:
    return " ".join(f"`{i}{' · ' + fmt_date(sources[i]['date']) if sources.get(i, {}).get('date') else ''}`" for i in ids)


def statement(s: dict, sources: dict) -> None:
    kind = ":green-badge[Documented]" if s.get("kind") == "documented_fact" else ":orange-badge[AI interpretation]"
    st.markdown(f"{kind} {s['text']} {cite(s.get('source_ids', []), sources)}")


patient_banner(patient)
st.info("Reads only records you are allowed to see. It does not diagnose, prescribe or change records; every statement "
        "links to its source.", icon=":material/info:")
sources = {**overview.get("sources", {}), **(st.session_state.get(summary_key) or {}).get("sources", {})}

left, right = st.columns([3, 2])
with left:
    with st.container(border=True):
        st.markdown("**Ask about this patient's records**")
        with st.form("assistant_ask", border=False, clear_on_submit=True):
            question = st.text_input("Question")
            asked = st.form_submit_button("Ask", type="primary", icon=":material/send:")
        picked = st.pills("Suggestions", QUESTIONS, key=f"assistant_pick_{patient_id}")
        to_ask = question.strip() if asked and len(question.strip()) > 2 else None
        if picked and st.session_state.get("assistant_last_pick") != picked:
            st.session_state.assistant_last_pick = picked
            to_ask = picked
        if to_ask:
            with st.spinner("Reading the records…"):
                try:
                    answer = api.post(f"/assistant/patients/{patient_id}/ask", {"question": to_ask})
                except api.ApiError as exc:
                    show_error(exc)
                else:
                    st.session_state[answers_key].insert(0, (to_ask, answer))
        for q, answer in st.session_state[answers_key]:
            with st.container(border=True):
                st.markdown(f"**{q}**")
                if answer.get("information_unavailable"):
                    st.warning(f"Not available in the records: {answer.get('unavailable_reason')}")
                for s in answer.get("statements", []):
                    statement(s, {**sources, **answer.get("sources", {})})
                if answer.get("removed_unsupported"):
                    st.caption(f"{answer['removed_unsupported']} statement(s) without valid sources were removed.")

    with st.container(border=True):
        summary = st.session_state.get(summary_key)
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown("**Medical history summary**")
            if st.button("Regenerate" if summary else "Generate", icon=":material/auto_awesome:"):
                with st.spinner("Summarising…"):
                    try:
                        st.session_state[summary_key] = api.post(f"/assistant/patients/{patient_id}/summary")
                    except api.ApiError as exc:
                        show_error(exc)
                    else:
                        st.rerun()
        if not summary:
            st.caption("Generate an AI summary of the records you can access.")
        else:
            for k in SECTIONS:
                if summary.get(k):
                    st.markdown(f"**{k.replace('_', ' ').capitalize()}**")
                    for s in summary[k]:
                        statement(s, sources)
            if summary.get("missing_information"):
                st.info("Missing information: " + "; ".join(summary["missing_information"]))
            st.caption(f"Based on {summary.get('records_considered')} record(s)"
                       + (f"; {summary['records_omitted']} older record(s) not included" if summary.get("records_omitted") else "")
                       + (f". {summary['removed_unsupported']} unsupported statement(s) removed." if summary.get("removed_unsupported") else "."))

with right:
    with st.container(border=True):
        st.markdown("**Timeline**")
        if not overview.get("timeline"):
            st.caption("No records you can access.")
        for t in overview.get("timeline", []):
            st.markdown(f"**{fmt_date(t['date'])}** · {t['type']} · {t['source']}" + (f" · {t['author']}" if t.get("author") else ""))
    with st.container(border=True):
        st.markdown("**Laboratory results over time**")
        if not overview.get("lab_trends"):
            st.caption("No test appears more than once.")
        for t in overview.get("lab_trends", []):
            unit = (t["points"][0].get("unit") or "") if t.get("points") else ""
            st.markdown(f"**{t['test']}**" + (f" · change {t['change']:+g} {unit}" if t.get("comparable") else f" · {t.get('note') or ''}"))
            if t.get("comparable"):
                st.line_chart(pd.DataFrame({"Date": [pd.to_datetime(p["date"]) for p in t["points"]],
                                            t["test"]: [p["value"] for p in t["points"]]}), x="Date", y=t["test"], height=150,
                              alt=f"{t['test']} over time")
            else:
                st.caption(" · ".join(f"{fmt_date(p['date'])}: {p.get('value') or p.get('value_text')} {p.get('unit') or ''}"
                                      for p in t["points"]))
