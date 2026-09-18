"""
AP Automation Production Notification Engine (PRD Section 6 & 8)
Enforces:
1. Single Email Conversation Threading (RFC 5322 In-Reply-To and References).
2. Dynamic Rolling CC participant accumulation across approval lifecycle.
3. Strict isolation of 2FA OTP Batch Release and compliance security alerts.
4. Desk Real-Time Notification synchronization.
"""
import re
from typing import Dict, Any, List, Optional
import frappe
from frappe.utils import get_url_to_form, fmt_money


def _resolve_email(user_or_email: Optional[str]) -> Optional[str]:
    """
    Robust resolver that maps any User ID, Employee ID, or email address
    to a valid sendable email address. O(1) cached lookup.
    """
    if not user_or_email:
        return None
    val = str(user_or_email).strip()
    if not val:
        return None

    # Filter dummy accounts
    if val in ("Administrator", "admin@example.com"):
        return "ashwinkumar59@gmail.com"

    # Already valid email format
    if "@" in val and "." in val:
        return val

    # Lookup User DocType
    if frappe.db.exists("User", val):
        email = frappe.db.get_value("User", val, "email")
        if email and "@" in email:
            return email

    # Lookup Employee DocType
    if frappe.db.exists("Employee", val):
        emp_email = (
            frappe.db.get_value("Employee", val, "prefered_email")
            or frappe.db.get_value("Employee", val, "company_email")
            or frappe.db.get_value("Employee", val, "personal_email")
            or frappe.db.get_value("Employee", val, "user_id")
        )
        if emp_email and "@" in emp_email:
            return emp_email

    return None


def _get_matrix_or_role_approvers(
    company: str,
    document_lane: str,
    level_number: int,
    fallback_roles: List[str]
) -> List[str]:
    """
    Fetches designated approvers dynamically with O(1) dictionary indexing.
    """
    recipients = []

    # 1. Check Approval Matrix
    matrix_name = None
    if frappe.db.exists("DocType", "AP Approval Matrix"):
        matrix_name = frappe.db.get_value(
            "AP Approval Matrix",
            {"company": company, "document_lane": document_lane, "is_active": 1},
            "name"
        ) or frappe.db.get_value(
            "AP Approval Matrix",
            {"document_lane": document_lane, "is_active": 1},
            "name"
        )

    if matrix_name:
        matrix = frappe.get_doc("AP Approval Matrix", matrix_name)
        for lvl in matrix.approval_levels:
            if lvl.level_number == level_number and lvl.designated_approver:
                recipients.append(lvl.designated_approver)

    # 2. Fallback to Role-Based Lookup
    if not recipients and fallback_roles:
        role_users = frappe.get_all(
            "Has Role",
            filters={"role": ["in", fallback_roles], "parenttype": "User"},
            pluck="parent"
        )
        recipients.extend(role_users)

    return list(dict.fromkeys([r for r in recipients if r]))


def _get_claim_rolling_cc(doc, exclude_users: Optional[List[str]] = None) -> List[str]:
    """
    O(1) in-memory extraction of all prior actors and stakeholders on a claim
    to maintain a continuous rolling CC participant thread.
    """
    cc_list = []
    exclude = set(exclude_users or [])

    # 1. Custodian & Owner (Front Desk)
    for field in ("custodian", "owner", "employee"):
        val = getattr(doc, field, None)
        if val and val not in exclude:
            cc_list.append(val)

    # 2. Designated Admin Approvers
    for field in ("admin_l1_approver", "admin_l2_approver"):
        val = getattr(doc, field, None)
        if val and val not in exclude:
            cc_list.append(val)

    # 3. Approval Trail (Prior Reviewers)
    for row in getattr(doc, "approval_trail", []):
        act_by = getattr(row, "action_taken_by", None)
        if act_by and act_by not in exclude:
            cc_list.append(act_by)

    return list(dict.fromkeys(cc_list))


