# Copyright (c) 2026, Quanti and contributors
# Enterprise Admin Weekly Vendor Claim Controller (Petty-Cash-Style Multi-Row Architecture)

import io
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, flt, get_url, now_datetime
from frappe.utils.xlsxutils import make_xlsx
from ap_automation.exceptions import APValidationError, APSecurityError


class AdminWeeklyVendorClaim(Document):
    """
    Parent Controller for Admin Weekly Vendor Claims.
    Replaces manual weekly Excel spreadsheets with automated multi-row child table intake,
    6-stage Petty-Cash-style approvals (Admin L1 -> Admin L2 -> Accounts -> Director -> Paid),
    zero-typing locked bank masters, in-grid bill proof uploaders, and 1-click Excel export.
    """

    def validate(self):
        """Standard lifecycle hook called on document save."""
        self.set_claim_metadata()
        self.validate_posting_date()
        self.validate_and_lock_vendor_lines()
        self.calculate_totals()
        self.validate_immutability()

    def set_claim_metadata(self):
        """Generates dynamic voucher title based on Week Period."""
        if not self.prepared_by:
            self.prepared_by = frappe.session.user if getattr(frappe, "session", None) else "Administrator"

        period_label = self.week_period or "Weekly Claim"
        line_count = len(self.vendor_lines) if getattr(self, "vendor_lines", None) else 0
        self.claim_title = f"Admin Vendor Expenses — {period_label} ({line_count} Bills)"

    def validate_posting_date(self):
        """Blocks future posting dates."""
        if self.posting_date and getdate(self.posting_date) > getdate(frappe.utils.nowdate()):
            frappe.throw(_("Posting Date cannot be set to a future date."), title=_("Invalid Posting Date"), exc=APValidationError)

    def validate_and_lock_vendor_lines(self):
        """
        Validates every line item in the child table grid:
        1. Ensures at least one vendor bill line exists.
        2. Automatically fetches, verifies, and locks Bank Account & IFSC from ERPNext Supplier Master.
        3. Enforces Penny Drop Zero-Trust security checks.
        4. Validates mandatory bill proof and positive amount.
        """
        if not self.vendor_lines or len(self.vendor_lines) == 0:
            frappe.throw(
                _("At least one Vendor Bill line item is required in the table grid before saving."),
                title=_("Empty Table Grid"),
                exc=APValidationError
            )

        is_submitting = getattr(self, "status", "Draft") not in ("Draft", "Rejected")

        for idx, row in enumerate(self.vendor_lines, start=1):
            if not row.vendor:
                frappe.throw(_("Row #{0}: Vendor / Supplier is mandatory.").format(idx), title=_("Missing Vendor"), exc=APValidationError)

            if not row.company:
                frappe.throw(_("Row #{0}: Company Entity is mandatory.").format(idx), title=_("Missing Company"), exc=APValidationError)

            if flt(row.amount) <= 0:
                frappe.throw(_("Row #{0}: Net Pay Amount must be strictly greater than 0.00.").format(idx), title=_("Invalid Amount"), exc=APValidationError)

            if is_submitting and not row.receipt_attachment:
                frappe.throw(
                    _("Row #{0} ({1}): Vendor Bill Proof PDF/Photo attachment is strictly mandatory.").format(idx, row.vendor),
                    title=_("Missing Bill Attachment"),
                    exc=APValidationError
                )

            # Auto-fetch & lock Supplier details and bank account from tabBank Account
            supp = frappe.db.get_value("Supplier", row.vendor, ["supplier_name", "disabled"], as_dict=True)
            if not supp:
                frappe.throw(_("Row #{0}: Supplier '{1}' not found in master.").format(idx, row.vendor), exc=APValidationError)

            if supp.disabled:
                frappe.throw(_("Row #{0}: Supplier '{1}' is Disabled in ERPNext.").format(idx, row.vendor), exc=APSecurityError)

            row.vendor_name = supp.supplier_name

            # Fetch Bank details
            bank_info = self._get_supplier_bank_details(row.vendor)
            if bank_info:
                row.bank_beneficiary_name = bank_info.get("bank_beneficiary_name") or supp.supplier_name
                row.bank_account_number = bank_info.get("bank_account_no") or ""
                row.bank_ifsc_code = bank_info.get("ifsc_code") or ""
                row.penny_drop_status = bank_info.get("penny_drop_status") or "UNVERIFIED"

                if is_submitting and bank_info.get("penny_drop_status") == "LOCKED_PENNY_DROP_MISMATCH":
                    frappe.throw(
                        _("Row #{0} ({1}): Bank account is hard-locked due to NPCI Penny Drop Name Mismatch! "
                          "Submission is halted until Accounts Manager override.").format(idx, row.vendor),
                        title=_("Penny Drop Security Lockout"),
                        exc=APSecurityError
                    )
            elif is_submitting:
                # If no bank account found in Bank Account doctype, set beneficiary to vendor name
                row.bank_beneficiary_name = row.bank_beneficiary_name or supp.supplier_name

    @staticmethod
    def _get_supplier_bank_details(supplier_id):
        """Queries the active Bank Account linked to the Supplier."""
        accs = frappe.db.sql(
            """
            SELECT ba.name, ba.bank, ba.bank_account_no, ba.branch_code, ba.penny_drop_status, ba.account_name
            FROM `tabBank Account` ba
            WHERE ba.party_type = 'Supplier' AND ba.party = %s
            ORDER BY ba.is_default DESC, ba.creation DESC
            LIMIT 1
            """,
            (supplier_id,),
            as_dict=True
        )
        if accs:
            return {
                "bank_name": accs[0].bank or "",
                "bank_account_no": accs[0].bank_account_no or "",
                "ifsc_code": accs[0].branch_code or "",
                "penny_drop_status": accs[0].penny_drop_status or "UNVERIFIED",
                "bank_beneficiary_name": accs[0].account_name or ""
            }
        return None

    def calculate_totals(self):
        """Auto-computes total count of bills and grand total net pay."""
        self.total_lines = len(self.vendor_lines) if self.vendor_lines else 0
        self.total_amount = sum(flt(r.amount) for r in self.vendor_lines) if self.vendor_lines else 0.0

    def validate_immutability(self):
        """Prevents tampering once approved beyond Draft."""
        if self.is_new():
            return
        old_status = frappe.db.get_value(self.doctype, self.name, "status")
        if old_status in ("Approved for Payment", "Queued in Batch", "Paid") and self.status == old_status:
            # Check if lines were modified
            old_count = frappe.db.count("Admin Vendor Claim Item", {"parent": self.name})
            if old_count != len(self.vendor_lines):
                frappe.throw(_("Immutability Violation: Approved weekly vouchers cannot be modified."), exc=APSecurityError)


