def _get_form_url(doctype: str, docname: str) -> str:
    host = ""
    if getattr(frappe.local, "request", None) and hasattr(frappe.local.request, "host"):
        host = f"{frappe.local.request.scheme}://{frappe.local.request.host}"
    if not host:
        host = frappe.utils.get_url()
    return f"{host}/desk/{doctype.lower().replace(' ', '-')}/{docname}"

"""
AP Automation Production Notification Engine (PRD Section 6 & 8)
Enforces:
1. Single Email Conversation Threading (RFC 5322 In-Reply-To and References).
2. Dynamic Rolling CC participant accumulation across approval lifecycle.
3. Strict isolation of 2FA OTP Batch Release and compliance security alerts.
4. Desk Real-Time Notification synchronization.
"""
import re
from typing import Any, Dict, List, Optional, Tuple, Union
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
        return None

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
    fallback_roles: List[str],
    stage_keyword: Optional[str] = None
) -> List[str]:
    """
    Fetches designated approvers dynamically from AP Approval Matrix with fallback to Role.
    Supports both level_number and semantic stage keyword matching (e.g. 'Admin L1', 'Admin L2', 'Accounts', 'Director').
    """
    recipients = []

    # 1. Check Approval Matrix
    matrix_name = None
    if frappe.db.exists("DocType", "AP Approval Matrix"):
        lane_options = [document_lane]
        if document_lane in ("Petty Cash", "Petty Cash Entry"):
            lane_options = ["Petty Cash Entry", "Petty Cash"]
        elif document_lane in ("Employee Reimbursement", "Employee Reimbursement Claim"):
            lane_options = ["Employee Reimbursement Claim", "Employee Reimbursement"]
        elif document_lane in ("AP Vendor Invoice", "Vendor Invoice Claim", "Vendor Invoice"):
            lane_options = ["AP Vendor Invoice", "Vendor Invoice Claim"]
        elif document_lane in ("Event Advance Request", "Event Advance"):
            lane_options = ["Event Advance Request", "Event Advance"]

        for lane in lane_options:
            matrix_name = frappe.db.get_value(
                "AP Approval Matrix",
                {"company": company, "document_lane": lane, "is_active": 1},
                "name"
            ) or frappe.db.get_value(
                "AP Approval Matrix",
                {"document_lane": lane, "is_active": 1},
                "name"
            )
            if matrix_name:
                break

    if matrix_name:
        matrix = frappe.get_doc("AP Approval Matrix", matrix_name)
        
        # Try matching by semantic stage keyword first
        if stage_keyword:
            kw = stage_keyword.lower()
            for lvl in matrix.approval_levels:
                lvl_title = (getattr(lvl, "level_name", None) or getattr(lvl, "level_title", None) or "").lower()
                if kw in lvl_title and lvl.designated_approver:
                    recipients.append(lvl.designated_approver)
        
        # Try matching by level_number if not found
        if not recipients:
            for lvl in matrix.approval_levels:
                if lvl.level_number == level_number and lvl.designated_approver:
                    recipients.append(lvl.designated_approver)

    # 2. Fallback to Role-Based Lookup
    if not recipients and fallback_roles:
        roles_to_query = list(fallback_roles)
        if "Admin L1 Approver" in roles_to_query and "Admin Manager" not in roles_to_query:
            roles_to_query.append("Admin Manager")
        role_users = frappe.get_all(
            "Has Role",
            filters={"role": ["in", roles_to_query], "parenttype": "User"},
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
    Includes strict recipient deduplication and idempotency debouncing.
    """
    if getattr(frappe.flags, "in_test", False) or getattr(frappe.flags, "mute_emails", False):
        return
    if not recipients:
        return

    # Idempotency / Debounce check: Prevent duplicate email triggers within 60 seconds
    try:
        import hashlib
        subject_hash = hashlib.md5(subject.strip().encode("utf-8")).hexdigest()
        dedup_key = f"ap_email_dedup:{reference_doctype}:{reference_name}:{subject_hash}"
        if frappe.cache().get_value(dedup_key):
            return  # Suppress duplicate email sent within debounce window
        frappe.cache().set_value(dedup_key, 1, expires_in_sec=60)
    except Exception:
        pass

    # Deduplicate Primary Recipients (case-insensitive)
    valid_recipients = []
    desk_users = []
    for r in recipients:
        if not r:
            continue
        desk_users.append(str(r).strip())
        resolved = _resolve_email(r)
        if resolved and resolved.strip():
            clean_email = resolved.strip()
            if clean_email.lower() not in [x.lower() for x in valid_recipients]:
                valid_recipients.append(clean_email)

    # Deduplicate CC Recipients (Exclude any email already present in To:)
    valid_cc = []
    if cc:
        recipients_lower = [x.lower() for x in valid_recipients]
        for c in cc:
            if not c:
                continue
            resolved_cc = _resolve_email(c)
            if resolved_cc and resolved_cc.strip():
                clean_cc = resolved_cc.strip()
                if clean_cc.lower() not in recipients_lower and clean_cc.lower() not in [x.lower() for x in valid_cc]:
                    valid_cc.append(clean_cc)

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
            ref_link = f"<br><a href='/desk/{reference_doctype.lower().replace(' ', '-')}/{reference_name}'>View {reference_name}</a>" if reference_name else ""
            frappe.publish_realtime(
                event="msgprint",
                message={
                    "message": f"<b>{subject}</b>{ref_link}",
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
    doc_url = _get_form_url(voucher_doctype, voucher_name)

    l1_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=1,
        fallback_roles=["Admin L1 Approver", "Admin Manager"], stage_keyword="Admin L1"
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
    doc_url = _get_form_url(voucher_doctype, voucher_name)

    l2_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=2,
        fallback_roles=["Admin L2 Approver"], stage_keyword="Admin L2"
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
    doc_url = _get_form_url(voucher_doctype, voucher_name)

    accounts_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=1,
        fallback_roles=["Accounts L1 Auditor"], stage_keyword="Accounts"
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
    doc_url = _get_form_url(voucher_doctype, voucher_name)

    director_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=4,
        fallback_roles=["Accounts Director", "Director Tier"], stage_keyword="Director"
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


def notify_on_director_sanction_approved(voucher_doctype: str, voucher_name: str) -> None:
    """Notifies Custodian, Admin, and Payment Releaser when Director sanctions voucher for payment."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or getattr(doc, "net_payable_amount", 0.0) or 0.0)
    doc_url = _get_form_url(voucher_doctype, voucher_name)

    recipient = getattr(doc, "custodian", None) or getattr(doc, "owner", None)
    releasers = _get_role_recipients(["Payment Releaser", "Accounts Manager"])
    cc_users = _get_claim_rolling_cc(doc, exclude_users=[recipient] + releasers)

    all_recipients = [recipient] + [r for r in releasers if r and r != recipient]

    subject = f"Re: [Voucher #{voucher_name}] {company} {voucher_doctype} (₹ {fmt_money(amount)}) - Director Sanctioned (Approved for Payment)"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #bbf7d0; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #16a34a; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #15803d; font-weight: 700;">Executive Sanction Completed</span>
            <h2 style="margin: 4px 0 0 0; color: #14532d; font-size: 20px;">Voucher Approved for Payment</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Accounts Director has sanctioned voucher <b>#{voucher_name}</b> for <b>{company}</b>. The claim has passed all approval tiers and is queued for corporate banking payment release.
        </p>
        <div style="background: #f0fdf4; border: 1px solid #dcfce7; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #166534;">Approved Amount: <b style="font-size: 18px; color: #16a34a;">₹ {fmt_money(amount)}</b></div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #16a34a; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                View Voucher Details &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=all_recipients,
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
    doc_url = _get_form_url(voucher_doctype, voucher_name)

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
    doc_url = _get_form_url(voucher_doctype, voucher_name)

    accounts_users = _get_matrix_or_role_approvers(
        company=company,
        document_lane=voucher_doctype,
        level_number=1,
        fallback_roles=["Accounts L1 Auditor"], stage_keyword="Accounts"
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

    # Filter only enabled, active users
    active_releasers = []
    for r in releasers:
        if r != "Administrator" and frappe.db.get_value("User", r, "enabled"):
            active_releasers.append(r)

    if not active_releasers:
        directors = frappe.get_all(
            "Has Role",
            filters={"role": ["in", ["Accounts Director", "Director Tier"]], "parenttype": "User"},
            pluck="parent"
        )
        active_releasers = [d for d in directors if d != "Administrator" and frappe.db.get_value("User", d, "enabled")]

    releasers = active_releasers
    if not releasers:
        return

    subject = f"🔐 [Action: 2FA Release] Payment Batch #{batch_name} (₹ {fmt_money(total_amt)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #c7d2fe; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #4f46e5; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #4338ca; font-weight: 700;">Executive Release Authority • Payment Releaser</span>
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


@frappe.whitelist()
def send_pending_petty_cash_reminders() -> Dict[str, Any]:
    """
    Scheduled cron job to remind approvers of vouchers pending action
    (e.g., Friday submissions pending by Tuesday morning).
    """
    pending_vouchers = frappe.get_all(
        "Petty Cash Entry",
        filters={"status": ["in", ["Pending Admin L1", "Pending Admin L2", "Submitted", "L1 Verified"]]},
        fields=["name", "company", "custodian", "status", "total_amount", "creation", "admin_l1_approver", "admin_l2_approver", "designated_approver"]
    )

    sent_count = 0
    for vch in pending_vouchers:
        amt_str = fmt_money(vch.total_amount, currency="INR")
        target_approvers = []

        if vch.status == "Pending Admin L1":
            target_approvers = [vch.admin_l1_approver] if vch.admin_l1_approver else _get_matrix_or_role_approvers(vch.company, "Petty Cash Entry", 1, ["Admin L1 Approver"], stage_keyword="Admin L1")
        elif vch.status == "Pending Admin L2":
            target_approvers = [vch.admin_l2_approver] if vch.admin_l2_approver else _get_matrix_or_role_approvers(vch.company, "Petty Cash Entry", 2, ["Admin L2 Approver"], stage_keyword="Admin L2")
        elif vch.status == "Submitted":
            target_approvers = _get_matrix_or_role_approvers(vch.company, "Petty Cash Entry", 3, ["Accounts L1 Auditor"], stage_keyword="Accounts")
        elif vch.status == "L1 Verified":
            target_approvers = _get_matrix_or_role_approvers(vch.company, "Petty Cash Entry", 4, ["Accounts Director", "Director Tier"], stage_keyword="Director")

        if target_approvers:
            subject = f"[AP-PettyCash] [Reminder] [Action Required] [Voucher #{vch.name}] {vch.company} ({amt_str}) - {vch.status}"
            msg_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px;">
                <div style="background: #eff6ff; padding: 12px; border-radius: 6px; margin-bottom: 16px;">
                    <h3 style="color: #1e40af; margin: 0;">⏰ Petty Cash Approval Reminder</h3>
                </div>
                <p>Dear Approver,</p>
                <p>This is an automated reminder that Petty Cash Voucher <b>#{vch.name}</b> (Amount: <b>{amt_str}</b>) submitted by <b>{vch.custodian}</b> is currently pending your review under stage <b>{vch.status}</b>.</p>
                <p>Please review and take action promptly.</p>
                <div style="margin-top: 20px;">
                    <a href="{get_url_to_form('Petty Cash Entry', vch.name)}" style="background: #2563eb; color: #ffffff; padding: 10px 18px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                        Open Voucher #{vch.name}
                    </a>
                </div>
            </div>
            """
            _send_email_and_desk_alert(
                recipients=target_approvers,
                subject=subject,
                message_html=msg_html,
                reference_doctype="Petty Cash Entry",
                reference_name=vch.name,
                alert_type="orange",
                is_thread_reply=True
            )
            sent_count += 1

    return {"status": "SUCCESS", "reminders_sent": sent_count}



def notify_admin_l1_on_l2_return(voucher_doctype: str, voucher_name: str, reason: str) -> None:
    """Notifies Admin L1 Supervisor when Admin L2 Head returns a claim back to L1."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    l1_user = getattr(doc, "admin_l1_approver", None)
    if not l1_user:
        l1_user = _get_matrix_or_role_approvers(company, voucher_doctype, 1, ["Admin L1 Approver"])
    else:
        l1_user = [l1_user]

    cc_users = _get_claim_rolling_cc(doc, exclude_users=l1_user)
    doc_url = _get_form_url(voucher_doctype, voucher_name)

    subject = f"Re: [Voucher #{voucher_name}] {company} {voucher_doctype} (₹ {fmt_money(amount)}) - Returned to L1 by Admin Head"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fecaca; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #dc2626; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #dc2626; font-weight: 700;">Revision Required • Admin L1</span>
            <h2 style="margin: 4px 0 0 0; color: #991b1b; font-size: 20px;">Returned by Admin Department Head</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Admin Department Head returned voucher <b>#{voucher_name}</b> for <b>{company}</b> back to Level 1 review.
        </p>
        <div style="background: #fef2f2; border-left: 4px solid #dc2626; padding: 12px 16px; margin: 16px 0; border-radius: 0 8px 8px 0;">
            <div style="font-size: 12px; text-transform: uppercase; font-weight: 700; color: #b91c1c; margin-bottom: 4px;">Return Reason:</div>
            <p style="margin: 0; color: #7f1d1d; font-size: 14px; font-weight: 600;">{reason}</p>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #dc2626; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Review Voucher &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=l1_user,
        subject=subject,
        message_html=html,
        reference_doctype=voucher_doctype,
        reference_name=voucher_name,
        alert_type="red",
        cc=cc_users,
        is_thread_reply=True
    )


def notify_admin_l2_on_direct_resubmit(voucher_doctype: str, voucher_name: str) -> None:
    """Notifies Admin L2 Head when Reception resubmits directly after corrections (L1 skipped)."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    l2_users = getattr(doc, "admin_l2_approver", None)
    if not l2_users:
        l2_users = _get_matrix_or_role_approvers(company, voucher_doctype, 2, ["Admin L2 Approver"])
    else:
        l2_users = [l2_users]

    cc_users = _get_claim_rolling_cc(doc, exclude_users=l2_users)
    doc_url = _get_form_url(voucher_doctype, voucher_name)

    subject = f"Re: [Voucher #{voucher_name}] {company} {voucher_doctype} (₹ {fmt_money(amount)}) - Resubmitted by Reception for Head Sign-off"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #c7d2fe; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #4f46e5; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #4338ca; font-weight: 700;">Direct Resubmission • Admin L2 Head</span>
            <h2 style="margin: 4px 0 0 0; color: #1e1b4b; font-size: 20px;">Corrections Completed by Reception</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Reception / Custodian has applied requested bill corrections and resubmitted voucher <b>#{voucher_name}</b> directly for your final sign-off (L1 intermediate review skipped).
        </p>
        <div style="background: #eef2ff; border: 1px solid #e0e7ff; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #4338ca;">Total Resubmitted Value: <b style="font-size: 18px; color: #4f46e5;">₹ {fmt_money(amount)}</b></div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #4f46e5; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Review & Sign-Off &rarr;
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
        alert_type="blue",
        cc=cc_users,
        is_thread_reply=True
    )

def notify_accounts_l1_sla_reminder(voucher_doctype: str, voucher_name: str) -> None:
    """Dispatches a 24-hour SLA reminder to Accounts L1 Auditor."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    admin_date = getattr(doc, "admin_l2_approval_date", None)
    admin_date_str = frappe.utils.format_datetime(admin_date, "dd-MM-yyyy hh:mm a") if admin_date else "Yesterday"

    l1_auditors = _get_matrix_or_role_approvers(company, voucher_doctype, 3, ["Accounts L1 Auditor"])
    cc_users = _get_claim_rolling_cc(doc, exclude_users=l1_auditors)
    doc_url = _get_form_url(voucher_doctype, voucher_name)

    subject = f"[AP-PettyCash] [SLA Reminder] [Action Required] [Voucher #{voucher_name}] {company} (₹ {fmt_money(amount)}) - Accounts L1 Audit Pending > 24 Hours"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fde68a; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #d97706; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #d97706; font-weight: 700;">24-Hour SLA Reminder • Accounts L1</span>
            <h2 style="margin: 4px 0 0 0; color: #92400e; font-size: 20px;">Accounts L1 Audit Pending Overdue</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Petty Cash Voucher <b>#{voucher_name}</b> for <b>{company}</b> was approved and submitted by Admin Department Head on <b>{admin_date_str}</b>.
        </p>
        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px 16px; margin: 16px 0; border-radius: 0 8px 8px 0;">
            <div style="font-size: 12px; text-transform: uppercase; font-weight: 700; color: #b45309; margin-bottom: 4px;">SLA Notice:</div>
            <p style="margin: 0; color: #78350f; font-size: 14px;">This voucher has exceeded the <b>1-Day (24-Hour)</b> initial review SLA. Please verify the receipts and approve or return without delay.</p>
        </div>
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin: 16px 0;">
            <div style="font-size: 13px; color: #475569;">Voucher Total: <b style="font-size: 17px; color: #0f172a;">₹ {fmt_money(amount)}</b></div>
            <div style="font-size: 13px; color: #475569; margin-top: 4px;">Custodian: <b>{getattr(doc, 'custodian', 'Front Desk')}</b></div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #d97706; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Open Voucher & Verify Audit &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=l1_auditors,
        subject=subject,
        message_html=html,
        reference_doctype=voucher_doctype,
        reference_name=voucher_name,
        alert_type="orange",
        cc=cc_users,
        is_thread_reply=True
    )


