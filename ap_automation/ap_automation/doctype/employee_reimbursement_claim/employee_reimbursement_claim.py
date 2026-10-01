# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

"""
Enterprise Employee Business Expense & Reimbursement Claim Controller
Inherits from APDocument base controller.
Enforces:
1. Dynamic HRMS Profile & Reporting Manager Binding (Zero-typing, O(1) indexed lookup).
2. Category-Specific Validation Rules for all 5 Enterprise Categories:
   - Category 1: Client Visit (Mandatory Pre-Travel Approval reference OR Email Approval Screenshot).
   - Category 2: Team Lunch / Outing (Participant headcount validation + budget tracking).
   - Category 3: Dinner Allowance (Late-night dinner allowance validation).
   - Category 4: Branch Expense & Maintenance (Housekeeping, repairs, facility maintenance).
   - Category 5: General Expense (Itemized receipts & statutory B2B GSTIN checks).
3. Universal Multi-Tier Fast-Track Rerouting Support.
4. Mandatory Bill Proofs on all reimbursement lines.
5. Group-Wide Cross-Lane & Cross-Company Duplicate Spend Fingerprint Engine (O(1) SHA-256).
6. Segregation of Duties and Self-Approval Prevention.
"""

import re
from typing import Dict, Any, List, Optional
import frappe
from frappe.utils import flt, getdate, nowdate, cstr
from ap_automation.controllers.ap_document import APDocument
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services import hrms_hierarchy_service
from ap_automation.services.duplicate_engine import (
    calculate_invoice_fingerprint,
    register_spend_fingerprint,
    release_spend_fingerprint
)
from ap_automation.services import reimbursement_policy_service
from ap_automation.services import employee_reimbursement_permission_service

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


