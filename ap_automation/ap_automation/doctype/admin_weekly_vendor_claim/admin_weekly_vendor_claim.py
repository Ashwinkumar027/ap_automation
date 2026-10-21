# Copyright (c) 2026, Quanti and contributors
# Enterprise Admin Weekly Vendor Claim Controller (Petty-Cash-Style Multi-Row Architecture)

import io
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, flt, get_url, now_datetime
from frappe.utils.xlsxutils import make_xlsx
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.services.approval_service import (
    get_applicable_matrix,
    get_current_level_rule,
    validate_approver_identity
)
from ap_automation.services.security import resolve_acting_approver
from ap_automation.services.notification_service import (
    notify_admin_weekly_submitted,
    notify_admin_weekly_admin_l1_approved,
    notify_admin_weekly_admin_l2_approved,
    notify_admin_weekly_accounts_l1_approved,
    notify_admin_weekly_accounts_l2_approved,
    notify_admin_weekly_paid
)

TDS_SECTION_RATES = {
    "None / Exempt": 0.0,
    "194C - Contractor (1%)": 1.0,
    "194C - Contractor (2%)": 2.0,
    "194C - Company (2%)": 2.0,
    "194J - Technical Fees (2%)": 2.0,
    "194J - Professional/Technical (2%)": 2.0,
    "194J - Professional Fees (10%)": 10.0,
    "194J - Professional (10%)": 10.0,
    "194Q - Purchase of Goods (0.1%)": 0.1,
    "194I - Rent (10%)": 10.0,
    "194I - Rent Land/Building (10%)": 10.0,
    "194I - Rent Plant/Machinery (2%)": 2.0,
    "206AB - Higher Non-Filer (20%)": 20.0,
    "206AB - Non-Filer Higher Rate (20%)": 20.0,
}


