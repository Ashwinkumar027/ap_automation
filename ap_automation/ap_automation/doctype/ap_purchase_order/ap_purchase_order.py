# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import hashlib
import json
import re
import secrets
from typing import Dict, Any, List, Optional
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate, now_datetime, get_url

DEFAULT_PO_TERMS = """
<h4>1. Standard Commercial Terms</h4>
<ol>
  <li><strong>Payment Terms:</strong> Invoices shall be processed as per agreed payment terms following three-way match reconciliation against delivered goods/services.</li>
  <li><strong>Advance Deduction:</strong> Any mobilization advance disbursed under this Purchase Order shall be offset against final tax invoices.</li>
  <li><strong>Statutory Compliance:</strong> Vendor warrants full compliance with Indian GST & TDS provisions. Tax invoices must quote this PO number and valid HSN/SAC codes.</li>
  <li><strong>Service Level & Quality:</strong> Deliverables must adhere strictly to agreed specifications. Deviations may result in rejection and invoice hold.</li>
  <li><strong>Confidentiality & Governing Law:</strong> Both parties agree to maintain strict non-disclosure. Disputes are subject to local jurisdiction.</li>
</ol>
"""

COMPANY_ADDRESS_REGISTRY = {
    "Aionion Capital Market Services Private Limited": {
        "address": "Level 8, Tower B, Peninsula Business Park, Lower Parel, Mumbai, Maharashtra 400013",
        "gstin": "27AAACA1234A1Z5",
        "cin": "U74999MH2020PTC123456",
        "email": "finance@aionioncapital.com",
        "phone": "+91 22 6900 1000"
    },
    "Quanticus Software Solutions Private Limited": {
        "address": "Unit 402, 4th Floor, Godrej Genesis, Kanjurmarg East, Mumbai, Maharashtra 400042",
        "gstin": "27AAACQ5678Q1Z2",
        "cin": "U72900MH2021PTC654321",
        "email": "accounts@quanticustech.com",
        "phone": "+91 22 6900 2000"
    },
    "Aionion Insurance Marketing Private Limited": {
        "address": "Level 8, Peninsula Business Park, Lower Parel, Mumbai, Maharashtra 400013",
        "gstin": "27AAACI9876I1Z9",
        "cin": "U66000MH2022PTC789123",
        "email": "insurance@aionion.com",
        "phone": "+91 22 6900 3000"
    },
    "Aionion Businesses and Management Services LLP": {
        "address": "Tower 2, World Trade Centre, Cuffe Parade, Mumbai, Maharashtra 400005",
        "gstin": "27AABCA3456B1Z1",
        "cin": "AAB-3456-LLP",
        "email": "management@aionion.com",
        "phone": "+91 22 6900 4000"
    },
    "Aionion Businesses and Management Services LLC": {
        "address": "Suite 1402, Al Saaha Offices, Downtown Dubai, UAE",
        "gstin": "DXB-TRN-100234567800003",
        "cin": "LLC-DXB-98765",
        "email": "dubai.ops@aionion.com",
        "phone": "+971 4 312 0000"
    },
    "Anshul A Gupta & Associates": {
        "address": "12th Floor, Express Towers, Nariman Point, Mumbai, Maharashtra 400021",
        "gstin": "27AAAGA1111A1Z0",
        "cin": "FRN-123456W",
        "email": "anshul@aagassociates.com",
        "phone": "+91 22 6900 5000"
    }
}


@frappe.whitelist()
def get_user_department_details(user_id: str) -> Dict[str, Any]:
    """Auto-fetches department and employee contact details for a given User ID."""
    if not user_id:
        return {}

    emp = frappe.db.get_value(
        "Employee",
        {"user_id": user_id, "status": "Active"},
        ["department", "cell_number", "employee_name"],
        as_dict=True
    )
    if not emp:
        emp = frappe.db.get_value(
            "Employee",
            {"user_id": user_id},
            ["department", "cell_number", "employee_name"],
            as_dict=True
        ) or frappe.db.get_value(
            "Employee",
            {"company_email": user_id},
            ["department", "cell_number", "employee_name"],
            as_dict=True
        ) or frappe.db.get_value(
            "Employee",
            {"personal_email": user_id},
            ["department", "cell_number", "employee_name"],
            as_dict=True
        )

    dept = emp.get("department") if emp else None
    mobile = emp.get("cell_number") if emp else None

    if not dept and frappe.db.has_column("User", "department"):
        dept = frappe.db.get_value("User", user_id, "department")

    return {
        "department": dept or "",
        "mobile": mobile or ""
    }


