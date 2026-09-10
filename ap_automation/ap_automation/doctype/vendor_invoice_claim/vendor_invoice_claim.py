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
"""
from typing import Dict, Any, List
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.duplicate_engine import register_spend_fingerprint, release_spend_fingerprint
from ap_automation.services.matching_service import execute_3way_matching
from ap_automation.services.tds_service import apply_tds_to_invoice


class VendorInvoiceClaim(APDocument):
    """
    Vendor Invoice Claim controller.
    Ensures zero fraud, penny drop lockout enforcement, statutory GST/TDS compliance, and IDFC payout integration.
    """

    def validate(self):
        """Lifecycle hook executed on document save."""
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

        # Execute parent base validations (duplicate hash, immutability, tamper guard)
        super().validate()

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
            raise APValidationError("Vendor / Supplier is mandatory.")

        supp = frappe.db.get_value(
            "Supplier",
            vendor_id,
            ["supplier_name", "tax_id", "country", "disabled"],
            as_dict=True
        )
        if not supp:
            raise APValidationError(f"Supplier '{vendor_id}' not found in ERPNext master.")

        if supp.disabled:
            raise APSecurityError(f"Supplier '{vendor_id}' is Disabled / Inactive in ERPNext. Invoices cannot be processed.")

        self.vendor_name = supp.supplier_name
        self.vendor_gstin = supp.tax_id or ""

        bank_acc = self._fetch_supplier_bank_account(vendor_id)
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        if not bank_acc:
            if is_submitting:
                raise APValidationError(
                    f"Banking Details Missing: Vendor '{self.vendor_name}' does not have a registered, verified "
                    "bank account in ERPNext. Please update the Supplier Bank Master before filing an invoice."
                )
            else:
                bank_acc = {"bank_name": "Pending Verification", "bank_account_no": "", "ifsc_code": ""}

        # Zero-Trust Penny Drop Lockout Guard
        pd_status = bank_acc.get("penny_drop_status")
        if pd_status == "LOCKED_PENNY_DROP_MISMATCH":
            raise APSecurityError(
                f"🚨 FRAUD & SECURITY HARD-LOCKOUT: Vendor '{self.vendor_name}' bank account "
                f"({bank_acc.get('bank_account_no')}) is hard-locked due to NPCI Penny Drop Name Mismatch! "
                "Invoice submission and payments are strictly halted until Accounts Manager review and manual unlock."
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
                raise APValidationError("Linked Purchase Order is mandatory when Route is 'With Purchase Order'.")

        elif route == "Without PO (Direct Tax Invoice)":
            if not getattr(self, "email_approval_attachment", None):
                raise APValidationError(
                    "Missing Internal Email Approval: For non-PO direct tax invoices, a screenshot or PDF of the "
                    "approving manager's email is strictly mandatory (PRD Section 6)."
                )

        if not getattr(self, "tax_invoice_attachment", None):
            raise APValidationError("Vendor Tax Invoice PDF attachment is strictly mandatory.")

        if not getattr(self, "tax_invoice_number", None):
            raise APValidationError("Vendor Tax Invoice # is mandatory.")

        if not getattr(self, "tax_invoice_date", None):
            raise APValidationError("Tax Invoice Date is mandatory.")

    def calculate_financial_totals(self):
        """Calculates GST amount and Total Invoice amount with progressive Draft support."""
        base = float(getattr(self, "base_amount", 0.0) or getattr(self, "invoice_amount", 0.0) or getattr(self, "taxable_amount", 0.0) or 0.0)
        self.base_amount = base
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        if is_submitting and base <= 0:
            raise APValidationError("Base Taxable Amount must be strictly positive upon submission.")

        rate_str = getattr(self, "gst_rate", "18%") or "18%"
        rate_val = float(rate_str.replace("%", "").strip() or 0.0)

        gst = round(base * (rate_val / 100.0), 2)
        total = round(base + gst, 2)
        advance = float(getattr(self, "advance_deducted", 0.0) or 0.0)

        if advance < 0:
            raise APValidationError("Advance Deducted cannot be negative.")

        if advance > total:
            raise APValidationError(
                f"Prior Advance Deducted (INR {advance:,.2f}) cannot exceed Total Invoice Amount (INR {total:,.2f})."
            )

        self.gst_amount = gst
        self.total_invoice_amount = total
        self.net_payable_amount = round(total - advance, 2)
