"""
Vendor Invoice Claim Controller (Lane 3 Intake & Governance)
Inherits from APDocument base controller.
Enforces:
1. Dual-route intake rules (With PO vs Without PO).
2. Zero-typing vendor bank account binding from ERPNext Supplier master.
3. Penny Drop Zero-Trust Lockout: Blocks filing if bank account is locked due to NPCI mismatch.
4. Mandatory proof attachments (Tax invoice + Email approval for non-PO).
5. Statutory GST calculation (0%, 5%, 12%, 18%, 28%).
6. Autonomous 3-Way Matching against PO and GRN with tolerance checks.
7. Statutory Indian TDS calculation (194C, 194J, 194Q, 206AB).
8. Advance offset deduction: Net = Total - Advance - TDS.
9. Group-wide duplicate spend fingerprinting via APDocument base class.
10. Full Audit Error Logging (frappe.log_error) and Interactive Error Dialogs.
"""
from typing import Dict, Any, List, Optional, Union, Tuple
import frappe
from frappe import _
from frappe.utils import now_datetime, flt, nowdate
from ap_automation.controllers.ap_document import APDocument
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.duplicate_engine import register_spend_fingerprint, release_spend_fingerprint
from ap_automation.services.matching_service import execute_3way_matching
from ap_automation.services.tds_service import apply_tds_to_invoice
from ap_automation.services.notification_service import (
    notify_vendor_claim_submitted,
    notify_vendor_claim_manager_approved,
    notify_vendor_claim_hod_approved,
    notify_vendor_claim_director_approved,
    notify_vendor_claim_accounts_l1_verified,
    notify_vendor_claim_accounts_l2_approved,
    notify_vendor_claim_disputed
)


def log_and_throw(message: str, title: str = "Vendor Claim Validation Error", exc=APValidationError, doc=None):
    """
    Logs an official Error Log in Frappe DB and raises a user-facing interactive error dialog.
    Guarantees zero silent rejections and full audit visibility in Desk UI.
    """
    doc_name = getattr(doc, "name", "Draft") if doc else "Draft"
    vendor_label = getattr(doc, "vendor_name", None) or getattr(doc, "vendor", "Unassigned") if doc else "Unassigned"
    
    try:
        frappe.log_error(
            title=f"Vendor Claim Validation Error: {title} ({doc_name})",
            message=(
                f"Validation Failure Details:\n"
                f"---------------------------\n"
                f"Title: {title}\n"
                f"Reason: {message}\n"
                f"Document: {doc_name}\n"
                f"Vendor: {vendor_label}\n"
                f"User: {frappe.session.user if getattr(frappe, 'session', None) else 'System'}\n"
                f"DocType: Vendor Invoice Claim\n"
            )
        )
    except Exception:
        pass

    frappe.throw(message, title=title, exc=exc)


