# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Universal Expense Claim Receipt & Proof Aggregator Service
Collects, sanitizes, and packages all receipt attachments, tax invoices,
pre-approval screenshots, and audit trail documents across all spend lanes.
Provides permission-safe streaming of both Public and Private files directly
to the AP Proof & Receipt Gallery.
"""

import os
import io
import mimetypes
import zipfile
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote, unquote

import frappe
from frappe import _
from ap_automation.exceptions import APValidationError, APSecurityError


def _check_document_permission(doctype: str, docname: str, ptype: str = "read") -> None:
    """Verifies user has permission on the parent AP document."""
    if not frappe.has_permission(doctype, ptype=ptype, doc=docname):
        raise APSecurityError(
            f"Access Denied: You do not possess '{ptype}' permission on {doctype} #{docname}."
        )


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
            file_url = (
                getattr(row, "receipt_attachment", None)
                or getattr(row, "attach_receipt", None)
                or getattr(row, "attachment", None)
            )
            if file_url and isinstance(file_url, str) and file_url.strip():
                file_url = file_url.strip()
                file_name = file_url.split("/")[-1]
                ext = os.path.splitext(file_name)[1].lower()

                view_url = f"/api/method/ap_automation.services.attachment_service.view_receipt_file?file_url={quote(file_url)}&doctype={doctype}&docname={docname}"

                attachments.append({
                    "source": "row",
                    "row_idx": getattr(row, "idx", len(attachments) + 1),
                    "merchant": getattr(row, "merchant_name", "") or getattr(row, "merchant", "Expense Item"),
                    "category": getattr(row, "category", "") or getattr(row, "expense_type", "Expense Line"),
                    "amount": float(getattr(row, "amount", 0.0) or 0.0),
                    "date": str(getattr(row, "expense_date", "") or doc.get("posting_date", "")),
                    "bill_no": getattr(row, "invoice_number", ""),
                    "file_url": file_url,
                    "view_url": view_url,
                    "file_name": file_name,
                    "is_image": ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"],
                    "is_pdf": ext == ".pdf",
                    "extension": ext
                })

    # 2. Scan Multi-Leg Client Travel Table
    if hasattr(doc, "legs") and doc.legs:
        for leg in doc.legs:
            file_url = getattr(leg, "toll_parking_receipt", None) or getattr(leg, "odometer_proof", None)
            if file_url and isinstance(file_url, str) and file_url.strip():
                file_url = file_url.strip()
                file_name = file_url.split("/")[-1]
                ext = os.path.splitext(file_name)[1].lower()

                view_url = f"/api/method/ap_automation.services.attachment_service.view_receipt_file?file_url={quote(file_url)}&doctype={doctype}&docname={docname}"
                travel_desc = f"{getattr(leg, 'client_name', 'Client Visit')} ({getattr(leg, 'mode_of_travel', 'Travel')})"
                attachments.append({
                    "source": "row",
                    "row_idx": getattr(leg, "idx", len(attachments) + 1),
                    "merchant": travel_desc,
                    "category": f"Travel: {getattr(leg, 'from_location', '')} → {getattr(leg, 'to_location', '')}",
                    "amount": float(getattr(leg, "leg_amount", 0.0) or 0.0) + float(getattr(leg, "toll_parking_amount", 0.0) or 0.0),
                    "date": str(getattr(leg, "visit_date", "") or getattr(leg, "travel_date", "") or doc.get("posting_date", "")),
                    "bill_no": str(getattr(leg, "idx", "")),
                    "file_url": file_url,
                    "view_url": view_url,
                    "file_name": file_name,
                    "is_image": ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"],
                    "is_pdf": ext == ".pdf",
                    "extension": ext
                })

    # 3. Scan Generic other child tables (e.g. lines, items, instructions, vendor_lines, expense_items, imprest_items)
    other_child_tables = ["lines", "items", "instructions", "vendor_lines", "expense_items", "imprest_items"]
    for table_field in other_child_tables:
        rows = getattr(doc, table_field, []) or []
        for row in rows:
            file_url = (
                getattr(row, "receipt_attachment", None)
                or getattr(row, "attach_receipt", None)
                or getattr(row, "attachment", None)
                or getattr(row, "quote_attachment", None)
                or getattr(row, "tax_invoice_attachment", None)
            )
            raw_v = (
                getattr(row, "vendor_name", None)
                or getattr(row, "beneficiary_name", None)
                or getattr(row, "vendor", None)
                or getattr(row, "merchant_name", None)
                or getattr(row, "merchant", None)
                or getattr(row, "particulars", "")
            )
            if file_url and isinstance(file_url, str) and file_url.strip():
                file_url = file_url.strip()
                file_name = file_url.split("/")[-1]
                ext = os.path.splitext(file_name)[1].lower()

                view_url = f"/api/method/ap_automation.services.attachment_service.view_receipt_file?file_url={quote(file_url)}&doctype={doctype}&docname={docname}"

                attachments.append({
                    "source": "row",
                    "row_idx": getattr(row, "idx", len(attachments) + 1),
                    "merchant": raw_v or getattr(row, "particulars", "Expense Item"),
                    "vendor": raw_v,
                    "vendor_name": raw_v,
                    "category": getattr(row, "category", "") or getattr(row, "vendor_category", "") or getattr(row, "expense_type", "Expense Line"),
                    "amount": float(getattr(row, "amount", 0.0) or getattr(row, "total_invoice_amount", 0.0) or getattr(row, "base_amount", 0.0) or 0.0),
                    "date": str(getattr(row, "invoice_date", "") or getattr(row, "expense_date", "") or getattr(row, "bill_date", "") or doc.get("posting_date", "")),
                    "bill_no": getattr(row, "invoice_number", "") or getattr(row, "bill_number", ""),
                    "file_url": file_url,
                    "view_url": view_url,
                    "file_name": file_name,
                    "is_image": ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"],
                    "is_pdf": ext == ".pdf",
                    "extension": ext
                })

            # Check if row has Bank Proof attachment
            row_bp = getattr(row, "bank_proof_attachment", None)
            if row_bp and isinstance(row_bp, str) and row_bp.strip():
                bp_url = row_bp.strip()
                bp_name = bp_url.split("/")[-1]
                bp_ext = os.path.splitext(bp_name)[1].lower()
                attachments.append({
                    "source": "row",
                    "row_idx": getattr(row, "idx", len(attachments) + 1),
                    "merchant": f"Bank Cheque Proof — {raw_v or 'Vendor'}",
                    "vendor": raw_v,
                    "vendor_name": raw_v,
                    "category": "Bank Account Proof (Cancelled Cheque)",
                    "amount": float(getattr(row, "amount", 0.0) or getattr(row, "total_invoice_amount", 0.0) or 0.0),
                    "date": str(getattr(row, "invoice_date", "") or doc.get("posting_date", "")),
                    "bill_no": getattr(row, "invoice_number", ""),
                    "file_url": bp_url,
                    "view_url": f"/api/method/ap_automation.services.attachment_service.view_receipt_file?file_url={quote(bp_url)}&doctype={doctype}&docname={docname}",
                    "file_name": bp_name,
                    "is_image": bp_ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"],
                    "is_pdf": bp_ext == ".pdf",
                    "extension": bp_ext
                })

    # 4. Scan Parent-Level Direct Attachment Fields
    parent_vendor = getattr(doc, "vendor_name", None) or getattr(doc, "supplier_name", None) or getattr(doc, "vendor", None) or getattr(doc, "supplier", "")
    parent_fields = [
        ("activity_photo", "📸 Team Activity Photo Proof", "Team Engagement & Recreation"),
        ("pre_approval_attachment", "📋 Pre-Approval Authorization Screenshot", "Audit Proof Document"),
        ("tax_invoice_attachment", f"Vendor Tax Invoice — {parent_vendor}" if parent_vendor else "Vendor Tax Invoice", "Audit Proof Document"),
        ("email_approval_attachment", "Manager Email Approval", "Audit Proof Document"),
        ("bank_proof_attachment", f"Bank Cheque Proof — {parent_vendor}" if parent_vendor else "Bank Account Proof (Cancelled Cheque / Passbook)", "Bank Details Verification"),
        ("grn_attachment", "Goods Receipt Note / Delivery Proof", "Audit Proof Document"),
        ("advance_receipt_attachment", "Advance Payment Proof", "Audit Proof Document"),
        ("settlement_statement", "Event Settlement Statement", "Audit Proof Document")
    ]

    for fieldname, label, cat_label in parent_fields:
        file_url = getattr(doc, fieldname, None)
        if file_url and isinstance(file_url, str) and file_url.strip():
            file_url = file_url.strip()
            file_name = file_url.split("/")[-1]
            ext = os.path.splitext(file_name)[1].lower()

            view_url = f"/api/method/ap_automation.services.attachment_service.view_receipt_file?file_url={quote(file_url)}&doctype={doctype}&docname={docname}"

            attachments.append({
                "source": "parent",
                "row_idx": None,
                "merchant": label,
                "vendor": parent_vendor,
                "vendor_name": parent_vendor,
                "category": cat_label,
                "amount": float(getattr(doc, "total_claim_amount", 0.0) or getattr(doc, "total_amount", 0.0) or getattr(doc, "total_invoice_amount", 0.0) or getattr(doc, "grand_total", 0.0) or 0.0),
                "date": str(doc.get("posting_date", "") or doc.get("activity_date", "") or doc.get("invoice_date", "")),
                "bill_no": str(doc.get("name", "")),
                "file_url": file_url,
                "view_url": view_url,
                "file_name": file_name,
                "is_image": ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"],
                "is_pdf": ext == ".pdf",
                "extension": ext
            })

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
        <text x="300" y="300" font-size="12" fill="#94a3b8" text-anchor="middle">This receipt attachment URL was referenced on the voucher line,</text>
        <text x="300" y="320" font-size="12" fill="#94a3b8" text-anchor="middle">but the physical file is not present in server storage.</text>
        <text x="300" y="360" font-size="12" font-weight="600" fill="#fbbf24" text-anchor="middle">⚠️ Please ask the employee to re-upload the original bill or receipt.</text>
    </svg>"""
    return svg_content.encode("utf-8")


