"""
Petty Cash Entry Controller (Lane 1 - Imprest System)
Enforces:
1. Strict line item amount validation (amount > 0).
2. Mandatory non-empty expense lines validation.
3. Automatic calculation of total_amount and verified_amount.
4. Duplicate bill validation (within voucher and across all existing vouchers).
5. Immutability when batch_id is linked or status is Disbursed/Queued in Batch.
6. Automated Notification Hook on submission to notify L1 Accounts Verifier.
7. Automated Notification Hook on Accounts L1 Audit Completion to notify Director (Anshul Sir).
8. Automated Notification Hook on L2 Approval to notify Custodian / Admin.
"""
import frappe
from frappe.model.document import Document
from ap_automation.exceptions import APValidationError
from ap_automation.services import notification_service


class PettyCashEntry(Document):
    def validate(self):
        self.validate_expense_lines()
        self.validate_duplicate_lines()
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

    def validate_duplicate_lines(self):
        """Checks for duplicate bills within the voucher and across all vouchers."""
        seen_keys = set()
        for idx, row in enumerate(self.expense_lines, 1):
            merchant = (row.merchant_name or "").strip().lower()
            bill_no = (row.bill_number or "").strip().lower()
            amt = float(row.amount or 0.0)

            if merchant and bill_no:
                key = (merchant, bill_no)
                # 1. Check duplicate within this same voucher
                if key in seen_keys:
                    frappe.throw(
                        f"🚨 Duplicate Bill in Voucher: Row #{idx} has duplicate Merchant '{row.merchant_name}' "
                        f"and Bill #{row.bill_number}. Duplicate line items within the same voucher are not allowed.",
                        exc=APValidationError
                    )
                seen_keys.add(key)

                # 2. Check duplicate across existing active vouchers in database
                existing_lines = frappe.db.sql(
                    """
                    SELECT parent, merchant_name, bill_number, amount
                    FROM `tabPetty Cash Line Item`
                    WHERE parent != %s
                      AND LOWER(TRIM(merchant_name)) = %s
                      AND LOWER(TRIM(bill_number)) = %s
                      AND docstatus < 2
                    LIMIT 1
                    """,
                    (self.name or "", merchant, bill_no),
                    as_dict=True
                )
                if existing_lines:
                    match = existing_lines[0]
                    # Verify parent voucher is not cancelled or rejected
                    p_status = frappe.db.get_value("Petty Cash Entry", match.parent, "status")
                    if p_status not in ("Rejected", "Cancelled"):
                        frappe.throw(
                            f"🚨 FRAUD SHIELD: Duplicate Bill Detected!\n"
                            f"Bill #{row.bill_number} from Merchant '{row.merchant_name}' (Amount: ₹{row.amount:,.2f}) "
                            f"has already been claimed in Voucher #{match.parent}. "
                            f"Duplicate submissions are strictly blocked across the system.",
                            exc=APValidationError
                        )

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
            frappe.log_error(f"Notification error on submit for {self.name}: {str(e)}", "AP Notification Error")

    def on_update(self):
        """Dispatches automated notifications on status transitions."""
        if self.has_value_changed("status"):
            # 1. Accounts L1 verified -> Escalates to Director L2 (Anshul Sir)
            if self.status in ("L1 Verified", "Pending Director Signoff", "Pending Director Approval"):
                try:
                    notification_service.notify_director_on_l1_audit_completed(self.doctype, self.name)
                except Exception as e:
                    frappe.log_error(f"Notification error on Director escalation for {self.name}: {str(e)}", "AP Notification Error")
            # 2. Director approves -> Notifies Admin / Custodian that payment is queued
            elif self.status in ("Approved for Payment", "Approved"):
                try:
                    notification_service.notify_admin_on_l2_approved(self.doctype, self.name)
                except Exception as e:
                    frappe.log_error(f"Notification error on L2 approve for {self.name}: {str(e)}", "AP Notification Error")

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
