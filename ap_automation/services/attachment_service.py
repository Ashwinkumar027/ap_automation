# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Universal Expense Claim Receipt & Proof Aggregator Service
Collects, sanitizes, and packages all receipt attachments, tax invoices,
pre-approval screenshots, and audit trail documents across all spend lanes.
Provides permission-safe streaming of both Public and Private files directly
to the AP Proof & Receipt Gallery.
"""

import json
import os
import io
import mimetypes
import urllib.parse
import zipfile
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote

import frappe
from frappe import _
from ap_automation.exceptions import APValidationError, APSecurityError


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

BATCH_AUDIT_ROLES = {
    "Accounts L1 Auditor",
    "Accounts Director",
    "AP Director",
    "Accounts Manager",
    "Admin L1 Approver",
    "Admin L2 Approver",
    "Admin Manager",
    "Receptionist",
    "Payment Releaser",
    "System Manager",
}


def _check_document_permission(doctype: str, docname: str, ptype: str = "read") -> None:
    """Verifies user has permission on the parent AP document or an enclosing audit batch."""
    if not doctype or not docname:
        return
    if frappe.has_permission(doctype, ptype=ptype, doc=docname):
        return

    user = frappe.session.user
    user_roles = set(frappe.get_roles(user)) if user else set()
    if ptype == "read" and (user == "Administrator" or user_roles.intersection(BATCH_AUDIT_ROLES)):
        if frappe.db.exists("Weekly Accounts Audit Item", {"voucher_no": docname}):
            return

    raise APSecurityError(
        f"Access Denied: You do not possess '{ptype}' permission on {doctype} #{docname}."
    )


def _unpack_raw_file_url(file_url: str) -> str:
    """Unpacks nested view_receipt_file?file_url=... query URLs cleanly."""
    clean = unquote((file_url or "").strip())
    if "file_url=" in clean:
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(clean).query)
        if parsed.get("file_url"):
            clean = unquote(parsed["file_url"][0].strip())
    return clean.split("?")[0]


def _resolve_physical_file_path(raw_url: str) -> Optional[str]:
    """Resolves public or private Frappe File path safely within the current site directory."""
    if not raw_url:
        return None

    clean_url = _unpack_raw_file_url(raw_url)
    site_path = os.path.normpath(frappe.get_site_path())
    file_name = os.path.basename(clean_url)
    rel_clean = clean_url.lstrip("/")

    candidates = []
    if clean_url.startswith("/private/files/"):
        candidates.append(os.path.join(site_path, rel_clean))
    elif clean_url.startswith("/files/"):
        candidates.append(os.path.join(site_path, "public", rel_clean))
    else:
        candidates.append(os.path.join(site_path, rel_clean))

    candidates.extend([
        os.path.join(site_path, "public", "files", file_name),
        os.path.join(site_path, "private", "files", file_name),
    ])

    for cand in candidates:
        norm = os.path.normpath(cand)
        if norm.startswith(site_path) and os.path.exists(norm) and os.path.isfile(norm):
            return norm

    # Fallback lookup via tabFile for moved or subfolder-stored files
    file_doc = (
        frappe.db.get_value("File", {"file_url": clean_url}, ["file_url", "is_private"], as_dict=True)
        or frappe.db.get_value("File", {"file_url": ["like", f"%{file_name}"]}, ["file_url", "is_private"], as_dict=True)
    )
    if file_doc and file_doc.get("file_url"):
        stored_url = file_doc["file_url"].lstrip("/")
        sub_path = (
            os.path.join(site_path, stored_url)
            if stored_url.startswith("private/")
            else os.path.join(site_path, "public", stored_url)
        )
        folder = "private/files" if file_doc.get("is_private") else "public/files"
        base_path = os.path.join(site_path, folder, os.path.basename(stored_url))
        for p in (sub_path, base_path):
            norm = os.path.normpath(p)
            if norm.startswith(site_path) and os.path.exists(norm) and os.path.isfile(norm):
                return norm

    return None


def _build_attachment_entry(
    *,
    doctype: str,
    docname: str,
    doc: Any,
    source: str,
    proof_type: str,
    proof_label: str,
    row_idx: Optional[int],
    merchant: str,
    vendor: str,
    category: str,
    expense_head: str,
    custom_ledger_name: str,
    description: str,
    amount: float,
    date_val: str,
    bill_no: str,
    file_url: str,
) -> Dict[str, Any]:
    """Builds a normalized attachment dictionary matching APReceiptGallery expectations."""
    clean_url = file_url.strip()
    file_name = clean_url.split("/")[-1].split("?")[0]
    ext = os.path.splitext(file_name)[1].lower()
    view_url = (
        f"/api/method/ap_automation.services.attachment_service.view_receipt_file"
        f"?file_url={quote(clean_url)}&doctype={quote(doctype)}&docname={quote(docname)}"
    )
    return {
        "source": source,
        "claim_name": docname,
        "proof_type": proof_type,
        "proof_label": proof_label,
        "row_idx": row_idx,
        "merchant": merchant or "Expense Item",
        "vendor": vendor or "",
        "vendor_name": vendor or "",
        "expense_head": expense_head or "",
        "custom_ledger_name": custom_ledger_name or "",
        "category": category or "Expense Line",
        "description": description or "",
        "amount": float(amount or 0.0),
        "date": str(date_val or ""),
        "bill_no": str(bill_no or ""),
        "jv_number": getattr(doc, "jv_number", None) or "",
        "jv_date": str(getattr(doc, "jv_date", "") or ""),
        "file_url": clean_url,
        "view_url": view_url,
        "file_name": file_name,
        "is_image": ext in IMAGE_EXTENSIONS,
        "is_pdf": ext == ".pdf",
        "extension": ext,
    }


def get_all_claim_attachments(doctype: str, docname: str) -> List[Dict[str, Any]]:
    """
    Scans child rows, legs, and parent fields of any AP Document
    to produce a consolidated, verified list of all digital receipts.
    Provides streaming view_url that bypasses 403 Forbidden errors on private files.
    """
    _check_document_permission(doctype, docname, ptype="read")

    doc = frappe.get_doc(doctype, docname)
    attachments: List[Dict[str, Any]] = []

    # 1. Scan Main Expense Lines (Petty Cash & Employee Reimbursements)
    if hasattr(doc, "expense_lines") and doc.expense_lines:
        for row in doc.expense_lines:
            r_idx = getattr(row, "idx", len(attachments) + 1)
            m_title = (
                getattr(row, "merchant_name", None)
                or getattr(row, "merchant", None)
                or getattr(row, "supplier_name", None)
                or getattr(row, "supplier", None)
                or "Expense Item"
            )
            r_vendor = getattr(row, "vendor_name", None) or getattr(row, "vendor", None) or m_title
            r_head = getattr(row, "expense_head", None) or getattr(row, "head_of_expense", None) or ""
            r_custom_head = getattr(row, "custom_ledger_name", None) or ""
            r_cat = (
                getattr(row, "expense_type", None)
                or getattr(row, "expense_category", None)
                or getattr(row, "vendor_category", None)
                or getattr(row, "category", None)
                or "Expense Line"
            )
            r_desc = (
                getattr(row, "description", None)
                or getattr(row, "remarks", None)
                or getattr(row, "particulars", None)
                or ""
            )
            r_amt = float(getattr(row, "amount", 0.0) or 0.0)
            r_date = str(getattr(row, "expense_date", "") or doc.get("posting_date", ""))
            r_bill = (
                getattr(row, "invoice_number", None)
                or getattr(row, "bill_number", None)
                or getattr(row, "bill_no", None)
                or getattr(row, "bill_ref", "")
            )

            proof_slots = [
                (
                    getattr(row, "receipt_attachment", None)
                    or getattr(row, "attach_receipt", None)
                    or getattr(row, "attachment", None),
                    "bill",
                    "🧾 1. Tax Invoice / Bill",
                    m_title,
                    r_cat,
                ),
                (
                    getattr(row, "payment_proof_attachment", None),
                    "payment",
                    "💳 2. Payment Proof (GPay/UPI)",
                    f"Payment Proof (GPay/UPI) — {m_title}",
                    "Payment Confirmation (GPay/UPI)",
                ),
                (
                    getattr(row, "additional_proof_attachment", None),
                    "extra",
                    "📎 3. Additional Proof",
                    f"Supporting Proof — {m_title}",
                    "Additional Supporting Proof",
                ),
            ]
            for f_url, p_type, p_label, p_merch, p_cat in proof_slots:
                if f_url and isinstance(f_url, str) and f_url.strip():
                    attachments.append(_build_attachment_entry(
                        doctype=doctype, docname=docname, doc=doc, source="row",
                        proof_type=p_type, proof_label=p_label, row_idx=r_idx,
                        merchant=p_merch, vendor=r_vendor, category=p_cat,
                        expense_head=r_head, custom_ledger_name=r_custom_head,
                        description=r_desc, amount=r_amt, date_val=r_date,
                        bill_no=r_bill, file_url=f_url,
                    ))

    # 2. Scan Multi-Leg Client Travel Table (legs or client_visit_legs)
    legs_rows = getattr(doc, "client_visit_legs", None) or getattr(doc, "legs", None) or []
    for leg in legs_rows:
        l_idx = getattr(leg, "idx", len(attachments) + 1)
        client_label = getattr(leg, "client_name", None) or "Client Visit"
        travel_mode = getattr(leg, "mode_of_travel", None) or "Travel"
        travel_desc = f"{client_label} ({travel_mode})"
        route_cat = f"Travel: {getattr(leg, 'from_location', '')} → {getattr(leg, 'to_location', '')}"
        l_amt = float(getattr(leg, "leg_amount", 0.0) or 0.0) + float(getattr(leg, "toll_parking_amount", 0.0) or 0.0)
        l_date = str(getattr(leg, "visit_date", "") or getattr(leg, "travel_date", "") or doc.get("posting_date", ""))
        l_desc = getattr(leg, "purpose", None) or getattr(leg, "purpose_of_visit", None) or getattr(leg, "description", None) or ""
        l_head = getattr(leg, "expense_head", None) or "TRAVEL EXPENSES"

        leg_slots = [
            (
                getattr(leg, "receipt_attachment", None)
                or getattr(leg, "toll_parking_receipt", None)
                or getattr(leg, "odometer_proof", None),
                "bill",
                "🧾 1. Travel Ticket / Bill",
                travel_desc,
                route_cat,
            ),
            (
                getattr(leg, "payment_proof_attachment", None),
                "payment",
                "💳 2. Payment Proof (GPay/UPI)",
                f"Payment Proof (GPay/UPI) — {travel_desc}",
                "Payment Confirmation (GPay/UPI)",
            ),
            (
                getattr(leg, "additional_proof_attachment", None),
                "extra",
                "📎 3. Additional Travel Proof",
                f"Additional Travel Proof — {travel_desc}",
                "Additional Supporting Proof",
            ),
        ]
        for f_url, p_type, p_label, p_merch, p_cat in leg_slots:
            if f_url and isinstance(f_url, str) and f_url.strip():
                attachments.append(_build_attachment_entry(
                    doctype=doctype, docname=docname, doc=doc, source="row",
                    proof_type=p_type, proof_label=p_label, row_idx=l_idx,
                    merchant=p_merch, vendor=client_label, category=p_cat,
                    expense_head=l_head, custom_ledger_name="",
                    description=l_desc, amount=l_amt, date_val=l_date,
                    bill_no=str(l_idx), file_url=f_url,
                ))

    # 3. Scan Generic other child tables
    other_child_tables = ["lines", "items", "instructions", "vendor_lines", "expense_items", "imprest_items"]
    for table_field in other_child_tables:
        rows = getattr(doc, table_field, []) or []
        for row in rows:
            r_idx = getattr(row, "idx", len(attachments) + 1)
            raw_v = (
                getattr(row, "vendor_name", None)
                or getattr(row, "beneficiary_name", None)
                or getattr(row, "vendor", None)
                or getattr(row, "merchant_name", None)
                or getattr(row, "merchant", None)
                or getattr(row, "particulars", "")
            )
            r_head = getattr(row, "expense_head", None) or ""
            r_cat = getattr(row, "category", "") or getattr(row, "vendor_category", "") or getattr(row, "expense_type", "Expense Line")
            r_desc = getattr(row, "description", None) or getattr(row, "remarks", None) or getattr(row, "particulars", "")
            r_amt = float(getattr(row, "amount", 0.0) or getattr(row, "total_invoice_amount", 0.0) or getattr(row, "base_amount", 0.0) or 0.0)
            r_date = str(getattr(row, "invoice_date", "") or getattr(row, "expense_date", "") or getattr(row, "bill_date", "") or doc.get("posting_date", ""))
            r_bill = getattr(row, "invoice_number", "") or getattr(row, "bill_number", "")

            generic_slots = [
                (
                    getattr(row, "receipt_attachment", None)
                    or getattr(row, "attach_receipt", None)
                    or getattr(row, "attachment", None)
                    or getattr(row, "quote_attachment", None)
                    or getattr(row, "tax_invoice_attachment", None),
                    "bill",
                    "🧾 1. Tax Invoice / Bill",
                    raw_v or getattr(row, "particulars", "Expense Item"),
                    r_cat,
                ),
                (
                    getattr(row, "payment_proof_attachment", None),
                    "payment",
                    "💳 2. Payment Proof (GPay/UPI)",
                    f"Payment Proof — {raw_v or 'Vendor'}",
                    "Payment Confirmation (GPay/UPI)",
                ),
                (
                    getattr(row, "additional_proof_attachment", None),
                    "extra",
                    "📎 3. Additional Proof",
                    f"Supporting Proof — {raw_v or 'Vendor'}",
                    "Additional Supporting Proof",
                ),
                (
                    getattr(row, "bank_proof_attachment", None),
                    "extra",
                    "🏦 Bank Cheque Proof",
                    f"Bank Cheque Proof — {raw_v or 'Vendor'}",
                    "Bank Account Proof (Cancelled Cheque)",
                ),
            ]
            for f_url, p_type, p_label, p_merch, p_cat in generic_slots:
                if f_url and isinstance(f_url, str) and f_url.strip():
                    attachments.append(_build_attachment_entry(
                        doctype=doctype, docname=docname, doc=doc, source="row",
                        proof_type=p_type, proof_label=p_label, row_idx=r_idx,
                        merchant=p_merch, vendor=raw_v, category=p_cat,
                        expense_head=r_head, custom_ledger_name="",
                        description=r_desc, amount=r_amt, date_val=r_date,
                        bill_no=r_bill, file_url=f_url,
                    ))

    # 4. Scan Parent-Level Direct Attachment Fields
    parent_vendor = getattr(doc, "vendor_name", None) or getattr(doc, "supplier_name", None) or getattr(doc, "vendor", None) or getattr(doc, "supplier", "")
    parent_fields = [
        ("activity_photo", "📸 Team Activity Photo Proof", "Team Engagement & Recreation", "bill"),
        ("pre_approval_attachment", "📋 Pre-Approval Authorization Screenshot", "Audit Proof Document", "extra"),
        ("tax_invoice_attachment", f"Vendor Tax Invoice — {parent_vendor}" if parent_vendor else "Vendor Tax Invoice", "Audit Proof Document", "bill"),
        ("email_approval_attachment", "Manager Email Approval", "Audit Proof Document", "payment"),
        ("bank_proof_attachment", f"Bank Cheque Proof — {parent_vendor}" if parent_vendor else "Bank Account Proof (Cancelled Cheque / Passbook)", "Bank Details Verification", "extra"),
        ("grn_attachment", "Goods Receipt Note / Delivery Proof", "Audit Proof Document", "extra"),
        ("advance_receipt_attachment", "Advance Payment Proof", "Audit Proof Document", "payment"),
        ("settlement_statement", "Event Settlement Statement", "Audit Proof Document", "extra"),
    ]

    p_amt = float(getattr(doc, "total_claim_amount", 0.0) or getattr(doc, "total_amount", 0.0) or getattr(doc, "total_invoice_amount", 0.0) or getattr(doc, "grand_total", 0.0) or 0.0)
    p_date = str(doc.get("posting_date", "") or doc.get("activity_date", "") or doc.get("invoice_date", ""))

    for fieldname, label, cat_label, p_type in parent_fields:
        file_url = getattr(doc, fieldname, None)
        if file_url and isinstance(file_url, str) and file_url.strip():
            attachments.append(_build_attachment_entry(
                doctype=doctype, docname=docname, doc=doc, source="parent",
                proof_type=p_type, proof_label=label, row_idx=None,
                merchant=label, vendor=parent_vendor, category=cat_label,
                expense_head="", custom_ledger_name="",
                description="", amount=p_amt, date_val=p_date,
                bill_no=str(doc.get("name", "")), file_url=file_url,
            ))

    return attachments


def _generate_missing_file_svg(file_name: str) -> bytes:
    clean_fn = "".join(c for c in file_name if c.isalnum() or c in (" ", ".", "_", "-"))
    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="420" viewBox="0 0 600 420" style="background:#0f172a; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;">
        <rect width="596" height="416" x="2" y="2" rx="14" fill="#1e293b" stroke="#334155" stroke-width="2"/>
        <g transform="translate(300, 130)">
            <circle cx="0" cy="0" r="44" fill="#334155" stroke="#475569" stroke-width="2"/>
            <text x="0" y="14" font-size="38" text-anchor="middle">📄</text>
        </g>
        <text x="300" y="215" font-size="18" font-weight="700" fill="#f87171" text-anchor="middle">Receipt File Missing on Disk</text>
        <rect x="80" y="235" width="440" height="34" rx="6" fill="#0f172a" stroke="#334155"/>
        <text x="300" y="258" font-size="13" font-family="monospace" font-weight="600" fill="#38bdf8" text-anchor="middle">{clean_fn}</text>
        <text x="300" y="300" font-size="12" fill="#94a3b8" text-anchor="middle">The physical file is missing from /files/ or /private/files/.</text>
    </svg>"""
    return svg_content.encode("utf-8")


