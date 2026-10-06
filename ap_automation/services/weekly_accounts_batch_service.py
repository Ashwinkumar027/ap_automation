# -*- coding: utf-8 -*-
# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Enterprise Weekly Accounts Audit Batch (WAAB) Service
Consolidates all Admin L2 approved claims into a single Weekly Friday Batch for Accounts L1 & Accounts Director.
"""

from typing import Dict, Any, List, Optional
import frappe
from frappe.utils import getdate, nowdate, now_datetime, flt, cstr, fmt_money
import datetime
from ap_automation.services import employee_reimbursement_notification_service as notif


def get_current_friday(ref_date=None) -> datetime.date:
    """Calculates the Friday date for the current week."""
    dt = getdate(ref_date or nowdate())
    # Monday is 0, Friday is 4, Sunday is 6
    days_ahead = 4 - dt.weekday()
    return dt + datetime.timedelta(days=days_ahead)


@frappe.whitelist()
def generate_weekly_accounts_batch(company: str, batch_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Consolidates all Admin L2 approved claims for a company into a single Weekly Accounts Audit Batch.
    """
    if not company:
        frappe.throw("Company Entity is required to generate a Weekly Accounts Audit Batch.")

    friday_date = get_current_friday(batch_date)
    week_str = friday_date.strftime("%Y-W%W")

    # Fetch all claims awaiting Accounts Audit (cleared by Admin L2)
    claims = frappe.db.sql("""
        SELECT name, employee, employee_name, department, claim_category,
               posting_date, total_claim_amount, sanctioned_amount,
               bank_name, bank_account_number, bank_ifsc_code AS bank_ifsc
        FROM `tabEmployee Reimbursement Claim`
        WHERE company = %s
          AND status IN ('Pending Accounts L1', 'Admin L2 Approved', 'Pending Weekly Accounts Batch')
        ORDER BY employee_name ASC, posting_date ASC
    """, (company,), as_dict=True)

    if not claims:
        return {
            "status": "NO_CLAIMS",
            "message": f"No claims currently pending Accounts Audit for {company}."
        }

    # Check if a batch already exists for this Friday in Draft/Pending status
    existing_batch_name = frappe.db.get_value(
        "Weekly Accounts Audit Batch",
        {"company": company, "batch_date": friday_date, "status": ["in", ["Draft", "Pending Accounts L1 Audit"]]},
        "name"
    )

    if existing_batch_name:
        batch = frappe.get_doc("Weekly Accounts Audit Batch", existing_batch_name)
        batch.items = []  # Refresh items
    else:
        batch = frappe.new_doc("Weekly Accounts Audit Batch")
        batch.company = company
        batch.batch_date = friday_date
        batch.week_number = week_str
        batch.status = "Pending Accounts L1 Audit"

    total_claimed = 0.0
    total_sanctioned = 0.0
    unique_employees = set()

    for c in claims:
        claimed = flt(c.total_claim_amount)
        sanctioned = flt(c.sanctioned_amount or c.total_claim_amount)
        total_claimed += claimed
        total_sanctioned += sanctioned
        unique_employees.add(c.employee)

        # Count receipts attached
        receipt_count = frappe.db.count("File", {
            "attached_to_doctype": "Employee Reimbursement Claim",
            "attached_to_name": c.name
        }) or 1

        batch.append("items", {
            "voucher_type": "Employee Reimbursement Claim",
            "voucher_no": c.name,
            "employee_id": c.employee,
            "employee_name": c.employee_name,
            "department": c.department or "General",
            "bank_name": c.bank_name or "Salary Bank",
            "bank_account_number": c.bank_account_number or "",
            "bank_ifsc": c.bank_ifsc or "",
            "claim_category": c.claim_category or "General Expense",
            "claim_date": c.posting_date,
            "claimed_amount": claimed,
            "sanctioned_amount": sanctioned,
            "status": "Pending Audit",
            "receipt_count": receipt_count
        })

    batch.total_claims_count = len(claims)
    batch.total_employees_count = len(unique_employees)
    batch.total_claimed_amount = round(total_claimed, 2)
    batch.total_sanctioned_amount = round(total_sanctioned, 2)
    batch.total_disputed_amount = 0.0

    batch.save(ignore_permissions=True)
    frappe.db.commit()

    # Dispatch Single Consolidated Email to Accounts L1
    try:
        notif.notify_accounts_l1_on_weekly_batch_ready(batch.name)
    except Exception as e:
        frappe.log_error(f"Failed to send weekly batch notification for {batch.name}: {str(e)}", "AP Batch Error")

    return {
        "status": "SUCCESS",
        "batch_name": batch.name,
        "claims_count": len(claims),
        "employees_count": len(unique_employees),
        "total_amount": round(total_claimed, 2),
        "message": f"Weekly Accounts Batch {batch.name} generated with {len(claims)} claims for ₹ {total_claimed:,.2f}."
    }


