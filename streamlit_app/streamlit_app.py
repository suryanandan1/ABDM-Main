import streamlit as st

if tuple(int(x) for x in st.__version__.split(".")[:2]) < (1, 57):
    st.error(f"This app needs Streamlit 1.57 or newer, but it was started with {st.__version__}. "
             "Start it with the project's venv: `.\\.venv\\Scripts\\streamlit.exe run streamlit_app.py`")
    st.stop()

import api
import ui
from ui import can

st.set_page_config(page_title="ABDM Hospital", page_icon=":material/local_hospital:", layout="wide")

if "auth" not in st.session_state:
    st.session_state.auth = None

if st.session_state.auth is None:
    page = st.navigation([st.Page("app_pages/login.py", title="Sign in", icon=":material/login:")], position="hidden")
    page.run()
    st.stop()

user = st.session_state.auth["user"]

# Same menu and permission rules as the React app (Layout.tsx), grouped into sections.
MENU = {
    "": [
        ("portal:view", "app_pages/my_record.py", "My health record", ":material/favorite:",
         "Your details and the visits, prescriptions and lab reports your doctors approved, from every hospital."),
        ("portal:view", "app_pages/my_consents.py", "Consent requests", ":material/verified_user:",
         "Hospitals asking to see your records. Approve, deny, or revoke a consent you gave."),
        ("network:manage", "app_pages/network.py", "Hospitals", ":material/apartment:",
         "Every hospital on the network: status, ABDM IDs, administrators. Add or deactivate a hospital."),
        ("dashboard:view", "app_pages/dashboard.py", "Dashboard", ":material/dashboard:",
         "Today's counts for this hospital, recent patients and recent activity."),
        ("patient:read", "app_pages/patients.py", "Patients", ":material/group:",
         "Search this hospital's patients by name, ID, mobile or ABHA address and open their record."),
        ("patient:create", "app_pages/patient_register.py", "Register patient", ":material/person_add:",
         "Register a new patient. Possible duplicates are checked before the record is created."),
    ],
    "Clinical": [
        ("clinical:read", "app_pages/consultations.py", "Consultations", ":material/assignment:",
         "Consultations of this hospital. Start a new one, or continue a draft."),
        ("clinical:read", "app_pages/prescriptions.py", "Prescriptions", ":material/medication:",
         "Prescriptions with their approval status."),
    ],
    "Laboratory": [
        ("lab:read", "app_pages/lab_orders.py", "Lab orders", ":material/science:",
         "Lab worklist: collect samples, enter results, approve reports."),
        ("lab:read", "app_pages/lab_tests.py", "Lab catalogue", ":material/biotech:",
         "Tests that can be ordered, with parameters, units and reference ranges."),
    ],
    "Records": [
        ("document:read", "app_pages/documents.py", "AI documents", ":material/document_scanner:",
         "Upload clinical documents, review what the AI extracted, and approve them."),
        ("fhir:read", "app_pages/fhir_records.py", "FHIR records", ":material/data_object:",
         "FHIR documents generated from approved records, with HL7 validation results."),
    ],
    "ABDM": [
        ("hip:read", "app_pages/hip.py", "ABDM HIP", ":material/hub:",
         "This hospital as a Health Information Provider: verify ABHA, link records, see consents."),
        ("hiu:read", "app_pages/hiu_requests.py", "HIU requests", ":material/travel_explore:",
         "Requests this hospital sent for records held elsewhere, their status, and the simulated patient decision."),
        ("hiu:request", "app_pages/hiu_new.py", "New HIU request", ":material/add_circle:",
         "Ask a patient's consent to fetch their records from other hospitals."),
        ("hiu:records", "app_pages/hiu_records.py", "Retrieved records", ":material/folder_shared:",
         "Records received from other hospitals under consent, with a timeline and repeated lab tests."),
    ],
    "Administration": [
        ("doctor:read", "app_pages/doctors.py", "Doctors", ":material/medical_services:",
         "Doctors of this hospital and their login accounts."),
        ("staff:read", "app_pages/staff.py", "Staff", ":material/badge:",
         "Staff accounts: roles, active state, password and two-step sign-in resets."),
        ("hospital:read", "app_pages/hospital_profile.py", "Hospital profile", ":material/local_hospital:",
         "This hospital's details and ABDM identifiers."),
        ("audit:read", "app_pages/audit_logs.py", "Audit logs", ":material/history:",
         "Who did what and when, without patient details."),
    ],
}
# Detail pages: not in the menu, opened from lists with ?id=... (like /patients/5 in React).
HIDDEN = [
    ("patient:read", ui.PATIENT, "Patient"),
    ("clinical:read", ui.PATIENT_HISTORY, "Medical history"),
    ("clinical:read", ui.ASSISTANT, "Patient assistant"),
    ("clinical:read", ui.CONSULTATION, "Consultation"),
    ("clinical:read", ui.PRESCRIPTION, "Prescription"),
    ("lab:read", ui.LAB_ORDER, "Lab order"),
    ("document:read", ui.DOCUMENT, "Document review"),
    ("fhir:read", ui.FHIR_RECORD, "FHIR record"),
    ("network:manage", ui.NETWORK_HOSPITAL, "Hospital"),
]
ACCOUNT = st.Page("app_pages/account.py", title="My account", icon=":material/manage_accounts:",
                  help="Change your password, set up two-step sign-in, or sign out of every device.")

if user.get("mfa_setup_required"):
    # Same as the React app: until two-step sign-in is set up, only the account page is available.
    sections = {"": [ACCOUNT]}
else:
    sections = {}
    for section, entries in MENU.items():
        pages = [st.Page(path, title=title, icon=icon, help=help_text)
                 for permission, path, title, icon, help_text in entries if can(permission)]
        if pages:
            sections[section] = pages
    sections.setdefault("Account", []).append(ACCOUNT)
    hidden = [st.Page(path, title=title, visibility="hidden") for permission, path, title in HIDDEN if can(permission)]
    sections["Account"].extend(hidden)

with st.sidebar:
    with st.container(border=True):
        st.markdown(f"**{user['full_name']}**")
        st.caption(f"{user['role_name']} · {user.get('hospital_name') or user['username']}")
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            api.logout()
            st.rerun()

page = st.navigation(sections, position="sidebar")
st.title(page.title, anchor=False)
if user.get("mfa_setup_required"):
    st.warning("Your role must use two-step sign-in. Set it up below to continue.", icon=":material/lock:")
ui.show_flash()
page.run()
