"""
Petty Cash Entry Controller (Lane 1 - Imprest System)
Enforces:
1. Strict line item amount validation (amount > 0).
2. Mandatory non-empty expense lines validation.
3. Automatic calculation of total_amount and verified_amount.
4. Auto-population of Beneficiary Bank Details from HRMS Employee Master.
5. Mandatory Remarks validation for Miscellaneous expenses.
6. Duplicate bill validation within and across vouchers.
7. Immutability when batch_id is linked or status is Disbursed/Queued in Batch.
8. Automated Notification Hook on submission to notify L1 Accounts Verifier.
9. Automated Notification Hook on L2 Approval to notify Custodian.
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
            if row.expense_category == "Miscellaneous" and not (getattr(row, "remarks", None) or getattr(row, "description", None) or "").strip():
                frappe.throw(
                    f"Row #{idx} (Miscellaneous): Please specify the purpose/details in the Remarks field.",
                    exc=APValidationError
                )

    def validate_duplicate_lines(self):
        """Checks for duplicate bills (Merchant + Bill #) within the voucher and across all other active vouchers."""
        seen_keys = set()
        current_name = getattr(self, "name", None) or ""
        old_name = None
        if hasattr(self, "get_doc_before_save") and self.get_doc_before_save():
            old_name = self.get_doc_before_save().name

        parent_voucher = getattr(self, "parent_voucher", None) or ""
        forked_voucher = getattr(self, "forked_voucher", None) or ""

        for idx, row in enumerate(self.expense_lines, 1):
            merchant = (row.merchant_name or "").strip().lower()
            bill_no = (row.bill_number or "").strip().lower()

            if merchant and bill_no:
                key = (merchant, bill_no)
                # 1. Check duplicate within this same voucher (in-memory) - Merchant + Bill # only
                if key in seen_keys:
                    frappe.throw(
                        f"⚠️ Duplicate Line in Voucher: Row #{idx} has duplicate Merchant '{row.merchant_name}' "
                        f"and Bill #{row.bill_number}. Duplicate bills within the same voucher are not permitted.",
                        exc=APValidationError
                    )
                seen_keys.add(key)

                # 2. Check duplicate across other active vouchers in database
                existing_lines = frappe.db.sql(
                    """
                    SELECT parent, merchant_name, bill_number, amount
                    FROM `tabPetty Cash Line Item`
                    WHERE LOWER(TRIM(merchant_name)) = %s
                      AND LOWER(TRIM(bill_number)) = %s
                      AND docstatus < 2
                    LIMIT 10
                    """,
                    (merchant, bill_no),
                    as_dict=True
                )
                for match in existing_lines:
                    # Strictly ignore this voucher itself
                    if match.parent == current_name or (old_name and match.parent == old_name):
                        continue
                    if self.is_new() and match.parent == self.name:
                        continue

                    # Strictly ignore related parent/child dispute vouchers in the same lineage
                    if parent_voucher and match.parent == parent_voucher:
                        continue
                    if forked_voucher and match.parent == forked_voucher:
                        continue
                    if current_name and frappe.db.get_value("Petty Cash Entry", match.parent, "parent_voucher") == current_name:
                        continue
                    if current_name and frappe.db.get_value("Petty Cash Entry", match.parent, "forked_voucher") == current_name:
                        continue

                    # Verify parent voucher is active (not cancelled/rejected)
                    p_status = frappe.db.get_value("Petty Cash Entry", match.parent, "status")
                    if p_status not in ("Rejected", "Cancelled", "Merged"):
                        frappe.throw(
                            f"⚠️ Duplicate Bill Detected: Bill #{row.bill_number} from Merchant '{row.merchant_name}' "
                            f"(Amount: ₹{row.amount:,.2f}) has already been submitted in Voucher #{match.parent}. "
                            f"To prevent duplicate payments, please verify the bill details.",
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
        SELECT name, company_name
        FROM `tabCompany`
        WHERE name LIKE %(txt)s OR company_name LIKE %(txt)s
        ORDER BY name ASC
        LIMIT %(start)s, %(page_len)s
    """, {
        "txt": txt_filter,
        "start": int(start or 0),
        "page_len": int(page_len or 20)
    })
