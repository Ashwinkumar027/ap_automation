# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Enterprise Employee Business Expense & Reimbursement Dedicated Notification Service
Enforces:
1. Dedicated standalone notification module for Employee Reimbursement & Pre-Travel workflows.
2. 100% Simple, crystal-clear English phrasing with prominent metrics and action buttons.
3. Single Email Conversation Threading (RFC 5322 In-Reply-To and References headers).
4. Prominent high-visibility Rejection Boxes displaying exact reasons and fast-track guidance.
5. Smart Fast-Track Resubmission Alerts to approvers when claims bypass earlier stages.
6. Asynchronous non-blocking queue execution (frappe.enqueue).
7. Zero Data Privacy Leaks (Dynamic System Manager fallbacks, no hardcoded emails).
8. Safe numeric formatting (_safe_fmt_money) resilient against None values.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import re
import hashlib
import frappe
from frappe.utils import get_url_to_form, fmt_money, cstr, flt


def _safe_fmt_money(amount: Any) -> str:
    """Safely formats monetary amounts avoiding NoneType errors."""
    return f"{fmt_money(flt(amount or 0.0))}"


def _get_form_url(doctype: str, docname: str) -> str:
    """
    Dynamically generates the proper desk URL across Local, UAT, and Production.
    """
    if getattr(frappe.local, "request", None) and hasattr(frappe.local.request, "host_url"):
        base_host = frappe.local.request.host_url.rstrip("/")
        doctype_slug = doctype.lower().replace(" ", "-")
        return f"{base_host}/desk/{doctype_slug}/{docname}"

    url = get_url_to_form(doctype, docname)
    if "127.0.0.1:8000" in url and getattr(frappe.local, "site", "") == "hrms1.local":
        url = url.replace("127.0.0.1:8000", "hrms1.local:8000")
    return url


# ==============================================================================
# CORE EMAIL DISPATCHER & THREADING ENGINE
# ==============================================================================

def _resolve_email_address(user_or_emp_or_email: Optional[str]) -> Optional[str]:
    """
    O(1) cached resolver that maps any User ID, Employee ID, or raw email to a valid sendable address.
    """
    if not user_or_emp_or_email:
        return None
    val = str(user_or_emp_or_email).strip()
    if not val:
        return None

    # Filter dummy accounts
    if val in ("Administrator", "admin@example.com"):
        admin_email = frappe.db.get_value("User", "Administrator", "email")
        if admin_email and "@" in admin_email and "example.com" not in admin_email:
            return admin_email
        return None

    # Already valid email
    if "@" in val and "." in val:
        return val

    # Lookup User Master
    if frappe.db.exists("User", val):
        email = frappe.db.get_value("User", val, "email")
        if email and "@" in email:
            return email

    # Lookup Employee Master
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


def _get_system_manager_emails() -> List[str]:
    """Fetches active System Managers as fallback recipients."""
    managers = frappe.get_all("Has Role", filters={"role": "System Manager", "parenttype": "User"}, pluck="parent")
    emails = []
    for u in managers:
        if u != "Administrator":
            resolved = _resolve_email_address(u)
            if resolved:
                emails.append(resolved)
    return list(dict.fromkeys(emails))


def _get_role_recipients(role_names: List[str]) -> List[str]:
    """Fetches all active users holding specified roles with fallback to System Managers."""
    if not role_names:
        return []
    users = frappe.get_all(
        "Has Role",
        filters={"role": ["in", role_names], "parenttype": "User"},
        pluck="parent"
    )
    emails = []
    for u in users:
        resolved = _resolve_email_address(u)
        if resolved:
            emails.append(resolved)
    clean_list = list(dict.fromkeys(emails))
    if not clean_list:
        clean_list = _get_system_manager_emails()
    return clean_list


def _get_matrix_or_role_recipients(company: str, level_number: int, fallback_roles: List[str]) -> List[str]:
    """
    Fetches designated approver from AP Approval Matrix for company & level_number.
    Falls back to active users with fallback_roles, and finally System Managers.
    """
    recipients = []
    if frappe.db.exists("DocType", "AP Approval Matrix"):
        matrix_name = frappe.db.get_value(
            "AP Approval Matrix",
            {"company": company, "document_lane": "Employee Reimbursement Claim", "is_active": 1},
            "name"
        ) or frappe.db.get_value(
            "AP Approval Matrix",
            {"document_lane": "Employee Reimbursement Claim", "is_active": 1},
            "name"
        )
        if matrix_name:
            matrix = frappe.get_doc("AP Approval Matrix", matrix_name)
            for lvl in matrix.approval_levels:
                if lvl.level_number == level_number and lvl.designated_approver:
                    resolved = _resolve_email_address(lvl.designated_approver)
                    if resolved:
                        recipients.append(resolved)

    if not recipients and fallback_roles:
        recipients = _get_role_recipients(fallback_roles)

    if not recipients:
        recipients = _get_system_manager_emails()

    return list(dict.fromkeys(recipients))


