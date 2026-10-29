"""
Enterprise Dynamic Multi-Tier Permission Engine for Employee Reimbursements & Pre-Travel.
Implements:
1. Dynamic Real-time Role Permission Manager Evaluation (respects Read, Write, Create, Delete, Print, Email, Export checkboxes).
2. Dynamic ORM SQL Query Conditions (Desk List, Report, and API isolation).
3. Document-Level Fine-Grained Permissions (Read/Write/Approval security).
4. 4-Tier Organizational Scoping (Claimant, Reporting Manager, AP Approval Matrix Approver, Global Approver).
"""
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import frappe
from frappe.model.document import Document

# Pre-registered fallback roles for organization-wide visibility
GLOBAL_VIEW_ROLES = {
    "System Manager",
    "Administrator",
    "Accounts L1 Auditor",
    "Accounts Director",
    "Payment Releaser",
    "Accounts Manager",
    "Receptionist",
    "Admin L1 Approver",
    "Admin L2 Approver",
    "Admin Manager",
    "AP Director"
}

EMPLOYEE_EDITABLE_STATUSES = {"Draft", "Returned for Correction", "Returned to Employee", "Rejected", None, ""}


def get_dynamic_user_permissions(doctype: str, user: Optional[str] = None) -> Dict[str, bool]:
    """
    Dynamically inspects active permissions from Role Permission Manager (tabCustom DocPerm / tabDocPerm)
    and AP Approval Matrix for a specific user and doctype.
    Respects every individual checkbox: Read, Write, Create, Delete, Select, Print, Email, Report, Export, Share.
    """
    if not user:
        user = frappe.session.user

    perms = {
        "read": False,
        "write": False,
        "create": False,
        "delete": False,
        "select": False,
        "print": False,
        "email": False,
        "report": False,
        "export": False,
        "share": False,
        "is_global": False
    }

    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        for k in perms:
            perms[k] = True
        return perms

    user_roles = set(frappe.get_roles(user))
    
    # 1. Real-time inspection of active DocPerms (automatically selects Custom DocPerm if modified via UI)
    try:
        meta = frappe.get_meta(doctype)
        for p in meta.permissions:
            if p.role in user_roles:
                # Corporate/approver role (not restricted to creator/employee only)
                is_corporate_rule = (not getattr(p, "if_owner", 0)) and (p.role not in ("Employee", "All"))
                if is_corporate_rule:
                    for k in ["read", "write", "create", "delete", "select", "print", "email", "report", "export", "share"]:
                        if getattr(p, k, 0):
                            perms[k] = True
                    if getattr(p, "read", 0):
                        perms["is_global"] = True
    except Exception as e:
        frappe.log_error(f"Error evaluating dynamic permissions for {doctype}: {str(e)}", "Dynamic RBAC Error")

    # 2. Real-time inspection of AP Approval Matrix designated approvers
    try:
        if frappe.db.exists("DocType", "AP Approval Matrix"):
            matrix_approvers = frappe.db.sql("""
                SELECT lvl.designated_approver 
                FROM `tabAP Approval Level Rule` lvl
                JOIN `tabAP Approval Matrix` mat ON lvl.parent = mat.name
                WHERE mat.is_active = 1 
                  AND (mat.document_lane = %s OR mat.document_lane LIKE %s)
                  AND lvl.designated_approver = %s
            """, (doctype, f"%{doctype}%", user))
            if matrix_approvers:
                perms["read"] = True
                perms["write"] = True
                perms["select"] = True
                perms["print"] = True
                perms["email"] = True
                perms["report"] = True
                perms["is_global"] = True
    except Exception:
        pass

    # 3. Fallback to pre-registered global roles
    if bool(user_roles.intersection(GLOBAL_VIEW_ROLES)):
        perms["read"] = True
        perms["select"] = True
        perms["is_global"] = True

    return perms


def is_global_view_user(user: Optional[str] = None, doctype: str = "Employee Reimbursement Claim") -> bool:
    """
    Checks if the user possesses any corporate-wide audit or approval roles
    dynamically configured in Role Permission Manager or AP Approval Matrix.
    """
    if not user:
        user = frappe.session.user
    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        return True

    perms = get_dynamic_user_permissions(doctype, user)
    return bool(perms.get("is_global") and perms.get("read"))


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

    subordinates: Set[str] = set()
    to_process = list(manager_emp_names)
    processed = set()

    while to_process:
        current_mgr = to_process.pop(0)
        if current_mgr in processed:
            continue
        processed.add(current_mgr)

        direct_reports = frappe.db.get_all(
            "Employee",
            filters={"reports_to": current_mgr, "status": "Active"},
            pluck="name"
        )
        for dr in direct_reports:
            if dr not in subordinates:
                subordinates.add(dr)
                to_process.append(dr)

    all_emp_names = set(manager_emp_names).union(subordinates)
    return list(all_emp_names)


