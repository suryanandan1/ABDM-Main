import pandas as pd
import streamlit as st

import api
from ui import (DOCUMENT_TYPES, FHIR_RECORD, can, fmt_datetime, load, patient_banner, patient_picker, query_id, reason_dialog,
                run, status_badge, user)

LISTS = {
    "diagnoses": ("Diagnoses (as documented)", ["text", "icd10_code"]),
    "allergies": ("Allergies", ["substance", "reaction"]),
    "vitals": ("Vital signs and observations", ["name", "value", "unit"]),
    "medications": ("Medicines", ["name", "dosage", "route", "frequency", "duration", "quantity", "instructions"]),
    "lab_results": ("Laboratory results", ["test_name", "value", "unit", "reference_range", "flag", "panel_name"]),
    "immunizations": ("Immunizations", ["vaccine", "date", "dose_number", "lot_number"]),
}
FOCUS = {"prescription": ["medications", "diagnoses"], "lab_report": ["lab_results", "summary"],
         "opd_consultation": ["encounter", "diagnoses", "vitals", "medications"],
         "discharge_summary": ["encounter", "diagnoses", "medications"], "immunization": ["immunizations"],
         "wellness": ["vitals"], "clinical_note": ["summary", "encounter"], "other": ["summary"]}
REVIEW = ["pending", "accepted", "rejected", "edited"]

doc_id = query_id()
doc = load(lambda: api.get(f"/documents/{doc_id}"))
editable = can("document:write") and doc["status"] in ("draft", "rejected") and doc["extraction_status"] != "pending"
record = doc.get("data")


def humanize(key: str) -> str:
    return (key[0].upper() + key[1:]).replace("_", " ").replace("icd10", "ICD-10")


def provenance(f: dict) -> str:
    if f.get("review") == "rejected":
        return "Rejected"
    if f.get("value") is None:
        return "Missing"
    if f.get("source") == "manual":
        return "Manual"
    pct = round((f.get("confidence") or 0) * 100)
    return f"AI {pct}%" + (" ✓" if f.get("review") == "accepted" else " ⚠ check" if f.get("status") == "uncertain" else "")


def manual(value) -> dict:
    v = None if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "" else str(value).strip()
    return {"value": v, "confidence": None, "evidence": None, "source": "manual", "status": "extracted" if v else "missing",
            "review": "edited" if v else "pending"}


def field_table(fields: dict[str, dict], key: str) -> dict[str, dict]:
    """Single fields (a group such as patient/doctor/encounter): one row per field, editable value and review."""
    names = [k for k, f in fields.items() if isinstance(f, dict) and "review" in f]
    df = pd.DataFrame([{"Field": humanize(k), "Value": fields[k].get("value"), "From": provenance(fields[k]),
                        "Evidence": fields[k].get("evidence") or "", "Review": fields[k].get("review")} for k in names])
    edited = st.data_editor(df, hide_index=True, disabled=not editable or ["Field", "From", "Evidence"], key=key,
                            column_config={"Value": st.column_config.TextColumn("Value", width="large"),
                                           "Review": st.column_config.SelectboxColumn("Review", options=REVIEW, required=True,
                                                                                      help="Accept or reject an AI suggestion")})
    out = {}
    for name, (_, row) in zip(names, edited.iterrows()):
        original = fields[name]
        new_value = None if pd.isna(row["Value"]) or str(row["Value"]).strip() == "" else str(row["Value"])
        out[name] = manual(new_value) if new_value != original.get("value") else {**original, "review": row["Review"]}
    return out