@frappe.whitelist()
def generate_all_weekly_accounts_batches() -> Dict[str, Any]:
    """
    Cron Entrypoint: Scheduled every Friday at 12:00 PM.
    Generates weekly audit batches for all active companies.
    """
    companies = frappe.get_all("Company", pluck="name")
    results = {}
    for comp in companies:
        try:
            res = generate_weekly_accounts_batch(comp)
            results[comp] = res
        except Exception as e:
            results[comp] = {"status": "ERROR", "message": str(e)}
            frappe.log_error(f"Error generating Friday batch for {comp}: {str(e)}", "AP Friday Cron Error")
    return results


@frappe.whitelist()
def dispute_batch_item(batch_name: str, voucher_no: str, dispute_reason: str) -> Dict[str, Any]:
    """
    Accounts disputes a specific voucher in the batch:
    - Detaches the voucher from the batch and returns it directly to the Employee.
    - Other vouchers in the batch remain untouched and move forward.
    """
    if not batch_name or not voucher_no or not dispute_reason:
        frappe.throw("Batch Name, Voucher Number, and Dispute Reason are mandatory.")

    batch = frappe.get_doc("Weekly Accounts Audit Batch", batch_name)
    found_item = None
    for it in batch.items:
        if it.voucher_no == voucher_no:
            found_item = it
            break

    if not found_item:
        frappe.throw(f"Voucher #{voucher_no} not found in Batch {batch_name}.")

    found_item.status = "Disputed / Returned"
    found_item.dispute_reason = dispute_reason.strip()

    # Recalculate batch totals
    sanctioned_total = 0.0
    disputed_total = 0.0
    for it in batch.items:
        if it.status == "Disputed / Returned":
            disputed_total += flt(it.claimed_amount)
        else:
            sanctioned_total += flt(it.sanctioned_amount or it.claimed_amount)

    batch.total_sanctioned_amount = round(sanctioned_total, 2)
    batch.total_disputed_amount = round(disputed_total, 2)
    batch.save(ignore_permissions=True)

    # Return the individual claim back to Employee with dispute reason
    from ap_automation.services import employee_expense_approval_service
    employee_expense_approval_service.reject_claim_flexible(
        voucher_name=voucher_no,
        reason=dispute_reason,
        return_to="Employee"
    )

    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "voucher_no": voucher_no,
        "message": f"Voucher #{voucher_no} returned to employee with dispute reason. Remaining batch total: INR {batch.total_sanctioned_amount:,.2f}."
    }


