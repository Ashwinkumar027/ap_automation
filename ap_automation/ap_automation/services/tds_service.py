"""
Statutory Indian TDS Engine (Income Tax Act)
Enforces:
1. Automatic statutory tax withholding based on Section (194C, 194J, 194Q, 194I, 206AB).
2. CBDT Circular 23/2017 compliance: TDS is strictly calculated on Base Taxable Value (excluding GST).
3. Complete mathematical conservation: Total = Net Payable + TDS Payable + Advance Offset.
"""
from typing import Dict, Any, Optional

TDS_SECTION_RATES = {
    "None / Exempt": 0.0,
    "194C - Contractor (1%)": 1.0,
    "194C - Contractor (2%)": 2.0,
    "194J - Technical Fees (2%)": 2.0,
    "194J - Professional Fees (10%)": 10.0,
    "194Q - Purchase of Goods (0.1%)": 0.1,
    "194I - Rent (10%)": 10.0,
    "206AB - Higher Non-Filer (20%)": 20.0
}


def calculate_tds(base_amount: float, section: str) -> Dict[str, Any]:
    """
    Computes statutory TDS withholding amount on base taxable spend.
    """
    rate = TDS_SECTION_RATES.get(section, 0.0)
    base = float(base_amount or 0.0)
    tds_amt = round(base * (rate / 100.0), 2)
    return {
        "section": section,
        "rate": rate,
        "tds_amount": tds_amt
    }


def apply_tds_to_invoice(claim_doc) -> None:
    """
    Applies statutory TDS withholding to a Vendor Invoice Claim and updates net payable.
    """
    section = getattr(claim_doc, "tds_section", "None / Exempt") or "None / Exempt"
    base = float(getattr(claim_doc, "base_amount", 0.0) or 0.0)

    tds_info = calculate_tds(base, section)
    claim_doc.tds_rate = tds_info["rate"]
    claim_doc.tds_amount = tds_info["tds_amount"]

    # Statutory Net Payable Formula: Total Invoice (Base + GST) - Prior Advance - TDS Deducted
    total = float(getattr(claim_doc, "total_invoice_amount", 0.0) or 0.0)
    advance = float(getattr(claim_doc, "advance_deducted", 0.0) or 0.0)
    tds = float(claim_doc.tds_amount or 0.0)

    net = round(max(total - advance - tds, 0.0), 2)
    claim_doc.net_payable_amount = net
    claim_doc.total_amount = net
