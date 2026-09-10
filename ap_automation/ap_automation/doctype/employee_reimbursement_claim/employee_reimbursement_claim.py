"""
Employee Reimbursement Claim Controller (Lane 2 Intake, Autonomous Routing & Spend Shield)
Inherits from APDocument base controller.
Enforces:
1. Immutable HRMS company locking.
2. Zero-typing salary bank account auto-fetch.
3. Mandatory receipt attachment on every single line item (Zero exceptions).
4. Statutory B2B GSTIN regex validation.
5. Automatic advance offset: Net = Total - Advance.
6. Autonomous HRMS Leave Delegation and Self-Approval Conflict Shield.
7. Line-Item Group-Wide Duplicate Spend Fingerprinting (Cross-Lane & Cross-Company).
"""
import re
from typing import Dict, Any, List
import frappe
from ap_automation.controllers.ap_document import APDocument
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.leave_delegation_service import resolve_claim_approver
from ap_automation.services.duplicate_engine import (
    calculate_invoice_fingerprint,
    register_spend_fingerprint,
    release_spend_fingerprint
)

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


class EmployeeReimbursementClaim(APDocument):
    """
    Employee Reimbursement Claim controller.
    Ensures zero fraud, statutory GST compliance, and autonomous HRMS leave routing.
    """

    def validate(self):
        """Lifecycle hook executed on document save."""
        self.bind_and_lock_hrms_profile()
        self.validate_salary_bank_account()
        self.validate_expense_lines()
        self.calculate_settlement_totals()

        # Map payee fields for APDocument base spend hash and banking dispatch
        self.payee_name = getattr(self, "employee_name", "") or getattr(self, "employee", "")
        self.bank_account_number = getattr(self, "bank_account_number", "")
        self.bank_ifsc_code = getattr(self, "bank_ifsc_code", "")
        self.total_amount = self.net_payable_amount

        # Execute parent base validations (duplicate hash, immutability, tamper guard)
        super().validate()

    def before_submit(self):
        """Hook executed when employee clicks Submit Claim."""
        routing = resolve_claim_approver(
            employee_id=self.employee,
            claim_amount=self.total_claim_amount,
            check_date=self.posting_date
        )

        self.designated_approver = routing["assigned_approver"]
        self.status = "Pending Manager Approval"
        self.workflow_state = "Pending Manager Approval"
        self.current_approval_level = 1

        self.append("approval_trail", {
            "level_number": 1,
            "level_name": "Claim Submission & Routing",
            "designated_approver": routing["assigned_approver"],
            "action_taken_by": frappe.session.user,
            "action": "APPROVED",
            "action_timestamp": frappe.utils.now_datetime(),
            "remarks": routing["routing_reason"]
        })

    def on_submit(self):
        """Registers line-level spend fingerprints upon submission."""
        super().on_submit()
        self._register_line_spend_fingerprints()

    def on_cancel(self):
        """Releases line-level spend fingerprints if claim is cancelled."""
        super().on_cancel()
        self._release_line_spend_fingerprints()

    def bind_and_lock_hrms_profile(self):
        """Pulls employee company and profile directly from HRMS."""
        emp_id = getattr(self, "employee", None)
        if not emp_id:
            raise APValidationError("Employee ID is mandatory to file a reimbursement claim.")

        emp = frappe.db.get_value(
            "Employee",
            emp_id,
            ["employee_name", "company", "department", "status", "bank_name", "bank_ac_no", "ifsc_code"],
            as_dict=True
        )
        if not emp:
            raise APValidationError(f"Employee record '{emp_id}' not found in HRMS database.")

        if emp.status and emp.status != "Active":
            raise APSecurityError(f"Inactive or Relieved Employee '{emp_id}' cannot file reimbursement claims.")

        if getattr(self, "company", None) and self.company != emp.company:
            raise APSecurityError(
                f"Security Violation: You cannot file a claim under '{self.company}'. "
                f"Your profile is strictly locked to HRMS entity '{emp.company}'."
            )

        self.company = emp.company
        self.employee_name = emp.employee_name
        self.department = emp.department

        if not self.bank_account_number and emp.bank_ac_no:
            self.bank_account_number = emp.bank_ac_no
            self.bank_name = emp.bank_name
            self.bank_ifsc_code = emp.ifsc_code

    def validate_salary_bank_account(self):
        """Ensures verified bank account exists in HRMS before allowing submission."""
        if not getattr(self, "bank_account_number", None) or not getattr(self, "bank_ifsc_code", None):
            raise APValidationError(
                "Banking Details Missing: Your salary bank account or IFSC code is not configured in HRMS. "
                "Please contact HR to update your bank master before submitting claims."
            )

    def validate_expense_lines(self):
        """Enforces line-level policy rules with progressive Draft validation."""
        lines = getattr(self, "expense_lines", []) or []
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        
        if not lines:
            if not is_submitting:
                return
            raise APValidationError("Employee Reimbursement Claim must contain at least one expense line item.")

        for idx, row in enumerate(lines, start=1):
            if not getattr(row, "expense_date", None):
                row.expense_date = self.posting_date or frappe.utils.nowdate()

            merchant = (getattr(row, "merchant_name", "") or "").strip()
            if not merchant:
                if is_submitting:
                    raise APValidationError(f"Row {idx}: Merchant / Service Provider is mandatory.")
                else:
                    row.merchant_name = "General Expense"

            amt = float(getattr(row, "amount", 0.0) or getattr(row, "claim_amount", 0.0) or 0.0)
            if is_submitting and amt <= 0:
                raise APValidationError(f"Row {idx}: Amount must be positive (Found: {amt}).")

            if is_submitting and not getattr(row, "receipt_attachment", None):
                raise APValidationError(
                    f"Row {idx} ({merchant} - INR {amt:,.2f}): "
                    "Bill / Tax Receipt attachment is strictly mandatory for every reimbursement line upon submission."
                )

            if getattr(row, "is_b2b", 0):
                gstin = (getattr(row, "merchant_gstin", "") or "").strip().upper()
                if not gstin:
                    raise APValidationError(f"Row {idx}: Merchant GSTIN is mandatory when 'B2B Tax Invoice' is checked.")
                if not GSTIN_REGEX.match(gstin):
                    raise APValidationError(
                        f"Row {idx}: Invalid Merchant GSTIN '{gstin}'. "
                        "Must adhere to 15-character statutory format (e.g. 29AAAAA0000A1Z5)."
                    )
                row.merchant_gstin = gstin

            # Group-Wide & Cross-Lane Duplicate Spend Detection on Row Level
            inv = (getattr(row, "invoice_number", "") or "").strip()
            if merchant and inv and amt > 0:
                inv_hash = calculate_invoice_fingerprint(merchant, inv, amt)
                collisions = frappe.get_all(
                    "AP Spend Fingerprint",
                    filters={
                        "fingerprint_hash": inv_hash,
                        "tier": "EXACT_INVOICE",
                        "status": "ACTIVE"
                    },
                    fields=["document_type", "document_name", "company", "invoice_number", "amount"],
                    limit=1
                )
                for c in collisions:
                    if c["document_name"] != getattr(self, "name", None):
                        raise APValidationError(
                            f"🚨 FRAUD SHIELD ALERT: Cross-Lane Duplicate Spend Detected on Row {idx}! "
                            f"Invoice '{c['invoice_number']}' for INR {c['amount']:,.2f} at '{merchant}' "
                            f"has already been claimed in Company '{c['company']}' (Voucher: {c['document_type']} #{c['document_name']}). "
                            f"Duplicate claims across sister companies and expense lanes are strictly blocked."
                        )

    def calculate_settlement_totals(self):
        """Calculates total spend, advance offset, and net payable amount."""
        lines = getattr(self, "expense_lines", []) or []
        total_spend = sum(float(getattr(r, "amount", 0.0) or 0.0) for r in lines)
        advance = float(getattr(self, "advance_amount", 0.0) or 0.0)

        if advance < 0:
            raise APValidationError("Advance Offset cannot be negative.")

        self.total_claim_amount = round(total_spend, 2)
        self.net_payable_amount = round(max(total_spend - advance, 0.0), 2)

    def _register_line_spend_fingerprints(self):
        """Registers line items into AP Spend Fingerprint ledger."""
        for row in (self.expense_lines or []):
            merchant = getattr(row, "merchant_name", "")
            inv = getattr(row, "invoice_number", "")
            amt = float(getattr(row, "amount", 0.0) or 0.0)
            if merchant and inv and amt > 0:
                inv_hash = calculate_invoice_fingerprint(merchant, inv, amt)
                if not frappe.db.exists("AP Spend Fingerprint", {"fingerprint_hash": inv_hash, "tier": "EXACT_INVOICE"}):
                    frappe.get_doc({
                        "doctype": "AP Spend Fingerprint",
                        "fingerprint_hash": inv_hash,
                        "tier": "EXACT_INVOICE",
                        "company": self.company,
                        "document_type": self.doctype,
                        "document_name": self.name,
                        "payee_name": merchant,
                        "invoice_number": inv,
                        "amount": amt,
                        "status": "ACTIVE"
                    }).insert(ignore_permissions=True)

    def _release_line_spend_fingerprints(self):
        """Releases line item fingerprints if document is cancelled."""
        frappe.db.sql(
            "UPDATE `tabAP Spend Fingerprint` SET status = 'RELEASED' WHERE document_name = %s AND document_type = %s",
            (self.name, self.doctype)
        )
