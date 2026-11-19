"""Patient demographics form shared by registration and editing (React: components/PatientForm.tsx)."""
from datetime import date

import streamlit as st

from ui import GENDERS, to_date

TEXT_FIELDS = ["full_name", "mobile", "address_line", "city", "state", "pincode", "abha_number", "abha_address",
               "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation"]


def patient_form(key: str, patient: dict | None, submit_label: str) -> dict | None:
    """Render the form; returns the payload when submitted, otherwise None."""
    p = patient or {}
    has_dob = bool(p.get("date_of_birth")) or not patient
    dob_mode = st.segmented_control("Birth date", ["Date of birth", "Age (DOB unknown)"],
                                    default="Date of birth" if has_dob else "Age (DOB unknown)", key=f"{key}_dobmode")
    with st.form(key):
        st.markdown("**Basic details**")
        c1, c2, c3 = st.columns([2, 1, 1])
        full_name = c1.text_input("Full name *", p.get("full_name", ""))
        genders = list(GENDERS)
        gender = c2.selectbox("Gender *", genders, index=genders.index(p["gender"]) if p.get("gender") in genders else None,
                              format_func=GENDERS.get, placeholder="Choose…")
        mobile = c3.text_input("Mobile number *", p.get("mobile", ""), placeholder="10-digit mobile")
        if dob_mode == "Age (DOB unknown)":
            age = st.number_input("Age in years *", 0, 130,
                                  value=date.today().year - p["year_of_birth"] if p.get("year_of_birth") else None)
            dob = None
        else:
            dob = st.date_input("Date of birth *", to_date(p.get("date_of_birth")), min_value=date(1890, 1, 1),
                                max_value=date.today(), format="DD/MM/YYYY")
            age = None

        st.markdown("**Address**")
        address_line = st.text_input("Address", p.get("address_line") or "")
        c1, c2, c3 = st.columns(3)
        city = c1.text_input("City / Town", p.get("city") or "")
        state = c2.text_input("State", p.get("state") or "")
        pincode = c3.text_input("Pincode", p.get("pincode") or "")

        st.markdown("**ABHA (optional)**")
        st.caption("Entered ABHA details stay unverified until authorised health information staff verify them.")
        c1, c2 = st.columns(2)
        abha_number = c1.text_input("ABHA number", p.get("abha_number") or "", placeholder="91-1234-5678-9012")
        abha_address = c2.text_input("ABHA address", p.get("abha_address") or "", placeholder="name@abdm")

        st.markdown("**Emergency contact**")
        c1, c2, c3 = st.columns([5, 4, 3])
        ec_name = c1.text_input("Name", p.get("emergency_contact_name") or "")
        ec_phone = c2.text_input("Mobile number", p.get("emergency_contact_phone") or "")
        ec_relation = c3.text_input("Relation", p.get("emergency_contact_relation") or "")
        submitted = st.form_submit_button(submit_label, type="primary")

    if not submitted:
        return None
    values = {"full_name": full_name, "mobile": mobile, "address_line": address_line, "city": city, "state": state,
              "pincode": pincode, "abha_number": abha_number, "abha_address": abha_address,
              "emergency_contact_name": ec_name, "emergency_contact_phone": ec_phone,
              "emergency_contact_relation": ec_relation}
    payload = {k: (v.strip() or None) for k, v in values.items()}
    payload["gender"] = gender
    payload["date_of_birth"] = dob.isoformat() if dob else None
    payload["age"] = int(age) if age is not None else None
    missing = [label for label, ok in (("full name", payload["full_name"]), ("gender", gender), ("mobile", payload["mobile"]),
                                       ("date of birth or age", dob or age is not None)) if not ok]
    if missing:
        st.error("Please enter: " + ", ".join(missing), icon=":material/error:")
        return None
    return payload