def resolve_po_workflow_policy(company: str, department: Optional[str] = None):
    """
    100% Dynamic: Queries AP Approval Matrix for company & department.
    1. Checks for active matrix with matching company AND matching department (by ID or department_name).
    2. If not found, checks for active matrix with matching company and empty department (company default).
    """
    if not frappe.db.exists("DocType", "AP Approval Matrix"):
        return None

    if department:
        # Direct match on matrix.department
        m_name = frappe.db.get_value(
            "AP Approval Matrix",
            {"company": company, "department": department, "document_lane": "AP Purchase Order", "is_active": 1},
            "name"
        )
        if m_name:
            return frappe.get_doc("AP Approval Matrix", m_name)

        # Match via Department doctype link (department_name vs name)
        dept_names = frappe.db.get_all(
            "Department",
            filters={"department_name": department},
            pluck="name"
        )
        if dept_names:
            m_name = frappe.db.get_value(
                "AP Approval Matrix",
                {"company": company, "department": ["in", dept_names], "document_lane": "AP Purchase Order", "is_active": 1},
                "name"
            )
            if m_name:
                return frappe.get_doc("AP Approval Matrix", m_name)

    m_name = frappe.db.get_value(
        "AP Approval Matrix",
        {"company": company, "department": ["in", ["", None]], "document_lane": "AP Purchase Order", "is_active": 1},
        "name"
    )
    if m_name:
        return frappe.get_doc("AP Approval Matrix", m_name)

    return None