def _dispatch_reimbursement_email(
    recipients: List[str],
    subject: str,
    html_body: str,
    reference_doctype: str,
    reference_name: str,
    cc: Optional[List[str]] = None,
    alert_color: str = "blue",
    is_thread_reply: bool = True
) -> None:
    """
    Dispatches asynchronous email with RFC 5322 continuous single-threading and real-time Desk popups.
    """
    clean_recipients = list(dict.fromkeys([_resolve_email_address(r) for r in recipients if _resolve_email_address(r)]))
    if not clean_recipients:
        return

    clean_cc = list(dict.fromkeys([_resolve_email_address(c) for c in (cc or []) if _resolve_email_address(c) and c not in clean_recipients]))

    # Deterministic Thread Message-ID Root for continuous Gmail/Outlook conversation grouping
    clean_dt = re.sub(r'[^a-zA-Z0-9]', '', reference_doctype)
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', reference_name)
    thread_msg_id = f"<{clean_dt}-{clean_name}-thread@quanticus.com>"

    # 1. Email Dispatch
    try:
        email_kwargs = {
            "recipients": clean_recipients,
            "cc": clean_cc,
            "subject": subject,
            "message": html_body,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "header": ["AP Automation", alert_color],
            "now": True
        }
        if is_thread_reply:
            email_kwargs["in_reply_to"] = thread_msg_id
            email_kwargs["email_headers"] = {"References": thread_msg_id}
        else:
            email_kwargs["message_id"] = thread_msg_id

        frappe.sendmail(**email_kwargs)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to dispatch reimbursement email for {reference_name}: {str(e)}", "AP Email Error")

    # 2. Desk Real-time Notification
    for user_email in clean_recipients:
        try:
            frappe.publish_realtime(
                event="msgprint",
                message={
                    "message": f"<b>{subject}</b><br><a href='/desk/{reference_doctype.lower().replace(' ', '-')}/{reference_name}'>Open #{reference_name}</a>",
                    "indicator": alert_color,
                    "title": "Expense Alert"
                },
                user=user_email
            )
        except Exception:
            pass


def _build_html_template(
    title: str,
    subtitle: str,
    greeting_name: str,
    main_message: str,
    metric_label_1: str,
    metric_val_1: str,
    metric_label_2: Optional[str],
    metric_val_2: Optional[str],
    doc_url: str,
    button_text: str,
    rejection_reason: Optional[str] = None,
    fast_track_tip: Optional[str] = None,
    badge_color: str = "#2563eb",
    theme_color: str = "#1e293b"
) -> str:
    """
    Renders clean, bank-grade, responsive HTML email in Simple English.
    """
    rejection_block = ""
    if rejection_reason:
        rejection_block = f"""
        <div style="background: #fef2f2; border: 1px solid #fecaca; border-left: 4px solid #ef4444; border-radius: 6px; padding: 14px; margin: 18px 0;">
            <strong style="color: #991b1b; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">🔴 Reason for Rejection / Return:</strong>
            <div style="color: #b91c1c; font-size: 14px; margin-top: 6px; font-weight: 500; line-height: 1.5;">"{rejection_reason}"</div>
        </div>
        """

    fast_track_block = ""
    if fast_track_tip:
        fast_track_block = f"""
        <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-left: 4px solid #22c55e; border-radius: 6px; padding: 14px; margin: 18px 0;">
            <strong style="color: #166534; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">⚡ Fast-Track Resubmission Guide:</strong>
            <div style="color: #15803d; font-size: 13px; margin-top: 4px; line-height: 1.5;">{fast_track_tip}</div>
        </div>
        """

    metric_2_html = ""
    if metric_label_2 and metric_val_2:
        metric_2_html = f"""
        <div style="margin-top: 8px; font-size: 13px; color: #475569;">
            {metric_label_2}: <strong style="color: #0f172a;">{metric_val_2}</strong>
        </div>
        """

    return f"""
    <div style="font-family: Arial, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; background: #ffffff;">
        <!-- Header -->
        <div style="background: {theme_color}; padding: 20px 24px; color: #ffffff;">
            <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; font-weight: 700;">{subtitle}</span>
            <h2 style="margin: 6px 0 0 0; font-size: 20px; font-weight: 700; color: #ffffff;">{title}</h2>
        </div>

        <!-- Body -->
        <div style="padding: 24px; background: #ffffff;">
            <p style="color: #334155; font-size: 15px; margin-top: 0;">Hello <b>{greeting_name}</b>,</p>
            <p style="color: #334155; font-size: 14px; line-height: 1.6;">{main_message}</p>

            <!-- Metrics Card -->
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 18px 0;">
                <div style="font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px;">{metric_label_1}</div>
                <div style="font-size: 20px; font-weight: 800; color: #0f172a; margin-top: 4px;">{metric_val_1}</div>
                {metric_2_html}
            </div>

            {rejection_block}
            {fast_track_block}

            <!-- CTA Button -->
            <div style="text-align: center; margin-top: 26px; margin-bottom: 10px;">
                <a href="{doc_url}" style="background: {badge_color}; color: #ffffff; padding: 12px 26px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; display: inline-block;">
                    {button_text} &rarr;
                </a>
            </div>
        </div>

        <!-- Footer -->
        <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 14px 24px; text-align: center; font-size: 12px; color: #94a3b8;">
            This is an automated notification from AP Automation System &bull; Quanti Systems
        </div>
    </div>
    """


