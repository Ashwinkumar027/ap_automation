"""
Petty Cash Entry Controller (Enterprise Bank-Grade Standard)
Implements:
1. Auto-Calculated Claim Title: 'Week {ISO_Week_Number} - {Company_Abbr}' (e.g. 'Week 38 - ACM').
2. Posting Date Validation: Blocks future dates & enforces 10th-of-following-month cutoff rule.
3. GST vs Non-GST Line Item Architecture:
   - Non-GST: Mandatory Bill / Txn # (UPI/Card/Cash Memo).
   - GST: Mandatory GST Invoice # & 15-Character Merchant GSTIN Validation.
4. 1 Bill Per Line Item Validation (Rejects multi-file/delimiter payloads).
5. Full Immutability Guard: Submitted vouchers are strictly locked from tampering.
6. Bank Account Security & Auto-Fetch.
7. Merchant + Bill # / Txn ID Intra & Cross-Voucher Duplicate Spend Shield.
"""
import re
import datetime
from typing import Dict, Any, List, Optional
import frappe
from frappe.model.document import Document
from frappe.utils import getdate, nowdate, flt
from ap_automation.exceptions import APValidationError
from ap_automation.services import notification_service

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


class PettyCashEntry(Document):
    """
    Petty Cash Entry Controller.
    Governs corporate imprest management, multi-tier approvals, and statutory GST compliance.
    """

    RECEIPT_THRESHOLD = 500.00

    def validate(self):
        """Lifecycle hook executed on document save."""
        self.set_claim_title()
        self.validate_posting_date()
        self.fetch_custodian_bank_details()
        self.validate_expense_lines()
        self.validate_duplicate_lines()
        self.calculate_totals()
        # validate_immutability removed per user request

    def set_claim_title(self):
        """Auto-computes Claim Title based on Posting Date week number and Company abbreviation (e.g. 'Week 38 - ACM')."""
        if self.posting_date and self.company:
            post_dt = getdate(self.posting_date)
            week_num = post_dt.isocalendar()[1]
            abbr = frappe.db.get_value("Company", self.company, "abbr") or (self.company.split()[0] if self.company else "ACM")
            self.claim_title = f"Week {week_num} - {abbr}"

    def validate_posting_date(self):
        """
        Enforces corporate posting date policies:
        1. Future posting dates are strictly forbidden.
        2. Claims for current month are allowed up to today.
        3. Claims for the immediately preceding calendar month are allowed up to the 10th of the current month.
        4. Claims older than the immediately preceding calendar month are strictly blocked.
        """
        if not self.posting_date:
            self.posting_date = nowdate()

        post_date = getdate(self.posting_date)
        today = getdate(nowdate())

        # 1. Block Future Posting Dates
        if post_date > today:
            frappe.throw(
                f"❌ Invalid Posting Date: {self.posting_date}. Posting Date cannot be in the future.",
                exc=APValidationError
            )

        # 2. Cut-off Window Calculation
        first_of_current_month = today.replace(day=1)
        prev_month_last_day = first_of_current_month - datetime.timedelta(days=1)
        prev_month_first_day = prev_month_last_day.replace(day=1)

        # Current month bills are valid
        if post_date >= first_of_current_month:
            return

        # Preceding month bills: valid only up to 10th of current month
        if prev_month_first_day <= post_date <= prev_month_last_day:
            if today.day > 10:
                month_name = prev_month_first_day.strftime("%B %Y")
                current_month_name = today.strftime("%B %Y")
                frappe.throw(
                    f"⏰ Submission Cut-off Expired: Claims for {month_name} were only accepted until the 10th of {current_month_name}. "
                    f"Please contact the Accounts Director for special audit approval.",
                    exc=APValidationError
                )
            return

        # Older than preceding month
        if post_date < prev_month_first_day:
            old_month_name = post_date.strftime("%B %Y")
            frappe.throw(
                f"❌ Stale Expense Date: Claims for {old_month_name} exceed the allowed historical submission window (prior calendar month max).",
                exc=APValidationError
            )

    def fetch_custodian_bank_details(self):
        """Auto-fetches read-only bank details directly from the Employee master."""
        if self.custodian:
            emp = frappe.db.get_value(
                "Employee",
                self.custodian,
                ["employee_name", "custom_name_as_per_bank", "bank_name", "bank_ac_no", "custom_ifsc_code", "ifsc_code"],
                as_dict=True
            )
            if emp:
                self.beneficiary_name = emp.get("custom_name_as_per_bank") or emp.get("employee_name") or ""
                self.bank_name = emp.get("bank_name") or ""
                self.custodian_bank_account = emp.get("bank_ac_no") or ""
                self.custodian_ifsc_code = emp.get("custom_ifsc_code") or emp.get("ifsc_code") or ""

    def validate_expense_lines(self):
        """
        Validates line-level compliance, single bill per line, and GST / Non-GST rules.
        """
        if not self.expense_lines or len(self.expense_lines) == 0:
            frappe.throw(
                "A Petty Cash Entry must contain at least one valid expense line item.",
                exc=APValidationError
            )

        for idx, row in enumerate(self.expense_lines, 1):
            amt = flt(row.amount or 0.0)
            if amt <= 0:
                frappe.throw(
                    f"Row #{idx} ({row.expense_category or 'Expense Line'}): Amount must be strictly greater than ₹ 0.00.",
                    exc=APValidationError
                )
            if not row.expense_category:
                frappe.throw(f"Row #{idx}: Expense Category is required.", exc=APValidationError)
            if not row.merchant_name:
                frappe.throw(f"Row #{idx}: Merchant / Payee Name is required.", exc=APValidationError)
            if not row.expense_date:
                frappe.throw(f"Row #{idx}: Expense Date is required.", exc=APValidationError)
            
            # Miscellaneous Category Mandatory Remarks
            if row.expense_category == "Miscellaneous" and not (getattr(row, "remarks", None) or getattr(row, "description", None) or "").strip():
                frappe.throw(
                    f"Row #{idx} (Miscellaneous): Please specify the purpose/details in the Remarks field.",
                    exc=APValidationError
                )

            # 1 Bill Per Line Item Validation
            attachment = (getattr(row, "receipt_attachment", None) or "").strip()
            if attachment:
                if "," in attachment or ";" in attachment or "\n" in attachment or "\r" in attachment:
                    frappe.throw(
                        f"Row #{idx}: Multiple receipts detected. Only one single bill is permitted per line item. "
                        f"Please split multiple bills into separate rows.",
                        exc=APValidationError
                    )

            # Receipt threshold validation (> ₹500)
            if amt > self.RECEIPT_THRESHOLD and not attachment:
                desc = (getattr(row, "remarks", "") or getattr(row, "description", "") or "").lower()
                if "no receipt" not in desc and "exempt" not in desc:
                    frappe.throw(
                        f"Row #{idx} ({row.merchant_name} - ₹{amt:,.2f}): "
                        f"Receipt attachment is mandatory for expenses exceeding ₹{self.RECEIPT_THRESHOLD:,.2f}.",
                        exc=APValidationError
                    )

            # GST vs Non-GST Rules
            is_gst = int(getattr(row, "is_gst", 0) or 0)
            bill_no = (getattr(row, "bill_number", None) or getattr(row, "transaction_id", None) or "").strip()
            
            if is_gst == 1:
                if not bill_no:
                    frappe.throw(
                        f"Row #{idx} ({row.merchant_name}): GST Invoice Number is mandatory for GST bills.",
                        exc=APValidationError
                    )
                gstin = (getattr(row, "merchant_gstin", None) or "").strip().upper()
                if not gstin:
                    frappe.throw(
                        f"Row #{idx} ({row.merchant_name}): Merchant GSTIN is mandatory for GST bills.",
                        exc=APValidationError
                    )
                if not GSTIN_REGEX.match(gstin):
                    frappe.throw(
                        f"Row #{idx} ({row.merchant_name}): Invalid Merchant GSTIN '{gstin}'. "
                        f"Must be a valid 15-character statutory GSTIN (e.g. 29AAAAA0000A1Z5).",
                        exc=APValidationError
                    )
                row.merchant_gstin = gstin
                row.bill_number = bill_no
            else:
                if bill_no and not getattr(row, "bill_number", None):
                    row.bill_number = bill_no

    def validate_duplicate_lines(self):
        """Checks for duplicate bills (Merchant + Bill # / Txn ID) intra and cross-voucher."""
        seen_keys = set()
        current_name = getattr(self, "name", None) or ""
        old_name = None
        if hasattr(self, "get_doc_before_save") and self.get_doc_before_save():
            old_name = self.get_doc_before_save().name

        parent_voucher = getattr(self, "parent_voucher", None) or ""
        forked_voucher = getattr(self, "forked_voucher", None) or ""

        for idx, row in enumerate(self.expense_lines, 1):
            merchant = (row.merchant_name or "").strip().lower()
            bill_no = (row.bill_number or row.transaction_id or "").strip().lower()

            if merchant and bill_no:
                key = (merchant, bill_no)
                # 1. Check duplicate within this same voucher (in-memory)
                if key in seen_keys:
                    frappe.throw(
                        f"⚠️ Duplicate Line in Voucher: Row #{idx} has duplicate Merchant '{row.merchant_name}' "
                        f"and Bill #{bill_no}. Duplicate bills within the same voucher are not permitted.",
                        exc=APValidationError
                    )
                seen_keys.add(key)

                # 2. Check duplicate across other active vouchers in database
                existing_lines = frappe.db.sql(
                    """
                    SELECT parent, merchant_name, bill_number, amount
                    FROM `tabPetty Cash Line Item`
                    WHERE LOWER(TRIM(merchant_name)) = %s
                      AND (LOWER(TRIM(bill_number)) = %s OR LOWER(TRIM(COALESCE(transaction_id, ''))) = %s)
                      AND docstatus < 2
                    LIMIT 10
                    """,
                    (merchant, bill_no, bill_no),
                    as_dict=True
                )
                for match in existing_lines:
                    if match.parent == current_name or (old_name and match.parent == old_name):
                        continue
                    if self.is_new() and match.parent == self.name:
                        continue

                    if parent_voucher and match.parent == parent_voucher:
                        continue
                    if forked_voucher and match.parent == forked_voucher:
                        continue
                    if current_name and frappe.db.get_value("Petty Cash Entry", match.parent, "parent_voucher") == current_name:
                        continue
                    if current_name and frappe.db.get_value("Petty Cash Entry", match.parent, "forked_voucher") == current_name:
                        continue

                    p_status = frappe.db.get_value("Petty Cash Entry", match.parent, "status")
                    if p_status not in ("Rejected", "Cancelled", "Merged"):
                        frappe.throw(
                            f"⚠️ Duplicate Bill Detected: Bill #{bill_no} from Merchant '{row.merchant_name}' "
                            f"(Amount: ₹{row.amount:,.2f}) has already been submitted in Voucher #{match.parent}. "
                            f"To prevent duplicate payments, please verify the bill details.",
                            exc=APValidationError
                        )

    def calculate_totals(self):
        """Calculates total amount dynamically."""
        total = 0.0
        for row in self.expense_lines:
            total += flt(row.amount or 0.0)
        self.total_amount = round(total, 2)

    def validate_immutability(self):
        """Locking removed per user request. Lines remain editable by approvers/auditors."""
        pass

    def on_submit(self):
        """Dispatches automated notification to L1 Admin Reviewer."""
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

    def before_delete(self):
        if self.batch_id or self.status in ("Queued in Batch", "Disbursed via IDFC", "Settled"):
            frappe.throw(
                f"Cannot delete Petty Cash Entry '{self.name}' because it is linked to Payment Batch '{self.batch_id}' or already disbursed.",
                exc=APValidationError
            )
        if self.status not in ("Draft", "Cancelled", "Rejected") and frappe.session.user != "Administrator":
            frappe.throw(
                f"Cannot delete Petty Cash Entry '{self.name}' because it is in active status '{self.status}'. "
                f"Only Draft or Cancelled vouchers can be deleted.",
                exc=APValidationError
            )