@frappe.whitelist()
def view_receipt_file(file_url: str, doctype: Optional[str] = None, docname: Optional[str] = None):
    """
    Direct, permission-safe file streaming endpoint for AP Proof Gallery and Reviewers.
    Streams receipt images and PDFs cleanly (public and private) using raw inline bytes.
    """
    if not file_url:
        frappe.throw(_("File URL is required."))

    if doctype and docname and frappe.db.exists(doctype, docname):
        _check_document_permission(doctype, docname, ptype="read")

    target_path = _resolve_physical_file_path(file_url)
    clean_url = _unpack_raw_file_url(file_url)
    file_name = os.path.basename(clean_url) or "receipt"

    if not target_path:
        svg_bytes = _generate_missing_file_svg(file_name)
        frappe.response["filename"] = f"{os.path.splitext(file_name)[0]}_missing.svg"
        frappe.response["filecontent"] = svg_bytes
        frappe.response["type"] = "download"
        frappe.response["display_content_as"] = "inline"
        frappe.response["content_type"] = "image/svg+xml"
        return

    with open(target_path, "rb") as f:
        file_bytes = f.read()

    ext = os.path.splitext(target_path)[1].lower()
    is_pdf_bytes = file_bytes[:5] == b"%PDF-" or ext == ".pdf"

    if is_pdf_bytes:
        content_type = "application/pdf"
        if not file_name.lower().endswith(".pdf"):
            file_name = f"{file_name}.pdf"
    else:
        content_type, _enc = mimetypes.guess_type(target_path)
        if not content_type:
            content_type = f"image/{ext.lstrip('.')}" if ext in IMAGE_EXTENSIONS else "application/octet-stream"

    frappe.response["filename"] = file_name
    frappe.response["filecontent"] = file_bytes
    frappe.response["type"] = "download"
    frappe.response["display_content_as"] = "inline"
    frappe.response["content_type"] = content_type


