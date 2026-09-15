"""
Enterprise Multi-Tier Notification Service (PRD Section 10)
Handles:
1. Automated Role-based & Matrix-based Email & Frappe Desk Realtime Notifications.
2. Professional Responsive HTML Email Templates with Enterprise Styling.
3. Itemized Dispute Alerts with Rejection Reasons.
4. Executive L2 Approval & 2FA Batch Release Alerts.
5. Post-Disbursement Bank Remittance Advice with Bank UTR.
6. Admin Pre-Approval Lifecycle Notifications (Reception -> Admin L1 -> Admin L2).
7. Immediate synchronous/queue dispatch with resilient user resolution.
"""
from typing import Dict, Any, List, Optional
import frappe
from frappe.utils import get_url_to_form, fmt_money


def _resolve_email(user_or_email: Optional[str]) -> Optional[str]:
    """Helper to resolve a Frappe user ID or email to a valid email address."""
    if not user_or_email:
        return None
    val = str(user_or_email).strip()
    if "@" in val and "." in val:
        # Ignore dummy test domains
        if val.endswith("@example.com"):
            return None
        return val
    # Look up in User table
    email = frappe.db.get_value("User", val, "email")
    if email and "@" in str(email) and not str(email).endswith("@example.com"):
        return str(email).strip()
    # Look up in Employee table
    if frappe.db.exists("Employee", val):
        emp_email = frappe.db.get_value("Employee", val, "company_email") or frappe.db.get_value("Employee", val, "personal_email") or frappe.db.get_value("Employee", val, "user_id")
        if emp_email:
            return _resolve_email(emp_email)
    return None


def _get_matrix_or_role_approvers(
    company: str,
    document_lane: str,
    level_number: int,
    fallback_roles: List[str]
) -> List[str]:
    """
    Looks up designated approvers from active AP Approval Matrix first;
    falls back to users holding the specified roles.
    """
    recipients = []
    
    # 1. Check AP Approval Matrix
    matrix_name = frappe.db.get_value(
        "AP Approval Matrix",
        {"company": company, "document_lane": document_lane, "is_active": 1},
        "name"
    )
    if not matrix_name:
        matrix_name = frappe.db.get_value(
            "AP Approval Matrix",
            {"document_lane": document_lane, "is_active": 1},
            "name"
        )
    
    if matrix_name:
        matrix = frappe.get_doc("AP Approval Matrix", matrix_name)
        for lvl in matrix.approval_levels:
            if lvl.level_number == level_number and lvl.designated_approver:
                recipients.append(lvl.designated_approver)
    
    # 2. Fallback to Role-Based Lookup if matrix is not configured or empty
    if not recipients and fallback_roles:
        role_users = frappe.get_all(
            "Has Role",
            filters={"role": ["in", fallback_roles], "parenttype": "User"},
            pluck="parent"
        )
        recipients.extend(role_users)
        
    return list(dict.fromkeys(recipients))


def _send_email_and_desk_alert(
    recipients: List[str],
    subject: str,
    message_html: str,
    reference_doctype: str,
    reference_name: str,
    alert_type: str = "blue"
) -> None:
    """Internal helper to dispatch both email and desk real-time alerts."""
    if not recipients:
        return

    valid_recipients = []
    desk_users = []
    for r in recipients:
        if not r:
            continue
        desk_users.append(str(r).strip())
        resolved = _resolve_email(r)
        if resolved:
            valid_recipients.append(resolved)

    valid_recipients = list(dict.fromkeys(valid_recipients))
    desk_users = list(dict.fromkeys(desk_users))

    # 1. Send Email (now=True for immediate SMTP dispatch)
    if valid_recipients:
        try:
            frappe.sendmail(
                recipients=valid_recipients,
                subject=subject,
                message=message_html,
                reference_doctype=reference_doctype,
                reference_name=reference_name,
                now=True
            )
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Failed to send email for {reference_name}: {str(e)}", "AP Notification Error")

    # 2. Desk Real-time Notification
    for user in desk_users:
        try:
            frappe.publish_realtime(
                event="msgprint",
                message={
                    "message": f"<b>{subject}</b><br><a href='/desk/{reference_doctype.lower().replace(' ', '-')}/{reference_name}'>View {reference_name}</a>",
                    "indicator": alert_type,
                    "title": "AP Automation Alert"
                },
                user=user
            )
        except Exception:
            pass


