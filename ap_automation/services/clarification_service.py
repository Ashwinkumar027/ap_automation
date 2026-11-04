# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, get_url_to_form, escape_html
from typing import Dict, List, Any, Optional
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.notification_service import _resolve_email


def _map_doctype_to_lane(doctype: str) -> str:
    """Maps DocType name to AP Approval Matrix document_lane keyword."""
    dt = str(doctype).strip()
    if dt in ("Petty Cash Entry", "Petty Cash"):
        return "Petty Cash Entry"
    if dt in ("Employee Reimbursement Claim", "Employee Reimbursement", "Pre Travel Request"):
        return "Employee Reimbursement Claim"
    if dt in ("Vendor Invoice Claim", "AP Vendor Invoice", "Vendor Invoice"):
        return "AP Vendor Invoice"
    if dt in ("Admin Weekly Vendor Claim", "Admin Weekly Vendor"):
        return "Admin Weekly Vendor Claim"
    if dt in ("Event Advance Request", "Event Expense Claim", "Event Settlement"):
        return "Event Advance Request"
    return dt


def resolve_document_stakeholders(doctype: str, docname: str) -> List[Dict[str, Any]]:
    """
    Dynamically identifies all relevant human stakeholders for a specific AP document
    by cross-referencing document fields and the governing AP Approval Matrix.
    Returns zero hardcoding, dynamic 1-to-1 stakeholder directory.
    """
    if not frappe.db.exists(doctype, docname):
        return []

    doc = frappe.get_doc(doctype, docname)
    company = getattr(doc, "company", None)
    lane = _map_doctype_to_lane(doctype)

    stakeholders: List[Dict[str, Any]] = []
    seen_users = set()

    def _add_stakeholder(role_title: str, user_or_emp: Optional[str], source: str = "Direct"):
        if not user_or_emp:
            return
        user_val = str(user_or_emp).strip()
        email_val = _resolve_email(user_val)

        # Lookup user name
        full_name = user_val
        if frappe.db.exists("User", user_val):
            full_name = frappe.db.get_value("User", user_val, "full_name") or user_val
        elif frappe.db.exists("Employee", user_val):
            emp = frappe.get_doc("Employee", user_val)
            full_name = emp.employee_name or user_val
            user_val = emp.user_id or user_val

        if not user_val or user_val in ("Administrator", "Guest"):
            return

        key = (role_title, user_val)
        if key in seen_users:
            return
        seen_users.add(key)

        stakeholders.append({
            "role": role_title,
            "user": user_val,
            "email": email_val or user_val,
            "name": full_name,
            "source": source
        })

    # 1. Claimant / Submitter / Custodian
    claimant_val = (
        getattr(doc, "employee", None)
        or getattr(doc, "claimant", None)
        or getattr(doc, "spoc", None)
        or getattr(doc, "custodian", None)
        or getattr(doc, "prepared_by", None)
        or doc.owner
    )
    _add_stakeholder("Claimant / Submitter", claimant_val, "Document Owner")

    # 2. Document Explicit Stage Assignees (if already stamped on doc)
    if getattr(doc, "reporting_manager", None):
        _add_stakeholder("Reporting Manager", doc.reporting_manager, "Document Field")
    if getattr(doc, "admin_l1_approver", None):
        _add_stakeholder("Admin Reviewer", doc.admin_l1_approver, "Document Field")
    if getattr(doc, "accounts_l1_approver", None):
        _add_stakeholder("Accounts L1 Auditor (Gokul)", doc.accounts_l1_approver, "Document Field")
    if getattr(doc, "accounts_auditor", None):
        _add_stakeholder("Accounts L1 Auditor", doc.accounts_auditor, "Document Field")
    if getattr(doc, "accounts_director", None):
        _add_stakeholder("Accounts Director", doc.accounts_director, "Document Field")
    if getattr(doc, "director_approver", None):
        _add_stakeholder("Accounts Director", doc.director_approver, "Document Field")
    if getattr(doc, "payment_releaser", None):
        _add_stakeholder("Payment Releaser", doc.payment_releaser, "Document Field")

    # 3. Dynamic AP Approval Matrix Resolution
    matrix_name = None
    if company:
        matrix_name = frappe.db.get_value(
            "AP Approval Matrix",
            {"company": company, "document_lane": lane, "is_active": 1},
            "name"
        )
    if not matrix_name:
        matrix_name = frappe.db.get_value(
            "AP Approval Matrix",
            {"document_lane": lane, "is_active": 1},
            "name"
        )

    if matrix_name and frappe.db.exists("AP Approval Matrix", matrix_name):
        matrix = frappe.get_doc("AP Approval Matrix", matrix_name)
        for lvl in getattr(matrix, "approval_levels", []):
            approver = lvl.designated_approver
            lvl_name = (lvl.level_name or "").lower()
            if not approver:
                continue

            if "director" in lvl_name or lvl.level_number in (4, 5) and "accounts" in lvl_name:
                _add_stakeholder("Accounts Director", approver, f"Matrix L{lvl.level_number}")
            elif "l1" in lvl_name or "audit" in lvl_name or "accounts" in lvl_name:
                _add_stakeholder("Accounts L1 Auditor (Gokul)", approver, f"Matrix L{lvl.level_number}")
            elif "admin" in lvl_name:
                _add_stakeholder("Admin Reviewer", approver, f"Matrix L{lvl.level_number}")
            elif "manager" in lvl_name:
                _add_stakeholder("Reporting Manager", approver, f"Matrix L{lvl.level_number}")
            elif "release" in lvl_name or "payment" in lvl_name:
                _add_stakeholder("Payment Releaser", approver, f"Matrix L{lvl.level_number}")
            else:
                _add_stakeholder(lvl.level_name, approver, f"Matrix L{lvl.level_number}")

    # 4. Fallback Role Lookups if matrix levels had empty approvers
    has_l1 = any("Accounts L1" in s["role"] for s in stakeholders)
    has_director = any("Accounts Director" in s["role"] for s in stakeholders)

    if not has_l1:
        # Check users with Accounts L1 Auditor role
        l1_users = frappe.get_all("Has Role", filters={"role": "Accounts L1 Auditor", "parenttype": "User"}, pluck="parent")
        if not l1_users:
            l1_users = frappe.get_all("Has Role", filters={"role": "Accounts User", "parenttype": "User"}, pluck="parent")
        for u in l1_users[:2]:
            _add_stakeholder("Accounts L1 Auditor (Gokul)", u, "Role Fallback")

    if not has_director:
        dir_users = frappe.get_all("Has Role", filters={"role": "Accounts Director", "parenttype": "User"}, pluck="parent")
        for u in dir_users[:2]:
            _add_stakeholder("Accounts Director", u, "Role Fallback")

    return stakeholders


