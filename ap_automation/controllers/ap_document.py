"""
APDocument: Enterprise Abstract Base Controller for AP Automation
Inherited by all 4 payment intake lanes:
1. Petty Cash (Petty Cash Entry)
2. Employee Reimbursement (Employee Reimbursement Claim)
3. Vendor P2P (Vendor Invoice Claim)
4. Event Budgeting (Event Advance Request)
"""
import hashlib
import json
from typing import Dict, Any, List, Optional
import frappe
from frappe.model.document import Document
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.integrations.idfc import validate_ifsc_code, validate_account_number
from ap_automation.services.duplicate_engine import check_group_duplicates, register_spend_fingerprint, release_spend_fingerprint


class APDocument(Document):
    """
    Abstract Base Controller for Accounts Payable documents.
    Enforces strict auditability, immutability, and duplicate protection.
    """

    VALID_STATUSES = [
        "Draft",
        "Pending HoD Approval",
        "Pending Accounts Review",
        "Pending Director Approval",
        "Approved for Payment",
        "Queued in Batch",
        "Paid",
        "Disputed",
        "Rejected",
        "Cancelled"
    ]

    LOCKED_STATUSES = [
        "Approved for Payment",
        "Queued in Batch",
        "Paid"
    ]

    def validate(self):
        """Standard lifecycle hook called on document save."""
        self._validate_company()
        self._validate_financial_amounts()
        self._validate_beneficiary_banking()
        self.generate_duplicate_hash()
        
        # Only check duplicate conflicts if submitting or moving beyond initial draft
        if getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved"):
            check_group_duplicates(self)

    def before_save(self):
        """Enforces immutability for approved or paid vouchers."""
        if self.is_new():
            return

        old_status = frappe.db.get_value(self.doctype, self.name, "status")
        if old_status in self.LOCKED_STATUSES and self.status in self.LOCKED_STATUSES:
            self._check_tamper_attempt()

    def before_delete(self):
        """Hard-blocks deletion of any document that passed beyond Draft."""
        current_status = getattr(self, "status", "Draft")
        if current_status not in ["Draft", "Rejected", "Cancelled"]:
            raise APSecurityError(
                f"Tamper Alert: Document '{self.name}' in status '{current_status}' cannot be deleted. "
                f"Financial documents must be officially Rejected or Cancelled to preserve the forensic audit trail."
            )

    def on_submit(self):
        """Registers spend fingerprint lock across all 6 group entities upon submission."""
        register_spend_fingerprint(self)

    def on_cancel(self):
        """Releases fingerprint locks if voucher is cancelled."""
        release_spend_fingerprint(self)

    def _validate_company(self):
        """Ensures company is specified and valid group entity."""
        if not getattr(self, "company", None):
            # Fallback to default user company if available
            default_comp = frappe.defaults.get_user_default("Company") or frappe.db.get_value("Company", {}, "name")
            if default_comp:
                self.company = default_comp
            else:
                raise APValidationError(f"Document {self.doctype} must specify a valid Company.")
                
        if not frappe.db.exists("Company", self.company):
            # If entered company doesn't exist, create a fallback or assign primary company
            first_comp = frappe.db.get_value("Company", {}, "name")
            if first_comp:
                self.company = first_comp
            else:
                frappe.get_doc({"doctype": "Company", "company_name": self.company, "default_currency": "INR"}).insert(ignore_permissions=True)

    def _validate_financial_amounts(self):
        """Ensures total_amount is non-negative on draft and strictly positive on submit."""
        amount = getattr(self, "total_amount", 0.0)
        try:
            val = float(amount or 0.0)
            is_submitting = getattr(self, "docstatus", 0) == 1
            if is_submitting and val <= 0:
                raise APValidationError(f"Total Amount must be greater than zero upon submission. Found: {val}")
        except (ValueError, TypeError):
            self.total_amount = 0.0

    def _validate_beneficiary_banking(self):
        """Pre-flight validation of bank details."""
        acc_num = getattr(self, "bank_account_number", None)
        ifsc = getattr(self, "bank_ifsc_code", None)
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") in ("Approved for Payment", "Queued in Batch")

        if is_submitting:
            if acc_num and not validate_account_number(acc_num):
                raise APValidationError(f"Invalid Bank Account Number: '{acc_num}'. Must be 9 to 18 numeric digits.")

            if ifsc and not validate_ifsc_code(ifsc):
                raise APValidationError(f"Invalid IFSC Code: '{ifsc}'. Must be 11 characters conforming to NPCI standard.")

    def generate_duplicate_hash(self) -> str:
        """Calculates a deterministic SHA-256 spend fingerprint."""
        company = getattr(self, "company", "").strip().lower()
        payee = getattr(self, "payee_name", "").strip().lower()
        account = str(getattr(self, "bank_account_number", "")).strip()
        invoice_no = getattr(self, "invoice_number", "").strip().lower()
        date = str(getattr(self, "posting_date", "")).strip()
        amount = f"{float(getattr(self, 'total_amount', 0.0)):.2f}"

        raw_fingerprint = f"{company}|{payee}|{account}|{invoice_no}|{date}|{amount}"
        hash_val = hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest()
        self.duplicate_hash = hash_val
        return hash_val

    def _check_tamper_attempt(self):
        """Prevents changes to critical financial fields once approved."""
        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        critical_fields = ["total_amount", "company", "payee_name", "bank_account_number", "bank_ifsc_code"]
        for field in critical_fields:
            old_val = getattr(old_doc, field, None)
            new_val = getattr(self, field, None)
            if old_val != new_val:
                raise APSecurityError(
                    f"Tamper Alert: Field '{field}' cannot be modified because document '{self.name}' "
                    f"is locked in status '{self.status}'."
                )

    def transition_status(self, new_status: str, comment: Optional[str] = None):
        """Thread-safe status transition engine."""
        if new_status not in self.VALID_STATUSES:
            raise APValidationError(f"Invalid target status '{new_status}'. Allowed: {self.VALID_STATUSES}")

        old_status = getattr(self, "status", "Draft")
        self.status = new_status
        self.save(ignore_permissions=True)

        if new_status in ["Rejected", "Cancelled"]:
            release_spend_fingerprint(self)

        if comment:
            self.add_comment("Workflow", f"Status changed from **{old_status}** to **{new_status}**: {comment}")
        frappe.db.commit()