# --------------------------------------------------------------------------------------
# A. ADMIN PRE-APPROVAL NOTIFICATIONS
# --------------------------------------------------------------------------------------
def notify_admin_l1_on_reception_submit(voucher_doctype: str, voucher_name: str) -> None:
    """Triggered when Receptionist submits envelope to Assistant Admin Manager."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    custodian = getattr(doc, "custodian", "Reception Staff")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    # Find Level 1 Approvers (Matrix Level 1 -> Asst Admin Manager)
    l1_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=1,
        fallback_roles=["Assistant Admin Manager", "Admin L1 Approver", "Admin Manager", "System Manager"]
    )

    subject = f"📋 [Admin L1 Review] {voucher_doctype} #{voucher_name} (₹ {fmt_money(amount)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fed7aa; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #ea580c; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #c2410c; font-weight: 700;">Admin Department Gate • Assistant Admin Manager Review</span>
            <h2 style="margin: 4px 0 0 0; color: #7c2d12; font-size: 20px;">New Petty Cash Voucher Submitted</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Front Desk / Receptionist <b>{custodian}</b> has entered a new petty cash envelope for <b>{company}</b> and requires your Level 1 operational review.
        </p>
        <div style="background: #fff7ed; border: 1px solid #ffedd5; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #9a3412; margin-bottom: 4px;">Voucher Reference: <b style="color: #0f172a;">{voucher_name}</b></div>
            <div style="font-size: 18px; font-weight: 800; color: #ea580c;">Total Claim Value: ₹ {fmt_money(amount)}</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #ea580c; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Review Voucher & Approve &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(l1_users, subject, html, voucher_doctype, voucher_name, "orange")


def notify_admin_l2_on_l1_approved(voucher_doctype: str, voucher_name: str) -> None:
    """Triggered when Assistant Admin Manager approves and forwards to Admin Manager."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    l1_approver = getattr(doc, "admin_l1_approver", "Assistant Admin Manager")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    # Find Level 2 Approvers (Matrix Level 2 -> Admin Manager)
    l2_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=2,
        fallback_roles=["Admin Manager", "Admin L2 Approver", "System Manager"]
    )

    subject = f"📋 [Admin L2 Final Review] {voucher_doctype} #{voucher_name} (₹ {fmt_money(amount)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fbcfe8; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #db2777; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #be185d; font-weight: 700;">Admin Department Gate • Admin Manager Sign-off</span>
            <h2 style="margin: 4px 0 0 0; color: #831843; font-size: 20px;">Voucher Approved by Assistant Admin Manager</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Assistant Admin Manager <b>{l1_approver}</b> has approved petty cash claim <b>#{voucher_name}</b> (₹ {fmt_money(amount)}) for <b>{company}</b>. Please complete the final Admin sign-off before forwarding to Accounts.
        </p>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #db2777; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Review & Forward to Accounts &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(l2_users, subject, html, voucher_doctype, voucher_name, "purple")