# ==============================================================================
# STAGE A: PRE-TRAVEL APPROVAL NOTIFICATIONS (CLIENT VISIT ONLY)
# ==============================================================================

def notify_manager_on_pre_travel_submitted(docname: str) -> None:
    """1. Triggered when Employee submits Pre-Travel Request to Reporting Manager."""
    doc = frappe.get_doc("Pre Travel Request", docname)
    mgr_email = _resolve_email_address((doc.get("manager_user_id") or getattr(doc, "manager_user_id", None)) or doc.reporting_manager)
    if not mgr_email:
        return

    client = doc.get("client_name") or "Corporate Client"
    est_budget = doc.get("estimated_cost") or doc.get("estimated_budget") or 0.0
    from_d = doc.get("from_date") or doc.get("departure_date") or "N/A"
    to_d = doc.get("to_date") or doc.get("return_date") or "N/A"

    doc_url = _get_form_url("Pre Travel Request", docname)
    subject = f"✈️ [Action Required] Pre-Travel Request: {doc.employee_name} visiting {client}"
    body = _build_html_template(
        title="Pre-Travel Approval Required",
        subtitle="Stage A &bull; Client Visit Pre-Approval",
        greeting_name=doc.reporting_manager or "Manager",
        main_message=(
            f"Employee <b>{doc.employee_name}</b> ({doc.get('department') or 'Company'}) has requested Pre-Travel Approval for an upcoming client visit. "
            f"Please review the agenda and estimated budget to approve or reject."
        ),
        metric_label_1="Estimated Travel Budget",
        metric_val_1=f"₹ {_safe_fmt_money(est_budget)}",
        metric_label_2="Client & Travel Dates",
        metric_val_2=f"{client} ({from_d} to {to_d})",
        doc_url=doc_url,
        button_text="Review & Approve Pre-Travel",
        badge_color="#2563eb"
    )
    _dispatch_reimbursement_email([mgr_email], subject, body, "Pre Travel Request", docname)


def notify_employee_on_pre_travel_approved(docname: str) -> None:
    """2. Triggered when Reporting Manager approves Pre-Travel Request."""
    doc = frappe.get_doc("Pre Travel Request", docname)
    emp_email = _resolve_email_address(doc.employee)
    if not emp_email:
        return

    client = doc.get("client_name") or "Corporate Client"
    est_budget = doc.get("estimated_cost") or doc.get("estimated_budget") or 0.0
    doc_url = _get_form_url("Pre Travel Request", docname)

    subject = f"✅ Pre-Travel Approved: #{doc.name} ({client})"
    body = _build_html_template(
        title="Pre-Travel Request Approved!",
        subtitle="Stage A &bull; Pre-Approval Granted",
        greeting_name=doc.employee_name,
        main_message=(
            f"Great news! Your Reporting Manager has <b>Approved</b> your Pre-Travel Request for visiting <b>{client}</b>.<br><br>"
            f"After completing your visit, please submit your Expense Claim and link your approved reference <b>#{doc.name}</b>."
        ),
        metric_label_1="Approved Pre-Travel Reference",
        metric_val_1=doc.name,
        metric_label_2="Approved Budget",
        metric_val_2=f"₹ {_safe_fmt_money(est_budget)}",
        doc_url=doc_url,
        button_text="View Pre-Travel Reference",
        badge_color="#16a34a"
    )
    _dispatch_reimbursement_email([emp_email], subject, body, "Pre Travel Request", docname)


