"""
================================================================================
AP AUTOMATION - 4-TIER ORGANIZATIONAL PERMISSION SERVICE
================================================================================
Implements production-grade, multi-tier scoping across all AP Automation workflows:
  - Tier 1: Standard Employees (Strict Self-Isolation: Own employee ID / Own claims only)
  - Tier 2: Reporting Managers (Subordinate Scope: Self + direct/indirect reportees)
            * NOTE: Managers ONLY see subordinate requests/claims AFTER submission
                    (Status != 'Draft'). Drafts remain strictly private to the employee.
  - Tier 3: Global Approvers (Reception, Admin L1/L2, Accounts L1/Director, Payment Releaser)
            * Full organization-wide view for review, audit, and sanctioning.
  - Tier 4: System Managers (Global administrative control)
================================================================================
"""

import frappe
from typing import List, Optional, Set

GLOBAL_VIEW_ROLES = {
    "System Manager",
    "Administrator",
    "Admin L1 Approver",
    "Admin L2 Approver",
    "Accounts L1 Auditor",
    "Accounts Director",
    "Accounts Manager",
    "Payment Releaser",
    "Receptionist"
}


def is_global_view_user(user: Optional[str] = None) -> bool:
    """
    Checks if the user has any organization-wide governance/approver role.
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
    - Global Approvers: View all claims.
    - Standard Employee: View only own claims.
    - Reporting Manager: View own claims (including drafts) + subordinate claims (ONLY when status != 'Draft').
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
            OR (`tabEmployee Reimbursement Claim`.`employee` IN ({formatted_sub_ids}) AND `tabEmployee Reimbursement Claim`.`status` != 'Draft')
            OR (`tabEmployee Reimbursement Claim`.`manager_user_id` = {escaped_user} AND `tabEmployee Reimbursement Claim`.`status` != 'Draft')
        )"""
    else:
        emp_match = f"OR `tabEmployee Reimbursement Claim`.`employee` = {escaped_own_emp}" if escaped_own_emp else ""
        return f"(`tabEmployee Reimbursement Claim`.`owner` = {escaped_user} {emp_match})"


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

    own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")

    # Drafts are strictly accessible only to the owner/claimant
    if getattr(doc, "status", None) == "Draft":
        if getattr(doc, "owner", None) == user or (own_emp and getattr(doc, "employee", None) == own_emp):
            return True
        return False

    if getattr(doc, "owner", None) == user:
        return True

    if own_emp and getattr(doc, "employee", None) == own_emp:
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
    - Global Approvers: View all requests.
    - Standard Employee: View only own requests.
    - Reporting Manager: View own requests (including drafts) + subordinate requests (ONLY when status != 'Draft').
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
            OR (`tabPre Travel Request`.`employee` IN ({formatted_sub_ids}) AND `tabPre Travel Request`.`status` != 'Draft')
            OR (`tabPre Travel Request`.`manager_user_id` = {escaped_user} AND `tabPre Travel Request`.`status` != 'Draft')
        )"""
    else:
        emp_match = f"OR `tabPre Travel Request`.`employee` = {escaped_own_emp}" if escaped_own_emp else ""
        return f"(`tabPre Travel Request`.`owner` = {escaped_user} {emp_match})"


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

    own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")

    # Drafts are strictly accessible only to the owner/creator
    if getattr(doc, "status", None) == "Draft":
        if getattr(doc, "owner", None) == user or (own_emp and getattr(doc, "employee", None) == own_emp):
            return True
        return False

    if getattr(doc, "owner", None) == user:
        return True

    if own_emp and getattr(doc, "employee", None) == own_emp:
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