def notify_reception_on_admin_return(
    voucher_doctype: str,
    voucher_name: str,
    returned_by_role: str,
    return_reason: str,
    return_to: str = "Reception"
) -> None:
    """Triggered when Admin L1/L2 rejects/returns voucher back to Receptionist or Admin L1."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    recipients = []
    
    # Creator / Front Desk
    if getattr(doc, "owner", None):
        recipients.append(doc.owner)
    if getattr(doc, "custodian", None):
        recipients.append(doc.custodian)
        
    # If returned to Admin L1, also include Admin L1 approver
    if return_to == "Admin L1" and getattr(doc, "admin_l1_approver", None):
        recipients.append(doc.admin_l1_approver)

    if not recipients:
        return

    doc_url = get_url_to_form(voucher_doctype, voucher_name)
    target_label = "Admin L1 Lead" if return_to == "Admin L1" else "Front Desk Reception"
    subject = f"⚠️ [Admin Returned to {target_label}] {voucher_doctype} #{voucher_name} Returned for Corrections"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fed7aa; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #f97316; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #c2410c; font-weight: 700;">Action Required &bull; Admin Corrections</span>
            <h2 style="margin: 4px 0 0 0; color: #7c2d12; font-size: 20px;">Voucher Returned by {returned_by_role}</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Your petty cash voucher <b>#{voucher_name}</b> has been returned by the Admin team with the following remarks:
        </p>
        <div style="background: #fff7ed; border-left: 4px solid #f97316; padding: 12px 16px; margin: 16px 0; border-radius: 0 8px 8px 0;">
            <p style="margin: 0; color: #9a3412; font-size: 14px; font-weight: 600;">{return_reason}</p>
        </div>
        <p style="color: #64748b; font-size: 13px;">
            Please open the voucher, adjust the line items / upload the required receipts, and re-submit for Admin approval.
        </p>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #f97316; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Open Voucher & Fix Receipts &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(recipients, subject, html, voucher_doctype, voucher_name, "orange")


# --------------------------------------------------------------------------------------
# 1. NOTIFY ACCOUNTS L1 AUDITOR: New Voucher Submitted
# --------------------------------------------------------------------------------------
def notify_l1_on_voucher_submitted(voucher_doctype: str, voucher_name: str) -> None:
    """Triggered when claim is submitted to Accounts L1 queue."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    custodian = getattr(doc, "custodian", "Branch Custodian")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    # Find Accounts L1 Auditors (Matrix Level 3 -> Accounts L1)
    auditors = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=3,
        fallback_roles=["Accounts L1 Auditor", "Accounts User", "Accounts Manager", "System Manager"]
    )

    subject = f"🔔 [Audit Required] {voucher_doctype} #{voucher_name} (₹ {fmt_money(amount)}) for {company}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #e2e8f0; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #2563eb; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #2563eb; font-weight: 700;">AP Automation &bull; Accounts Audit Queue</span>
            <h2 style="margin: 4px 0 0 0; color: #1e293b; font-size: 20px;">Petty Cash Claim Ready for Audit</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            A new petty cash claim has passed Admin pre-approval and has been submitted for <b>{company}</b> by <b>{custodian}</b>.
        </p>
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #64748b; margin-bottom: 4px;">Claim Number: <b style="color: #0f172a;">{voucher_name}</b></div>
            <div style="font-size: 18px; font-weight: 800; color: #0f172a;">Claim Amount: ₹ {fmt_money(amount)}</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #2563eb; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Open Document & Audit Line Items &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(auditors, subject, html, voucher_doctype, voucher_name, "blue")


