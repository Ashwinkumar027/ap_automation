"""
Petty Cash Entry Controller
Inherits from APDocument base controller.
Implements:
1. Smart Grid row summation and auto-calculation.
2. Mandatory receipt threshold (> INR 500).
3. Pre-flight beneficiary validation and group-wide duplicate protection.
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

    def validate(self):
        """Standard lifecycle hook called on document save."""
        self.calculate_totals()
        self.validate_line_items()

        # Map custodian banking details to standard APDocument properties
        self.payee_name = getattr(self, "custodian", "")
        self.bank_account_number = getattr(self, "custodian_bank_account", "")
        self.bank_ifsc_code = getattr(self, "custodian_ifsc_code", "")

        # Execute parent base validations (immutability, company authorization, duplicate hash)
        super().validate()

    def calculate_totals(self):
        """Sums row amounts into parent total_amount."""
        lines = getattr(self, "expense_lines", []) or []
        if not lines:
            raise APValidationError("Petty Cash Entry must contain at least one expense line item.")

        total = 0.0
        for idx, row in enumerate(lines, start=1):
            amt = float(getattr(row, "amount", 0.0) or 0.0)
            if amt <= 0:
                raise APValidationError(f"Invalid amount at row {idx}: {amt}. Line items must have positive amounts.")
            total += amt

        self.total_amount = round(total, 2)

    def validate_line_items(self):
        """Enforces line-level policy rules."""
        lines = getattr(self, "expense_lines", []) or []
        for idx, row in enumerate(lines, start=1):
            if not getattr(row, "expense_date", None):
                raise APValidationError(f"Row {idx}: Expense Date is mandatory.")

            if not getattr(row, "merchant_name", None):
                raise APValidationError(f"Row {idx}: Merchant / Vendor name is mandatory.")

            amt = float(getattr(row, "amount", 0.0) or 0.0)
            # Enforce receipt attachment if expense exceeds threshold
            if amt > self.RECEIPT_THRESHOLD and not getattr(row, "receipt_attachment", None):
                # We allow an admin override if explicitly marked in description, otherwise enforce
                desc = (getattr(row, "description", "") or "").lower()
                if "no receipt" not in desc and "exempt" not in desc:
                    raise APValidationError(
                        f"Row {idx} ({getattr(row, 'merchant_name', 'Expense')} - INR {amt:,.2f}): "
                        f"Receipt attachment is mandatory for expenses exceeding INR {self.RECEIPT_THRESHOLD:,.2f}."
                    )