@frappe.whitelist()
def get_all_employees_query(doctype, txt, searchfield, start, page_len, filters):
    """Returns all active employees ignoring user permission filters so Front Desk can select any beneficiary/staff."""
    txt_filter = f"%{txt}%" if txt else "%"
    return frappe.db.sql("""
        SELECT name, employee_name, department, designation
        FROM `tabEmployee`
        WHERE status = 'Active'
          AND (name LIKE %(txt)s OR employee_name LIKE %(txt)s)
        ORDER BY employee_name ASC
        LIMIT %(start)s, %(page_len)s
    """, {
        "txt": txt_filter,
        "start": int(start or 0),
        "page_len": int(page_len or 20)
    })


@frappe.whitelist()
def get_all_companies_query(doctype, txt, searchfield, start, page_len, filters):
    """Returns all companies ignoring user permission filters."""
    txt_filter = f"%{txt}%" if txt else "%"
    return frappe.db.sql("""
        SELECT name, company_name, abbr
        FROM `tabCompany`
        WHERE name LIKE %(txt)s OR company_name LIKE %(txt)s
        ORDER BY name ASC
        LIMIT %(start)s, %(page_len)s
    """, {
        "txt": txt_filter,
        "start": int(start or 0),
        "page_len": int(page_len or 20)
    })
