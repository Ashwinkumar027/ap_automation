"""
Vendor Invoice Claim Controller (Lane 3 Intake & Governance)
Inherits from APDocument base controller.
Enforces:
1. Dual-route intake rules (With PO vs Without PO).
2. Zero-typing vendor bank account binding from ERPNext Supplier master.
3. Penny Drop Zero-Trust Lockout: Blocks filing if bank account is locked due to NPCI mismatch.
4. Mandatory proof attachments (Tax invoice + Email approval for non-PO).
5. Statutory GST calculation (0%, 5%, 12%, 18%, 28%).
6. Autonomous 3-Way Matching against PO and GRN with tolerance checks.
7. Statutory Indian TDS calculation (194C, 194J, 194Q, 206AB).
8. Advance offset deduction: Net = Total - Advance - TDS.
9. Group-wide duplicate spend fingerprinting via APDocument base class.
10. Full Audit Error Logging (frappe.log_error) and Interactive Error Dialogs.
"""
from typing import Dict, Any, List
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.duplicate_engine import register_spend_fingerprint, release_spend_fingerprint
from ap_automation.services.matching_service import execute_3way_matching
from ap_automation.services.tds_service import apply_tds_to_invoice


def log_and_throw(message: str, title: str = "Vendor Claim Validation Error", exc=APValidationError, doc=None):
    """
    Logs an official Error Log in Frappe DB and raises a user-facing interactive error dialog.
    Guarantees zero silent rejections and full audit visibility in Desk UI.
    """
    doc_name = getattr(doc, "name", "Draft") if doc else "Draft"
    vendor_label = getattr(doc, "vendor_name", None) or getattr(doc, "vendor", "Unassigned") if doc else "Unassigned"
    
    try:
        frappe.log_error(
            title=f"Vendor Claim Validation Error: {title} ({doc_name})",
            message=(
                f"Validation Failure Details:\n"
                f"---------------------------\n"
                f"Title: {title}\n"
                f"Reason: {message}\n"
                f"Document: {doc_name}\n"
                f"Vendor: {vendor_label}\n"
                f"User: {frappe.session.user if getattr(frappe, 'session', None) else 'System'}\n"
                f"DocType: Vendor Invoice Claim\n"
            )
        )
    except Exception:
        pass

    frappe.throw(message, title=title, exc=exc)