def resolve_user_role_badge(doctype: str, docname: str, user: str) -> str:
    """
    Returns the exact role badge of the user with respect to this specific document.
    E.g. 'Accounts Director', 'Accounts L1 Auditor', 'Claimant / Submitter', 'Admin Reviewer'.
    """
    if not user:
        return "User"

    user_roles = frappe.get_roles(user)
    if "System Manager" in user_roles and user == "Administrator":
        return "System Admin"

    stakeholders = resolve_document_stakeholders(doctype, docname)
    for s in stakeholders:
        if s["user"] == user:
            return s["role"]

    # Role heuristics
    if "Accounts Director" in user_roles:
        return "Accounts Director"
    if "Accounts L1 Auditor" in user_roles or "Accounts User" in user_roles:
        return "Accounts L1 Auditor"
    if "Admin L1 Approver" in user_roles:
        return "Admin Reviewer"

    return "Auditor / Reviewer"


@frappe.whitelist()
def get_clarification_thread(doctype: str, docname: str) -> Dict[str, Any]:
    """
    Fetches the complete clarification discussion stream, dynamically resolved
    participant list, and un-resolved query counters for this document.
    """
    if not frappe.has_permission(doctype, "read", docname):
        frappe.throw("You do not have permission to view clarifications for this document.", exc=APSecurityError)

    queries = frappe.get_all(
        "AP Clarification Query",
        filters={"parent_doctype": doctype, "parent_docname": docname},
        fields=[
            "name", "creation", "query_status", "is_resolution", "resolved_by", "resolved_at",
            "from_user", "from_full_name", "from_role_badge",
            "target_role", "target_user", "target_user_name",
            "message", "attachment"
        ],
        order_by="creation asc"
    )

    stakeholders = resolve_document_stakeholders(doctype, docname)
    current_badge = resolve_user_role_badge(doctype, docname, frappe.session.user)
    current_name = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user

    pending_count = sum(1 for q in queries if q.query_status == "Pending Reply")
    resolved_count = sum(1 for q in queries if q.query_status == "Resolved")

    return {
        "success": True,
        "doctype": doctype,
        "docname": docname,
        "queries": queries,
        "stakeholders": stakeholders,
        "summary": {
            "total": len(queries),
            "pending": pending_count,
            "resolved": resolved_count,
            "has_unresolved": pending_count > 0
        },
        "current_user": {
            "user": frappe.session.user,
            "name": current_name,
            "role_badge": current_badge
        }
    }