class AdminWeeklyVendorClaim(Document):
    """
    Parent Controller for Admin Weekly Vendor Claims.
    Replaces manual weekly Excel spreadsheets with automated multi-row child table intake,
    6-stage AP Approval Matrix workflow:
      Stage 1: Receptionist Submit ->
      Stage 2: Admin L1 Approver (Matrix Level 1) ->
      Stage 3: Admin L2 Approver (Matrix Level 2) ->
      Stage 4: Accounts L1 Auditor (Matrix Level 3) ->
      Stage 5: Accounts L2 Sanction (Matrix Level 4) ->
      Stage 6: Payment Releaser Disburse & UTR Stamp.
    Zero-typing locked bank masters, in-grid bill proof uploaders, statutory GST & TDS sub-ledgers,
    strict identity validation gates, and 1-click Excel export.
    """

    def validate(self):
        """Standard lifecycle hook called on document save."""
        self.set_claim_metadata()
        self.validate_posting_date()
        self.validate_and_lock_vendor_lines()
        self.validate_role_field_permissions()
        self.calculate_totals()
        self.validate_immutability()

    def set_claim_metadata(self):
        """Generates dynamic voucher title and auto-populates parent company & preparer."""
        if not self.prepared_by:
            self.prepared_by = frappe.session.user if getattr(frappe, "session", None) else "Administrator"

        # Auto-resolve parent company if missing
        if not self.company:
            # 1. From first line item
            if getattr(self, "vendor_lines", None) and len(self.vendor_lines) > 0 and self.vendor_lines[0].company:
                self.company = self.vendor_lines[0].company
            else:
                # 2. From claimant employee record or default
                emp_company = frappe.db.get_value("Employee", {"user_id": self.prepared_by, "status": "Active"}, "company")
                self.company = emp_company or frappe.defaults.get_user_default("Company")

        period_label = self.week_period or "Weekly Claim"
        line_count = len(self.vendor_lines) if getattr(self, "vendor_lines", None) else 0
        self.claim_title = f"Admin Vendor Expenses — {period_label} ({line_count} Bills)"

    def validate_posting_date(self):
        """Blocks future posting dates."""
        if self.posting_date and getdate(self.posting_date) > getdate(frappe.utils.nowdate()):
            frappe.throw(_("Posting Date cannot be set to a future date."), title=_("Invalid Posting Date"), exc=APValidationError)

    def validate_and_lock_vendor_lines(self):
        """
        Validates every line item in the child table grid:
        1. Ensures at least one vendor bill line exists.
        2. Automatically fetches, verifies, and locks Bank Account & IFSC from ERPNext Supplier Master.
        3. Enforces Penny Drop Zero-Trust security checks.
        4. Validates mandatory bill proof and positive amount.
        """
        if not self.vendor_lines or len(self.vendor_lines) == 0:
            frappe.throw(
                _("At least one Vendor Bill line item is required in the table grid before saving."),
                title=_("Empty Table Grid"),
                exc=APValidationError
            )

        is_submitting = getattr(self, "status", "Draft") not in ("Draft", "Rejected")

        for idx, row in enumerate(self.vendor_lines, start=1):
            if not row.vendor:
                frappe.throw(_("Row #{0}: Vendor / Supplier is mandatory.").format(idx), title=_("Missing Vendor"), exc=APValidationError)

            if not row.company:
                row.company = self.company or frappe.defaults.get_user_default("Company")
                if not row.company:
                    frappe.throw(_("Row #{0}: Company Entity is mandatory.").format(idx), title=_("Missing Company"), exc=APValidationError)

            val = flt(row.base_amount) or flt(row.amount)
            if val <= 0:
                frappe.throw(_("Row #{0}: Base Taxable Amount must be strictly greater than 0.00.").format(idx), title=_("Invalid Amount"), exc=APValidationError)

            if is_submitting and not row.receipt_attachment:
                frappe.throw(
                    _("Row #{0} ({1}): Vendor Bill Proof PDF/Photo attachment is strictly mandatory.").format(idx, row.vendor),
                    title=_("Missing Bill Attachment"),
                    exc=APValidationError
                )

            # Auto-fetch & lock Supplier details and bank account from tabBank Account
            supp = frappe.db.get_value("Supplier", row.vendor, ["supplier_name", "disabled"], as_dict=True)
            if not supp:
                frappe.throw(_("Row #{0}: Supplier '{1}' not found in master.").format(idx, row.vendor), exc=APValidationError)

            if supp.disabled:
                frappe.throw(_("Row #{0}: Supplier '{1}' is Disabled in ERPNext.").format(idx, row.vendor), exc=APSecurityError)

            row.vendor_name = supp.supplier_name

            # Fetch Bank details
            bank_info = self._get_supplier_bank_details(row.vendor)
            if bank_info:
                row.bank_beneficiary_name = bank_info.get("bank_beneficiary_name") or supp.supplier_name
                row.bank_account_number = bank_info.get("bank_account_no") or ""
                row.bank_ifsc_code = bank_info.get("ifsc_code") or ""
                row.penny_drop_status = bank_info.get("penny_drop_status") or "UNVERIFIED"

                if is_submitting and bank_info.get("penny_drop_status") == "LOCKED_PENNY_DROP_MISMATCH":
                    frappe.throw(
                        _("Row #{0} ({1}): Bank account is hard-locked due to NPCI Penny Drop Name Mismatch! "
                          "Submission is halted until Accounts Manager override.").format(idx, row.vendor),
                        title=_("Penny Drop Security Lockout"),
                        exc=APSecurityError
                    )
            elif is_submitting:
                row.bank_beneficiary_name = row.bank_beneficiary_name or supp.supplier_name

    def validate_role_field_permissions(self):
        """
        Enforces strict RBAC:
        Admin/Reception can only enter vendor, invoice details, proof, and base amount.
        Only Accounts L1 and Accounts L2 can modify GST rates, TDS sections, or adjust financial amounts.
        """
        if self.is_new():
            return

        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        user = frappe.session.user if getattr(frappe, "session", None) else "Administrator"
        roles = frappe.get_roles(user) if user else []
        is_accounts_authorized = any(r in roles for r in ["Accounts User", "Accounts Manager", "Accounts L1 Auditor", "Accounts Director", "Director Tier", "System Manager", "Administrator"])

        if not is_accounts_authorized:
            old_rows = {r.name: r for r in (old_doc.vendor_lines or [])}
            for row in (self.vendor_lines or []):
                if row.name and row.name in old_rows:
                    old_r = old_rows[row.name]
                    # Disallow altering GST or TDS by non-accounts users
                    if old_r.gst_rate and row.gst_rate and old_r.gst_rate != row.gst_rate:
                        frappe.throw(
                            _("Unauthorized: Only Accounts L1 and Accounts L2 are authorized to modify GST classification."),
                            title=_("Permission Denied"),
                            exc=APSecurityError
                        )
                    if old_r.tds_section and row.tds_section and old_r.tds_section != row.tds_section:
                        frappe.throw(
                            _("Unauthorized: Only Accounts L1 and Accounts L2 are authorized to classify TDS sections."),
                            title=_("Permission Denied"),
                            exc=APSecurityError
                        )

    @staticmethod
    def _get_supplier_bank_details(supplier_id):
        """Queries the active Bank Account linked to the Supplier."""
        accs = frappe.db.sql(
            """
            SELECT ba.name, ba.bank, ba.bank_account_no, ba.branch_code, ba.penny_drop_status, ba.account_name
            FROM `tabBank Account` ba
            WHERE ba.party_type = 'Supplier' AND ba.party = %s
            ORDER BY ba.is_default DESC, ba.creation DESC
            LIMIT 1
            """,
            (supplier_id,),
            as_dict=True
        )
        if accs:
            return {
                "bank_name": accs[0].bank or "",
                "bank_account_no": accs[0].bank_account_no or "",
                "ifsc_code": accs[0].branch_code or "",
                "penny_drop_status": accs[0].penny_drop_status or "UNVERIFIED",
                "bank_beneficiary_name": accs[0].account_name or ""
            }
        return None

    def calculate_totals(self):
        """Auto-computes row-level GST, TDS, Net Pay and voucher-level totals."""
        tot_base = 0.0
        tot_gst = 0.0
        tot_tds = 0.0
        tot_net = 0.0

        for row in (self.vendor_lines or []):
            base = flt(row.base_amount)
            if base <= 0 and flt(row.amount) > 0:
                base = flt(row.amount)
                row.base_amount = base

            # GST computation
            rate_str = row.gst_rate or "18%"
            gst_pct = flt(str(rate_str).replace("%", "").strip() or 0.0)
            gst_amt = round(base * (gst_pct / 100.0), 2)
            total_bill = round(base + gst_amt, 2)

            # Statutory Indian TDS computation
            section = row.tds_section or "None / Exempt"
            tds_rate = TDS_SECTION_RATES.get(section)
            if tds_rate is None:
                import re
                m = re.search(r"\((\d+(?:\.\d+)?)\s*%\)", section)
                tds_rate = flt(m.group(1)) if m else flt(row.tds_rate)
            tds_amt = round(base * (tds_rate / 100.0), 2)

            net_pay = round(total_bill - tds_amt, 2)

            row.gst_amount = gst_amt
            row.total_invoice_amount = total_bill
            row.tds_rate = tds_rate
            row.tds_amount = tds_amt
            row.amount = net_pay

            tot_base += base
            tot_gst += gst_amt
            tot_tds += tds_amt
            tot_net += net_pay

        self.total_lines = len(self.vendor_lines) if self.vendor_lines else 0
        self.total_base_amount = round(tot_base, 2)
        self.total_gst_amount = round(tot_gst, 2)
        self.total_tds_amount = round(tot_tds, 2)
        self.total_amount = round(tot_net, 2)

    def validate_immutability(self):
        """Prevents tampering once approved beyond Draft."""
        if self.is_new():
            return
        old_status = frappe.db.get_value(self.doctype, self.name, "status")
        if old_status in ("Pending Accounts L2 Approval", "Queued for Payment Release", "Approved for Payment", "Queued in Batch", "Paid") and self.status == old_status:
            old_count = frappe.db.count("Admin Vendor Claim Item", {"parent": self.name})
            if old_count != len(self.vendor_lines):
                frappe.throw(_("Immutability Violation: Approved weekly vouchers cannot be modified."), exc=APSecurityError)


