import api
from staff_admin import staff_section
from ui import can, load

roles = load(lambda: api.get("/roles"))
staff_section("/staff", "/staff", "/staff", roles, can("staff:manage"), "staff")