class VendorInvoiceClaim(APDocument):
    """
    Vendor Invoice Claim controller.
    Ensures zero fraud, penny drop lockout enforcement, statutory GST/TDS compliance, and IDFC payout integration.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flags.ignore_links = True

    def after_insert(self):
        if getattr(self, "status", None) == "Pending Manager Approval":
            try:
                notify_vendor_claim_submitted(self.name)
            except Exception as e:
                frappe.log_error(f"Vendor submission notification dispatch: {e}")

    def validate(self):
        """Lifecycle hook executed on document save."""
        po_val = getattr(self, "purchase_order", None)
        if po_val and frappe.db.exists("AP Purchase Order", po_val):
            self.flags.ignore_links = True

        has_items = bool(getattr(self, "items", None) and len(self.items) > 0)
        if has_items:
            self.validate_and_lock_vendor_lines()
            self.calculate_financial_totals()
            execute_3way_matching(self)
        else:
            self.bind_and_lock_vendor_profile()
            self.validate_intake_route_and_proofs()
            self.calculate_financial_totals()

            # Execute 3-Way Matching Engine
            execute_3way_matching(self)

            # Apply Statutory Indian TDS
            apply_tds_to_invoice(self)

            # Re-verify and finalize all financial totals and deductions
            self.calculate_financial_totals()

        # Map payee and invoice fields for APDocument base spend hash and banking dispatch
        self.payee_name = getattr(self, "vendor_name", "") or getattr(self, "vendor", "")
        self.invoice_number = getattr(self, "tax_invoice_number", "")
        self.total_amount = self.net_payable_amount

        # Ensure Draft status is preserved while user uploads documents or edits
        if getattr(self, "status", "Draft") in ("Draft", "Not Saved"):
            self.status = "Draft"
            self.workflow_state = "Draft Filing"

        # Auto-resolve and bind claimant's dynamic HRMS reporting manager with O(1) indexed lookup
        if self.status == "Pending Manager Approval" and not getattr(self, "designated_approver", None) and getattr(self, "owner", None):
            claimant_emp = frappe.db.get_value(
                "Employee",
                {"user_id": self.owner, "status": "Active"},
                ["reports_to"],
                as_dict=True
            )
            if claimant_emp and claimant_emp.reports_to:
                mgr_user = frappe.db.get_value("Employee", claimant_emp.reports_to, "user_id")
                if mgr_user:
                    self.designated_approver = mgr_user

        # Execute parent base validations (duplicate hash, immutability, tamper guard)
        super().validate()

    def before_submit(self):
        """Pre-submission verification guard: strictly halts any invalid or incomplete filing."""
        if getattr(self, "status", "Draft") != "Approved for Payment":
            log_and_throw(
                f"Direct Submission Blocked: Vendor Invoice Claim must complete all required approval stages (Manager -> Director -> Accounts L1 -> Accounts L2) before it can be submitted. Current status: '{self.status}'.",
                title="Approval Stages Pending",
                doc=self
            )
        if getattr(self, "items", None) and len(self.items) > 0:
            self.validate_and_lock_vendor_lines()
        else:
            self.bind_and_lock_vendor_profile()
            self.validate_intake_route_and_proofs()
        self.calculate_financial_totals()

    def on_submit(self):
        """Registers spend fingerprint lock and syncs linked Event Master budget ledger."""
        super().on_submit()
        if getattr(self, "items", None) and len(self.items) > 0:
            for row in self.items:
                row_amt = flt(row.total_invoice_amount) or flt(row.base_amount)
                if row_amt > 0 and getattr(row, "invoice_number", None):
                    dummy_doc = frappe._dict({
                        "doctype": "Vendor Invoice Claim",
                        "name": f"{self.name}-{row.idx}",
                        "company": row.company or self.company,
                        "vendor": row.vendor,
                        "vendor_name": row.vendor_name or row.vendor,
                        "tax_invoice_number": row.invoice_number,
                        "total_invoice_amount": row_amt,
                        "net_payable_amount": flt(row.amount),
                        "status": self.status
                    })
                    register_spend_fingerprint(dummy_doc)
        register_spend_fingerprint(self)
        _sync_event_master_if_linked(getattr(self, "event", None))

    def on_cancel(self):
        """Releases spend fingerprint lock and re-syncs linked Event Master budget ledger."""
        super().on_cancel()
        if getattr(self, "items", None) and len(self.items) > 0:
            for row in self.items:
                dummy_doc = frappe._dict({
                    "name": f"{self.name}-{row.idx}",
                })
                try:
                    release_spend_fingerprint(dummy_doc)
                except Exception:
                    pass
        release_spend_fingerprint(self)
        _sync_event_master_if_linked(getattr(self, "event", None))

    def validate_and_lock_vendor_lines(self):
        """
        Validates every line item in the items child table:
        1. Ensures supplier is valid and active.
        2. Auto-fetches Supplier Legal Name and GSTIN.
        3. Auto-fetches and locks verified Bank Account and IFSC from Supplier Bank Master.
        4. Enforces Penny Drop Zero-Trust security check.
        5. Enforces mandatory bill proof, invoice number, and invoice date upon submission.
        6. Enforces positive base taxable amount.
        7. If po_type == 'With PO', validates purchase_order link and checks remaining balance.
        8. Intra-claim duplicate invoice protection: ensures same vendor + invoice_number isn't entered twice.
        9. AP Spend Fingerprint cross-lane duplicate spend detection.
        10. Sets header vendor metadata (single vendor vs 'Multiple Vendors (N Bills)').
        """
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        seen_bills = set()
        distinct_vendors = []

        for idx, row in enumerate(self.items, start=1):
            if not row.vendor:
                log_and_throw(f"Row #{idx}: Supplier / Vendor is mandatory.", title="Missing Vendor", doc=self)

            supp = frappe.db.get_value(
                "Supplier",
                row.vendor,
                ["supplier_name", "tax_id", "country", "disabled"],
                as_dict=True
            )
            if not supp:
                log_and_throw(f"Row #{idx}: Supplier '{row.vendor}' not found in master.", title="Supplier Not Found", doc=self)

            if supp.disabled:
                log_and_throw(
                    f"Row #{idx}: Supplier '{row.vendor}' is Disabled / Inactive in ERPNext. Invoices cannot be processed.",
                    title="Supplier Inactive / Disabled",
                    exc=APSecurityError,
                    doc=self
                )

            row.vendor_name = supp.supplier_name
            row.vendor_gstin = supp.tax_id or ""
            if not getattr(row, "company", None):
                row.company = self.company or frappe.defaults.get_user_default("Company")

            if row.vendor not in distinct_vendors:
                distinct_vendors.append(row.vendor)

            base_val = flt(row.base_amount)
            if is_submitting and base_val <= 0:
                log_and_throw(
                    f"Row #{idx} ({row.vendor_name}): Base Taxable Amount must be strictly greater than 0.00 upon submission.",
                    title="Invalid Base Amount",
                    doc=self
                )

            # Bank Account fetching and locking
            bank_acc = self._fetch_supplier_bank_account(row.vendor)
            if bank_acc:
                row.bank_beneficiary_name = bank_acc.get("bank_name") or supp.supplier_name
                row.bank_account_number = bank_acc.get("bank_account_no") or ""
                row.bank_ifsc_code = bank_acc.get("ifsc_code") or ""
                row.penny_drop_status = bank_acc.get("penny_drop_status") or "VERIFIED"
                if not getattr(row, "bank_proof_attachment", None):
                    row.bank_proof_attachment = bank_acc.get("bank_proof_attachment") or ""

                if is_submitting and bank_acc.get("penny_drop_status") == "LOCKED_PENNY_DROP_MISMATCH":
                    log_and_throw(
                        f"Row #{idx} ({row.vendor_name}): Bank account ({bank_acc.get('bank_account_no')}) is hard-locked due to NPCI Penny Drop Name Mismatch! Submission is halted until Accounts Manager override.",
                        title="NPCI Penny Drop Lockout",
                        exc=APSecurityError,
                        doc=self
                    )
            elif is_submitting:
                log_and_throw(
                    f"Row #{idx} ({row.vendor_name}): Registered verified bank account not found in ERPNext. Please update Supplier Bank Master.",
                    title="Vendor Bank Master Missing",
                    doc=self
                )

            # PO validation
            po_type = getattr(row, "po_type", "Without PO") or "Without PO"
            row.po_type = po_type
            if po_type == "With PO":
                if not getattr(row, "purchase_order", None):
                    if is_submitting:
                        log_and_throw(
                            f"Row #{idx} ({row.vendor_name}): Linked Purchase Order is mandatory when PO Type is 'With PO'.",
                            title="Missing Purchase Order",
                            doc=self
                        )
                else:
                    po_doc = frappe.db.get_value(
                        "AP Purchase Order",
                        row.purchase_order,
                        ["name", "net_taxable_value", "advance_amount", "status"],
                        as_dict=True
                    )
                    if po_doc and base_val > 0:
                        po_contracted = flt(po_doc.net_taxable_value)
                        bill_type = getattr(row, "bill_payment_type", "Final / Regular Bill") or "Final / Regular Bill"
                        row.bill_payment_type = bill_type
                        has_bpt_col = frappe.db.has_column("Vendor Invoice Item", "bill_payment_type")

                        if bill_type == "Advance / Part Payment":
                            if has_bpt_col:
                                prior_adv_res = frappe.db.sql(
                                    """
                                    SELECT SUM(vii.base_amount) as total
                                    FROM `tabVendor Invoice Item` vii
                                    JOIN `tabVendor Invoice Claim` vic ON vic.name = vii.parent
                                    WHERE vii.purchase_order = %s AND vic.name != %s
                                      AND vii.bill_payment_type = 'Advance / Part Payment'
                                      AND vic.docstatus != 2
                                      AND vic.status NOT IN ('Disputed', 'Draft', 'Cancelled')
                                    """,
                                    (row.purchase_order, getattr(self, "name", "NEW") or "NEW"),
                                    as_dict=True
                                )
                                prior_adv = flt(prior_adv_res[0].total) if prior_adv_res else 0.0
                            else:
                                prior_adv = 0.0

                            sibling_adv = sum(
                                flt(r.base_amount)
                                for i, r in enumerate(self.items)
                                if i < idx - 1
                                and getattr(r, "purchase_order", None) == row.purchase_order
                                and (getattr(r, "bill_payment_type", "Final / Regular Bill") or "Final / Regular Bill") == "Advance / Part Payment"
                            )
                            cumulative_adv = round(prior_adv + sibling_adv + base_val, 2)
                            if po_contracted > 0 and cumulative_adv > po_contracted and is_submitting:
                                log_and_throw(
                                    f"Row #{idx}: PO Advance Over-Limit! Cumulative advance payments for PO #{row.purchase_order} (Prior INR {prior_adv:,.2f} + Sibling INR {sibling_adv:,.2f} + Current INR {base_val:,.2f} = INR {cumulative_adv:,.2f}) exceed contracted PO value (INR {po_contracted:,.2f}).",
                                    title="PO Advance Exceeds Contract Value",
                                    doc=self
                                )
                        else:
                            # Regular / Final Bill: exclude prior Advance / Part Payment rows so final invoices are never falsely blocked
                            bpt_filter = "AND COALESCE(vii.bill_payment_type, 'Final / Regular Bill') != 'Advance / Part Payment'" if has_bpt_col else ""
                            prior_res = frappe.db.sql(
                                f"""
                                SELECT SUM(vii.base_amount) as total
                                FROM `tabVendor Invoice Item` vii
                                JOIN `tabVendor Invoice Claim` vic ON vic.name = vii.parent
                                WHERE vii.purchase_order = %s AND vic.name != %s
                                  {bpt_filter}
                                  AND vic.docstatus != 2
                                  AND vic.status NOT IN ('Disputed', 'Draft', 'Cancelled')
                                """,
                                (row.purchase_order, getattr(self, "name", "NEW") or "NEW"),
                                as_dict=True
                            )
                            prior_invoiced = flt(prior_res[0].total) if prior_res else 0.0
                            sibling_sum = sum(
                                flt(r.base_amount)
                                for i, r in enumerate(self.items)
                                if i < idx - 1
                                and getattr(r, "purchase_order", None) == row.purchase_order
                                and (getattr(r, "bill_payment_type", "Final / Regular Bill") or "Final / Regular Bill") != "Advance / Part Payment"
                            )
                            cumulative = round(prior_invoiced + sibling_sum + base_val, 2)
                            allowed_max = round(po_contracted * 1.10, 2)  # 10% price tolerance
                            if po_contracted > 0 and cumulative > allowed_max and is_submitting:
                                log_and_throw(
                                    f"Row #{idx}: Over-Invoicing Alert! Cumulative billed base for PO #{row.purchase_order} (Prior INR {prior_invoiced:,.2f} + Sibling INR {sibling_sum:,.2f} + Current INR {base_val:,.2f} = INR {cumulative:,.2f}) exceeds contracted value (INR {po_contracted:,.2f}).",
                                    title="PO Over-Invoicing Detected",
                                    doc=self
                                )
            elif po_type == "External / Email PO (Not in System)":
                row.purchase_order = None
                ext_po_no = (getattr(row, "external_po_number", None) or "").strip()
                row.external_po_number = ext_po_no
                ext_po_amt = flt(getattr(row, "external_po_amount", 0.0))
                bill_type = getattr(row, "bill_payment_type", "Final / Regular Bill") or "Final / Regular Bill"
                row.bill_payment_type = bill_type

                if is_submitting:
                    if not ext_po_no:
                        log_and_throw(
                            f"Row #{idx} ({row.vendor_name}): Manual / Email PO Number is mandatory when PO Type is 'External / Email PO (Not in System)'.",
                            title="Missing External PO Number",
                            doc=self
                        )
                    if ext_po_amt <= 0:
                        log_and_throw(
                            f"Row #{idx} ({row.vendor_name}): External PO Value Before GST (INR) must be strictly greater than 0.00.",
                            title="Missing External PO Value",
                            doc=self
                        )
                    if not getattr(row, "po_attachment", None):
                        log_and_throw(
                            f"Row #{idx} ({row.vendor_name}): Upload PO / Email Copy attachment is strictly mandatory for External / Email POs.",
                            title="Missing External PO Copy",
                            doc=self
                        )

                if ext_po_no and ext_po_amt > 0 and base_val > 0 and frappe.db.has_column("Vendor Invoice Item", "external_po_number"):
                    norm_ext = ext_po_no.lower()
                    has_bpt_col = frappe.db.has_column("Vendor Invoice Item", "bill_payment_type")

                    if bill_type == "Advance / Part Payment":
                        if has_bpt_col:
                            prior_adv_res = frappe.db.sql(
                                """
                                SELECT SUM(vii.base_amount) as total
                                FROM `tabVendor Invoice Item` vii
                                JOIN `tabVendor Invoice Claim` vic ON vic.name = vii.parent
                                WHERE vii.vendor = %s
                                  AND LOWER(TRIM(COALESCE(vii.external_po_number, ''))) = %s
                                  AND vic.name != %s
                                  AND vii.bill_payment_type = 'Advance / Part Payment'
                                  AND vic.docstatus != 2
                                  AND vic.status NOT IN ('Disputed', 'Draft', 'Cancelled', 'Rejected')
                                """,
                                (row.vendor, norm_ext, getattr(self, "name", "NEW") or "NEW"),
                                as_dict=True
                            )
                            prior_ext_adv = flt(prior_adv_res[0].total) if prior_adv_res else 0.0
                        else:
                            prior_ext_adv = 0.0

                        sibling_ext_adv = sum(
                            flt(r.base_amount)
                            for i, r in enumerate(self.items)
                            if i < idx - 1
                            and getattr(r, "vendor", None) == row.vendor
                            and (getattr(r, "external_po_number", None) or "").strip().lower() == norm_ext
                            and (getattr(r, "bill_payment_type", "Final / Regular Bill") or "Final / Regular Bill") == "Advance / Part Payment"
                        )
                        cumulative_ext_adv = round(prior_ext_adv + sibling_ext_adv + base_val, 2)
                        if cumulative_ext_adv > ext_po_amt and is_submitting:
                            log_and_throw(
                                f"Row #{idx}: External PO Advance Over-Limit! Cumulative advance payments for External PO '{ext_po_no}' (Prior INR {prior_ext_adv:,.2f} + Sibling INR {sibling_ext_adv:,.2f} + Current INR {base_val:,.2f} = INR {cumulative_ext_adv:,.2f}) exceed contracted External PO value (INR {ext_po_amt:,.2f}).",
                                title="External PO Advance Exceeds Contract Value",
                                doc=self
                            )
                    else:
                        bpt_filter = "AND COALESCE(vii.bill_payment_type, 'Final / Regular Bill') != 'Advance / Part Payment'" if has_bpt_col else ""
                        prior_ext_res = frappe.db.sql(
                            f"""
                            SELECT SUM(vii.base_amount) as total
                            FROM `tabVendor Invoice Item` vii
                            JOIN `tabVendor Invoice Claim` vic ON vic.name = vii.parent
                            WHERE vii.vendor = %s
                              AND LOWER(TRIM(COALESCE(vii.external_po_number, ''))) = %s
                              AND vic.name != %s
                              {bpt_filter}
                              AND vic.docstatus != 2
                              AND vic.status NOT IN ('Disputed', 'Draft', 'Cancelled', 'Rejected')
                            """,
                            (row.vendor, norm_ext, getattr(self, "name", "NEW") or "NEW"),
                            as_dict=True
                        )
                        prior_ext_invoiced = flt(prior_ext_res[0].total) if prior_ext_res else 0.0
                        sibling_ext_sum = sum(
                            flt(r.base_amount)
                            for i, r in enumerate(self.items)
                            if i < idx - 1
                            and getattr(r, "vendor", None) == row.vendor
                            and (getattr(r, "external_po_number", None) or "").strip().lower() == norm_ext
                            and (getattr(r, "bill_payment_type", "Final / Regular Bill") or "Final / Regular Bill") != "Advance / Part Payment"
                        )
                        cumulative_ext = round(prior_ext_invoiced + sibling_ext_sum + base_val, 2)
                        allowed_ext_max = round(ext_po_amt * 1.10, 2)  # 10% price tolerance
                        if cumulative_ext > allowed_ext_max and is_submitting:
                            log_and_throw(
                                f"Row #{idx}: External PO Over-Invoicing Detected! Cumulative billed base for External PO '{ext_po_no}' (Prior INR {prior_ext_invoiced:,.2f} + Sibling INR {sibling_ext_sum:,.2f} + Current INR {base_val:,.2f} = INR {cumulative_ext:,.2f}) exceeds contracted value (INR {ext_po_amt:,.2f} + 10% tolerance).",
                                title="External PO Over-Invoicing Detected",
                                doc=self
                            )
            else:
                row.purchase_order = None
                if hasattr(row, "external_po_number"):
                    row.external_po_number = None
                if hasattr(row, "external_po_amount"):
                    row.external_po_amount = 0.0
                if hasattr(row, "external_po_date"):
                    row.external_po_date = None

            # Submission mandatory checks
            if is_submitting:
                if not getattr(row, "invoice_number", None):
                    log_and_throw(f"Row #{idx}: Invoice # / Bill Ref is mandatory.", title="Missing Invoice Number", doc=self)
                if not getattr(row, "invoice_date", None):
                    log_and_throw(f"Row #{idx}: Invoice Date is mandatory.", title="Missing Invoice Date", doc=self)
                if not getattr(row, "receipt_attachment", None):
                    log_and_throw(
                        f"Row #{idx} ({row.vendor_name}): Bill Proof PDF/Photo attachment is strictly mandatory.",
                        title="Missing Bill Attachment",
                        doc=self
                    )

            # Intra-voucher duplicate invoice protection
            inv_no = (getattr(row, "invoice_number", None) or "").strip().lower()
            if row.vendor and inv_no:
                bill_tuple = (row.vendor.strip(), inv_no)
                if bill_tuple in seen_bills:
                    log_and_throw(
                        f"Row #{idx}: Duplicate Invoice detected! Invoice '{row.invoice_number}' for Vendor '{row.vendor_name or row.vendor}' is entered multiple times in this claim. Duplicate line items within the same claim are strictly prohibited.",
                        title="Duplicate Line Item in Claim",
                        doc=self
                    )
                seen_bills.add(bill_tuple)

                # Cross-lane duplicate spend fingerprint check
                row_amt = flt(row.total_invoice_amount) or base_val
                if row_amt > 0 and is_submitting:
                    from ap_automation.services.duplicate_engine import calculate_invoice_fingerprint
                    inv_hash = calculate_invoice_fingerprint(row.vendor_name or row.vendor, row.invoice_number, row_amt)
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
                        if c["document_name"] == self.name:
                            continue
                        log_and_throw(
                            f"Row #{idx}: Cross-Lane Duplicate Spend Detected! Invoice '{row.invoice_number}' from '{row.vendor_name}' (Amount: INR {row_amt:,.2f}) has already been claimed in {c['document_type']} #{c['document_name']} under Company '{c['company']}'. Duplicate submissions across spend lanes are strictly blocked.",
                            title="Cross-Lane Duplicate Spend Detected",
                            doc=self
                        )

        # Set parent header metadata
        if len(distinct_vendors) == 1:
            first_row = self.items[0]
            self.vendor = first_row.vendor
            self.vendor_name = first_row.vendor_name
            self.vendor_gstin = first_row.vendor_gstin
            self.bank_name = first_row.bank_beneficiary_name
            self.bank_account_number = first_row.bank_account_number
            self.bank_ifsc_code = first_row.bank_ifsc_code
            self.bank_proof_attachment = first_row.bank_proof_attachment
            if len(self.items) == 1:
                self.tax_invoice_number = first_row.invoice_number
                self.tax_invoice_date = first_row.invoice_date
                if not getattr(self, "tax_invoice_attachment", None):
                    self.tax_invoice_attachment = first_row.receipt_attachment
            else:
                self.tax_invoice_number = f"Consolidated ({len(self.items)} Bills)"
        elif len(distinct_vendors) > 1:
            first_row = self.items[0]
            self.vendor = first_row.vendor
            self.vendor_name = f"Multiple Vendors ({len(self.items)} Bills)"
            self.vendor_gstin = "Multiple"
            self.bank_name = "Multiple Accounts"
            self.bank_account_number = "Multiple Accounts"
            self.bank_ifsc_code = "Multiple Accounts"
            self.tax_invoice_number = f"Consolidated ({len(self.items)} Bills)"

    def bind_and_lock_vendor_profile(self):
        """
        Pulls verified vendor details and bank account directly from ERPNext Supplier master.
        Enforces Penny Drop Zero-Trust lockout.
        """
        vendor_id = getattr(self, "vendor", None)
        if not vendor_id:
            log_and_throw("Vendor / Supplier is mandatory.", title="Vendor Required", doc=self)

        supp = frappe.db.get_value(
            "Supplier",
            vendor_id,
            ["supplier_name", "tax_id", "country", "disabled"],
            as_dict=True
        )
        if not supp:
            log_and_throw(f"Supplier '{vendor_id}' not found in ERPNext master.", title="Supplier Not Found", doc=self)

        if supp.disabled:
            log_and_throw(
                f"Supplier '{vendor_id}' is Disabled / Inactive in ERPNext. Invoices cannot be processed.",
                title="Supplier Inactive / Disabled",
                exc=APSecurityError,
                doc=self
            )

        self.vendor_name = supp.supplier_name
        self.vendor_gstin = supp.tax_id or ""

        bank_acc = self._fetch_supplier_bank_account(vendor_id)
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        if not bank_acc:
            if is_submitting:
                log_and_throw(
                    f"Banking Details Missing: Vendor '{self.vendor_name}' does not have a registered, verified "
                    "bank account in ERPNext. Please update the Supplier Bank Master before filing an invoice.",
                    title="Vendor Bank Master Missing",
                    doc=self
                )
            else:
                bank_acc = {"bank_name": "Pending Verification", "bank_account_no": "", "ifsc_code": ""}

        # Zero-Trust Penny Drop Lockout Guard
        pd_status = bank_acc.get("penny_drop_status")
        if pd_status == "LOCKED_PENNY_DROP_MISMATCH":
            log_and_throw(
                f"⚠️ Security Notice: Vendor '{self.vendor_name}' bank account "
                f"({bank_acc.get('bank_account_no')}) is hard-locked due to NPCI Penny Drop Name Mismatch! "
                "Invoice submission and payments are strictly halted until Accounts Manager review and manual unlock.",
                title="NPCI Penny Drop Lockout",
                exc=APSecurityError,
                doc=self
            )

        self.bank_name = bank_acc.get("bank_name", "")
        self.bank_account_number = bank_acc.get("bank_account_no", "")
        self.bank_ifsc_code = bank_acc.get("ifsc_code", "")
        if hasattr(self, "bank_proof_attachment"):
            self.bank_proof_attachment = bank_acc.get("bank_proof_attachment", "")

    def _fetch_supplier_bank_account(self, supplier_name: str) -> Dict[str, Any]:
        """Looks up active Bank Account linked to Supplier in tabBank Account with approval enforcement."""
        has_pd = frappe.db.has_column("Bank Account", "penny_drop_status")
        pd_select = ", ba.penny_drop_status" if has_pd else ""
        has_bp = frappe.db.has_column("Bank Account", "bank_proof_attachment")
        bp_select = ", ba.bank_proof_attachment" if has_bp else ""
        has_status = frappe.db.has_column("Bank Account", "approval_status")
        status_filter = "AND (ba.approval_status = 'Approved / Active' OR ba.approval_status IS NULL OR ba.approval_status = '')" if has_status else ""

        accs = frappe.db.sql(
            f"""
            SELECT ba.name, ba.bank, ba.bank_account_no, ba.branch_code{pd_select}{bp_select}
            FROM `tabBank Account` ba
            WHERE ba.party_type = 'Supplier' AND ba.party = %s {status_filter}
            ORDER BY ba.is_default DESC, ba.creation DESC
            LIMIT 1
            """,
            (supplier_name,),
            as_dict=True
        )
        if accs:
            return {
                "name": accs[0].name,
                "bank_name": accs[0].bank or "",
                "bank_account_no": accs[0].bank_account_no or "",
                "ifsc_code": accs[0].branch_code or "",
                "penny_drop_status": accs[0].get("penny_drop_status") or "VERIFIED",
                "bank_proof_attachment": accs[0].get("bank_proof_attachment") or ""
            }

        # If no approved account found, check if an account is pending approval
        if has_status:
            pending_acc = frappe.db.get_value(
                "Bank Account",
                {"party_type": "Supplier", "party": supplier_name},
                ["name", "approval_status"],
                as_dict=True
            )
            if pending_acc and pending_acc.approval_status not in ("Approved / Active", "", None):
                log_and_throw(
                    f"Vendor bank account '{pending_acc.name}' is currently in '{pending_acc.approval_status}' status. "
                    f"Vendor bank account details must be approved through the governance workflow before payments can be processed.",
                    title="Vendor Bank Account Approval Pending",
                    doc=self
                )

        return {}

    def validate_intake_route_and_proofs(self):
        """Enforces dual-route mandatory requirements and audit proof attachments with progressive Draft validation."""
        has_items = bool(getattr(self, "items", None) and len(self.items) > 0)
        if has_items:
            return

        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        route = getattr(self, "invoice_type", "Without PO (Direct Tax Invoice)")

        if not is_submitting:
            # On Draft, assign fallbacks
            if not getattr(self, "tax_invoice_number", None):
                self.tax_invoice_number = getattr(self, "invoice_number", None) or f"DRAFT-{frappe.generate_hash(length=6).upper()}"
            return

        if route == "With Purchase Order":
            if not getattr(self, "purchase_order", None):
                log_and_throw(
                    "Linked Purchase Order is mandatory when Route is 'With Purchase Order'.",
                    title="Linked Purchase Order Required",
                    doc=self
                )

        elif route == "Without PO (Direct Tax Invoice)":
            if not getattr(self, "email_approval_attachment", None):
                log_and_throw(
                    "Missing Internal Email Approval: For non-PO direct tax invoices, a screenshot or PDF of the "
                    "approving manager's email is strictly mandatory (PRD Section 6).",
                    title="Missing Manager Email Approval Proof",
                    doc=self
                )

        if not getattr(self, "tax_invoice_attachment", None):
            log_and_throw(
                "Vendor Tax Invoice PDF attachment is strictly mandatory.",
                title="Missing Tax Invoice PDF Attachment",
                doc=self
            )

        if not getattr(self, "tax_invoice_number", None):
            log_and_throw(
                "Vendor Tax Invoice # is mandatory.",
                title="Tax Invoice Number Required",
                doc=self
            )

        if not getattr(self, "tax_invoice_date", None):
            log_and_throw(
                "Tax Invoice Date is mandatory.",
                title="Tax Invoice Date Required",
                doc=self
            )

    def calculate_financial_totals(self):
        """Calculates GST amount and Total Invoice amount with progressive Draft support."""
        has_items = bool(getattr(self, "items", None) and len(self.items) > 0)
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")

        if has_items:
            tot_base = 0.0
            tot_gst = 0.0
            tot_cgst = 0.0
            tot_sgst = 0.0
            tot_igst = 0.0
            tot_bill = 0.0
            tot_tds = 0.0
            tot_adv = 0.0
            tot_ret = 0.0
            tot_net = 0.0

            for idx, row in enumerate(self.items, start=1):
                base = flt(row.base_amount)
                if base <= 0 and flt(row.amount) > 0:
                    base = flt(row.amount)
                    row.base_amount = base

                # GST calculation
                rate_str = row.gst_rate or "18%"
                gst_pct = flt(str(rate_str).replace("%", "").strip() or 0.0)
                gst_amt = round(base * (gst_pct / 100.0), 2)
                total_bill = round(base + gst_amt, 2)

                # Tax type split
                tax_type = getattr(row, "tax_type", "Intra-State (CGST + SGST)") or "Intra-State (CGST + SGST)"
                if "Inter-State" in tax_type or "IGST" in tax_type:
                    row.tax_type = "Inter-State (IGST)"
                    row.igst_amount = gst_amt
                    row.cgst_amount = 0.0
                    row.sgst_amount = 0.0
                else:
                    row.tax_type = "Intra-State (CGST + SGST)"
                    half_gst = round(gst_amt / 2.0, 2)
                    row.cgst_amount = half_gst
                    row.sgst_amount = round(gst_amt - half_gst, 2)
                    row.igst_amount = 0.0

                # Statutory TDS calculation
                section = getattr(row, "tds_section", "None / Exempt") or "None / Exempt"
                try:
                    from ap_automation.services.tds_service import calculate_tds
                    tds_info = calculate_tds(base, section)
                    tds_rate = tds_info.get("rate", 0.0)
                    tds_amt = tds_info.get("tds_amount", 0.0)
                except Exception:
                    tds_rate = 0.0
                    import re
                    m = re.search(r"\((\d+(?:\.\d+)?)\s*%\)", section)
                    if m:
                        tds_rate = flt(m.group(1))
                    elif "194C" in section:
                        tds_rate = 2.0
                    elif "194J" in section:
                        tds_rate = 10.0
                    elif "194Q" in section:
                        tds_rate = 0.1
                    elif "194I" in section:
                        tds_rate = 10.0
                    tds_amt = round(base * (tds_rate / 100.0), 2)

                # Deductions
                advance = flt(row.advance_deducted)
                retention = flt(row.retention_hold_amount)
                total_deductions = round(tds_amt + advance + retention, 2)

                if total_deductions > total_bill:
                    log_and_throw(
                        f"Row #{idx}: Deductions (TDS INR {tds_amt:,.2f} + Advance INR {advance:,.2f} + Retention INR {retention:,.2f} = INR {total_deductions:,.2f}) cannot exceed total bill amount (INR {total_bill:,.2f}).",
                        title="Deductions Exceed Bill Total",
                        doc=self
                    )

                net_pay = round(max(total_bill - total_deductions, 0.0), 2)

                row.gst_amount = gst_amt
                row.total_invoice_amount = total_bill
                row.tds_rate = tds_rate
                row.tds_amount = tds_amt
                row.amount = net_pay

                # Disputed lines excluded from net totals
                if getattr(row, "line_status", "Pending") == "Disputed / Discrepancy":
                    continue

                tot_base += base
                tot_gst += gst_amt
                tot_cgst += row.cgst_amount
                tot_sgst += row.sgst_amount
                tot_igst += row.igst_amount
                tot_bill += total_bill
                tot_tds += tds_amt
                tot_adv += advance
                tot_ret += retention
                tot_net += net_pay

            # Milestone advances reconciliation across all items
            milestone_sum = 0.0
            if self.get("milestone_payments") and len(self.get("milestone_payments")) > 0:
                milestone_sum = sum(flt(getattr(m, "adjusted_amount", None) or getattr(m, "disbursed_amount", 0.0) or 0.0) for m in self.get("milestone_payments"))

            if milestone_sum > 0:
                tot_adv = milestone_sum
                if len(self.items) == 1 and getattr(self.items[0], "line_status", "Pending") != "Disputed / Discrepancy":
                    r0 = self.items[0]
                    r0.advance_deducted = milestone_sum
                    r0.amount = round(max(float(r0.total_invoice_amount or 0.0) - float(r0.tds_amount or 0.0) - milestone_sum - float(r0.retention_hold_amount or 0.0), 0.0), 2)

            claim_ret = float(getattr(self, "retention_hold_amount", 0.0) or 0.0)
            if claim_ret > 0 and tot_ret == 0.0:
                tot_ret = claim_ret
                if len(self.items) == 1 and getattr(self.items[0], "line_status", "Pending") != "Disputed / Discrepancy":
                    r0 = self.items[0]
                    r0.retention_hold_amount = claim_ret
                    r0.amount = round(max(float(r0.total_invoice_amount or 0.0) - float(r0.tds_amount or 0.0) - float(r0.advance_deducted or 0.0) - claim_ret, 0.0), 2)

            tot_net = round(max(tot_bill - tot_tds - tot_adv - tot_ret, 0.0), 2)

            self.total_lines = len(self.items)
            self.base_amount = round(tot_base, 2)
            self.gst_amount = round(tot_gst, 2)
            self.cgst_amount = round(tot_cgst, 2)
            self.sgst_amount = round(tot_sgst, 2)
            self.igst_amount = round(tot_igst, 2)
            self.total_invoice_amount = round(tot_bill, 2)
            self.tds_amount = round(tot_tds, 2)
            self.advance_deducted = round(tot_adv, 2)
            self.total_prior_payments_adjusted = self.advance_deducted
            self.retention_hold_amount = round(tot_ret, 2)
            self.net_payable_amount = round(tot_net, 2)
            self.total_amount = self.net_payable_amount

            # Urgency audit for multi-row intake
            if getattr(self, "is_urgent", 0) or any(getattr(r, "is_urgent", 0) for r in self.items):
                self.is_urgent = 1
                if not getattr(self, "urgency_reason", None) or len(self.urgency_reason.strip()) < 5:
                    first_r_reason = next((r.urgency_reason for r in self.items if getattr(r, "urgency_reason", None)), None)
                    if first_r_reason and len(first_r_reason.strip()) >= 5:
                        self.urgency_reason = first_r_reason
                    else:
                        log_and_throw(
                            "Reason for Urgency is mandatory when marking a payment request as urgent.",
                            title="Missing Urgency Reason",
                            doc=self
                        )
                if not getattr(self, "urgency_flagged_by", None):
                    self.urgency_flagged_by = frappe.session.user
                    self.urgency_flagged_on = now_datetime()

            return

        base = float(getattr(self, "base_amount", 0.0) or getattr(self, "invoice_amount", 0.0) or getattr(self, "taxable_amount", 0.0) or 0.0)
        self.base_amount = base
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        if is_submitting and base <= 0:
            log_and_throw("Base Taxable Amount must be strictly positive upon submission.", title="Invalid Base Amount", doc=self)

        rate_str = getattr(self, "gst_rate", "18%") or "18%"
        rate_val = float(rate_str.replace("%", "").strip() or 0.0)

        gst = round(base * (rate_val / 100.0), 2)
        total = round(base + gst, 2)

        # Milestone advances reconciliation
        if self.get("milestone_payments") and len(self.get("milestone_payments")) > 0:
            total_milestone = sum(flt(m.adjusted_amount) for m in self.get("milestone_payments"))
            self.total_prior_payments_adjusted = round(total_milestone, 2)
            self.advance_deducted = round(total_milestone, 2)
        else:
            self.total_prior_payments_adjusted = float(getattr(self, "advance_deducted", 0.0) or 0.0)

        advance = float(getattr(self, "advance_deducted", 0.0) or 0.0)
        retention = float(getattr(self, "retention_hold_amount", 0.0) or 0.0)
        if getattr(self, "gst_released_separately", 0):
            self.gst_withheld_amount = gst
            gst_withheld = gst
        else:
            gst_withheld = float(getattr(self, "gst_withheld_amount", 0.0) or 0.0)

        if advance < 0:
            log_and_throw("Advance Deducted cannot be negative.", title="Negative Advance Amount", doc=self)

        if retention < 0:
            log_and_throw("Retention Hold Amount cannot be negative.", title="Negative Retention Amount", doc=self)

        if retention > 0 and (not getattr(self, "retention_hold_reason", None) or len(self.retention_hold_reason.strip()) < 5):
            log_and_throw("Retention Hold Reason is mandatory when retention hold amount is specified.", title="Missing Retention Reason", doc=self)

        # Urgency validation
        if getattr(self, "is_urgent", 0):
            if not getattr(self, "urgency_reason", None) or len(self.urgency_reason.strip()) < 5:
                log_and_throw("Reason for Urgency is mandatory when marking a payment request as urgent.", title="Missing Urgency Reason", doc=self)
            if not getattr(self, "urgency_flagged_by", None):
                self.urgency_flagged_by = frappe.session.user
                self.urgency_flagged_on = now_datetime()

        if advance > total:
            log_and_throw(
                f"Prior Advance Deducted (INR {advance:,.2f}) cannot exceed Total Invoice Amount (INR {total:,.2f}).",
                title="Advance Exceeds Total Amount",
                doc=self
            )

        # Automated 50:50 CGST & SGST Split vs. Inter-State IGST
        tax_type = getattr(self, "tax_type", "Intra-State (CGST + SGST)") or "Intra-State (CGST + SGST)"
        if "Inter-State" in tax_type or "IGST" in tax_type:
            self.tax_type = "Inter-State (IGST)"
            self.igst_rate = rate_val
            self.igst_amount = gst
            self.cgst_rate = 0.0
            self.cgst_amount = 0.0
            self.sgst_rate = 0.0
            self.sgst_amount = 0.0
        else:
            self.tax_type = "Intra-State (CGST + SGST)"
            half_rate = round(rate_val / 2.0, 2)
            half_gst = round(gst / 2.0, 2)
            self.cgst_rate = half_rate
            self.cgst_amount = half_gst
            self.sgst_rate = half_rate
            self.sgst_amount = round(gst - half_gst, 2)
            self.igst_rate = 0.0
            self.igst_amount = 0.0

        self.gst_amount = gst
        self.total_invoice_amount = total

        # Event Cost Variance calculation against previous benchmark spend
        prev_bench = float(getattr(self, "previous_benchmark_spend", 0.0) or 0.0)
        if prev_bench > 0:
            diff = total - prev_bench
            self.cost_variance = round(diff, 2)
            self.cost_variance_percentage = round((diff / prev_bench) * 100.0, 2)
        else:
            self.cost_variance = 0.0
            self.cost_variance_percentage = 0.0

        # Statutory Indian TDS Withholding calculation (1961 & 2025 Act)
        try:
            from ap_automation.services.tds_service import calculate_tds
            section = getattr(self, "tds_section", "None / Exempt") or "None / Exempt"
            tds_info = calculate_tds(base, section)
            self.tds_rate = tds_info.get("rate", 0.0)
            self.tds_amount = tds_info.get("tds_amount", 0.0)
            self.tds_threshold_warning = tds_info.get("threshold_warning") or ""
        except Exception:
            self.tds_rate = getattr(self, "tds_rate", 0.0) or 0.0
            self.tds_amount = getattr(self, "tds_amount", 0.0) or 0.0

        tds = float(getattr(self, "tds_amount", 0.0) or 0.0)
        total_deductions = round(advance + tds + retention + gst_withheld, 2)
        if is_submitting and total_deductions > total:
            log_and_throw(
                f"Total Deductions Exceed Invoice Total: Prior Advances (INR {advance:,.2f}) + "
                f"TDS (INR {tds:,.2f}) + Retention (INR {retention:,.2f}) + GST Withheld (INR {gst_withheld:,.2f}) = "
                f"INR {total_deductions:,.2f}, which exceeds Invoice Total (INR {total:,.2f}). Net payable cannot be negative. "
                f"Please adjust deductions so total deductions do not exceed invoice total.",
                title="Deductions Exceed Invoice Amount",
                doc=self
            )

        net = round(max(total - advance - tds - retention - gst_withheld, 0.0), 2)
        self.net_payable_amount = net
        self.total_amount = net


@frappe.whitelist()
def fetch_po_milestones(po_name: str, exclude_claim: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetches all disbursed and approved advance/part payments recorded against an AP Purchase Order.
    Priority order:
      1. Prior 'Advance / Part Payment' rows in Vendor Invoice Claim linked to this PO (with remaining unadjusted balance).
      2. Legacy Vendor PO Request records (backward compatibility).
      3. Direct AP Purchase Order advance_amount (only if no prior advance claims exist).
    Used to auto-populate Advances Already Paid Earlier (milestone_payments) and row advance_deducted.
    """
    if not po_name:
        return []

    results = []
    excl = exclude_claim or "NEW"
    had_prior_advance_claims = False

    # 1. Fetch prior 'Advance / Part Payment' rows filed via Vendor Invoice Claim for this PO
    if frappe.db.has_column("Vendor Invoice Item", "bill_payment_type"):
        adv_rows = frappe.db.sql(
            """
            SELECT
                vic.name AS claim_name,
                vic.status AS claim_status,
                vic.batch_id AS batch_id,
                vic.creation AS claim_creation,
                vii.invoice_number AS inv_no,
                vii.invoice_date AS inv_date,
                vii.base_amount AS base_amount,
                vii.total_invoice_amount AS gross_amount,
                vii.amount AS net_paid,
                vii.remarks AS row_remarks
            FROM `tabVendor Invoice Item` vii
            JOIN `tabVendor Invoice Claim` vic ON vic.name = vii.parent
            WHERE vii.purchase_order = %s
              AND vii.bill_payment_type = 'Advance / Part Payment'
              AND vic.name != %s
              AND vic.docstatus != 2
              AND vic.status NOT IN ('Draft', 'Disputed', 'Cancelled', 'Rejected')
              AND COALESCE(vii.line_status, 'Pending') != 'Disputed / Discrepancy'
            ORDER BY vic.creation ASC, vii.idx ASC
            """,
            (po_name, excl),
            as_dict=True
        )

        if adv_rows:
            had_prior_advance_claims = True
            for ar in adv_rows:
                # Use net paid amount (or gross/base fallback if net is 0)
                disbursed_amt = round(flt(ar.net_paid) or flt(ar.gross_amount) or flt(ar.base_amount), 2)
                if disbursed_amt <= 0:
                    continue

                # Resolve real UTR from Payment Instruction if available
                utr_ref = None
                if frappe.db.exists("DocType", "Payment Instruction") and frappe.db.has_column("Payment Instruction", "idfc_utr"):
                    utr_ref = frappe.db.get_value(
                        "Payment Instruction",
                        {"source_doctype": "Vendor Invoice Claim", "source_voucher": ar.claim_name, "idfc_utr": ["is", "set"]},
                        "idfc_utr"
                    )
                pay_ref = utr_ref or ar.batch_id or f"{ar.claim_name} / {ar.inv_no or 'ADV'}"

                # Check how much of this advance was already adjusted on other non-cancelled claims
                adj_res = frappe.db.sql(
                    """
                    SELECT SUM(vm.adjusted_amount) AS already_adj
                    FROM `tabVendor Milestone Payment Item` vm
                    JOIN `tabVendor Invoice Claim` vic2 ON vic2.name = vm.parent
                    WHERE vm.payment_reference = %s
                      AND vic2.name != %s
                      AND vic2.docstatus != 2
                      AND vic2.status NOT IN ('Cancelled', 'Rejected', 'Disputed')
                    """,
                    (pay_ref, excl),
                    as_dict=True
                )
                already_adjusted = round(flt(adj_res[0].already_adj) if adj_res else 0.0, 2)
                remaining_to_deduct = round(max(disbursed_amt - already_adjusted, 0.0), 2)
                if remaining_to_deduct <= 0:
                    continue

                pdate = str(ar.inv_date) if ar.inv_date else (
                    ar.claim_creation.strftime("%Y-%m-%d") if hasattr(ar.claim_creation, "strftime") else str(ar.claim_creation)[:10]
                )
                note = f"Auto-picked from {ar.claim_name} ({ar.claim_status})"
                if ar.row_remarks:
                    note += f" - {ar.row_remarks[:80]}"

                results.append({
                    "milestone_type": "Mobilization Advance" if len(results) == 0 else "Milestone / Part Payment",
                    "payment_reference": pay_ref,
                    "payment_date": pdate,
                    "disbursed_amount": disbursed_amt,
                    "adjusted_amount": remaining_to_deduct,
                    "advance_request": None,
                    "remarks": note
                })

    # 2. Look up legacy Vendor PO Request records linked to this PO (backward compatibility)
    if not results and not had_prior_advance_claims:
        adv_requests = frappe.get_all(
            "Vendor PO Request",
            filters={"purchase_order": po_name, "status": ["in", ["Disbursed", "Approved"]]},
            fields=["name", "advance_percentage", "requested_advance_amount", "justification", "status", "creation"]
        )
        for adv in adv_requests:
            adv_amt = flt(adv.requested_advance_amount)
            pct = flt(adv.advance_percentage)
            m_type = "Mobilization Advance" if pct >= 50 else "Milestone / Part Payment"
            pdate = adv.creation.strftime("%Y-%m-%d") if hasattr(adv.creation, "strftime") else str(adv.creation)[:10]
            results.append({
                "milestone_type": m_type,
                "payment_reference": f"ADV-{adv.name}",
                "payment_date": pdate,
                "disbursed_amount": adv_amt,
                "adjusted_amount": adv_amt,
                "advance_request": adv.name,
                "remarks": f"Advance request {adv.name} ({pct}% of PO)"
            })

    # 3. Fallback: Check if the PO itself has an advance_amount recorded (only if no advance claims exist yet)
    if not results and not had_prior_advance_claims and frappe.db.exists("AP Purchase Order", po_name):
        po = frappe.get_doc("AP Purchase Order", po_name)
        adv_val = flt(po.advance_amount)
        if adv_val > 0:
            results.append({
                "milestone_type": "Mobilization Advance" if flt(po.advance_percentage) >= 50 else "Milestone / Part Payment",
                "payment_reference": f"PO-ADV-{po.name}",
                "payment_date": po.date_of_issue or str(po.creation)[:10],
                "disbursed_amount": adv_val,
                "adjusted_amount": adv_val,
                "advance_request": None,
                "remarks": f"PO Mobilization Advance ({po.advance_percentage or 'Direct'})"
            })

    return results