# --------------------------------------------------------------------------------------
# WHITELISTED LIFECYCLE WORKFLOW TRANSITION APIS (AP APPROVAL MATRIX ROUTED)
# --------------------------------------------------------------------------------------

@frappe.whitelist()
def get_supplier_bank_info(supplier):
    """Fetches legal name and verified bank account details for a Supplier."""
    supp = frappe.db.get_value("Supplier", supplier, ["supplier_name", "disabled"], as_dict=True)
    if not supp:
        return None

    bank_info = AdminWeeklyVendorClaim._get_supplier_bank_details(supplier) or {}
    return {
        "supplier_name": supp.supplier_name,
        "disabled": supp.disabled,
        "bank_name": bank_info.get("bank_name", ""),
        "bank_account_number": bank_info.get("bank_account_no", ""),
        "bank_ifsc_code": bank_info.get("ifsc_code", ""),
        "penny_drop_status": bank_info.get("penny_drop_status", "UNVERIFIED"),
        "bank_beneficiary_name": bank_info.get("bank_beneficiary_name", supp.supplier_name)
    }


def _resolve_matrix_level_approver(doc, level_number: int):
    """
    Finds designated approver rule from AP Approval Matrix for lane 'Admin Weekly Vendor Claim'.
    Raises informative validation error if matrix is missing.
    """
    matrix = get_applicable_matrix("Admin Weekly Vendor Claim", doc.company, doc.total_amount)
    if not matrix:
        # Fallback to AP Vendor Invoice if not specifically set
        matrix = get_applicable_matrix("AP Vendor Invoice", doc.company, doc.total_amount)

    if not matrix:
        frappe.throw(
            _(f"No active AP Approval Matrix configured for Company '{doc.company}' and Document Lane 'Admin Weekly Vendor Claim'. "
              f"Please configure the 4-tier matrix policy in AP Approval Matrix."),
            title=_("Approval Matrix Missing"),
            exc=APValidationError
        )

    rule = get_current_level_rule(matrix, level_number)
    if not rule or not rule.designated_approver:
        frappe.throw(
            _(f"Approval Level #{level_number} has no Designated Approver configured in Policy '{matrix.name}'."),
            title=_("Incomplete Matrix Configuration"),
            exc=APValidationError
        )
    return rule


