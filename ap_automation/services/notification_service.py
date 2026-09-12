"""
Enterprise Multi-Tier Notification Service (PRD Section 10)
Handles:
1. Automated Role-based Email & Frappe Desk Realtime Notifications.
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
        return val
    # Look up in User table
    email = frappe.db.get_value("User", val, "email")
    if email and "@" in str(email):
        return str(email).strip()
    return None


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
    """Triggered when Receptionist submits envelope to Admin Supervisor."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    custodian = getattr(doc, "custodian", "Reception Staff")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    # Find Admin L1 Approvers
    l1_users = frappe.get_all(
        "Has Role",
        filters={"role": ["in", ["Admin L1 Approver", "Admin Manager", "System Manager"]], "parenttype": "User"},
        pluck="parent"
    )
    if not l1_users:
        l1_users = ["Administrator"]

    subject = f"📋 [Admin L1 Review] {voucher_doctype} #{voucher_name} (₹ {fmt_money(amount)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fed7aa; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #ea580c; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #c2410c; font-weight: 700;">Admin Department Gate • Level 1 Review</span>
            <h2 style="margin: 4px 0 0 0; color: #7c2d12; font-size: 20px;">New Petty Cash Voucher Submitted</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Front Desk / Receptionist <b>{custodian}</b> has entered a new petty cash envelope for <b>{company}</b> and requires your Admin Level 1 operational review.
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
    """Triggered when Admin L1 Supervisor approves and forwards to Admin Department Head."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    l1_approver = getattr(doc, "admin_l1_approver", "Admin Lead")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    # Find Admin L2 Approvers
    l2_users = frappe.get_all(
        "Has Role",
        filters={"role": ["in", ["Admin L2 Approver", "Admin Manager", "System Manager"]], "parenttype": "User"},
        pluck="parent"
    )
    if not l2_users:
        l2_users = ["Administrator"]

    subject = f"🏢 [Admin Head Sign-Off] {voucher_doctype} #{voucher_name} (₹ {fmt_money(amount)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #ddd6fe; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #7c3aed; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #6d28d9; font-weight: 700;">Admin Department Gate • Head Sign-off</span>
            <h2 style="margin: 4px 0 0 0; color: #4c1d95; font-size: 20px;">Voucher Approved by Admin Lead</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Admin Supervisor <b>{l1_approver}</b> has approved voucher <b>#{voucher_name}</b> for <b>{company}</b>. Your final departmental sign-off is required to dispatch this claim to Accounts.
        </p>
        <div style="background: #f5f3ff; border: 1px solid #ede9fe; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #5b21b6; margin-bottom: 4px;">Voucher Reference: <b style="color: #0f172a;">{voucher_name}</b></div>
            <div style="font-size: 18px; font-weight: 800; color: #7c3aed;">Total Value: ₹ {fmt_money(amount)}</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #7c3aed; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Approve & Dispatch to Accounts &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(l2_users, subject, html, voucher_doctype, voucher_name, "purple")


def notify_reception_on_admin_return(voucher_doctype: str, voucher_name: str, reason: str, returned_by: str) -> None:
    """Triggered when Admin L1 or L2 returns claim to Reception with remarks."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    custodian = getattr(doc, "custodian", None) or getattr(doc, "owner", None)
    if not custodian:
        return

    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    subject = f"↩️ [Action Required] Voucher #{voucher_name} Returned by {returned_by}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fecaca; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #dc2626; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #dc2626; font-weight: 700;">Petty Cash Return Notice</span>
            <h2 style="margin: 4px 0 0 0; color: #991b1b; font-size: 20px;">Voucher Returned for Rectification</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Your petty cash voucher <b>#{voucher_name}</b> (₹ {fmt_money(amount)}) has been returned by <b>{returned_by}</b> with the following remarks:
        </p>
        <div style="background: #fef2f2; border: 1px solid #fee2e2; border-radius: 8px; padding: 14px; margin: 16px 0; color: #991b1b; font-weight: 600;">
            "{reason}"
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #dc2626; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Open Voucher & Correct Details &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert([custodian], subject, html, voucher_doctype, voucher_name, "red")