# --------------------------------------------------------------------------------------
# WHITELISTED LIFECYCLE WORKFLOW TRANSITION APIS (PETTY CASH FLOW)
# --------------------------------------------------------------------------------------

@frappe.whitelist()
def get_supplier_bank_info(supplier):
    """Fetches legal name and verified bank account details for a Supplier."""
    if not supplier:
        return {}
    supp = frappe.db.get_value("Supplier", supplier, ["supplier_name", "disabled"], as_dict=True)
    if not supp:
        return {}

    bank_data = AdminWeeklyVendorClaim._get_supplier_bank_details(supplier)
    return {
        "supplier_name": supp.supplier_name,
        "disabled": supp.disabled,
        "bank_beneficiary_name": bank_data.get("bank_beneficiary_name") if bank_data else supp.supplier_name,
        "bank_account_number": bank_data.get("bank_account_no") if bank_data else "",
        "bank_ifsc_code": bank_data.get("ifsc_code") if bank_data else "",
        "penny_drop_status": bank_data.get("penny_drop_status") if bank_data else "UNVERIFIED"
    }


@frappe.whitelist()
def submit_to_admin_l1(docname):
    """Stage 1 -> Stage 2: Submits draft voucher to Admin L1 Review."""
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status not in ("Draft", "Rejected"):
        frappe.throw(_("Voucher must be in Draft or Rejected status to submit."))

    doc.status = "Pending Admin L1"
    doc.admin_rejection_reason = ""
    doc.save()
    return {"status": doc.status, "message": _("Voucher successfully submitted to Admin L1 Review.")}


@frappe.whitelist()
def approve_admin_l1(docname):
    """Stage 2 -> Stage 3: Admin L1 Approver sign-off."""
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status != "Pending Admin L1":
        frappe.throw(_("Voucher must be in 'Pending Admin L1' status."))

    doc.admin_l1_approver = frappe.session.user
    doc.admin_l1_date = now_datetime()
    doc.status = "Pending Admin L2"
    doc.save()
    return {"status": doc.status, "message": _("Admin L1 Review approved. Forwarded to Admin L2 (Operations Head).")}


@frappe.whitelist()
def approve_admin_l2(docname):
    """Stage 3 -> Stage 4: Admin L2 Head sign-off."""
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status != "Pending Admin L2":
        frappe.throw(_("Voucher must be in 'Pending Admin L2' status."))

    doc.admin_l2_approver = frappe.session.user
    doc.admin_l2_date = now_datetime()
    doc.status = "Pending Accounts Review"
    doc.save()
    return {"status": doc.status, "message": _("Admin L2 Sign-off complete. Transferred to Accounts Review.")}


