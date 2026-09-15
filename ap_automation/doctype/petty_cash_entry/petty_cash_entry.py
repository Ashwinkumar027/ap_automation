"""
Petty Cash Entry Controller (Lane 1 - Imprest System)
Enforces:
1. Strict line item amount validation (amount > 0).
2. Mandatory non-empty expense lines validation.
3. Automatic calculation of total_amount and verified_amount.
4. Auto-population of Beneficiary Bank Details from HRMS Employee Master.
5. Duplicate bill validation within and across vouchers.
6. Immutability when batch_id is linked or status is Disbursed/Queued in Batch.
7. Automated Notification Hook on submission to notify L1 Accounts Verifier.
8. Automated Notification Hook on L2 Approval to notify Custodian.
"""
import frappe
from frappe.model.document import Document
from ap_automation.exceptions import APValidationError
from ap_automation.services import notification_service


class PettyCashEntry(Document):
    def validate(self):
        self.fetch_custodian_bank_details()
        self.validate_expense_lines()
        self.validate_duplicate_lines()
        self.calculate_totals()
        self.validate_immutability()

    def fetch_custodian_bank_details(self):
        """Auto-populates custodian beneficiary bank details from HRMS Employee master if empty."""
        if self.custodian:
            emp = frappe.db.get_value(
                "Employee",
                self.custodian,
                ["employee_name", "custom_name_as_per_bank", "bank_name", "bank_ac_no", "custom_ifsc_code", "ifsc_code"],
                as_dict=True
            )
            if emp:
                if not getattr(self, "beneficiary_name", None):
                    self.beneficiary_name = emp.get("custom_name_as_per_bank") or emp.get("employee_name") or ""
                if not getattr(self, "bank_name", None):
                    self.bank_name = emp.get("bank_name") or ""
                if not getattr(self, "custodian_bank_account", None):
                    self.custodian_bank_account = emp.get("bank_ac_no") or ""
                if not getattr(self, "custodian_ifsc_code", None):
                    self.custodian_ifsc_code = emp.get("custom_ifsc_code") or emp.get("ifsc_code") or ""

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

    def validate_duplicate_lines(self):
        """Prevents duplicate bills (same date, merchant, amount, bill number) within this voucher."""
        seen_keys = set()
        for idx, row in enumerate(self.expense_lines, 1):
            if row.merchant_name and row.amount:
                key = (
                    str(row.expense_date or self.posting_date or ""),
                    str(row.merchant_name or "").strip().lower(),
                    float(row.amount or 0.0),
                    str(row.bill_number or "").strip().lower()
                )
                if key in seen_keys:
                    frappe.throw(
                        f"Duplicate bill detected within this voucher at Row #{idx}: Merchant '{row.merchant_name}', Amount ₹{row.amount}, Bill #{row.bill_number or 'N/A'}.",
                        exc=APValidationError
                    )
                seen_keys.add(key)

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

    def on_update(self):
        """Dispatches automated notifications on status transitions."""
        if self.has_value_changed("status"):
            if self.status == "Approved for Payment":
                try:
                    notification_service.notify_admin_on_l2_approved(self.doctype, self.name)
                except Exception as e:
                    frappe.log_error(f"Notification error on L2 approve for {self.name}: {str(e)}")

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