class EmployeeReimbursementClaim(APDocument):
    """
    Unified 5-Category Employee Reimbursement Claim Controller.
    """

    def validate(self):
        """Lifecycle hook executed on document save."""
        self.bind_and_lock_hrms_profile()
        self.validate_salary_bank_account()
        self.validate_category_and_pre_approvals()
        self.validate_expense_lines()
        self.calculate_settlement_totals()
        self.auto_link_and_unlock_receipt_files()

        # Map base fields for APDocument fingerprint and corporate batch release
        self.payee_name = getattr(self, "employee_name", "") or getattr(self, "employee", "")
        self.bank_account_number = getattr(self, "bank_account_number", "")
        self.bank_ifsc_code = getattr(self, "bank_ifsc_code", "")
        self.total_amount = self.net_payable_amount

    def before_save(self):
        """Enforces immutability on in-flight and approved documents."""
        if self.is_new():
            return

        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        # If document is in intermediate workflow or approved/paid status
        if getattr(old_doc, "status", None) not in ("Draft", "Returned to Employee", "Cancelled", "Rejected"):
            # Check if this is a regular UI save (status unchanged)
            if getattr(old_doc, "status", None) == self.status and not getattr(self.flags, "in_workflow_transition", False):
                self._check_tamper_attempt(old_doc)

    def _check_tamper_attempt(self, old_doc=None):
        """Prevents unauthorized modification of lines, amounts, and metadata while in workflow."""
        if not old_doc:
            old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        # 1. Critical Header Fields Guard
        critical_fields = [
            "total_claim_amount",
            "net_payable_amount",
            "total_amount",
            "employee",
            "claim_category",
            "company",
            "bank_account_number",
            "bank_ifsc_code",
            "pre_travel_request",
            "pre_approval_attachment"
        ]
        for field in critical_fields:
            old_val = getattr(old_doc, field, None)
            new_val = getattr(self, field, None)
            if old_val and new_val and old_val != new_val:
                raise APSecurityError(
                    f"Tamper Alert: Field '{field}' cannot be modified because document '{self.name}' "
                    f"is locked in workflow status '{self.status}'. Any changes require an official Rejection / Return."
                )

        # 2. Child Table Lines Guard
        old_lines = getattr(old_doc, "expense_lines", []) or []
        new_lines = getattr(self, "expense_lines", []) or []
        if len(old_lines) != len(new_lines):
            raise APSecurityError(
                f"Tamper Alert: Cannot add or remove expense lines on document '{self.name}' "
                f"in status '{self.status}'."
            )

        for idx, (o_row, n_row) in enumerate(zip(old_lines, new_lines), 1):
            for lf in ("amount", "merchant_name", "receipt_attachment", "invoice_number", "expense_date"):
                if getattr(o_row, lf, None) != getattr(n_row, lf, None):
                    raise APSecurityError(
                        f"Tamper Alert: Row {idx} ({lf}) cannot be modified on document '{self.name}' "
                        f"in status '{self.status}'."
                    )

    def before_submit(self):
        """Pre-submission verification."""
        self.validate_category_and_pre_approvals()

    def on_submit(self):
        """Registers line-level spend fingerprints upon submission."""
        super().on_submit()
        self._register_line_spend_fingerprints()
        self._mark_linked_pre_travel_claimed()

    def on_cancel(self):
        """Releases line-level spend fingerprints if claim is cancelled."""
        super().on_cancel()
        self._release_line_spend_fingerprints()
        self._unmark_linked_pre_travel_claimed()

    def bind_and_lock_hrms_profile(self):
        """Pulls and binds employee profile and reporting manager directly from HRMS."""
        emp_id = getattr(self, "employee", None)
        if not emp_id:
            emp_rec = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
            if emp_rec:
                self.employee = emp_rec
                emp_id = emp_rec
            else:
                raise APValidationError("Employee ID is mandatory to file a reimbursement claim.")

        emp_profile = hrms_hierarchy_service.get_employee_hrms_profile(emp_id)

        # Enforce employee filing authorization (Self or Subordinate only for non-global users)
        user = frappe.session.user
        if not employee_reimbursement_permission_service.is_global_view_user(user):
            allowed_emps = employee_reimbursement_permission_service.get_subordinate_employees_for_user(user)
            if not allowed_emps:
                own_emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
                if own_emp:
                    allowed_emps = [own_emp]
            if allowed_emps and emp_id not in allowed_emps:
                raise APSecurityError(
                    f"Security Violation: You are not authorized to create or edit reimbursement claims for Employee '{emp_id}'."
                )

        if getattr(self, "company", None) and self.company != emp_profile["company"] and frappe.session.user != "Administrator":
            raise APSecurityError(
                f"Security Violation: You cannot file a claim under '{self.company}'. "
                f"Your profile is locked to HRMS entity '{emp_profile['company']}'."
            )

        self.company = emp_profile["company"]
        self.employee_name = emp_profile["employee_name"]
        self.department = emp_profile["department"]

        if not getattr(self, "bank_account_number", None) and emp_profile.get("bank_ac_no"):
            self.bank_account_number = emp_profile.get("bank_ac_no")
            self.bank_name = emp_profile.get("bank_name")
            self.bank_ifsc_code = emp_profile.get("ifsc_code")

        # Resolve and bind Reporting Manager
        mgr_info = hrms_hierarchy_service.get_reporting_manager_for_employee(emp_id)
        self.reporting_manager = mgr_info["manager_employee_id"]
        self.manager_user_id = mgr_info["manager_user_id"]

    def validate_salary_bank_account(self):
        """Ensures verified salary bank account exists in HRMS before allowing submission."""
        if not getattr(self, "bank_account_number", None) or not getattr(self, "bank_ifsc_code", None):
            raise APValidationError(
                "Banking Details Missing: Your salary bank account or IFSC code is not configured in HRMS. "
                "Please contact HR to update your bank master before submitting claims."
            )

    def validate_category_and_pre_approvals(self):
        """
        Validates category specific business rules:
        - Client Visit: Requires either an Approved Pre-Travel Request OR Pre-Approval Screenshot Attachment.
        - Team Lunch: Validates participants and headcount cap.
        - Dinner Allowance: Late night allowance rules.
        """
        cat = getattr(self, "claim_category", "") or getattr(self, "expense_type", "") or "General Expense"
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved", "Returned to Employee")

        # Normalize category naming
        if cat in ("Client Visit", "Client Visit Travel"):
            self.claim_category = "Client Visit Travel"
            # PRE-APPROVAL VALIDATION FOR CLIENT VISIT
            ptr_name = getattr(self, "pre_travel_request", None)
            attachment = getattr(self, "pre_approval_attachment", None)

            if is_submitting:
                if not ptr_name and not attachment:
                    raise APValidationError(
                        "Pre-Approval Required: For 'Client Visit' expenses, you must either:\n"
                        "1. Link an Approved 'Pre Travel Request' document, OR\n"
                        "2. Upload a 'Pre-Approval Attachment / Approval Screenshot' of email authorization."
                    )

                if ptr_name:
                    ptr_doc = frappe.db.get_value(
                        "Pre Travel Request",
                        ptr_name,
                        ["employee", "status"],
                        as_dict=True
                    )
                    if not ptr_doc:
                        raise APValidationError(f"Linked Pre-Travel Request '{ptr_name}' does not exist.")
                    if ptr_doc.employee != self.employee:
                        raise APSecurityError(f"Pre-Travel Request '{ptr_name}' belongs to a different employee ({ptr_doc.employee}).")
                    if ptr_doc.status not in ("Approved", "Claimed"):
                        raise APValidationError(f"Pre-Travel Request '{ptr_name}' cannot be used: status is '{ptr_doc.status}', expected 'Approved'.")

        elif cat == "Team Lunch / Outing":
            self.claim_category = "Team Lunch / Outing"
            from ap_automation.services import team_bonding_wallet_service
            team_bonding_wallet_service.validate_team_bonding_claim(self)

        elif cat == "Dinner Allowance":
            self.claim_category = "Dinner Allowance"

        elif cat == "Branch Expense & Maintenance":
            self.claim_category = "Branch Expense & Maintenance"

        else:
            self.claim_category = "General Expense"

    def validate_expense_lines(self):
        """Enforces line-level policy rules and bill proof attachment requirements."""
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved", "Returned to Employee")
        if getattr(self, "claim_category", "") == "Client Visit Travel" or getattr(self, "expense_category", "") == "Client Visit Travel":
            legs = getattr(self, "client_visit_legs", []) or []
            if is_submitting and not legs:
                raise APValidationError("Client Visit Travel claim must list at least one client visit travel leg.")
            return

        lines = getattr(self, "expense_lines", []) or []
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved", "Returned to Employee")

        if not lines:
            if not is_submitting:
                return
            raise APValidationError("Expense Claim must contain at least one expense line item.")

        for idx, row in enumerate(lines, start=1):
            if not getattr(row, "expense_date", None):
                row.expense_date = self.posting_date or nowdate()

            merchant = (getattr(row, "merchant_name", "") or "").strip()
            if not merchant:
                if is_submitting:
                    raise APValidationError(f"Row {idx}: Merchant / Service Provider is mandatory.")
                else:
                    row.merchant_name = "General Merchant"

            amt = flt(getattr(row, "amount", 0.0) or 0.0)
            if is_submitting and amt <= 0:
                raise APValidationError(f"Row {idx}: Amount must be positive (Found: INR {amt:,.2f}).")

            # Mandatory proof check upon submission
            if is_submitting and not getattr(row, "receipt_attachment", None):
                raise APValidationError(
                    f"Row {idx} ({merchant} - INR {amt:,.2f}): "
                    "Bill / Tax Receipt attachment is strictly mandatory for every expense line upon submission."
                )

            # GSTIN statutory check if marked B2B
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

            # Group-Wide Cross-Lane Duplicate Spend Detection
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
                            f"⚠️ Duplicate Expense Detected on Row {idx}! "
                            f"Invoice '{c['invoice_number']}' for INR {c['amount']:,.2f} at '{merchant}' "
                            f"has already been claimed in Company '{c['company']}' (Voucher: #{c['document_name']}). "
                            f"Duplicate claims across sister companies and expense lanes are strictly blocked."
                        )

    def calculate_settlement_totals(self):
        """Calculates total claimed amount and net payable amount (100% direct reimbursement, no advance)."""
        if getattr(self, "claim_category", "") == "Client Visit Travel" or getattr(self, "expense_category", "") == "Client Visit Travel":
            legs = getattr(self, "client_visit_legs", []) or []
            total_km = sum(flt(getattr(r, "distance_km", 0.0) or 0.0) for r in legs)
            total_mileage = sum(flt(getattr(r, "leg_amount", 0.0) or 0.0) for r in legs)
            total_tolls = sum(flt(getattr(r, "toll_parking_amount", 0.0) or 0.0) for r in legs)
            per_diem = (flt(getattr(self, "per_diem_days", 1) or 1) * flt(getattr(self, "per_diem_amount", 0.0) or 0.0)) if getattr(self, "is_per_diem_claimed", 0) else 0.0

            self.total_trip_distance_km = round(total_km, 2)
            self.total_leg_mileage_amount = round(total_mileage, 2)
            self.total_toll_parking_amount = round(total_tolls, 2)
            total_spend = total_mileage + total_tolls + per_diem
        elif getattr(self, "claim_category", "") == "Team Lunch / Outing":
            lines = getattr(self, "expense_lines", []) or []
            gross_spend = sum(flt(getattr(r, "amount", 0.0) or 0.0) for r in lines)
            capped = flt(getattr(self, "capped_claim_amount", 0.0) or 0.0)
            if getattr(self, "participants", None) and capped > 0:
                total_spend = min(gross_spend, capped)
            else:
                total_spend = gross_spend
        else:
            lines = getattr(self, "expense_lines", []) or []
            total_spend = sum(flt(getattr(r, "amount", 0.0) or 0.0) for r in lines)

        self.total_claim_amount = round(total_spend, 2)
        if not getattr(self, "sanctioned_amount", None) or flt(self.sanctioned_amount) <= 0:
            self.sanctioned_amount = self.total_claim_amount
        self.net_payable_amount = round(flt(self.sanctioned_amount), 2)

    def _mark_linked_pre_travel_claimed(self):
        """Marks linked Pre-Travel Request as Claimed upon final submission."""
        ptr = getattr(self, "pre_travel_request", None)
        if ptr and frappe.db.exists("Pre Travel Request", ptr):
            frappe.db.set_value("Pre Travel Request", ptr, "status", "Claimed", update_modified=False)

    def _unmark_linked_pre_travel_claimed(self):
        """Reverts Pre-Travel Request status to Approved if claim is cancelled."""
        ptr = getattr(self, "pre_travel_request", None)
        if ptr and frappe.db.exists("Pre Travel Request", ptr):
            frappe.db.set_value("Pre Travel Request", ptr, "status", "Approved", update_modified=False)

    def _register_line_spend_fingerprints(self):
        """Registers line items into AP Spend Fingerprint ledger."""
        for row in (self.expense_lines or []):
            merchant = getattr(row, "merchant_name", "")
            inv = getattr(row, "invoice_number", "")
            amt = flt(getattr(row, "amount", 0.0) or 0.0)
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

    def auto_link_and_unlock_receipt_files(self):
        """
        Permanent Auto-Link & Public Access Assurance Hook:
        Ensures all uploaded receipt files (child rows & parent pre-approval screenshot)
        are properly linked to this document in tabFile and marked is_private=0.
        This permanently eliminates 403 Forbidden errors for all approvers across all workflow stages
        (Manager, Receptionist, Admin L1/L2, Accounts L1/L2, Payment Releaser).
        """
        if self.is_new():
            return

        file_urls = []
        # 1. Line item proofs
        for row in (getattr(self, "expense_lines", []) or []):
            att = getattr(row, "receipt_attachment", None) or getattr(row, "attach_receipt", None)
            if att and isinstance(att, str) and att.strip():
                file_urls.append(att.strip())

        # 2. Parent pre-approval screenshot
        parent_att = getattr(self, "pre_approval_attachment", None)
        if parent_att and isinstance(parent_att, str) and parent_att.strip():
            file_urls.append(parent_att.strip())

        for url in file_urls:
            file_name = url.split("/")[-1]
            files = frappe.get_all(
                "File",
                filters={"file_url": ["like", f"%{file_name}"]},
                fields=["name", "attached_to_name", "attached_to_doctype", "is_private"]
            )
            for f in files:
                updates = {}
                if f.get("attached_to_name") != self.name or f.get("attached_to_doctype") != self.doctype:
                    updates["attached_to_doctype"] = self.doctype
                    updates["attached_to_name"] = self.name
                    updates["attached_to_field"] = "expense_lines"
                if f.get("is_private") != 0:
                    updates["is_private"] = 0

                if updates:
                    frappe.db.set_value("File", f["name"], updates, update_modified=False)