@frappe.whitelist()
def view_receipt_file(file_url: str, doctype: Optional[str] = None, docname: Optional[str] = None):
    """
    Direct, permission-safe file streaming endpoint for AP Proof Gallery and Reviewers.
    Streams receipt images and PDFs directly to the browser (even if stored in private/files/)
    without 403 Forbidden or 404 Werkzeug errors.
    """
    if not file_url:
        frappe.throw(_("File URL is required."))

    file_url = unquote(file_url.strip())
    # Unpack nested view_url if passed
    if "file_url=" in file_url:
        import urllib.parse
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(file_url).query)
        if "file_url" in parsed and parsed["file_url"]:
            file_url = parsed["file_url"][0]

    clean_url = file_url.split("?")[0]
    site_path = frappe.get_site_path()
    file_name = os.path.basename(clean_url)

    # Search paths in order of preference
    possible_paths = [
        # 1. Direct if relative to site
        os.path.join(site_path, clean_url.lstrip("/")),
        # 2. Public files
        os.path.join(site_path, "public", "files", file_name),
        # 3. Private files
        os.path.join(site_path, "private", "files", file_name),
    ]

    target_path = None
    for p in possible_paths:
        norm = os.path.normpath(p)
        if norm.startswith(os.path.normpath(site_path)) and os.path.exists(norm) and os.path.isfile(norm):
            target_path = norm
            break

    if not target_path:
        # Check tabFile for file_url
        file_doc = frappe.db.get_value("File", {"file_url": ["like", f"%{file_name}"]}, ["file_url", "is_private"], as_dict=True)
        if file_doc:
            folder = "private/files" if file_doc.get("is_private") else "public/files"
            p = os.path.join(site_path, folder, file_name)
            if os.path.exists(p) and os.path.isfile(p):
                target_path = p

    if not target_path:
        svg_bytes = _generate_missing_file_svg(file_name)
        frappe.response["filename"] = f"{os.path.splitext(file_name)[0]}_missing.svg"
        frappe.response["filecontent"] = svg_bytes
        frappe.response["type"] = "download"
        frappe.response["display_content_as"] = "inline"
        frappe.response["content_type"] = "image/svg+xml"
        return

    # Determine Content-Type
    ext = os.path.splitext(file_name)[1].lower()
    content_type, encoding = mimetypes.guess_type(target_path)
    if not content_type:
        if ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"]:
            content_type = f"image/{ext.lstrip('.')}"
        elif ext == ".pdf":
            content_type = "application/pdf"
        else:
            content_type = "application/octet-stream"

    with open(target_path, "rb") as f:
        file_bytes = f.read()

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
    site_path = frappe.get_site_path()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for idx, att in enumerate(attachments, start=1):
            raw_url = att["file_url"]

            # Resolve physical file path on disk
            if raw_url.startswith("/private/files/"):
                file_rel = raw_url.replace("/private/files/", "private/files/")
                physical_path = os.path.join(site_path, file_rel)
            elif raw_url.startswith("/files/"):
                file_rel = raw_url.replace("/files/", "public/files/")
                physical_path = os.path.join(site_path, file_rel)
            else:
                physical_path = os.path.join(site_path, "public", "files", os.path.basename(raw_url))

            # Check if exists in private/files as fallback
            if not os.path.exists(physical_path):
                alt_priv = os.path.join(site_path, "private", "files", os.path.basename(raw_url))
                if os.path.exists(alt_priv):
                    physical_path = alt_priv

            norm_path = os.path.normpath(physical_path)
            if not norm_path.startswith(os.path.normpath(site_path)):
                continue

            if os.path.exists(norm_path) and os.path.isfile(norm_path):
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


