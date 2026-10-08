import frappe

def inspect_all_users():
    users = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, fields=["name", "email", "full_name"])
    print("=== ACTIVE SYSTEM USERS & ROLES ===")
    for u in users:
        roles = frappe.get_roles(u.name)
        emp = frappe.db.get_value("Employee", {"user_id": u.name}, ["name", "employee_name", "reports_to"], as_dict=True)
        print(f"User: {u.name} | Roles: {roles} | Employee: {emp}")

    # Check Custom DocPerm and standard DocPerm on Pre Travel Request
    print("\n=== PRE TRAVEL REQUEST DOCPERM ===")
    perms = frappe.get_all("DocPerm", filters={"parent": "Pre Travel Request"}, fields=["*"])
    for p in perms:
        print(f"Role: {p.role} | Create: {p.create} | Read: {p.read} | Write: {p.write}")

    custom_perms = frappe.get_all("Custom DocPerm", filters={"parent": "Pre Travel Request"}, fields=["*"])
    print("\n=== PRE TRAVEL REQUEST CUSTOM DOCPERM ===")
    for cp in custom_perms:
        print(f"Role: {cp.role} | Create: {cp.create} | Read: {cp.read} | Write: {cp.write}")

if __name__ == "__main__":
    inspect_all_users()