@frappe.whitelist()
def submit_to_admin_l1(docname):
    """
    Stage 1 -> Stage 2: Receptionist submits to Admin L1.
    Resolves Level 1 designated approver from AP Matrix and sends 1-to-1 forward email.
    """
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status not in ("Draft", "Rejected"):
        frappe.throw(_("Voucher must be in Draft or Rejected status to submit."))

    # Resolve Level 1 designated approver
    rule_1 = _resolve_matrix_level_approver(doc, level_number=1)

    doc.status = "Pending Admin L1"
    doc.current_approval_level = 1
    doc.designated_approver = rule_1.designated_approver
    doc.admin_rejection_reason = ""
    doc.save(ignore_permissions=True)

    doc.add_comment("Comment", text=f"🚀 <b>Submitted to Admin L1:</b> Forwarded to designated approver <b>{doc.designated_approver}</b>.")

    # 1-to-1 forward email
    notify_admin_weekly_submitted(doc.name)

    return {
        "status": doc.status,
        "designated_approver": doc.designated_approver,
        "message": _("Voucher successfully submitted to Admin L1 ({0}).").format(doc.designated_approver)
    }


@frappe.whitelist()
def approve_admin_l1(docname):
    """
    Stage 2 -> Stage 3: Admin L1 Approver sign-off.
    Enforces strict user identity validation.
    Resolves Level 2 designated approver from AP Matrix and sends 1-to-1 forward email.
    """
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status != "Pending Admin L1":
        frappe.throw(_("Voucher must be in 'Pending Admin L1' status."))

    # Strict Identity Gate
    validate_approver_identity(doc.designated_approver, frappe.session.user, allow_delegation=True)

    # Resolve Level 2 designated approver
    rule_2 = _resolve_matrix_level_approver(doc, level_number=2)

    doc.admin_l1_approver = frappe.session.user
    doc.admin_l1_date = now_datetime()
    doc.status = "Pending Admin L2"
    doc.current_approval_level = 2
    doc.designated_approver = rule_2.designated_approver
    doc.save(ignore_permissions=True)

    doc.add_comment("Comment", text=f"✅ <b>Admin L1 Approved:</b> Approved by {frappe.session.user}. Forwarded to Admin L2 <b>{doc.designated_approver}</b>.")

    # 1-to-1 forward email
    notify_admin_weekly_admin_l1_approved(doc.name)

    return {
        "status": doc.status,
        "designated_approver": doc.designated_approver,
        "message": _("Admin L1 Review approved. Forwarded to Admin L2 ({0}).").format(doc.designated_approver)
    }


