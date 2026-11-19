from datetime import date

PRIMARY = "CGH"

HOSPITALS = {
    "CGH": {"name": "City General Hospital", "city": "Mumbai", "state": "Maharashtra", "facility_type": "Hospital",
            "hip_id": "SIM_HIP_CGH", "hiu_id": "SIM_HIU_CGH"},
    "GVH": {"name": "Green Valley Multispeciality Hospital", "city": "Bengaluru", "state": "Karnataka",
            "facility_type": "Hospital", "address": "14 Lake View Road, Indiranagar", "pincode": "560038",
            "phone": "080-41000000", "hip_id": "SIM_HIP_GVH", "hiu_id": "SIM_HIU_GVH"},
    "RMC": {"name": "Riverside Medical Centre", "city": "New Delhi", "state": "Delhi", "facility_type": "Hospital",
            "address": "7 Yamuna Marg, Civil Lines", "pincode": "110054", "phone": "011-42000000",
            "hip_id": "SIM_HIP_RMC", "hiu_id": "SIM_HIU_RMC"},
}

STAFF = {
    "GVH": [
        ("gvh.admin", "Green Valley Administrator", "hospital_admin", None),
        ("gvh.shetty", "Dr. Kiran Shetty", "doctor",
         {"registration_number": "KMC-61204", "specialization": "Cardiology", "qualification": "MBBS, MD, DM",
          "department": "Cardiology"}),
        ("gvh.kulkarni", "Dr. Neha Kulkarni", "doctor",
         {"registration_number": "KMC-58817", "specialization": "Endocrinology", "qualification": "MBBS, MD",
          "department": "Medicine"}),
        ("gvh.reception", "Ravi Gowda", "receptionist", None),
        ("gvh.labtech", "Deepa Hegde", "lab_technician", None),
        ("gvh.hims", "Sanjay Murthy", "health_info_staff", None),
    ],
    "RMC": [
        ("rmc.admin", "Riverside Administrator", "hospital_admin", None),
        ("rmc.malhotra", "Dr. Vikram Malhotra", "doctor",
         {"registration_number": "DMC-70452", "specialization": "General Medicine", "qualification": "MBBS, MD",
          "department": "Medicine"}),
        ("rmc.sheikh", "Dr. Fatima Sheikh", "doctor",
         {"registration_number": "DMC-66930", "specialization": "Pulmonology", "qualification": "MBBS, MD",
          "department": "Chest Medicine"}),
        ("rmc.reception", "Pooja Arora", "receptionist", None),
        ("rmc.labtech", "Amit Chauhan", "lab_technician", None),
        ("rmc.hims", "Neelam Bhatia", "health_info_staff", None),
    ],
}

PEOPLE = [
    {"full_name": "Surya Prakash", "gender": "M", "date_of_birth": date(1990, 5, 14), "mobile": "9845012345",
     "city": "Bengaluru", "state": "Karnataka", "abha_address": "surya@abdm", "abha_number": "91100000000001",
     "hospitals": ["CGH", "GVH", "RMC"]},
    {"full_name": "Ramesh Kumar", "gender": "M", "date_of_birth": date(1978, 4, 12), "mobile": "9876543210",
     "city": "Mumbai", "state": "Maharashtra", "abha_address": "ramesh.kumar@abdm", "abha_number": "91100000000002",
     "hospitals": ["CGH", "GVH"]},
    {"full_name": "Sita Devi", "gender": "F", "date_of_birth": date(1985, 9, 3), "mobile": "9123456780",
     "city": "Pune", "state": "Maharashtra", "abha_address": "sita.devi@abdm", "abha_number": "91100000000003",
     "hospitals": ["CGH", "RMC"]},
    {"full_name": "Arjun Singh", "gender": "M", "date_of_birth": date(2012, 1, 25), "mobile": "9988776655",
     "city": "Nagpur", "state": "Maharashtra", "abha_address": "arjun.singh@abdm", "abha_number": "91100000000004",
     "hospitals": ["CGH"]},
    {"full_name": "Meera Nair", "gender": "F", "date_of_birth": date(1972, 11, 2), "mobile": "9447011223",
     "city": "Bengaluru", "state": "Karnataka", "abha_address": "meera.nair@abdm", "abha_number": "91100000000005",
     "hospitals": ["GVH", "RMC"]},
    {"full_name": "Farhan Ali", "gender": "M", "date_of_birth": date(1965, 7, 19), "mobile": "9900112233",
     "city": "Bengaluru", "state": "Karnataka", "abha_address": "farhan.ali@abdm", "abha_number": "91100000000006",
     "hospitals": ["GVH"]},
    {"full_name": "Lakshmi Iyer", "gender": "F", "date_of_birth": date(1958, 3, 8), "mobile": "9810022334",
     "city": "New Delhi", "state": "Delhi", "abha_address": "lakshmi.iyer@abdm", "abha_number": "91100000000007",
     "hospitals": ["RMC"]},
]


# ABHA accounts known to the simulated ABDM for patients registered later by hand (not created by init_db --demo).
EXTRA_ABHA = [
    {"full_name": "Priya Sharma", "gender": "F", "date_of_birth": date(1995, 3, 21), "abha_address": "priya.sharma@abdm",
     "abha_number": "91100000000008"},
    {"full_name": "Vikram Rao", "gender": "M", "date_of_birth": date(1982, 8, 9), "abha_address": "vikram.rao@abdm",
     "abha_number": "91100000000009"},
    {"full_name": "Anjali Gupta", "gender": "F", "date_of_birth": date(1978, 12, 2), "abha_address": "anjali.gupta@abdm",
     "abha_number": "91100000000010"},
]


def abha_accounts() -> dict[str, dict]:
    return {p["abha_address"]: {"name": p["full_name"], "gender": p["gender"], "yearOfBirth": p["date_of_birth"].year,
                                "abhaNumber": p["abha_number"]} for p in PEOPLE + EXTRA_ABHA}