def notify_employee_on_pre_travel_rejected(docname: str, reason: str) -> None:
    """3. Triggered when Reporting Manager rejects Pre-Travel Request."""
    doc = frappe.get_doc("Pre Travel Request", docname)
    emp_email = _resolve_email_address(doc.employee)
    if not emp_email:
        return

    client = doc.get("client_name") or "Corporate Client"
    doc_url = _get_form_url("Pre Travel Request", docname)
    subject = f"❌ Pre-Travel Request Rejected: #{doc.name} ({client})"
    body = _build_html_template(
        title="Pre-Travel Request Rejected",
        subtitle="Stage A &bull; Request Declined",
        greeting_name=doc.employee_name,
        main_message=(
            f"Your Pre-Travel Request to visit <b>{client}</b> has been <b>Rejected</b> by your Reporting Manager."
        ),
        metric_label_1="Request Reference",
        metric_val_1=doc.name,
        metric_label_2="Client Name",
        metric_val_2=client,
        rejection_reason=reason,
        doc_url=doc_url,
        button_text="View Request Details",
        badge_color="#dc2626",
        theme_color="#7f1d1d"
    )
    _dispatch_reimbursement_email([emp_email], subject, body, "Pre Travel Request", docname, alert_color="red")


# ==============================================================================
# STAGE B: FORWARD EXPENSE CLAIM PIPELINE (STEPS 1 TO 7)
# ==============================================================================

def notify_manager_on_claim_submitted(docname: str) -> None:
    """4. Step 1: Employee submits Expense Claim to Reporting Manager."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    mgr_email = _resolve_email_address((doc.get("manager_user_id") or getattr(doc, "manager_user_id", None)) or doc.reporting_manager)
    if not mgr_email:
        return

    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    cat = doc.claim_category or doc.expense_type or "General Expense"
    amount = flt(doc.total_claim_amount)
    subject = f"[Claim #{doc.name}] {doc.employee_name} - {cat} (₹ {_safe_fmt_money(amount)}) - Submitted for Review"
    body = _build_html_template(
        title="New Expense Claim Submitted",
        subtitle=f"Stage 1 &bull; {cat}",
        greeting_name=doc.reporting_manager or "Reporting Manager",
        main_message=(
            f"Employee <b>{doc.employee_name}</b> has submitted an Expense Claim for <b>{cat}</b>. "
            f"Please review the business justification, line items, and receipts to approve."
        ),
        metric_label_1="Total Claim Amount",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Line Items & Employee",
        metric_val_2=f"{len(doc.expense_lines or [])} expense lines &bull; {doc.employee_name}",
        doc_url=doc_url,
        button_text="Review & Approve Claim",
        badge_color="#2563eb"
    )
    _dispatch_reimbursement_email([mgr_email], subject, body, "Employee Reimbursement Claim", docname, is_thread_reply=False)


def notify_receptionist_on_manager_approved(docname: str) -> None:
    """5. Step 2: Reporting Manager approves -> Notifies Receptionist (Petty Cash Flow)."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    rec_users = _get_matrix_or_role_recipients(doc.company, 1, ["Receptionist"])

    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    amount = flt(doc.total_claim_amount)
    subject = f"Re: [Claim #{doc.name}] {doc.employee_name} - {doc.claim_category or 'Expense'} (₹ {_safe_fmt_money(amount)}) - Manager Approved"
    body = _build_html_template(
        title="Receipt Verification Required",
        subtitle="Stage 2 &bull; Receptionist / Petty Cash Flow",
        greeting_name="Front Desk / Reception Team",
        main_message=(
            f"Reporting Manager approved Claim <b>#{doc.name}</b> for <b>{doc.employee_name}</b>. "
            f"Please verify the physical/digital bills and register the voucher."
        ),
        metric_label_1="Claim Amount",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Claimant & Category",
        metric_val_2=f"{doc.employee_name} &bull; {doc.claim_category or 'General'}",
        doc_url=doc_url,
        button_text="Verify Receipts & Tag",
        badge_color="#0891b2"
    )
    _dispatch_reimbursement_email(rec_users, subject, body, "Employee Reimbursement Claim", docname)


def notify_admin_l1_on_reception_verified(docname: str) -> None:
    """6. Step 3: Receptionist verified -> Notifies Admin L1 Approver."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    l1_users = _get_matrix_or_role_recipients(doc.company, 2, ["Admin L1 Approver"])

    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    amount = flt(doc.total_claim_amount)
    subject = f"Re: [Claim #{doc.name}] {doc.employee_name} - {doc.claim_category or 'Expense'} (₹ {_safe_fmt_money(amount)}) - Reception Verified"
    body = _build_html_template(
        title="Admin L1 Operational Review",
        subtitle="Stage 3 &bull; Admin L1 Approval",
        greeting_name="Admin L1 Approver",
        main_message=(
            f"Receipts for Claim <b>#{doc.name}</b> ({doc.employee_name}) have been verified by Reception. "
            f"Please review for operational policy compliance."
        ),
        metric_label_1="Claim Value",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Department & Company",
        metric_val_2=f"{doc.department} &bull; {doc.company}",
        doc_url=doc_url,
        button_text="Review & Pass to Admin L2",
        badge_color="#2563eb"
    )
    _dispatch_reimbursement_email(l1_users, subject, body, "Employee Reimbursement Claim", docname)


def notify_admin_l2_on_admin_l1_approved(docname: str) -> None:
    """7. Step 4: Admin L1 approves -> Notifies Admin L2 Department Head."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    l2_users = _get_matrix_or_role_recipients(doc.company, 3, ["Admin L2 Approver"])

    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    amount = flt(doc.total_claim_amount)
    subject = f"Re: [Claim #{doc.name}] {doc.employee_name} - {doc.claim_category or 'Expense'} (₹ {_safe_fmt_money(amount)}) - Admin L1 Approved"
    body = _build_html_template(
        title="Admin L2 Department Sign-Off",
        subtitle="Stage 4 &bull; Admin L2 Head Clearance",
        greeting_name="Admin Department Head",
        main_message=(
            f"Admin L1 has cleared Claim <b>#{doc.name}</b> for <b>{doc.employee_name}</b>. "
            f"Your department head sign-off is required before forwarding to Accounts."
        ),
        metric_label_1="Total Claim Amount",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Claimant",
        metric_val_2=doc.employee_name,
        doc_url=doc_url,
        button_text="Sign-Off & Pass to Accounts",
        badge_color="#4f46e5"
    )
    _dispatch_reimbursement_email(l2_users, subject, body, "Employee Reimbursement Claim", docname)