def notify_accounts_director_sla_escalation(voucher_doctype: str, voucher_name: str) -> None:
    """Dispatches 24-hour SLA Escalation alert to Accounts Director / Director Tier."""
    if not frappe.db.exists(voucher_doctype, voucher_name):
        return

    doc = frappe.get_doc(voucher_doctype, voucher_name)
    company = getattr(doc, "company", "Company")
    amount = float(getattr(doc, "total_amount", 0.0) or 0.0)
    admin_date = getattr(doc, "admin_l2_approval_date", None)
    admin_date_str = frappe.utils.format_datetime(admin_date, "dd-MM-yyyy hh:mm a") if admin_date else "Yesterday"

    directors = _get_matrix_or_role_approvers(company, voucher_doctype, 4, ["Accounts Director", "Director Tier"])
    l1_auditors = _get_matrix_or_role_approvers(company, voucher_doctype, 3, ["Accounts L1 Auditor"])
    cc_users = _get_claim_rolling_cc(doc, exclude_users=directors)
    for auditor in l1_auditors:
        if auditor not in directors and auditor not in cc_users:
            cc_users.append(auditor)

    doc_url = _get_form_url(voucher_doctype, voucher_name)

    subject = f"[AP-PettyCash] [🚨 SLA Escalation] [Voucher #{voucher_name}] {company} (₹ {fmt_money(amount)}) - Accounts L1 Review Overdue (> 24 Hours)"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fecaca; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #dc2626; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #dc2626; font-weight: 700;">🚨 Executive Escalation • Accounts SLA</span>
            <h2 style="margin: 4px 0 0 0; color: #991b1b; font-size: 20px;">Accounts L1 24h Review SLA Breached</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Petty Cash Voucher <b>#{voucher_name}</b> for <b>{company}</b> (Total: <b>₹ {fmt_money(amount)}</b>) has been awaiting Accounts L1 audit for <b>over 24 hours</b> since Admin Department Head sign-off on <b>{admin_date_str}</b>.
        </p>
        <div style="background: #fef2f2; border-left: 4px solid #dc2626; padding: 12px 16px; margin: 16px 0; border-radius: 0 8px 8px 0;">
            <div style="font-size: 12px; text-transform: uppercase; font-weight: 700; color: #b91c1c; margin-bottom: 4px;">Escalation Reason:</div>
            <p style="margin: 0; color: #7f1d1d; font-size: 14px; font-weight: 600;">Accounts L1 has not verified, disputed, or returned the voucher within the mandatory 1-day turnaround SLA.</p>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #dc2626; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                View Overdue Voucher &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=directors,
        subject=subject,
        message_html=html,
        reference_doctype=voucher_doctype,
        reference_name=voucher_name,
        alert_type="red",
        cc=cc_users,
        is_thread_reply=True
    )