def list_table(rows: list[dict], keys: list[str], key: str) -> list[dict]:
    """Repeating rows (medicines, lab results, ...): one row per item; ticking 'Accept AI values' accepts its AI fields."""
    df = pd.DataFrame([{**{k: r.get(k, {}).get("value") for k in keys},
                        "From": ", ".join(sorted({provenance(r[k]) for k in keys if k in r and r[k].get("value") is not None})),
                        "Accept AI values": all(r[k].get("review") != "pending" or r[k].get("source") != "ai" for k in keys if k in r)}
                       for r in rows], columns=[*keys, "From", "Accept AI values"])
    edited = st.data_editor(df, hide_index=True, num_rows="dynamic" if editable else "fixed",
                            disabled=not editable or ["From"], key=key,
                            column_config={k: st.column_config.TextColumn(humanize(k)) for k in keys})
    out = []
    for index, row in edited.iterrows():
        original = rows[index] if isinstance(index, int) and index < len(rows) else None
        item = {}
        for k in keys:
            value = None if pd.isna(row[k]) or str(row[k]).strip() == "" else str(row[k])
            f = (original or {}).get(k)
            if f is None or value != f.get("value"):
                item[k] = manual(value)
            elif row["Accept AI values"] and f.get("source") == "ai" and f.get("review") == "pending":
                item[k] = {**f, "review": "accepted"}
            else:
                item[k] = f
        if any(item[k]["value"] for k in keys):
            out.append(item)
    return out


# ---------- header ----------
with st.container(horizontal=True, vertical_alignment="center"):
    st.subheader(doc["file_name"], anchor=False)
    status_badge(doc["status"])
    st.badge({"pending": "AI extracting…", "completed": "Extracted", "failed": "Manual entry"}.get(doc["extraction_status"], ""),
             color="blue" if doc["extraction_status"] == "pending" else "gray")
    if doc.get("fhir_record_id") and can("fhir:read"):
        st.page_link(FHIR_RECORD, label="FHIR preview", query_params={"id": str(doc["fhir_record_id"])}, icon=":material/data_object:")
    if editable and st.button("Cancel document", icon=":material/cancel:"):
        reason_dialog("Cancel document", f"/documents/{doc_id}/cancel", "Cancelled.")
    if doc["status"] == "pending_approval" and can("document:approve") and user().get("doctor_id"):
        if st.button("Return for correction", icon=":material/undo:"):
            reason_dialog("Return document for correction", f"/documents/{doc_id}/reject", "Returned for correction.")
        if st.button("Approve", type="primary", icon=":material/verified:"):
            run(lambda: api.post(f"/documents/{doc_id}/approve"), "Approved. FHIR bundle generated.")
            st.rerun()
if doc.get("status_reason"):
    st.warning(f"{'Returned for correction' if doc['status'] == 'rejected' else 'Cancelled'}: {doc['status_reason']}")
if doc["extraction_status"] == "failed":
    st.warning(f"AI extraction failed ({doc.get('extraction_error')}). Enter the information manually.")
    if editable and st.button("Try AI extraction again", icon=":material/auto_awesome:"):
        run(lambda: api.post(f"/documents/{doc_id}/extract"), "Extraction started.")
        st.rerun()

left, right = st.columns([1, 1])
with left, st.container(border=True, height=780):
    try:
        data = api.get_bytes(f"/documents/{doc_id}/file")
    except api.ApiError as exc:
        st.warning(str(exc))
    else:
        if doc["content_type"] == "application/pdf":
            try:
                st.pdf(data, height=740, alt=doc["file_name"])
            except Exception:  # st.pdf needs the optional streamlit-pdf package
                st.download_button("Download PDF", data, doc["file_name"], "application/pdf", icon=":material/download:")
                if doc.get("text"):
                    st.text(doc["text"])
        elif doc["content_type"].startswith("image/"):
            st.image(data, alt=doc["file_name"])
        else:
            st.text(doc.get("text") or data.decode("utf-8", errors="replace"))

