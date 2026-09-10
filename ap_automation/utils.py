import frappe

def check_app_permission(user: str = None) -> bool:
    """
    Colleague's Bug 2 Method:
    Dynamically verifies if the active user possesses at least one of the authorized
    roles configured on the 'AP Automation' Workspace.
    """
    if not user:
        user = frappe.session.user

    if user == "Guest":
        return False

    if user == "Administrator":
        return True

    user_roles = frappe.get_roles(user)

    # If System Manager, always allow
    if "System Manager" in user_roles:
        return True

    # Pull allowed roles dynamically from AP Automation Workspace (Single Source of Truth)
    if frappe.db.exists("Workspace", "AP Automation"):
        ws = frappe.get_doc("Workspace", "AP Automation")
        allowed_roles = [r.role for r in ws.roles]
        if not allowed_roles:
            return True
        return bool(set(user_roles).intersection(set(allowed_roles)))

    # Fallback to standard financial/desk roles
    standard_allowed = ["Accounts Manager", "Accounts User", "Employee", "Desk User"]
    return bool(set(user_roles).intersection(set(standard_allowed)))
