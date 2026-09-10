"""
AP Automation - Unified Attachment Service (Bank-Grade Production Architecture)
Provides server-side attachment extraction, child table linking, and dynamic ZIP packaging.
Certified against path traversal and strict authorization boundaries.
"""
import os
import io
import zipfile
from typing import List, Dict, Any, Optional
import frappe
from frappe import _
from ap_automation.exceptions import APValidationError, APPermissionError


def _check_document_permission(doctype: str, docname: str, ptype: str = "read") -> None:
    """Enforces Frappe user permission checks before extracting attachments."""
    if not frappe.has_permission(doctype, ptype=ptype, doc=docname):
        raise APPermissionError(f"User {frappe.session.user} does not have '{ptype}' permission on {doctype} {docname}.")


@frappe.whitelist()
def get_all_claim_attachments(doctype: str, docname: str) -> List[Dict[str, Any]]:
    """
    Scans child tables and Frappe File records to extract all receipts and proofs
    with enriched business metadata (Merchant, Expense Date, Amount, Category, Staff Name, Row Index).
    """
    _check_document_permission(doctype, docname, ptype="read")

    if not frappe.db.exists(doctype, docname):
        raise APValidationError(f"Document '{doctype}' / '{docname}' does not exist.")

    doc = frappe.get_doc(doctype, docname)
    attachments: List[Dict[str, Any]] = []

    # 1. Scan Child Table Expense Lines
    child_tables = ["expense_lines", "lines", "items", "instructions"]
    for table_field in child_tables:
        rows = getattr(doc, table_field, []) or []
        for row in rows:
            file_url = (
                getattr(row, "receipt_attachment", None)
                or getattr(row, "attach_receipt", None)
                or getattr(row, "attachment", None)
                or getattr(row, "tax_invoice_attachment", None)
                or getattr(row, "bill_attachment", None)
            )

            if file_url and isinstance(file_url, str) and file_url.strip():
                file_url = file_url.strip()
                file_name = file_url.split("/")[-1]
                ext = os.path.splitext(file_name)[1].lower()

                # Robust Category Resolution
                cat = (
                    getattr(row, "expense_category", None)
                    or getattr(row, "category", None)
                    or getattr(row, "expense_type", None)
                    or "General Expense"
                )

                # Robust Date Resolution
                exp_date = (
                    getattr(row, "expense_date", None)
                    or getattr(row, "date", None)
                    or doc.get("posting_date", None)
                    or doc.get("invoice_date", None)
                    or ""
                )

                staff = (
                    getattr(row, "staff_name", "")
                    or getattr(row, "employee_name", "")
                    or getattr(row, "employee", "")
                    or ""
                )

                attachments.append({
                    "source": "row",
                    "row_idx": getattr(row, "idx", len(attachments) + 1),
                    "merchant": getattr(row, "merchant_name", "") or getattr(row, "merchant", "") or getattr(row, "vendor_name", "Vendor / Merchant"),
                    "category": cat,
                    "amount": float(getattr(row, "amount", 0.0) or getattr(row, "claim_amount", 0.0) or 0.0),
                    "date": str(exp_date),
                    "staff_name": staff,
                    "bill_no": getattr(row, "bill_number", "") or getattr(row, "bill_no", "") or getattr(row, "invoice_number", ""),
                    "file_url": file_url,
                    "file_name": file_name,
                    "is_image": ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"],
                    "is_pdf": ext == ".pdf",
                    "extension": ext
                })

    # 2. Scan Parent-Level Direct Attachment Fields
    parent_fields = [
        ("tax_invoice_attachment", "Vendor Tax Invoice", "Vendor Commercial Invoice"),
        ("email_approval_attachment", "Manager Email Approval", "Audit Approval Proof"),
        ("grn_attachment", "Goods Receipt Note / Delivery Proof", "Warehouse Receipt"),
        ("advance_receipt_attachment", "Advance Payment Proof", "Bank Advance Proof"),
        ("settlement_statement", "Event Settlement Statement", "Event Settlement")
    ]

    for fieldname, label, cat_label in parent_fields:
        file_url = getattr(doc, fieldname, None)
        if file_url and isinstance(file_url, str) and file_url.strip():
            file_url = file_url.strip()
            file_name = file_url.split("/")[-1]
            ext = os.path.splitext(file_name)[1].lower()

            attachments.append({
                "source": "parent",
                "row_idx": None,
                "merchant": label,
                "category": cat_label,
                "amount": float(getattr(doc, "total_amount", 0.0) or getattr(doc, "total_invoice_amount", 0.0) or getattr(doc, "total_claim_amount", 0.0) or 0.0),
                "date": str(doc.get("posting_date", "") or doc.get("invoice_date", "")),
                "staff_name": str(doc.get("custodian", "") or doc.get("employee_name", "") or ""),
                "bill_no": str(doc.get("invoice_number", "") or doc.get("name", "")),
                "file_url": file_url,
                "file_name": file_name,
                "is_image": ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"],
                "is_pdf": ext == ".pdf",
                "extension": ext
            })

    # 3. Scan Generic File Attachments from tabFile
    files = frappe.get_all(
        "File",
        filters={"attached_to_doctype": doctype, "attached_to_name": docname},
        fields=["file_name", "file_url", "file_size", "is_private"]
    )

    existing_urls = {a["file_url"] for a in attachments}
    for f in files:
        f_url = f.get("file_url")
        if f_url and f_url not in existing_urls:
            ext = os.path.splitext(f.get("file_name", ""))[1].lower()
            attachments.append({
                "source": "attached_file",
                "row_idx": None,
                "merchant": "Attached Supporting File",
                "category": "General Attachment",
                "amount": 0.0,
                "date": str(doc.get("posting_date", "")),
                "staff_name": "",
                "bill_no": "",
                "file_url": f_url,
                "file_name": f.get("file_name") or f_url.split("/")[-1],
                "is_image": ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"],
                "is_pdf": ext == ".pdf",
                "extension": ext
            })

    return attachments


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
            
            if raw_url.startswith("/private/files/"):
                file_rel = raw_url.replace("/private/files/", "private/files/")
                physical_path = os.path.join(site_path, file_rel)
            elif raw_url.startswith("/files/"):
                file_rel = raw_url.replace("/files/", "public/files/")
                physical_path = os.path.join(site_path, file_rel)
            else:
                physical_path = os.path.join(site_path, "public", "files", os.path.basename(raw_url))

            norm_path = os.path.normpath(physical_path)
            if not norm_path.startswith(os.path.normpath(site_path)):
                continue

            if os.path.exists(norm_path) and os.path.isfile(norm_path):
                ext = att["extension"] or ".png"
                clean_merchant = "".join(c for c in (att["merchant"] or "Expense") if c.isalnum() or c in (" ", "-", "_")).strip()
                clean_cat = "".join(c for c in (att["category"] or "Receipt") if c.isalnum() or c in (" ", "-", "_")).strip()
                clean_staff = "".join(c for c in (att.get("staff_name") or "") if c.isalnum() or c in (" ", "-", "_")).strip()
                date_str = (att.get("date") or "").replace("-", "")
                
                staff_part = f"_{clean_staff}" if clean_staff else ""
                if att["row_idx"]:
                    archive_name = f"Row-{att['row_idx']}_{clean_cat}_{clean_merchant}{staff_part}_{date_str}_{int(att['amount'])}INR{ext}"
                else:
                    archive_name = f"{clean_cat}_{clean_merchant}{staff_part}_{date_str}_{idx}{ext}"

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
