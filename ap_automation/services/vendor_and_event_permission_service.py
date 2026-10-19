from typing import Optional
import frappe

ACCOUNTS_GLOBAL_ROLES = {
    "System Manager",
    "Administrator",
    "Accounts L1 Auditor",
    "Accounts Director",
    "Accounts Manager",
    "Payment Releaser",
}


def is_accounts_user(user: Optional[str] = None) -> bool:
    if not user:
        user = frappe.session.user
    if user == "Administrator":
        return True
    user_roles = set(frappe.get_roles(user))
    if "System Manager" in user_roles:
        return True
    return bool(user_roles.intersection(ACCOUNTS_GLOBAL_ROLES))


# ==============================================================================
# 1. LANE 3: VENDOR INVOICE PERMISSION HOOKS
# ==============================================================================

def get_vendor_invoice_permission_query_conditions(user: Optional[str] = None) -> str:
    """
    Accounts team sees ALL vendor invoice claims.
    All other users (Receptionist, Admin, Employee, Purchase User)
    can ONLY see claims created by themselves or assigned to them for approval.
    """
    if not user:
        user = frappe.session.user

    if is_accounts_user(user):
        return ""

    escaped_user = frappe.db.escape(user)
    return f"""(
        `tabVendor Invoice Claim`.`owner` = {escaped_user}
        OR `tabVendor Invoice Claim`.`designated_approver` = {escaped_user}
        OR `tabVendor Invoice Claim`.`manager_approver` = {escaped_user}
        OR `tabVendor Invoice Claim`.`director_approver` = {escaped_user}
        OR `tabVendor Invoice Claim`.`hod_approver` = {escaped_user}
    )"""


def has_vendor_invoice_permission(doc, user: Optional[str] = None, ptype: str = "read") -> Optional[bool]:
    if not user:
        user = frappe.session.user
    if not doc or isinstance(doc, str):
        return None

    if is_accounts_user(user):
        return True

    # Creator
    if getattr(doc, "owner", None) == user:
        return True

    # Assigned Approver
    for approver_field in ["designated_approver", "manager_approver", "director_approver", "hod_approver"]:
        if getattr(doc, approver_field, None) == user:
            return True

    return False


def get_admin_weekly_vendor_permission_query_conditions(user: Optional[str] = None) -> str:
    """
    Accounts team sees ALL Admin Weekly Vendor Claims.
    Admins / Receptionists / Employees only see claims created by themselves or assigned to them.
    """
    if not user:
        user = frappe.session.user

    if is_accounts_user(user):
        return ""

    escaped_user = frappe.db.escape(user)
    return f"""(
        `tabAdmin Weekly Vendor Claim`.`owner` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`prepared_by` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`admin_l1_approver` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`admin_l2_approver` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`director_approver` = {escaped_user}
    )"""


def has_admin_weekly_vendor_permission(doc, user: Optional[str] = None, ptype: str = "read") -> Optional[bool]:
    if not user:
        user = frappe.session.user
    if not doc or isinstance(doc, str):
        return None

    if is_accounts_user(user):
        return True

    if getattr(doc, "owner", None) == user or getattr(doc, "prepared_by", None) == user:
        return True

    for approver_field in ["admin_l1_approver", "admin_l2_approver", "director_approver"]:
        if getattr(doc, approver_field, None) == user:
            return True

    return False


# ==============================================================================
# 2. LANE 4: EVENT SPENDS PERMISSION HOOKS
# ==============================================================================

def get_event_advance_permission_query_conditions(user: Optional[str] = None) -> str:
    """
    Accounts team sees ALL Event Advance Requests.
    Receptionists, Admins, and Employees ONLY see requests created by themselves
    or where they are designated SPOC / Business Head.
    """
    if not user:
        user = frappe.session.user

    if is_accounts_user(user):
        return ""

    escaped_user = frappe.db.escape(user)
    return f"""(
        `tabEvent Advance Request`.`owner` = {escaped_user}
        OR `tabEvent Advance Request`.`spoc` = {escaped_user}
        OR `tabEvent Advance Request`.`approved_by_business_head` = {escaped_user}
    )"""


def has_event_advance_permission(doc, user: Optional[str] = None, ptype: str = "read") -> Optional[bool]:
    if not user:
        user = frappe.session.user
    if not doc or isinstance(doc, str):
        return None

    if is_accounts_user(user):
        return True

    return bool(
        getattr(doc, "owner", None) == user
        or getattr(doc, "spoc", None) == user
        or getattr(doc, "approved_by_business_head", None) == user
    )


def get_event_expense_permission_query_conditions(user: Optional[str] = None) -> str:
    if not user:
        user = frappe.session.user

    if is_accounts_user(user):
        return ""

    escaped_user = frappe.db.escape(user)
    return f"""(
        `tabEvent Expense Claim`.`owner` = {escaped_user}
        OR `tabEvent Expense Claim`.`spoc` = {escaped_user}
    )"""


def has_event_expense_permission(doc, user: Optional[str] = None, ptype: str = "read") -> Optional[bool]:
    if not user:
        user = frappe.session.user
    if not doc or isinstance(doc, str):
        return None

    if is_accounts_user(user):
        return True

    return bool(
        getattr(doc, "owner", None) == user
        or getattr(doc, "spoc", None) == user
    )


def get_event_settlement_permission_query_conditions(user: Optional[str] = None) -> str:
    if not user:
        user = frappe.session.user

    if is_accounts_user(user):
        return ""

    escaped_user = frappe.db.escape(user)
    return f"""(
        `tabEvent Settlement`.`owner` = {escaped_user}
        OR `tabEvent Settlement`.`spoc` = {escaped_user}
    )"""


def has_event_settlement_permission(doc, user: Optional[str] = None, ptype: str = "read") -> Optional[bool]:
    if not user:
        user = frappe.session.user
    if not doc or isinstance(doc, str):
        return None

    if is_accounts_user(user):
        return True

    return bool(
        getattr(doc, "owner", None) == user
        or getattr(doc, "spoc", None) == user
    )