@frappe.whitelist()
def approve_admin_l2(docname):
    """
    Stage 3 -> Stage 4: Admin L2 Head sign-off.
    Enforces strict user identity validation.
    Resolves Level 3 (Accounts L1 Auditor) from AP Matrix and sends 1-to-1 forward email.
    """
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status != "Pending Admin L2":
        frappe.throw(_("Voucher must be in 'Pending Admin L2' status."))

    # Strict Identity Gate
    validate_approver_identity(doc.designated_approver, frappe.session.user, allow_delegation=True)

    # Resolve Level 3 designated approver (Accounts L1 Auditor)
    rule_3 = _resolve_matrix_level_approver(doc, level_number=3)

    doc.admin_l2_approver = frappe.session.user
    doc.admin_l2_date = now_datetime()
    doc.status = "Pending Accounts L1 Review"
    doc.current_approval_level = 3
    doc.designated_approver = rule_3.designated_approver
    doc.save(ignore_permissions=True)

    doc.add_comment("Comment", text=f"✅ <b>Admin L2 Sign-Off:</b> Approved by {frappe.session.user}. Transferred to Accounts L1 Audit <b>{doc.designated_approver}</b>.")

    # 1-to-1 forward email
    notify_admin_weekly_admin_l2_approved(doc.name)

    return {
        "status": doc.status,
        "designated_approver": doc.designated_approver,
        "message": _("Admin L2 Sign-off complete. Transferred to Accounts L1 Review ({0}).").format(doc.designated_approver)
    }


@frappe.whitelist()
def approve_accounts_l1(docname):
    """
    Stage 4 -> Stage 5: Accounts L1 Audit clearance.
    Verifies GST rates, TDS deductions, invoice attachments, and vendor bank verification.
    Resolves Level 4 (Accounts L2 / Director) from AP Matrix and sends 1-to-1 forward email.
    """
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status not in ("Pending Accounts L1 Review", "Pending Accounts Review"):
        frappe.throw(_("Voucher must be in 'Pending Accounts L1 Review' status."))

    # Strict Identity Gate
    validate_approver_identity(doc.designated_approver, frappe.session.user, allow_delegation=True)

    # Resolve Level 4 designated approver (Accounts L2 / Director Sanction)
    rule_4 = _resolve_matrix_level_approver(doc, level_number=4)

    doc.accounts_l1_approver = frappe.session.user
    doc.accounts_l1_date = now_datetime()
    # Backward compatibility fields
    doc.accounts_reviewer = frappe.session.user
    doc.accounts_date = now_datetime()

    doc.status = "Pending Accounts L2 Approval"
    doc.current_approval_level = 4
    doc.designated_approver = rule_4.designated_approver
    doc.save(ignore_permissions=True)

    doc.add_comment("Comment", text=f"🔍 <b>Accounts L1 Audit Cleared:</b> Tax & compliance verified by {frappe.session.user}. Awaiting Accounts L2 Sanction <b>{doc.designated_approver}</b>.")

    # 1-to-1 forward email
    notify_admin_weekly_accounts_l1_approved(doc.name)

    return {
        "status": doc.status,
        "designated_approver": doc.designated_approver,
        "message": _("Accounts L1 Audit cleared. Transferred to Accounts L2 Sanction ({0}).").format(doc.designated_approver)
    }

# Backward compatible alias
approve_accounts = approve_accounts_l1


@frappe.whitelist()
def approve_accounts_l2(docname):
    """
    Stage 5 -> Stage 6: Accounts L2 / Director authorization.
    Enforces strict user identity validation.
    Queues voucher in Payment Batch for Bank Release.
    """
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status not in ("Pending Accounts L2 Approval", "Approved for Payment"):
        frappe.throw(_("Voucher must be in 'Pending Accounts L2 Approval' to sanction."))

    # Strict Identity Gate
    validate_approver_identity(doc.designated_approver, frappe.session.user, allow_delegation=True)

    doc.accounts_l2_approver = frappe.session.user
    doc.accounts_l2_date = now_datetime()
    # Backward compatibility fields
    doc.director_approver = frappe.session.user
    doc.director_date = now_datetime()

    doc.status = "Queued for Payment Release"
    doc.current_approval_level = 5
    doc.designated_approver = ""
    doc.batch_id = f"BATCH-ADMIN-{doc.name[-5:]}"
    doc.save(ignore_permissions=True)

    doc.add_comment("Comment", text=f"⭐ <b>Accounts L2 Sanction Approved:</b> Payout sanctioned by {frappe.session.user}. Queued in payment batch **{doc.batch_id}**.")

    # Notification email to Submitter + Payment Releasers
    notify_admin_weekly_accounts_l2_approved(doc.name)

    return {
        "status": doc.status,
        "batch_id": doc.batch_id,
        "message": _("Accounts L2 Payout sanctioned. Queued in Payment Batch for Bank Release.")
    }

