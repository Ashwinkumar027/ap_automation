# Copyright (c) 2026, Quanti and contributors
# Production-grade Vendor Payment and P2P 360 Financial & Audit Report Engine

import frappe
from frappe import _
from frappe.utils import flt, getdate, formatdate, get_url


def execute(filters=None):
    filters = filters or {}
    columns = get_columns(filters)
    data, chart, report_summary = get_data_and_summary(filters)
    return columns, data, None, chart, report_summary


def get_columns(filters):
    group_by = filters.get("group_by") or "None (Detailed Invoices)"

    if group_by == "Month Wise":
        return [
            {"fieldname": "period", "label": _("Billing Month"), "fieldtype": "Data", "width": 140},
            {"fieldname": "company", "label": _("Company Entity"), "fieldtype": "Link", "options": "Company", "width": 180},
            {"fieldname": "invoice_count", "label": _("Invoice Count"), "fieldtype": "Int", "width": 110},
            {"fieldname": "total_base", "label": _("Base Taxable (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "total_gst", "label": _("Total GST (₹)"), "fieldtype": "Currency", "width": 130},
            {"fieldname": "total_gross", "label": _("Gross Invoiced (₹)"), "fieldtype": "Currency", "width": 150},
            {"fieldname": "total_advance", "label": _("Advance Offset (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "total_tds", "label": _("TDS Withheld (₹)"), "fieldtype": "Currency", "width": 130},
            {"fieldname": "total_net", "label": _("Net Disbursal (₹)"), "fieldtype": "Currency", "width": 160},
            {"fieldname": "paid_amount", "label": _("Settled / Paid (₹)"), "fieldtype": "Currency", "width": 150},
            {"fieldname": "pending_amount", "label": _("In Review (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "disputed_amount", "label": _("Disputed (₹)"), "fieldtype": "Currency", "width": 140},
        ]

    elif group_by == "Supplier Wise":
        return [
            {"fieldname": "vendor", "label": _("Supplier ID"), "fieldtype": "Link", "options": "Supplier", "width": 160},
            {"fieldname": "vendor_name", "label": _("Supplier Name"), "fieldtype": "Data", "width": 220},
            {"fieldname": "vendor_gstin", "label": _("GSTIN"), "fieldtype": "Data", "width": 150},
            {"fieldname": "invoice_count", "label": _("Invoices Filed"), "fieldtype": "Int", "width": 120},
            {"fieldname": "total_gross", "label": _("Gross Spend (₹)"), "fieldtype": "Currency", "width": 160},
            {"fieldname": "total_advance", "label": _("Advance Offset (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "total_tds", "label": _("TDS Deducted (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "total_net", "label": _("Net Payable (₹)"), "fieldtype": "Currency", "width": 160},
            {"fieldname": "paid_amount", "label": _("Disbursed / Paid (₹)"), "fieldtype": "Currency", "width": 150},
            {"fieldname": "disputed_count", "label": _("Disputed Claims"), "fieldtype": "Int", "width": 120},
        ]

    elif group_by == "Company Wise":
        return [
            {"fieldname": "company", "label": _("Company Entity"), "fieldtype": "Link", "options": "Company", "width": 240},
            {"fieldname": "invoice_count", "label": _("Total Invoices"), "fieldtype": "Int", "width": 120},
            {"fieldname": "total_base", "label": _("Base Taxable (₹)"), "fieldtype": "Currency", "width": 150},
            {"fieldname": "total_gst", "label": _("GST Input (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "total_gross", "label": _("Gross Spend (₹)"), "fieldtype": "Currency", "width": 160},
            {"fieldname": "total_advance", "label": _("Advance Offset (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "total_tds", "label": _("TDS Deposited (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "total_net", "label": _("Net Liability (₹)"), "fieldtype": "Currency", "width": 160},
            {"fieldname": "paid_amount", "label": _("Settled (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "pending_amount", "label": _("Pending (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "disputed_amount", "label": _("Disputed (₹)"), "fieldtype": "Currency", "width": 140},
        ]

    elif group_by == "Status Wise":
        return [
            {"fieldname": "status", "label": _("Claim Lifecycle Status"), "fieldtype": "Data", "width": 200},
            {"fieldname": "invoice_count", "label": _("Invoice Count"), "fieldtype": "Int", "width": 120},
            {"fieldname": "total_gross", "label": _("Gross Amount (₹)"), "fieldtype": "Currency", "width": 160},
            {"fieldname": "total_tds", "label": _("TDS Withheld (₹)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "total_net", "label": _("Net Disbursal (₹)"), "fieldtype": "Currency", "width": 170},
            {"fieldname": "avg_ticket", "label": _("Average Invoice (₹)"), "fieldtype": "Currency", "width": 150},
        ]

    elif group_by == "TDS Section Wise":
        return [
            {"fieldname": "tds_section", "label": _("Statutory TDS Section"), "fieldtype": "Data", "width": 200},
            {"fieldname": "invoice_count", "label": _("Vouchers"), "fieldtype": "Int", "width": 100},
            {"fieldname": "taxable_base", "label": _("Taxable Base (₹)"), "fieldtype": "Currency", "width": 160},
            {"fieldname": "tds_rate", "label": _("Effective Rate (%)"), "fieldtype": "Percent", "width": 130},
            {"fieldname": "total_tds", "label": _("Total TDS Withheld (₹)"), "fieldtype": "Currency", "width": 160},
            {"fieldname": "total_net", "label": _("Net Settlement (₹)"), "fieldtype": "Currency", "width": 170},
        ]

    elif group_by == "3-Way Match Audit Wise":
        return [
            {"fieldname": "match_status", "label": _("3-Way Match Audit Outcome"), "fieldtype": "Data", "width": 220},
            {"fieldname": "invoice_count", "label": _("Invoices Evaluated"), "fieldtype": "Int", "width": 140},
            {"fieldname": "total_gross", "label": _("Gross Value (₹)"), "fieldtype": "Currency", "width": 160},
            {"fieldname": "total_net", "label": _("Net Disbursal (₹)"), "fieldtype": "Currency", "width": 160},
            {"fieldname": "action_required", "label": _("Auditor Action Needed"), "fieldtype": "Data", "width": 220},
        ]

    # Default: None (Detailed Invoices)
    return [
        {"fieldname": "name", "label": _("Claim ID"), "fieldtype": "Link", "options": "Vendor Invoice Claim", "width": 160},
        {"fieldname": "tax_invoice_date", "label": _("Invoice Date"), "fieldtype": "Date", "width": 110},
        {"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 160},
        {"fieldname": "vendor", "label": _("Supplier"), "fieldtype": "Link", "options": "Supplier", "width": 140},
        {"fieldname": "vendor_name", "label": _("Supplier Name"), "fieldtype": "Data", "width": 180},
        {"fieldname": "vendor_gstin", "label": _("Vendor GSTIN"), "fieldtype": "Data", "width": 140},
        {"fieldname": "invoice_type", "label": _("Intake Route"), "fieldtype": "Data", "width": 150},
        {"fieldname": "purchase_order", "label": _("Linked AP PO"), "fieldtype": "Link", "options": "AP Purchase Order", "width": 150},
        {"fieldname": "tax_invoice_number", "label": _("Invoice #"), "fieldtype": "Data", "width": 130},
        {"fieldname": "tax_invoice_attachment", "label": _("Proof PDF"), "fieldtype": "Data", "width": 100},
        {"fieldname": "base_amount", "label": _("Base Taxable (₹)"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "gst_rate", "label": _("GST Rate"), "fieldtype": "Data", "width": 90},
        {"fieldname": "gst_amount", "label": _("GST (₹)"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "total_invoice_amount", "label": _("Gross Total (₹)"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "advance_deducted", "label": _("(-) Advance (₹)"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "tds_section", "label": _("TDS Section"), "fieldtype": "Data", "width": 130},
        {"fieldname": "tds_amount", "label": _("(-) TDS (₹)"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "net_payable_amount", "label": _("Net Disbursal (₹)"), "fieldtype": "Currency", "width": 150},
        {"fieldname": "match_status", "label": _("3-Way Match"), "fieldtype": "Data", "width": 160},
        {"fieldname": "status", "label": _("Claim Status"), "fieldtype": "Data", "width": 140},
        {"fieldname": "bank_account_number", "label": _("Bank A/C #"), "fieldtype": "Data", "width": 130},
        {"fieldname": "bank_ifsc_code", "label": _("IFSC Code"), "fieldtype": "Data", "width": 110},
        {"fieldname": "batch_id", "label": _("Payment Batch"), "fieldtype": "Data", "width": 130},
        {"fieldname": "creation", "label": _("Filing Timestamp"), "fieldtype": "Datetime", "width": 150},
    ]


def get_data_and_summary(filters):
    conditions, values = build_filter_conditions(filters)
    group_by = filters.get("group_by") or "None (Detailed Invoices)"

    # Base Query
    base_sql = f"""
        SELECT 
            vic.name,
            vic.tax_invoice_date,
            vic.company,
            vic.vendor,
            vic.vendor_name,
            vic.vendor_gstin,
            vic.invoice_type,
            vic.purchase_order,
            vic.tax_invoice_number,
            vic.tax_invoice_attachment,
            vic.base_amount,
            vic.gst_rate,
            vic.gst_amount,
            vic.total_invoice_amount,
            vic.advance_deducted,
            vic.tds_section,
            vic.tds_rate,
            vic.tds_amount,
            vic.net_payable_amount,
            vic.match_status,
            vic.match_variance_details,
            vic.status,
            vic.bank_account_number,
            vic.bank_ifsc_code,
            vic.batch_id,
            vic.creation,
            vic.docstatus
        FROM `tabVendor Invoice Claim` vic
        WHERE {conditions}
        ORDER BY vic.creation DESC
    """

    raw_data = frappe.db.sql(base_sql, values, as_dict=True)

    # Format attachment as clickable Excel HYPERLINK with clean 'View Proof' display text
    for r in raw_data:
        att = r.get("tax_invoice_attachment")
        if att:
            full_url = get_url(att)
            r["tax_invoice_attachment"] = f'=HYPERLINK("{full_url}", "View Proof")'
        else:
            r["tax_invoice_attachment"] = ""

    # Calculate Top KPI Summary Cards
    report_summary = calculate_kpi_summary(raw_data)

    # Process Data & Chart according to group_by
    if group_by == "Month Wise":
        data, chart = aggregate_month_wise(raw_data)
    elif group_by == "Supplier Wise":
        data, chart = aggregate_supplier_wise(raw_data)
    elif group_by == "Company Wise":
        data, chart = aggregate_company_wise(raw_data)
    elif group_by == "Status Wise":
        data, chart = aggregate_status_wise(raw_data)
    elif group_by == "TDS Section Wise":
        data, chart = aggregate_tds_section_wise(raw_data)
    elif group_by == "3-Way Match Audit Wise":
        data, chart = aggregate_match_audit_wise(raw_data)
    else:
        data = raw_data
        chart = build_supplier_spend_chart(raw_data)

    return data, chart, report_summary


def build_filter_conditions(filters):
    conditions = ["1 = 1"]
    values = {}

    if filters.get("company"):
        conditions.append("vic.company = %(company)s")
        values["company"] = filters["company"]

    if filters.get("from_date"):
        conditions.append("(vic.tax_invoice_date >= %(from_date)s OR (vic.tax_invoice_date IS NULL AND vic.creation >= %(from_date)s))")
        values["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions.append("(vic.tax_invoice_date <= %(to_date)s OR (vic.tax_invoice_date IS NULL AND vic.creation <= %(to_date_end)s))")
        values["to_date"] = filters["to_date"]
        values["to_date_end"] = f"{filters['to_date']} 23:59:59"

    if filters.get("supplier"):
        conditions.append("vic.vendor = %(supplier)s")
        values["supplier"] = filters["supplier"]

    if filters.get("purchase_order"):
        conditions.append("vic.purchase_order = %(purchase_order)s")
        values["purchase_order"] = filters["purchase_order"]

    if filters.get("invoice_type") and filters["invoice_type"] != "All":
        conditions.append("vic.invoice_type = %(invoice_type)s")
        values["invoice_type"] = filters["invoice_type"]

    if filters.get("status") and filters["status"] != "All":
        conditions.append("vic.status = %(status)s")
        values["status"] = filters["status"]

    if filters.get("match_status") and filters["match_status"] != "All":
        conditions.append("vic.match_status = %(match_status)s")
        values["match_status"] = filters["match_status"]

    if filters.get("tds_section") and filters["tds_section"] != "All":
        if filters["tds_section"] == "None":
            conditions.append("(vic.tds_section IS NULL OR vic.tds_section = '')")
        else:
            conditions.append("vic.tds_section = %(tds_section)s")
            values["tds_section"] = filters["tds_section"]

    return " AND ".join(conditions), values


def calculate_kpi_summary(rows):
    total_gross = sum(flt(r.total_invoice_amount) for r in rows)
    total_gst = sum(flt(r.gst_amount) for r in rows)
    total_advance = sum(flt(r.advance_deducted) for r in rows)
    total_tds = sum(flt(r.tds_amount) for r in rows)
    total_net = sum(flt(r.net_payable_amount) for r in rows)

    settled_net = sum(flt(r.net_payable_amount) for r in rows if r.status == "Paid")
    pending_net = sum(flt(r.net_payable_amount) for r in rows if r.status in ("Pending Accounts Review", "Approved for Payment", "Queued in Batch"))
    disputed_net = sum(flt(r.net_payable_amount) for r in rows if r.status == "Disputed" or (r.match_status and "Mismatch Flagged" in r.match_status))

    return [
        {
            "value": total_gross,
            "label": _("Gross Spend Invoiced"),
            "datatype": "Currency",
            "currency": "INR"
        },
        {
            "value": total_gst,
            "label": _("Input Tax Credit (GST)"),
            "datatype": "Currency",
            "currency": "INR"
        },
        {
            "value": total_advance,
            "label": _("Prior Advance Recovered"),
            "datatype": "Currency",
            "currency": "INR"
        },
        {
            "value": total_tds,
            "label": _("Statutory TDS Withheld"),
            "datatype": "Currency",
            "currency": "INR"
        },
        {
            "value": settled_net,
            "label": _("Net Settled (Paid UTR)"),
            "datatype": "Currency",
            "currency": "INR",
            "indicator": "Green"
        },
        {
            "value": pending_net,
            "label": _("Pending Review Pipeline"),
            "datatype": "Currency",
            "currency": "INR",
            "indicator": "Blue"
        },
        {
            "value": disputed_net,
            "label": _("Disputed / Flagged Risk"),
            "datatype": "Currency",
            "currency": "INR",
            "indicator": "Red"
        }
    ]


def aggregate_month_wise(rows):
    months = {}
    for r in rows:
        date_val = r.tax_invoice_date or (getdate(r.creation) if r.creation else None)
        period = formatdate(date_val, "YYYY-MM") if date_val else "Unassigned"
        key = (period, r.company)

        if key not in months:
            months[key] = {
                "period": period,
                "company": r.company,
                "invoice_count": 0,
                "total_base": 0.0,
                "total_gst": 0.0,
                "total_gross": 0.0,
                "total_advance": 0.0,
                "total_tds": 0.0,
                "total_net": 0.0,
                "paid_amount": 0.0,
                "pending_amount": 0.0,
                "disputed_amount": 0.0,
            }

        m = months[key]
        m["invoice_count"] += 1
        m["total_base"] += flt(r.base_amount)
        m["total_gst"] += flt(r.gst_amount)
        m["total_gross"] += flt(r.total_invoice_amount)
        m["total_advance"] += flt(r.advance_deducted)
        m["total_tds"] += flt(r.tds_amount)
        m["total_net"] += flt(r.net_payable_amount)

        if r.status == "Paid":
            m["paid_amount"] += flt(r.net_payable_amount)
        elif r.status in ("Pending Accounts Review", "Approved for Payment", "Queued in Batch"):
            m["pending_amount"] += flt(r.net_payable_amount)
        elif r.status == "Disputed":
            m["disputed_amount"] += flt(r.net_payable_amount)

    sorted_data = sorted(list(months.values()), key=lambda x: x["period"], reverse=True)

    # Monthly Trend Chart
    chart_labels = [d["period"] for d in reversed(sorted_data[:6])]
    chart_gross = [d["total_gross"] for d in reversed(sorted_data[:6])]
    chart_net = [d["total_net"] for d in reversed(sorted_data[:6])]

    chart = {
        "data": {
            "labels": chart_labels,
            "datasets": [
                {"name": _("Gross Invoiced (₹)"), "values": chart_gross},
                {"name": _("Net Disbursal (₹)"), "values": chart_net}
            ]
        },
        "type": "bar",
        "colors": ["#3b82f6", "#10b981"]
    }

    return sorted_data, chart


def aggregate_supplier_wise(rows):
    suppliers = {}
    for r in rows:
        key = r.vendor or "Unassigned"
        if key not in suppliers:
            suppliers[key] = {
                "vendor": key,
                "vendor_name": r.vendor_name or key,
                "vendor_gstin": r.vendor_gstin or "Unregistered",
                "invoice_count": 0,
                "total_gross": 0.0,
                "total_advance": 0.0,
                "total_tds": 0.0,
                "total_net": 0.0,
                "paid_amount": 0.0,
                "disputed_count": 0,
            }

        s = suppliers[key]
        s["invoice_count"] += 1
        s["total_gross"] += flt(r.total_invoice_amount)
        s["total_advance"] += flt(r.advance_deducted)
        s["total_tds"] += flt(r.tds_amount)
        s["total_net"] += flt(r.net_payable_amount)

        if r.status == "Paid":
            s["paid_amount"] += flt(r.net_payable_amount)
        if r.status == "Disputed":
            s["disputed_count"] += 1

    sorted_data = sorted(list(suppliers.values()), key=lambda x: x["total_gross"], reverse=True)

    # Top 10 Suppliers Spend Chart
    top10 = sorted_data[:10]
    chart = {
        "data": {
            "labels": [d["vendor_name"][:18] for d in top10],
            "datasets": [
                {"name": _("Gross Spend (₹)"), "values": [d["total_gross"] for d in top10]}
            ]
        },
        "type": "bar",
        "colors": ["#6366f1"]
    }

    return sorted_data, chart


def aggregate_company_wise(rows):
    companies = {}
    for r in rows:
        key = r.company or "Unassigned"
        if key not in companies:
            companies[key] = {
                "company": key,
                "invoice_count": 0,
                "total_base": 0.0,
                "total_gst": 0.0,
                "total_gross": 0.0,
                "total_advance": 0.0,
                "total_tds": 0.0,
                "total_net": 0.0,
                "paid_amount": 0.0,
                "pending_amount": 0.0,
                "disputed_amount": 0.0,
            }

        c = companies[key]
        c["invoice_count"] += 1
        c["total_base"] += flt(r.base_amount)
        c["total_gst"] += flt(r.gst_amount)
        c["total_gross"] += flt(r.total_invoice_amount)
        c["total_advance"] += flt(r.advance_deducted)
        c["total_tds"] += flt(r.tds_amount)
        c["total_net"] += flt(r.net_payable_amount)

        if r.status == "Paid":
            c["paid_amount"] += flt(r.net_payable_amount)
        elif r.status in ("Pending Accounts Review", "Approved for Payment", "Queued in Batch"):
            c["pending_amount"] += flt(r.net_payable_amount)
        elif r.status == "Disputed":
            c["disputed_amount"] += flt(r.net_payable_amount)

    sorted_data = sorted(list(companies.values()), key=lambda x: x["total_gross"], reverse=True)

    chart = {
        "data": {
            "labels": [d["company"] for d in sorted_data],
            "datasets": [
                {"name": _("Net Liability (₹)"), "values": [d["total_net"] for d in sorted_data]}
            ]
        },
        "type": "donut",
        "colors": ["#0284c7", "#059669", "#d97706", "#dc2626"]
    }

    return sorted_data, chart


def aggregate_status_wise(rows):
    statuses = {}
    for r in rows:
        key = r.status or "Draft"
        if key not in statuses:
            statuses[key] = {
                "status": key,
                "invoice_count": 0,
                "total_gross": 0.0,
                "total_tds": 0.0,
                "total_net": 0.0,
                "avg_ticket": 0.0,
            }

        st = statuses[key]
        st["invoice_count"] += 1
        st["total_gross"] += flt(r.total_invoice_amount)
        st["total_tds"] += flt(r.tds_amount)
        st["total_net"] += flt(r.net_payable_amount)

    for st in statuses.values():
        if st["invoice_count"] > 0:
            st["avg_ticket"] = round(st["total_gross"] / st["invoice_count"], 2)

    sorted_data = sorted(list(statuses.values()), key=lambda x: x["total_net"], reverse=True)

    chart = {
        "data": {
            "labels": [d["status"] for d in sorted_data],
            "datasets": [
                {"name": _("Net Value (₹)"), "values": [d["total_net"] for d in sorted_data]}
            ]
        },
        "type": "donut",
        "colors": ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#9ca3af"]
    }

    return sorted_data, chart


def aggregate_tds_section_wise(rows):
    sections = {}
    desc_map = {
        "194C (Contractor)": "Contractor Payments (Sub-contractors / Works)",
        "194J (Professional)": "Fees for Professional / Technical Services",
        "194Q (Goods Purchase)": "TDS on Purchase of Goods over INR 50 Lakhs",
        "None": "Exempt / Non-Deductible Spend"
    }

    for r in rows:
        sec = r.tds_section or "None"
        if sec not in sections:
            sections[sec] = {
                "tds_section": sec,
                "description": desc_map.get(sec, "Indian Statutory Withholding"),
                "tds_rate": flt(r.tds_rate) if r.tds_rate else 0.0,
                "invoice_count": 0,
                "taxable_base": 0.0,
                "total_tds": 0.0,
                "total_net": 0.0,
            }

        s = sections[sec]
        s["invoice_count"] += 1
        s["taxable_base"] += flt(r.base_amount)
        s["total_tds"] += flt(r.tds_amount)
        s["total_net"] += flt(r.net_payable_amount)
        if not s["tds_rate"] and r.tds_rate:
            s["tds_rate"] = flt(r.tds_rate)

    sorted_data = sorted(list(sections.values()), key=lambda x: x["total_tds"], reverse=True)

    chart = {
        "data": {
            "labels": [d["tds_section"] for d in sorted_data],
            "datasets": [
                {"name": _("TDS Deposited (₹)"), "values": [d["total_tds"] for d in sorted_data]}
            ]
        },
        "type": "bar",
        "colors": ["#ea580c"]
    }

    return sorted_data, chart


def aggregate_match_audit_wise(rows):
    outcomes = {}
    action_map = {
        "3-Way Match Passed": "Clean — Ready for Payout",
        "Price Mismatch Flagged": "Price Overrun — Reconcile PO & Invoice",
        "Quantity Mismatch Flagged": "Qty Discrepancy — Physical GRN Check Required",
        "Missing GRN Flagged": "GRN Missing — Warehouse Intake Pending",
        "Pending Match Execution": "Draft — Attach PO / Proofs to Trigger Matching"
    }

    for r in rows:
        st = r.match_status or "Pending Match Execution"
        if st not in outcomes:
            outcomes[st] = {
                "match_status": st,
                "invoice_count": 0,
                "total_gross": 0.0,
                "total_net": 0.0,
                "action_required": action_map.get(st, "Review Audit Diagnostics")
            }

        o = outcomes[st]
        o["invoice_count"] += 1
        o["total_gross"] += flt(r.total_invoice_amount)
        o["total_net"] += flt(r.net_payable_amount)

    sorted_data = sorted(list(outcomes.values()), key=lambda x: x["invoice_count"], reverse=True)

    chart = {
        "data": {
            "labels": [d["match_status"] for d in sorted_data],
            "datasets": [
                {"name": _("Invoices Count"), "values": [d["invoice_count"] for d in sorted_data]}
            ]
        },
        "type": "donut",
        "colors": ["#059669", "#dc2626", "#ea580c", "#d97706", "#64748b"]
    }

    return sorted_data, chart


def build_supplier_spend_chart(rows):
    supplier_totals = {}
    for r in rows:
        v = r.vendor_name or r.vendor or "Unassigned"
        supplier_totals[v] = supplier_totals.get(v, 0.0) + flt(r.net_payable_amount)

    top_sorted = sorted(supplier_totals.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "data": {
            "labels": [x[0][:18] for x in top_sorted],
            "datasets": [
                {"name": _("Net Disbursal (₹)"), "values": [x[1] for x in top_sorted]}
            ]
        },
        "type": "bar",
        "colors": ["#2563eb"]
    }