def notify_accounts_l1_on_admin_l2_approved(docname: str) -> None:
    """8. Step 5: Admin L2 signs off -> Notifies Accounts L1 Tax Auditor."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    acc_users = _get_matrix_or_role_recipients(doc.company, 4, ["Accounts L1 Auditor"])

    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    amount = flt(doc.total_claim_amount)
    subject = f"Re: [Claim #{doc.name}] {doc.employee_name} - {doc.claim_category or 'Expense'} (₹ {_safe_fmt_money(amount)}) - Admin L2 Cleared"
    body = _build_html_template(
        title="Accounts L1 Line-Item & Tax Audit",
        subtitle="Stage 5 &bull; Accounts Audit Tier",
        greeting_name="Accounts Auditor",
        main_message=(
            f"Claim <b>#{doc.name}</b> has completed administrative clearance. "
            f"Please perform tax invoice audit, check GSTIN compliance, and set sanctioned amounts."
        ),
        metric_label_1="Claim Amount",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Bank Details Configured",
        metric_val_2=f"{doc.bank_name or 'Salary Bank'} (A/C: ****{cstr(doc.bank_account_number)[-4:]})",
        doc_url=doc_url,
        button_text="Audit Tax Receipts & Sanction",
        badge_color="#d97706"
    )
    _dispatch_reimbursement_email(acc_users, subject, body, "Employee Reimbursement Claim", docname)


def notify_accounts_l2_on_accounts_l1_audited(docname: str) -> None:
    """9. Step 6: Accounts L1 audits -> Notifies Accounts L2 Finance Controller."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    l2_acc = _get_matrix_or_role_recipients(doc.company, 5, ["Accounts Director"])

    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    sanctioned = flt(doc.sanctioned_amount or doc.total_claim_amount)
    subject = f"Re: [Claim #{doc.name}] {doc.employee_name} - {doc.claim_category or 'Expense'} (₹ {_safe_fmt_money(sanctioned)}) - Accounts L1 Audited"
    body = _build_html_template(
        title="Final Financial Sanction Required",
        subtitle="Stage 6 &bull; Accounts L2 Sanction",
        greeting_name="Finance Controller / Director",
        main_message=(
            f"Accounts L1 has audited Claim <b>#{doc.name}</b> for <b>{doc.employee_name}</b>. "
            f"Please authorize final financial sanction for payment disbursal."
        ),
        metric_label_1="Sanctioned Net Payable",
        metric_val_1=f"₹ {_safe_fmt_money(sanctioned)}",
        metric_label_2="Claimed vs Sanctioned",
        metric_val_2=f"Claimed: ₹ {_safe_fmt_money(doc.total_claim_amount)} &bull; Sanctioned: ₹ {_safe_fmt_money(sanctioned)}",
        doc_url=doc_url,
        button_text="Authorize Final Sanction",
        badge_color="#16a34a"
    )
    _dispatch_reimbursement_email(l2_acc, subject, body, "Employee Reimbursement Claim", docname)