class APPurchaseOrder(Document):
    def autoname(self):
        if getattr(self, "name", None):
            return
        from frappe.model.naming import make_autoname
        self.name = make_autoname("PO-.YYYY.-.MM.-.#####")
    def validate(self):
        """Lifecycle validation hook."""
        self.fetch_entity_master_data()
        self.fetch_vendor_master_data()
        self.fetch_spoc_details()
        self.calculate_line_items_and_taxes()
        self.calculate_advance_commercials()
        self.ensure_default_terms()
        self.validate_procurement_quotations()
        self.generate_signatory_hash()
        self.ensure_vendor_esign_token()

    def fetch_entity_master_data(self):
        """Populates company entity details and registered address dynamically per entity."""
        if not getattr(self, "company_entity", None):
            self.company_entity = frappe.defaults.get_user_default("Company") or "Aionion Capital Market Services Private Limited"

        reg = COMPANY_ADDRESS_REGISTRY.get(self.company_entity, {})
        
        comp = frappe.db.get_value(
            "Company",
            self.company_entity,
            ["tax_id", "registration_details", "email", "phone_no"],
            as_dict=True
        ) or {}

        self.company_gstin = comp.get("tax_id") or reg.get("gstin") or "27AAACA1234A1Z5"
        self.company_cin = comp.get("registration_details") or reg.get("cin") or "U74999MH2020PTC123456"
        self.company_contact_email = comp.get("email") or reg.get("email") or "finance@aionion.com"
        self.company_contact_phone = comp.get("phone_no") or reg.get("phone") or "+91 22 6900 1000"
        self.company_registered_address = reg.get("address") or f"{self.company_entity}, Mumbai, Maharashtra"

    def fetch_vendor_master_data(self):
        """Fetches registered supplier details from ERPNext Supplier master."""
        vendor_id = getattr(self, "vendor", None)
        if not vendor_id:
            return

        supp = frappe.db.get_value(
            "Supplier",
            vendor_id,
            ["supplier_name", "tax_id", "country", "mobile_no", "email_id"],
            as_dict=True
        )
        if supp:
            self.vendor_name = supp.supplier_name
            self.vendor_gstin = supp.tax_id or getattr(self, "vendor_gstin", "")
            if not getattr(self, "vendor_email", None):
                self.vendor_email = supp.email_id or ""
            if not getattr(self, "vendor_mobile", None):
                self.vendor_mobile = supp.mobile_no or ""

    def fetch_spoc_details(self):
        """Pulls SPOC details if user link is provided."""
        spoc_user = getattr(self, "spoc_user", None)
        if spoc_user:
            usr = frappe.db.get_value("User", spoc_user, ["full_name", "email", "mobile_no"], as_dict=True)
            if usr:
                if not getattr(self, "spoc_name", None) and usr.full_name:
                    self.spoc_name = usr.full_name
                if not getattr(self, "spoc_email", None) and usr.email:
                    self.spoc_email = usr.email
                if not getattr(self, "spoc_mobile", None) and usr.mobile_no:
                    self.spoc_mobile = usr.mobile_no

            if not getattr(self, "spoc_department", None):
                dept_info = get_user_department_details(spoc_user)
                if dept_info.get("department"):
                    self.spoc_department = dept_info["department"]

    def calculate_line_items_and_taxes(self):
        """Calculates line item subtotals and dynamic location-based GST (IGST vs CGST/SGST)."""
        net_taxable = 0.0
        total_gst = 0.0

        comp_state = (getattr(self, "company_gstin", "") or "")[:2].strip()
        vendor_state = (getattr(self, "vendor_gstin", "") or "")[:2].strip()

        is_intra_state = False
        if comp_state and vendor_state and comp_state == vendor_state:
            is_intra_state = True
            self.gst_type = f"Intra-State (CGST + SGST - State {comp_state})"
        elif comp_state and vendor_state and comp_state != vendor_state:
            is_intra_state = False
            self.gst_type = f"Inter-State (IGST - State {comp_state} to {vendor_state})"
        else:
            is_intra_state = True
            self.gst_type = "Intra-State (Default CGST + SGST)"

        for item in self.get("items", []):
            qty = flt(getattr(item, "qty", 1.0)) or 1.0
            rate = flt(getattr(item, "rate", 0.0)) or 0.0
            discount = flt(getattr(item, "discount_amount", 0.0)) or 0.0
            taxable = round(max((qty * rate) - discount, 0.0), 2)

            gst_rate_str = getattr(item, "gst_rate", "18%") or "18%"
            gst_pct = flt(gst_rate_str.replace("%", "").strip() or 18.0)
            gst_val = round(taxable * (gst_pct / 100.0), 2)

            item.taxable_amount = taxable
            item.gst_amount = gst_val
            item.total_amount = round(taxable + gst_val, 2)

            net_taxable += taxable
            total_gst += gst_val

        self.net_taxable_value = round(net_taxable, 2)
        self.total_gst_amount = round(total_gst, 2)
        self.grand_total = round(net_taxable + total_gst, 2)

        if is_intra_state:
            half_gst = round(total_gst / 2.0, 2)
            self.cgst_amount = half_gst
            self.sgst_amount = round(total_gst - half_gst, 2)
            self.igst_amount = 0.0
        else:
            self.cgst_amount = 0.0
            self.sgst_amount = 0.0
            self.igst_amount = round(total_gst, 2)

    def calculate_advance_commercials(self):
        """Computes advance payment obligation and remaining balance."""
        adv_pct_str = getattr(self, "advance_percentage", "0%") or "0%"
        adv_pct = flt(adv_pct_str.replace("%", "").strip() or 0.0)

        adv_amt = round(flt(self.grand_total) * (adv_pct / 100.0), 2)
        self.advance_amount = adv_amt
        self.balance_due_on_completion = round(flt(self.grand_total) - adv_amt, 2)

    def ensure_default_terms(self):
        """Injects default terms & conditions if empty."""
        if not getattr(self, "terms_and_conditions", None):
            self.terms_and_conditions = DEFAULT_PO_TERMS

    def validate_procurement_quotations(self, is_submitting: bool = False):
        """Validates quotation requirements based on procurement type upon submission."""
        if not is_submitting and self.status in ("Draft", "", None):
            return

        ptype = getattr(self, "procurement_type", None) or "Multiple Vendors (Competitive Bidding)"
        if ptype == "Single / Sole Source Vendor (Direct Procurement)":
            if not getattr(self, "sole_source_justification", None) or len(self.sole_source_justification.strip()) < 10:
                frappe.throw(_("Sole Source Procurement Justification (minimum 10 characters) is mandatory when single vendor is selected."))
            if not getattr(self, "single_quotation_attachment", None):
                frappe.throw(_("Single Vendor Quotation File attachment is mandatory for sole source procurement."))
        elif ptype == "Multiple Vendors (Competitive Bidding)":
            if not getattr(self, "comparison_statement_attachment", None):
                frappe.throw(_("Quotation Comparison Statement / CS Sheet attachment is mandatory for competitive bidding."))
            if not self.get("quotations") or len(self.get("quotations")) == 0:
                frappe.throw(_("At least one evaluated vendor quotation must be added in the quotations table."))

    def generate_signatory_hash(self):
        """Generates digital hash verifying the authorised signatory and PO contents."""
        if not getattr(self, "date_of_issue", None):
            self.date_of_issue = nowdate()

        if getattr(self, "signatory_signature_hash", None) and self.signatory_signature_hash.startswith("SHA256:"):
            return

        sign_name = getattr(self, "signatory_name", "Anshul Gupta") or "Anshul Gupta"
        raw = f"PO|{self.name or 'DRAFT'}|{self.company_entity}|{getattr(self, 'vendor', '')}|{flt(self.grand_total):.2f}|{self.date_of_issue}|{sign_name}"
        full_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self.signatory_signature_hash = f"SHA256:{full_hash[:4].upper()}-{full_hash[4:8].upper()}-{full_hash[8:12].upper()}-{full_hash[12:16].upper()}"

    def ensure_vendor_esign_token(self):
        """Generates secure token and public signing URL for vendor once, keeping it immutable."""
        if getattr(self, "vendor_sign_url", None):
            import urllib.parse
            parsed = urllib.parse.urlparse(self.vendor_sign_url)
            existing_token = urllib.parse.parse_qs(parsed.query).get("token", [None])[0]
            if existing_token:
                self.vendor_sign_token = existing_token
                return

        if not getattr(self, "vendor_sign_token", None):
            self.vendor_sign_token = secrets.token_hex(20)
        
        base_url = get_url()
        self.vendor_sign_url = f"{base_url}/po-sign?token={self.vendor_sign_token}&po={self.name or 'DRAFT'}"

    @frappe.whitelist()
    def submit_po(self):
        """
        Submits PO from Draft into the dynamic multi-tier approval workflow.
        Zero hardcoded departments: dynamically inspects AP Approval Matrix for department / company policy.
        """
        if self.status not in ("Draft", "", None):
            frappe.throw(_(f"Only Draft Purchase Orders can be submitted for approval. Current status is '{self.status}'."))

        if not self.get("items") or len(self.get("items")) == 0:
            frappe.throw(_("Cannot submit Purchase Order without line items."))

        for idx, item in enumerate(self.get("items"), 1):
            if flt(item.qty) <= 0:
                frappe.throw(_(f"Row #{idx}: Quantity must be greater than zero."))
            if flt(item.rate) <= 0:
                frappe.throw(_(f"Row #{idx}: Rate must be greater than zero."))

        if not getattr(self, "vendor_email", None):
            frappe.throw(_("Vendor Email is mandatory for Purchase Order submission."))

        if not getattr(self, "spoc_email", None) or not getattr(self, "spoc_name", None):
            frappe.throw(_("SPOC Name and Official Email are mandatory for Purchase Order submission."))

        # Validate procurement requirements
        self.validate_procurement_quotations(is_submitting=True)

        # Dynamic routing via AP Approval Matrix
        policy = resolve_po_workflow_policy(self.company_entity, self.spoc_department)
        target_status = "Pending HoD Approval"
        next_approver_desc = "Authorised Signatory / Director"

        if policy and policy.get("approval_levels"):
            levels = policy.get("approval_levels")
            first_level = levels[0]
            lvl_name = (first_level.level_name or "").lower()
            if "assistant" in lvl_name:
                target_status = "Pending Assistant Manager Review"
                next_approver_desc = first_level.level_name
            elif "manager" in lvl_name or "l1" in lvl_name or "admin" in lvl_name or len(levels) > 1:
                dept_str = (getattr(self, "spoc_department", "") or "").lower() + " " + lvl_name
                target_status = "Pending Admin Manager Review" if "admin" in dept_str else "Pending Manager Review"
                next_approver_desc = first_level.level_name

        self.status = target_status
        self.flags.ignore_permissions = True
        self.save()

        # Timeline comment in simple English (no emoji)
        self.add_comment(
            "Comment",
            f"Purchase Order submitted for approval by {frappe.session.user}. Status transitioned to {self.status}. Awaiting {next_approver_desc}."
        )

        try:
            from ap_automation.services.notification_service import notify_po_stage_transition
            notify_po_stage_transition(self.name, "Draft", self.status)
        except Exception as e:
            frappe.log_error(f"Error dispatching PO submission notification: {e}")

        return {"status": "success", "message": f"Purchase Order #{self.name} submitted. Status: {self.status}."}

    # Backward compatibility alias
    @frappe.whitelist()
    def submit_for_hod_approval(self):
        return self.submit_po()

    @frappe.whitelist()
    def review_by_assistant_manager(self, comments: Optional[str] = None):
        """Assistant Manager reviews PO and forwards to Department / Admin Manager."""
        if self.status != "Pending Assistant Manager Review":
            frappe.throw(_(f"PO must be in 'Pending Assistant Manager Review'. Current status: '{self.status}'."))

        self.assistant_manager_reviewer = frappe.session.user
        self.assistant_manager_reviewed_on = now_datetime()
        
        # Route to manager stage
        dept = (getattr(self, "spoc_department", "") or "").lower()
        if "admin" in dept:
            self.status = "Pending Admin Manager Review"
        else:
            self.status = "Pending Manager Review"

        self.flags.ignore_permissions = True
        self.save()

        note = f" Comments: {comments}" if comments else ""
        self.add_comment(
            "Comment",
            f"Assistant Manager review completed by {frappe.session.user}. Status transitioned to {self.status}.{note}"
        )

        try:
            from ap_automation.services.notification_service import notify_po_stage_transition
            notify_po_stage_transition(self.name, "Pending Assistant Manager Review", self.status)
        except Exception as e:
            frappe.log_error(f"PO Assistant Manager review notification error: {e}")

        return {"status": "success", "message": f"Purchase Order #{self.name} forwarded to Manager.", "po_status": self.status}

    @frappe.whitelist()
    def review_by_manager(self, comments: Optional[str] = None):
        """Department / Admin Manager reviews PO and forwards for Director Final Sanction."""
        if self.status not in ("Pending Admin Manager Review", "Pending Manager Review", "Pending Assistant Manager Review"):
            frappe.throw(_(f"PO cannot be reviewed by Manager in '{self.status}' status."))

        self.manager_reviewer = frappe.session.user
        self.manager_reviewed_on = now_datetime()
        self.status = "Pending HoD Approval"
        self.flags.ignore_permissions = True
        self.save()

        note = f" Comments: {comments}" if comments else ""
        self.add_comment(
            "Comment",
            f"Manager approval granted by {frappe.session.user}. Forwarded for Director Final Sanction and Digital Seal.{note}"
        )

        try:
            from ap_automation.services.notification_service import notify_po_stage_transition
            notify_po_stage_transition(self.name, "Pending Manager Review", "Pending HoD Approval")
        except Exception as e:
            frappe.log_error(f"PO Manager review notification error: {e}")

        return {"status": "success", "message": f"Purchase Order #{self.name} forwarded for Director Approval.", "po_status": self.status}

    @frappe.whitelist()
    def return_po(self, remarks: str = "Commercial discrepancy"):
        """Returns PO to Draft for corrections."""
        if not remarks or len(remarks.strip()) < 5:
            frappe.throw(_("Return remarks are required."))

        prev_status = self.status
        self.status = "Draft"
        self.rejection_reason = remarks.strip()
        self.flags.ignore_permissions = True
        self.save()

        self.add_comment(
            "Comment",
            f"Purchase Order returned to Draft by {frappe.session.user}. Reason: {remarks.strip()}"
        )

        try:
            from ap_automation.services.notification_service import notify_po_returned
            notify_po_returned(self.name, remarks.strip())
        except Exception as e:
            frappe.log_error(f"PO return notification error: {e}")

        return {"status": "success", "message": f"Purchase Order #{self.name} returned to Draft."}

    # Backward compatibility alias
    @frappe.whitelist()
    def reject_by_hod(self, remarks: str = "Commercial discrepancy"):
        return self.return_po(remarks)

    @frappe.whitelist()
    def cancel_po(self, reason: str):
        """Cancels an existing PO with mandatory remarks."""
        if not reason or len(reason.strip()) < 10:
            frappe.throw(_("A cancellation reason (minimum 10 characters) is mandatory."))

        if self.status == "Cancelled":
            frappe.throw(_("Purchase Order is already cancelled."))

        self.status = "Cancelled"
        self.cancellation_reason = reason.strip()
        self.cancelled_by = frappe.session.user
        self.cancelled_on = now_datetime()
        self.flags.ignore_permissions = True
        self.save()

        self.add_comment(
            "Comment",
            f"Purchase Order cancelled by {frappe.session.user}. Reason: {reason.strip()}"
        )

        try:
            from ap_automation.services.notification_service import notify_po_cancelled
            notify_po_cancelled(self.name, reason.strip())
        except Exception as e:
            frappe.log_error(f"PO cancellation notification error: {e}")

        return {"status": "success", "message": f"Purchase Order #{self.name} cancelled successfully."}

    @frappe.whitelist()
    def revise_po(self, reason: str) -> Dict[str, Any]:
        """
        Creates a new version clone of an existing PO (e.g. PO-2026-11-00001 -> PO-2026-11-00001-R1).
        Marks the previous PO as 'Superseded / Revised' and routes the new PO for re-approval.
        """
        if not reason or len(reason.strip()) < 10:
            frappe.throw(_("A revision reason (minimum 10 characters) is mandatory."))

        if self.status in ("Draft", "Cancelled", "Superseded / Revised"):
            frappe.throw(_(f"Purchase Order in '{self.status}' status cannot be revised."))

        # Determine revision suffix
        base_name = self.original_po or self.name
        match = re.search(r"-R(\d+)$", self.name)
        if match:
            rev_num = int(match.group(1)) + 1
            new_po_name = re.sub(r"-R\d+$", f"-R{rev_num}", self.name)
        else:
            rev_num = 1
            new_po_name = f"{self.name}-R{rev_num}"

        # Clone document
        new_po = frappe.new_doc("AP Purchase Order")
        copy_fields = [
            "company_entity", "vendor", "vendor_name", "vendor_registered_address",
            "vendor_gstin", "msme_category", "vendor_contact_person", "vendor_email",
            "vendor_mobile", "spoc_user", "spoc_name", "spoc_department", "spoc_email",
            "spoc_mobile", "service_type", "default_uom", "is_subscription",
            "subscription_start_date", "subscription_end_date", "auto_renewal_alert",
            "payment_terms", "advance_percentage", "terms_and_conditions",
            "procurement_type", "sole_source_justification", "single_quotation_attachment",
            "comparison_statement_attachment"
        ]
        for f in copy_fields:
            if hasattr(self, f):
                setattr(new_po, f, getattr(self, f))

        # Copy line items
        for it in self.get("items", []):
            new_po.append("items", {
                "item_name": it.item_name,
                "description": it.description,
                "hsn_sac_code": it.hsn_sac_code,
                "uom": it.uom,
                "qty": it.qty,
                "rate": it.rate,
                "discount_amount": it.discount_amount,
                "gst_rate": it.gst_rate
            })

        # Copy quotations
        for q in self.get("quotations", []):
            new_po.append("quotations", {
                "vendor_name": q.vendor_name,
                "quotation_ref": q.quotation_ref,
                "quotation_date": q.quotation_date,
                "quoted_amount": q.quoted_amount,
                "quotation_file": q.quotation_file,
                "is_selected": q.is_selected,
                "selection_justification": q.selection_justification
            })

        new_po.name = new_po_name
        new_po.revision_version = rev_num
        new_po.original_po = base_name
        new_po.previous_po_version = self.name
        new_po.is_latest_version = 1
        new_po.revision_reason = reason.strip()
        new_po.status = "Draft"
        new_po.insert(set_name=new_po_name, ignore_permissions=True)

        # Mark current PO as Superseded
        self.status = "Superseded / Revised"
        self.is_latest_version = 0
        self.flags.ignore_permissions = True
        self.save()

        # Cross-linked audit comments
        self.add_comment(
            "Comment",
            f"This Purchase Order has been superseded and revised into new version {new_po.name}. Reason: {reason.strip()}"
        )
        new_po.add_comment(
            "Comment",
            f"Revision version created from preceding PO {self.name}. Reason: {reason.strip()}"
        )

        try:
            from ap_automation.services.notification_service import notify_po_revised
            notify_po_revised(self.name, new_po.name, reason.strip())
        except Exception as e:
            frappe.log_error(f"PO revision notification error: {e}")

        return {
            "status": "success",
            "message": f"Purchase Order revised successfully into version #{new_po.name}.",
            "new_po_name": new_po.name
        }

    @frappe.whitelist()
    def send_po_to_vendor_for_esign(self):
        """Sends the generated PO and E-Sign token link to the vendor via email."""
        if not getattr(self, "vendor_email", None):
            frappe.throw(_("Vendor Email is required to send Purchase Order for digital signature."))

        self.vendor_sign_status = "Sent to Vendor"
        self.save()

        subject = f"Purchase Order #{self.name} from {self.company_entity} - Signature Requested"
        message = f"""
        <p>Dear {getattr(self, 'vendor_contact_person', None) or self.vendor_name},</p>
        <p>Please find enclosed Purchase Order <strong>#{self.name}</strong> for <strong>₹{self.grand_total:,.2f}</strong> issued by <strong>{self.company_entity}</strong>.</p>
        <p><strong>Department SPOC:</strong> {self.spoc_name} ({self.spoc_email})</p>
        <p>Please review the details and sign digitally using the secure link below:</p>
        <p><a href="{self.vendor_sign_url}" style="background-color: #1B365D; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block;">Review & Sign Purchase Order &rarr;</a></p>
        <p>Regards,<br>{getattr(self, 'signatory_name', 'Anshul Gupta')}<br>{getattr(self, 'signatory_designation', 'Director')}<br>{self.company_entity}</p>
        """

        try:
            frappe.sendmail(
                recipients=[self.vendor_email],
                cc=[self.spoc_email] if getattr(self, "spoc_email", None) else [],
                subject=subject,
                message=message,
                now=False
            )
        except Exception as e:
            frappe.log_error(f"PO E-Sign email dispatch notification: {e}")

    @frappe.whitelist()
    def record_vendor_esign(self, signer_name: str, signer_ip: str, signature_data: str = None):
        """Records vendor's digital signature stamp and activates the Purchase Order."""
        self.vendor_signed_by = signer_name
        self.vendor_signed_ip = signer_ip
        self.vendor_signed_timestamp = now_datetime()
        self.vendor_sign_status = "Digitally Signed"
        self.status = "Active PO"
        self.save(ignore_permissions=True)
        frappe.db.commit()
        try:
            from ap_automation.services.notification_service import notify_on_vendor_po_signed
            notify_on_vendor_po_signed(self.name)
        except Exception as e:
            frappe.log_error(f"PO signed notification error: {e}")
        return {"status": "success", "message": "Purchase Order digitally accepted and signed."}

    @frappe.whitelist()
    def record_vendor_rejection(self, reason: str = "Commercial terms discrepancy"):
        """Records vendor rejection and notifies SPOC."""
        self.vendor_sign_status = "Rejected by Vendor"
        self.status = "Cancelled"
        self.save(ignore_permissions=True)
        frappe.db.commit()
        try:
            from ap_automation.services.notification_service import notify_on_vendor_po_rejected
            notify_on_vendor_po_rejected(self.name, reason)
        except Exception as e:
            frappe.log_error(f"PO rejection notification error: {e}")
        return {"status": "success", "message": "Purchase Order marked as rejected by vendor."}