# --------------------------------------------------------------------------------------
# 2. NOTIFY CUSTODIAN/ADMIN: Item Disputed/Rejected by Accounts
# --------------------------------------------------------------------------------------
def notify_custodian_on_dispute(
    voucher_doctype: str,
    voucher_name: str,
    disputed_items: List[Dict[str, Any]]
) -> None:
    """Triggered when Accounts L1 disputes one or more line items."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    custodian = getattr(doc, "custodian", None) or getattr(doc, "owner", None)
    if not custodian:
        return

    items_html = ""
    for item in disputed_items:
        exp_head = item.get("expense_head", "Expense")
        amt = float(item.get("amount", 0.0))
        reason = item.get("remarks") or item.get("dispute_reason") or "Receipt invalid or unreadable"
        items_html += f"""
        <tr style="border-bottom: 1px solid #e2e8f0;">
            <td style="padding: 10px; font-size: 13px; color: #1e293b;">{exp_head}</td>
            <td style="padding: 10px; font-size: 13px; color: #e11d48; font-weight: 600;">₹ {fmt_money(amt)}</td>
            <td style="padding: 10px; font-size: 13px; color: #475569;">{reason}</td>
        </tr>
        """

    doc_url = get_url_to_form(voucher_doctype, voucher_name)
    subject = f"⚠️ [Action Required] Items Disputed on {voucher_doctype} #{voucher_name}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fecdd3; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #e11d48; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #e11d48; font-weight: 700;">Audit Finding &bull; Dispute Notice</span>
            <h2 style="margin: 4px 0 0 0; color: #881337; font-size: 20px;">Line Items Disputed by Accounts</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            During the audit of voucher <b>#{voucher_name}</b>, the Accounts team flagged the following items requiring your attention:
        </p>
        <table style="width: 100%; border-collapse: collapse; margin: 16px 0; background: #fff1f2; border-radius: 6px; overflow: hidden;">
            <thead>
                <tr style="background: #ffe4e6; text-align: left;">
                    <th style="padding: 10px; font-size: 12px; color: #881337;">Expense Head</th>
                    <th style="padding: 10px; font-size: 12px; color: #881337;">Amount</th>
                    <th style="padding: 10px; font-size: 12px; color: #881337;">Reason</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
            </tbody>
        </table>
        <p style="color: #64748b; font-size: 13px;">
            <i>Note: Validated items will proceed to payment batching. Please review the disputed lines to re-submit or adjust.</i>
        </p>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #e11d48; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                View Voucher Details &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert([custodian], subject, html, voucher_doctype, voucher_name, "red")


# --------------------------------------------------------------------------------------
# 3. NOTIFY DIRECTOR L2: Batch / Claim Ready for Sanction (Anshul Sir)
# --------------------------------------------------------------------------------------
def notify_director_on_l1_audit_completed(voucher_doctype: str, voucher_name: str) -> None:
    """Triggered when Accounts L1 finishes audit and escalates to Director for L2 sanction."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    # Find Director / L2 Approvers (Matrix Level 4 -> Director Anshul Sir)
    directors = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=4,
        fallback_roles=["Accounts Director", "Director", "Accounts L2 Approver", "Director Tier", "System Manager"]
    )

    subject = f"📑 [Approval Required] {voucher_doctype} #{voucher_name} (₹ {fmt_money(amount)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fed7aa; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #ea580c; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #c2410c; font-weight: 700;">Executive Sanction &bull; Anshul Sir (Director)</span>
            <h2 style="margin: 4px 0 0 0; color: #7c2d12; font-size: 20px;">Voucher Audited by Accounts</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Petty cash claim <b>#{voucher_name}</b> for <b>{company}</b> has been audited and verified by Accounts L1. Management approval is requested.
        </p>
        <div style="background: #fff7ed; border: 1px solid #ffedd5; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #9a3412;">Payable Amount: <b style="font-size: 18px; color: #ea580c;">₹ {fmt_money(amount)}</b></div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #ea580c; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Review & Sanction Payout &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(directors, subject, html, voucher_doctype, voucher_name, "orange")


# --------------------------------------------------------------------------------------
# 4. NOTIFY CUSTODIAN/ADMIN: Claim Approved by Director
# --------------------------------------------------------------------------------------
def notify_admin_on_l2_approved(voucher_doctype: str, voucher_name: str) -> None:
    """Triggered when Director signs off on the voucher."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    custodian = getattr(doc, "custodian", None) or getattr(doc, "owner", None)
    if not custodian:
        return

    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    subject = f"✅ [Approved] {voucher_doctype} #{voucher_name} (₹ {fmt_money(amount)}) Approved for Payout"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #d1fae5; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #10b981; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #059669; font-weight: 700;">Approval Complete &bull; Payout Scheduled</span>
            <h2 style="margin: 4px 0 0 0; color: #065f46; font-size: 20px;">Voucher Approved by Director</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Your petty cash voucher <b>#{voucher_name}</b> for <b>₹ {fmt_money(amount)}</b> has received final Director Approval and is queued in the upcoming corporate IDFC release batch.
        </p>
    </div>
    """
    _send_email_and_desk_alert([custodian], subject, html, voucher_doctype, voucher_name, "green")


