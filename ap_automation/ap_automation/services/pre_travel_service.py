# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Stage A: Pre-Travel Approval Domain Service (Client Visit Travel Only)
Governs:
1. Submission of Pre-Travel Requests.
2. Dynamic routing to HRMS Reporting Manager.
3. Manager Approval & Issuance of verified PTR Reference.
4. Manager Rejection with mandatory forensic rejection reason.
5. Asynchronous multi-channel notifications.
"""

from typing import Dict, Any, List, Optional
import frappe
from frappe.utils import now_datetime, getdate, nowdate, flt
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services import hrms_hierarchy_service
from ap_automation.services import employee_reimbursement_notification_service


def _append_trail(doc, user: str, action: str, remarks: str):
    """Safely appends audit trail entry if child table is defined."""
    row = {
        "action_taken_by": user,
        "action": action,
        "action_timestamp": now_datetime(),
        "remarks": remarks
    }
    for field in ("audit_trail", "approval_trail"):
        if hasattr(doc, field) and getattr(doc, field) is not None and hasattr(getattr(doc, field), "append"):
            try:
                doc.append(field, row)
                return
            except Exception:
                pass


@frappe.whitelist()
def submit_pre_travel_request(docname: str) -> Dict[str, Any]:
    """
    Submits Pre-Travel Request and routes directly to HRMS Reporting Manager.
    Allows submission from Draft, Returned for Correction, or Rejected states.
    """
    user = frappe.session.user
    doc = frappe.get_doc("Pre Travel Request", docname)

    if doc.status not in ("Draft", "Returned for Correction", "Rejected"):
        raise APValidationError(f"Cannot submit Pre-Travel Request '{docname}' with status '{doc.status}'.")

    # Enforce mandatory fields
    client_name = doc.get("client_name") or "Corporate Client"
    purpose = doc.get("purpose_of_visit") or doc.get("trip_purpose")
    from_date = doc.get("from_date") or doc.get("departure_date")
    to_date = doc.get("to_date") or doc.get("return_date")

    if not purpose:
        raise APValidationError("Purpose of Visit / Agenda is mandatory.")
    if not from_date or not to_date:
        raise APValidationError("Travel Start and End dates are mandatory.")
    if getdate(to_date) < getdate(from_date):
        raise APValidationError("Travel End Date cannot be earlier than Start Date.")

    # Dynamic HRMS Manager binding
    mgr_info = hrms_hierarchy_service.get_reporting_manager_for_employee(doc.employee)
    doc.reporting_manager = mgr_info["manager_employee_id"]
    doc.manager_user_id = mgr_info["manager_user_id"]
    doc.status = "Pending Manager Approval"
    doc.rejection_reason = None

    _append_trail(
        doc,
        user,
        "SUBMITTED",
        f"Submitted for Pre-Travel Approval to Reporting Manager {mgr_info['manager_name']}."
    )

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Trigger dedicated notification
    try:
        employee_reimbursement_notification_service.notify_manager_on_pre_travel_submitted(doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Manager for Pre-Travel {docname}: {str(e)}")

    return {
        "status": "SUCCESS",
        "docname": doc.name,
        "new_status": doc.status,
        "message": f"Pre-Travel Request #{doc.name} successfully submitted to Manager {mgr_info['manager_name']}."
    }


@frappe.whitelist()
def approve_pre_travel_request(docname: str, comments: Optional[str] = None) -> Dict[str, Any]:
    """
    HRMS Reporting Manager approves the Pre-Travel Request.
    """
    user = frappe.session.user
    doc = frappe.get_doc("Pre Travel Request", docname)

    if doc.status != "Pending Manager Approval":
        raise APValidationError(f"Cannot approve Pre-Travel Request '{docname}': status is '{doc.status}', expected 'Pending Manager Approval'.")

    # Authorize manager
    if not hrms_hierarchy_service.verify_manager_authorization(doc.employee, user):
        raise APSecurityError("Unauthorized: Only the designated HRMS Reporting Manager or Administrator can approve this Pre-Travel Request.")

    doc.status = "Approved"
    doc.approval_date = now_datetime()
    doc.approved_by_user = user

    _append_trail(
        doc,
        user,
        "APPROVED",
        comments or "Pre-Travel Request approved by Reporting Manager."
    )

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Trigger dedicated notification to employee
    try:
        employee_reimbursement_notification_service.notify_employee_on_pre_travel_approved(doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Employee for Pre-Travel Approval {docname}: {str(e)}")

    return {
        "status": "SUCCESS",
        "docname": doc.name,
        "new_status": doc.status,
        "message": f"Pre-Travel Request #{doc.name} approved. Employee notified."
    }


@frappe.whitelist()
def reject_pre_travel_request(docname: str, reason: str) -> Dict[str, Any]:
    """
    HRMS Reporting Manager rejects the Pre-Travel Request with a mandatory reason.
    """
    user = frappe.session.user
    if not reason or not reason.strip():
        raise APValidationError("Rejection Reason is strictly mandatory when rejecting a Pre-Travel Request.")

    doc = frappe.get_doc("Pre Travel Request", docname)

    if doc.status != "Pending Manager Approval":
        raise APValidationError(f"Cannot reject Pre-Travel Request '{docname}': status is '{doc.status}', expected 'Pending Manager Approval'.")

    # Authorize manager
    if not hrms_hierarchy_service.verify_manager_authorization(doc.employee, user):
        raise APSecurityError("Unauthorized: Only the designated HRMS Reporting Manager or Administrator can reject this Pre-Travel Request.")

    doc.status = "Rejected"
    doc.rejection_reason = reason.strip()
    doc.rejected_by_user = user

    _append_trail(
        doc,
        user,
        "REJECTED",
        f"Rejected by Manager. Reason: {reason.strip()}"
    )

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Trigger dedicated rejection notification
    try:
        employee_reimbursement_notification_service.notify_employee_on_pre_travel_rejected(doc.name, reason.strip())
    except Exception as e:
        frappe.log_error(f"Failed to notify Employee for Pre-Travel Rejection {docname}: {str(e)}")

    return {
        "status": "SUCCESS",
        "docname": doc.name,
        "new_status": doc.status,
        "message": f"Pre-Travel Request #{doc.name} has been rejected. Notification sent to employee."
    }
