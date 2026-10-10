"""
Enterprise Multi-Tier Permission Engine for Employee Reimbursements & Pre-Travel.
Implements:
1. Dynamic ORM SQL Query Conditions (Desk List, Report, and API isolation).
2. Document-Level Fine-Grained Permissions (Read/Write/Approval security).
3. 4-Tier Organizational Scoping (Claimant, Reporting Manager, SPOC, Global Approver).
"""
from typing import Any, Dict, List, Optional, Tuple, Union
import frappe
from frappe.model.document import Document

# Roles that bypass document-level user restrictions and have organization-wide visibility
GLOBAL_VIEW_ROLES = {
    "System Manager",
    "Administrator",
    "Accounts L1 Auditor",
    "Accounts Director",
    "Payment Releaser",
    "Accounts Manager"
}

EMPLOYEE_EDITABLE_STATUSES = {"Draft", "Returned for Correction", "Rejected", None, ""}


def is_global_view_user(user: Optional[str] = None) -> bool:
    """Checks if the user possesses any corporate-wide audit or approval roles."""
    if not user:
        user = frappe.session.user
    if user == "Administrator":
        return True
    user_roles = set(frappe.get_roles(user))
    return bool(user_roles.intersection(GLOBAL_VIEW_ROLES))


def get_subordinate_employees_for_user(user: Optional[str] = None) -> List[str]:
    """
    Returns a list of Employee document names that report directly or indirectly to the user.
    """
    if not user:
        user = frappe.session.user

    manager_emp_names = frappe.db.get_all(
        "Employee",
        filters={"user_id": user, "status": "Active"},
        pluck="name"
    )

    if not manager_emp_names:
        return []

    subordinates = frappe.db.get_all(
        "Employee",
        filters={
            "reports_to": ["in", manager_emp_names],
            "status": "Active"
        },
        pluck="name"
    )

    return list(set(manager_emp_names + subordinates))


# ==============================================================================
# 1. EMPLOYEE REIMBURSEMENT CLAIM PERMISSION HOOKS
# ==============================================================================

def get_reimbursement_permission_query_conditions(user: Optional[str] = None) -> str:
    """
    Injected into Frappe ORM queries for 'Employee Reimbursement Claim'.
    """
    if not user:
        user = frappe.session.user

    if is_global_view_user(user):
        return ""

    own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
    subordinate_emps = get_subordinate_employees_for_user(user)
    escaped_user = frappe.db.escape(user)
    escaped_own_emp = frappe.db.escape(own_emp) if own_emp else None

    subordinate_only = [e for e in subordinate_emps if e != own_emp]

    if subordinate_only:
        formatted_sub_ids = ", ".join([frappe.db.escape(e) for e in subordinate_only])
        emp_match = f"`tabEmployee Reimbursement Claim`.`employee` = {escaped_own_emp}" if escaped_own_emp else "1=0"
        return f"""(
            `tabEmployee Reimbursement Claim`.`owner` = {escaped_user}
            OR {emp_match}
            OR (`tabEmployee Reimbursement Claim`.`employee` IN ({formatted_sub_ids}) AND `tabEmployee Reimbursement Claim`.`status` NOT IN ('Draft'))
            OR (`tabEmployee Reimbursement Claim`.`manager_user_id` = {escaped_user} AND `tabEmployee Reimbursement Claim`.`status` NOT IN ('Draft'))
        )"""
    else:
        emp_match = f"OR `tabEmployee Reimbursement Claim`.`employee` = {escaped_own_emp}" if escaped_own_emp else ""
        return f"(`tabEmployee Reimbursement Claim`.`owner` = {escaped_user} {emp_match})"


def has_reimbursement_permission(doc, user: Optional[str] = None, ptype: str = "read") -> Optional[bool]:
    """
    Document-level permission evaluator for 'Employee Reimbursement Claim'.
    """
    if not user:
        user = frappe.session.user

    # If doc is None or a string (doctype-level check), let standard DocPerm decide
    if not doc or isinstance(doc, str):
        return None

    # Allow create/write on new/unsaved docs
    if getattr(doc, "__islocal", False) or (hasattr(doc, "is_new") and doc.is_new()) or not getattr(doc, "name", None) or str(getattr(doc, "name", "")).startswith("new-"):
        return True

    if is_global_view_user(user):
        return True

    own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
    is_owner = (getattr(doc, "owner", None) == user) or (own_emp and getattr(doc, "employee", None) == own_emp)

    doc_status = getattr(doc, "status", None)

    # 1. Draft & Returned states are editable by the claimant
    if is_owner:
        if ptype in ("read", "select", "email", "print"):
            return True
        if ptype in ("write", "create", "delete"):
            return doc_status in EMPLOYEE_EDITABLE_STATUSES
        return True

    # 2. Manager authorization
    mgr_uid = getattr(doc, "manager_user_id", None) or (doc.get("manager_user_id") if hasattr(doc, "get") else None)
    if mgr_uid == user:
        if ptype in ("read", "select", "email", "print"):
            return True
        if ptype == "write":
            return doc_status == "Pending Manager Approval"
        return True

    doc_emp = getattr(doc, "employee", None)
    if doc_emp:
        subordinate_emps = get_subordinate_employees_for_user(user)
        if doc_emp in subordinate_emps:
            if ptype in ("read", "select", "email", "print"):
                return True
            if ptype == "write":
                return doc_status == "Pending Manager Approval"
            return True

    return False