# --------------------------------------------------------------------------------------
# 5. NOTIFY RELEASER: Payment Batch Ready for 2FA Release (Anish Sir)
# --------------------------------------------------------------------------------------
def notify_releaser_on_batch_ready(batch_name: str) -> None:
    """Triggered when consolidated Payment Batch is generated and awaits 2FA release."""
    if not frappe.db.exists("Payment Batch", batch_name):
        return

    batch = frappe.get_doc("Payment Batch", batch_name)
    company = getattr(batch, "company", "Company")
    total_amt = float(getattr(batch, "total_batch_amount", 0.0) or 0.0)
    item_count = len(getattr(batch, "instructions", []) or [])
    doc_url = get_url_to_form("Payment Batch", batch_name)

    releasers = frappe.get_all(
        "Has Role",
        filters={"role": ["in", ["Payment Releaser", "Director", "System Manager"]], "parenttype": "User"},
        pluck="parent"
    )

    # Filter out dummy addresses
    releasers = [r for r in releasers if r != "Administrator"]
    if not releasers:
        releasers = ["anish@quanticus.com"]

    subject = f"🔐 [Action: 2FA Release] Payment Batch #{batch_name} (₹ {fmt_money(total_amt)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #c7d2fe; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #4f46e5; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #4338ca; font-weight: 700;">Executive Release Authority &bull; Anish Sir (CEO & MD)</span>
            <h2 style="margin: 4px 0 0 0; color: #1e1b4b; font-size: 20px;">Corporate Payment Batch Ready</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Consolidated Payment Batch <b>#{batch_name}</b> for <b>{company}</b> has completed all L1 and L2 audit gates and is waiting for your 2FA OTP release authorization.
        </p>
        <div style="background: #eef2ff; border: 1px solid #e0e7ff; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="display: flex; justify-content: space-between;">
                <div>
                    <div style="font-size: 12px; color: #4338ca; font-weight: 600;">Total Payout Instructions</div>
                    <div style="font-size: 16px; font-weight: 700; color: #1e1b4b;">{item_count} Claims</div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 12px; color: #4338ca; font-weight: 600;">Total Payout Value</div>
                    <div style="font-size: 20px; font-weight: 800; color: #059669;">₹ {fmt_money(total_amt)}</div>
                </div>
            </div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #4f46e5; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Authorize Release with 2FA OTP &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(releasers, subject, html, "Payment Batch", batch_name, "purple")