@frappe.whitelist()
def audit_and_sanction_weekly_batch(batch_name: str, remarks: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage: Accounts L1 Auditor audits and sanctions the weekly batch -> Passes to Accounts Director.
    """
    user = frappe.session.user
    batch = frappe.get_doc("Weekly Accounts Audit Batch", batch_name)

    if batch.status not in ("Draft", "Pending Accounts L1 Audit"):
        frappe.throw(f"Batch {batch_name} is in status '{batch.status}', expected 'Pending Accounts L1 Audit'.")

    # Mark all non-disputed items as Audited / Approved
    sanctioned_total = 0.0
    for it in batch.items:
        if it.status != "Disputed / Returned":
            it.status = "Audited / Approved"
            sanctioned_total += flt(it.sanctioned_amount or it.claimed_amount)

    batch.status = "Pending Accounts Director"
    batch.accounts_l1_auditor = user
    batch.accounts_l1_audit_date = now_datetime()
    batch.accounts_l1_remarks = remarks or "Accounts L1 Tax & GST audit completed. Forwarded to Director."
    batch.total_sanctioned_amount = round(sanctioned_total, 2)

    batch.save(ignore_permissions=True)
    frappe.db.commit()

    # Notify Accounts Director (Level 5)
    try:
        notif.notify_accounts_director_on_weekly_batch_audited(batch.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Director for batch {batch.name}: {str(e)}", "AP Batch Error")

    return {
        "status": "SUCCESS",
        "batch_name": batch.name,
        "new_status": batch.status,
        "sanctioned_amount": batch.total_sanctioned_amount,
        "message": f"Batch {batch.name} audited by Accounts L1 (INR {batch.total_sanctioned_amount:,.2f}) and forwarded to Accounts Director."
    }


@frappe.whitelist()
def approve_accounts_director_weekly_batch(batch_name: str, remarks: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage: Accounts Director (Level 5) signs off on the entire weekly batch -> Queues for Payment Release.
    """
    user = frappe.session.user
    batch = frappe.get_doc("Weekly Accounts Audit Batch", batch_name)

    if batch.status != "Pending Accounts Director":
        frappe.throw(f"Batch {batch_name} is in status '{batch.status}', expected 'Pending Accounts Director'.")

    batch.status = "Approved for Payment"
    batch.accounts_director = user
    batch.accounts_director_sign_date = now_datetime()

    # Update all underlying vouchers to Approved for Payment
    for it in batch.items:
        if it.status == "Audited / Approved":
            doc = frappe.get_doc("Employee Reimbursement Claim", it.voucher_no)
            doc.status = "Approved for Payment"
            doc.workflow_state = "Approved - Ready for Payment Release"
            doc.sanctioned_amount = flt(it.sanctioned_amount)
            doc.net_payable_amount = flt(it.sanctioned_amount)
            doc.accounts_l2_approver = user
            doc.append("approval_trail", {
                "level_number": 7,
                "level_name": "Accounts Director Sign-Off (Weekly Batch)",
                "action_taken_by": user,
                "action": "APPROVED",
                "action_timestamp": now_datetime(),
                "remarks": f"Approved via Weekly Batch #{batch.name}. {remarks or ''}"
            })
            doc.save(ignore_permissions=True)

    batch.save(ignore_permissions=True)
    frappe.db.commit()

    # Notify Payment Releaser (Level 6)
    try:
        notif.notify_releaser_on_weekly_batch_approved(batch.name)
    except Exception as e:
        frappe.log_error(f"Failed to notify Payment Releaser for batch {batch.name}: {str(e)}", "AP Batch Error")

    return {
        "status": "SUCCESS",
        "batch_name": batch.name,
        "new_status": batch.status,
        "message": f"Weekly Batch {batch.name} approved by Director. Queued for Payment Release (INR {batch.total_sanctioned_amount:,.2f})."
    }


@frappe.whitelist()
def release_weekly_payment_batch(batch_name: str, payment_reference: Optional[str] = None, remarks: Optional[str] = None) -> Dict[str, Any]:
    """
    Stage: Payment Releaser executes payment disbursal for the weekly batch:
    - Marks batch as Paid.
    - Marks all underlying claims as Paid.
    - Settles AP Spend Fingerprints.
    - Dispatches individual payment confirmation emails with UTR to each employee.
    """
    user = frappe.session.user
    batch = frappe.get_doc("Weekly Accounts Audit Batch", batch_name)

    if batch.status != "Approved for Payment":
        frappe.throw(f"Batch {batch_name} is in status '{batch.status}', expected 'Approved for Payment'.")

    ref = payment_reference or f"WEEKLY-DISBURSAL-{batch.week_number}"
    batch.status = "Paid"
    batch.payment_releaser = user
    batch.payment_reference = ref
    batch.payment_date = now_datetime()

    for it in batch.items:
        if it.status == "Audited / Approved":
            claim = frappe.get_doc("Employee Reimbursement Claim", it.voucher_no)
            claim.status = "Paid"
            claim.workflow_state = "Payment Disbursed & Completed"
            claim.payment_reference = ref
            claim.payment_release_date = now_datetime()
            claim.payment_releaser = user
            claim.append("approval_trail", {
                "level_number": 8,
                "level_name": "Payment Release (Weekly Batch Disbursal)",
                "action_taken_by": user,
                "action": "APPROVED",
                "action_timestamp": now_datetime(),
                "remarks": f"Disbursed via Weekly Batch #{batch.name}. Ref: {ref}."
            })
            claim.save(ignore_permissions=True)

            # Settle spend fingerprints
            frappe.db.sql(
                "UPDATE `tabAP Spend Fingerprint` SET status = 'SETTLED' WHERE document_name = %s AND document_type = %s",
                (claim.name, claim.doctype)
            )

            # Notify individual employee with UTR
            try:
                notif.notify_employee_on_payment_released(claim.name, ref)
            except Exception as e:
                frappe.log_error(f"Failed to notify employee {claim.employee} for payment {claim.name}: {str(e)}", "AP Disbursal Error")

    batch.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "batch_name": batch.name,
        "payment_reference": ref,
        "total_disbursed": batch.total_sanctioned_amount,
        "message": f"Weekly Batch #{batch.name} disbursed successfully (INR {batch.total_sanctioned_amount:,.2f}). All vouchers marked as Paid."
    }