# Backward compatible alias
sanction_director = approve_accounts_l2


@frappe.whitelist()
def disburse_payment(docname, utr_number=None):
    """
    Stage 6: Settlement stamped with Bank UTR by Payment Releaser.
    """
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    if doc.status not in ("Queued for Payment Release", "Queued in Batch", "Approved for Payment"):
        frappe.throw(_("Voucher must be in 'Queued for Payment Release' to disburse."))

    user = frappe.session.user
    roles = frappe.get_roles(user) if user else []
    if not any(r in roles for r in ["Payment Releaser", "Accounts Manager", "Accounts Director", "System Manager", "Administrator"]):
        frappe.throw(_("Unauthorized: Only users with 'Payment Releaser' role can disburse payments."), exc=APSecurityError)

    utr = utr_number or f"IDFC{now_datetime().strftime('%Y%m%d%H%M%S')}"

    doc.disbursement_utr = utr
    doc.payment_releaser = user
    doc.disbursement_date = now_datetime()
    doc.status = "Paid"
    doc.current_approval_level = 6
    doc.designated_approver = ""
    doc.save(ignore_permissions=True)

    doc.add_comment("Comment", text=f"💳 <b>Disbursed & Paid via Bank:</b> UTR Reference #{utr} by {user}.")

    # Notification email to Submitter + Accounts
    notify_admin_weekly_paid(doc.name, utr)

    return {"status": doc.status, "utr": utr, "message": _("All line payouts settled. Stamped with Bank UTR #{0}.").format(utr)}


@frappe.whitelist()
def reject_or_return(docname, reason_code, remarks, return_to="Draft"):
    """
    Enhanced Targeted Rejection & Return Hook:
    1. Supports returning to Reception (Draft), Admin L1, Admin L2, or Accounts L1.
    2. Remembers return_origin_stage.
    3. Re-assigns designated_approver to target stage owner.
    4. Sends threaded notification email.
    """
    if not remarks or len(remarks.strip()) < 10:
        frappe.throw(_("Detailed remarks are strictly mandatory for rejection (minimum 10 characters)."), title=_("Remarks Required"))

    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    user = frappe.session.user
    now_str = now_datetime().strftime("%Y-%m-%d %H:%M:%S")

    origin_stage = doc.status
    rej_text = f"[{now_str}] Returned from {origin_stage} by {user} | Reason: {reason_code} | Notes: {remarks.strip()}"
    doc.admin_rejection_reason = rej_text
    doc.return_to = return_to
    doc.return_origin_stage = origin_stage

    # Update level and designated approver based on target return stage
    if return_to == "Draft":
        doc.status = "Draft"
        doc.current_approval_level = 0
        doc.designated_approver = doc.prepared_by
    elif return_to == "Pending Admin L1":
        doc.status = "Pending Admin L1"
        doc.current_approval_level = 1
        rule_1 = _resolve_matrix_level_approver(doc, 1)
        doc.designated_approver = rule_1.designated_approver
    elif return_to == "Pending Admin L2":
        doc.status = "Pending Admin L2"
        doc.current_approval_level = 2
        rule_2 = _resolve_matrix_level_approver(doc, 2)
        doc.designated_approver = rule_2.designated_approver
    elif return_to in ("Pending Accounts L1 Review", "Pending Accounts Review"):
        doc.status = "Pending Accounts L1 Review"
        doc.current_approval_level = 3
        rule_3 = _resolve_matrix_level_approver(doc, 3)
        doc.designated_approver = rule_3.designated_approver
    else:
        doc.status = "Draft"
        doc.current_approval_level = 0
        doc.designated_approver = doc.prepared_by

    doc.save(ignore_permissions=True)

    frappe.log_error(title=f"Admin Vendor Claim Returned: {docname}", message=rej_text)
    doc.add_comment("Comment", text=f"🚫 <b>Voucher Returned to {doc.status}:</b> {reason_code} — {remarks.strip()} (Origin: {origin_stage})")

    # Send targeted email notification
    send_rejection_email_thread(doc, origin_stage, doc.status, reason_code, remarks)

    return {"status": doc.status, "message": _("Voucher returned to {0}.").format(doc.status), "rejection_log": rej_text}


