"""
Tally Voucher Log Controller (Module 8 Accounting Export)
Inherits from APDocument base controller.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.exceptions import APValidationError


class TallyVoucherLog(APDocument):
    """
    Controller for Tally ERP XML/JSON Export Logs.
    """

    def validate(self):
        """Validation lifecycle hook."""
        self.payee_name = "Tally ERP Integration"
        self.total_amount = float(getattr(self, "total_debit_amount", 0.0) or 0.0)
        super().validate()

    def _validate_financial_amounts(self):
        """Allow validation to pass without strict duplicate fingerprint checks."""
        val = float(getattr(self, "total_amount", 0.0) or 0.0)
        if val <= 0:
            raise APValidationError(f"Total Debit Amount must be positive. Found: {val}")