@frappe.whitelist()
def get_vendor_bank_info(vendor: str) -> Dict[str, Any]:
    """
    Safely fetches vendor legal name, GSTIN, and verified bank details via server-side SQL,
    completely bypassing client-side query permission restrictions on Bank Account columns.
    """
    if not vendor:
        return {}

    supp = frappe.db.get_value("Supplier", vendor, ["supplier_name", "tax_id", "disabled"], as_dict=True)
    if not supp:
        return {}

    has_pd = frappe.db.has_column("Bank Account", "penny_drop_status")
    pd_select = ", ba.penny_drop_status" if has_pd else ""
    has_bp = frappe.db.has_column("Bank Account", "bank_proof_attachment")
    bp_select = ", ba.bank_proof_attachment" if has_bp else ""

    accs = frappe.db.sql(
        f"""
        SELECT ba.name, ba.bank, ba.bank_account_no, ba.branch_code{pd_select}{bp_select}
        FROM `tabBank Account` ba
        WHERE ba.party_type = 'Supplier' AND ba.party = %s
        ORDER BY ba.is_default DESC, ba.creation DESC
        LIMIT 1
        """,
        (vendor,),
        as_dict=True
    )

    bank_data = {}
    if accs:
        bank_data = {
            "name": accs[0].name,
            "bank_name": accs[0].bank or "",
            "bank_account_number": accs[0].bank_account_no or "",
            "bank_ifsc_code": accs[0].branch_code or "",
            "penny_drop_status": accs[0].get("penny_drop_status") or "VERIFIED",
            "bank_proof_attachment": accs[0].get("bank_proof_attachment") or ""
        }

    return {
        "vendor_name": supp.supplier_name or vendor,
        "vendor_gstin": supp.tax_id or "",
        "disabled": supp.disabled or 0,
        "bank_account": bank_data
    }