# ==============================================================================
# 1. EMPLOYEE REIMBURSEMENT CLAIM PERMISSION HOOKS
# ==============================================================================

def get_reimbursement_permission_query_conditions(user: Optional[str] = None) -> str:
    """
    Injected into Frappe ORM queries for 'Employee Reimbursement Claim'.
    - If user has a corporate role with Read=1 in Role Permission Manager -> returns "" (full company list).
    - If user is standard employee -> restricts to own claims and reporting subordinates.
    """
    if not user:
        user = frappe.session.user

    if is_global_view_user(user, "Employee Reimbursement Claim"):
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
    Dynamically respects UI checkboxes:
    - read: View claim
    - write: Edit/approve claim (if unchecked, user is strictly read-only)
    - create: Submit new claim
    - delete: Remove claim (if unchecked, delete is blocked)
    - print, email, export, report: Feature access
    """
    if not user:
        user = frappe.session.user

    # If doc is None or a string (doctype-level check), let standard DocPerm decide
    if not doc or isinstance(doc, str):
        return None

    # Dynamic check for new / unsaved documents
    perms = get_dynamic_user_permissions("Employee Reimbursement Claim", user)
    is_new_doc = (
        getattr(doc, "__islocal", False)
        or (hasattr(doc, "is_new") and doc.is_new())
        or not getattr(doc, "name", None)
        or str(getattr(doc, "name", "")).startswith("new-")
    )
    if is_new_doc:
        if ptype in ("create", "write"):
            # Check if user has create permission in DocPerm
            meta = frappe.get_meta("Employee Reimbursement Claim")
            user_roles = set(frappe.get_roles(user))
            can_create = any(p.role in user_roles and p.create for p in meta.permissions)
            return bool(can_create or perms.get("create"))
        return True

    # 1. Dynamic Check for Corporate / Approver Roles
    if perms.get("is_global"):
        if ptype == "delete":
            return bool(perms.get("delete"))
        if ptype == "write":
            return bool(perms.get("write"))
        if ptype in ("read", "select", "email", "print", "report", "export", "share"):
            return bool(perms.get(ptype, perms.get("read", False)))
        return bool(perms.get("read"))

    # 2. Claimant / Owner permissions
    own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
    is_owner = (getattr(doc, "owner", None) == user) or (own_emp and getattr(doc, "employee", None) == own_emp)
    doc_status = getattr(doc, "status", None)

    if is_owner:
        if ptype in ("read", "select", "email", "print"):
            return True
        if ptype in ("write", "create", "delete"):
            return doc_status in EMPLOYEE_EDITABLE_STATUSES
        return True

    # 3. Manager authorization
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
# 2. PRE TRAVEL REQUEST PERMISSION HOOKS (DYNAMIC)
# ==============================================================================

def get_pre_travel_permission_query_conditions(user: Optional[str] = None) -> str:
    """
    Injected into Frappe ORM queries for 'Pre Travel Request'.
    Dynamically respects Role Permission Manager.
    """
    if not user:
        user = frappe.session.user

    if is_global_view_user(user, "Pre Travel Request"):
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
    Dynamically respects UI checkboxes.
    """
    if not user:
        user = frappe.session.user

    if not doc or isinstance(doc, str):
        return None

    perms = get_dynamic_user_permissions("Pre Travel Request", user)
    is_new_doc = (
        getattr(doc, "__islocal", False)
        or (hasattr(doc, "is_new") and doc.is_new())
        or not getattr(doc, "name", None)
        or str(getattr(doc, "name", "")).startswith("new-")
    )
    if is_new_doc:
        if ptype in ("create", "write"):
            meta = frappe.get_meta("Pre Travel Request")
            user_roles = set(frappe.get_roles(user))
            can_create = any(p.role in user_roles and p.create for p in meta.permissions)
            return bool(can_create or perms.get("create"))
        return True

    # 1. Dynamic Check for Corporate / Approver Roles
    if perms.get("is_global"):
        if ptype == "delete":
            return bool(perms.get("delete"))
        if ptype == "write":
            return bool(perms.get("write"))
        if ptype in ("read", "select", "email", "print", "report", "export", "share"):
            return bool(perms.get(ptype, perms.get("read", False)))
        return bool(perms.get("read"))

    # 2. Claimant permissions
    own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
    is_owner = (getattr(doc, "owner", None) == user) or (own_emp and getattr(doc, "employee", None) == own_emp)
    doc_status = getattr(doc, "status", None) or ""

    if is_owner:
        if ptype in ("read", "select", "email", "print"):
            return True
        if ptype in ("write", "create", "delete"):
            return doc_status in EMPLOYEE_EDITABLE_STATUSES
        return True

    # 3. Manager authorization
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

    if is_global_view_user(user, doctype or "Employee Reimbursement Claim"):
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