@frappe.whitelist()
def resubmit_corrected_voucher(docname, remarks=None):
    """
    Fast-Track Resubmission API:
    When Reception or Admin corrects the discrepancy, they resubmit directly back
    to the stage that returned it (e.g. back to Accounts L1 or Accounts L2), bypassing
    already-approved stages. Re-assigns designated_approver from matrix.
    """
    if not docname:
        frappe.throw(_("Document name is required."))

    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)
    target = doc.return_origin_stage or "Pending Accounts L1 Review"
    user = frappe.session.user

    # Resolve target level and approver
    if target in ("Pending Accounts L1 Review", "Pending Accounts Review"):
        target_status = "Pending Accounts L1 Review"
        lvl = 3
    elif target in ("Pending Accounts L2 Approval", "Approved for Payment"):
        target_status = "Pending Accounts L2 Approval"
        lvl = 4
    elif target == "Pending Admin L2":
        target_status = "Pending Admin L2"
        lvl = 2
    else:
        target_status = "Pending Admin L1"
        lvl = 1

    rule = _resolve_matrix_level_approver(doc, lvl)

    doc.status = target_status
    doc.current_approval_level = lvl
    doc.designated_approver = rule.designated_approver
    doc.return_origin_stage = None
    doc.admin_rejection_reason = ""
    doc.save(ignore_permissions=True)

    doc.add_comment("Comment", text=f"🚀 <b>Corrected & Resubmitted:</b> Resubmitted by {user}. Fast-tracked directly to **{target_status}** ({doc.designated_approver}).")

    # Send targeted email update
    send_resubmission_email_thread(doc, target_status, user, remarks)

    return {
        "status": doc.status,
        "designated_approver": doc.designated_approver,
        "message": _("Voucher successfully resubmitted directly to {0} ({1}).").format(target_status, doc.designated_approver)
    }


def send_rejection_email_thread(doc, origin_stage, return_to, reason_code, remarks):
    """Sends a targeted notification email to the recipient of the return."""
    try:
        recipients = []
        if return_to == "Draft" and doc.prepared_by:
            recipients.append(doc.prepared_by)
        elif doc.designated_approver:
            recipients.append(doc.designated_approver)

        recipients = [r for r in recipients if r and "@" in r]
        if not recipients:
            return

        subject = f"[AP-ADMIN-VOUCHER] Weekly Vendor Claim #{doc.name} — Action Required: Discrepancy Returned"
        doc_url = get_url(f"/desk/admin-weekly-vendor-claim/{doc.name}")

        message = f"""
        <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #1e293b;">
            <h3 style="color: #dc2626;">🚫 Weekly Vendor Voucher Returned for Discrepancy</h3>
            <p>Admin Weekly Vendor Claim <b>#{doc.name}</b> (<i>{doc.week_period or 'Weekly Claim'}</i>) has been returned from <b>{origin_stage}</b> to <b>{return_to}</b>.</p>
            <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 12px; margin: 15px 0;">
                <p style="margin: 0; font-weight: bold; color: #991b1b;">Reason Code: {reason_code}</p>
                <p style="margin: 6px 0 0 0; color: #7f1d1d;">Reviewer Notes: {remarks}</p>
            </div>
            <p>Please review and correct the affected vendor line item(s). Once corrected, click <b>Resubmit Corrected Voucher</b> on the document to fast-track it directly back to {origin_stage}.</p>
            <p><a href="{doc_url}" style="background: #2563eb; color: #ffffff; padding: 8px 16px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">Open Voucher #{doc.name}</a></p>
        </div>
        """

        frappe.sendmail(
            recipients=list(set(recipients)),
            subject=subject,
            message=message,
            reference_doctype=doc.doctype,
            reference_name=doc.name
        )
    except Exception as e:
        frappe.log_error(title=f"Failed to send rejection email: {doc.name}", message=str(e))


