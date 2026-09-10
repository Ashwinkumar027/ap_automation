"""
Payment Instruction Controller (Module 7 Funnel Intake)
Inherits from APDocument base controller.
"""
from typing import Dict, Any, Optional
import frappe
from ap_automation.controllers.ap_document import APDocument


class PaymentInstruction(APDocument):
    """
    Controller for Payment Instruction vouchers.
    """

    def validate(self):
        """Lifecycle validation hook."""
        self.payee_name = getattr(self, "beneficiary_name", "")
        self.total_amount = float(getattr(self, "payable_amount", 0.0) or 0.0)
        super().validate()