@frappe.whitelist()
def check_and_escalate_accounts_l1_slas() -> Dict[str, Any]:
    """
    Automated SLA Monitor:
    Scans all vouchers in 'Submitted' status (Accounts L1 stage).
    If a voucher has been pending for >= 24 hours (1 day) without L1 action:
      1. Dispatches Reminder to Accounts L1 Auditor.
      2. Dispatches Escalation Alert to Accounts Director.
      3. Records escalation in audit trail to avoid redundant duplicate alerts.
    Time Complexity: O(N) where N is active Submitted vouchers (typically < 50).
    """
    submitted_vouchers = frappe.get_all(
        "Petty Cash Entry",
        filters={"status": "Submitted"},
        fields=["name", "company", "total_amount", "admin_l2_approval_date", "creation", "modified"]
    )

    now = frappe.utils.now_datetime()
    escalated_count = 0

    for vch in submitted_vouchers:
        # Determine baseline submission time from admin_l2_approval_date or creation
        submission_time = vch.admin_l2_approval_date or vch.modified or vch.creation
        if not submission_time:
            continue

        submission_dt = frappe.utils.get_datetime(submission_time)
        hours_elapsed = (now - submission_dt).total_seconds() / 3600.0

        if hours_elapsed >= 24.0:
            doc = frappe.get_doc("Petty Cash Entry", vch.name)

            # Check if 24h SLA escalation has already been stamped for this cycle
            already_escalated = False
            for trail in (doc.approval_trail or []):
                if getattr(trail, "level_name", "") == "Accounts L1 24h SLA Escalation":
                    trail_dt = frappe.utils.get_datetime(getattr(trail, "action_timestamp", None) or now)
                    if trail_dt >= submission_dt:
                        already_escalated = True
                        break

            if not already_escalated:
                # 1. Notify Accounts L1 Auditor (Reminder)
                notify_accounts_l1_sla_reminder("Petty Cash Entry", doc.name)

                # 2. Notify Accounts Director (Escalation)
                notify_accounts_director_sla_escalation("Petty Cash Entry", doc.name)

                # 3. Record in audit trail
                doc.append("approval_trail", {
                    "level_number": 3,
                    "level_name": "Accounts L1 24h SLA Escalation",
                    "action_taken_by": "Administrator",
                    "action": "APPROVED",
                    "action_timestamp": now,
                    "remarks": f"1-Day (24h) SLA breached ({hours_elapsed:.1f} hours elapsed). Reminder sent to Accounts L1; Escalation sent to Accounts Director."
                })
                doc.save(ignore_permissions=True)
                frappe.db.commit()
                escalated_count += 1

    return {
        "status": "SUCCESS",
        "scanned_count": len(submitted_vouchers),
        "escalated_count": escalated_count
    }