def send_resubmission_email_thread(doc, target, resubmitter, remarks):
    """Sends email notification on fast-track resubmission strictly to designated approver."""
    try:
        recipients = []
        if doc.designated_approver and "@" in doc.designated_approver:
            recipients.append(doc.designated_approver)

        if not recipients:
            return

        subject = f"[AP-ADMIN-VOUCHER] Weekly Vendor Claim #{doc.name} — Resubmitted for {target}"
        doc_url = get_url(f"/desk/admin-weekly-vendor-claim/{doc.name}")

        message = f"""
        <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #1e293b;">
            <h3 style="color: #059669;">🚀 Corrected Weekly Vendor Voucher Resubmitted</h3>
            <p>Admin Weekly Vendor Claim <b>#{doc.name}</b> has been corrected and resubmitted by <b>{resubmitter}</b> directly to you for <b>{target}</b>.</p>
            <p>Remarks: {remarks or 'Discrepancies corrected.'}</p>
            <p><a href="{doc_url}" style="background: #059669; color: #ffffff; padding: 8px 16px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">Review Voucher #{doc.name}</a></p>
        </div>
        """

        frappe.sendmail(
            recipients=list(set(recipients)),
            subject=subject,
            message=message,
            reference_doctype=doc.doctype,
            reference_name=doc.name
        )
    except Exception as e:
        frappe.log_error(title=f"Failed to send resubmission email: {doc.name}", message=str(e))


@frappe.whitelist()
def generate_weekly_excel_download(docname):
    """
    Generates exact Excel Spreadsheet matching the Admin team's format,
    including the statutory GST, TDS, and Net Pay sub-ledger,
    and injecting clean =HYPERLINK(..., 'View Proof') formulas in the Proof PDF column.
    """
    doc = frappe.get_doc("Admin Weekly Vendor Claim", docname)

    headers = [
        "Sr.No",
        "Vendor Category",
        "Supplier / Vendor",
        "Vendor Legal Name",
        "Company",
        "Invoice #",
        "Invoice Date",
        "Base Taxable (INR)",
        "GST %",
        "Calculated GST (INR)",
        "Total Bill (INR)",
        "TDS Section",
        "Deducted TDS (INR)",
        "Net Pay (INR)",
        "Proof PDF",
        "Name As Per Bank Records",
        "Bank Ac No",
        "IFSC Code",
        "Remarks"
    ]

    rows = []
    for idx, row in enumerate(doc.vendor_lines, start=1):
        proof_formula = ""
        if row.receipt_attachment:
            full_url = get_url(row.receipt_attachment)
            proof_formula = f'=HYPERLINK("{full_url}", "View Proof")'

        rows.append([
            idx,
            row.vendor_category or "",
            row.vendor or "",
            row.vendor_name or "",
            row.company or doc.company or "",
            row.invoice_number or "",
            str(row.invoice_date or ""),
            flt(row.base_amount),
            row.gst_rate or "18%",
            flt(row.gst_amount),
            flt(row.total_invoice_amount),
            row.tds_section or "None / Exempt",
            flt(row.tds_amount),
            flt(row.amount),
            proof_formula,
            row.bank_beneficiary_name or row.vendor_name or "",
            f"'{row.bank_account_number}" if row.bank_account_number else "",
            row.bank_ifsc_code or "",
            row.remarks or ""
        ])

    # Grand Total row
    rows.append([
        "",
        "TOTAL",
        "",
        "",
        "",
        "",
        "",
        flt(doc.total_base_amount),
        "",
        flt(doc.total_gst_amount),
        round(flt(doc.total_base_amount) + flt(doc.total_gst_amount), 2),
        "",
        flt(doc.total_tds_amount),
        flt(doc.total_amount),
        "",
        "",
        "",
        "",
        f"Total Bills: {doc.total_lines or len(doc.vendor_lines)}"
    ])

    xlsx_file = make_xlsx([headers] + rows, "Admin Weekly Vendor Claims")

    frappe.response["filename"] = f"Admin_Weekly_Vendor_Claim_{doc.name}.xlsx"
    frappe.response["filecontent"] = xlsx_file.getvalue()
    frappe.response["type"] = "binary"