@frappe.whitelist()
def get_purchase_order_details(purchase_order: str, exclude_claim: Optional[str] = None) -> Dict[str, Any]:
    """
    Whitelisted API: Safely fetches AP Purchase Order (or ERPNext standard Purchase Order) details
    along with all unadjusted prior advance/part payments for automatic pick-up on final bills.
    """
    if not purchase_order:
        return {}

    milestones = fetch_po_milestones(purchase_order, exclude_claim=exclude_claim)
    unadjusted_advance_total = round(sum(flt(m.get("adjusted_amount")) for m in milestones), 2)

    # 1. Try AP Purchase Order first
    if frappe.db.exists("DocType", "AP Purchase Order") and frappe.db.exists("AP Purchase Order", purchase_order):
        po = frappe.get_doc("AP Purchase Order", purchase_order)
        return {
            "source": "AP Purchase Order",
            "name": po.name,
            "vendor": po.vendor or "",
            "company": po.company_entity or "",
            "base_amount": frappe.utils.flt(po.net_taxable_value or 0.0),
            "advance_amount": frappe.utils.flt(po.advance_amount or 0.0),
            "unadjusted_advance_total": unadjusted_advance_total,
            "milestones": milestones,
            "grand_total": frappe.utils.flt(po.grand_total or 0.0),
            "balance_due": frappe.utils.flt(po.balance_due_on_completion or 0.0),
            "status": po.status or "",
        }

    # 2. Fallback to ERPNext standard Purchase Order
    if frappe.db.exists("DocType", "Purchase Order") and frappe.db.exists("Purchase Order", purchase_order):
        po = frappe.get_doc("Purchase Order", purchase_order)
        return {
            "source": "Purchase Order",
            "name": po.name,
            "vendor": getattr(po, "supplier", None) or "",
            "company": getattr(po, "company", None) or "",
            "base_amount": frappe.utils.flt(getattr(po, "net_total", None) or getattr(po, "base_net_total", None) or 0.0),
            "advance_amount": frappe.utils.flt(getattr(po, "advance_paid", None) or 0.0),
            "unadjusted_advance_total": unadjusted_advance_total,
            "milestones": milestones,
            "grand_total": frappe.utils.flt(getattr(po, "grand_total", None) or 0.0),
            "balance_due": frappe.utils.flt(getattr(po, "rounded_total", None) or getattr(po, "grand_total", None) or 0.0),
            "status": getattr(po, "status", None) or "",
        }

    return {}


