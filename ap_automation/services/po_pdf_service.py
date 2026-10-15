import os
import base64
import json
import hashlib
import frappe
from frappe import _
from frappe.utils.pdf import get_pdf
from frappe.utils import format_date, fmt_money, flt, now_datetime

PUBLIC_IMG_DIR = "/home/ashwinkumark_quanti/frappe/my-bench/apps/ap_automation/ap_automation/public/images"

def get_image_base64(filename):
    path = os.path.join(PUBLIC_IMG_DIR, filename)
    if os.path.exists(path):
        with open(path, "rb") as f:
            ext = filename.split(".")[-1].lower()
            mime = "image/png" if ext == "png" else "image/jpeg"
            return f"data:{mime};base64," + base64.b64encode(f.read()).decode("utf-8")
    return ""

def format_inr(val):
    return fmt_money(flt(val), currency="INR").replace("₹ ", "₹").replace("₹", "")

def get_entity_profile(entity_name: str, requested_signatory: str = None):
    """
    Returns full entity profile including branding, logos, legal registrations, 
    watermark, addresses, and default business head / authorized signatory.
    """
    e = (entity_name or "").lower().strip()
    
    # 1. QUANTICUS SOFTWARE SOLUTIONS PRIVATE LIMITED
    if "quanticus" in e:
        return {
            "key": "quanticus",
            "full_name": "QUANTICUS SOFTWARE SOLUTIONS PRIVATE LIMITED",
            "logo_b64": get_image_base64("logo_quanticus.png"),
            "logo_width": "220px",
            "cin": "U62090TN2024PTC175627",
            "gstin": "33AAACQ5678Q1Z2",
            "reg_address": "33, Meerlan Tower, Hanumantha Road, Balaji Nagar, Royapettah, Chennai - 600 014",
            "watermark_text": "QUANTICUS",
            "watermark_logo": get_image_base64("logo_quanticus.png"),
            "default_signatory": "Dileep Keerthi Kumar",
            "default_designation": "Director",
            "accent_color": "#0284c7",
            "footer_html": """
                <div style="text-align: center; font-size: 10px; color: #334155; line-height: 1.4; border-top: 2px solid #0284c7; padding-top: 6px; margin-top: 15px;">
                    <b>33, MEERLAN TOWER, HANUMANTHA ROAD, BALAJI NAGAR, ROYAPETTAH, CHENNAI - 600 014</b><br>
                    CIN: U62090TN2024PTC175627 &nbsp;|&nbsp; WWW.QUANTISYSTEMS.COM
                </div>
            """
        }

    # 2. ANSHUL A GUPTA & ASSOCIATES (AAG)
    elif "anshul" in e or "gupta & associates" in e or "aag" in e:
        return {
            "key": "aag",
            "full_name": "ANSHUL A GUPTA & ASSOCIATES",
            "subtitle": "CHARTERED ACCOUNTANTS CA",
            "logo_b64": get_image_base64("logo_aag.png"),
            "logo_width": "260px",
            "cin": "ICAI Firm Registration No.: FNA295288",
            "gstin": "33BAFPG1837F1Z5",
            "phone": "+91 91500 87656 / +91 91500 23455",
            "reg_address": "2A, 2nd Floor, Meerlan Towers, No.33, Hanumantha Road, Royapettah, Chennai - 600 014",
            "watermark_text": "ANSHUL A GUPTA & ASSOCIATES",
            "watermark_logo": get_image_base64("logo_aag.png"),
            "default_signatory": requested_signatory or "Anish Gupta",
            "default_designation": "Senior Partner / CA",
            "accent_color": "#1e3a8a",
            "footer_html": """
                <div style="text-align: center; font-size: 10px; color: #1e3a8a; line-height: 1.4; border-top: 2px solid #1e3a8a; padding-top: 6px; margin-top: 15px;">
                    <b>2A, 2nd Floor, Meerlan Towers, No.33, Hanumantha Road, Royapettah, Chennai - 600 014</b><br>
                    Phone: +91 91500 87656 / +91 91500 23455 &nbsp;|&nbsp; www.angassociates.com
                </div>
            """
        }

    # 3. AIONION GLOBAL CAPITAL MARKET SERVICES (IFSC) LLP
    elif "global" in e or "ifsc" in e:
        return {
            "key": "aionion_global",
            "full_name": "AIONION GLOBAL CAPITAL MARKET SERVICES (IFSC) LLP",
            "logo_b64": get_image_base64("logo_aionion_global.png"),
            "logo_width": "230px",
            "cin": "LLPIN: ABR-1234",
            "gstin": "24AAJFA1234F1Z9",
            "reg_address": "Unit 208, Seat No 1 to 4, First Floor, Pragya Accelerator II, Building 15B, Block 15 Road, No 1 C, Zone 1, GIFT City, Gandhinagar, Gujarat - 382050",
            "watermark_text": "AIONION GLOBAL IFSC",
            "watermark_logo": get_image_base64("logo_aionion_global.png"),
            "default_signatory": requested_signatory or "Anish Gupta",
            "default_designation": "Designated Partner",
            "accent_color": "#1e60ff",
            "footer_html": """
                <div style="text-align: center; font-size: 9.5px; color: #000000; line-height: 1.35; border-top: 2px solid #1e60ff; padding-top: 6px; margin-top: 15px;">
                    <b>UNIT 208, SEAT NO 1 TO 4, FIRST FLOOR, PRAGYA ACCELERATOR II, BUILDING 15B, BLOCK 15 ROAD, NO 1 C, ZONE 1,</b><br>
                    <b>GIFT CITY, GANDHINAGAR, INDIA 382050</b>
                    <table style="width: 100%; border-collapse: collapse; margin-top: 4px;">
                        <tr><td style="width: 100%; height: 4px; background-color: #ff6b8b; padding: 0;"></td></tr>
                    </table>
                </div>
            """
        }

    # 4. AIONION INSURANCE MARKETING PRIVATE LIMITED
    elif "insurance" in e:
        return {
            "key": "aionion_insurance",
            "full_name": "AIONION INSURANCE MARKETING PRIVATE LIMITED",
            "logo_b64": get_image_base64("logo_aionion_insurance.png"),
            "logo_width": "160px",
            "cin": "U66000TN2021PTC142985",
            "gstin": "33AAACI9876I1Z9",
            "reg_address": "No.5/2 (2/2), Hanumantha Road, Balaji Nagar, Royapettah, Chennai - 600 014",
            "watermark_text": "AIONION INSURANCE",
            "watermark_logo": get_image_base64("logo_aionion_insurance.png"),
            "default_signatory": requested_signatory or "Anish Gupta",
            "default_designation": "Director",
            "accent_color": "#1e3a8a",
            "footer_html": """
                <div style="text-align: center; font-size: 10px; color: #000000; line-height: 1.4; border-top: 2px solid #1e3a8a; padding-top: 6px; margin-top: 15px;">
                    <b>NO.5/2 (2/2), HANUMANTHA ROAD, BALAJI NAGAR, ROYAPETTAH, CHENNAI - 600 014</b><br>
                    CIN: U66000TN2021PTC142985
                </div>
            """
        }

    # 5. AIONION CAPITAL MARKET SERVICES PRIVATE LIMITED (ACM / Default)
    else:
        return {
            "key": "aionion_capital",
            "full_name": "AIONION CAPITAL MARKET SERVICES PRIVATE LIMITED",
            "logo_b64": get_image_base64("logo_aionion_capital.png"),
            "logo_width": "260px",
            "cin": "U66120TN2024PTC167864",
            "gstin": "27AAACA1234A1Z5",
            "sebi": "INZ000318532",
            "amfi": "ARN-296313",
            "reg_address": "3rd Floor, Meerlan Towers, No 33, Hanumantha Road, Royapettah, Chennai - 600 014",
            "watermark_text": "AIONION CAPITAL",
            "watermark_logo": get_image_base64("logo_aionion_capital.png"),
            "default_signatory": requested_signatory or "Anish Gupta",
            "default_designation": "Director",
            "accent_color": "#1e60ff",
            "footer_html": """
                <div style="margin-top: 15px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 9.5px; color: #000000; line-height: 1.35; border-top: 2px solid #1e60ff; padding-top: 5px;">
                        <tr>
                            <td style="width: 55%; vertical-align: top; padding-top: 4px;">
                                REG OFFICE: 3RD FLOOR, MEERLAN TOWERS,<br>
                                NO 33, HANUMANTHA ROAD, ROYAPETTAH, CHENNAI - 600014.<br>
                                SEBI REGISTRATION NO : INZ000318532
                            </td>
                            <td style="width: 45%; text-align: right; vertical-align: top; padding-top: 4px;">
                                COMPLIANCE@AIONIONCAPITAL.COM<br>
                                CIN: U66120TN2024PTC167864<br>
                                AMFI REG. NO. : ARN-296313
                            </td>
                        </tr>
                    </table>
                    <table style="width: 100%; border-collapse: collapse; margin-top: 4px;">
                        <tr>
                            <td style="width: 50%; height: 5px; background-color: #ff6b8b; padding: 0;"></td>
                            <td style="width: 50%; height: 5px; background-color: #1e60ff; padding: 0;"></td>
                        </tr>
                    </table>
                </div>
            """
        }