@frappe.whitelist()
def post_clarification_query(
    doctype: str,
    docname: str,
    message: str,
    target_role: Optional[str] = None,
    target_user: Optional[str] = None,
    attachment: Optional[str] = None,
    is_resolution: int = 0
) -> Dict[str, Any]:
    """
    Submits a new immutable clarification question or resolution answer in the thread.
    Automatically:
    1. Dispatches branded email and real-time Desk notification to the target.
    2. Updates document activity timeline with a clear clarification log.
    3. Stretches zero-trust audit compliance with immutable message records.
    """
    if not frappe.has_permission(doctype, "read", docname):
        frappe.throw("You do not have permission to post clarifications on this document.", exc=APSecurityError)

    msg_clean = (message or "").strip()
    if not msg_clean:
        frappe.throw("Clarification message text cannot be empty.", exc=APValidationError)

    doc = frappe.get_doc(doctype, docname)
    company = getattr(doc, "company", None)
    sender = frappe.session.user
    sender_name = frappe.db.get_value("User", sender, "full_name") or sender
    sender_badge = resolve_user_role_badge(doctype, docname, sender)

    target_name = None
    if target_user:
        target_name = frappe.db.get_value("User", target_user, "full_name") or target_user

    # Auto-resolve previous pending queries if marked as resolution
    is_res = int(is_resolution or 0)
    if is_res:
        open_queries = frappe.get_all(
            "AP Clarification Query",
            filters={"parent_doctype": doctype, "parent_docname": docname, "query_status": "Pending Reply"},
            fields=["name"]
        )
        for oq in open_queries:
            frappe.db.set_value("AP Clarification Query", oq.name, {
                "query_status": "Resolved",
                "resolved_by": sender,
                "resolved_at": now_datetime()
            })

    q = frappe.get_doc({
        "doctype": "AP Clarification Query",
        "parent_doctype": doctype,
        "parent_docname": docname,
        "company": company,
        "query_status": "Resolved" if is_res else "Pending Reply",
        "is_resolution": is_res,
        "resolved_by": sender if is_res else None,
        "resolved_at": now_datetime() if is_res else None,
        "from_user": sender,
        "from_full_name": sender_name,
        "from_role_badge": sender_badge,
        "target_role": target_role or "Anyone / Public",
        "target_user": target_user or None,
        "target_user_name": target_name,
        "message": msg_clean,
        "attachment": attachment or None
    })
    q.insert(ignore_permissions=True)
    frappe.db.commit()

    # Append Timeline Comment on Parent Doc for Frappe Audit Trail
    try:
        target_label = target_name or target_role or "All Stakeholders"
        action_verb = "submitted resolution for" if is_res else "raised clarification for"
        comment_html = f"""
        <div class="ap-clarification-timeline-note" style="border-left: 3px solid #0284c7; padding-left: 8px;">
            <div style="font-size: 11px; color: #0284c7; font-weight: 700; text-transform: uppercase;">
                💬 Clarification Thread &bull; {sender_badge} &rarr; @{target_label}
            </div>
            <div style="margin-top: 4px; color: #1e293b; font-size: 13px;">
                {escape_html(msg_clean)}
            </div>
        </div>
        """
        doc.add_comment("Comment", comment_html)
    except Exception:
        pass

    # Trigger Notifications
    try:
        from ap_automation.services.notification_service import notify_clarification_query
        notify_clarification_query(q.name)
    except Exception as e:
        frappe.log_error(f"Failed to dispatch clarification notification for {q.name}: {e}")

    return {
        "success": True,
        "query": q.as_dict()
    }


@frappe.whitelist()
def mark_query_resolved(query_name: str, resolution_notes: Optional[str] = None) -> Dict[str, Any]:
    """
    Marks a specific clarification query as resolved.
    Notifies the original sender that their query was satisfied.
    """
    if not frappe.db.exists("AP Clarification Query", query_name):
        frappe.throw("Clarification query not found.", exc=APValidationError)

    q = frappe.get_doc("AP Clarification Query", query_name)
    if not frappe.has_permission(q.parent_doctype, "read", q.parent_docname):
        frappe.throw("Permission denied.", exc=APSecurityError)

    user = frappe.session.user
    q.query_status = "Resolved"
    q.is_resolution = 1
    q.resolved_by = user
    q.resolved_at = now_datetime()
    q.save(ignore_permissions=True)
    frappe.db.commit()

    # Append note if provided
    if resolution_notes and str(resolution_notes).strip():
        post_clarification_query(
            doctype=q.parent_doctype,
            docname=q.parent_docname,
            message=str(resolution_notes).strip(),
            target_role=q.from_role_badge or "Questioner",
            target_user=q.from_user,
            is_resolution=1
        )

    # Notify Questioner
    try:
        from ap_automation.services.notification_service import notify_clarification_resolved
        notify_clarification_resolved(query_name)
    except Exception as e:
        frappe.log_error(f"Failed to dispatch resolution notification for {query_name}: {e}")

    return {"success": True}