def notify_releaser_on_accounts_l2_sanctioned(docname: str) -> None:
    """10. Step 7: Accounts L2 authorizes -> Notifies Payment Releaser / Cashier."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    releasers = _get_matrix_or_role_recipients(doc.company, 6, ["Payment Releaser"])

    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    sanctioned = flt(doc.sanctioned_amount or doc.total_claim_amount)
    subject = f"Re: [Claim #{doc.name}] {doc.employee_name} - {doc.claim_category or 'Expense'} (₹ {_safe_fmt_money(sanctioned)}) - Ready for Payment"
    body = _build_html_template(
        title="Payment Release Ready",
        subtitle="Stage 7 &bull; Treasury & Disbursal",
        greeting_name="Payment Releaser / Cashier",
        main_message=(
            f"Claim <b>#{doc.name}</b> for <b>{doc.employee_name}</b> is fully sanctioned. "
            f"Please disburse payment to beneficiary account."
        ),
        metric_label_1="Disbursal Amount",
        metric_val_1=f"₹ {_safe_fmt_money(sanctioned)}",
        metric_label_2="Beneficiary Account",
        metric_val_2=f"{doc.employee_name} &bull; {doc.bank_name} ({doc.bank_account_number})",
        doc_url=doc_url,
        button_text="Disburse & Mark Paid",
        badge_color="#16a34a"
    )
    _dispatch_reimbursement_email(releasers, subject, body, "Employee Reimbursement Claim", docname)


def notify_employee_on_payment_released(docname: str, payment_reference: str) -> None:
    """11. Step 8: Payment released -> Notifies Employee with bank details and UTR."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    emp_email = _resolve_email_address(doc.employee)
    if not emp_email:
        return

    mgr_email = _resolve_email_address((doc.get("manager_user_id") or getattr(doc, "manager_user_id", None)) or doc.reporting_manager)
    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    amount = flt(doc.sanctioned_amount or doc.total_claim_amount)

    subject = f"Re: [Claim #{doc.name}] {doc.employee_name} - {doc.claim_category or 'Expense'} (₹ {_safe_fmt_money(amount)}) - 🎉 Payment Disbursed"
    body = _build_html_template(
        title="Payment Successfully Released!",
        subtitle="Disbursal Completed &bull; Reimbursement Settled",
        greeting_name=doc.employee_name,
        main_message=(
            f"Payment of <b>₹ {_safe_fmt_money(amount)}</b> for your Expense Claim <b>#{doc.name}</b> has been released "
            f"and credited to your registered salary bank account."
        ),
        metric_label_1="Amount Disbursed",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Bank Reference / UTR",
        metric_val_2=f"{payment_reference or 'SETTLED'} &bull; {doc.bank_name} (****{cstr(doc.bank_account_number)[-4:]})",
        doc_url=doc_url,
        button_text="View Voucher Details",
        badge_color="#16a34a"
    )
    _dispatch_reimbursement_email([emp_email], subject, body, "Employee Reimbursement Claim", docname, cc=[mgr_email] if mgr_email else None)


# ==============================================================================
# STAGE C: REJECTION, RETURN & SMART FAST-TRACK NOTIFICATIONS
# ==============================================================================

def notify_employee_on_claim_returned(docname: str, approver_role: str, reason: str) -> None:
    """12. Triggered when any approver returns claim to Employee."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    emp_email = _resolve_email_address(doc.employee)
    if not emp_email:
        return

    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    amount = flt(doc.total_claim_amount)
    subject = f"Re: [Claim #{doc.name}] {doc.employee_name} - {doc.claim_category or 'Expense'} (₹ {_safe_fmt_money(amount)}) - ⚠️ Returned by {approver_role}"
    body = _build_html_template(
        title="Claim Returned for Correction",
        subtitle=f"Action Required &bull; Returned by {approver_role}",
        greeting_name=doc.employee_name,
        main_message=(
            f"Your Expense Claim <b>#{doc.name}</b> has been reviewed by <b>{approver_role}</b> and returned for corrections."
        ),
        metric_label_1="Claim Amount",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Voucher Category",
        metric_val_2=doc.claim_category or "General Expense",
        rejection_reason=reason,
        fast_track_tip=(
            f"If you replace or update your bill attachments <b>without increasing the total claim amount</b>, "
            f"your resubmission will <b>automatically bypass intermediate stages</b> and go straight back to <b>{approver_role}</b>!"
        ),
        doc_url=doc_url,
        button_text="Correct & Resubmit Claim",
        badge_color="#dc2626",
        theme_color="#7f1d1d"
    )
    _dispatch_reimbursement_email([emp_email], subject, body, "Employee Reimbursement Claim", docname, alert_color="red")


def notify_internal_stage_on_claim_returned(docname: str, target_stage: str, approver_role: str, reason: str) -> None:
    """13. Triggered when claim is returned to Receptionist, Manager, or Admin L1."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    amount = flt(doc.total_claim_amount)

    recipients = []
    if target_stage in ("Reporting Manager", "Manager"):
        recipients = [_resolve_email_address((doc.get("manager_user_id") or getattr(doc, "manager_user_id", None)) or doc.reporting_manager)]
    elif target_stage == "Receptionist":
        recipients = _get_role_recipients(["Receptionist"])
    elif target_stage == "Admin L1":
        recipients = _get_role_recipients(["Admin L1 Approver"])

    if not recipients:
        recipients = _get_system_manager_emails()

    subject = f"⚠️ [Action Required] Claim #{doc.name} Returned to {target_stage} by {approver_role}"
    body = _build_html_template(
        title=f"Claim Returned to {target_stage}",
        subtitle=f"Re-Review Required &bull; Returned by {approver_role}",
        greeting_name=f"{target_stage} Team",
        main_message=(
            f"Claim <b>#{doc.name}</b> for <b>{doc.employee_name}</b> (₹ {_safe_fmt_money(amount)}) "
            f"has been returned by <b>{approver_role}</b> for re-verification."
        ),
        metric_label_1="Claim Amount",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Claimant",
        metric_val_2=doc.employee_name,
        rejection_reason=reason,
        doc_url=doc_url,
        button_text="Review & Update Voucher",
        badge_color="#d97706",
        theme_color="#78350f"
    )
    _dispatch_reimbursement_email(recipients, subject, body, "Employee Reimbursement Claim", docname, alert_color="orange")