# --------------------------------------------------------------------------------------
# 6. NOTIFY PAYEE & ADMIN: Payout Disbursed with Bank UTR
# --------------------------------------------------------------------------------------
def notify_payee_and_admin_on_payout_dispatched(
    batch_name: str,
    idfc_ref: str
) -> None:
    """Triggered upon successful 2FA IDFC Bank API release."""
    if not frappe.db.exists("Payment Batch", batch_name):
        return

    batch = frappe.get_doc("Payment Batch", batch_name)
    items = getattr(batch, "instructions", []) or []

    for item in items:
        bene_name = item.beneficiary_name or "Payee"
        amt = float(item.amount or 0.0)
        utr = item.utr or f"UTR-{idfc_ref}"
        ac_num = str(item.account_number or "")
        masked_ac = ("X" * (len(ac_num) - 4) + ac_num[-4:]) if len(ac_num) >= 4 else ac_num
        src_dt = item.source_doctype
        src_vch = item.source_voucher

        # Get recipient user/email (from source voucher custodian/vendor)
        recipient = None
        if src_dt and src_vch and frappe.db.exists(src_dt, src_vch):
            recipient = frappe.db.get_value(src_dt, src_vch, "custodian") or frappe.db.get_value(src_dt, src_vch, "owner")

        if not recipient:
            recipient = bene_name

        if recipient:
            subject = f"🎉 [Payment Disbursed] ₹ {fmt_money(amt)} Credited (Bank UTR: {utr})"
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #d1fae5; border-radius: 10px; padding: 24px; background: #ffffff;">
                <div style="border-bottom: 2px solid #10b981; padding-bottom: 12px; margin-bottom: 16px;">
                    <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #059669; font-weight: 700;">IDFC FIRST Bank &bull; Corporate Payout Advice</span>
                    <h2 style="margin: 4px 0 0 0; color: #065f46; font-size: 20px;">Funds Disbursed to Bank Account</h2>
                </div>
                <p style="color: #334155; font-size: 14px; line-height: 1.5;">
                    Dear <b>{bene_name}</b>,<br>
                    Your claim for <b>{src_vch}</b> has been successfully disbursed via IDFC Bank API.
                </p>
                <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
                    <div style="font-size: 13px; color: #166534;">Disbursed Amount: <b style="font-size: 18px; color: #15803d;">₹ {fmt_money(amt)}</b></div>
                    <div style="font-size: 13px; color: #166534; margin-top: 8px;">Credited Account: <b>{masked_ac}</b> ({item.ifsc_code})</div>
                    <div style="font-size: 14px; font-weight: 800; color: #166534; margin-top: 10px; background: #dcfce7; padding: 6px 12px; border-radius: 4px; display: inline-block;">
                        Bank UTR: {utr}
                    </div>
                </div>
                <p style="font-size: 12px; color: #64748b;">
                    Branch Imprest Float has been replenished and posted to accounting records.
                </p>
            </div>
            """
            _send_email_and_desk_alert([recipient], subject, html, src_dt or "Payment Batch", src_vch or batch_name, "green")


# --------------------------------------------------------------------------------------
# 3.5 NOTIFY ACCOUNTS L1 & ADMIN: Claim Rejected / Returned by Accounts Director
# --------------------------------------------------------------------------------------
def notify_on_director_rejection(
    voucher_doctype: str,
    voucher_name: str,
    reason: str,
    director_user: str,
    return_to: str = "Accounts L1"
) -> None:
    """Triggered when Accounts Director rejects or returns a voucher back to Accounts L1 / Admin."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    recipients = []

    # 1. Accounts L1 Auditors (who audited or hold Accounts User role)
    for row in getattr(doc, "approval_trail", []):
        act_by = getattr(row, "action_taken_by", None)
        if act_by and act_by != director_user:
            recipients.append(act_by)

    accounts_users = _get_matrix_or_role_approvers(
        getattr(doc, "company", ""),
        getattr(doc, "doctype", ""),
        1,
        ["Accounts User", "Accounts Auditor", "Accounts L1"]
    )
    recipients.extend(accounts_users)

    # 2. Admin Approvers
    if getattr(doc, "admin_l2_approver", None):
        recipients.append(doc.admin_l2_approver)
    if getattr(doc, "admin_l1_approver", None):
        recipients.append(doc.admin_l1_approver)

    # 3. Custodian / Front Desk
    if getattr(doc, "owner", None):
        recipients.append(doc.owner)
    if getattr(doc, "custodian", None):
        recipients.append(doc.custodian)

    recipients = list(dict.fromkeys([r for r in recipients if r]))
    if not recipients:
        return

    amount = float(getattr(doc, "total_amount", 0.0) or getattr(doc, "net_payable_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)
    target_label = "Accounts L1 Team" if return_to == "Accounts L1" else "Front Desk Reception"
    subject = f"🚫 [Director Rejected to {target_label}] {voucher_doctype} #{voucher_name} (₹ {fmt_money(amount)}) Returned"
    
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fecaca; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #ef4444; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #dc2626; font-weight: 700;">Executive Rejection &bull; Action Required</span>
            <h2 style="margin: 4px 0 0 0; color: #991b1b; font-size: 20px;">Claim Rejected by Accounts Director</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            The voucher <b>#{voucher_name}</b> for <b>₹ {fmt_money(amount)}</b> was reviewed by <b>Accounts Director</b> and returned to <b>{target_label}</b>.
        </p>
        <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 12px 16px; margin: 16px 0; border-radius: 0 8px 8px 0;">
            <div style="font-size: 12px; text-transform: uppercase; font-weight: 700; color: #b91c1c; margin-bottom: 4px;">Director's Rejection Reason:</div>
            <p style="margin: 0; color: #7f1d1d; font-size: 14px; font-weight: 600;">{reason}</p>
        </div>
        <p style="color: #64748b; font-size: 13px;">
            Please inspect the flagged discrepancy, perform necessary audit corrections, or coordinate with the claimant.
        </p>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #dc2626; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Open Voucher & Rectify Audit &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(recipients, subject, html, voucher_doctype, voucher_name, "red")