import frappe

def notify_on_vendor_po_signed(po_name: str) -> None:
    """
    Dispatches automated post-signature notifications to both parties:
    1. Vendor (Email Confirmation with Signed Certificate link).
    2. Internal SPOC & Finance Team (Email + Desk Realtime Alert).
    3. Document Timeline Audit Stamp.
    """
    if not frappe.db.exists("AP Purchase Order", po_name):
        return

    po = frappe.get_doc("AP Purchase Order", po_name)
    company = po.company_entity
    vendor_name = po.vendor_name
    grand_total = float(po.grand_total or 0.0)
    signed_by = po.vendor_signed_by or "Authorized Signatory"
    signed_time = frappe.utils.format_datetime(po.vendor_signed_timestamp, "dd-MM-yyyy hh:mm a") if po.vendor_signed_timestamp else "Just now"
    ip = po.vendor_signed_ip or "Remote IP"

    base_url = frappe.utils.get_url()
    desk_url = f"{base_url}/desk/ap-purchase-order/{po.name}"
    portal_url = po.vendor_sign_url or f"{base_url}/po-sign?po={po.name}"

    # 1. Internal SPOC & Accounts Alert
    recipients = []
    if po.spoc_email and po.spoc_email not in recipients:
        recipients.append(po.spoc_email)
    if po.company_contact_email and po.company_contact_email not in recipients:
        recipients.append(po.company_contact_email)

    if not recipients:
        recipients = ["admin@example.com"]

    internal_subject = f"✅ [PO Signed & Active] #{po.name} - {vendor_name} (₹ {grand_total:,.2f})"
    internal_html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #bbf7d0; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #16a34a; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #16a34a; font-weight: 700;">🎉 Contract Executed • Vendor Signature Complete</span>
            <h2 style="margin: 4px 0 0 0; color: #14532d; font-size: 20px;">Purchase Order #{po.name} is now ACTIVE</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Vendor representative <b>{signed_by}</b> from <b>{vendor_name}</b> has accepted and digitally signed Purchase Order <b>#{po.name}</b>.
        </p>
        <div style="background: #f0fdf4; border: 1px solid #86efac; border-radius: 8px; padding: 14px; margin: 16px 0;">
            <div style="font-size: 13px; color: #166534;">Contracted Value: <b style="font-size: 18px; color: #0f172a;">₹ {grand_total:,.2f}</b></div>
            <div style="font-size: 13px; color: #166534; margin-top: 4px;">Advance Obligation: <b>₹ {float(po.advance_amount or 0.0):,.2f} ({po.advance_percentage or '0%'})</b></div>
            <div style="font-size: 12px; color: #475569; margin-top: 6px; padding-top: 6px; border-top: 1px solid #bbf7d0;">
                Signed Timestamp: <b>{signed_time}</b> | IP Address: <code>{ip}</code>
            </div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{desk_url}" style="background: #16a34a; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Open Purchase Order in AP Desk &rarr;
            </a>
        </div>
    </div>
    """

    try:
        frappe.sendmail(
            recipients=recipients,
            subject=internal_subject,
            message=internal_html,
            reference_doctype="AP Purchase Order",
            reference_name=po.name,
            now=False
        )
    except Exception as e:
        frappe.log_error(f"Internal PO signed alert: {e}")

    # 2. Vendor Confirmation Email
    if po.vendor_email:
        vendor_subject = f"📄 Executed Purchase Order #{po.name} - {company}"
        vendor_html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #e2e8f0; border-radius: 10px; padding: 24px; background: #ffffff;">
            <div style="border-bottom: 2px solid #1e3a8a; padding-bottom: 12px; margin-bottom: 16px;">
                <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #1e3a8a; font-weight: 700;">Digital Signature Confirmation</span>
                <h2 style="margin: 4px 0 0 0; color: #0f172a; font-size: 20px;">Thank You for Executing PO #{po.name}</h2>
            </div>
            <p style="color: #334155; font-size: 14px; line-height: 1.5;">
                Dear {po.vendor_contact_person or vendor_name},<br><br>
                This confirms that Purchase Order <strong>#{po.name}</strong> from <strong>{company}</strong> for <strong>₹ {grand_total:,.2f}</strong> has been successfully signed and validated on {signed_time}.
            </p>
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin: 16px 0;">
                <div style="font-size: 13px; color: #475569;">Company SPOC: <b>{po.spoc_name} ({po.spoc_email})</b></div>
                <div style="font-size: 13px; color: #475569; margin-top: 4px;">Signer: <b>{signed_by}</b></div>
                <div style="font-size: 12px; color: #0284c7; margin-top: 6px; font-family: monospace;">SHA-256 Hash: {po.signatory_signature_hash}</div>
            </div>
            <p style="color: #64748b; font-size: 13px;">
                You can review or download your digitally signed certificate copy anytime using the link below:
            </p>
            <div style="text-align: center; margin-top: 20px;">
                <a href="{portal_url}" style="background: #1e3a8a; color: #ffffff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 13.5px; display: inline-block;">
                    View Executed Certificate &rarr;
                </a>
            </div>
        </div>
        """
        try:
            frappe.sendmail(
                recipients=[po.vendor_email],
                subject=vendor_subject,
                message=vendor_html,
                reference_doctype="AP Purchase Order",
                reference_name=po.name,
                now=False
            )
        except Exception as e:
            frappe.log_error(f"Vendor PO executed confirmation email: {e}")

    # 3. Add Document Timeline Audit Stamp
    try:
        po.add_comment(
            "Comment",
            text=f"🖋️ <b>Digital E-Signature Confirmed & Verified</b><br>"
                 f"Signed by: <b>{signed_by}</b><br>"
                 f"IP Address: <code>{ip}</code><br>"
                 f"Timestamp: <code>{signed_time}</code><br>"
                 f"Status transitioned to: <span class='indicator-pill green'>Active PO</span>"
        )
    except Exception as e:
        frappe.log_error(f"PO timeline stamp error: {e}")

    # 4. Real-time in-app Desk alert
    try:
        frappe.publish_realtime(
            event="msgprint",
            message=f"🎉 Purchase Order #{po.name} was just digitally signed by {vendor_name} ({signed_by})!",
            user=po.spoc_email
        )
    except Exception:
        pass