def notify_approver_on_fast_track_resubmitted(docname: str, rejecting_user: str, prior_stage: str) -> None:
    """14. Triggered when claim FAST-TRACKS directly back to the rejecting approver's queue."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    approver_email = _resolve_email_address(rejecting_user)
    if not approver_email:
        return

    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    amount = flt(doc.total_claim_amount)
    subject = f"⚡ Fast-Track Update: Claim #{doc.name} Returned Directly to Your Queue ({prior_stage})"
    body = _build_html_template(
        title="⚡ Fast-Track Resubmission Received",
        subtitle=f"Direct Bypass Active &bull; {prior_stage}",
        greeting_name="Approver",
        main_message=(
            f"Employee <b>{doc.employee_name}</b> has updated the requested details on Claim <b>#{doc.name}</b> "
            f"without increasing the total cost.<br><br>"
            f"🚀 <b>Fast-Track Activated:</b> This claim has bypassed earlier approval stages and returned directly "
            f"to your queue for immediate sign-off."
        ),
        metric_label_1="Claim Amount (Unchanged)",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Claimant & Stage",
        metric_val_2=f"{doc.employee_name} &bull; {prior_stage}",
        doc_url=doc_url,
        button_text="Approve Fast-Tracked Claim",
        badge_color="#16a34a",
        theme_color="#064e3b"
    )
    _dispatch_reimbursement_email([approver_email], subject, body, "Employee Reimbursement Claim", docname, alert_color="green")


def notify_manager_on_cost_increased_resubmitted(docname: str, old_amount: float, new_amount: float) -> None:
    """15. Triggered when employee resubmits with an increased amount, resetting to Stage 1."""
    doc = frappe.get_doc("Employee Reimbursement Claim", docname)
    mgr_email = _resolve_email_address((doc.get("manager_user_id") or getattr(doc, "manager_user_id", None)) or doc.reporting_manager)
    if not mgr_email:
        return

    doc_url = _get_form_url("Employee Reimbursement Claim", docname)
    subject = f"📋 [Action Required] Resubmitted Claim #{doc.name} with Updated Amount (₹ {_safe_fmt_money(new_amount)})"
    body = _build_html_template(
        title="Resubmitted Claim (Amount Increased)",
        subtitle="Stage 1 &bull; Financial Re-Approval Required",
        greeting_name=doc.reporting_manager or "Reporting Manager",
        main_message=(
            f"Employee <b>{doc.employee_name}</b> has resubmitted Claim <b>#{doc.name}</b> with an increased claim amount. "
            f"Because the amount was raised from ₹ {_safe_fmt_money(old_amount)} to ₹ {_safe_fmt_money(new_amount)}, "
            f"full financial re-approval starting from Reporting Manager has been initiated."
        ),
        metric_label_1="New Total Claim Amount",
        metric_val_1=f"₹ {_safe_fmt_money(new_amount)}",
        metric_label_2="Previous Baseline Amount",
        metric_val_2=f"₹ {_safe_fmt_money(old_amount)} (Increased by ₹ {_safe_fmt_money(new_amount - old_amount)})",
        doc_url=doc_url,
        button_text="Review & Approve Updated Claim",
        badge_color="#2563eb"
    )
    _dispatch_reimbursement_email([mgr_email], subject, body, "Employee Reimbursement Claim", docname, is_thread_reply=False)


# ==============================================================================
# STAGE D: WEEKLY CONSOLIDATED ACCOUNTS AUDIT BATCH NOTIFICATIONS (FRIDAY)
# ==============================================================================

def notify_accounts_l1_on_weekly_batch_ready(batch_name: str) -> None:
    """16. Triggered every Friday @ 12:00 PM when Weekly Accounts Batch is generated."""
    batch = frappe.get_doc("Weekly Accounts Audit Batch", batch_name)
    acc_users = _get_matrix_or_role_recipients(batch.company, 4, ["Accounts L1 Auditor", "Accounts Manager"])

    doc_url = _get_form_url("Weekly Accounts Audit Batch", batch_name)
    amount = flt(batch.total_claimed_amount)
    claims_count = batch.total_claims_count or len(batch.items or [])
    emp_count = batch.total_employees_count or len(set(i.employee_id for i in (batch.items or [])))

    subject = f"📅 [Weekly Friday Audit] Reimbursement Batch #{batch.name}: {claims_count} Claims across {emp_count} Employees (₹ {_safe_fmt_money(amount)})"
    body = _build_html_template(
        title="Weekly Friday Accounts Audit Workstation",
        subtitle=f"Batch {batch.week_number} &bull; Consolidated Reimbursements",
        greeting_name="Accounts Audit Team",
        main_message=(
            f"The Weekly Friday Consolidated Reimbursement Batch <b>#{batch.name}</b> has been compiled. "
            f"All claims approved by Admin L2 this week have been consolidated into your workstation.<br><br>"
            f"Please review employee-wise line items, verify GST tax invoices, and sanction or dispute items as needed."
        ),
        metric_label_1="Total Batch Amount",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Claims & Employees",
        metric_val_2=f"{claims_count} claims &bull; {emp_count} employees ({batch.company})",
        doc_url=doc_url,
        button_text="Open Weekly Audit Workstation",
        badge_color="#d97706"
    )
    _dispatch_reimbursement_email(acc_users, subject, body, "Weekly Accounts Audit Batch", batch_name, alert_color="orange")


def notify_accounts_director_on_weekly_batch_audited(batch_name: str) -> None:
    """17. Triggered when Accounts L1 audits and sanctions the weekly batch -> Director Sign-Off."""
    batch = frappe.get_doc("Weekly Accounts Audit Batch", batch_name)
    director_users = _get_matrix_or_role_recipients(batch.company, 5, ["Accounts Director"])

    doc_url = _get_form_url("Weekly Accounts Audit Batch", batch_name)
    amount = flt(batch.total_sanctioned_amount)
    claims_count = batch.total_claims_count

    subject = f"💰 [Action Required] Weekly Batch #{batch.name} Audited by Accounts L1: Director Sign-Off (₹ {_safe_fmt_money(amount)})"
    body = _build_html_template(
        title="Weekly Batch Director Authorization",
        subtitle=f"Stage 5 &bull; Financial Sanction Sign-Off",
        greeting_name="Accounts Director",
        main_message=(
            f"Accounts L1 has completed the financial and tax audit for Weekly Batch <b>#{batch.name}</b>. "
            f"The final audited amount is <b>₹ {_safe_fmt_money(amount)}</b> across <b>{claims_count}</b> verified claims.<br><br>"
            f"Please review and provide final director authorization to queue for payment release."
        ),
        metric_label_1="Total Sanctioned Amount",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Company & Week",
        metric_val_2=f"{batch.company} &bull; {batch.week_number}",
        doc_url=doc_url,
        button_text="Authorize Weekly Batch",
        badge_color="#2563eb"
    )
    _dispatch_reimbursement_email(director_users, subject, body, "Weekly Accounts Audit Batch", batch_name, alert_color="blue")


def notify_releaser_on_weekly_batch_approved(batch_name: str) -> None:
    """18. Triggered when Director signs off on weekly batch -> Payment Releaser Disbursal."""
    batch = frappe.get_doc("Weekly Accounts Audit Batch", batch_name)
    releasers = _get_matrix_or_role_recipients(batch.company, 6, ["Payment Releaser"])

    doc_url = _get_form_url("Weekly Accounts Audit Batch", batch_name)
    amount = flt(batch.total_sanctioned_amount)

    subject = f"💵 [Action Required] Weekly Batch #{batch.name} Ready for Payment Release (₹ {_safe_fmt_money(amount)})"
    body = _build_html_template(
        title="Weekly Batch Ready for Disbursal",
        subtitle=f"Stage 6 &bull; Banking Release Queue",
        greeting_name="Payment Releaser",
        main_message=(
            f"Weekly Reimbursement Batch <b>#{batch.name}</b> has completed all administrative and finance approvals. "
            f"Total sanctioned funds of <b>₹ {_safe_fmt_money(amount)}</b> are ready for bank transfer / IDFC payout."
        ),
        metric_label_1="Total Net Payable",
        metric_val_1=f"₹ {_safe_fmt_money(amount)}",
        metric_label_2="Batch Reference",
        metric_val_2=f"{batch.name} ({batch.week_number})",
        doc_url=doc_url,
        button_text="Release Bank Disbursal",
        badge_color="#16a34a"
    )
    _dispatch_reimbursement_email(releasers, subject, body, "Weekly Accounts Audit Batch", batch_name, alert_color="green")