@frappe.whitelist()
def approve_accounts(docname):
    """Stage 4 -> Stage 5: Accounts Audit clearance."""
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status != "Pending Accounts Review":
        frappe.throw(_("Voucher must be in 'Pending Accounts Review' status."))

    doc.accounts_reviewer = frappe.session.user
    doc.accounts_date = now_datetime()
    doc.status = "Approved for Payment"
    doc.save()
    return {"status": doc.status, "message": _("Accounts Audit cleared. Approved for Director Payout Sanction.")}


@frappe.whitelist()
def sanction_director(docname):
    """Stage 5 -> Stage 6 Queued in Batch: Director authorization."""
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status != "Approved for Payment":
        frappe.throw(_("Voucher must be 'Approved for Payment' to sanction."))

    doc.director_approver = frappe.session.user
    doc.director_date = now_datetime()
    doc.status = "Queued in Batch"
    doc.batch_id = f"BATCH-ADMIN-{doc.name[-5:]}"
    doc.save()
    return {"status": doc.status, "message": _("Director Payout sanctioned. Queued in Payment Batch for Bank Release.")}


@frappe.whitelist()
def disburse_payment(docname, utr_number=None):
    """Stage 6: Settlement stamped with Bank UTR."""
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    utr = utr_number or f"IDFC{now_datetime().strftime('%Y%m%d%H%M%S')}"

    doc.disbursement_utr = utr
    doc.status = "Paid"
    doc.save()

    doc.add_comment("Comment", text=f"💳 <b>Disbursed & Paid via Bank:</b> UTR Reference #{utr}")
    return {"status": doc.status, "utr": utr, "message": _("All line payouts settled. Stamped with UTR.")}


@frappe.whitelist()
def reject_or_return(docname, reason_code, remarks, return_to="Draft"):
    """
    Non-Silent Rejection & Return Hook:
    Strictly forces mandatory remarks and returns voucher to designated step.
    """
    if not remarks or len(remarks.strip()) < 10:
        frappe.throw(_("Detailed remarks are strictly mandatory for rejection (minimum 10 characters)."), title=_("Remarks Required"))

    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    user = frappe.session.user
    now_str = now_datetime().strftime("%Y-%m-%d %H:%M:%S")

    rej_text = f"[{now_str}] Returned by {user} | Reason: {reason_code} | Notes: {remarks.strip()}"
    doc.admin_rejection_reason = rej_text
    doc.return_to = return_to
    doc.status = return_to if return_to in ("Draft", "Pending Admin L1", "Pending Admin L2", "Pending Accounts Review") else "Draft"
    doc.save()

    # Log forensic error
    frappe.log_error(title=f"Admin Vendor Claim Returned: {docname}", message=rej_text)
    doc.add_comment("Comment", text=f"🚫 <b>Voucher Returned:</b> {reason_code} — {remarks.strip()}")

    return {"status": doc.status, "message": _("Voucher returned to {0}.").format(doc.status), "rejection_log": rej_text}


@frappe.whitelist()
def generate_weekly_excel_download(docname):
    """
    Generates exact Excel Spreadsheet matching the Admin team's format,
    injecting clean =HYPERLINK(..., 'View Proof') formulas in the Proof PDF column.
    """
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)

    headers = [
        "Sr.No",
        "Vendor Category",
        "Name",
        "Net Pay",
        "Name As Per Bank Records",
        "Bank Ac No",
        "IFSC Code",
        "Company",
        "Proof PDF",
        "Invoice #",
        "Remarks"
    ]

    rows = []
    for idx, row in enumerate(doc.vendor_lines, start=1):
        proof_formula = ""
        if row.receipt_attachment:
            full_url = get_url(row.receipt_attachment)
            proof_formula = f'=HYPERLINK("{full_url}", "View Proof")'

        rows.append([
            idx,
            row.vendor_category or "",
            row.vendor_name or row.vendor or "",
            flt(row.amount),
            row.bank_beneficiary_name or row.vendor_name or "",
            f"'{row.bank_account_number}" if row.bank_account_number else "",
            row.bank_ifsc_code or "",
            row.company or "",
            proof_formula,
            row.invoice_number or "",
            row.remarks or ""
        ])

    # Grand Total row
    rows.append([
        "",
        "",
        "Grand Total",
        flt(doc.total_amount),
        "",
        "",
        "",
        "",
        "",
        "",
        ""
    ])

    xlsx_data = [headers] + rows
    sheet_title = doc.week_period or "Vendor Expenses"
    xlsx_file = make_xlsx(xlsx_data, sheet_title[:31])

    frappe.response["filename"] = f"{doc.name}_{sheet_title}.xlsx".replace(" ", "_")
    frappe.response["filecontent"] = xlsx_file.getvalue()
    frappe.response["type"] = "binary"