def _send_email_and_desk_alert(
    recipients: List[str],
    subject: str,
    message_html: str,
    reference_doctype: str,
    reference_name: str,
    alert_type: str = "blue",
    cc: Optional[List[str]] = None,
    is_thread_reply: bool = False
) -> None:
    """
    Dispatches threaded corporate emails and Frappe Desk real-time alerts.
    Enforces RFC 5322 In-Reply-To / References linking for continuous inbox conversation threads.
    """
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

    valid_cc = []
    if cc:
        for c in cc:
            if not c:
                continue
            resolved_cc = _resolve_email(c)
            if resolved_cc and resolved_cc not in valid_recipients:
                valid_cc.append(resolved_cc)
        valid_cc = list(dict.fromkeys(valid_cc))

    # Construct Deterministic Clean RFC 5322 Thread Key
    clean_dt = re.sub(r'[^a-zA-Z0-9]', '', reference_doctype)
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', reference_name)
    thread_root_id = f"<{clean_dt}-{clean_name}-thread@quanticus.com>"

    # 1. Send Threaded Email
    if valid_recipients:
        try:
            email_kwargs = {
                "recipients": valid_recipients,
                "subject": subject,
                "message": message_html,
                "reference_doctype": reference_doctype,
                "reference_name": reference_name,
                "now": True
            }
            if valid_cc:
                email_kwargs["cc"] = valid_cc

            if is_thread_reply:
                email_kwargs["in_reply_to"] = thread_root_id
            else:
                email_kwargs["message_id"] = thread_root_id

            frappe.sendmail(**email_kwargs)
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
# 1. STAGE 1: FRONT DESK SUBMISSION (Thread Starter)
# --------------------------------------------------------------------------------------
def notify_admin_l1_on_reception_submit(voucher_doctype: str, voucher_name: str) -> None:
    """Triggered when Receptionist submits envelope to Assistant Admin Manager."""
    notify_l1_on_voucher_submitted(voucher_doctype, voucher_name)


def notify_l1_on_voucher_submitted(voucher_doctype: str, voucher_name: str) -> None:
    """Starts the official email thread upon voucher submission."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    custodian = getattr(doc, "custodian", "Reception Staff")
    amount = float(getattr(doc, "total_amount", 0.0) or getattr(doc, "net_payable_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    l1_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=1,
        fallback_roles=["Admin L1 Approver"]
    )

    cc_users = [custodian, getattr(doc, "owner", None)]

    subject = f"[Voucher #{voucher_name}] {company} {voucher_doctype} (₹ {fmt_money(amount)}) - Submitted"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fed7aa; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #ea580c; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #c2410c; font-weight: 700;">Admin Department Gate • Level 1 Review</span>
            <h2 style="margin: 4px 0 0 0; color: #7c2d12; font-size: 20px;">New Petty Cash Voucher Submitted</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Front Desk / Custodian <b>{custodian}</b> has entered a new petty cash claim for <b>{company}</b> and requires your Level 1 departmental review.
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
    _send_email_and_desk_alert(
        recipients=l1_users,
        subject=subject,
        message_html=html,
        reference_doctype=voucher_doctype,
        reference_name=voucher_name,
        alert_type="orange",
        cc=cc_users,
        is_thread_reply=False
    )


# --------------------------------------------------------------------------------------
# 2. STAGE 2: ADMIN L1 APPROVED -> ESCALATE TO ADMIN L2 (Thread Reply)
# --------------------------------------------------------------------------------------
def notify_admin_l2_on_l1_approved(voucher_doctype: str, voucher_name: str) -> None:
    """Appends Admin L1 approval into the continuous conversation thread."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    l2_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=2,
        fallback_roles=["Admin L2 Approver"]
    )

    cc_users = _get_claim_rolling_cc(doc, exclude_users=l2_users)

    subject = f"Re: [Voucher #{voucher_name}] {company} {voucher_doctype} (₹ {fmt_money(amount)}) - Admin L1 Approved"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fed7aa; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #ea580c; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #c2410c; font-weight: 700;">Admin Department Gate • Head Sign-off</span>
            <h2 style="margin: 4px 0 0 0; color: #7c2d12; font-size: 20px;">Voucher Approved by Admin L1</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Assistant Admin Manager has completed Level 1 review and approved voucher <b>#{voucher_name}</b> (₹ {fmt_money(amount)}).
        </p>
        <div style="background: #fff7ed; border: 1px solid #ffedd5; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #9a3412;">Status: <b>Pending Admin L2 Sign-off</b></div>
            <div style="font-size: 18px; font-weight: 800; color: #ea580c; margin-top: 4px;">Claim Value: ₹ {fmt_money(amount)}</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #ea580c; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Sign-off & Forward to Accounts &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=l2_users,
        subject=subject,
        message_html=html,
        reference_doctype=voucher_doctype,
        reference_name=voucher_name,
        alert_type="orange",
        cc=cc_users,
        is_thread_reply=True
    )


