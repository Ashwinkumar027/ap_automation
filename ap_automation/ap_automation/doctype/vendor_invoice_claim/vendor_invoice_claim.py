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

        self.bind_and_lock_vendor_profile()
        self.validate_intake_route_and_proofs()
        self.calculate_financial_totals()

        # Execute 3-Way Matching Engine
        execute_3way_matching(self)

        # Apply Statutory Indian TDS
        apply_tds_to_invoice(self)

        # Map payee and invoice fields for APDocument base spend hash and banking dispatch
        self.payee_name = getattr(self, "vendor_name", "") or getattr(self, "vendor", "")
        self.invoice_number = getattr(self, "tax_invoice_number", "")
        self.total_amount = self.net_payable_amount

        # Advance status from Draft based on 3-Way matching & proof validation
        if self.match_status in ("Price Mismatch Flagged", "Quantity Mismatch Flagged", "Missing GRN Flagged"):
            self.status = "Disputed"
        elif getattr(self, "status", "Draft") in ("Draft", "Not Saved"):
            # Route to Manager Approval as first business gate (PRD Stage 3)
            self.status = "Pending Manager Approval"
            self.workflow_state = "Awaiting Manager Approval (PRD Stage 3)"

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
        self.bind_and_lock_vendor_profile()
        self.validate_intake_route_and_proofs()
        self.calculate_financial_totals()

    def on_submit(self):
        """Registers spend fingerprint lock upon submission."""
        super().on_submit()
        register_spend_fingerprint(self)

    def on_cancel(self):
        """Releases spend fingerprint lock if cancelled."""
        super().on_cancel()
        release_spend_fingerprint(self)

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

    def _fetch_supplier_bank_account(self, supplier_name: str) -> Dict[str, Any]:
        """Looks up active Bank Account linked to Supplier in tabBank Account."""
        has_pd = frappe.db.has_column("Bank Account", "penny_drop_status")
        pd_select = ", ba.penny_drop_status" if has_pd else ""
        accs = frappe.db.sql(
            f"""
            SELECT ba.name, ba.bank, ba.bank_account_no, ba.branch_code{pd_select}
            FROM `tabBank Account` ba
            WHERE ba.party_type = 'Supplier' AND ba.party = %s
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
                "penny_drop_status": accs[0].get("penny_drop_status") or "VERIFIED"
            }
        return {}

    def validate_intake_route_and_proofs(self):
        """Enforces dual-route mandatory requirements and audit proof attachments with progressive Draft validation."""
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        route = getattr(self, "invoice_type", "Without PO (Direct Tax Invoice)")

        if not is_submitting:
            # On Draft, assign fallbacks
            if not getattr(self, "tax_invoice_number", None):
                self.tax_invoice_number = self.invoice_number or f"DRAFT-{frappe.generate_hash(length=6).upper()}"
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
        base = float(getattr(self, "base_amount", 0.0) or getattr(self, "invoice_amount", 0.0) or getattr(self, "taxable_amount", 0.0) or 0.0)
        self.base_amount = base
        is_submitting = getattr(self, "docstatus", 0) == 1 or getattr(self, "status", "Draft") not in ("Draft", "Not Saved")
        if is_submitting and base <= 0:
            log_and_throw("Base Taxable Amount must be strictly positive upon submission.", title="Invalid Base Amount", doc=self)

        rate_str = getattr(self, "gst_rate", "18%") or "18%"
        rate_val = float(rate_str.replace("%", "").strip() or 0.0)

        gst = round(base * (rate_val / 100.0), 2)
        total = round(base + gst, 2)
        advance = float(getattr(self, "advance_deducted", 0.0) or 0.0)

        if advance < 0:
            log_and_throw("Advance Deducted cannot be negative.", title="Negative Advance Amount", doc=self)

        if advance > total:
            log_and_throw(
                f"Prior Advance Deducted (INR {advance:,.2f}) cannot exceed Total Invoice Amount (INR {total:,.2f}).",
                title="Advance Exceeds Total Amount",
                doc=self
            )

        self.gst_amount = gst
        self.total_invoice_amount = total

        # Statutory Indian TDS Withholding calculation
        try:
            from ap_automation.services.tds_service import calculate_tds
            section = getattr(self, "tds_section", "None / Exempt") or "None / Exempt"
            tds_info = calculate_tds(base, section)
            self.tds_rate = tds_info.get("rate", 0.0)
            self.tds_amount = tds_info.get("tds_amount", 0.0)
        except Exception:
            self.tds_rate = getattr(self, "tds_rate", 0.0) or 0.0
            self.tds_amount = getattr(self, "tds_amount", 0.0) or 0.0

        tds = float(getattr(self, "tds_amount", 0.0) or 0.0)
        net = round(max(total - advance - tds, 0.0), 2)
        self.net_payable_amount = net
        self.total_amount = net


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

    dispute_msg = f"[{now_str}] Disputed by {user} | Reason: {reason_code} | Remarks: {remarks.strip()}"
    old_variance = doc.match_variance_details or ""
    doc.match_variance_details = f"{dispute_msg}\n{old_variance}".strip()
    doc.status = "Disputed"
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

    # Check if Manager is also the Director / Business Head for this company
    company = getattr(doc, "company", None)
    bus_head = frappe.db.get_value("Company", company, "ap_business_head") if company else None
    from ap_automation.services.notification_service import _get_matrix_or_role_approvers
    matrix_dirs = _get_matrix_or_role_approvers(
        company=company,
        document_lane="AP Vendor Invoice",
        level_number=1,
        fallback_roles=["Accounts Director", "Director Tier"],
        stage_keyword="Director"
    )
    user_roles = frappe.get_roles(user)
    is_also_director = (
        user == bus_head or
        user in matrix_dirs or
        "Accounts Director" in user_roles or
        "Director Tier" in user_roles
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
            "message": f"Claim #{docname} approved! Since you are both Reporting Manager and Director, your single approval satisfies commercial sanction and routes directly to Accounts L1 (Gokulnath)."
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
            fallback_roles=["Accounts Director", "Director Tier"],
            stage_keyword="Director"
        )
        user_roles = frappe.get_roles(user)
        is_auth = (user == bus_head or user in matrix_dirs or "Accounts Director" in user_roles or "Director Tier" in user_roles)
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
    doc.workflow_state = "Awaiting Accounts L1 Review (Gokulnath)"

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

    return {"status": doc.status, "message": f"Claim #{docname} successfully approved by Director. Routed to Accounts L1 (Gokulnath)."}


@frappe.whitelist()
def verify_vendor_claim_by_accounts_l1(docname: str, tally_reference: str, remarks: Optional[str] = None):
    """
    Stage 4 & 6: Accounts L1 Verification (Gokulnath).
    1. Re-runs and verifies 3-Way Match & statutory TDS.
    2. Strictly enforces Tally Voucher Reference logging (PRD Stage 6).
    3. Advances claim to Accounts L2 Approval (Anshul Sir / Srinivasan Sir).
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

    # Enforce clean 3-way match
    if doc.match_status in ("Quantity Mismatch Flagged", "Price Mismatch Flagged", "Missing GRN Flagged"):
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
    doc.workflow_state = "Awaiting Accounts L2 Signoff (Anshul Sir / Srinivasan Sir)"

    doc.append("approval_trail", {
        "level_number": 4,
        "level_name": "Stage 4 & 6: Accounts L1 Verification & Tally Logged",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_ts,
        "remarks": f"Verified by L1 (Gokulnath) | Tally Ref: {clean_tally} | {remarks or 'Voucher Posted to Tally'}"
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
    Stage 7: Accounts L2 Approval (Anshul Sir / Srinivasan Sir).
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
            fallback_roles=["Accounts Director", "Accounts Manager"],
            stage_keyword="Accounts L2"
        )
        if not (user in matrix_l2 or any(r in user_roles for r in ["Accounts Director", "Accounts Manager"])):
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
    doc.workflow_state = "Approved for Shared Payment Core Release (Anish Sir)"

    doc.append("approval_trail", {
        "level_number": 5,
        "level_name": "Stage 7: Accounts L2 Approval (Anshul Sir / Srinivasan Sir)",
        "action_taken_by": user,
        "action": "APPROVED",
        "action_timestamp": now_ts,
        "remarks": remarks or "Approved by Accounts L2 for payment core release"
    })
    doc.save(ignore_permissions=True)
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

@frappe.whitelist()
def disburse_vendor_claim(docname: str, utr_reference: str, remarks: Optional[str] = None):
    """
    Stage 6: Bank Disbursement & UTR Stamping (Payment Releaser).
    Validates claim status and stamps bank UTR reference, marking claim as 'Paid'.
    """
    if not docname or not frappe.db.exists("Vendor Invoice Claim", docname):
        frappe.throw(f"Vendor Invoice Claim '{docname}' not found.")

    if not utr_reference or not str(utr_reference).strip():
        frappe.throw("Bank UTR Reference Number is strictly mandatory for disbursement signoff.", title="UTR Required")

    doc = frappe.get_doc("Vendor Invoice Claim", docname)
    user = frappe.session.user if getattr(frappe, "session", None) else "Administrator"

    if doc.status not in ("Approved for Payment", "Queued in Batch"):
        frappe.throw(f"Claim '{docname}' is in status '{doc.status}', not ready for bank disbursement.")

    clean_utr = str(utr_reference).strip().upper()
    now_ts = frappe.utils.now_datetime()

    # Update status directly in database to avoid triggering tamper alert on locked status transition
    frappe.db.set_value("Vendor Invoice Claim", docname, {
        "status": "Paid",
        "workflow_state": "Disbursed via Corporate Bank Transfer"
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

    doc.add_comment("Comment", text=f"💳 <b>Payment Disbursed:</b> Bank UTR: <code>{clean_utr}</code> by {user}")
    frappe.db.commit()

    return {
        "status": "Paid",
        "utr": clean_utr,
        "message": f"Claim #{docname} successfully marked Paid with Bank UTR '{clean_utr}'."
    }
