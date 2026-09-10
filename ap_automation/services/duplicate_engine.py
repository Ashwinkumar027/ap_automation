"""
Group-Wide Duplicate Spend Detection Engine
Cross-entity, cross-lane fraud protection across all 6 group entities.

Responsibilities:
1. Tier 1 Exact Match: SHA256(Payee + Invoice No + Amount).
   -> Hard blocks submission across ANY of the 6 sister entities.
2. Tier 2 Temporal Match: SHA256(Beneficiary Account + Amount).
   -> Detects repeated identical payouts within a 7-day rolling window.
3. High Performance O(1) lookups via indexed AP Spend Fingerprint ledger.
4. Automatic lock release if a parent voucher is cancelled or rejected.
"""
import hashlib
from typing import Dict, Any, List, Optional
import frappe
from ap_automation.exceptions import APValidationError


def calculate_invoice_fingerprint(payee: str, invoice_no: str, amount: float) -> str:
    """
    Computes a normalized, case-insensitive Tier 1 exact match fingerprint.
    Formula: SHA256(Normalized Payee | Normalized Invoice No | Formatted Amount)
    """
    clean_payee = (payee or "").strip().lower()
    clean_invoice = (invoice_no or "").strip().lower()
    formatted_amount = f"{float(amount or 0.0):.2f}"
    
    raw = f"EXACT|{clean_payee}|{clean_invoice}|{formatted_amount}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def calculate_temporal_fingerprint(bank_account: str, amount: float) -> str:
    """
    Computes Tier 2 temporal match fingerprint for detecting repeated payouts to the same bank account.
    """
    clean_account = str(bank_account or "").strip()
    formatted_amount = f"{float(amount or 0.0):.2f}"
    
    raw = f"TEMPORAL|{clean_account}|{formatted_amount}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def check_group_duplicates(doc) -> Dict[str, Any]:
    """
    Scans across ALL 6 group companies and ALL 4 lanes for duplicate claims.
    Raises APValidationError if an active Tier 1 collision is discovered.
    """
    payee = getattr(doc, "payee_name", "")
    invoice_no = getattr(doc, "invoice_number", "")
    amount = getattr(doc, "total_amount", 0.0)
    bank_account = getattr(doc, "bank_account_number", "")
    current_docname = getattr(doc, "name", None)

    # 1. Tier 1 Check: Exact Payee + Invoice No + Amount
    if payee and invoice_no and float(amount) > 0:
        inv_hash = calculate_invoice_fingerprint(payee, invoice_no, amount)
        
        # Batch lookup in AP Spend Fingerprint
        collisions = frappe.get_all(
            "AP Spend Fingerprint",
            filters={
                "fingerprint_hash": inv_hash,
                "tier": "EXACT_INVOICE",
                "status": "ACTIVE"
            },
            fields=["name", "document_type", "document_name", "company", "payee_name", "invoice_number", "amount"],
            limit=1
        )
        
        for c in collisions:
            # Skip self
            if current_docname and c["document_name"] == current_docname:
                continue

            raise APValidationError(
                f"🚨 FRAUD SHIELD ALERT: Cross-Company Duplicate Detected!\n"
                f"This exact invoice has already been claimed in Company '{c['company']}' "
                f"(Voucher: {c['document_type']} #{c['document_name']}, "
                f"Invoice: '{c['invoice_number']}', Amount: ₹{c['amount']:,.2f}). "
                f"Duplicate submissions across sister entities are strictly blocked."
            )

    # 2. Tier 2 Check: Temporal Beneficiary Repeat Check (Rolling 7 Days)
    warnings = []
    if bank_account and float(amount) > 0:
        seven_days_ago = frappe.utils.add_days(frappe.utils.nowdate(), -7)
        temporal_hash = calculate_temporal_fingerprint(bank_account, amount)
        
        recent_repeats = frappe.get_all(
            "AP Spend Fingerprint",
            filters={
                "fingerprint_hash": temporal_hash,
                "tier": "TEMPORAL_ACCOUNT",
                "status": "ACTIVE",
                "creation": [">=", seven_days_ago]
            },
            fields=["document_type", "document_name", "company", "creation"],
            limit=3
        )
        
        filtered = [r for r in recent_repeats if not (current_docname and r["document_name"] == current_docname)]
        if filtered:
            warnings.append(
                f"Warning: Beneficiary account was paid this exact amount within the last 7 days "
                f"(Voucher: {filtered[0]['document_type']} #{filtered[0]['document_name']})."
            )

    return {"status": "clean", "warnings": warnings}


def register_spend_fingerprint(doc) -> List[str]:
    """
    Registers Tier 1 and Tier 2 fingerprints in the ledger upon voucher creation or approval.
    """
    payee = getattr(doc, "payee_name", "")
    invoice_no = getattr(doc, "invoice_number", "")
    amount = getattr(doc, "total_amount", 0.0)
    bank_account = getattr(doc, "bank_account_number", "")
    doc_type = getattr(doc, "doctype", "AP Document")
    doc_name = getattr(doc, "name", "UNSAVED")
    company = getattr(doc, "company", "")

    registered = []

    # Register Tier 1 Exact Match
    if payee and invoice_no and float(amount) > 0:
        inv_hash = calculate_invoice_fingerprint(payee, invoice_no, amount)
        existing = frappe.db.exists("AP Spend Fingerprint", {"fingerprint_hash": inv_hash, "status": "ACTIVE"})
        if not existing:
            f1 = frappe.get_doc({
                "doctype": "AP Spend Fingerprint",
                "fingerprint_hash": inv_hash,
                "tier": "EXACT_INVOICE",
                "status": "ACTIVE",
                "document_type": doc_type,
                "document_name": doc_name,
                "company": company,
                "payee_name": payee,
                "invoice_number": invoice_no,
                "amount": float(amount),
                "bank_account_number": bank_account
            })
            f1.insert(ignore_permissions=True)
            registered.append(f1.name)

    # Register Tier 2 Temporal Match
    if bank_account and float(amount) > 0:
        temp_hash = calculate_temporal_fingerprint(bank_account, amount)
        f2 = frappe.get_doc({
            "doctype": "AP Spend Fingerprint",
            "fingerprint_hash": temp_hash,
            "tier": "TEMPORAL_ACCOUNT",
            "status": "ACTIVE",
            "document_type": doc_type,
            "document_name": doc_name,
            "company": company,
            "payee_name": payee,
            "invoice_number": invoice_no,
            "amount": float(amount),
            "bank_account_number": bank_account
        })
        f2.insert(ignore_permissions=True)
        registered.append(f2.name)

    frappe.db.commit()
    return registered


def release_spend_fingerprint(doc) -> None:
    """
    Releases all active fingerprint locks if a parent voucher is Rejected or Cancelled.
    Allows honest errors to be re-submitted.
    """
    doc_name = getattr(doc, "name", None)
    if not doc_name:
        return

    frappe.db.sql(
        """
        UPDATE `tabAP Spend Fingerprint`
        SET status = 'RELEASED', modified = %s
        WHERE document_name = %s AND status = 'ACTIVE'
        """,
        (frappe.utils.now(), doc_name)
    )
    frappe.db.commit()