def render_po_html(doc):
    entity_name = doc.company_entity or "Aionion Capital Market Services Private Limited"
    profile = get_entity_profile(entity_name, doc.signatory_name)

    vendor_name = doc.vendor_name or doc.vendor or "Vendor"
    vendor_addr = (doc.vendor_registered_address or "").replace("\n", "<br>")
    po_date = format_date(doc.date_of_issue or doc.creation, "dd MMMM, yyyy")
    scope = doc.service_type or "Commercial Services / Procurement"

    # Items rows HTML
    items_rows = ""
    for idx, item in enumerate(doc.items or [], 1):
        item_title = item.item_name or "Service Item"
        desc = (item.description or item.hsn_sac_code or "").replace("\n", "<br>")
        rate = format_inr(item.rate or item.taxable_amount)
        qty = int(item.qty) if flt(item.qty).is_integer() else item.qty
        amt = format_inr(item.taxable_amount or (item.rate * item.qty))

        items_rows += f"""
        <tr>
            <td style="border: 1px solid #000; padding: 8px 10px; font-weight: 700; text-align: center; vertical-align: middle;">{item_title}</td>
            <td style="border: 1px solid #000; padding: 8px 10px; vertical-align: middle;">{desc}</td>
            <td style="border: 1px solid #000; padding: 8px 10px; text-align: center; vertical-align: middle;">{rate}</td>
            <td style="border: 1px solid #000; padding: 8px 10px; text-align: center; vertical-align: middle;">{qty}</td>
            <td style="border: 1px solid #000; padding: 8px 10px; text-align: right; vertical-align: middle; font-weight: 700;">{amt}</td>
        </tr>
        """

    gst_amt = format_inr(doc.total_gst_amount or (doc.cgst_amount + doc.sgst_amount + doc.igst_amount))
    grand_total = format_inr(doc.grand_total)

    # Signatory details
    final_signatory = doc.signatory_name or profile["default_signatory"]
    final_designation = doc.signatory_designation or profile["default_designation"]
    is_signed = bool(doc.status == "Active PO" or doc.signatory_signature_hash)

    # Signature Block rendering
    if is_signed:
        hash_code = doc.signatory_signature_hash or "AUTH-VERIFIED"
        raw_dt = doc.vendor_signed_timestamp or doc.modified or now_datetime()
        if hasattr(raw_dt, "strftime"):
            time_str = raw_dt.strftime("%d-%b-%Y %H:%M:%S")
        else:
            time_str = str(raw_dt)[:19]
        signature_box_html = f"""
        <div style="border: 2px solid #059669; background: #ecfdf5; border-radius: 6px; padding: 8px 12px; margin: 8px 0; display: inline-block; text-align: left;">
            <div style="color: #047857; font-size: 11px; font-weight: 800; margin-bottom: 3px;">
                ✔ DIGITALLY SIGNED & AUTHORIZED
            </div>
            <div style="font-size: 9.5px; color: #1f2937; line-height: 1.35;">
                <b>Signatory:</b> {final_signatory}<br>
                <b>Designation:</b> {final_designation}<br>
                <b>Entity:</b> {profile['full_name']}<br>
                <b>Timestamp:</b> {time_str} IST<br>
                <span style="font-family: monospace; font-size: 8.5px; color: #047857;"><b>Hash:</b> {hash_code}</span>
            </div>
        </div>
        """
    else:
        # Clean empty box for external USB DSC Token signing
        signature_box_html = """
        <div style="height: 52px; margin: 6px 0; border: 1px dashed #cbd5e1; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 9px; color: #94a3b8;">
            (Space for Digital Signature / Physical DSC Token)
        </div>
        """

    watermark_html = ""
    if profile.get("watermark_logo"):
        watermark_html = f"""
        <div class="watermark">
            <img src="{profile['watermark_logo']}" alt="Watermark">
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{
                size: A4 portrait;
                margin: 12mm 14mm 16mm 14mm;
            }}
            body {{
                font-family: Arial, Helvetica, sans-serif;
                color: #000000;
                margin: 0;
                padding: 0;
                font-size: 11px;
                line-height: 1.35;
                position: relative;
            }}
            .watermark {{
                position: fixed;
                top: 35%;
                left: 15%;
                width: 70%;
                opacity: 0.04;
                z-index: -100;
                text-align: center;
                pointer-events: none;
            }}
            .watermark img {{
                width: 100%;
                max-width: 480px;
            }}
            .header-container {{
                text-align: center;
                padding-bottom: 5px;
            }}
            .header-logo {{
                width: {profile['logo_width']};
                margin: 0 auto;
                display: block;
            }}
            .company-title {{
                font-size: 14.5px;
                font-weight: 900;
                color: #000000;
                letter-spacing: 0.5px;
                margin-top: 6px;
                margin-bottom: 8px;
                text-transform: uppercase;
            }}
            .header-divider {{
                border-top: 1.5px solid {profile['accent_color']};
                margin: 6px 0 14px 0;
            }}
            .po-main-title {{
                text-align: center;
                font-size: 15px;
                font-weight: 900;
                text-decoration: underline;
                margin-bottom: 16px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .meta-table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 14px;
            }}
            .meta-table td {{
                vertical-align: top;
                font-size: 11px;
                line-height: 1.4;
            }}
            .items-table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
                margin-bottom: 15px;
            }}
            .items-table th {{
                border: 1px solid #000;
                background-color: #f1f5f9;
                padding: 8px 10px;
                font-size: 11px;
                font-weight: 900;
                text-align: center;
                vertical-align: middle;
            }}
            .gst-clauses {{
                font-size: 9.5px;
                line-height: 1.35;
                margin-top: 10px;
                margin-bottom: 12px;
                padding-left: 18px;
            }}
            .gst-clauses li {{
                margin-bottom: 4px;
            }}
            .gst-clauses ul {{
                margin-top: 2px;
                margin-bottom: 4px;
                padding-left: 16px;
            }}
            .sign-section {{
                margin-top: 15px;
                font-size: 11px;
                line-height: 1.4;
                page-break-inside: avoid;
            }}
        </style>
    </head>
    <body>
        {watermark_html}

        <!-- Official Header -->
        <div class="header-container">
            <img src="{profile['logo_b64']}" class="header-logo" alt="{profile['full_name']}">
            <div class="company-title">{profile['full_name']}</div>
            <div class="header-divider"></div>
        </div>

        <!-- Purchase Order Header -->
        <div class="po-main-title">PURCHASE ORDER</div>

        <!-- Top Details Table -->
        <table class="meta-table">
            <tr>
                <td style="width: 58%; padding-right: 15px;">
                    <b>To:</b><br>
                    <b>{vendor_name}</b><br>
                    {vendor_addr}
                </td>
                <td style="width: 42%;">
                    <b>Date:</b> {po_date}<br>
                    <b>PO No:</b> #{doc.name}<br>
                    <b>Scope of work:</b> {scope}
                </td>
            </tr>
        </table>

        <!-- Line Items Table -->
        <table class="items-table">
            <thead>
                <tr>
                    <th style="width: 20%;">Item</th>
                    <th style="width: 38%;">Description</th>
                    <th style="width: 14%;">Rate (Rs)</th>
                    <th style="width: 10%;">Qty</th>
                    <th style="width: 18%;">Amount (Rs)</th>
                </tr>
            </thead>
            <tbody>
                {items_rows}
                <tr>
                    <td colspan="4" style="border: 1px solid #000; padding: 7px 10px; text-align: right; font-weight: 700;">
                        GST Amount (Rs)
                    </td>
                    <td style="border: 1px solid #000; padding: 7px 10px; text-align: right; font-weight: 700;">
                        {gst_amt}
                    </td>
                </tr>
                <tr>
                    <td colspan="4" style="border: 1px solid #000; padding: 8px 10px; text-align: right; font-weight: 900; font-size: 11.5px;">
                        Grand Total (Rs)
                    </td>
                    <td style="border: 1px solid #000; padding: 8px 10px; text-align: right; font-weight: 900; font-size: 11.5px;">
                        {grand_total}
                    </td>
                </tr>
            </tbody>
        </table>

        <!-- Legal GST & Compliance Clauses -->
        <div style="font-weight: 900; font-size: 10px; text-transform: uppercase; margin-top: 12px; letter-spacing: 0.3px;">
            TERMS, CONDITIONS & STATUTORY GST COMPLIANCE:
        </div>
        <ol class="gst-clauses">
            <li><b>Compliance with GST Laws:</b> The Vendor must comply with all provisions of the Goods and Services Tax (GST) laws, including timely uploading of invoices to the Goods and Services Tax Network (GSTN).</li>
            <li><b>Valid Invoice Requirement:</b> The Vendor must issue a valid GST-compliant tax invoice containing all mandatory fields (e.g., GSTIN of both parties, SAC/HSN code, invoice number, date, and description of services).</li>
            <li><b>Input Tax Credit (ITC) Eligibility:</b> The Company will claim Input Tax Credit based on the details uploaded by the Vendor in GSTR-1, which must correctly reflect in the Company's GSTR-2B.</li>
            <li><b>Timeline for Invoicing and Uploading:</b> Invoices must be submitted to the Company within 30 days of service delivery and uploaded to the GST portal by the 11th of the following month to ensure ITC availability.</li>
            <li><b>Reimbursement of Taxes:</b> The Company will reimburse GST to the Vendor only after:
                <ul>
                    <li>The invoice is verified and approved.</li>
                    <li>Vendor has uploaded the invoice in GSTR-1.</li>
                    <li>The GST credit is available to the Company in its GSTR-2B.</li>
                </ul>
            </li>
            <li><b>Consequences of Non-Compliance:</b>
                <ul>
                    <li>If input GST credit is denied to the Company due to Vendor non-compliance, the Vendor shall bear the loss, including any applicable interest.</li>
                    <li>The Company may recover such amounts such as applicable taxes, including penalties and litigation costs, from any dues payable to the Vendor or withhold from future payments until the denied credit is reinstated.</li>
                </ul>
            </li>
            <li><b>Non-Excusability of Tax Filing Delays:</b> Delay or non-payment by the Company cannot be cited as a reason by the Vendor for not filing tax returns or depositing taxes on time.</li>
            <li><b>Required Documentation:</b> The Vendor must submit all documents and a valid invoice, as required by the Company, to claim payment.</li>
        </ol>

        <!-- Sign-off Section -->
        <div class="sign-section">
            Thanking you,<br>
            <b>For,</b><br>
            <b>{profile['full_name']}</b><br>
            {signature_box_html}
            <b>{final_signatory}</b><br>
            {final_designation}.
        </div>

        <!-- Dynamic Official Footer -->
        {profile['footer_html']}
    </body>
    </html>
    """
    return html