@frappe.whitelist()
def download_all_claim_attachments_zip(doctype: str, docname: str) -> None:
    """
    Packages all attachments for a claim into an in-memory ZIP archive
    with human-readable, sanitized filenames and streams directly to client.
    """
    _check_document_permission(doctype, docname, ptype="read")

    attachments = get_all_claim_attachments(doctype, docname)
    if not attachments:
        frappe.throw(_("No receipt files or attachments found to download for this document."))

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for idx, att in enumerate(attachments, start=1):
            norm_path = _resolve_physical_file_path(att["file_url"])
            if norm_path:
                ext = att["extension"] or ".png"
                clean_merchant = "".join(c for c in (att["merchant"] or "Expense") if c.isalnum() or c in (" ", "-", "_")).strip()
                clean_cat = "".join(c for c in (att["category"] or "Receipt") if c.isalnum() or c in (" ", "-", "_")).strip()

                if att["row_idx"]:
                    archive_name = f"Row-{att['row_idx']}_{clean_cat}_{clean_merchant}_{int(att['amount'])}INR{ext}"
                else:
                    archive_name = f"{clean_cat}_{clean_merchant}_{idx}{ext}"

                zip_file.write(norm_path, arcname=archive_name)

    zip_buffer.seek(0)
    zip_bytes = zip_buffer.getvalue()

    if not zip_bytes:
        frappe.throw(_("Could not read physical receipt files from disk."))

    clean_docname = docname.replace("/", "-")
    download_filename = f"{doctype}_{clean_docname}_All_Receipts.zip"

    frappe.response["filename"] = download_filename
    frappe.response["filecontent"] = zip_bytes
    frappe.response["type"] = "download"


