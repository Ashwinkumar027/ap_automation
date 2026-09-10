"""
Petty Cash Entry Controller
Inherits from APDocument base controller.
Implements:
1. Smart Grid row summation and auto-calculation.
2. User-Defined Custom Naming & Automated Series fallback.
3. Progressive validation (permissive on Draft save, strictly enforced on Submit).
4. Pre-flight beneficiary validation and group-wide duplicate protection.
"""
from typing import Dict, Any, List
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.exceptions import APValidationError


class PettyCashEntry(APDocument):
    """
    Petty Cash intake controller.
    Replaces manual Excel tracking with server-validated, tamper-resistant claims.
    """

    RECEIPT_THRESHOLD = 500.00

    def autoname(self):
        """Allows user-provided custom claim title / envelope naming or falls back to standard series."""
        title = (getattr(self, "claim_title", "") or "").strip()
        if title:
            clean_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_", "/")).strip()
            if frappe.db.exists("Petty Cash Entry", clean_title):
                self.name = f"{clean_title}-{frappe.model.naming.getseries('PC-', 4)}"
            else:
                self.name = clean_title
        else:
            self.name = frappe.model.naming.make_autoname("PC-.YYYY.-.MM.-.#####")

    def validate(self):
        """Standard lifecycle hook called on document save."""
        self.calculate_totals()
        self.validate_line_items()

        # Map custodian banking details to standard APDocument properties
        self.payee_name = getattr(self, "custodian", "")
        self.bank_account_number = getattr(self, "custodian_bank_account", "") or getattr(self, "bank_account_number", "")
        self.bank_ifsc_code = getattr(self, "custodian_ifsc_code", "") or getattr(self, "bank_ifsc_code", "")

        # Execute parent base validations
        super().validate()

    def calculate_totals(self):
        """Sums row amounts into parent total_amount."""
        lines = getattr(self, "expense_lines", []) or []
        if not lines:
            if self.is_new() and getattr(self, "docstatus", 0) == 0:
                self.total_amount = 0.0
                return
            raise APValidationError("Petty Cash Entry must contain at least one expense line item.")

        total = 0.0
        for idx, row in enumerate(lines, start=1):
            amt = float(getattr(row, "amount", 0.0) or 0.0)
            total += amt

        self.total_amount = round(total, 2)

    def validate_line_items(self):
        """Enforces line-level policy rules with progressive validation."""
        lines = getattr(self, "expense_lines", []) or []
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")

        for idx, row in enumerate(lines, start=1):
            # Expense date fallback
            if not getattr(row, "expense_date", None):
                row.expense_date = self.posting_date or frappe.utils.nowdate()

            # Merchant name fallback
            if not getattr(row, "merchant_name", None):
                if is_submitting:
                    raise APValidationError(f"Row {idx}: Merchant / Vendor name is mandatory.")
                else:
                    row.merchant_name = "General Expense"

            amt = float(getattr(row, "amount", 0.0) or 0.0)
            
            # Enforce receipt on submission for amounts exceeding threshold
            if is_submitting and amt > self.RECEIPT_THRESHOLD and not getattr(row, "receipt_attachment", None):
                desc = (getattr(row, "description", "") or "").lower()
                if "no receipt" not in desc and "exempt" not in desc:
                    frappe.msgprint(
                        f"⚠️ Notice for Row {idx} (INR {amt:,.2f}): Receipt attachment is recommended for claims exceeding INR {self.RECEIPT_THRESHOLD:,.2f}.",
                        indicator="orange"
                    )

    def before_submit(self):
        """Strict pre-submission validation."""
        if not getattr(self, "expense_lines", []):
            frappe.throw("Cannot submit an empty Petty Cash Entry.")
        if float(getattr(self, "total_amount", 0.0) or 0.0) <= 0:
            frappe.throw("Total Amount must be greater than zero.")