@frappe.whitelist()
def submit_for_hod_approval(po_name: str):
    """Module-level whitelisted API to submit PO for approval."""
    if not po_name:
        frappe.throw(_("PO Name is required."))
    doc = frappe.get_doc("AP Purchase Order", po_name)
    return doc.submit_po()


@frappe.whitelist()
def reject_by_hod(po_name: str, remarks: str = "Commercial discrepancy"):
    """Module-level whitelisted API to return PO from review."""
    if not po_name:
        frappe.throw(_("PO Name is required."))
    doc = frappe.get_doc("AP Purchase Order", po_name)
    return doc.return_po(remarks)


@frappe.whitelist()
def review_by_assistant_manager(po_name: str, comments: Optional[str] = None):
    doc = frappe.get_doc("AP Purchase Order", po_name)
    return doc.review_by_assistant_manager(comments)


@frappe.whitelist()
def review_by_manager(po_name: str, comments: Optional[str] = None):
    doc = frappe.get_doc("AP Purchase Order", po_name)
    return doc.review_by_manager(comments)


@frappe.whitelist()
def cancel_po(po_name: str, reason: str):
    doc = frappe.get_doc("AP Purchase Order", po_name)
    return doc.cancel_po(reason)


@frappe.whitelist()
def revise_po(po_name: str, reason: str):
    doc = frappe.get_doc("AP Purchase Order", po_name)
    return doc.revise_po(reason)