with right:
    if doc["extraction_status"] == "pending":
        @st.fragment(run_every=3)
        def wait_for_extraction() -> None:
            st.info("The AI is reading the document. This page refreshes when it finishes.", icon=":material/hourglass_top:")
            if api.get(f"/documents/{doc_id}")["extraction_status"] != "pending":
                st.rerun(scope="app")
        wait_for_extraction()
        st.stop()

    with st.container(border=True):
        try:  # roles without doctor:read (lab technicians) see the field without the list, as in React
            doctors = api.get("/doctors", is_active=True, page_size=100)["items"]
        except api.ApiError:
            doctors = [doc["author_doctor"]] if doc.get("author_doctor") else []
        c1, c2 = st.columns(2)
        types = list(DOCUMENT_TYPES)
        new_type = c1.selectbox("Document type", types, index=types.index(doc["document_type"]), format_func=DOCUMENT_TYPES.get,
                                disabled=not editable, key=f"doctype_{doc_id}")
        doctor_ids = [d["id"] for d in doctors]
        current_doctor = (doc.get("author_doctor") or {}).get("id")
        new_doctor = c2.selectbox("Responsible doctor", doctor_ids,
                                  index=doctor_ids.index(current_doctor) if current_doctor in doctor_ids else None,
                                  format_func=lambda i: next(d["full_name"] for d in doctors if d["id"] == i),
                                  disabled=not editable, placeholder="Choose…", key=f"docdoc_{doc_id}")
        if editable and (new_type != doc["document_type"] or (new_doctor and new_doctor != current_doctor)):
            changes = {}
            if new_type != doc["document_type"]:
                changes["document_type"] = new_type
            if new_doctor and new_doctor != current_doctor:
                changes["author_doctor_id"] = new_doctor
            run(lambda: api.put(f"/documents/{doc_id}", changes), "Saved.")
            st.rerun()
        if doc.get("patient"):
            patient_banner(doc["patient"])
            if editable and st.button("Change patient", icon=":material/swap_horiz:"):
                run(lambda: api.put(f"/documents/{doc_id}", {"patient_id": None}), "Patient unlinked.")
                st.rerun()
        elif editable:
            chosen = patient_picker(f"doc_patient_{doc_id}", "Link patient")
            if chosen and st.button("Link this patient", icon=":material/link:"):
                run(lambda: api.put(f"/documents/{doc_id}", {"patient_id": chosen["id"]}), "Patient linked.")
                st.rerun()
        else:
            st.caption("No patient linked.")
        for w in doc.get("warnings") or []:
            st.warning(w)
        if doc.get("requirements") and editable:
            st.info("Before submitting:\n" + "\n".join(f"- {r}" for r in doc["requirements"]))
        counts = doc.get("review_counts") or {}
        with st.container(horizontal=True):
            st.badge(f"{counts.get('ai', 0)} from AI", color="green")
            st.badge(f"{counts.get('manual', 0)} entered manually", color="blue")
            st.badge(f"{counts.get('uncertain_pending', 0)} low-confidence to review", color="orange")
            if doc.get("ai_model"):
                st.badge(f"Model: {doc['ai_model']}", color="gray")
        if doc.get("approved_by_name"):
            st.caption(f"Approved by {doc['approved_by_name']} on {fmt_datetime(doc['approved_at'])}")

    if record:
        focus = FOCUS.get(doc["document_type"], ["summary"])
        new_record = dict(record)
        with st.expander("Document date, conclusion and notes", expanded="summary" in focus):
            summary = field_table({k: record[k] for k in ("document_date", "report_conclusion", "notes") if k in record},
                                  f"sum_{doc_id}")
            new_record.update(summary)
        for key, title in (("patient", "Patient details on the document"), ("doctor", "Doctor details on the document"),
                           ("encounter", "Visit and clinical notes")):
            if isinstance(record.get(key), dict):
                with st.expander(title, expanded=key in focus):
                    if key == "patient":
                        st.caption("Used to check the linked patient. FHIR uses the registered patient record.")
                    new_record[key] = field_table(record[key], f"{key}_{doc_id}")
        for key, (title, keys) in LISTS.items():
            if isinstance(record.get(key), list):
                with st.expander(f"{title} ({len(record[key])})", expanded=key in focus):
                    new_record[key] = list_table(record[key], keys, f"{key}_{doc_id}")

        if editable:
            dirty = new_record != record
            with st.container(horizontal=True):
                if st.button("Save", disabled=not dirty, icon=":material/save:"):
                    run(lambda: api.put(f"/documents/{doc_id}", {"data": new_record}), "Saved.")
                    st.rerun()
                if st.button("Submit for approval", type="primary", icon=":material/send:"):
                    ok = run(lambda: api.put(f"/documents/{doc_id}", {"data": new_record})) if dirty else True
                    if ok:
                        run(lambda: api.post(f"/documents/{doc_id}/submit"), "Submitted for approval.")
                    st.rerun()