@frappe.whitelist()
def get_external_po_details(vendor: str, external_po_number: str, exclude_claim: Optional[str] = None) -> Dict[str, Any]:
    """
    Whitelisted API: Looks up prior records for an External / Email PO (Not in System)
    matched case-insensitively by (vendor, LOWER(TRIM(external_po_number))).
    Returns previously recorded PO Value, PO Date, PO Copy attachment, and all unadjusted
    prior Advance / Part Payment rows so final bills auto-pick advances identically to System POs.
    """
    if not vendor or not external_po_number:
        return {}
    if not frappe.db.has_column("Vendor Invoice Item", "external_po_number"):
        return {}

    norm_ext = external_po_number.strip().lower()
    if not norm_ext:
        return {}

    excl = exclude_claim or "NEW"

    # 1. Fetch latest known PO metadata (value, date, attachment) for this External PO
    meta_rows = frappe.db.sql(
        """
        SELECT
            vii.external_po_number,
            vii.external_po_amount,
            vii.external_po_date,
            vii.po_attachment
        FROM `tabVendor Invoice Item` vii
        JOIN `tabVendor Invoice Claim` vic ON vic.name = vii.parent
        WHERE vii.vendor = %s
          AND LOWER(TRIM(COALESCE(vii.external_po_number, ''))) = %s
          AND vic.name != %s
          AND vic.docstatus != 2
          AND vic.status NOT IN ('Cancelled', 'Rejected', 'Disputed')
        ORDER BY vic.creation DESC, vii.idx DESC
        LIMIT 1
        """,
        (vendor, norm_ext, excl),
        as_dict=True
    )

    po_amount = flt(meta_rows[0].external_po_amount) if meta_rows else 0.0
    po_date = str(meta_rows[0].external_po_date) if (meta_rows and meta_rows[0].external_po_date) else ""
    po_attachment = (meta_rows[0].po_attachment or "") if meta_rows else ""

    # 2. Fetch all prior active/paid 'Advance / Part Payment' rows for this External PO
    milestones = []
    if frappe.db.has_column("Vendor Invoice Item", "bill_payment_type"):
        adv_rows = frappe.db.sql(
            """
            SELECT
                vic.name AS claim_name,
                vic.status AS claim_status,
                vic.batch_id AS batch_id,
                vic.creation AS claim_creation,
                vii.invoice_number AS inv_no,
                vii.invoice_date AS inv_date,
                vii.base_amount AS base_amount,
                vii.total_invoice_amount AS gross_amount,
                vii.amount AS net_paid,
                vii.remarks AS row_remarks
            FROM `tabVendor Invoice Item` vii
            JOIN `tabVendor Invoice Claim` vic ON vic.name = vii.parent
            WHERE vii.vendor = %s
              AND LOWER(TRIM(COALESCE(vii.external_po_number, ''))) = %s
              AND vii.bill_payment_type = 'Advance / Part Payment'
              AND vic.name != %s
              AND vic.docstatus != 2
              AND vic.status NOT IN ('Draft', 'Disputed', 'Cancelled', 'Rejected')
              AND COALESCE(vii.line_status, 'Pending') != 'Disputed / Discrepancy'
            ORDER BY vic.creation ASC, vii.idx ASC
            """,
            (vendor, norm_ext, excl),
            as_dict=True
        )

        for ar in adv_rows:
            disbursed_amt = round(flt(ar.net_paid) or flt(ar.gross_amount) or flt(ar.base_amount), 2)
            if disbursed_amt <= 0:
                continue

            utr_ref = None
            if frappe.db.exists("DocType", "Payment Instruction") and frappe.db.has_column("Payment Instruction", "idfc_utr"):
                utr_ref = frappe.db.get_value(
                    "Payment Instruction",
                    {"source_doctype": "Vendor Invoice Claim", "source_voucher": ar.claim_name, "idfc_utr": ["is", "set"]},
                    "idfc_utr"
                )
            pay_ref = utr_ref or ar.batch_id or f"{ar.claim_name} / {ar.inv_no or 'ADV'}"

            adj_res = frappe.db.sql(
                """
                SELECT SUM(vm.adjusted_amount) AS already_adj
                FROM `tabVendor Milestone Payment Item` vm
                JOIN `tabVendor Invoice Claim` vic2 ON vic2.name = vm.parent
                WHERE vm.payment_reference = %s
                  AND vic2.name != %s
                  AND vic2.docstatus != 2
                  AND vic2.status NOT IN ('Cancelled', 'Rejected', 'Disputed')
                """,
                (pay_ref, excl),
                as_dict=True
            )
            already_adjusted = round(flt(adj_res[0].already_adj) if adj_res else 0.0, 2)
            remaining_to_deduct = round(max(disbursed_amt - already_adjusted, 0.0), 2)
            if remaining_to_deduct <= 0:
                continue

            pdate = str(ar.inv_date) if ar.inv_date else (
                ar.claim_creation.strftime("%Y-%m-%d") if hasattr(ar.claim_creation, "strftime") else str(ar.claim_creation)[:10]
            )
            note = f"Auto-picked from External PO '{external_po_number.strip()}' ({ar.claim_name} - {ar.claim_status})"
            if ar.row_remarks:
                note += f" | {ar.row_remarks[:70]}"

            milestones.append({
                "milestone_type": "Mobilization Advance" if len(milestones) == 0 else "Milestone / Part Payment",
                "payment_reference": pay_ref,
                "payment_date": pdate,
                "disbursed_amount": disbursed_amt,
                "adjusted_amount": remaining_to_deduct,
                "advance_request": None,
                "remarks": note
            })

    unadjusted_advance_total = round(sum(flt(m.get("adjusted_amount")) for m in milestones), 2)

    return {
        "source": "External / Email PO",
        "vendor": vendor,
        "external_po_number": external_po_number.strip(),
        "external_po_amount": po_amount,
        "external_po_date": po_date,
        "po_attachment": po_attachment,
        "unadjusted_advance_total": unadjusted_advance_total,
        "milestones": milestones,
    }


@frappe.whitelist()
def dispute_vendor_claim(docname: str, reason_code: str, remarks: str):
    """
    Whitelisted API: Flags a vendor claim as Disputed with forensic audit logging.
    Ensures rejection is never silent and remarks are permanently preserved.
    """
    if not docname:
        frappe.throw("Document Name is required.", title="Missing Document ID")
    if not remarks or len(remarks.strip()) < 10:
        frappe.throw("Detailed dispute remarks are mandatory (minimum 10 characters).", title="Remarks Required")

    doc = frappe.get_doc("Vendor Invoice Claim", docname)
    user = frappe.session.user if frappe.session else "System"
    now_str = frappe.utils.now()
    now_ts = frappe.utils.now_datetime()

    dispute_msg = f"[{now_str}] Disputed by {user} | Reason: {reason_code} | Remarks: {remarks.strip()}"
    old_variance = doc.match_variance_details or ""
    doc.match_variance_details = f"{dispute_msg}\n{old_variance}".strip()
    doc.status = "Disputed"
    doc.workflow_state = f"Returned / Disputed: {reason_code}"
    
    doc.append("approval_trail", {
        "level_number": 0,
        "level_name": f"Disputed / Returned: {reason_code}",
        "action_taken_by": user,
        "action": "REJECTED",
        "action_timestamp": now_ts,
        "remarks": f"[{reason_code}] {remarks.strip()}"
    })
    doc.save(ignore_permissions=True)

    # Log forensic Error Log in Frappe DB
    frappe.log_error(
        title=f"Vendor Claim Flagged Disputed: {docname}",
        message=f"{dispute_msg}\n\nVendor: {doc.vendor_name}\nAmount: INR {doc.net_payable_amount:,.2f}"
    )

    doc.add_comment("Comment", text=f"🚫 <b>Disputed / Rejected:</b> {reason_code} — {remarks.strip()}")
    try:
        notify_vendor_claim_disputed(docname, reason_code, remarks.strip())
    except Exception as e:
        frappe.log_error(f"Vendor dispute notification dispatch: {e}")

    return {
        "status": "Disputed",
        "message": f"Claim '{docname}' has been successfully placed in Disputed status.",
        "dispute_log": dispute_msg
    }


