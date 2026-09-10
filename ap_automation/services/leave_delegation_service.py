"""
Autonomous HRMS Leave Delegation Engine
Enforces:
1. Live HRMS Leave Inspection (tabLeave Application).
2. Self-Approval Conflict-of-Interest Shield.
3. Dynamic Backup Routing when manager is on approved leave.
4. ₹50,000 Above-Limit Executive Escalation Gate (PRD Section 12).
5. In-flight claim re-routing worker.
"""
from typing import Dict, Any, List, Optional
import frappe
from ap_automation.exceptions import APValidationError, APSecurityError

ABOVE_LIMIT_THRESHOLD = 50000.00


def is_user_away(user_email: str, check_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Checks if a user is currently on an approved leave in Frappe HRMS.
    Inspects tabLeave Application where status='Approved' and docstatus=1.
    """
    if not user_email or user_email == "Administrator":
        return {"is_away": False}

    date_to_check = check_date or frappe.utils.nowdate()

    emp_name = frappe.db.get_value("Employee", {"user_id": user_email}, "name")
    if not emp_name:
        return {"is_away": False}

    active_leaves = frappe.get_all(
        "Leave Application",
        filters={
            "employee": emp_name,
            "status": "Approved",
            "from_date": ["<=", date_to_check],
            "to_date": [">=", date_to_check],
            "docstatus": 1
        },
        fields=["name", "leave_type", "from_date", "to_date", "description"],
        limit=1
    )

    if active_leaves:
        leave = active_leaves[0]
        return {
            "is_away": True,
            "leave_id": leave["name"],
            "leave_type": leave["leave_type"],
            "from_date": str(leave["from_date"]),
            "to_date": str(leave["to_date"]),
            "reason": f"On {leave['leave_type']} from {leave['from_date']} to {leave['to_date']}"
        }

    return {"is_away": False}


def resolve_claim_approver(
    employee_id: str,
    claim_amount: float,
    check_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Resolves the designated approver for an employee reimbursement claim:
    1. Prevents self-approval if employee is their own manager.
    2. Checks if reporting manager is on approved leave in HRMS; diverts to backup.
    3. Evaluates above-limit threshold (INR 50,000) for Executive Escalation.
    """
    date_to_check = check_date or frappe.utils.nowdate()

    emp = frappe.db.get_value(
        "Employee",
        employee_id,
        ["name", "employee_name", "user_id", "reports_to", "company", "department"],
        as_dict=True
    )
    if not emp:
        raise APValidationError(f"Employee record '{employee_id}' not found.")

    claimant_user = emp.user_id
    manager_emp_id = emp.reports_to

    primary_manager_user = None
    next_level_manager_user = None

    if manager_emp_id:
        mgr = frappe.db.get_value("Employee", manager_emp_id, ["user_id", "reports_to"], as_dict=True)
        if mgr:
            primary_manager_user = mgr.user_id
            if mgr.reports_to:
                next_mgr = frappe.db.get_value("Employee", mgr.reports_to, "user_id")
                if next_mgr:
                    next_level_manager_user = next_mgr

    # Self-Approval Conflict-of-Interest Shield
    is_self_claim = False
    if not manager_emp_id or (claimant_user and claimant_user == primary_manager_user):
        is_self_claim = True
        assigned_user = next_level_manager_user or "Administrator"
        primary_manager_user = primary_manager_user or claimant_user or "Administrator"
        routing_reason = (
            f"Self-Approval Conflict Shield: Employee '{emp.employee_name}' is their own reporting manager / top of hierarchy. "
            f"Claim automatically elevated to '{assigned_user}'."
        )
    else:
        assigned_user = primary_manager_user
        routing_reason = f"Routed to direct reporting manager '{primary_manager_user}'."

    # Live HRMS Leave Delegation Check
    is_delegated = False
    leave_status = is_user_away(assigned_user, check_date=date_to_check)
    if leave_status.get("is_away"):
        is_delegated = True
        backup_user = next_level_manager_user or "Administrator"
        routing_reason = (
            f"HRMS Leave Delegation: Primary Manager '{assigned_user}' is {leave_status.get('reason')}. "
            f"Claim automatically diverted to backup approver '{backup_user}'."
        )
        assigned_user = backup_user

    # Above-Limit Executive Gate (INR 50,000)
    requires_executive = float(claim_amount or 0.0) > ABOVE_LIMIT_THRESHOLD

    return {
        "claimant_user": claimant_user,
        "primary_manager": primary_manager_user,
        "assigned_approver": assigned_user,
        "is_self_claim": is_self_claim,
        "is_delegated": is_delegated,
        "requires_executive_approval": requires_executive,
        "routing_reason": routing_reason
    }


def reroute_inflight_pending_claims() -> Dict[str, Any]:
    """
    Scheduled worker: Detects managers who went on leave today and safely
    re-routes in-flight claims waiting in 'Pending Manager Approval' status.
    """
    today = frappe.utils.nowdate()
    pending_claims = frappe.get_all(
        "Employee Reimbursement Claim",
        filters={
            "status": "Pending Manager Approval"
        },
        fields=["name", "employee", "total_claim_amount", "designated_approver"]
    )

    rerouted_count = 0
    rerouted_details = []

    for claim in pending_claims:
        curr_approver = claim["designated_approver"]
        leave_status = is_user_away(curr_approver, check_date=today)
        if leave_status.get("is_away"):
            new_routing = resolve_claim_approver(claim["employee"], claim["total_claim_amount"], check_date=today)
            new_approver = new_routing["assigned_approver"]
            if new_approver != curr_approver:
                doc = frappe.get_doc("Employee Reimbursement Claim", claim["name"])
                doc.designated_approver = new_approver
                doc.append("approval_trail", {
                    "level_number": 1,
                    "level_name": "In-Flight Leave Reroute",
                    "designated_approver": new_approver,
                    "action_taken_by": "System Autonomous Engine",
                    "action": "APPROVED",
                    "action_timestamp": frappe.utils.now_datetime(),
                    "remarks": f"In-Flight Absence: {leave_status.get('reason')}. Diverted from '{curr_approver}' to '{new_approver}'."
                })
                doc.save(ignore_permissions=True)
                rerouted_count += 1
                rerouted_details.append({"claim": claim["name"], "from": curr_approver, "to": new_approver})

    if rerouted_count > 0:
        frappe.db.commit()

    return {
        "status": "success",
        "rerouted_count": rerouted_count,
        "claims": rerouted_details
    }
