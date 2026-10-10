from typing import Any, Dict, List, Optional, Tuple, Union
# -*- coding: utf-8 -*-
# Copyright (c) 2026, Aionion Capital Market Services Private Limited
# For license information, please see license.txt

import frappe
from frappe.utils import get_url, flt, cstr, nowdate

def get_system_email_stakeholders(claim_doc):
    """
    Resolves official corporate email addresses for all workflow stakeholders:
    - Claimant Employee
    - Reporting Manager
    - Receptionist
    - Admin L1 & L2
    - Accounts Team
    """
    emp_id = claim_doc.employee
    emp_user = frappe.db.get_value("Employee", emp_id, "user_id") or ""
    emp_email = frappe.db.get_value("Employee", emp_id, "company_email") or frappe.db.get_value("Employee", emp_id, "personal_email") or emp_user

    mgr_user = claim_doc.manager_user_id or ""
    if not mgr_user and claim_doc.reporting_manager:
        mgr_user = frappe.db.get_value("Employee", claim_doc.reporting_manager, "user_id") or ""

    # Fetch role-based emails for Reception, Admin, Accounts
    reception_users = frappe.get_all("Has Role", filters={"role": "Receptionist", "parenttype": "User"}, fields=["parent"])
    admin_users = frappe.get_all("Has Role", filters={"role": ["in", ["Admin L1", "Admin L2", "System Manager"]], "parenttype": "User"}, fields=["parent"])
    accounts_users = frappe.get_all("Has Role", filters={"role": ["in", ["Accounts User", "Accounts Manager", "Auditor"]], "parenttype": "User"}, fields=["parent"])

    return {
        "employee_email": emp_email or "employee@aionion.in",
        "manager_email": mgr_user or "manager@aionion.in",
        "reception_emails": [r.parent for r in reception_users if "@" in r.parent] or ["reception@aionion.in"],
        "admin_emails": list(set([a.parent for a in admin_users if "@" in a.parent])) or ["admin@aionion.in"],
        "accounts_emails": list(set([acc.parent for acc in accounts_users if "@" in acc.parent])) or ["accounts@aionion.in"]
    }


@frappe.whitelist()
def send_dispute_notification_email(claim_name, line_idx=None, target_role="Employee", dispute_reason=""):
    """
    Sends a high-priority, single-thread dispute notification email:
    TO: Selected Target Role (Employee / Receptionist / Admin L1 / Manager)
    CC: All remaining stakeholders (Employee, Reception, Admin L1/L2, Manager, Accounts)
    """
    claim = frappe.get_doc("Employee Reimbursement Claim", claim_name)
    stakeholders = get_system_email_stakeholders(claim)

    # Determine TO recipient based on target_role
    if target_role == "Receptionist":
        to_email = stakeholders["reception_emails"][0] if stakeholders["reception_emails"] else "reception@aionion.in"
        target_title = "Reception Desk"
    elif target_role in ("Admin L1", "Admin L2"):
        to_email = stakeholders["admin_emails"][0] if stakeholders["admin_emails"] else "admin@aionion.in"
        target_title = target_role
    elif target_role == "Reporting Manager":
        to_email = stakeholders["manager_email"]
        target_title = "Reporting Manager"
    else:
        to_email = stakeholders["employee_email"]
        target_title = claim.employee_name or claim.employee

    # Build CC list (all other stakeholders except TO)
    cc_list = []
    if stakeholders["employee_email"] != to_email:
        cc_list.append(stakeholders["employee_email"])
    if stakeholders["manager_email"] != to_email:
        cc_list.append(stakeholders["manager_email"])
    for email in stakeholders["reception_emails"] + stakeholders["admin_emails"] + stakeholders["accounts_emails"]:
        if email != to_email and email not in cc_list:
            cc_list.append(email)

    claim_link = f"{get_url()}/app/employee-reimbursement-claim/{claim.name}"

    # Extract disputed line details
    disputed_line_desc = claim.claim_category
    disputed_amt = claim.total_claim_amount
    if line_idx is not None and claim.get("expense_lines"):
        try:
            line_item = claim.expense_lines[int(line_idx) - 1]
            disputed_line_desc = f"{line_item.expense_type} - {line_item.description or ''}"
            disputed_amt = line_item.amount
        except Exception:
            pass

    subject = f"[ACTION REQUIRED] Expense Line Disputed - Claim #{claim.name} - {claim.employee_name}"

    message_html = f"""
    <div style="font-family: Arial, sans-serif; font-size: 14px; color: #333; line-height: 1.6; max-width: 650px; border: 1px solid #e0e0e0; border-radius: 8px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #ff9800; padding-bottom: 12px; margin-bottom: 18px;">
            <h2 style="color: #e65100; margin: 0; font-size: 18px;">⚠️ Accounts Audit Notice: Expense Item Disputed</h2>
            <p style="margin: 4px 0 0; color: #666; font-size: 12px;">Voucher: <strong>{claim.name}</strong> | Category: <strong>{claim.claim_category}</strong></p>
        </div>

        <p>Dear <strong>{target_title}</strong>,</p>

        <p>During the Weekly Corporate Accounts Settlement Run, an expense item in the claim below requires your clarification or corrected documentation.</p>

        <div style="background-color: #fff8e1; border-left: 4px solid #ffb300; padding: 14px 18px; border-radius: 4px; margin: 16px 0;">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <tr>
                    <td style="padding: 4px 0; color: #777; width: 35%;"><strong>Employee Name:</strong></td>
                    <td style="padding: 4px 0; color: #111;"><strong>{claim.employee_name} ({claim.employee})</strong></td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #777;"><strong>Disputed Item:</strong></td>
                    <td style="padding: 4px 0; color: #111;">{disputed_line_desc}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #777;"><strong>Disputed Amount:</strong></td>
                    <td style="padding: 4px 0; color: #d32f2f; font-weight: bold;">INR {flt(disputed_amt):,.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #777;"><strong>Disputed By:</strong></td>
                    <td style="padding: 4px 0; color: #111;">Accounts Audit Team</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0 2px; color: #777; vertical-align: top;"><strong>Reason for Dispute:</strong></td>
                    <td style="padding: 6px 0 2px; color: #c62828; font-weight: bold; background: #ffebee; border-radius: 4px; padding: 6px 10px;">{dispute_reason or "Invoice / Receipt proof missing or illegible."}</td>
                </tr>
            </table>
        </div>

        <div style="background: #f1f8e9; border: 1px solid #c8e6c9; border-radius: 6px; padding: 12px 16px; margin: 16px 0;">
            <p style="margin: 0; color: #2e7d32; font-size: 13px;">
                💡 <strong>Weekly Payout Continuity:</strong><br>
                Any undisputed balance on other legitimate vouchers will be processed as scheduled. The disputed amount (INR {flt(disputed_amt):,.2f}) has been held pending your correction.
            </p>
        </div>

        <p style="margin: 20px 0 10px;"><strong>Required Next Action:</strong></p>
        <p style="margin: 0 0 20px; font-size: 13px; color: #555;">Please click the button below to upload the corrected invoice/tax receipt and resubmit.</p>

        <div style="text-align: center; margin: 24px 0;">
            <a href="{claim_link}" style="background-color: #1976d2; color: #ffffff; padding: 12px 26px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 14px; display: inline-block;">
                🔗 Review & Resubmit Claim #{claim.name}
            </a>
        </div>

        <p style="font-size: 12px; color: #888; margin-top: 24px; border-top: 1px solid #eee; padding-top: 12px;">
            ⚡ <em>Fast-Track Active: Resubmitting with corrected proofs will bypass repetitive manager approvals and roll directly into the next scheduled Friday payout run.</em>
        </p>
    </div>
    """

    # Enqueue threaded email
    frappe.sendmail(
        recipients=[to_email],
        cc=cc_list,
        subject=subject,
        message=message_html,
        reference_doctype="Employee Reimbursement Claim",
        reference_name=claim.name,
        now=True
    )

    # Log audit comment
    claim.add_comment("Comment", f"⚠️ <b>Line Disputed by Accounts</b>: {dispute_reason} (Action Routed to: <b>{target_title}</b>, Email sent to {to_email})")

    return {
        "status": "SUCCESS",
        "to": to_email,
        "cc": cc_list,
        "message": f"Dispute notice dispatched to {to_email} (CC: {len(cc_list)} stakeholders)"
    }