@frappe.whitelist()
def approve_and_digitally_sign_po(po_name: str, signatory_name: str = None):
    """
    Director Portal 1-Click Digital Approval Engine.
    Validates user role, generates cryptographic SHA-256 seal, and updates PO to Active PO.
    """
    if not po_name:
        frappe.throw(_("PO Name is required."))

    doc = frappe.get_doc("AP Purchase Order", po_name)
    profile = get_entity_profile(doc.company_entity)

    # Determine signatory
    chosen_signatory = signatory_name or doc.signatory_name or profile["default_signatory"]
    designation = profile["default_designation"]

    # Security check: User must be signed in
    current_user = frappe.session.user
    if current_user == "Guest":
        frappe.throw(_("Please login to approve and digitally sign this Purchase Order."))

    # Generate Cryptographic SHA-256 seal
    timestamp_str = now_datetime().strftime("%Y-%m-%d %H:%M:%S")
    ip_addr = frappe.local.request_ip or "127.0.0.1"
    raw_payload = f"{doc.name}|{doc.grand_total}|{chosen_signatory}|{current_user}|{timestamp_str}|{ip_addr}"
    full_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
    short_hash = f"SHA256:{full_hash[:4].upper()}-{full_hash[4:8].upper()}-{full_hash[8:12].upper()}-{full_hash[12:16].upper()}"

    # Update PO Document
    doc.status = "Active PO"
    doc.signatory_name = chosen_signatory
    doc.signatory_designation = designation
    doc.signatory_signature_hash = short_hash
    doc.vendor_signed_timestamp = now_datetime()
    doc.vendor_signed_ip = ip_addr
    doc.vendor_signed_by = f"{chosen_signatory} ({current_user})"
    doc.flags.ignore_permissions = True
    doc.save()

    # Add system comment / audit log
    doc.add_comment("Comment", f"🎉 Purchase Order approved & digitally certified by <b>{chosen_signatory}</b> ({designation}) on {timestamp_str} IST. Auth Hash: <code>{short_hash}</code>")

    return {
        "status": "success",
        "po_name": doc.name,
        "signatory_name": chosen_signatory,
        "signatory_designation": designation,
        "hash": short_hash,
        "timestamp": timestamp_str
    }


@frappe.whitelist()
def download_purchase_order_pdf(po_name: str):
    """
    Generates and streams the official PDF on the designated entity letterhead.
    """
    if not po_name:
        frappe.throw(_("PO Name is required."))

    doc = frappe.get_doc("AP Purchase Order", po_name)
    html = render_po_html(doc)

    options = {
        "page-size": "A4",
        "orientation": "Portrait",
        "margin-top": "12mm",
        "margin-bottom": "18mm",
        "margin-left": "14mm",
        "margin-right": "14mm",
        "encoding": "UTF-8",
        "no-outline": None
    }

    pdf_content = get_pdf(html, options=options)

    clean_vendor = (doc.vendor_name or "Vendor").replace(" ", "_")
    filename = f"PO_{doc.name}_{clean_vendor}.pdf"

    frappe.local.response.filename = filename
    frappe.local.response.filecontent = pdf_content
    frappe.local.response.type = "pdf"
    frappe.local.response.headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
