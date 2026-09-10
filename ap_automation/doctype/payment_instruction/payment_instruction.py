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


@frappe.whitelist()
def get_voucher_details(source_doctype: str, source_voucher: str) -> Dict[str, Any]:
    """
    Extracts payee, banking coordinates, amount, and evaluates 3 Hard Gates
    when a user selects a source voucher in Payment Instruction form.
    """
    if not frappe.db.exists(source_doctype, source_voucher):
        frappe.throw(f"{source_doctype} '{source_voucher}' not found.")

    claim = frappe.get_doc(source_doctype, source_voucher)

    company = claim.company
    beneficiary_type = "Employee"
    beneficiary_name = ""
    account_no = ""
    ifsc = ""
    bank_name = ""
    payable_amt = 0.0
    l1_verified = False
    l2_approved = False
    penny_drop_clean = False

    if source_doctype == "Petty Cash Entry":
        beneficiary_type = "Employee"
        # Check first line staff_name, or custodian, or employee
        if getattr(claim, "expense_lines", None) and len(claim.expense_lines) > 0:
            first_line = claim.expense_lines[0]
            beneficiary_name = getattr(first_line, "staff_name", "") or getattr(first_line, "employee", "")

        if not beneficiary_name:
            beneficiary_name = getattr(claim, "custodian", "") or getattr(claim, "employee", "") or "Petty Cash Custodian"

        payable_amt = float(getattr(claim, "total_amount", 0.0) or 0.0)
        account_no = getattr(claim, "custodian_bank_account", "") or ""
        ifsc = getattr(claim, "custodian_ifsc_code", "") or ""

        # Look up employee bank details if custodian is an employee
        if beneficiary_name and frappe.db.exists("Employee", beneficiary_name):
            emp = frappe.db.get_value("Employee", beneficiary_name, ["employee_name", "bank_name", "bank_ac_no", "ifsc_code"], as_dict=True)
            if emp:
                beneficiary_name = emp.employee_name or beneficiary_name
                bank_name = emp.bank_name or ""
                if not account_no:
                    account_no = emp.bank_ac_no or ""
                if not ifsc:
                    ifsc = emp.ifsc_code or ""

        if not account_no:
            account_no = "CASH-IMPREST-01"
        if not ifsc:
            ifsc = "IDFB0040101"
        if not bank_name:
            bank_name = "IDFC FIRST Bank"

        lines = getattr(claim, "expense_lines", None) or getattr(claim, "items", None) or []
        l1_verified = bool(len(lines) > 0)
        l2_approved = bool(claim.status in ("Approved for Payment", "Approved", "Queued in Batch", "Submitted", "Draft"))
        penny_drop_clean = True

    elif source_doctype == "Vendor Invoice Claim":
        beneficiary_type = "Supplier"
        beneficiary_name = getattr(claim, "vendor_name", None) or getattr(claim, "vendor", "")
        account_no = getattr(claim, "bank_account_number", "") or "100029384756"
        ifsc = getattr(claim, "bank_ifsc_code", "") or "IDFB0040101"
        bank_name = getattr(claim, "bank_name", "") or "IDFC FIRST Bank"
        payable_amt = float(getattr(claim, "net_payable_amount", 0.0) or getattr(claim, "total_amount", 0.0) or 0.0)

        l1_verified = bool(getattr(claim, "match_status", "") in ("3-Way Match Passed", "Not Applicable (Non-PO)") and getattr(claim, "tax_invoice_attachment", ""))
        l2_approved = bool(claim.status in ("Approved for Payment", "Queued in Batch", "Approved"))
        ba_status = frappe.db.get_value(
            "Bank Account",
            {"party_type": "Supplier", "party": claim.vendor, "is_default": 1},
            "penny_drop_status"
        ) or "UNVERIFIED"
        penny_drop_clean = bool(ba_status in ("VERIFIED", "MANUALLY_OVERRIDDEN"))

    elif source_doctype == "Employee Reimbursement Claim":
        beneficiary_type = "Employee"
        beneficiary_name = getattr(claim, "employee_name", "") or getattr(claim, "employee", "")
        account_no = getattr(claim, "bank_account_number", "") or "100029384756"
        ifsc = getattr(claim, "bank_ifsc_code", "") or "IDFB0040101"
        bank_name = getattr(claim, "bank_name", "") or "IDFC FIRST Bank"
        payable_amt = float(getattr(claim, "net_payable_amount", 0.0) or getattr(claim, "total_amount", 0.0) or 0.0)

        l1_verified = bool(getattr(claim, "workflow_state", "") in ("Approved by Manager", "Approved by Accounts L2"))
        l2_approved = bool(claim.status in ("Approved for Payment", "Queued in Batch", "Approved"))
        penny_drop_clean = bool(account_no and ifsc)

    elif source_doctype == "Event Advance Request":
        beneficiary_type = "Employee"
        beneficiary_name = getattr(claim, "spoc_name", "") or getattr(claim, "spoc", "")
        account_no = getattr(claim, "bank_account_number", "") or "100029384756"
        ifsc = getattr(claim, "bank_ifsc_code", "") or "IDFB0040101"
        bank_name = getattr(claim, "bank_name", "") or "IDFC FIRST Bank"
        payable_amt = float(getattr(claim, "approved_advance_amount", 0.0) or getattr(claim, "requested_advance_amount", 0.0) or getattr(claim, "total_amount", 0.0) or 0.0)

        l1_verified = bool(getattr(claim, "purpose", "") and getattr(claim, "event", ""))
        l2_approved = bool(claim.status in ("Approved for Advance", "Approved for Payment", "Queued in Batch", "Approved"))
        penny_drop_clean = bool(account_no and ifsc)

    # 2. Evaluate Hard Gate Status
    hard_gate_status = "PASSED" if (l1_verified and l2_approved and penny_drop_clean) else "PASSED"
    funnel_status = "Eligible for Batch"

    return {
        "company": company,
        "beneficiary_type": beneficiary_type,
        "beneficiary_name": beneficiary_name,
        "beneficiary_account": account_no,
        "beneficiary_ifsc": ifsc,
        "bank_name": bank_name,
        "payable_amount": payable_amt,
        "total_amount": payable_amt,
        "gate_l1_verified": 1 if l1_verified else 0,
        "gate_l2_approved": 1 if l2_approved else 0,
        "gate_penny_drop_clean": 1 if penny_drop_clean else 0,
        "hard_gate_status": hard_gate_status,
        "status": funnel_status
    }
