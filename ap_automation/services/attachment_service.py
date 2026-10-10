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

    # 3. Scan Generic other child tables (e.g. lines, items, instructions)
    other_child_tables = ["lines", "items", "instructions"]
    for table_field in other_child_tables:
        rows = getattr(doc, table_field, []) or []
        for row in rows:
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

    # 4. Scan Parent-Level Direct Attachment Fields
    parent_fields = [
        ("activity_photo", "📸 Team Activity Photo Proof", "Team Engagement & Recreation"),
        ("pre_approval_attachment", "📋 Pre-Approval Authorization Screenshot", "Audit Proof Document"),
        ("tax_invoice_attachment", "Vendor Tax Invoice", "Audit Proof Document"),
        ("email_approval_attachment", "Manager Email Approval", "Audit Proof Document"),
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
                "category": cat_label,
                "amount": float(getattr(doc, "total_claim_amount", 0.0) or getattr(doc, "total_amount", 0.0) or 0.0),
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
    site_path = frappe.get_site_path()
    file_name = os.path.basename(file_url)

    # Search paths in order of preference
    possible_paths = [
        # 1. Direct if relative to site
        os.path.join(site_path, file_url.lstrip("/")),
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