@frappe.whitelist()
def download_voucher_receipts_zip(voucher_type: Optional[str] = None, voucher_name: Optional[str] = None, doctype: Optional[str] = None, docname: Optional[str] = None) -> None:
    """
    Direct endpoint called from Desk Form: Downloads ZIP containing all receipts for a claim/voucher.
    Accepts both (voucher_type, voucher_name) and (doctype, docname).
    """
    dt = voucher_type or doctype
    dn = voucher_name or docname
    if not dt or not dn:
        frappe.throw(_("Document Type and Document Name are required."))
    return download_all_claim_attachments_zip(dt, dn)


def _enrich_attachments_with_batch_meta(
    attachments: List[Dict[str, Any]],
    batch_name: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
    """Enriches attachments with Weekly Accounts Audit Batch row fields (Expense Head & JV #/Date)."""
    batch_items_meta: Dict[str, Dict[str, Any]] = {}
    if not batch_name or not frappe.db.exists("Weekly Accounts Audit Batch", batch_name):
        return batch_items_meta

    rows = frappe.get_all(
        "Weekly Accounts Audit Item",
        filters={"parent": batch_name},
        fields=["voucher_no", "expense_head", "jv_number", "jv_date", "status", "employee_name"],
    )
    for r in rows:
        if r.get("voucher_no"):
            batch_items_meta[r["voucher_no"]] = {
                "voucher_no": r["voucher_no"],
                "expense_head": r.get("expense_head") or "",
                "jv_number": r.get("jv_number") or "",
                "jv_date": str(r.get("jv_date") or ""),
                "status": r.get("status") or "",
                "employee_name": r.get("employee_name") or "",
            }

    for att in attachments:
        v_no = att.get("claim_name") or ""
        meta = batch_items_meta.get(v_no)
        if meta:
            att["batch_name"] = batch_name
            att["expense_head"] = meta["expense_head"]
            att["jv_number"] = meta["jv_number"]
            att["jv_date"] = meta["jv_date"]
            att["audit_status"] = meta["status"]
        else:
            att["batch_name"] = batch_name

    return batch_items_meta


@frappe.whitelist()
def get_claim_receipt_summary(
    claim_name: str,
    doctype: str = "Employee Reimbursement Claim",
    batch_name: Optional[str] = None
):
    """Returns structured list of attachments and receipts for a claim to populate audit modals."""
    attachments = get_all_claim_attachments(doctype=doctype, docname=claim_name)
    batch_meta = _enrich_attachments_with_batch_meta(attachments, batch_name)
    return {
        "claim_name": claim_name,
        "batch_name": batch_name,
        "batch_items_meta": batch_meta,
        "total_receipts": len(attachments),
        "attachments": attachments
    }


def _parse_claim_names_list(claim_names):
    chars = " '\"[]"
    if isinstance(claim_names, str):
        try:
            parsed = json.loads(claim_names)
            if isinstance(parsed, str):
                try:
                    parsed = json.loads(parsed)
                except Exception:
                    pass
            claim_names = parsed
        except Exception:
            if "," in claim_names:
                claim_names = [s.strip(chars) for s in claim_names.split(",") if s.strip(chars)]
            else:
                claim_names = [claim_names.strip(chars)]

    if not isinstance(claim_names, (list, tuple)):
        claim_names = [claim_names]

    cleaned = []
    for c in claim_names:
        if isinstance(c, (list, tuple)):
            cleaned.extend(_parse_claim_names_list(c))
        elif isinstance(c, str):
            c_str = c.strip()
            if c_str.startswith("[") and c_str.endswith("]"):
                try:
                    sub_list = json.loads(c_str)
                    cleaned.extend(_parse_claim_names_list(sub_list))
                    continue
                except Exception:
                    pass
            if "," in c_str and not frappe.db.exists("Employee Reimbursement Claim", c_str):
                for part in c_str.split(","):
                    p = part.strip(chars)
                    if p:
                        cleaned.append(p)
            elif c_str:
                cleaned.append(c_str.strip(chars))
        elif c:
            cleaned.append(str(c))
    return cleaned


@frappe.whitelist()
def get_multiple_claims_receipt_summary(
    claim_names=None,
    doctype: str = "Employee Reimbursement Claim",
    batch_name: Optional[str] = None
):
    """
    Returns aggregated list of attachments across multiple claims/vouchers
    for employee-level audit view in Weekly Accounts Audit Batch.
    """
    clean_claims = _parse_claim_names_list(claim_names)
    if not clean_claims:
        return {"total_receipts": 0, "attachments": [], "batch_items_meta": {}}

    all_attachments = []
    for c_name in clean_claims:
        if not c_name:
            continue
        try:
            atts = get_all_claim_attachments(doctype=doctype, docname=str(c_name))
            for a in atts:
                a["claim_name"] = str(c_name)
                all_attachments.append(a)
        except Exception as e:
            frappe.log_error(f"Error fetching attachments for claim {c_name}: {e}")

    batch_meta = _enrich_attachments_with_batch_meta(all_attachments, batch_name)

    return {
        "batch_name": batch_name,
        "batch_items_meta": batch_meta,
        "total_receipts": len(all_attachments),
        "attachments": all_attachments
    }


@frappe.whitelist()
def download_multiple_claims_receipts_zip(claim_names=None, label="Employee_Receipts", doctype="Employee Reimbursement Claim"):
    """
    Packages all attachments for multiple claims/vouchers into an in-memory ZIP archive
    organized by voucher number, and streams directly to the client.
    """
    clean_claims = _parse_claim_names_list(claim_names)
    if not clean_claims:
        frappe.throw(_("No vouchers specified for receipt download."))

    zip_buffer = io.BytesIO()
    site_path = frappe.get_site_path()
    total_files_added = 0

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for c_name in clean_claims:
            if not c_name:
                continue
            clean_v = str(c_name).replace("/", "-")
            try:
                attachments = get_all_claim_attachments(doctype, str(c_name))
            except Exception:
                attachments = []

            for idx, att in enumerate(attachments, start=1):
                raw_url = att.get("file_url")
                if not raw_url:
                    continue

                norm_path = _resolve_physical_file_path(raw_url)
                if norm_path:
                    ext = att.get("extension") or ".png"
                    clean_merchant = "".join(c for c in (att.get("merchant") or "Expense") if c.isalnum() or c in (" ", "-", "_")).strip()
                    clean_cat = "".join(c for c in (att.get("category") or "Receipt") if c.isalnum() or c in (" ", "-", "_")).strip()

                    archive_name = f"{clean_v}/{clean_cat}_{clean_merchant}_{idx}{ext}"
                    zip_file.write(norm_path, arcname=archive_name)
                    total_files_added += 1

        if total_files_added == 0:
            notice = "No physical receipt files or invoices were attached to vouchers: " + ", ".join(clean_claims) + "\n"
            zip_file.writestr("NO_RECEIPTS_ATTACHED.txt", notice)

    zip_buffer.seek(0)
    clean_label = "".join(c for c in str(label) if c.isalnum() or c in (" ", "-", "_")).strip() or "Employee_Receipts"
    download_filename = f"{clean_label}_Receipts.zip"

    frappe.response["filename"] = download_filename
    frappe.response["filecontent"] = zip_buffer.getvalue()
    frappe.response["type"] = "download"


@frappe.whitelist()
def get_active_expense_heads():
    """Returns sorted list of active expense heads from AP Expense Head Master."""
    heads = frappe.get_all(
        "AP Expense Head Master",
        filters={"is_active": 1},
        fields=["head_name", "category_group"],
        order_by="sort_order asc, head_name asc"
    )
    if not heads:
        return [
            "STAFF WELFARE", "FOOD EXPENSES", "OFFICE EXPENSES", "OFFICE EXPENSES - GROCERY",
            "OFFICE EXPENSES - POOJA", "PRINTING & STATIONARY", "COURIER CHARGES",
            "POWER & FUEL EXPENSES", "TRAVEL EXPENSES", "OTHER EXPENSES", "OTHER / VENDOR LEDGER"
        ]
    return [h["head_name"] for h in heads]


@frappe.whitelist()
def create_or_edit_expense_head(head_name, is_active=1, description=None):
    """Allows Admin/Accounts to add or edit an Expense Head on the fly."""
    if not head_name or not head_name.strip():
        frappe.throw(_("Expense Head name cannot be empty."))

    clean_name = head_name.strip().upper()
    if frappe.db.exists("AP Expense Head Master", clean_name):
        doc = frappe.get_doc("AP Expense Head Master", clean_name)
        doc.is_active = int(is_active)
        if description is not None:
            doc.description = description
        doc.save(ignore_permissions=True)
        return {"status": "updated", "head_name": clean_name}
    else:
        doc = frappe.get_doc({
            "doctype": "AP Expense Head Master",
            "head_name": clean_name,
            "is_active": int(is_active),
            "description": description or "",
            "sort_order": 50
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return {"status": "created", "head_name": clean_name}


@frappe.whitelist()
def update_claim_row_expense_head(doctype, docname, row_idx, expense_head, custom_ledger_name=None):
    """
    Directly updates the Expenses of Head on a voucher row from the View Receipt modal or form.
    Maintains full audit integrity and updates child line item in DB.
    """
    row_idx = int(row_idx)
    doc = frappe.get_doc(doctype, docname)

    table_field = None
    for candidate in ["expense_lines", "vendor_lines", "expense_items", "reimbursement_lines", "items", "client_visit_legs"]:
        if hasattr(doc, candidate) and getattr(doc, candidate, None):
            table_field = candidate
            break

    if not table_field or not getattr(doc, table_field, None):
        frappe.throw(_(f"No expense rows found on {doctype} #{docname}."))

    rows = getattr(doc, table_field)
    target_row = None
    for r in rows:
        if getattr(r, "idx", 0) == row_idx:
            target_row = r
            break

    if not target_row and 0 <= row_idx - 1 < len(rows):
        target_row = rows[row_idx - 1]

    if not target_row:
        frappe.throw(_(f"Row #{row_idx} not found on {doctype} #{docname}."))

    old_head = getattr(target_row, "expense_head", "")
    clean_head = (expense_head or "").strip()
    target_row.expense_head = clean_head

    child_table = target_row.doctype
    meta = frappe.get_meta(child_table)
    update_vals = {}
    if meta.has_field("expense_head"):
        update_vals["expense_head"] = clean_head
    if custom_ledger_name and meta.has_field("custom_ledger_name"):
        target_row.custom_ledger_name = custom_ledger_name.strip()
        update_vals["custom_ledger_name"] = custom_ledger_name.strip()

    if update_vals:
        frappe.db.set_value(child_table, target_row.name, update_vals)

    # Sync to batch item if this claim is linked in a Weekly Accounts Audit Batch
    if doctype == "Employee Reimbursement Claim":
        batch_items = frappe.db.sql("""
            SELECT name FROM `tabWeekly Accounts Audit Item`
            WHERE voucher_no = %s
        """, (docname,), as_dict=True)
        for bi in batch_items:
            frappe.db.set_value("Weekly Accounts Audit Item", bi.name, "expense_head", clean_head, update_modified=False)

    user_name = frappe.session.user
    doc.add_comment(
        "Edit",
        f"Row #{row_idx} Expense Head updated from '{old_head}' to '{clean_head}' by {user_name} via Proof Gallery."
    )
    frappe.db.commit()

    return {
        "status": "success",
        "row_idx": row_idx,
        "new_head": clean_head,
        "message": f"Row #{row_idx} Expense Head updated to '{clean_head}'."
    }


@frappe.whitelist()
def get_active_expense_types(module_scope="All"):
    """Returns sorted list of active expense types, optionally filtered by module scope."""
    if module_scope and module_scope != "All":
        types = frappe.db.sql("""
            SELECT type_name, module_scope, sort_order, description
            FROM `tabAP Expense Type Master`
            WHERE is_active = 1 AND (module_scope = 'All' OR module_scope = %s OR module_scope IS NULL OR module_scope = '')
            ORDER BY sort_order ASC, type_name ASC
        """, (module_scope,), as_dict=True)
    else:
        types = frappe.get_all(
            "AP Expense Type Master",
            filters={"is_active": 1},
            fields=["type_name", "module_scope", "sort_order", "description"],
            order_by="sort_order asc, type_name asc"
        )

    if not types:
        return [
            "Tea & Refreshments", "Courier & Logistics", "Office Supplies & Stationery",
            "Repairs & Maintenance", "Local Conveyance", "Cleaning & Housekeeping", "Miscellaneous"
        ]
    return [t["type_name"] for t in types]


@frappe.whitelist()
def get_expense_type_records(module_scope="All"):
    """Returns all expense type records with their active status for management dialog."""
    if module_scope and module_scope != "All":
        records = frappe.db.sql("""
            SELECT name, type_name, module_scope, is_active, sort_order, description
            FROM `tabAP Expense Type Master`
            WHERE module_scope = 'All' OR module_scope = %s OR module_scope IS NULL OR module_scope = ''
            ORDER BY is_active DESC, sort_order ASC, type_name ASC
        """, (module_scope,), as_dict=True)
    else:
        records = frappe.get_all(
            "AP Expense Type Master",
            fields=["name", "type_name", "module_scope", "is_active", "sort_order", "description"],
            order_by="is_active desc, sort_order asc, type_name asc"
        )
    return records


@frappe.whitelist()
def create_or_edit_expense_type(type_name, module_scope="All", is_active=1, description=None, old_name=None):
    """Allows Admin/Accounts to add or edit an Expense Type on the fly."""
    if not type_name or not type_name.strip():
        frappe.throw(_("Expense Type name cannot be empty."))

    clean_name = type_name.strip()
    target_name = (old_name or clean_name).strip()

    if frappe.db.exists("AP Expense Type Master", target_name):
        doc = frappe.get_doc("AP Expense Type Master", target_name)
        if old_name and clean_name != old_name:
            doc.type_name = clean_name
        doc.module_scope = module_scope or "All"
        doc.is_active = int(is_active)
        if description is not None:
            doc.description = description
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return {"status": "updated", "type_name": doc.type_name}
    else:
        doc = frappe.get_doc({
            "doctype": "AP Expense Type Master",
            "type_name": clean_name,
            "module_scope": module_scope or "All",
            "is_active": int(is_active),
            "description": description or "",
            "sort_order": 50
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return {"status": "created", "type_name": clean_name}


@frappe.whitelist()
def delete_or_deactivate_expense_type(type_name, permanent=0):
    """Deactivates or deletes an Expense Type."""
    if not type_name:
        frappe.throw(_("Expense Type name is required."))

    clean_name = type_name.strip()
    if not frappe.db.exists("AP Expense Type Master", clean_name):
        frappe.throw(_(f"Expense Type '{clean_name}' does not exist."))

    if int(permanent) == 1:
        try:
            frappe.delete_doc("AP Expense Type Master", clean_name, ignore_permissions=True)
            frappe.db.commit()
            return {"status": "deleted", "type_name": clean_name}
        except Exception:
            frappe.db.set_value("AP Expense Type Master", clean_name, "is_active", 0)
            frappe.db.commit()
            return {"status": "deactivated", "type_name": clean_name, "fallback": True}
    else:
        frappe.db.set_value("AP Expense Type Master", clean_name, "is_active", 0)
        frappe.db.commit()
        return {"status": "deactivated", "type_name": clean_name}


@frappe.whitelist()
def update_claim_row_expense_type(doctype, docname, row_idx, expense_type):
    """
    Directly updates the Expense Type / Category / Head on a voucher row from the View Receipt modal or form.
    Maintains full audit integrity and updates child line item in DB.
    Supports Petty Cash, Admin Weekly Vendor Claims, Event Expense Claims, and Reimbursements.
    """
    row_idx = int(row_idx)
    doc = frappe.get_doc(doctype, docname)

    table_field = None
    for candidate in ["expense_lines", "vendor_lines", "expense_items", "reimbursement_lines", "items"]:
        if hasattr(doc, candidate) and getattr(doc, candidate, None):
            table_field = candidate
            break

    if not table_field or not getattr(doc, table_field, None):
        frappe.throw(_(f"No expense rows found on {doctype} #{docname}."))

    rows = getattr(doc, table_field)
    target_row = None
    for r in rows:
        if getattr(r, "idx", 0) == row_idx:
            target_row = r
            break

    if not target_row and 0 <= row_idx - 1 < len(rows):
        target_row = rows[row_idx - 1]

    if not target_row:
        frappe.throw(_(f"Row #{row_idx} not found on {doctype} #{docname}."))

    child_table = target_row.doctype
    meta = frappe.get_meta(child_table)
    clean_type = (expense_type or "").strip()

    EXPENSE_HEADS = [
        "STAFF WELFARE", "FOOD EXPENSES", "OFFICE EXPENSES", "OFFICE EXPENSES - GROCERY",
        "OFFICE EXPENSES - POOJA", "PRINTING & STATIONARY", "COURIER CHARGES",
        "POWER & FUEL EXPENSES", "TRAVEL EXPENSES", "OTHER EXPENSES", "OTHER / VENDOR LEDGER"
    ]
    is_head_match = clean_type.upper() in [h.upper() for h in EXPENSE_HEADS]

    # Dynamically find the appropriate column on the child table
    type_field = None
    if is_head_match and meta.has_field("expense_head"):
        type_field = "expense_head"
        clean_type = next(h for h in EXPENSE_HEADS if h.upper() == clean_type.upper())
    elif meta.has_field("expense_type"):
        type_field = "expense_type"
        # If Link to AP Expense Subtype Master, ensure target doc exists
        field_def = meta.get_field("expense_type")
        if field_def and field_def.fieldtype == "Link" and field_def.options == "AP Expense Subtype Master":
            if not frappe.db.exists("AP Expense Subtype Master", clean_type):
                cat = getattr(doc, "claim_category", "General Expense") or "General Expense"
                try:
                    frappe.get_doc({
                        "doctype": "AP Expense Subtype Master",
                        "subtype_name": clean_type,
                        "parent_claim_category": cat,
                        "is_active": 1
                    }).insert(ignore_permissions=True)
                except Exception:
                    pass
    elif meta.has_field("expense_category"):
        type_field = "expense_category"
    elif meta.has_field("vendor_category"):
        type_field = "vendor_category"
    elif meta.has_field("service_type"):
        type_field = "service_type"
    elif meta.has_field("expense_head"):
        type_field = "expense_head"
    else:
        for f in meta.fields:
            if f.fieldname in ("category", "claim_category", "type", "expense_type", "expense_category", "expense_head"):
                type_field = f.fieldname
                break

    if not type_field:
        frappe.throw(_(f"Could not find a valid category/type field on row of doctype '{child_table}'."))

    old_type = getattr(target_row, type_field, "")
    setattr(target_row, type_field, clean_type)

    frappe.db.set_value(child_table, target_row.name, type_field, clean_type)

    # Sync to batch item if this claim is linked in a Weekly Accounts Audit Batch
    if doctype == "Employee Reimbursement Claim" and type_field in ("expense_head", "expense_type"):
        batch_items = frappe.db.sql("""
            SELECT name FROM `tabWeekly Accounts Audit Item`
            WHERE voucher_no = %s
        """, (docname,), as_dict=True)
        for bi in batch_items:
            if type_field == "expense_head":
                frappe.db.set_value("Weekly Accounts Audit Item", bi.name, "expense_head", clean_type, update_modified=False)

    user_name = frappe.session.user
    label_text = meta.get_label(type_field) or type_field
    doc.add_comment(
        "Edit",
        f"Row #{row_idx} {label_text} updated from '{old_type}' to '{clean_type}' by {user_name} via Proof Gallery."
    )
    frappe.db.commit()

    return {
        "status": "success",
        "row_idx": row_idx,
        "field": type_field,
        "new_type": clean_type,
        "message": f"Row #{row_idx} {label_text} updated to '{clean_type}'."
    }


def seed_expense_types():
    """Seeds default standard expense types for all modules into AP Expense Type Master."""
    types = [
        # Petty Cash
        {"type_name": "Tea & Refreshments", "module_scope": "Petty Cash", "sort_order": 10},
        {"type_name": "Courier & Logistics", "module_scope": "Petty Cash", "sort_order": 20},
        {"type_name": "Office Supplies & Stationery", "module_scope": "Petty Cash", "sort_order": 30},
        {"type_name": "Repairs & Maintenance", "module_scope": "Petty Cash", "sort_order": 40},
        {"type_name": "Local Conveyance", "module_scope": "Petty Cash", "sort_order": 50},
        {"type_name": "Cleaning & Housekeeping", "module_scope": "Petty Cash", "sort_order": 60},
        {"type_name": "Miscellaneous", "module_scope": "Petty Cash", "sort_order": 70},

        # Admin Weekly Vendor Claims
        {"type_name": "Housekeeping", "module_scope": "Admin Weekly Vendor Claims", "sort_order": 110},
        {"type_name": "Pantry", "module_scope": "Admin Weekly Vendor Claims", "sort_order": 120},
        {"type_name": "Courier", "module_scope": "Admin Weekly Vendor Claims", "sort_order": 130},
        {"type_name": "Stationery", "module_scope": "Admin Weekly Vendor Claims", "sort_order": 140},
        {"type_name": "Printing", "module_scope": "Admin Weekly Vendor Claims", "sort_order": 150},
        {"type_name": "IT Hardware", "module_scope": "Admin Weekly Vendor Claims", "sort_order": 160},
        {"type_name": "Security & Facility", "module_scope": "Admin Weekly Vendor Claims", "sort_order": 170},
        {"type_name": "Office Supplies", "module_scope": "Admin Weekly Vendor Claims", "sort_order": 180},

        # Events
        {"type_name": "Venue & Stage", "module_scope": "Events", "sort_order": 210},
        {"type_name": "Travel & Flights", "module_scope": "Events", "sort_order": 220},
        {"type_name": "Food & Catering", "module_scope": "Events", "sort_order": 230},
        {"type_name": "Marketing & Collateral", "module_scope": "Events", "sort_order": 240},
        {"type_name": "Stationery & Props", "module_scope": "Events", "sort_order": 250},
        {"type_name": "Incidentals", "module_scope": "Events", "sort_order": 260},

        # General / Reimbursements / Invoices
        {"type_name": "Food & Meals", "module_scope": "Employee Reimbursements", "sort_order": 310},
        {"type_name": "Travel & Conveyance", "module_scope": "Employee Reimbursements", "sort_order": 320},
        {"type_name": "Client Entertainment", "module_scope": "Employee Reimbursements", "sort_order": 330},
        {"type_name": "Accommodation & Hotel", "module_scope": "Employee Reimbursements", "sort_order": 340},
        {"type_name": "Professional Fees", "module_scope": "Vendor Invoices", "sort_order": 410},
        {"type_name": "IT & Cloud Services", "module_scope": "Vendor Invoices", "sort_order": 420},
    ]

    count = 0
    for t in types:
        name = t["type_name"]
        if not frappe.db.exists("AP Expense Type Master", name):
            doc = frappe.get_doc({
                "doctype": "AP Expense Type Master",
                "type_name": name,
                "module_scope": t["module_scope"],
                "sort_order": t["sort_order"],
                "is_active": 1,
                "description": f"Standard expense type for {t['module_scope']}"
            })
            doc.insert(ignore_permissions=True)
            count += 1

    frappe.db.commit()
    return f"Seeded {count} new expense types."