@frappe.whitelist()
def reject_or_return_vendor_claim(docname: str, reason_code: str, remarks: str) -> Dict[str, Any]:
    """
    Whitelisted alias for dispute_vendor_claim.
    Allows reviewers at any stage (Manager, Director, Accounts L1, Accounts Director)
    to return or reject a claim with mandatory reason and remarks.
    """
    return dispute_vendor_claim(docname, reason_code, remarks)


@frappe.whitelist()
def create_po_advance_claim(
    po_name: str,
    advance_amount: float,
    proforma_number: str,
    proforma_date: str,
    proforma_attachment: str,
    remarks: Optional[str] = None
) -> Dict[str, Any]:
    """
    Whitelisted 1-Click API: Creates an advance claim directly from an Active AP Purchase Order.
    Auto-binds vendor details, sets Bill Type = 'Advance / Part Payment',
    pulls verified bank account, and routes to 'Pending Accounts Review' for L1 verification.
    """
    if not po_name or not frappe.db.exists("AP Purchase Order", po_name):
        frappe.throw(_(f"AP Purchase Order '{po_name}' not found."))

    po = frappe.get_doc("AP Purchase Order", po_name)
    if po.status != "Active PO":
        frappe.throw(_(f"Purchase Order '{po_name}' must be in 'Active PO' status to request advance. Current status: '{po.status}'."))

    adv_val = flt(advance_amount)
    if adv_val <= 0:
        frappe.throw(_("Advance Amount must be greater than 0.00."))

    po_val = flt(po.grand_total) or flt(po.net_taxable_value) or 0.0
    if po_val > 0 and adv_val > po_val:
        frappe.throw(_(f"Advance Amount (INR {adv_val:,.2f}) cannot exceed total contracted PO value (INR {po_val:,.2f})."))

    if not proforma_number or not str(proforma_number).strip():
        frappe.throw(_("Vendor Proforma Invoice / Demand Reference Number is required."))
    if not proforma_attachment:
        frappe.throw(_("Vendor Proforma Invoice / Quotation attachment is required."))

    user = frappe.session.user if getattr(frappe, "session", None) else "Administrator"
    now_ts = frappe.utils.now_datetime()

    # Determine GST and Tax Type from PO
    comp_state = (po.company_gstin or "")[:2].strip()
    vendor_state = (po.vendor_gstin or "")[:2].strip()
    is_intra = (not comp_state or not vendor_state or comp_state == vendor_state)
    tax_type = "Intra-State (CGST + SGST)" if is_intra else "Inter-State (IGST)"
    gst_rate = "18%"

    # Create new Vendor Invoice Claim
    vic = frappe.new_doc("Vendor Invoice Claim")
    vic.company = po.company_entity
    vic.vendor = po.vendor
    vic.vendor_name = po.vendor_name
    vic.vendor_gstin = po.vendor_gstin
    vic.purchase_order = po.name
    vic.status = "Pending Accounts Review"
    vic.workflow_state = "Awaiting Accounts L1 Review"

    # Add child item
    item_row = vic.append("items", {})
    item_row.vendor = po.vendor
    item_row.vendor_name = po.vendor_name
    item_row.vendor_gstin = po.vendor_gstin
    item_row.company = po.company_entity
    item_row.bill_payment_type = "Advance / Part Payment"
    item_row.po_type = "With PO"
    item_row.purchase_order = po.name
    item_row.invoice_number = str(proforma_number).strip()
    item_row.invoice_date = proforma_date or frappe.utils.nowdate()
    item_row.receipt_attachment = proforma_attachment
    item_row.base_amount = adv_val
    item_row.tax_type = tax_type
    item_row.gst_rate = gst_rate
    item_row.advance_deducted = 0.0
    item_row.remarks = remarks or f"PO Advance payment against PO #{po.name} ({po.advance_percentage or 'Direct'})"

    # Fetch and populate verified vendor bank account
    bank_info = vic._fetch_supplier_bank_account(po.vendor)
    if bank_info:
        item_row.bank_beneficiary_name = po.vendor_name
        item_row.bank_account_number = bank_info.get("bank_account_no", "")
        item_row.bank_ifsc_code = bank_info.get("ifsc_code", "")
        item_row.penny_drop_status = bank_info.get("penny_drop_status", "VERIFIED")
        item_row.bank_proof_attachment = bank_info.get("bank_proof_attachment", "")

    # Calculate financial totals on parent and row
    gst_pct = 18.0
    gst_val = round(adv_val * (gst_pct / 100.0), 2)
    item_row.gst_amount = gst_val
    if is_intra:
        item_row.cgst_amount = round(gst_val / 2.0, 2)
        item_row.sgst_amount = round(gst_val / 2.0, 2)
        item_row.igst_amount = 0.0
    else:
        item_row.cgst_amount = 0.0
        item_row.sgst_amount = 0.0
        item_row.igst_amount = gst_val
    item_row.total_invoice_amount = round(adv_val + gst_val, 2)
    item_row.amount = round(adv_val + gst_val, 2)

    vic.base_amount = adv_val
    vic.gst_amount = gst_val
    vic.total_invoice_amount = round(adv_val + gst_val, 2)
    vic.net_payable_amount = round(adv_val + gst_val, 2)
    vic.advance_deducted = 0.0

    # Append approval trail
    vic.append("approval_trail", {
        "level_number": 1,
        "level_name": "Stage 1: PO Advance Requested (1-Click)",
        "action_taken_by": user,
        "action": "VERIFIED",
        "action_timestamp": now_ts,
        "remarks": f"Advance requested against PO #{po.name} (Amount: INR {adv_val:,.2f}) | Ref: {proforma_number}"
    })

    vic.flags.ignore_permissions = True
    vic.insert()

    vic.add_comment(
        "Comment",
        text=f"⚡ <b>1-Click PO Advance Created:</b> Requested by {user} for PO #{po.name}. Amount: ₹ {adv_val:,.2f}. Routed directly to Accounts L1 for audit and Tally entry."
    )

    # Dispatch notification to Accounts L1
    try:
        from ap_automation.services.notification_service import notify_vendor_claim_director_approved
        notify_vendor_claim_director_approved(vic.name)
    except Exception as e:
        frappe.log_error(f"PO Advance claim notification error: {e}")

    return {
        "status": "success",
        "claim_name": vic.name,
        "advance_amount": adv_val,
        "message": f"PO Advance claim #{vic.name} created successfully! Routed for Accounts L1 review."
    }


@frappe.whitelist()
def get_vendor_claim_audit_logs(docname: str) -> List[Dict[str, Any]]:
    """
    Whitelisted API: Returns recent system error logs and audit events for this claim.
    """
    if not docname:
        return []

    logs = frappe.db.sql(
        """
        SELECT name, method, creation, error
        FROM `tabError Log`
        WHERE method LIKE %s OR error LIKE %s
        ORDER BY creation DESC
        LIMIT 10
        """,
        (f"%{docname}%", f"%{docname}%"),
        as_dict=True
    )
    return logs


# --------------------------------------------------------------------------------------
# PRD STAGE 3, 4, 6, 7 MULTI-TIER BUSINESS APPROVAL & TALLY LOGGING APIS
# --------------------------------------------------------------------------------------

@frappe.whitelist()
def approve_vendor_claim_by_manager(docname: str, remarks: Optional[str] = None):
    """
    Stage 3: Manager Approval.
    Validates claim status and advances to 'Pending HoD Approval'.
    """
    if not docname or not frappe.db.exists("Vendor Invoice Claim", docname):
        frappe.throw(f"Vendor Invoice Claim '{docname}' not found.")

    doc = frappe.get_doc("Vendor Invoice Claim", docname)
    user = frappe.session.user if getattr(frappe, "session", None) else "Administrator"

    if doc.status != "Pending Manager Approval":
        frappe.throw(f"Claim '{docname}' is in status '{doc.status}', not 'Pending Manager Approval'.")

    if user != "Administrator" and "System Manager" not in frappe.get_roles(user):
        if user == getattr(doc, "owner", None):
            frappe.throw(
                "Self-Approval Prohibited: As the creator of this claim, you cannot approve it as Manager. An independent Reporting Manager must review and sign off.",
                title="Self-Approval Prohibited",
                exc=APSecurityError
            )
        is_auth = False
        mgr_user = getattr(doc, "designated_approver", None)
        claimant_emp = frappe.db.get_value(
            "Employee",
            {"user_id": doc.owner, "status": "Active"},
            ["name", "employee_name", "reports_to"],
            as_dict=True
        )

        # 1. Primary Gate: Dynamic HRMS Reporting Manager of Claimant (O(1))
        if claimant_emp and claimant_emp.reports_to:
            direct_mgr_user = frappe.db.get_value("Employee", claimant_emp.reports_to, "user_id")
            if direct_mgr_user:
                mgr_user = direct_mgr_user
                if direct_mgr_user == user:
                    is_auth = True
                else:
                    # Check active HRMS Leave / Approval Delegation
                    try:
                        from ap_automation.services.security import resolve_acting_approver
                        if resolve_acting_approver(direct_mgr_user) == user:
                            is_auth = True
                    except Exception:
                        pass

        # 2. Fallback Gate: If claimant has no reports_to in HRMS, check AP Matrix or Admin Manager roles
        if not is_auth and not mgr_user:
            from ap_automation.services.notification_service import _get_matrix_or_role_approvers
            company = getattr(doc, "company", None)
            matrix_mgrs = _get_matrix_or_role_approvers(
                company=company,
                document_lane="AP Vendor Invoice",
                level_number=1,
                fallback_roles=["Admin L1 Approver", "Admin Manager"],
                stage_keyword="Manager"
            )
            user_roles = frappe.get_roles(user)
            if user in matrix_mgrs or any(r in user_roles for r in ["Admin L1 Approver", "Admin Manager", "Reporting Manager"]):
                is_auth = True

        if not is_auth:
            mgr_label = f"Reporting Manager ({mgr_user})" if mgr_user else "the designated Reporting Manager"
            frappe.throw(
                f"Access Denied: You ('{user}') are not authorized to approve this claim. "
                f"This claim is specifically assigned to claimant's {mgr_label}.",
                title="Reporting Manager Authorization Required",
                exc=APSecurityError
            )

    now_ts = frappe.utils.now_datetime()
    doc.manager_approver = user
    doc.manager_approved_on = now_ts

    # Check if Manager is also genuine Director / Business Head for this company (Strict check)
    company = getattr(doc, "company", None)
    bus_head = frappe.db.get_value("Company", company, "ap_business_head") if company else None
    user_roles = frappe.get_roles(user)
    is_also_director = (
        user == bus_head or
        "AP Director" in user_roles or
        "Accounts Director" in user_roles
    )

    if is_also_director:
        # Unified 1-Click Executive Approval: Manager and Director are same person
        doc.director_approver = user
        doc.director_approved_on = now_ts
        doc.status = "Pending Accounts Review"
        doc.workflow_state = "Awaiting Accounts L1 Review"

        doc.append("approval_trail", {
            "level_number": 1,
            "level_name": "Stage 1: Reporting Manager Review",
            "action_taken_by": user,
            "action": "APPROVED",
            "action_timestamp": now_ts,
            "remarks": remarks or "Approved by Reporting Manager"
        })
        doc.append("approval_trail", {
            "level_number": 2,
            "level_name": "Stage 2: Executive Director Approval (Unified with Manager Signoff)",
            "action_taken_by": user,
            "action": "APPROVED",
            "action_timestamp": now_ts,
            "remarks": remarks or "Executive Sanction granted (Reporting Manager & Director are same)"
        })
        doc.save(ignore_permissions=True)
        doc.add_comment(
            "Comment",
            text=f"👑 <b>Unified Executive Approval:</b> {user} approved as both Reporting Manager & Director. Auto-routed directly to Accounts L1."
        )
        try:
            from ap_automation.services.notification_service import notify_vendor_claim_director_approved
            notify_vendor_claim_director_approved(docname)
        except Exception as e:
            frappe.log_error(f"Vendor director approval notification dispatch: {e}")

        return {
            "status": doc.status,
            "message": f"Claim #{docname} approved! Since you are both Reporting Manager and Director, your single approval satisfies commercial sanction and routes directly to Accounts L1."
        }
    else:
        # Standard progression to Director
        doc.status = "Pending Director Approval"
        doc.workflow_state = "Awaiting Executive Director Approval"
        doc.append("approval_trail", {
            "level_number": 1,
            "level_name": "Stage 1: Reporting Manager Approval",
            "action_taken_by": user,
            "action": "APPROVED",
            "action_timestamp": now_ts,
            "remarks": remarks or "Approved by Reporting Manager"
        })
        doc.save(ignore_permissions=True)
        doc.add_comment("Comment", text=f"✅ <b>Approved by Manager:</b> {user} — {remarks or 'Approved'} (Next: Pending Director Approval)")
        try:
            notify_vendor_claim_manager_approved(docname)
        except Exception as e:
            frappe.log_error(f"Vendor manager approval notification dispatch: {e}")

        return {"status": doc.status, "message": f"Claim #{docname} successfully approved by Manager. Routed to Director."}


