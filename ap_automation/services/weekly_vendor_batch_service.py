# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
import frappe
from frappe import _
from frappe.utils import getdate, nowdate, now_datetime, flt, cstr, fmt_money


def get_current_friday(ref_date=None) -> datetime.date:
    """Calculates the Friday date for the current week."""
    dt = getdate(ref_date or nowdate())
    days_ahead = 4 - dt.weekday()
    return dt + datetime.timedelta(days=days_ahead)


@frappe.whitelist()
def preview_approved_vendor_invoices(company: str, cut_off_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns the count and total net payable amount of Vendor Invoice Claims
    in 'Approved for Payment' status on or before the cut_off_date.
    Applies active batch collision shielding.
    """
    if not company:
        return {"eligible_count": 0, "total_amount": 0.0, "message": _("Select a Company first.")}

    c_date = getdate(cut_off_date or nowdate())

    # Collision Shield: Exclude claims locked in active unfinalized batches
    active_batch_claims = frappe.db.sql("""
        select distinct it.invoice_claim
        from `tabWeekly Vendor Payment Item` it
        join `tabWeekly Vendor Payment Batch` b on it.parent = b.name
        where b.docstatus < 2
          and b.status not in ('Cancelled', 'Paid')
          and it.status != 'Disputed / Excluded'
          and ifnull(it.invoice_claim, '') != ''
    """, as_dict=True)
    locked_claims = {r["invoice_claim"] for r in active_batch_claims}

    # Query matching Vendor Invoice Claims
    matching_claims = frappe.get_all(
        "Vendor Invoice Claim",
        filters={
            "company": company,
            "status": "Approved for Payment",
            "docstatus": ["<", 2]
        },
        fields=["name", "net_payable_amount", "total_amount", "tax_invoice_date", "creation"]
    )

    eligible_claims = []
    total_amt = 0.0

    for c in matching_claims:
        if c.name in locked_claims:
            continue
        p_date = getdate(c.tax_invoice_date or c.creation or nowdate())
        if p_date <= c_date:
            payable = flt(c.net_payable_amount or c.total_amount or 0.0)
            eligible_claims.append(c.name)
            total_amt += payable

    count = len(eligible_claims)
    return {
        "eligible_count": count,
        "total_amount": round(total_amt, 2),
        "cut_off_date": str(c_date),
        "message": _("{0} approved vendor invoice(s) found totaling INR {1:,.2f} up to cut-off {2}.").format(
            count, total_amt, c_date
        )
    }


@frappe.whitelist()
def fetch_approved_vendor_invoices(
    batch_name: str,
    cut_off_date: Optional[str] = None,
    sync_mode: str = "Safe Append",
    company: Optional[str] = None
) -> Dict[str, Any]:
    """
    Ingests all 'Approved for Payment' Vendor Invoice Claims into the Weekly Vendor Payment Batch.
    Supports Safe Append (preserves already reviewed items) or Fresh Sync.
    Bi-directionally links batch_id on Vendor Invoice Claim.
    """
    if not batch_name or not frappe.db.exists("Weekly Vendor Payment Batch", batch_name):
        frappe.throw(_("Weekly Vendor Payment Batch '{0}' not found.").format(batch_name))

    batch = frappe.get_doc("Weekly Vendor Payment Batch", batch_name)
    if batch.status in ("Paid", "Cancelled"):
        frappe.throw(_("Cannot modify batch '{0}' in '{1}' status.").format(batch.name, batch.status))

    target_company = company or batch.company
    if not target_company:
        frappe.throw(_("Please select a Company Entity on the batch first."))

    c_date = getdate(cut_off_date or batch.batch_date or nowdate())

    # Active Batch Collision Shield (excluding current batch)
    active_batch_claims = frappe.db.sql("""
        select distinct it.invoice_claim
        from `tabWeekly Vendor Payment Item` it
        join `tabWeekly Vendor Payment Batch` b on it.parent = b.name
        where b.docstatus < 2
          and b.name != %s
          and b.status not in ('Cancelled', 'Paid')
          and it.status != 'Disputed / Excluded'
          and ifnull(it.invoice_claim, '') != ''
    """, (batch.name,), as_dict=True)
    locked_claims = {r["invoice_claim"] for r in active_batch_claims}

    # Query approved claims
    candidate_claims = frappe.get_all(
        "Vendor Invoice Claim",
        filters={
            "company": target_company,
            "status": "Approved for Payment",
            "docstatus": ["<", 2]
        },
        fields=[
            "name", "vendor", "vendor_name", "purchase_order", "tax_invoice_number", "tax_invoice_date",
            "bank_name", "bank_account_number", "bank_ifsc_code", "base_amount", "gst_amount",
            "tds_amount", "net_payable_amount", "total_amount", "creation"
        ]
    )

    eligible_claims = []
    for c in candidate_claims:
        if c.name in locked_claims:
            continue
        p_date = getdate(c.tax_invoice_date or c.creation or nowdate())
        if p_date <= c_date:
            eligible_claims.append(c)

    existing_claims = set()
    if sync_mode == "Fresh Sync":
        batch.items = []
    else:
        existing_claims = {it.invoice_claim for it in batch.items if it.invoice_claim}

    added_count = 0
    for c in eligible_claims:
        if c.name in existing_claims:
            continue

        net_pay = flt(c.net_payable_amount or c.total_amount or 0.0)
        batch.append("items", {
            "invoice_claim": c.name,
            "invoice_number": c.tax_invoice_number or c.name,
            "supplier": c.vendor,
            "supplier_name": c.vendor_name or c.vendor,
            "purchase_order": c.purchase_order or "",
            "invoice_date": c.tax_invoice_date,
            "bank_name": c.bank_name or "",
            "bank_account_number": c.bank_account_number or "",
            "bank_ifsc": c.bank_ifsc_code or "",
            "base_amount": flt(c.base_amount),
            "gst_amount": flt(c.gst_amount),
            "tds_amount": flt(c.tds_amount),
            "net_payable_amount": net_pay,
            "status": "Pending Payment"
        })
        existing_claims.add(c.name)
        added_count += 1

        # Link batch on individual claim
        frappe.db.set_value("Vendor Invoice Claim", c.name, "batch_id", batch.name, update_modified=False)

    # Recalculate batch summary totals
    tot_base = 0.0
    tot_gst = 0.0
    tot_tds = 0.0
    tot_pay = 0.0
    unique_vendors = set()

    for it in batch.items:
        if it.status != "Disputed / Excluded":
            tot_base += flt(it.base_amount)
            tot_gst += flt(it.gst_amount)
            tot_tds += flt(it.tds_amount)
            tot_pay += flt(it.net_payable_amount)
            if it.supplier:
                unique_vendors.add(it.supplier)

    batch.total_invoices_count = len(batch.items)
    batch.total_vendors_count = len(unique_vendors)
    batch.total_base_amount = round(tot_base, 2)
    batch.total_gst_amount = round(tot_gst, 2)
    batch.total_tds_amount = round(tot_tds, 2)
    batch.total_payable_amount = round(tot_pay, 2)

    if batch.status == "Draft":
        batch.status = "Pending Accounts Review"

    batch.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "batch_name": batch.name,
        "added_count": added_count,
        "total_invoices_count": batch.total_invoices_count,
        "total_payable_amount": batch.total_payable_amount,
        "cut_off_date": str(c_date),
        "message": _("Fetched {0} new approved vendor invoice(s) (Cut-Off: {1}). Total batch: {2} invoices (INR {3:,.2f}).").format(
            added_count, c_date, batch.total_invoices_count, batch.total_payable_amount
        )
    }


@frappe.whitelist()
def authorize_vendor_batch_by_accounts_director(batch_name: str, remarks: Optional[str] = None) -> Dict[str, Any]:
    """
    Accounts Director Authorization:
    Signs off the Weekly Vendor Payment Batch, transitioning status to 'Approved for Payment'.
    Unlocks IDFC Bank Bulk Excel download and Payment Release handoff.
    """
    if not batch_name or not frappe.db.exists("Weekly Vendor Payment Batch", batch_name):
        frappe.throw(_("Weekly Vendor Payment Batch '{0}' not found.").format(batch_name))

    batch = frappe.get_doc("Weekly Vendor Payment Batch", batch_name)
    user = frappe.session.user

    allowed_roles = {"Accounts Director", "Accounts Manager", "AP Director", "System Manager", "Administrator"}
    user_roles = set(frappe.get_roles(user))
    if not (allowed_roles & user_roles) and user != "Administrator":
        frappe.throw(_("Access Denied: Only Accounts Director or Accounts Manager can authorize vendor payment batches."))

    if not batch.items:
        frappe.throw(_("Cannot authorize an empty vendor payment batch. Please fetch invoices first."))

    batch.status = "Approved for Payment"
    batch.accounts_director = user
    batch.accounts_director_sign_date = now_datetime()
    batch.save(ignore_permissions=True)

    batch.add_comment(
        "Comment",
        text=f"⭐ <b>Accounts Director Authorization:</b> Authorized by {user} for IDFC Netbanking Payout. Remarks: {remarks or 'Approved for payment.'}"
    )
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "batch_name": batch.name,
        "message": _("Batch {0} authorized by Accounts Director! IDFC Disbursal Excel ready for download.").format(batch.name)
    }


@frappe.whitelist()
def trigger_vendor_batch_payment_release_notification(batch_name: str) -> Dict[str, Any]:
    """
    Maker-Checker Handoff:
    Invoked by the Maker (Accounts) after uploading the weekly vendor disbursal file to the IDFC Portal.
    Dynamically resolves the designated AP Director (TO) and Accounts Director (CC) strictly from the AP Approval Matrix,
    stamps immutable audit logs, updates payment release flags, and sends official notification email with direct batch link.
    """
    if not batch_name:
        frappe.throw(_("Batch Name is required."))

    doc = frappe.get_doc("Weekly Vendor Payment Batch", batch_name)
    user = frappe.session.user

    allowed_roles = {
        "Accounts Director", "Accounts L1 Auditor", "Accounts User", "Accounts Manager",
        "Payment Releaser", "Director Tier", "AP Director", "System Manager", "Administrator"
    }
    user_roles = set(frappe.get_roles(user))
    if not (allowed_roles & user_roles) and user != "Administrator":
        frappe.throw(_("You do not have permission to trigger payment release notifications."))

    if doc.status not in ("Approved for Payment", "Paid"):
        frappe.throw(_("Batch {0} must be in 'Approved for Payment' status to trigger payment release.").format(batch_name))

    from ap_automation.services.notification_service import notify_payment_releaser_on_idfc_upload

    res = notify_payment_releaser_on_idfc_upload(
        voucher_doctype=doc.doctype,
        voucher_name=doc.name,
        uploaded_by=user
    )

    releaser = res.get("releaser")
    ad = res.get("accounts_director")

    doc.db_set({
        "payment_release_notified": 1,
        "payment_release_notified_on": frappe.utils.now_datetime(),
        "payment_release_maker": user,
        "payment_releaser": releaser if releaser and not doc.payment_releaser else doc.payment_releaser
    }, update_modified=False)

    releaser_display = frappe.db.get_value("User", releaser, "full_name") or releaser
    ad_display = (frappe.db.get_value("User", ad, "full_name") or ad) if ad else "N/A"
    doc.add_comment(
        "Comment",
        text=f"📤 <b>Payment Release Notified:</b> IDFC Excel disbursal file uploaded to IDFC Netbanking by {user}. "
             f"Payout authorization request dispatched to AP Director (<b>{releaser_display}</b>) with CC to Accounts Director (<b>{ad_display}</b>)."
    )
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "batch_name": doc.name,
        "releaser": releaser,
        "accounts_director": ad,
        "message": _("Payment Release notification sent! AP Director ({0}) has been notified.").format(releaser_display)
    }


@frappe.whitelist()
def disburse_weekly_vendor_batch(batch_name: str, payment_reference: str, remarks: Optional[str] = None) -> Dict[str, Any]:
    """
    Bank Settlement & Stamping (Payment Releaser / AP Director):
    Marks the batch as 'Paid', stamps Bank Batch UTR reference, and automatically
    updates all linked Vendor Invoice Claims to 'Paid' with audit trail logging.
    """
    if not batch_name or not frappe.db.exists("Weekly Vendor Payment Batch", batch_name):
        frappe.throw(_("Weekly Vendor Payment Batch '{0}' not found.").format(batch_name))

    if not payment_reference or not str(payment_reference).strip():
        frappe.throw(_("Bank Disbursal / UTR Reference is required."), title=_("UTR Mandatory"))

    batch = frappe.get_doc("Weekly Vendor Payment Batch", batch_name)
    user = frappe.session.user

    allowed_roles = {"Payment Releaser", "AP Director", "Accounts Director", "Accounts Manager", "System Manager", "Administrator"}
    user_roles = set(frappe.get_roles(user))
    if not (allowed_roles & user_roles) and user != "Administrator":
        frappe.throw(_("Unauthorized: Only Payment Releaser or AP Director can disburse vendor batches."))

    if batch.status != "Approved for Payment":
        frappe.throw(_("Batch '{0}' must be in 'Approved for Payment' to disburse.").format(batch.name))

    clean_utr = str(payment_reference).strip().upper()
    now_ts = now_datetime()

    batch.status = "Paid"
    batch.payment_reference = clean_utr
    batch.payment_date = now_ts
    if not batch.payment_releaser:
        batch.payment_releaser = user

    settled_count = 0
    for it in batch.items:
        if it.status != "Disputed / Excluded":
            it.status = "Paid"
            it.utr_reference = clean_utr

            # Cascade status to individual Vendor Invoice Claim
            if it.invoice_claim and frappe.db.exists("Vendor Invoice Claim", it.invoice_claim):
                frappe.db.set_value("Vendor Invoice Claim", it.invoice_claim, {
                    "status": "Paid",
                    "utr": clean_utr,
                    "workflow_state": "Disbursed via Corporate Bank Transfer"
                }, update_modified=False)

                # Record in AP Approval Trail
                trail_entry = frappe.get_doc({
                    "doctype": "AP Approval Trail",
                    "parent": it.invoice_claim,
                    "parenttype": "Vendor Invoice Claim",
                    "parentfield": "approval_trail",
                    "level_number": 6,
                    "level_name": "Stage 6: Bank Disbursement & UTR Stamped (Weekly Batch)",
                    "action_taken_by": user,
                    "action": "APPROVED",
                    "action_timestamp": now_ts,
                    "remarks": f"Disbursed via Weekly Vendor Batch #{batch.name} | Bank UTR: {clean_utr} | {remarks or 'Settled'}"
                })
                trail_entry.insert(ignore_permissions=True)

                settled_count += 1

    batch.save(ignore_permissions=True)
    batch.add_comment(
        "Comment",
        text=f"💳 <b>Payment Disbursed:</b> Bank Batch UTR <code>{clean_utr}</code> stamped by {user}. {settled_count} vendor invoice(s) marked Paid."
    )
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "batch_name": batch.name,
        "settled_count": settled_count,
        "utr": clean_utr,
        "message": _("Batch {0} disbursed! {1} vendor invoice(s) marked Paid with UTR {2}.").format(batch.name, settled_count, clean_utr)
    }
