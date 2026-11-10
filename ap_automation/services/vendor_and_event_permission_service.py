from typing import Optional
import frappe

ACCOUNTS_GLOBAL_ROLES = {
    "System Manager",
    "Administrator",
    "Accounts L1 Auditor",
    "Accounts Director",
    "Accounts Manager",
    "Payment Releaser",
    "AP Director",
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
    Admins / Receptionists / Approvers only see claims created by themselves or assigned to them.
    """
    if not user:
        user = frappe.session.user

    if is_accounts_user(user):
        return ""

    escaped_user = frappe.db.escape(user)
    return f"""(
        `tabAdmin Weekly Vendor Claim`.`owner` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`prepared_by` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`designated_approver` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`admin_l1_approver` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`admin_l2_approver` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`accounts_l1_approver` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`accounts_l2_approver` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`director_approver` = {escaped_user}
        OR `tabAdmin Weekly Vendor Claim`.`payment_releaser` = {escaped_user}
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

    for approver_field in [
        "designated_approver",
        "admin_l1_approver",
        "admin_l2_approver",
        "accounts_l1_approver",
        "accounts_l2_approver",
        "director_approver",
        "payment_releaser"
    ]:
        if getattr(doc, approver_field, None) == user:
            return True

    return False


# ==============================================================================
# 2. LANE 4: EVENT SPENDS PERMISSION HOOKS
# ==============================================================================

def get_event_master_permission_query_conditions(user: Optional[str] = None) -> str:
    """
    Accounts/Finance/Directors see all Event Masters.
    Regular employees/SPOCs see ONLY Event Masters they created or where they are designated Event SPOC.
    """
    if not user:
        user = frappe.session.user

    if is_accounts_user(user):
        return ""

    user_roles = set(frappe.get_roles(user)) if user else set()
    if user_roles.intersection({"Director", "AP Director", "Business Head", "Business Head Approver"}):
        return ""

    escaped_user = frappe.db.escape(user)
    return f"""(
        `tabEvent Master`.`owner` = {escaped_user}
        OR `tabEvent Master`.`event_spoc` = {escaped_user}
    )"""


def has_event_master_permission(doc, user: Optional[str] = None, ptype: str = "read") -> Optional[bool]:
    if not user:
        user = frappe.session.user
    if not doc or isinstance(doc, str):
        return None

    if is_accounts_user(user):
        return True

    user_roles = set(frappe.get_roles(user)) if user else set()
    if user_roles.intersection({"Director", "AP Director", "Business Head", "Business Head Approver"}):
        return True

    return bool(
        getattr(doc, "owner", None) == user
        or getattr(doc, "event_spoc", None) == user
    )


def _is_event_advance_matrix_approver(user: str) -> bool:
    """Checks if user is designated in any active Event Advance Request AP Approval Matrix."""
    if not user or not frappe.db.exists("DocType", "AP Approval Matrix"):
        return False
    rows = frappe.db.sql(
        """
        SELECT r.designated_approver
        FROM `tabAP Approval Level Rule` r
        JOIN `tabAP Approval Matrix` m ON m.name = r.parent
        WHERE m.document_lane = 'Event Advance Request' AND m.is_active = 1
        """,
        as_dict=True,
    )
    return any(r.designated_approver == user for r in rows)


def get_event_advance_permission_query_conditions(user: Optional[str] = None) -> str:
    """
    Accounts team sees ALL Event Advance Requests.
    Directors see all requests pending Director approval or already approved by them.
    SPOCs/Employees ONLY see requests created by themselves or where they are SPOC.
    """
    if not user:
        user = frappe.session.user

    if is_accounts_user(user) or _is_event_advance_matrix_approver(user):
        return ""

    escaped_user = frappe.db.escape(user)
    user_roles = set(frappe.get_roles(user)) if user else set()
    is_director = bool(user_roles.intersection({"Director", "AP Director", "Accounts Director", "Business Head", "Business Head Approver"}))

    if is_director:
        return f"""(
            `tabEvent Advance Request`.`owner` = {escaped_user}
            OR `tabEvent Advance Request`.`spoc` = {escaped_user}
            OR `tabEvent Advance Request`.`status` = 'Pending Director Approval'
            OR `tabEvent Advance Request`.`approved_by_business_head` = {escaped_user}
        )"""

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

    if is_accounts_user(user) or _is_event_advance_matrix_approver(user):
        return True

    user_roles = set(frappe.get_roles(user)) if user else set()
    is_director = bool(user_roles.intersection({"Director", "AP Director", "Accounts Director", "Business Head", "Business Head Approver"}))
    if is_director and getattr(doc, "status", "") == "Pending Director Approval":
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
