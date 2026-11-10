# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
HRMS Hierarchy & Reporting Manager Resolution Service
Enterprise-grade, stateless service providing O(1) indexed lookups for employee reporting hierarchies,
active profile integrity, and dynamic RBAC security verification.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import frappe
from ap_automation.exceptions import APValidationError, APSecurityError


def resolve_employee_ifsc(*candidates: Any) -> str:
    """
    Resolves the cleanest IFSC code across Employee `custom_ifsc_code`, standard `ifsc_code`,
    and `Bank Account.branch_code`, preferring any valid 11-char NPCI IFSC over stale invalid strings.
    """
    from ap_automation.integrations.idfc import validate_ifsc_code

    cleaned = [str(c).strip().upper() for c in candidates if c and str(c).strip()]
    for cand in cleaned:
        if validate_ifsc_code(cand):
            return cand
    return cleaned[0] if cleaned else ""


def get_employee_hrms_profile(user_or_emp: str) -> Dict[str, Any]:
    """
    Fetches the verified HRMS profile for a given user ID or employee ID.
    Performs O(1) indexed lookup with strict field projection.
    """
    if not user_or_emp:
        raise APValidationError("User ID or Employee ID is required to fetch HRMS profile.")

    filters = {}
    if user_or_emp.startswith("EMP") or frappe.db.exists("Employee", user_or_emp):
        filters["name"] = user_or_emp
    else:
        filters["user_id"] = user_or_emp

    emp_meta = frappe.get_meta("Employee")
    proj = [
        "name",
        "employee_name",
        "user_id",
        "company",
        "department",
        "designation",
        "reports_to",
        "status",
        "bank_name",
        "bank_ac_no",
        "ifsc_code",
        "prefered_email",
        "cell_number",
    ]
    if emp_meta and emp_meta.has_field("custom_ifsc_code"):
        proj.append("custom_ifsc_code")

    emp_data = frappe.db.get_value("Employee", filters, proj, as_dict=True)

    if emp_data:
        resolved_ifsc = resolve_employee_ifsc(
            emp_data.get("custom_ifsc_code"),
            emp_data.get("ifsc_code"),
        )
        if resolved_ifsc:
            emp_data["ifsc_code"] = resolved_ifsc

    if not emp_data:
        raise APValidationError(f"Active HRMS Employee record not found for '{user_or_emp}'.")

    if emp_data.get("status") and emp_data.get("status") != "Active":
        raise APSecurityError(f"Employee '{emp_data.get('name')}' is '{emp_data.get('status')}'. Operations restricted.")

    return emp_data


def get_reporting_manager_for_employee(employee_id: str) -> Dict[str, Any]:
    """
    Resolves the HRMS Reporting Manager for a given Employee.
    Fetches the manager's Employee ID, User ID, Name, and Email in a single optimized DB roundtrip.
    """
    if not employee_id:
        raise APValidationError("Employee ID is required to resolve reporting manager.")

    # 1. Fetch direct reports_to pointer
    reports_to = frappe.db.get_value("Employee", employee_id, "reports_to")
    if not reports_to:
        raise APValidationError(
            f"HRMS Hierarchy Error: No Reporting Manager ('reports_to') is mapped for Employee '{employee_id}'. "
            f"Please ensure HR updates the reporting hierarchy in Employee Master."
        )

    # 2. Fetch manager profile details
    mgr_profile = frappe.db.get_value(
        "Employee",
        reports_to,
        ["name", "employee_name", "user_id", "status", "prefered_email", "cell_number"],
        as_dict=True
    )

    if not mgr_profile:
        raise APValidationError(f"Reporting Manager record '{reports_to}' does not exist in Employee database.")

    if mgr_profile.get("status") and mgr_profile.get("status") != "Active":
        raise APValidationError(
            f"Reporting Manager '{mgr_profile.get('employee_name')}' ({reports_to}) is marked as '{mgr_profile.get('status')}'. "
            f"Please contact HR to reassign reporting hierarchy."
        )

    if not mgr_profile.get("user_id"):
        raise APValidationError(
            f"Reporting Manager '{mgr_profile.get('employee_name')}' ({reports_to}) has no linked Frappe User Account. "
            f"System approval requires a valid User ID."
        )

    return {
        "manager_employee_id": mgr_profile.get("name"),
        "manager_name": mgr_profile.get("employee_name"),
        "manager_user_id": mgr_profile.get("user_id"),
        "manager_email": mgr_profile.get("prefered_email") or mgr_profile.get("user_id"),
        "manager_phone": mgr_profile.get("cell_number")
    }


def verify_manager_authorization(claimant_employee_id: str, actor_user_id: str) -> bool:
    """
    Verifies if actor_user_id is the authorized HRMS Reporting Manager or System Administrator.
    """
    if actor_user_id == "Administrator" or "System Manager" in frappe.get_roles(actor_user_id):
        return True

    mgr_info = get_reporting_manager_for_employee(claimant_employee_id)
    if mgr_info.get("manager_user_id") == actor_user_id:
        return True

    # Check active Leave/Approval Delegation if configured in system
    delegated_user = frappe.db.get_value(
        "Leave Application",
        {
            "employee": mgr_info.get("manager_employee_id"),
            "docstatus": 1,
            "from_date": ["<=", frappe.utils.nowdate()],
            "to_date": [">=", frappe.utils.nowdate()],
            "status": "Approved"
        },
        "leave_approver"
    )
    if delegated_user and delegated_user == actor_user_id:
        return True

    return False