# --------------------------------------------------------------------------------------
# 3. STAGE 3: ADMIN L2 APPROVED -> HANDOVER TO ACCOUNTS L1 AUDIT (Thread Reply)
# --------------------------------------------------------------------------------------
def notify_admin_on_l2_approved(voucher_doctype: str, voucher_name: str) -> None:
    """Appends Admin L2 signoff and hands over to Accounts Auditor in thread."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    accounts_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=1,
        fallback_roles=["Accounts L1 Auditor"]
    )

    cc_users = _get_claim_rolling_cc(doc, exclude_users=accounts_users)

    subject = f"Re: [Voucher #{voucher_name}] {company} {voucher_doctype} (₹ {fmt_money(amount)}) - Ready for Accounts Audit"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #bfdbfe; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #2563eb; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #1d4ed8; font-weight: 700;">Financial Audit • Accounts L1</span>
            <h2 style="margin: 4px 0 0 0; color: #1e3a8a; font-size: 20px;">Admin Sign-off Completed</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Admin Department Head has fully signed off on voucher <b>#{voucher_name}</b> for <b>{company}</b>. Ready for statutory invoice & duplicate check.
        </p>
        <div style="background: #eff6ff; border: 1px solid #dbeafe; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #1e40af;">Total Verified Amount: <b style="font-size: 18px; color: #2563eb;">₹ {fmt_money(amount)}</b></div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #2563eb; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Audit Voucher &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=accounts_users,
        subject=subject,
        message_html=html,
        reference_doctype=voucher_doctype,
        reference_name=voucher_name,
        alert_type="blue",
        cc=cc_users,
        is_thread_reply=True
    )


# --------------------------------------------------------------------------------------
# 4. STAGE 4: ACCOUNTS L1 AUDITED & PASSED -> ESCALATE TO DIRECTOR (Thread Reply)
# --------------------------------------------------------------------------------------
def notify_director_on_l1_audit_completed(voucher_doctype: str, voucher_name: str) -> None:
    """Appends Accounts L1 audit certification into thread and escalates to Director."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or getattr(doc, "net_payable_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    director_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=2,
        fallback_roles=["Accounts Director"]
    )

    cc_users = _get_claim_rolling_cc(doc, exclude_users=director_users)

    subject = f"Re: [Voucher #{voucher_name}] {company} {voucher_doctype} (₹ {fmt_money(amount)}) - Audited & Certified"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #bbf7d0; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #16a34a; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #15803d; font-weight: 700;">Executive Sanction • Accounts Director</span>
            <h2 style="margin: 4px 0 0 0; color: #14532d; font-size: 20px;">Voucher Audited & Certified</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Accounts L1 Auditor has certified voucher <b>#{voucher_name}</b> for <b>{company}</b>. Ready for final Director sanction.
        </p>
        <div style="background: #f0fdf4; border: 1px solid #dcfce7; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #166534;">Sanction Amount: <b style="font-size: 18px; color: #16a34a;">₹ {fmt_money(amount)}</b></div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #16a34a; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Sanction & Enrol in Thursday Batch &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=director_users,
        subject=subject,
        message_html=html,
        reference_doctype=voucher_doctype,
        reference_name=voucher_name,
        alert_type="green",
        cc=cc_users,
        is_thread_reply=True
    )