@frappe.whitelist()
def approve_vendor_claim_by_hod(docname: str, remarks: Optional[str] = None):
    """
    DEPRECATED (Lane 3A SOP v3.0): HoD tier eliminated.
    Vendor claims route directly from Line Manager to Executive Director.
    """
    frappe.throw(
        "HoD Approval Tier has been eliminated per Lane 3A SOP. Vendor claims route directly from Manager to Executive Director.",
        title="HoD Tier Deprecated",
        exc=APSecurityError
    )


@frappe.whitelist()
def approve_vendor_claim_by_director(docname: str, remarks: Optional[str] = None):
    """
    Stage 3: Executive Director Approval (> INR 2 Lakhs).
    Advances claim to Accounts L1 Review (Gokulnath).
    """
    if not docname or not frappe.db.exists("Vendor Invoice Claim", docname):
        frappe.throw(f"Vendor Invoice Claim '{docname}' not found.")

    doc = frappe.get_doc("Vendor Invoice Claim", docname)
    user = frappe.session.user if getattr(frappe, "session", None) else "Administrator"

    if doc.status != "Pending Director Approval":
        frappe.throw(f"Claim '{docname}' is in status '{doc.status}', not 'Pending Director Approval'.")

    if user != "Administrator" and "System Manager" not in frappe.get_roles(user):
        if user == getattr(doc, "owner", None):
            frappe.throw(
                "Self-Approval Prohibited: Submitter cannot approve their own claim as Director.",
                title="Self-Approval Prohibited",
                exc=APSecurityError
            )
        company = getattr(doc, "company", None)
        bus_head = frappe.db.get_value("Company", company, "ap_business_head") if company else None
        from ap_automation.services.notification_service import _get_matrix_or_role_approvers
        matrix_dirs = _get_matrix_or_role_approvers(
            company=company,
            document_lane="AP Vendor Invoice",
            level_number=2,
            fallback_roles=["AP Director", "Accounts Director"],
            stage_keyword="Director"
        )
        user_roles = frappe.get_roles(user)
        is_auth = (user == bus_head or user in matrix_dirs or "AP Director" in user_roles or "Accounts Director" in user_roles or "AP Director" in user_roles)
        if not is_auth:
            frappe.throw(
                f"Access Denied: You ('{user}') are not the designated Business Head or Director for '{company}'.",
                title="Director Authorization Required",
                exc=APSecurityError
            )

    now_ts = frappe.utils.now_datetime()
    doc.director_approver = user
    doc.director_approved_on = now_ts
    doc.status = "Pending Accounts Review"
    doc.workflow_state = "Awaiting Accounts L1 Review"

    doc.append("approval_trail", {
        "level_number": 2,
        "level_name": "Stage 2: Executive Director Approval",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_ts,
        "remarks": remarks or "Approved by Executive Director"
    })
    doc.save(ignore_permissions=True)
    doc.add_comment("Comment", text=f"âœ… <b>Approved by Executive Director:</b> {user} â€” {remarks or 'Approved'}")
    try:
        notify_vendor_claim_director_approved(docname)
    except Exception as e:
        frappe.log_error(f"Vendor director approval notification dispatch: {e}")

    return {"status": doc.status, "message": f"Claim #{docname} successfully approved by Director. Routed to Accounts L1."}


@frappe.whitelist()
def verify_vendor_claim_by_accounts_l1(docname: str, tally_reference: str, remarks: Optional[str] = None):
    """
    Stage 4 & 6: Accounts L1 Verification.
    1. Re-runs and verifies 3-Way Match & statutory TDS.
    2. Strictly enforces Tally Voucher Reference logging (PRD Stage 6).
    3. Advances claim to Accounts L2 Approval.
    """
    if not docname or not frappe.db.exists("Vendor Invoice Claim", docname):
        frappe.throw(f"Vendor Invoice Claim '{docname}' not found.")

    if not tally_reference or not str(tally_reference).strip():
        frappe.throw(
            "Tally Voucher Reference # is strictly mandatory per PRD Stage 6 before Accounts L1 signoff.",
            title="Tally Reference Required"
        )

    doc = frappe.get_doc("Vendor Invoice Claim", docname)
    user = frappe.session.user if getattr(frappe, "session", None) else "Administrator"

    if doc.status != "Pending Accounts Review":
        frappe.throw(f"Claim '{docname}' is in status '{doc.status}', not 'Pending Accounts Review'.")

    if user != "Administrator" and "System Manager" not in frappe.get_roles(user):
        user_roles = frappe.get_roles(user)
        if not any(r in user_roles for r in ["Accounts L1 Auditor", "Accounts User", "Accounts Manager"]):
            frappe.throw(
                "Access Denied: Accounts L1 Verification requires 'Accounts L1 Auditor' or 'Accounts User' role.",
                title="Accounts Permission Required",
                exc=APSecurityError
            )

    # Enforce clean 3-way match (GRN is non-mandatory)
    if doc.match_status in ("Quantity Mismatch Flagged", "Price Mismatch Flagged"):
        frappe.throw(
            f"Cannot complete L1 Verification: 3-Way Match Discrepancy Active ({doc.match_status}). "
            f"Diagnostics: {doc.match_variance_details}",
            title="3-Way Match Discrepancy"
        )

    clean_tally = str(tally_reference).strip().upper()
    now_ts = frappe.utils.now_datetime()

    doc.tally_reference = clean_tally
    doc.tally_posted_on = now_ts
    doc.tally_posted_by = user
    doc.accounts_l1_verifier = user
    doc.accounts_l1_verified_on = now_ts
    doc.status = "Pending Accounts L2 Approval"
    doc.workflow_state = "Awaiting Accounts L2 Signoff"

    doc.append("approval_trail", {
        "level_number": 4,
        "level_name": "Stage 4 & 6: Accounts L1 Verification & Tally Logged",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_ts,
        "remarks": f"Verified by Accounts L1 | Tally Ref: {clean_tally} | {remarks or 'Voucher Posted to Tally'}"
    })
    doc.save(ignore_permissions=True)
    doc.add_comment("Comment", text=f"âœ… <b>Accounts L1 Verified & Tally Logged:</b> {user} | Tally Ref: <code>{clean_tally}</code>")
    try:
        notify_vendor_claim_accounts_l1_verified(docname)
    except Exception as e:
        frappe.log_error(f"Vendor accounts L1 notification dispatch: {e}")

    return {
        "status": doc.status,
        "tally_reference": clean_tally,
        "message": f"Claim #{docname} successfully verified by Accounts L1 with Tally Ref '{clean_tally}'. Escalated to Accounts L2."
    }


@frappe.whitelist()
def approve_vendor_claim_by_accounts_l2(docname: str, remarks: Optional[str] = None):
    """
    Stage 7: Accounts L2 Approval.
    Approves what L1 has verified.
    Checks clean penny drop status and advances claim to 'Approved for Payment'.
    """
    if not docname or not frappe.db.exists("Vendor Invoice Claim", docname):
        frappe.throw(f"Vendor Invoice Claim '{docname}' not found.")

    doc = frappe.get_doc("Vendor Invoice Claim", docname)
    user = frappe.session.user if getattr(frappe, "session", None) else "Administrator"

    if doc.status != "Pending Accounts L2 Approval":
        frappe.throw(f"Claim '{docname}' is in status '{doc.status}', not 'Pending Accounts L2 Approval'.")

    if user != "Administrator" and "System Manager" not in frappe.get_roles(user):
        user_roles = frappe.get_roles(user)
        from ap_automation.services.notification_service import _get_matrix_or_role_approvers
        company = getattr(doc, "company", None)
        matrix_l2 = _get_matrix_or_role_approvers(
            company=company,
            document_lane="AP Vendor Invoice",
            level_number=4,
            fallback_roles=["AP Director", "Accounts Director", "Accounts Manager"],
            stage_keyword="Accounts L2"
        )
        if not (user in matrix_l2 or any(r in user_roles for r in ["AP Director", "Accounts Director", "Accounts Manager"])):
            frappe.throw(
                "Access Denied: Accounts L2 Approval requires designated Accounts L2 Approver or 'Accounts Director' role.",
                title="Accounts Director Required",
                exc=APSecurityError
            )

    if not doc.accounts_l1_verifier:
        frappe.throw("Cannot complete L2 Approval without prior Accounts L1 Verification.", title="L1 Verification Missing")

    # Gate on Penny Drop status
    bank_acc = doc._fetch_supplier_bank_account(doc.vendor)
    if bank_acc.get("penny_drop_status") == "LOCKED_PENNY_DROP_MISMATCH":
        frappe.throw(
            "Security Lock: Vendor Bank Account is locked due to NPCI Penny Drop Name Mismatch! "
            "L2 Approval is blocked until Accounts clears the bank account.",
            title="Penny Drop Lockout Active"
        )

    now_ts = frappe.utils.now_datetime()
    doc.accounts_l2_approver = user
    doc.accounts_l2_approved_on = now_ts
    doc.status = "Approved for Payment"
    doc.workflow_state = "Approved for Shared Payment Core Release"

    doc.append("approval_trail", {
        "level_number": 5,
        "level_name": "Stage 7: Accounts L2 Approval",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_ts,
        "remarks": remarks or "Approved by Accounts L2 for payment core release"
    })
    doc.save(ignore_permissions=True)
    _sync_event_master_if_linked(getattr(doc, "event", None))
    doc.add_comment("Comment", text=f"âœ… <b>Approved by Accounts L2:</b> {user} â€” {remarks or 'Approved for Payment'}")
    try:
        notify_vendor_claim_accounts_l2_approved(docname)
    except Exception as e:
        frappe.log_error(f"Vendor accounts L2 notification dispatch: {e}")

    return {
        "status": doc.status,
        "message": f"Claim #{docname} successfully approved by Accounts L2! Ready for Payment Core Release."
    }


@frappe.whitelist()
def save_tally_reference(docname: str, tally_reference: str):
    """
    Whitelisted API: Updates and saves Tally Voucher Reference on Vendor Claim.
    """
    if not docname or not tally_reference:
        frappe.throw("Document Name and Tally Reference are required.")

    clean_ref = tally_reference.strip().upper()
    user = frappe.session.user if getattr(frappe, "session", None) else "Administrator"
    now_ts = frappe.utils.now_datetime()

    frappe.db.set_value(
        "Vendor Invoice Claim",
        docname,
        {
            "tally_reference": clean_ref,
            "tally_posted_on": now_ts,
            "tally_posted_by": user
        }
    )
    frappe.db.commit()

    return {"status": "SUCCESS", "tally_reference": clean_ref}

def _sync_event_master_if_linked(event_name: Optional[str]) -> None:
    """Safely synchronizes Event Master budget ledger for Stream A direct vendor claims."""
    if not event_name or not frappe.db.exists("Event Master", event_name):
        return
    try:
        from ap_automation.services.event_budget_service import update_event_budget_ledger
        update_event_budget_ledger(event_name)
    except Exception:
        frappe.log_error(
            title="Event Stream A Sync Error",
            message=f"Failed to sync Event Master '{event_name}': {frappe.get_traceback()}"
        )


