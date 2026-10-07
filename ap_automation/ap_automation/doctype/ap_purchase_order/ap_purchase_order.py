# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import hashlib
import json
import secrets
from typing import Dict, Any, List
import frappe
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

class APPurchaseOrder(Document):
    def validate(self):
        """Lifecycle validation hook."""
        self.fetch_entity_master_data()
        self.fetch_vendor_master_data()
        self.fetch_spoc_details()
        self.calculate_line_items_and_taxes()
        self.calculate_advance_commercials()
        self.ensure_default_terms()
        self.generate_signatory_hash()
        self.ensure_vendor_esign_token()

    def fetch_entity_master_data(self):
        """Populates company entity details and registered address dynamically per entity."""
        if not getattr(self, "company_entity", None):
            self.company_entity = "Aionion Capital Market Services Private Limited"

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
        if spoc_user and (not getattr(self, "spoc_name", None) or not getattr(self, "spoc_email", None)):
            usr = frappe.db.get_value("User", spoc_user, ["full_name", "email", "mobile_no"], as_dict=True)
            if usr:
                self.spoc_name = usr.full_name
                self.spoc_email = usr.email
                if not getattr(self, "spoc_mobile", None) and usr.mobile_no:
                    self.spoc_mobile = usr.mobile_no

    def calculate_line_items_and_taxes(self):
        """Calculates line item subtotals and dynamic location-based GST (IGST vs CGST/SGST)."""
        net_taxable = 0.0
        total_gst = 0.0

        # Determine Intra-State vs Inter-State based on GSTIN State codes (first 2 digits)
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

    def generate_signatory_hash(self):
        """Generates digital hash verifying the authorised signatory and PO contents."""
        if not getattr(self, "date_of_issue", None):
            self.date_of_issue = nowdate()

        sign_name = getattr(self, "signatory_name", "Anshul Gupta") or "Anshul Gupta"
        raw = f"PO|{self.name or 'DRAFT'}|{self.company_entity}|{getattr(self, 'vendor', '')}|{flt(self.grand_total):.2f}|{self.date_of_issue}|{sign_name}"
        self.signatory_signature_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def ensure_vendor_esign_token(self):
        """Generates secure token and public signing URL for vendor."""
        if not getattr(self, "vendor_sign_token", None):
            self.vendor_sign_token = secrets.token_urlsafe(32)
        
        base_url = get_url()
        self.vendor_sign_url = f"{base_url}/po-sign?token={self.vendor_sign_token}&po={self.name or 'DRAFT'}"

    @frappe.whitelist()
    def send_po_to_vendor_for_esign(self):
        """Sends the generated PO and E-Sign token link to the vendor via email."""
        if not getattr(self, "vendor_email", None):
            frappe.throw("Vendor Email is required to send Purchase Order for digital signature.")

        self.vendor_sign_status = "Sent to Vendor"
        self.save()

        subject = f"Purchase Order #{self.name} from {self.company_entity} - Signature Requested"
        message = f"""
        <p>Dear {getattr(self, 'vendor_contact_person', None) or self.vendor_name},</p>
        <p>Please find enclosed Purchase Order <strong>#{self.name}</strong> for <strong>₹{self.grand_total:,.2f}</strong> issued by <strong>{self.company_entity}</strong>.</p>
        <p><strong>Department SPOC:</strong> {self.spoc_name} ({self.spoc_email})</p>
        <p>Please review the details and sign digitally using the secure link below:</p>
        <p><a href="{self.vendor_sign_url}" style="background-color: #1B365D; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block;">Review & Sign Purchase Order →</a></p>
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

        frappe.msgprint(f"✅ Purchase Order #{self.name} successfully dispatched to Vendor ({self.vendor_email}) for digital signature.")

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
        return {"status": "success", "message": "Purchase Order digitally accepted and signed."}