@frappe.whitelist()
def send_batch_payout_success_email(claim_name, utr_reference=""):
    """
    Sends a payment confirmation email to the employee upon Friday bulk disbursal.
    """
    claim = frappe.get_doc("Employee Reimbursement Claim", claim_name)
    stakeholders = get_system_email_stakeholders(claim)

    subject = f"🎉 Reimbursement Disbursed - Claim #{claim.name} - INR {claim.net_payable_amount:,.2f}"

    bank_mask = f"...{claim.bank_account_number[-4:]}" if claim.bank_account_number and len(claim.bank_account_number) >= 4 else "Registered Bank A/c"

    message_html = f"""
    <div style="font-family: Arial, sans-serif; font-size: 14px; color: #333; line-height: 1.6; max-width: 600px; border: 1px solid #e0e0e0; border-radius: 8px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #4caf50; padding-bottom: 12px; margin-bottom: 18px;">
            <h2 style="color: #2e7d32; margin: 0; font-size: 18px;">✅ Payment Released: Weekly Friday Settlement</h2>
            <p style="margin: 4px 0 0; color: #666; font-size: 12px;">Voucher: <strong>{claim.name}</strong></p>
        </div>

        <p>Dear <strong>{claim.employee_name}</strong>,</p>

        <p>We are pleased to inform you that your reimbursement payment has been successfully processed in today's Weekly Friday Payout Run.</p>

        <div style="background-color: #f1f8e9; border: 1px solid #c8e6c9; padding: 14px 18px; border-radius: 6px; margin: 16px 0;">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <tr>
                    <td style="padding: 4px 0; color: #555;"><strong>Disbursed Amount:</strong></td>
                    <td style="padding: 4px 0; color: #2e7d32; font-weight: bold; font-size: 16px;">INR {claim.net_payable_amount:,.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #555;"><strong>Bank Account:</strong></td>
                    <td style="padding: 4px 0; color: #111;">{claim.bank_name or 'Bank'} ({bank_mask})</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #555;"><strong>IFSC Code:</strong></td>
                    <td style="padding: 4px 0; color: #111;">{claim.bank_ifsc_code or 'N/A'}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #555;"><strong>UTR / Bank Ref:</strong></td>
                    <td style="padding: 4px 0; color: #111;"><strong>{utr_reference or 'NEFT-CMS-RELEASE'}</strong></td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #555;"><strong>Disbursal Date:</strong></td>
                    <td style="padding: 4px 0; color: #111;">{nowdate()}</td>
                </tr>
            </table>
        </div>

        <p style="font-size: 12px; color: #888; margin-top: 24px; border-top: 1px solid #eee; padding-top: 12px;">
            Aionion Capital Market Services Private Limited • Accounts & Finance Department
        </p>
    </div>
    """

    frappe.sendmail(
        recipients=[stakeholders["employee_email"]],
        cc=[stakeholders["manager_email"]] + stakeholders["accounts_emails"][:1],
        subject=subject,
        message=message_html,
        reference_doctype="Employee Reimbursement Claim",
        reference_name=claim.name,
        now=True
    )