# --------------------------------------------------------------------------------------
# 1. NOTIFY L1: Voucher Submitted by Admin to Accounts
# --------------------------------------------------------------------------------------
def notify_l1_on_voucher_submitted(voucher_doctype: str, voucher_name: str) -> None:
    """Triggered when Admin Head approves and submits voucher for Accounts audit."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    custodian = getattr(doc, "custodian", "Branch Admin")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    # Find L1 Accounts Verifiers
    l1_users = frappe.get_all(
        "Has Role",
        filters={"role": ["in", ["Accounts User", "Accounts Manager", "System Manager"]], "parenttype": "User"},
        pluck="parent"
    )
    if not l1_users:
        l1_users = ["Administrator"]

    subject = f"📑 [AP Audit Required] {voucher_doctype} #{voucher_name} (₹ {fmt_money(amount)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #e2e8f0; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #4f46e5; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #4f46e5; font-weight: 700;">AP Automation &bull; Lane 1 Imprest</span>
            <h2 style="margin: 4px 0 0 0; color: #0f172a; font-size: 20px;">New Expense Voucher Submitted</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            A new petty cash voucher has passed internal Admin approvals and has been submitted by <b>{custodian}</b> for <b>{company}</b>. It is ready for Accounts Level 1 line-item audit.
        </p>
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #64748b; margin-bottom: 4px;">Voucher Reference: <b style="color: #0f172a;">{voucher_name}</b></div>
            <div style="font-size: 18px; font-weight: 800; color: #059669;">Total Claim Value: ₹ {fmt_money(amount)}</div>
            <div style="font-size: 12px; color: #64748b; margin-top: 6px;">Line items and receipt attachments are ready for verification.</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #4f46e5; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Audit & Verify Line Items &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(l1_users, subject, html, voucher_doctype, voucher_name, "blue")


# --------------------------------------------------------------------------------------
# 2. NOTIFY ADMIN ON DISPUTE: Line Item Rejected/Disputed by L1
# --------------------------------------------------------------------------------------
def notify_admin_on_dispute(
    voucher_doctype: str,
    voucher_name: str,
    disputed_items: List[Dict[str, Any]],
    forked_voucher_name: Optional[str] = None
) -> None:
    """Triggered when L1 Accounts Verifier disputes specific bill lines."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    custodian = getattr(doc, "custodian", None) or getattr(doc, "owner", None)
    if not custodian:
        return

    total_disputed = sum(float(i.get("amount", 0.0)) for i in disputed_items)
    doc_url = get_url_to_form(voucher_doctype, forked_voucher_name or voucher_name)

    items_html = ""
    for idx, item in enumerate(disputed_items, 1):
        reason = item.get("dispute_reason") or item.get("rejection_reason") or "Missing valid tax invoice proof"
        items_html += f"""
        <tr style="border-bottom: 1px solid #e2e8f0; font-size: 13px;">
            <td style="padding: 10px; color: #0f172a;"><b>#{idx}</b> {item.get('merchant_name') or item.get('expense_category')}</td>
            <td style="padding: 10px; font-weight: 700; color: #dc2626;">₹ {fmt_money(float(item.get('amount', 0.0)))}</td>
            <td style="padding: 10px; color: #b91c1c;">{reason}</td>
        </tr>
        """

    subject = f"⚠️ [Action Required] Line Items Disputed in #{voucher_name} (₹ {fmt_money(total_disputed)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fecaca; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #dc2626; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #dc2626; font-weight: 700;">AP Audit Notice &bull; Action Required</span>
            <h2 style="margin: 4px 0 0 0; color: #991b1b; font-size: 20px;">Expense Line Items Disputed</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Accounts L1 Verifier has audited your voucher <b>#{voucher_name}</b> and flagged the following line item(s) as disputed:
        </p>
        <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
            <thead>
                <tr style="background: #fef2f2; text-align: left; font-size: 12px; color: #991b1b;">
                    <th style="padding: 8px 10px;">Item / Merchant</th>
                    <th style="padding: 8px 10px;">Amount</th>
                    <th style="padding: 8px 10px;">Dispute Reason</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
            </tbody>
        </table>
        <p style="font-size: 13px; color: #64748b;">
            Disputed lines have been separated into new draft <b>#{forked_voucher_name or voucher_name}</b>. Please attach rectified proof and resubmit.
        </p>
        <div style="text-align: center; margin-top: 20px;">
            <a href="{doc_url}" style="background: #dc2626; color: #ffffff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 13px; display: inline-block;">
                Review & Upload Corrected Proof &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert([custodian], subject, html, voucher_doctype, forked_voucher_name or voucher_name, "red")


# --------------------------------------------------------------------------------------
# 3. NOTIFY L2: Clean Voucher Audited & Ready for Director Approval
# --------------------------------------------------------------------------------------
def notify_l2_on_l1_verified(voucher_doctype: str, voucher_name: str) -> None:
    """Triggered when L1 audit passes and voucher moves to Director Tier."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    custodian = getattr(doc, "custodian", "Branch Admin")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    # Find L2 Director Approvers
    l2_users = frappe.get_all(
        "Has Role",
        filters={"role": ["in", ["Director Tier", "Dileep Director", "System Manager"]], "parenttype": "User"},
        pluck="parent"
    )
    if not l2_users:
        l2_users = ["dileep@quanticus.com", "Administrator"]

    subject = f"⭐ [Approval Required: L2 Director] {voucher_doctype} #{voucher_name} (₹ {fmt_money(amount)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fed7aa; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #f97316; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #ea580c; font-weight: 700;">Executive Director Approval Gate</span>
            <h2 style="margin: 4px 0 0 0; color: #7c2d12; font-size: 20px;">Voucher Audited & Verified by L1</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Accounts L1 has verified all supporting bills for <b>{voucher_name}</b> ({custodian} &bull; {company}) with zero audit discrepancies. Your final Level 2 approval is required.
        </p>
        <div style="background: #fff7ed; border: 1px solid #ffedd5; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #9a3412;">Approved Value for Payment:</div>
            <div style="font-size: 22px; font-weight: 800; color: #ea580c;">₹ {fmt_money(amount)}</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #ea580c; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Sanction & Approve Voucher &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(l2_users, subject, html, voucher_doctype, voucher_name, "orange")


# --------------------------------------------------------------------------------------
# 4. NOTIFY CUSTODIAN: Voucher Approved by Director
# --------------------------------------------------------------------------------------
def notify_admin_on_l2_approved(voucher_doctype: str, voucher_name: str) -> None:
    """Triggered when Director approves the claim for payment batching."""
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
            Your petty cash voucher <b>#{voucher_name}</b> for <b>₹ {fmt_money(amount)}</b> has received final Level 2 Approval and is queued in the upcoming corporate IDFC release batch.
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
        filters={"role": ["in", ["Payment Releaser", "System Manager"]], "parenttype": "User"},
        pluck="parent"
    )
    if not releasers:
        releasers = ["Administrator"]

    subject = f"🔐 [Action: 2FA Release] Payment Batch #{batch_name} (₹ {fmt_money(total_amt)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #c7d2fe; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #4f46e5; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #4338ca; font-weight: 700;">Executive Release Authority &bull; Anish Sir</span>
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
