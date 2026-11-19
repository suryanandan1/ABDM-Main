# Streamlit frontend (trial)

A second frontend for the same FastAPI backend. It runs next to the React app and changes nothing in it or in the
backend; both can be used at the same time against the same database.

## Run

```powershell
# backend first (as usual), then:
cd E:\project\abdm-main\streamlit_app
.\.venv\Scripts\Activate.ps1
streamlit run streamlit_app.py          # http://localhost:8501
```

Backend somewhere else: `$env:ABDM_API_URL = "http://host:port/api"` before `streamlit run`.
First time on a new machine: `python -m venv .venv` and `.\.venv\Scripts\pip install -r requirements.txt`.

## Layout

| Path | What |
|---|---|
| `streamlit_app.py` | Sign-in gate, sidebar menu filtered by the user's permissions (same rules as React `Layout.tsx`), hidden detail pages |
| `api.py` | Backend client (Bearer token per Streamlit session; back to sign-in when the session ends) |
| `ui.py` | Shared helpers: formatting, status badges, patient search, reason dialog, messages |
| `patient_form.py`, `staff_admin.py` | Forms shared by several pages |
| `app_pages/` | One file per page. Detail pages open with `?id=` like React routes (`patient`, `consultation`, `prescription`, `lab_order`, `document`, `fhir_record`, `assistant`, `network_hospital`) |

## Differences from the React app

- A row is opened with an **Open …** selector under each table instead of clicking the row.
- Diagnoses, medicines, lab parameters and AI-extracted fields are edited in editable tables.
- Buttons whose backend endpoints do not exist are left out (React HIP: discover/link-init/link-confirm and the
  transaction log; FHIR "regenerate" uses the existing generate endpoint).
- PDF documents render with `st.pdf` when the optional `streamlit[pdf]` extra is installed; otherwise they can be
  downloaded and their text is shown.
