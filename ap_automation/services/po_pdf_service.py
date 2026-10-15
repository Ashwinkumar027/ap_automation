import os
import base64
import json
import frappe
from frappe import _
from frappe.utils.pdf import get_pdf
from frappe.utils import format_date, fmt_money, flt

def get_logo_base64():
    logo_path = "/home/ashwinkumark_quanti/frappe/my-bench/apps/ap_automation/ap_automation/public/images/aionion_letterhead_logo.png"
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode("utf-8")
    return ""

def format_inr(val):
    return fmt_money(flt(val), currency="INR").replace("₹ ", "₹").replace("₹", "")

def render_po_html(doc):
    logo_b64 = get_logo_base64()
    vendor_name = doc.vendor_name or doc.vendor or "Vendor"
    vendor_addr = (doc.vendor_registered_address or "").replace("\n", "<br>")
    po_date = format_date(doc.date_of_issue or doc.creation, "dd MMMM, yyyy")
    scope = doc.service_type or "Cloud Telephony IVR / Procurement Services"

    # Items rows HTML
    items_rows = ""
    for idx, item in enumerate(doc.items or [], 1):
        item_title = item.item_name or "Service Item"
        desc = (item.description or item.hsn_sac_code or "Smartflo - ITS").replace("\n", "<br>")
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

    # HTML template matching Image 1 & Image 2
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
                top: 38%;
                left: 15%;
                width: 70%;
                opacity: 0.045;
                z-index: -100;
                text-align: center;
                pointer-events: none;
            }}
            .watermark img {{
                width: 100%;
                max-width: 500px;
            }}
            .header-container {{
                text-align: center;
                padding-bottom: 5px;
            }}
            .header-logo {{
                width: 260px;
                margin: 0 auto;
                display: block;
            }}
            .company-title {{
                font-size: 15px;
                font-weight: 900;
                color: #000000;
                letter-spacing: 0.5px;
                margin-top: 6px;
                margin-bottom: 10px;
                text-transform: uppercase;
            }}
            .header-divider {{
                height: 3px;
                background: #1e60ff;
                margin: 0 0 14px 0;
                border: none;
            }}
            .doc-title {{
                font-size: 14px;
                font-weight: 900;
                text-align: center;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin: 8px 0 14px 0;
            }}
            .meta-table {{
                width: 100%;
                margin-bottom: 12px;
            }}
            .meta-table td {{
                vertical-align: top;
                font-size: 11.5px;
            }}
            .salutation {{
                margin-bottom: 12px;
                font-size: 11px;
                line-height: 1.4;
            }}
            .items-table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 14px;
            }}
            .items-table th {{
                background-color: #0099cc;
                color: #ffffff;
                font-size: 11px;
                font-weight: 700;
                border: 1px solid #000;
                padding: 8px 6px;
                text-align: center;
            }}
            .terms-heading {{
                font-weight: 700;
                font-size: 10.5px;
                margin-top: 10px;
                margin-bottom: 4px;
            }}
            .terms-list {{
                margin: 0 0 14px 0;
                padding-left: 18px;
                font-size: 8.5px;
                line-height: 1.25;
                color: #222222;
            }}
            .terms-list li {{
                margin-bottom: 3px;
            }}
            .terms-list ul {{
                margin: 2px 0 2px 0;
                padding-left: 14px;
                list-style-type: circle;
            }}
            .sign-section {{
                margin-top: 10px;
                font-size: 10.5px;
                line-height: 1.4;
            }}
            .dsc-empty-box {{
                height: 52px;
                width: 220px;
                margin: 4px 0 6px 0;
                /* Left clean and empty for Adobe Acrobat / Hardware USB DSC Token Signing */
            }}
            .footer-container {{
                position: fixed;
                bottom: -8mm;
                left: 0;
                right: 0;
                width: 100%;
                font-size: 8px;
                font-weight: 700;
                line-height: 1.35;
                color: #000000;
                border-top: 1px solid #1e60ff;
                padding-top: 4px;
            }}
            .footer-table {{
                width: 100%;
                border-collapse: collapse;
            }}
            .footer-table td {{
                vertical-align: top;
            }}
            .color-bar {{
                margin-top: 4px;
                height: 6px;
                width: 100%;
                display: flex;
            }}
            .color-bar-pink {{
                width: 50%;
                height: 6px;
                background-color: #ff6b8b;
                display: inline-block;
            }}
            .color-bar-blue {{
                width: 50%;
                height: 6px;
                background-color: #1e60ff;
                display: inline-block;
            }}
        </style>
    </head>
    <body>
        <!-- Faint Center Watermark -->
        <div class="watermark">
            <img src="{logo_b64}" alt="Watermark" />
        </div>

        <!-- Header -->
        <div class="header-container">
            <img class="header-logo" src="{logo_b64}" alt="Aionion Capital" />
            <div class="company-title">AIONION CAPITAL MARKET SERVICES PRIVATE LIMITED</div>
            <div class="header-divider"></div>
        </div>

        <!-- Document Title -->
        <div class="doc-title">PURCHASE ORDER</div>

        <!-- Meta Section (To & Date) -->
        <table class="meta-table">
            <tr>
                <td style="width: 60%;">
                    <b>To,</b><br>
                    <span style="font-size: 12.5px; font-weight: 700;">{vendor_name}</span>
                    {f'<br>{vendor_addr}' if vendor_addr else ''}
                </td>
                <td style="width: 40%; text-align: right;">
                    <b>Date:</b> {po_date}<br>
                    <b>PO No:</b> {doc.name}
                </td>
            </tr>
        </table>

        <!-- Salutation -->
        <div class="salutation">
            Dear Team,<br>
            We are pleased to release the purchase order for <b>{scope}</b> with the Details mentioned below.
        </div>

        <!-- Commercial Table -->
        <table class="items-table">
            <thead>
                <tr>
                    <th style="width: 22%;">Item</th>
                    <th style="width: 38%;">Description</th>
                    <th style="width: 14%;">Per User<br>Cost</th>
                    <th style="width: 12%;">No of<br>calls/channels</th>
                    <th style="width: 14%;">Monthly<br>Charges (₹)</th>
                </tr>
            </thead>
            <tbody>
                {items_rows}
                <tr>
                    <td colspan="4" style="border: 1px solid #000; padding: 6px 10px; font-weight: 700; text-align: center;">GST</td>
                    <td style="border: 1px solid #000; padding: 6px 10px; text-align: right; font-weight: 700;">{gst_amt}</td>
                </tr>
                <tr>
                    <td colspan="4" style="border: 1px solid #000; padding: 6px 10px; font-weight: 900; text-align: center; text-transform: uppercase;">Grand Total</td>
                    <td style="border: 1px solid #000; padding: 6px 10px; text-align: right; font-weight: 900; font-size: 12px;">{grand_total}</td>
                </tr>
            </tbody>
        </table>

        <!-- Tax Compliance & GST Requirements (10 Statutory Clauses) -->
        <div class="terms-heading">Tax Compliance &amp; GST Requirements</div>
        <ol class="terms-list">
            <li><b>Inclusive Pricing:</b> Unless specified otherwise, all prices in this Purchase Order include all applicable taxes and duties.</li>
            <li><b>Separate Tax Line Items:</b> Any applicable sales and use taxes shall be separately itemized in the Vendor's invoice.</li>
            <li><b>Company's Right to Withhold Taxes:</b> Company ("Aionion Group Name") reserves the right to withhold any applicable taxes from payments due to the Vendor, as required by applicable laws or government authorities.</li>
            <li><b>No Liability for Vendor's Tax Submissions:</b> The Company shall not be held liable for any acts, omissions, delays, or submission failures by the Vendor to tax authorities.</li>
            <li><b>Vendor's Responsibility for Tax Notices:</b> The Vendor shall promptly notify the Company of any notices, actions, or compliance requirements received from the tax authorities.</li>
            <li><b>GST Return Filing Obligations:</b>
                <ul>
                    <li>The Vendor must upload invoice-wise details on the GSTN portal as part of GSTR-1 filings on a timely basis.</li>
                    <li>This enables the Company to avail input GST credit via auto-populated GSTR-2B.</li>
                </ul>
            </li>
            <li><b>Precondition for Payment:</b> Notwithstanding any other clause, the Company shall process payments to the Vendor only upon satisfaction of the following conditions:
                <ul>
                    <li>Vendor has filed GSTR-3B and paid the applicable taxes.</li>
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

        <!-- Sign-off Section (Empty for DSC USB Signing) -->
        <div class="sign-section">
            Thanking you,<br>
            <b>For,</b><br>
            <b>AIONION CAPITAL MARKET SERVICES PVT LTD</b><br>
            <!-- Blank space preserved for Adobe Acrobat / USB DSC Token Signature -->
            <div class="dsc-empty-box"></div>
            <b>Anish Gupta</b><br>
            Director.
        </div>

        <!-- Footer -->
        <div class="footer-container">
            <table class="footer-table">
                <tr>
                    <td style="width: 52%;">
                        REG OFFICE: 3RD FLOOR, MEERLAN TOWERS,<br>
                        NO 33, HANUMANTHA ROAD, ROYAPETTAH, CHENNAI - 600014.<br>
                        SEBI REGISTRATION NO : INZ000318532
                    </td>
                    <td style="width: 48%; text-align: right;">
                        COMPLIANCE@AIONIONCAPITAL.COM<br>
                        CIN: U66120TN2024PTC167864<br>
                        AMFI REG. NO. : ARN-296313
                    </td>
                </tr>
            </table>
            <!-- Dual Color Bottom Bar -->
            <table style="width: 100%; border-collapse: collapse; margin-top: 3px;">
                <tr>
                    <td style="width: 50%; height: 5px; background-color: #ff6b8b; padding: 0;"></td>
                    <td style="width: 50%; height: 5px; background-color: #1e60ff; padding: 0;"></td>
                </tr>
            </table>
        </div>
    </body>
    </html>
    """
    return html

@frappe.whitelist()
def download_purchase_order_pdf(po_name: str):
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
