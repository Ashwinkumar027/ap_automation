"""
Vendor Master Governance & Deduplication Service (PRD Requirement 9)
Enforces:
1. Strict prevention of duplicate vendor creation by matching on PAN or GSTIN across ERPNext.
2. Hard-block error on PAN / GSTIN duplicate conflict.
3. Proactive fuzzy name similarity warning (>= 85% match) to alert users to potential duplicate records.
"""

import re
import difflib
from typing import Optional
import frappe
from ap_automation.exceptions import APValidationError, APSecurityError


def extract_pan_and_gstin(tax_id: Optional[str]):
    """
    Extracts standardized GSTIN and 10-character PAN from tax_id or returns None.
    Standard Indian GSTIN: 2 state digits + 10 alphanumeric PAN + 1 entity + 1 'Z' + 1 checksum.
    Standard Indian PAN: 5 uppercase letters + 4 digits + 1 uppercase letter.
    """
    if not tax_id:
        return None, None

    clean = re.sub(r"[^A-Za-z0-9]", "", str(tax_id)).strip().upper()
    if not clean:
        return None, None

    pan = None
    gstin = None

    if len(clean) == 15:
        gstin = clean
        candidate_pan = clean[2:12]
        if re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$", candidate_pan):
            pan = candidate_pan
    elif len(clean) == 10:
        if re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$", clean):
            pan = clean

    return pan, gstin


def validate_supplier_deduplication(doc, method=None):
    """
    Validation hook for ERPNext Supplier DocType.
    1. Blocks duplicate vendor creation if PAN or GSTIN matches an existing supplier.
    2. Issues a prominent warning if the supplier name is >= 85% similar to an existing vendor.
    """
    supplier_name = (getattr(doc, "supplier_name", "") or getattr(doc, "name", "")).strip()
    raw_tax_id = getattr(doc, "tax_id", None) or getattr(doc, "pan", None)

    # ----------------------------------------------------------------------------------
    # 1. HARD BLOCK ON DUPLICATE PAN / GSTIN (PRD Requirement 9)
    # ----------------------------------------------------------------------------------
    if raw_tax_id:
        pan, gstin = extract_pan_and_gstin(raw_tax_id)
        current_id = getattr(doc, "name", None)

        duplicate = None

        if gstin:
            duplicate = frappe.db.sql(
                """
                SELECT name, supplier_name, tax_id
                FROM `tabSupplier`
                WHERE name != %s
                  AND UPPER(REPLACE(REPLACE(tax_id, ' ', ''), '-', '')) = %s
                LIMIT 1
                """,
                (current_id or "", gstin),
                as_dict=True
            )

        if not duplicate and pan:
            duplicate = frappe.db.sql(
                """
                SELECT name, supplier_name, tax_id
                FROM `tabSupplier`
                WHERE name != %s
                  AND (
                    UPPER(REPLACE(REPLACE(tax_id, ' ', ''), '-', '')) = %s
                    OR UPPER(REPLACE(REPLACE(tax_id, ' ', ''), '-', '')) LIKE %s
                  )
                LIMIT 1
                """,
                (current_id or "", pan, f"__{pan}___"),
                as_dict=True
            )

        if duplicate and len(duplicate) > 0:
            dup_vendor = duplicate[0]
            error_msg = (
                f"🚫 <b>Duplicate Vendor Creation Blocked!</b><br><br>"
                f"A vendor with matching <b>PAN / GSTIN ({raw_tax_id})</b> already exists in ERPNext Master:<br>"
                f"• <b>Existing Vendor ID:</b> {dup_vendor.name}<br>"
                f"• <b>Existing Vendor Name:</b> {dup_vendor.supplier_name}<br>"
                f"• <b>Registered Tax ID:</b> {dup_vendor.tax_id or 'N/A'}<br><br>"
                f"Per PRD Requirement 9, duplicate vendor accounts with the same PAN or GSTIN are strictly prohibited. "
                f"Please use the existing vendor account."
            )
            frappe.throw(error_msg, title="Duplicate Vendor Prohibited", exc=APValidationError)

    # ----------------------------------------------------------------------------------
    # 2. PROACTIVE FUZZY SIMILARITY WARNING (PRD Requirement 9)
    # ----------------------------------------------------------------------------------
    if supplier_name and len(supplier_name) >= 3:
        clean_name = re.sub(r"[^a-zA-Z0-9]", "", supplier_name).lower()
        current_id = getattr(doc, "name", None)

        existing_suppliers = frappe.db.sql(
            """
            SELECT name, supplier_name
            FROM `tabSupplier`
            WHERE name != %s AND disabled = 0
            LIMIT 500
            """,
            (current_id or "",),
            as_dict=True
        )

        for existing in existing_suppliers:
            existing_name = (existing.supplier_name or existing.name or "").strip()
            clean_existing = re.sub(r"[^a-zA-Z0-9]", "", existing_name).lower()

            if not clean_existing or clean_existing == clean_name:
                continue

            similarity = difflib.SequenceMatcher(None, clean_name, clean_existing).ratio()
            if similarity >= 0.85:
                pct = int(similarity * 100)
                frappe.msgprint(
                    msg=(
                        f"⚠️ <b>Potential Duplicate Vendor Warning ({pct}% Name Similarity):</b><br>"
                        f"The new vendor name '<b>{supplier_name}</b>' closely matches an existing active vendor: "
                        f"<b>{existing_name}</b> (ID: <code>{existing.name}</code>).<br>"
                        f"Please verify this is not an unintentional duplicate before proceeding."
                    ),
                    indicator="orange",
                    title="Similar Vendor Name Warning"
                )
                break
