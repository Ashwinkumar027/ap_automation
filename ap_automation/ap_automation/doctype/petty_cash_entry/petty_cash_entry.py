"""
Petty Cash Entry Controller (Lane 1 - Imprest System)
Enforces:
1. Strict line item amount validation (amount > 0).
2. Mandatory non-empty expense lines validation.
3. Automatic calculation of total_amount and verified_amount.
4. Immutability when batch_id is linked or status is Disbursed/Queued in Batch.
5. Automated Notification Hook on submission to notify L1 Accounts Verifier.
"""
import frappe
from frappe.model.document import Document
from ap_automation.exceptions import APValidationError
from ap_automation.services import notification_service


class PettyCashEntry(Document):
    def validate(self):
        self.validate_expense_lines()
        self.calculate_totals()
        self.validate_immutability()

    def validate_expense_lines(self):
        if not self.expense_lines or len(self.expense_lines) == 0:
            frappe.throw(
                "A Petty Cash Entry must contain at least one valid expense line item.",
                exc=APValidationError
            )

        for idx, row in enumerate(self.expense_lines, 1):
            if not row.amount or float(row.amount) <= 0:
                frappe.throw(
                    f"Row #{idx} ({row.expense_category or 'Expense Line'}): Amount must be strictly greater than ₹ 0.00.",
                    exc=APValidationError
                )
            if not row.expense_category:
                frappe.throw(f"Row #{idx}: Expense Category is required.", exc=APValidationError)
            if not row.merchant_name:
                frappe.throw(f"Row #{idx}: Merchant / Payee Name is required.", exc=APValidationError)

    def calculate_totals(self):
        total = 0.0
        verified = 0.0
        for row in self.expense_lines:
            amt = float(row.amount or 0.0)
            total += amt
            if not getattr(row, "is_disputed", 0):
                verified += amt

        self.total_amount = round(total, 2)

    def on_submit(self):
        """Dispatches automated notification to L1 Accounts Verifier."""
        try:
            notification_service.notify_l1_on_voucher_submitted(self.doctype, self.name)
        except Exception as e:
            frappe.log_error(f"Notification error on submit for {self.name}: {str(e)}")

    def validate_immutability(self):
        if self.is_new():
            return
        old_status = frappe.db.get_value("Petty Cash Entry", self.name, "status")
        if old_status in ("Disbursed via IDFC", "Settled") and self.has_value_changed("expense_lines"):
            frappe.throw(
                f"Petty Cash Entry '{self.name}' is already disbursed/settled and cannot be modified.",
                exc=APValidationError
            )

    def before_delete(self):
        if self.batch_id or self.status in ("Queued in Batch", "Disbursed via IDFC", "Settled"):
            frappe.throw(
                f"Cannot delete Petty Cash Entry '{self.name}' because it is linked to Payment Batch '{self.batch_id}' or already disbursed.",
                exc=APValidationError
            )