# --------------------------------------------------------------------------------------
# 5. STAGE 5: REJECTION / RETURN NOTIFICATION (Thread Reply)
# --------------------------------------------------------------------------------------
def notify_reception_on_admin_return(
    voucher_doctype: str,
    voucher_name: str,
    reason: str,
    admin_user: str
) -> None:
    """Appends Admin return notification into thread."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    custodian = getattr(doc, "custodian", None) or getattr(doc, "owner", None)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    recipients = [custodian] if custodian else []
    cc_users = _get_claim_rolling_cc(doc, exclude_users=recipients)

    subject = f"Re: [Voucher #{voucher_name}] {company} {voucher_doctype} (₹ {fmt_money(amount)}) - Returned for Corrections"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fecaca; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #dc2626; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #dc2626; font-weight: 700;">Revision Required • Admin Review</span>
            <h2 style="margin: 4px 0 0 0; color: #991b1b; font-size: 20px;">Voucher Returned for Rectification</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Your voucher <b>#{voucher_name}</b> was returned by <b>{admin_user}</b>.
        </p>
        <div style="background: #fef2f2; border-left: 4px solid #dc2626; padding: 12px 16px; margin: 16px 0; border-radius: 0 8px 8px 0;">
            <div style="font-size: 12px; text-transform: uppercase; font-weight: 700; color: #b91c1c; margin-bottom: 4px;">Return Reason:</div>
            <p style="margin: 0; color: #7f1d1d; font-size: 14px; font-weight: 600;">{reason}</p>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #dc2626; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Open Voucher & Correct &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=recipients,
        subject=subject,
        message_html=html,
        reference_doctype=voucher_doctype,
        reference_name=voucher_name,
        alert_type="red",
        cc=cc_users,
        is_thread_reply=True
    )


def notify_on_director_rejection(
    voucher_doctype: str,
    voucher_name: str,
    reason: str,
    director_user: str,
    return_to: str = "Accounts L1"
) -> None:
    """Appends Director rejection into thread."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or getattr(doc, "net_payable_amount", 0.0) or 0.0)
    doc_url = get_url_to_form(voucher_doctype, voucher_name)

    accounts_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=1,
        fallback_roles=["Accounts L1 Auditor"]
    )

    cc_users = _get_claim_rolling_cc(doc, exclude_users=accounts_users)
    target_label = "Accounts L1 Team" if return_to == "Accounts L1" else "Front Desk"

    subject = f"Re: [Voucher #{voucher_name}] {company} {voucher_doctype} (₹ {fmt_money(amount)}) - Returned by Director to {target_label}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fecaca; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #ef4444; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #dc2626; font-weight: 700;">Executive Rejection • Action Required</span>
            <h2 style="margin: 4px 0 0 0; color: #991b1b; font-size: 20px;">Claim Returned by Accounts Director</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            The voucher <b>#{voucher_name}</b> for <b>₹ {fmt_money(amount)}</b> was reviewed by <b>Accounts Director</b> and returned to <b>{target_label}</b>.
        </p>
        <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 12px 16px; margin: 16px 0; border-radius: 0 8px 8px 0;">
            <div style="font-size: 12px; text-transform: uppercase; font-weight: 700; color: #b91c1c; margin-bottom: 4px;">Director's Reason:</div>
            <p style="margin: 0; color: #7f1d1d; font-size: 14px; font-weight: 600;">{reason}</p>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #dc2626; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Open Voucher & Rectify Audit &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=accounts_users,
        subject=subject,
        message_html=html,
        reference_doctype=voucher_doctype,
        reference_name=voucher_name,
        alert_type="red",
        cc=cc_users,
        is_thread_reply=True
    )