# ==============================================================================
# 2. PRE TRAVEL REQUEST PERMISSION HOOKS
# ==============================================================================

def get_pre_travel_permission_query_conditions(user: Optional[str] = None) -> str:
    """
    Injected into Frappe ORM queries for 'Pre Travel Request'.
    """
    if not user:
        user = frappe.session.user

    if is_global_view_user(user):
        return ""

    own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
    subordinate_emps = get_subordinate_employees_for_user(user)
    escaped_user = frappe.db.escape(user)
    escaped_own_emp = frappe.db.escape(own_emp) if own_emp else None

    subordinate_only = [e for e in subordinate_emps if e != own_emp]

    if subordinate_only:
        formatted_sub_ids = ", ".join([frappe.db.escape(e) for e in subordinate_only])
        emp_match = f"`tabPre Travel Request`.`employee` = {escaped_own_emp}" if escaped_own_emp else "1=0"
        return f"""(
            `tabPre Travel Request`.`owner` = {escaped_user}
            OR {emp_match}
            OR (`tabPre Travel Request`.`employee` IN ({formatted_sub_ids}) AND `tabPre Travel Request`.`status` NOT IN ('Draft'))
            OR (`tabPre Travel Request`.`manager_user_id` = {escaped_user} AND `tabPre Travel Request`.`status` NOT IN ('Draft'))
        )"""
    else:
        emp_match = f"OR `tabPre Travel Request`.`employee` = {escaped_own_emp}" if escaped_own_emp else ""
        return f"(`tabPre Travel Request`.`owner` = {escaped_user} {emp_match})"


def has_pre_travel_permission(doc, user: Optional[str] = None, ptype: str = "read") -> Optional[bool]:
    """
    Document-level permission evaluator for 'Pre Travel Request'.
    """
    if not user:
        user = frappe.session.user

    # If doc is None or a string (doctype-level check), let standard DocPerm decide
    if not doc or isinstance(doc, str):
        return None

    # Allow create/write on new/unsaved docs
    if getattr(doc, "__islocal", False) or (hasattr(doc, "is_new") and doc.is_new()) or not getattr(doc, "name", None) or str(getattr(doc, "name", "")).startswith("new-"):
        return True

    if is_global_view_user(user):
        return True

    own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
    is_owner = (getattr(doc, "owner", None) == user) or (own_emp and getattr(doc, "employee", None) == own_emp)

    doc_status = getattr(doc, "status", None) or ""

    # 1. Claimant permissions
    if is_owner:
        if ptype in ("read", "select", "email", "print"):
            return True
        if ptype in ("write", "create", "delete"):
            return doc_status in EMPLOYEE_EDITABLE_STATUSES
        return True

    # 2. Manager authorization
    mgr_uid = getattr(doc, "manager_user_id", None) or (doc.get("manager_user_id") if hasattr(doc, "get") else None)
    if mgr_uid == user:
        if ptype in ("read", "select", "email", "print"):
            return True
        if ptype == "write":
            return doc_status == "Pending Manager Approval"
        return True

    doc_emp = getattr(doc, "employee", None)
    if doc_emp:
        subordinate_emps = get_subordinate_employees_for_user(user)
        if doc_emp in subordinate_emps:
            if ptype in ("read", "select", "email", "print"):
                return True
            if ptype == "write":
                return doc_status == "Pending Manager Approval"
            return True

    return False


# ==============================================================================
# 3. DYNAMIC EMPLOYEE DROPDOWN LINK QUERY FILTER
# ==============================================================================

@frappe.whitelist()
def get_allowed_employee_query(doctype, txt, searchfield, start, page_len, filters):
    """
    Link field query filter for 'Employee ID' dropdown on claims and pre-travel forms.
    - Global Approvers: View and select ALL Active Employees across the organization.
    - Reporting Manager: View and select THEMSELVES + ALL EMPLOYEES REPORTING UNDER THEM.
    - Standard Employee: View and select THEIR OWN Employee ID ONLY.
    """
    user = frappe.session.user

    if is_global_view_user(user):
        return frappe.db.sql("""
            SELECT name, employee_name, department, company
            FROM `tabEmployee`
            WHERE status = 'Active'
              AND (name LIKE %(txt)s OR employee_name LIKE %(txt)s)
            ORDER BY employee_name ASC
            LIMIT %(start)s, %(page_len)s
        """, {
            "txt": f"%{txt}%",
            "start": int(start or 0),
            "page_len": int(page_len or 20)
        })

    subordinate_emps = get_subordinate_employees_for_user(user)

    if not subordinate_emps:
        own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if own_emp:
            subordinate_emps = [own_emp]

    if not subordinate_emps:
        return []

    formatted_ids = ", ".join([frappe.db.escape(e) for e in subordinate_emps])

    return frappe.db.sql(f"""
        SELECT name, employee_name, department, company
        FROM `tabEmployee`
        WHERE name IN ({formatted_ids})
          AND status = 'Active'
          AND (name LIKE %(txt)s OR employee_name LIKE %(txt)s)
        ORDER BY employee_name ASC
        LIMIT %(start)s, %(page_len)s
    """, {
        "txt": f"%{txt}%",
        "start": int(start or 0),
        "page_len": int(page_len or 20)
    })
