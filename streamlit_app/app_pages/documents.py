import streamlit as st

import api
from ui import DOCUMENT, DOCUMENT_TYPES, can, flash, fmt_datetime, go, load, open_selector, pager, patient_picker, show_error, status_label

TABS = {"In review": "draft,rejected", "Awaiting approval": "pending_approval", "Approved": "approved", "All": ""}
EXTRACTION = {"pending": "AI extracting…", "completed": "Extracted", "failed": "Manual entry"}
TYPES = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
         "webp": "image/webp", "txt": "text/plain",
         "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


@st.dialog("Upload clinical document", width="large")
def upload_dialog() -> None:
    st.info("PDF (text or scanned), JPG, PNG, WEBP, DOCX or TXT, up to 20 MB. The document is sent to the configured AI "
            "provider for extraction; every value is reviewed by staff before approval.", icon=":material/info:")
    file = st.file_uploader("Document", type=list(TYPES), max_upload_size=20)
    patient = patient_picker("upload_doc", "Patient (optional)")
    st.caption("The patient can also be linked during review.")
    if st.button("Upload and extract", type="primary", disabled=file is None, icon=":material/upload_file:"):
        ext = file.name.rsplit(".", 1)[-1].lower()
        with st.spinner("Uploading…"):
            try:
                doc = api.upload("/documents", file.name, file.getvalue(), file.type or TYPES.get(ext, "application/octet-stream"),
                                 {"patient_id": patient["id"] if patient else None})
            except api.ApiError as exc:
                show_error(exc)
                return
        flash("Document uploaded.")
        go(DOCUMENT, id=doc["id"])


with st.container(horizontal=True, vertical_alignment="bottom"):
    tab = st.segmented_control("Show", list(TABS), default="In review", key="docs_tab") or "In review"
    if can("document:write") and st.button("Upload document", type="primary", icon=":material/upload_file:"):
        upload_dialog()

PAGE_SIZE = 20
result = load(lambda: api.get("/documents", status=TABS[tab] or None, page=st.session_state.get("docs_page", 1),
                              page_size=PAGE_SIZE))
items = result["items"]
st.caption(f"{result['total']} document(s)")
st.dataframe([{"#": d["id"], "Uploaded": fmt_datetime(d["created_at"]), "By": d["created_by_name"], "File": d["file_name"],
               "Type": DOCUMENT_TYPES.get(d["document_type"], d["document_type"]),
               "Patient": f"{d['patient']['full_name']} ({d['patient']['patient_code']})" if d.get("patient") else "Not linked",
               "Extraction": EXTRACTION.get(d["extraction_status"], d["extraction_status"]), "Status": status_label(d["status"])}
              for d in items], hide_index=True, alt="Clinical documents")
pager("docs_page", result["total"], PAGE_SIZE)
chosen = open_selector("Open document", items, "docs_open", lambda d: f"#{d['id']} · {d['file_name']}")
if chosen:
    go(DOCUMENT, id=chosen["id"])
