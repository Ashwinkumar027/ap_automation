"""
Multi-Entity Security & Delegation Service
Enforces strict company-level authorization and dynamic HoD/Approver delegations.
"""
from typing import List, Optional
import frappe
from ap_automation.exceptions import APSecurityError


def get_user_authorized_companies(user: Optional[str] = None) -> List[str]:
    """
    Returns the list of Group Companies that a specific user has permission to access.
    Admins and System Managers have global access to all registered entities.
    """
    user = user or frappe.session.user
    roles = frappe.get_roles(user)

    if "Administrator" in roles or "System Manager" in roles:
        return [c["name"] for c in frappe.get_all("Company", fields=["name"])]

    # Fetch User Permission restrictions
    user_perms = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Company"},
        fields=["for_value"]
    )
    if user_perms:
        return [p["for_value"] for p in user_perms]

    # Fallback to default company or all if unrestricted
    default_company = frappe.db.get_value("User", user, "company")
    if default_company:
        return [default_company]

    return [c["name"] for c in frappe.get_all("Company", fields=["name"])]


def validate_company_access(company: str, user: Optional[str] = None) -> bool:
    """
    Validates whether the user is permitted to create, view, or approve vouchers for this entity.
    """
    user = user or frappe.session.user
    allowed = get_user_authorized_companies(user)
    if company not in allowed:
        raise APSecurityError(
            f"Access Denied: User '{user}' is not authorized to process vouchers for company '{company}'."
        )
    return True


def resolve_acting_approver(primary_approver: str) -> str:
    """
    Resolves acting approver if the primary manager is on approved leave.
    Integrates seamlessly with HRMS Leave Application.
    """
    if not primary_approver:
        return primary_approver

    # Check if HRMS Leave Application exists and employee is currently on leave
    today = frappe.utils.nowdate()
    on_leave = frappe.db.exists(
        "Leave Application",
        {
            "user": primary_approver,
            "status": "Approved",
            "from_date": ["<=", today],
            "to_date": [">=", today]
        }
    )
    if on_leave:
        # Check if user has an active Delegation rule
        delegated_user = frappe.db.get_value(
            "User", primary_approver, "reports_to"
        )
        if delegated_user:
            return delegated_user

    return primary_approver