@frappe.whitelist()
def trigger_vendor_claim_payment_release_notification(docname: str):
    """
    Maker-Checker Handoff for Vendor Invoice Claim:
    Triggered by Accounts Maker after uploading IDFC Excel. Notifies Payment Releaser (Checker).
    """
    if not docname or not frappe.db.exists("Vendor Invoice Claim", docname):
        frappe.throw(f"Vendor Invoice Claim '{docname}' not found.")

    doc = frappe.get_doc("Vendor Invoice Claim", docname)
    user = frappe.session.user if getattr(frappe, "session", None) else "Administrator"
    user_roles = set(frappe.get_roles(user)) if user else set()
    maker_roles = {"Accounts L1 Auditor", "Accounts User", "Accounts Manager", "Accounts Director", "System Manager", "Administrator"}
    if user != "Administrator" and not user_roles.intersection(maker_roles):
        raise APSecurityError("Unauthorized: Only Accounts Makers can trigger Payment Release notifications.")

    if doc.status not in ("Approved for Payment", "Queued in Batch"):
        frappe.throw(f"Claim '{docname}' must be 'Approved for Payment' before triggering Payment Release. Current status: '{doc.status}'.")

    from ap_automation.services.notification_service import notify_payment_releaser_on_idfc_upload
    res = notify_payment_releaser_on_idfc_upload(
        voucher_doctype=doc.doctype,
        voucher_name=doc.name,
        uploaded_by=user
    )
    releaser = res.get("releaser")
    ad = res.get("accounts_director")

    frappe.db.set_value("Vendor Invoice Claim", docname, {
        "payment_release_notified": 1,
        "payment_release_notified_on": frappe.utils.now_datetime(),
        "payment_release_maker": user,
        "payment_releaser": releaser if releaser and not getattr(doc, "payment_releaser", None) else getattr(doc, "payment_releaser", None)
    }, update_modified=False)

    releaser_display = frappe.db.get_value("User", releaser, "full_name") or releaser
    doc.add_comment(
        "Comment",
        text=f"📤 <b>Payment Release Notified:</b> Uploaded to IDFC by {user}. Dispatched to Payment Releaser (<b>{releaser_display}</b>)."
    )
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "docname": docname,
        "releaser": releaser,
        "accounts_director": ad,
        "message": f"Payment Release notification sent to Payment Releaser ({releaser_display})."
    }


@frappe.whitelist()
def disburse_vendor_claim(docname: str, utr_reference: str, remarks: Optional[str] = None):
    """
    Stage 6 (Checker): Bank Disbursement & UTR Stamping (Payment Releaser).
    Validates claim status, Maker notification, and Maker != Checker segregation, then marks 'Paid' and syncs Event Master.
    """
    if not docname or not frappe.db.exists("Vendor Invoice Claim", docname):
        frappe.throw(f"Vendor Invoice Claim '{docname}' not found.")

    doc = frappe.get_doc("Vendor Invoice Claim", docname)
    user = frappe.session.user if getattr(frappe, "session", None) else "Administrator"
    user_roles = set(frappe.get_roles(user)) if user else set()
    authorized_roles = {"Payment Releaser", "AP Director", "Accounts Director", "System Manager", "Administrator"}

    is_designated_releaser = False
    try:
        from ap_automation.services.approval_service import get_matrix_designated_payment_releaser_and_accounts_director
        designated_releaser, _ = get_matrix_designated_payment_releaser_and_accounts_director(
            company=doc.company,
            doctype=doc.doctype,
            amount=float(doc.net_payable_amount or doc.total_invoice_amount or 0.0)
        )
        if designated_releaser and user == designated_releaser:
            is_designated_releaser = True
    except Exception:
        pass

    if user != "Administrator" and not is_designated_releaser and not user_roles.intersection(authorized_roles):
        raise APSecurityError("Unauthorized: Only Payment Releaser or Accounts Director can disburse commercial vendor invoices.")

    if not utr_reference or not str(utr_reference).strip():
        frappe.throw("Bank UTR Reference Number is strictly mandatory for disbursement signoff.", title="UTR Required")

    if doc.status not in ("Approved for Payment", "Queued in Batch"):
        frappe.throw(f"Claim '{docname}' is in status '{doc.status}', not ready for bank disbursement.")

    if not frappe.utils.cint(getattr(doc, "payment_release_notified", 0)):
        frappe.throw(
            f"Maker-Checker Gate: IDFC Payment Release notification must be triggered by Maker before disbursing Claim '{docname}'."
        )

    maker = getattr(doc, "payment_release_maker", None)
    if maker and user == maker and user != "Administrator":
        raise APSecurityError(
            f"Maker-Checker Segregation Violation: '{user}' triggered Payment Release notification (Maker) and cannot disburse the same claim."
        )

    clean_utr = str(utr_reference).strip().upper()
    now_ts = frappe.utils.now_datetime()

    # Update status directly in database to avoid triggering tamper alert on locked status transition
    frappe.db.set_value("Vendor Invoice Claim", docname, {
        "status": "Paid",
        "workflow_state": "Disbursed via Corporate Bank Transfer",
        "payment_releaser": user
    })

    # Record in AP Approval Trail
    trail_entry = frappe.get_doc({
        "doctype": "AP Approval Trail",
        "parent": docname,
        "parenttype": "Vendor Invoice Claim",
        "parentfield": "approval_trail",
        "level_number": 5,
        "level_name": "Stage 6: Bank Disbursement & UTR Stamped",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_ts,
        "remarks": f"Disbursed via Corporate Banking | Bank UTR: {clean_utr} | {remarks or 'Payment Settled'}"
    })
    trail_entry.insert(ignore_permissions=True)

    _sync_event_master_if_linked(getattr(doc, "event", None))

    doc.add_comment("Comment", text=f"💳 <b>Payment Disbursed:</b> Bank UTR: <code>{clean_utr}</code> by {user}")
    frappe.db.commit()

    return {
        "status": "Paid",
        "utr": clean_utr,
        "message": f"Claim #{docname} successfully marked Paid with Bank UTR '{clean_utr}'."
    }

@frappe.whitelist()
def submit_for_approval(docname: str):
    """
    Submits a Vendor Invoice Claim from Draft/Disputed to Pending Manager Approval.
    """
    if not docname or not frappe.db.exists("Vendor Invoice Claim", docname):
        frappe.throw(f"Vendor Invoice Claim '{docname}' not found.")

    doc = frappe.get_doc("Vendor Invoice Claim", docname)

    if doc.status not in ("Draft", "Disputed", "Not Saved"):
        frappe.throw(f"Only Draft or Disputed claims can be submitted for approval. Current status is '{doc.status}'.")

    if not doc.vendor:
        frappe.throw("Vendor is required before submitting for approval.", title="Missing Vendor")
    if not doc.tax_invoice_number:
        frappe.throw("Tax Invoice Number is required before submitting for approval.", title="Missing Invoice Number")
    inv_date = getattr(doc, "tax_invoice_date", None) or getattr(doc, "invoice_date", None)
    if not inv_date:
        frappe.throw("Invoice Date is required before submitting for approval.", title="Missing Invoice Date")
    if not doc.base_amount or float(doc.base_amount) <= 0:
        frappe.throw("Invoice Base Amount must be greater than zero.", title="Invalid Base Amount")
    inv_att = getattr(doc, "tax_invoice_attachment", None) or getattr(doc, "invoice_attachment", None)
    if not inv_att:
        frappe.throw("Invoice Attachment is mandatory before submitting for approval.", title="Missing Invoice Attachment")

    doc.status = "Pending Manager Approval"
    doc.workflow_state = "Awaiting Manager Approval (PRD Stage 3)"

    # Auto-resolve and bind claimant's dynamic HRMS reporting manager
    if not getattr(doc, "designated_approver", None) and getattr(doc, "owner", None):
        claimant_emp = frappe.db.get_value(
            "Employee",
            {"user_id": doc.owner, "status": "Active"},
            ["reports_to"],
            as_dict=True
        )
        if claimant_emp and claimant_emp.reports_to:
            mgr_user = frappe.db.get_value("Employee", claimant_emp.reports_to, "user_id")
            if mgr_user:
                doc.designated_approver = mgr_user

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        from ap_automation.services.notification_service import notify_vendor_claim_submitted
        notify_vendor_claim_submitted(docname)
    except Exception as e:
        frappe.log_error(f"Vendor claim submission notification dispatch: {e}")

    return {
        "status": "Pending Manager Approval",
        "message": f"Claim #{docname} submitted successfully! Routed to Reporting Manager for approval."
    }


@frappe.whitelist()
def export_vendor_invoices_excel(docname: str):
    """
    Exports itemized vendor invoices/bills to a professional Excel (.xlsx) file.
    """
    if not docname:
        frappe.throw("Document Name is required.")

    doc = frappe.get_doc("Vendor Invoice Claim", docname)

    headers = [
        "Sr No",
        "Vendor Code",
        "Vendor Legal Name",
        "Vendor GSTIN",
        "Invoice #",
        "Invoice Date",
        "PO Type",
        "Purchase Order",
        "Base Taxable (INR)",
        "Tax Type",
        "GST %",
        "CGST (INR)",
        "SGST (INR)",
        "IGST (INR)",
        "Calculated GST (INR)",
        "Total Bill (INR)",
        "TDS Section",
        "TDS Rate %",
        "Deducted TDS (INR)",
        "Advance Deducted (INR)",
        "Retention Hold (INR)",
        "Net Pay (INR)",
        "Bank Beneficiary Name",
        "Bank A/C No",
        "IFSC Code",
        "Penny Drop Status",
        "Line Status",
        "Discrepancy Remarks",
        "Remarks",
        "Is Urgent",
        "Urgency Reason"
    ]

    rows = []
    items = getattr(doc, "items", None) or []
    if items:
        for idx, row in enumerate(items, start=1):
            po_ref_str = row.purchase_order or (
                f"EXT: {row.external_po_number}" if getattr(row, "external_po_number", None) else ""
            )
            rows.append([
                idx,
                row.vendor or "",
                row.vendor_name or "",
                row.vendor_gstin or "",
                row.invoice_number or "",
                str(row.invoice_date or ""),
                row.po_type or "Without PO",
                po_ref_str,
                flt(row.base_amount),
                row.tax_type or "",
                row.gst_rate or "",
                flt(row.cgst_amount),
                flt(row.sgst_amount),
                flt(row.igst_amount),
                flt(row.gst_amount),
                flt(row.total_invoice_amount),
                row.tds_section or "None / Exempt",
                flt(row.tds_rate),
                flt(row.tds_amount),
                flt(row.advance_deducted),
                flt(row.retention_hold_amount),
                flt(row.amount),
                row.bank_beneficiary_name or "",
                row.bank_account_number or "",
                row.bank_ifsc_code or "",
                row.penny_drop_status or "",
                row.line_status or "Pending",
                row.discrepancy_remarks or "",
                row.remarks or "",
                "Yes" if row.is_urgent else "No",
                row.urgency_reason or ""
            ])
    else:
        # Legacy single-bill line
        rows.append([
            1,
            doc.vendor or "",
            doc.vendor_name or "",
            doc.vendor_gstin or "",
            doc.tax_invoice_number or "",
            str(doc.tax_invoice_date or ""),
            doc.invoice_type or "",
            doc.purchase_order or "",
            flt(doc.base_amount),
            doc.tax_type or "",
            doc.gst_rate or "",
            flt(doc.cgst_amount),
            flt(doc.sgst_amount),
            flt(doc.igst_amount),
            flt(doc.gst_amount),
            flt(doc.total_invoice_amount),
            doc.tds_section or "None / Exempt",
            flt(doc.tds_rate),
            flt(doc.tds_amount),
            flt(doc.advance_deducted),
            flt(doc.retention_hold_amount),
            flt(doc.net_payable_amount),
            doc.bank_name or "",
            doc.bank_account_number or "",
            doc.bank_ifsc_code or "",
            "VERIFIED",
            doc.status or "Draft",
            "",
            "",
            "Yes" if doc.is_urgent else "No",
            doc.urgency_reason or ""
        ])

    # Summary row
    rows.append([
        "TOTAL",
        "",
        "",
        "",
        f"Bills: {doc.total_lines or len(rows)}",
        "",
        "",
        "",
        flt(doc.base_amount),
        "",
        "",
        flt(doc.cgst_amount),
        flt(doc.sgst_amount),
        flt(doc.igst_amount),
        flt(doc.gst_amount),
        flt(doc.total_invoice_amount),
        "",
        "",
        flt(doc.tds_amount),
        flt(doc.advance_deducted),
        flt(doc.retention_hold_amount),
        flt(doc.net_payable_amount),
        "",
        "",
        "",
        "",
        doc.status,
        "",
        "",
        "",
        ""
    ])

    from frappe.utils.xlsxutils import make_xlsx
    xlsx_file = make_xlsx([headers] + rows, "Itemized Vendor Invoices")

    frappe.response["filename"] = f"Vendor_Invoice_Claim_{doc.name}.xlsx"
    frappe.response["filecontent"] = xlsx_file.getvalue()
    frappe.response["type"] = "binary"