# --------------------------------------------------------------------------------------

def notify_on_vendor_po_rejected(po_name: str, rejection_reason: str = "Commercial terms discrepancy") -> None:
    """Dispatches automated notification to SPOC and Company contact when vendor rejects PO."""
    if not frappe.db.exists("AP Purchase Order", po_name):
        return

    po = frappe.get_doc("AP Purchase Order", po_name)
    company = po.company_entity
    vendor_name = po.vendor_name
    grand_total = float(po.grand_total or 0.0)

    recipients = []
    if po.spoc_email and po.spoc_email not in recipients:
        recipients.append(po.spoc_email)
    if po.company_contact_email and po.company_contact_email not in recipients:
        recipients.append(po.company_contact_email)

    if not recipients:
        recipients = ["admin@example.com"]

    base_url = frappe.utils.get_url()
    desk_url = f"{base_url}/desk/ap-purchase-order/{po.name}"

    subject = f"❌ [PO Rejected by Vendor] #{po.name} - {vendor_name} (₹ {grand_total:,.2f})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fecaca; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #ef4444; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #dc2626; font-weight: 700;">Action Required • Vendor Rejection</span>
            <h2 style="margin: 4px 0 0 0; color: #991b1b; font-size: 20px;">Purchase Order #{po.name} Declined by Vendor</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Vendor <b>{vendor_name}</b> has declined to sign Purchase Order <b>#{po.name}</b>.
        </p>
        <div style="background: #fef2f2; border: 1px solid #fee2e2; border-radius: 8px; padding: 14px; margin: 16px 0;">
            <div style="font-size: 13px; color: #991b1b;">Rejection Reason: <b style="color: #0f172a;">{rejection_reason}</b></div>
            <div style="font-size: 13px; color: #991b1b; margin-top: 4px;">PO Amount: <b>₹ {grand_total:,.2f}</b></div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{desk_url}" style="background: #ef4444; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Review Purchase Order in AP Desk &rarr;
            </a>
        </div>
    </div>
    """

    try:
        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=html,
            reference_doctype="AP Purchase Order",
            reference_name=po.name,
            now=False
        )
    except Exception as e:
        frappe.log_error(f"PO Rejection email dispatch notification: {e}")

    try:
        po.add_comment(
            "Comment",
            text=f"❌ <b>Vendor Declined / Rejected PO</b><br>"
                 f"Reason: <b>{rejection_reason}</b><br>"
                 f"Status transitioned to: <span class='indicator-pill red'>Rejected by Vendor</span>"
        )
    except Exception as e:
        frappe.log_error(f"PO rejection timeline stamp error: {e}")


# VENDOR INVOICE CLAIM NOTIFICATIONS (PRD Stage 3, 4, 6, 7 & Dispute)
# --------------------------------------------------------------------------------------
def notify_vendor_claim_submitted(claim_name: str) -> None:
    """Triggered on initial filing. Alerts Manager (Level 1 in AP Matrix or Reports To)."""
    if not frappe.db.exists("Vendor Invoice Claim", claim_name):
        return
    doc = frappe.get_doc("Vendor Invoice Claim", claim_name)
    company = getattr(doc, "company", "Company")
    vendor = getattr(doc, "vendor_name", None) or getattr(doc, "vendor", "Vendor")
    amount = float(getattr(doc, "net_payable_amount", 0.0) or getattr(doc, "total_invoice_amount", 0.0) or 0.0)
    doc_url = _get_form_url("Vendor Invoice Claim", claim_name)

    recipients = []
    mgr_user = getattr(doc, "designated_approver", None)

    # 1. Primary Dynamic Dispatch: Resolve claimant's active HRMS Reporting Manager (O(1))
    if not mgr_user and getattr(doc, "owner", None):
        emp = frappe.db.get_value("Employee", {"user_id": doc.owner, "status": "Active"}, ["reports_to"], as_dict=True)
        if emp and emp.reports_to:
            mgr_user = frappe.db.get_value("Employee", emp.reports_to, "user_id")

    if mgr_user:
        recipients.append(mgr_user)
        # Check active leave delegation for manager
        try:
            from ap_automation.services.security import resolve_acting_approver
            acting_mgr = resolve_acting_approver(mgr_user)
            if acting_mgr and acting_mgr != mgr_user and acting_mgr not in recipients:
                recipients.append(acting_mgr)
        except Exception:
            pass
    else:
        # Fallback to Matrix / Role ONLY if claimant has no HRMS manager assigned
        recipients = _get_matrix_or_role_approvers(
            company=company,
            document_lane="AP Vendor Invoice",
            level_number=1,
            fallback_roles=["Admin L1 Approver", "Admin Manager"],
            stage_keyword="Manager"
        )

    subject = f"[Invoice #{claim_name}] {company} - {vendor} (₹ {fmt_money(amount)}) Submitted for Manager Review"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fed7aa; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #ea580c; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #c2410c; font-weight: 700;">Vendor Spend Gate • Stage 1 Manager Approval</span>
            <h2 style="margin: 4px 0 0 0; color: #7c2d12; font-size: 20px;">New Vendor Invoice Submitted</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            A new vendor invoice claim has been submitted for <b>{company}</b> and requires your operational review as Reporting Manager.
        </p>
        <div style="background: #fff7ed; border: 1px solid #ffedd5; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #9a3412; margin-bottom: 4px;">Vendor: <b style="color: #0f172a;">{vendor}</b></div>
            <div style="font-size: 13px; color: #9a3412; margin-bottom: 4px;">Invoice Number: <b style="color: #0f172a;">#{doc.tax_invoice_number or 'DRAFT'}</b></div>
            <div style="font-size: 13px; color: #9a3412; margin-bottom: 4px;">Intake Route: <b>{doc.invoice_type}</b></div>
            <div style="font-size: 18px; font-weight: 800; color: #ea580c; margin-top: 8px;">Net Payable: ₹ {fmt_money(amount)}</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #ea580c; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Review Claim & Approve &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=recipients,
        subject=subject,
        message_html=html,
        reference_doctype="Vendor Invoice Claim",
        reference_name=claim_name,
        alert_type="orange",
        cc=[doc.owner],
        is_thread_reply=False
    )


def notify_vendor_claim_manager_approved(claim_name: str) -> None:
    """Triggered after Manager signs off. Alerts HoD (Level 2 in AP Matrix)."""
    if not frappe.db.exists("Vendor Invoice Claim", claim_name):
        return
    doc = frappe.get_doc("Vendor Invoice Claim", claim_name)
    company = getattr(doc, "company", "Company")
    vendor = getattr(doc, "vendor_name", None) or getattr(doc, "vendor", "Vendor")
    amount = float(getattr(doc, "net_payable_amount", 0.0) or 0.0)
    doc_url = _get_form_url("Vendor Invoice Claim", claim_name)

    recipients = _get_matrix_or_role_approvers(
        company=company,
        document_lane="AP Vendor Invoice",
        level_number=2,
        fallback_roles=["Admin L2 Approver", "HoD"],
        stage_keyword="HoD"
    )
    subject = f"[Invoice #{claim_name}] {company} - {vendor} (₹ {fmt_money(amount)}) Approved by Manager -> Awaiting HoD"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fed7aa; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #2563eb; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #1d4ed8; font-weight: 700;">Department Gate • Stage 2 HoD Approval</span>
            <h2 style="margin: 4px 0 0 0; color: #1e3a8a; font-size: 20px;">Manager Approved Vendor Claim</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Reporting Manager <b>{doc.manager_approver or 'Manager'}</b> has approved this invoice for <b>{vendor}</b>. It now requires your Departmental sign-off.
        </p>
        <div style="background: #eff6ff; border: 1px solid #dbeafe; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #1e40af; margin-bottom: 4px;">Vendor: <b style="color: #0f172a;">{vendor}</b></div>
            <div style="font-size: 18px; font-weight: 800; color: #1d4ed8;">Net Disbursal: ₹ {fmt_money(amount)}</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #2563eb; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Review & Sanction as HoD &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=recipients,
        subject=subject,
        message_html=html,
        reference_doctype="Vendor Invoice Claim",
        reference_name=claim_name,
        alert_type="blue",
        cc=[doc.owner, doc.manager_approver],
        is_thread_reply=True
    )


def notify_vendor_claim_hod_approved(claim_name: str) -> None:
    """
    Triggered after HoD signs off.
    If Net > 2L: Alerts Business Head / Director (Level 3 in AP Matrix).
    Else: Alerts Accounts L1 (Level 4 in AP Matrix - Gokulnath).
    """
    if not frappe.db.exists("Vendor Invoice Claim", claim_name):
        return
    doc = frappe.get_doc("Vendor Invoice Claim", claim_name)
    company = getattr(doc, "company", "Company")
    vendor = getattr(doc, "vendor_name", None) or getattr(doc, "vendor", "Vendor")
    amount = float(getattr(doc, "net_payable_amount", 0.0) or 0.0)
    thresh = float(getattr(doc, "director_threshold", 200000.0) or 200000.0)
    doc_url = _get_form_url("Vendor Invoice Claim", claim_name)

    if amount > thresh:
        recipients = _get_matrix_or_role_approvers(
            company=company,
            document_lane="AP Vendor Invoice",
            level_number=3,
            fallback_roles=["Accounts Director", "Director Tier"],
            stage_keyword="Director"
        )
        bus_head = frappe.db.get_value("Company", company, "ap_business_head")
        if bus_head and bus_head not in recipients:
            recipients.append(bus_head)

        subject = f"[HIGH VALUE > ₹2L] [Invoice #{claim_name}] {company} - {vendor} (₹ {fmt_money(amount)}) Awaiting Director Sanction"
        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #e9d5ff; border-radius: 10px; padding: 24px; background: #ffffff;">
            <div style="border-bottom: 2px solid #7c3aed; padding-bottom: 12px; margin-bottom: 16px;">
                <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #6d28d9; font-weight: 700;">Executive Governance • High-Value Signoff</span>
                <h2 style="margin: 4px 0 0 0; color: #581c87; font-size: 20px;">Vendor Claim Escalated to Director Tier</h2>
            </div>
            <p style="color: #334155; font-size: 14px; line-height: 1.5;">
                This claim for <b>{vendor}</b> exceeds the ₹2,00,000 threshold and requires your executive sign-off as Business Head / Executive Director.
            </p>
            <div style="background: #faf5ff; border: 1px solid #f3e8ff; border-radius: 8px; padding: 16px; margin: 20px 0;">
                <div style="font-size: 13px; color: #6b21a8; margin-bottom: 4px;">Vendor: <b style="color: #0f172a;">{vendor}</b></div>
                <div style="font-size: 20px; font-weight: 800; color: #7c3aed;">Total Value: ₹ {fmt_money(amount)}</div>
            </div>
            <div style="text-align: center; margin-top: 24px;">
                <a href="{doc_url}" style="background: #7c3aed; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                    Review & Authorize as Director &rarr;
                </a>
            </div>
        </div>
        """
    else:
        recipients = _get_matrix_or_role_approvers(
            company=company,
            document_lane="AP Vendor Invoice",
            level_number=4,
            fallback_roles=["Accounts L1 Auditor", "Accounts User"],
            stage_keyword="Accounts L1"
        )
        subject = f"[Invoice #{claim_name}] {company} - {vendor} (₹ {fmt_money(amount)}) Approved by HoD -> Ready for Accounts L1 Audit"
        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #bfdbfe; border-radius: 10px; padding: 24px; background: #ffffff;">
            <div style="border-bottom: 2px solid #2563eb; padding-bottom: 12px; margin-bottom: 16px;">
                <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #1d4ed8; font-weight: 700;">Finance Audit Gate • Accounts L1</span>
                <h2 style="margin: 4px 0 0 0; color: #1e3a8a; font-size: 20px;">Ready for Accounts L1 Verification & Tally Entry</h2>
            </div>
            <p style="color: #334155; font-size: 14px; line-height: 1.5;">
                Departmental HoD approval is complete for <b>{vendor}</b>. Please complete the 3-Way Match audit and record the Tally Voucher Reference.
            </p>
            <div style="background: #eff6ff; border: 1px solid #dbeafe; border-radius: 8px; padding: 16px; margin: 20px 0;">
                <div style="font-size: 13px; color: #1e40af; margin-bottom: 4px;">Vendor: <b style="color: #0f172a;">{vendor}</b></div>
                <div style="font-size: 18px; font-weight: 800; color: #2563eb;">Net Disbursal: ₹ {fmt_money(amount)}</div>
            </div>
            <div style="text-align: center; margin-top: 24px;">
                <a href="{doc_url}" style="background: #2563eb; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                    Audit 3-Way Match & Post Tally Ref &rarr;
                </a>
            </div>
        </div>
        """

    _send_email_and_desk_alert(
        recipients=recipients,
        subject=subject,
        message_html=html,
        reference_doctype="Vendor Invoice Claim",
        reference_name=claim_name,
        alert_type="blue",
        cc=[doc.owner, doc.manager_approver, doc.hod_approver],
        is_thread_reply=True
    )


def notify_vendor_claim_director_approved(claim_name: str) -> None:
    """Triggered after Director signs off. Alerts Accounts L1 (Level 4 in AP Matrix - Gokulnath)."""
    if not frappe.db.exists("Vendor Invoice Claim", claim_name):
        return
    doc = frappe.get_doc("Vendor Invoice Claim", claim_name)
    company = getattr(doc, "company", "Company")
    vendor = getattr(doc, "vendor_name", None) or getattr(doc, "vendor", "Vendor")
    amount = float(getattr(doc, "net_payable_amount", 0.0) or 0.0)
    doc_url = _get_form_url("Vendor Invoice Claim", claim_name)

    recipients = _get_matrix_or_role_approvers(
        company=company,
        document_lane="AP Vendor Invoice",
        level_number=4,
        fallback_roles=["Accounts L1 Auditor", "Accounts User"],
        stage_keyword="Accounts L1"
    )
    subject = f"[Director Cleared] [Invoice #{claim_name}] {company} - {vendor} (₹ {fmt_money(amount)}) Ready for Accounts L1"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #bfdbfe; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #2563eb; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #1d4ed8; font-weight: 700;">Director Sanction Complete • Accounts L1</span>
            <h2 style="margin: 4px 0 0 0; color: #1e3a8a; font-size: 20px;">Executive Director Approved Vendor Claim</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Business Head / Executive Director <b>{doc.director_approver or 'Director'}</b> has authorized this invoice for <b>{vendor}</b>. Please complete L1 audit and record Tally voucher #.
        </p>
        <div style="background: #eff6ff; border: 1px solid #dbeafe; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #1e40af; margin-bottom: 4px;">Vendor: <b style="color: #0f172a;">{vendor}</b></div>
            <div style="font-size: 18px; font-weight: 800; color: #2563eb;">Net Disbursal: ₹ {fmt_money(amount)}</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #2563eb; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Post Tally Voucher Reference &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=recipients,
        subject=subject,
        message_html=html,
        reference_doctype="Vendor Invoice Claim",
        reference_name=claim_name,
        alert_type="blue",
        cc=[doc.owner, doc.manager_approver, doc.hod_approver, doc.director_approver],
        is_thread_reply=True
    )


def notify_vendor_claim_accounts_l1_verified(claim_name: str) -> None:
    """Triggered after Accounts L1 posts Tally voucher. Alerts Accounts L2 (Level 5 in AP Matrix)."""
    if not frappe.db.exists("Vendor Invoice Claim", claim_name):
        return
    doc = frappe.get_doc("Vendor Invoice Claim", claim_name)
    company = getattr(doc, "company", "Company")
    vendor = getattr(doc, "vendor_name", None) or getattr(doc, "vendor", "Vendor")
    amount = float(getattr(doc, "net_payable_amount", 0.0) or 0.0)
    tally_ref = getattr(doc, "tally_reference", "POSTED")
    doc_url = _get_form_url("Vendor Invoice Claim", claim_name)

    recipients = _get_matrix_or_role_approvers(
        company=company,
        document_lane="AP Vendor Invoice",
        level_number=5,
        fallback_roles=["Accounts Manager", "Accounts Director"],
        stage_keyword="Accounts L2"
    )
    subject = f"[Tally #{tally_ref}] [Invoice #{claim_name}] {company} - {vendor} (₹ {fmt_money(amount)}) Awaiting L2 Clearance"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #bbf7d0; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #16a34a; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #15803d; font-weight: 700;">Final Finance Gate • Stage 7 Accounts L2</span>
            <h2 style="margin: 4px 0 0 0; color: #14532d; font-size: 20px;">Accounts L1 Verified & Tally Logged</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Accounts L1 Auditor (<b>{doc.accounts_l1_verifier or 'Gokulnath'}</b>) has verified 3-Way matching, statutory TDS, and posted Tally Voucher <code>{tally_ref}</code>. Ready for final L2 payment authorization.
        </p>
        <div style="background: #f0fdf4; border: 1px solid #dcfce7; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #166534; margin-bottom: 4px;">Vendor: <b style="color: #0f172a;">{vendor}</b></div>
            <div style="font-size: 13px; color: #166534; margin-bottom: 4px;">Tally Reference: <code style="font-weight: 700;">{tally_ref}</code></div>
            <div style="font-size: 18px; font-weight: 800; color: #16a34a;">Approved Disbursal: ₹ {fmt_money(amount)}</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #16a34a; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Grant Accounts L2 Clearance &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=recipients,
        subject=subject,
        message_html=html,
        reference_doctype="Vendor Invoice Claim",
        reference_name=claim_name,
        alert_type="green",
        cc=[doc.owner, doc.accounts_l1_verifier],
        is_thread_reply=True
    )


def notify_vendor_claim_accounts_l2_approved(claim_name: str) -> None:
    """Triggered after Accounts L2 clearance. Alerts Payment Releaser and Submitter (Approved for Payment)."""
    if not frappe.db.exists("Vendor Invoice Claim", claim_name):
        return
    doc = frappe.get_doc("Vendor Invoice Claim", claim_name)
    company = getattr(doc, "company", "Company")
    vendor = getattr(doc, "vendor_name", None) or getattr(doc, "vendor", "Vendor")
    amount = float(getattr(doc, "net_payable_amount", 0.0) or 0.0)
    doc_url = _get_form_url("Vendor Invoice Claim", claim_name)

    recipients = _get_matrix_or_role_approvers(
        company=company,
        document_lane="AP Vendor Invoice",
        level_number=6,
        fallback_roles=["Payment Releaser"],
        stage_keyword="Payment"
    )
    if doc.owner and doc.owner not in recipients:
        recipients.append(doc.owner)

    subject = f"✅ [Approved for Payment] [Invoice #{claim_name}] {company} - {vendor} (₹ {fmt_money(amount)})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #86efac; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #10b981; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #047857; font-weight: 700;">Final Sanction Complete • Thursday Batch Queue</span>
            <h2 style="margin: 4px 0 0 0; color: #064e3b; font-size: 20px;">Vendor Invoice Approved for Payment</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Accounts L2 (<b>{doc.accounts_l2_approver or 'Accounts Director'}</b>) has granted final clearance. This claim is now marked <b>Approved for Payment</b> and will be included in the Thursday payment batch for IDFC 2FA release.
        </p>
        <div style="background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #047857; margin-bottom: 4px;">Vendor: <b style="color: #0f172a;">{vendor}</b></div>
            <div style="font-size: 20px; font-weight: 800; color: #059669;">Net Disbursement: ₹ {fmt_money(amount)}</div>
        </div>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #059669; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                View Approved Claim in AP Desk &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=recipients,
        subject=subject,
        message_html=html,
        reference_doctype="Vendor Invoice Claim",
        reference_name=claim_name,
        alert_type="green",
        cc=[doc.accounts_l1_verifier, doc.accounts_l2_approver],
        is_thread_reply=True
    )


def notify_vendor_claim_disputed(claim_name: str, reason_code: str, remarks: str) -> None:
    """Triggered on dispute/rejection. Alerts Submitter, Prior Approvers, and Accounts with forensic details."""
    if not frappe.db.exists("Vendor Invoice Claim", claim_name):
        return
    doc = frappe.get_doc("Vendor Invoice Claim", claim_name)
    company = getattr(doc, "company", "Company")
    vendor = getattr(doc, "vendor_name", None) or getattr(doc, "vendor", "Vendor")
    amount = float(getattr(doc, "net_payable_amount", 0.0) or 0.0)
    user = frappe.session.user if getattr(frappe, "session", None) else "Auditor"
    doc_url = _get_form_url("Vendor Invoice Claim", claim_name)

    recipients = []
    if doc.owner:
        recipients.append(doc.owner)
    if getattr(doc, "claimant_email", None):
        recipients.append(doc.claimant_email)
    if doc.manager_approver:
        recipients.append(doc.manager_approver)
    if doc.accounts_l1_verifier:
        recipients.append(doc.accounts_l1_verifier)
    if not any(_resolve_email(r) for r in recipients):
        matrix_mgrs = _get_matrix_or_role_approvers(
            company=company,
            document_lane="AP Vendor Invoice",
            level_number=1,
            fallback_roles=["Admin L1 Approver"],
            stage_keyword="Manager"
        )
        recipients.extend(matrix_mgrs)

    subject = f"🚫 [DISPUTED / REJECTED] [Invoice #{claim_name}] {company} - {vendor} ({reason_code})"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid #fca5a5; border-radius: 10px; padding: 24px; background: #ffffff;">
        <div style="border-bottom: 2px solid #dc2626; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: #991b1b; font-weight: 700;">Audit Discrepancy Flagged • Action Required</span>
            <h2 style="margin: 4px 0 0 0; color: #7f1d1d; font-size: 20px;">Vendor Claim Flagged as Disputed / Rejected</h2>
        </div>
        <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            Auditor <b>{user}</b> has placed Vendor Claim <b>#{claim_name}</b> for <b>{vendor}</b> into <b>Disputed</b> status.
        </p>
        <div style="background: #fef2f2; border: 1px solid #fee2e2; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <div style="font-size: 13px; color: #991b1b; margin-bottom: 4px;">Reason Code: <b style="color: #7f1d1d;">{reason_code}</b></div>
            <div style="font-size: 13px; color: #991b1b; margin-bottom: 6px;">Auditor Remarks: <span style="color: #0f172a;">{remarks}</span></div>
            <div style="font-size: 16px; font-weight: 700; color: #dc2626;">Claim Amount on Hold: ₹ {fmt_money(amount)}</div>
        </div>
        <p style="color: #64748b; font-size: 13px;">
            Payment processing is strictly halted until the PO discrepancy, tax variance, or proof issue is rectified.
        </p>
        <div style="text-align: center; margin-top: 24px;">
            <a href="{doc_url}" style="background: #dc2626; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                Open Claim & Resolve Discrepancy &rarr;
            </a>
        </div>
    </div>
    """
    _send_email_and_desk_alert(
        recipients=recipients,
        subject=subject,
        message_html=html,
        reference_doctype="Vendor Invoice Claim",
        reference_name=claim_name,
        alert_type="red",
        cc=[],
        is_thread_reply=True
    )
