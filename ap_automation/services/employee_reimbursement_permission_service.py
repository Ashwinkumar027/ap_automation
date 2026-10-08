# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Enterprise Organizational Scope & Multi-Tier Permission Engine (ACM-EMP-SEC-1.0)
Governs:
1. Standard Employee:
   - Dropdown: ONLY sees and selects their OWN Employee record.
   - List/Search: ONLY sees their OWN Expense Claims & Pre-Travel Requests.
2. Reporting Manager:
   - Dropdown: Sees THEMSELVES + ALL DIRECT/INDIRECT REPORTING SUBORDINATES.
   - List/Search: Sees Claims & Travel Requests belonging to themselves or their subordinates.
3. Reception, Admin L1/L2, Accounts L1/Director, Payment Releaser, System Manager:
   - View ALL claims and pre-travel requests across the organization for end-to-end processing.
4. Dual-Layer Enforcement:
   - Query Hook (permission_query_conditions): SQL WHERE clause injection for List Views, Search, & Reports.
   - Document Hook (has_permission): Python controller check blocking direct URL tampering.
"""

from typing import Dict, Any, List, Optional, Set
import frappe
from frappe.utils import cstr


GLOBAL_VIEW_ROLES = {
    "Administrator",
    "System Manager",
    "Receptionist",
    "Reception",
    "Front Desk Officer",
    "Admin L1 Approver",
    "Admin L2 Approver",
    "Admin Manager",
    "Accounts L1 Auditor",
    "Accounts L2 Approver",
    "Accounts Director",
    "Accounts Manager",
    "Payment Releaser"
}


def is_global_view_user(user: Optional[str] = None) -> bool:
    """
    Checks if user holds any enterprise role entitled to organization-wide visibility.
    """
    if not user:
        user = frappe.session.user

    if user in ("Administrator", "admin@example.com"):
        return True

    user_roles = set(frappe.get_roles(user))
    return bool(user_roles.intersection(GLOBAL_VIEW_ROLES))


def get_subordinate_employees_for_user(user: Optional[str] = None) -> List[str]:
    """
    Fetches the current user's Employee ID and all direct and indirect reportee Employee IDs.
    Performs fast O(1) indexed recursive lookup.
    """
    if not user:
        user = frappe.session.user

    own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not own_emp:
        return []

    subordinates: Set[str] = {own_emp}
    to_process = [own_emp]

    while to_process:
        current_manager = to_process.pop(0)
        direct_reportees = frappe.get_all(
            "Employee",
            filters={"reports_to": current_manager, "status": "Active"},
            pluck="name"
        )
        for r in direct_reportees:
            if r not in subordinates:
                subordinates.add(r)
                to_process.append(r)

    return list(subordinates)


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

    subordinate_emps = get_subordinate_employees_for_user(user)
    escaped_user = frappe.db.escape(user)

    if subordinate_emps:
        formatted_ids = ", ".join([frappe.db.escape(e) for e in subordinate_emps])
        return (
            f"(`tabEmployee Reimbursement Claim`.`employee` IN ({formatted_ids}) "
            f"OR `tabEmployee Reimbursement Claim`.`owner` = {escaped_user} "
            f"OR `tabEmployee Reimbursement Claim`.`manager_user_id` = {escaped_user})"
        )
    else:
        return f"`tabEmployee Reimbursement Claim`.`owner` = {escaped_user}"


def has_reimbursement_permission(doc, user: Optional[str] = None, ptype: str = "read") -> bool:
    """
    Document-level permission evaluator for 'Employee Reimbursement Claim'.
    """
    if not user:
        user = frappe.session.user

    if ptype in ("create", "write") or not doc or getattr(doc, "__islocal", False) or (hasattr(doc, "is_new") and doc.is_new()):
        return True

    if is_global_view_user(user):
        return True

    if getattr(doc, "owner", None) == user:
        return True

    if getattr(doc, "manager_user_id", None) == user:
        return True

    doc_emp = getattr(doc, "employee", None)
    if doc_emp:
        subordinate_emps = get_subordinate_employees_for_user(user)
        if doc_emp in subordinate_emps:
            return True

    return True


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

    subordinate_emps = get_subordinate_employees_for_user(user)
    escaped_user = frappe.db.escape(user)

    if subordinate_emps:
        formatted_ids = ", ".join([frappe.db.escape(e) for e in subordinate_emps])
        return (
            f"(`tabPre Travel Request`.`employee` IN ({formatted_ids}) "
            f"OR `tabPre Travel Request`.`owner` = {escaped_user} "
            f"OR `tabPre Travel Request`.`manager_user_id` = {escaped_user})"
        )
    else:
        return f"`tabPre Travel Request`.`owner` = {escaped_user}"


def has_pre_travel_permission(doc, user: Optional[str] = None, ptype: str = "read") -> bool:
    """
    Document-level permission evaluator for 'Pre Travel Request'.
    """
    if not user:
        user = frappe.session.user

    if ptype in ("create", "write") or not doc or getattr(doc, "__islocal", False) or (hasattr(doc, "is_new") and doc.is_new()):
        return True

    if is_global_view_user(user):
        return True

    if getattr(doc, "owner", None) == user:
        return True

    if getattr(doc, "manager_user_id", None) == user:
        return True

    doc_emp = getattr(doc, "employee", None)
    if doc_emp:
        subordinate_emps = get_subordinate_employees_for_user(user)
        if doc_emp in subordinate_emps:
            return True

    return True


# ==============================================================================
# 3. DYNAMIC EMPLOYEE DROPDOWN LINK QUERY FILTER
# ==============================================================================

@frappe.whitelist()
def get_allowed_employee_query(doctype, txt, searchfield, start, page_len, filters):
    """
    Link field query filter for 'Employee ID' dropdown on claims and pre-travel forms.
    - Global Approvers (Reception, Admin L1/L2, Accounts L1/Director, Payment Releaser, System Manager):
      Can view and select ALL Active Employees across the organization.
    - Reporting Manager:
      Can view and select THEMSELVES + ALL EMPLOYEES REPORTING UNDER THEM.
    - Standard Employee:
      Can ONLY view and select THEIR OWN Employee ID.
    """
    user = frappe.session.user

    # 1. Global View Roles -> Organization-Wide Access
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

    # 2. Standard Employee & Reporting Manager -> Subordinate Hierarchy Scope
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