class VendorInvoiceClaim(APDocument):
    """
    Vendor Invoice Claim controller.
    Ensures zero fraud, penny drop lockout enforcement, statutory GST/TDS compliance, and IDFC payout integration.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flags.ignore_links = True

    def validate(self):
        """Lifecycle hook executed on document save."""
        po_val = getattr(self, "purchase_order", None)
        if po_val and frappe.db.exists("AP Purchase Order", po_val):
            self.flags.ignore_links = True

        self.bind_and_lock_vendor_profile()
        self.validate_intake_route_and_proofs()
        self.calculate_financial_totals()

        # Execute 3-Way Matching Engine
        execute_3way_matching(self)

        # Apply Statutory Indian TDS
        apply_tds_to_invoice(self)

        # Map payee and invoice fields for APDocument base spend hash and banking dispatch
        self.payee_name = getattr(self, "vendor_name", "") or getattr(self, "vendor", "")
        self.invoice_number = getattr(self, "tax_invoice_number", "")
        self.total_amount = self.net_payable_amount

        # Advance status from Draft based on 3-Way matching & proof validation
        if self.match_status in ("Price Mismatch Flagged", "Quantity Mismatch Flagged", "Missing GRN Flagged"):
            self.status = "Disputed"
        elif getattr(self, "status", "Draft") in ("Draft", "Not Saved"):
            if self.match_status == "3-Way Match Passed":
                self.status = "Pending Accounts Review"
            elif self.invoice_type == "Without PO (Direct Tax Invoice)" and getattr(self, "email_approval_attachment", None):
                self.status = "Pending Accounts Review"

        # Execute parent base validations (duplicate hash, immutability, tamper guard)
        super().validate()

    def before_submit(self):
        """Pre-submission verification guard: strictly halts any invalid or incomplete filing."""
        self.bind_and_lock_vendor_profile()
        self.validate_intake_route_and_proofs()
        self.calculate_financial_totals()

    def on_submit(self):
        """Registers spend fingerprint lock upon submission."""
        super().on_submit()
        register_spend_fingerprint(self)

    def on_cancel(self):
        """Releases spend fingerprint lock if cancelled."""
        super().on_cancel()
        release_spend_fingerprint(self)

    def bind_and_lock_vendor_profile(self):
        """
        Pulls verified vendor details and bank account directly from ERPNext Supplier master.
        Enforces Penny Drop Zero-Trust lockout.
        """
        vendor_id = getattr(self, "vendor", None)
        if not vendor_id:
            log_and_throw("Vendor / Supplier is mandatory.", title="Vendor Required", doc=self)

        supp = frappe.db.get_value(
            "Supplier",
            vendor_id,
            ["supplier_name", "tax_id", "country", "disabled"],
            as_dict=True
        )
        if not supp:
            log_and_throw(f"Supplier '{vendor_id}' not found in ERPNext master.", title="Supplier Not Found", doc=self)

        if supp.disabled:
            log_and_throw(
                f"Supplier '{vendor_id}' is Disabled / Inactive in ERPNext. Invoices cannot be processed.",
                title="Supplier Inactive / Disabled",
                exc=APSecurityError,
                doc=self
            )

        self.vendor_name = supp.supplier_name
        self.vendor_gstin = supp.tax_id or ""

        bank_acc = self._fetch_supplier_bank_account(vendor_id)
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        if not bank_acc:
            if is_submitting:
                log_and_throw(
                    f"Banking Details Missing: Vendor '{self.vendor_name}' does not have a registered, verified "
                    "bank account in ERPNext. Please update the Supplier Bank Master before filing an invoice.",
                    title="Vendor Bank Master Missing",
                    doc=self
                )
            else:
                bank_acc = {"bank_name": "Pending Verification", "bank_account_no": "", "ifsc_code": ""}

        # Zero-Trust Penny Drop Lockout Guard
        pd_status = bank_acc.get("penny_drop_status")
        if pd_status == "LOCKED_PENNY_DROP_MISMATCH":
            log_and_throw(
                f"⚠️ Security Notice: Vendor '{self.vendor_name}' bank account "
                f"({bank_acc.get('bank_account_no')}) is hard-locked due to NPCI Penny Drop Name Mismatch! "
                "Invoice submission and payments are strictly halted until Accounts Manager review and manual unlock.",
                title="NPCI Penny Drop Lockout",
                exc=APSecurityError,
                doc=self
            )

        self.bank_name = bank_acc.get("bank_name", "")
        self.bank_account_number = bank_acc.get("bank_account_no", "")
        self.bank_ifsc_code = bank_acc.get("ifsc_code", "")

    def _fetch_supplier_bank_account(self, supplier_name: str) -> Dict[str, Any]:
        """Looks up active Bank Account linked to Supplier in tabBank Account."""
        accs = frappe.db.sql(
            """
            SELECT ba.name, ba.bank, ba.bank_account_no, ba.branch_code, ba.penny_drop_status
            FROM `tabBank Account` ba
            WHERE ba.party_type = 'Supplier' AND ba.party = %s
            ORDER BY ba.is_default DESC, ba.creation DESC
            LIMIT 1
            """,
            (supplier_name,),
            as_dict=True
        )
        if accs:
            return {
                "name": accs[0].name,
                "bank_name": accs[0].bank or "",
                "bank_account_no": accs[0].bank_account_no or "",
                "ifsc_code": accs[0].branch_code or "",
                "penny_drop_status": accs[0].penny_drop_status or "UNVERIFIED"
            }
        return {}

    def validate_intake_route_and_proofs(self):
        """Enforces dual-route mandatory requirements and audit proof attachments with progressive Draft validation."""
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        route = getattr(self, "invoice_type", "Without PO (Direct Tax Invoice)")

        if not is_submitting:
            # On Draft, assign fallbacks
            if not getattr(self, "tax_invoice_number", None):
                self.tax_invoice_number = self.invoice_number or f"DRAFT-{frappe.generate_hash(length=6).upper()}"
            return

        if route == "With Purchase Order":
            if not getattr(self, "purchase_order", None):
                log_and_throw(
                    "Linked Purchase Order is mandatory when Route is 'With Purchase Order'.",
                    title="Linked Purchase Order Required",
                    doc=self
                )

        elif route == "Without PO (Direct Tax Invoice)":
            if not getattr(self, "email_approval_attachment", None):
                log_and_throw(
                    "Missing Internal Email Approval: For non-PO direct tax invoices, a screenshot or PDF of the "
                    "approving manager's email is strictly mandatory (PRD Section 6).",
                    title="Missing Manager Email Approval Proof",
                    doc=self
                )

        if not getattr(self, "tax_invoice_attachment", None):
            log_and_throw(
                "Vendor Tax Invoice PDF attachment is strictly mandatory.",
                title="Missing Tax Invoice PDF Attachment",
                doc=self
            )

        if not getattr(self, "tax_invoice_number", None):
            log_and_throw(
                "Vendor Tax Invoice # is mandatory.",
                title="Tax Invoice Number Required",
                doc=self
            )

        if not getattr(self, "tax_invoice_date", None):
            log_and_throw(
                "Tax Invoice Date is mandatory.",
                title="Tax Invoice Date Required",
                doc=self
            )

    def calculate_financial_totals(self):
        """Calculates GST amount and Total Invoice amount with progressive Draft support."""
        base = float(getattr(self, "base_amount", 0.0) or getattr(self, "invoice_amount", 0.0) or getattr(self, "taxable_amount", 0.0) or 0.0)
        self.base_amount = base
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        if is_submitting and base <= 0:
            log_and_throw("Base Taxable Amount must be strictly positive upon submission.", title="Invalid Base Amount", doc=self)

        rate_str = getattr(self, "gst_rate", "18%") or "18%"
        rate_val = float(rate_str.replace("%", "").strip() or 0.0)

        gst = round(base * (rate_val / 100.0), 2)
        total = round(base + gst, 2)
        advance = float(getattr(self, "advance_deducted", 0.0) or 0.0)

        if advance < 0:
            log_and_throw("Advance Deducted cannot be negative.", title="Negative Advance Amount", doc=self)

        if advance > total:
            log_and_throw(
                f"Prior Advance Deducted (INR {advance:,.2f}) cannot exceed Total Invoice Amount (INR {total:,.2f}).",
                title="Advance Exceeds Total Amount",
                doc=self
            )

        self.gst_amount = gst
        self.total_invoice_amount = total
        self.net_payable_amount = round(total - advance, 2)


@frappe.whitelist()
def dispute_vendor_claim(docname: str, reason_code: str, remarks: str):
    """
    Whitelisted API: Flags a vendor claim as Disputed with forensic audit logging.
    Ensures rejection is never silent and remarks are permanently preserved.
    """
    if not docname:
        frappe.throw("Document Name is required.", title="Missing Document ID")
    if not remarks or len(remarks.strip()) < 10:
        frappe.throw("Detailed dispute remarks are mandatory (minimum 10 characters).", title="Remarks Required")

    doc = frappe.get_doc("Vendor Invoice Claim", docname)
    user = frappe.session.user if frappe.session else "System"
    now_str = frappe.utils.now()

    dispute_msg = f"[{now_str}] Disputed by {user} | Reason: {reason_code} | Remarks: {remarks.strip()}"
    old_variance = doc.match_variance_details or ""
    doc.match_variance_details = f"{dispute_msg}\n{old_variance}".strip()
    doc.status = "Disputed"
    doc.save(ignore_permissions=True)

    # Log forensic Error Log in Frappe DB
    frappe.log_error(
        title=f"Vendor Claim Flagged Disputed: {docname}",
        message=f"{dispute_msg}\n\nVendor: {doc.vendor_name}\nAmount: INR {doc.net_payable_amount:,.2f}"
    )

    doc.add_comment("Comment", text=f"🚫 <b>Disputed / Rejected:</b> {reason_code} — {remarks.strip()}")

    return {
        "status": "Disputed",
        "message": f"Claim '{docname}' has been successfully placed in Disputed status.",
        "dispute_log": dispute_msg
    }


@frappe.whitelist()
def get_vendor_claim_audit_logs(docname: str) -> List[Dict[str, Any]]:
    """
    Whitelisted API: Returns recent system error logs and audit events for this claim.
    """
    if not docname:
        return []

    logs = frappe.db.sql(
        """
        SELECT name, method, creation, error
        FROM `tabError Log`
        WHERE method LIKE %s OR error LIKE %s
        ORDER BY creation DESC
        LIMIT 10
        """,
        (f"%{docname}%", f"%{docname}%"),
        as_dict=True
    )
    return logs