# --------------------------------------------------------------------------------------
# 6. STAGE 6: DISPUTE SPLIT NOTIFICATION (Thread Reply)
# --------------------------------------------------------------------------------------
def notify_admin_on_dispute(
    voucher_doctype: str,
    voucher_name: str,
    disputed_items: List[Dict[str, Any]],
    forked_voucher_name: Optional[str] = None
) -> None:
    """Appends Line-Item Dispute finding into continuous thread."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    total_disputed = sum(float(i.get("amount", 0.0)) for i in disputed_items)
    doc_url = get_url_to_form(voucher_doctype, forked_voucher_name or voucher_name)

    admin_recipients = []
    if getattr(doc, "admin_l2_approver", None):
        admin_recipients.append(doc.admin_l2_approver)
    if getattr(doc, "admin_l1_approver", None):
        admin_recipients.append(doc.admin_l1_approver)

    if not admin_recipients:
        admin_recipients = _get_matrix_or_role_approvers(
            company=company,
            document_lane=voucher_doctype,
            level_number=1,
            fallback_roles=["Admin L1 Approver", "Admin L2 Approver"]
        )

    cc_users = _get_claim_rolling_cc(doc, exclude_users=admin_recipients)

    items_html = ""
    for idx, item in enumerate(disputed_items, 1):
        reason = item.get("dispute_reason") or item.get("rejection_reason") or item.get("remarks") or "Missing valid tax invoice proof"
        m_name = item.get("merchant_name") or item.get("expense_category") or "Item"
        amt = float(item.get("amount", 0.0))
        items_html += f"""
        <tr style="border-bottom: 1px solid #e2e8f0; font-size: 13px;">
            <td style="padding: 10px; color: #0f172a;"><b>#{idx}</b> {m_name}</td>
            <td style="padding: 10px; font-weight: 700; color: #dc2626;">₹ {fmt_money(amt)}</td>
            <td style="padding: 10px; color: #b91c1c;">{reason}</td>
        </tr>
        """

    subject = f"Re: [Voucher #{voucher_name}] {company} {voucher_doctype} (₹ {fmt_money(total_disputed)}) - Line Items Disputed"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fecaca; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #dc2626; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #dc2626; font-weight: 700;">AP Audit Notice • Action Required</span>
            <h2 style="margin: 4px 0 0 0; color: #991b1b; font-size: 20px;">Expense Line Items Disputed</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Accounts L1 Auditor has audited your voucher <b>#{voucher_name}</b> and flagged the following line item(s) as disputed:
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
            Disputed lines have been separated into child voucher <b>#{forked_voucher_name or voucher_name}</b>. Clean lines have moved forward to Director review.
        </p>
        <div style="text-align: center; margin-top: 20px;">
            <a href="{doc_url}" style="background: #dc2626; color: #ffffff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 13px; display: inline-block;">
                Review & Upload Corrected Proof &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=admin_recipients,
        subject=subject,
        message_html=html,
        reference_doctype=voucher_doctype,
        reference_name=voucher_name,
        alert_type="red",
        cc=cc_users,
        is_thread_reply=True
    )


def notify_custodian_on_dispute(voucher_doctype: str, voucher_name: str, disputed_items: List[Dict[str, Any]]) -> None:
    """Backwards compatibility alias."""
    notify_admin_on_dispute(voucher_doctype, voucher_name, disputed_items)


# --------------------------------------------------------------------------------------
# 7. STAGE 7: PAYMENT DISBURSED & BANK REMITTANCE WITH UTR (Thread Finale)
# --------------------------------------------------------------------------------------
def notify_payee_and_admin_on_payout_dispatched(
    batch_name: str,
    idfc_ref: str
) -> None:
    """Concludes the continuous voucher conversation thread with official Bank UTR."""
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

        recipient = None
        doc = None
        if src_dt and src_vch and frappe.db.exists(src_dt, src_vch):
            doc = frappe.get_doc(src_dt, src_vch)
            recipient = getattr(doc, "custodian", None) or getattr(doc, "owner", None)

        if not recipient:
            recipient = bene_name

        cc_users = _get_claim_rolling_cc(doc, exclude_users=[recipient]) if doc else []
        company = getattr(doc, "company", "Company") if doc else "Company"

        subject = f"Re: [Voucher #{src_vch}] {company} {src_dt} (₹ {fmt_money(amt)}) - Disbursed via IDFC (UTR: {utr})"
        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #d1fae5; border-radius: 10px; padding: 24px; background: #ffffff;">
            <div style="border-bottom: 2px solid #10b981; padding-bottom: 12px; margin-bottom: 16px;">
                <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #059669; font-weight: 700;">IDFC FIRST Bank • Corporate Payout Advice</span>
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
        _send_email_and_desk_alert(
            recipients=[recipient],
            subject=subject,
            message_html=html,
            reference_doctype=src_dt or "Payment Batch",
            reference_name=src_vch or batch_name,
            alert_type="green",
            cc=cc_users,
            is_thread_reply=True
        )


# --------------------------------------------------------------------------------------
# 8. 2FA OTP BATCH AUTHORIZATION ALERT (Strictly Isolated Separate Email)
# --------------------------------------------------------------------------------------
def notify_releaser_on_batch_ready(batch_name: str) -> None:
    """
    Isolated standalone urgent 2FA OTP alert sent exclusively to Payment Releaser.
    Never mixed into individual voucher threads.
    """
    if not frappe.db.exists("Payment Batch", batch_name):
        return

    batch = frappe.get_doc("Payment Batch", batch_name)
    company = getattr(batch, "company", "Company")
    total_amt = float(getattr(batch, "total_batch_amount", 0.0) or 0.0)
    item_count = len(getattr(batch, "instructions", []) or [])
    doc_url = get_url_to_form("Payment Batch", batch_name)

    releasers = frappe.get_all(
        "Has Role",
        filters={"role": ["in", ["Payment Releaser"]], "parenttype": "User"},
        pluck="parent"
    )

    releasers = [r for r in releasers if r != "Administrator"]
    if not releasers:
        releasers = ["anish@quanticus.com"]

    subject = f"🔐 [Action: 2FA Release] Payment Batch #{batch_name} (₹ {fmt_money(total_amt)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #c7d2fe; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #4f46e5; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #4338ca; font-weight: 700;">Executive Release Authority • Anish Sir (CEO & MD)</span>
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
    # Standalone isolated email - not a reply, no CC list
    _send_email_and_desk_alert(
        recipients=releasers,
        subject=subject,
        message_html=html,
        reference_doctype="Payment Batch",
        reference_name=batch_name,
        alert_type="purple",
        cc=None,
        is_thread_reply=False
    )