@frappe.whitelist()
def get_claim_receipt_summary(claim_name: str, doctype: str = "Employee Reimbursement Claim"):
    """Returns structured list of attachments and receipts for a claim to populate audit modals."""
    attachments = get_all_claim_attachments(doctype=doctype, docname=claim_name)
    return {
        "claim_name": claim_name,
        "total_receipts": len(attachments),
        "attachments": attachments
    }

def _parse_claim_names_list(claim_names):
    chars = " \'\"\[\]"
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
def get_multiple_claims_receipt_summary(claim_names=None, doctype="Employee Reimbursement Claim"):
    """
    Returns aggregated list of attachments across multiple claims/vouchers
    for employee-level audit view in Weekly Accounts Audit Batch.
    """
    clean_claims = _parse_claim_names_list(claim_names)
    if not clean_claims:
        return {"total_receipts": 0, "attachments": []}

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

    return {
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

                if raw_url.startswith("/private/files/"):
                    file_rel = raw_url.replace("/private/files/", "private/files/")
                    physical_path = os.path.join(site_path, file_rel)
                elif raw_url.startswith("/files/"):
                    file_rel = raw_url.replace("/files/", "public/files/")
                    physical_path = os.path.join(site_path, file_rel)
                else:
                    physical_path = os.path.join(site_path, "public", "files", os.path.basename(raw_url))

                if not os.path.exists(physical_path):
                    alt_priv = os.path.join(site_path, "private", "files", os.path.basename(raw_url))
                    if os.path.exists(alt_priv):
                        physical_path = alt_priv

                norm_path = os.path.normpath(physical_path)
                if not norm_path.startswith(os.path.normpath(site_path)):
                    continue

                if os.path.exists(norm_path) and os.path.isfile(norm_path):
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
    if hasattr(doc, "expense_lines"):
        table_field = "expense_lines"
    elif hasattr(doc, "vendor_lines"):
        table_field = "vendor_lines"
    elif hasattr(doc, "expense_items"):
        table_field = "expense_items"

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
    update_vals = {"expense_head": clean_head}
    if custom_ledger_name:
        target_row.custom_ledger_name = custom_ledger_name.strip()
        update_vals["custom_ledger_name"] = custom_ledger_name.strip()

    frappe.db.set_value(child_table, target_row.name, update_vals)

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
