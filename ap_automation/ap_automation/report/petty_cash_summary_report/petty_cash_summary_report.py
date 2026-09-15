import frappe
from frappe.utils import flt, getdate, formatdate


def execute(filters=None):
    filters = filters or {}
    columns = get_columns(filters)
    data, chart, report_summary = get_data_and_summary(filters)
    return columns, data, None, chart, report_summary


def get_columns(filters):
    group_by = filters.get("group_by") or "None (Detailed Lines)"

    if group_by == "Month Wise":
        return [
            {"fieldname": "period", "label": "Month", "fieldtype": "Data", "width": 140},
            {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "width": 200},
            {"fieldname": "voucher_count", "label": "Voucher Count", "fieldtype": "Int", "width": 120},
            {"fieldname": "line_count", "label": "Total Lines", "fieldtype": "Int", "width": 110},
            {"fieldname": "total_amount", "label": "Claimed Amount (₹)", "fieldtype": "Currency", "width": 160},
            {"fieldname": "paid_amount", "label": "Paid Amount (₹)", "fieldtype": "Currency", "width": 150},
            {"fieldname": "pending_amount", "label": "Pending Amount (₹)", "fieldtype": "Currency", "width": 150},
            {"fieldname": "disputed_amount", "label": "Disputed Amount (₹)", "fieldtype": "Currency", "width": 150},
        ]
    elif group_by == "Week Wise":
        return [
            {"fieldname": "period", "label": "Week (Year-Week)", "fieldtype": "Data", "width": 140},
            {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "width": 200},
            {"fieldname": "voucher_count", "label": "Vouchers", "fieldtype": "Int", "width": 110},
            {"fieldname": "total_amount", "label": "Claimed Amount (₹)", "fieldtype": "Currency", "width": 160},
            {"fieldname": "paid_amount", "label": "Paid (₹)", "fieldtype": "Currency", "width": 140},
            {"fieldname": "pending_amount", "label": "Pending (₹)", "fieldtype": "Currency", "width": 140},
            {"fieldname": "disputed_amount", "label": "Disputed (₹)", "fieldtype": "Currency", "width": 140},
        ]
    elif group_by == "Company Wise":
        return [
            {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "width": 240},
            {"fieldname": "voucher_count", "label": "Total Vouchers", "fieldtype": "Int", "width": 130},
            {"fieldname": "total_amount", "label": "Total Amount (₹)", "fieldtype": "Currency", "width": 160},
            {"fieldname": "paid_amount", "label": "Paid (₹)", "fieldtype": "Currency", "width": 150},
            {"fieldname": "pending_amount", "label": "Pending (₹)", "fieldtype": "Currency", "width": 150},
            {"fieldname": "disputed_amount", "label": "Disputed (₹)", "fieldtype": "Currency", "width": 150},
        ]
    elif group_by == "Category Wise":
        return [
            {"fieldname": "category", "label": "Expense Category", "fieldtype": "Data", "width": 220},
            {"fieldname": "line_count", "label": "Bill Count", "fieldtype": "Int", "width": 120},
            {"fieldname": "total_amount", "label": "Total Spend (₹)", "fieldtype": "Currency", "width": 170},
            {"fieldname": "pct_share", "label": "% Share", "fieldtype": "Percent", "width": 110},
        ]
    elif group_by == "Status Wise":
        return [
            {"fieldname": "status", "label": "Workflow Status", "fieldtype": "Data", "width": 200},
            {"fieldname": "voucher_count", "label": "Vouchers Count", "fieldtype": "Int", "width": 130},
            {"fieldname": "total_amount", "label": "Total Amount (₹)", "fieldtype": "Currency", "width": 170},
            {"fieldname": "pct_share", "label": "% Share", "fieldtype": "Percent", "width": 110},
        ]
    else:
        # Detailed Lines
        return [
            {"fieldname": "posting_date", "label": "Date", "fieldtype": "Date", "width": 110},
            {"fieldname": "voucher", "label": "Voucher ID", "fieldtype": "Link", "options": "Petty Cash Entry", "width": 160},
            {"fieldname": "claim_title", "label": "Claim Title", "fieldtype": "Data", "width": 160},
            {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "width": 180},
            {"fieldname": "custodian", "label": "Beneficiary", "fieldtype": "Link", "options": "Employee", "width": 140},
            {"fieldname": "category", "label": "Category", "fieldtype": "Data", "width": 150},
            {"fieldname": "merchant", "label": "Merchant", "fieldtype": "Data", "width": 140},
            {"fieldname": "bill_number", "label": "Bill #", "fieldtype": "Data", "width": 100},
            {"fieldname": "amount", "label": "Amount (₹)", "fieldtype": "Currency", "width": 120},
            {"fieldname": "remarks", "label": "Remarks", "fieldtype": "Data", "width": 160},
            {"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 130},
            {"fieldname": "receipt", "label": "Receipt", "fieldtype": "Data", "width": 110},
        ]


def get_data_and_summary(filters):
    conditions = []
    values = {}

    if filters.get("company"):
        conditions.append("pce.company = %(company)s")
        values["company"] = filters["company"]

    if filters.get("from_date"):
        conditions.append("pce.posting_date >= %(from_date)s")
        values["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions.append("pce.posting_date <= %(to_date)s")
        values["to_date"] = filters["to_date"]

    if filters.get("status") and filters["status"] != "All":
        conditions.append("pce.status = %(status)s")
        values["status"] = filters["status"]

    if filters.get("custodian"):
        conditions.append("pce.custodian = %(custodian)s")
        values["custodian"] = filters["custodian"]

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    raw_data = frappe.db.sql(f"""
        SELECT
            pce.name as voucher,
            pce.posting_date,
            pce.claim_title,
            pce.company,
            pce.custodian,
            pce.status,
            pce.total_amount as voucher_total,
            pce.batch_id,
            pli.name as line_id,
            pli.expense_date,
            pli.expense_category as category,
            pli.merchant_name as merchant,
            pli.bill_number,
            pli.amount,
            pli.remarks,
            pli.description,
            pli.receipt_attachment as receipt,
            pli.is_disputed
        FROM `tabPetty Cash Entry` pce
        LEFT JOIN `tabPetty Cash Line Item` pli ON pli.parent = pce.name
        {where_clause}
        ORDER BY pce.posting_date DESC, pce.name DESC, pli.idx ASC
    """, values, as_dict=True)

    group_by = filters.get("group_by") or "None (Detailed Lines)"
    data = []
    
    # Summary accumulators
    unique_vouchers = set()
    total_claim_amt = 0.0
    total_paid_amt = 0.0
    total_disputed_amt = 0.0

    vouchers_seen_for_total = set()
    for row in raw_data:
        v_name = row.voucher
        unique_vouchers.add(v_name)
        if v_name not in vouchers_seen_for_total:
            vouchers_seen_for_total.add(v_name)
            v_amt = flt(row.voucher_total)
            total_claim_amt += v_amt
            if row.status in ("Paid", "Disbursed via IDFC"):
                total_paid_amt += v_amt
            elif row.status in ("Disputed", "Rejected"):
                total_disputed_amt += v_amt

    if group_by == "Month Wise":
        months = {}
        for r in raw_data:
            dt = r.posting_date or getdate()
            month_key = formatdate(dt, "YYYY-MM (MMMM YYYY)")
            ck = (month_key, r.company or "All")
            if ck not in months:
                months[ck] = {
                    "period": month_key,
                    "company": r.company,
                    "vouchers": set(),
                    "lines": 0,
                    "total_amount": 0.0,
                    "paid_amount": 0.0,
                    "pending_amount": 0.0,
                    "disputed_amount": 0.0,
                }
            item = months[ck]
            if r.voucher not in item["vouchers"]:
                item["vouchers"].add(r.voucher)
                v_amt = flt(r.voucher_total)
                item["total_amount"] += v_amt
                if r.status in ("Paid", "Disbursed via IDFC"):
                    item["paid_amount"] += v_amt
                elif r.status in ("Disputed", "Rejected"):
                    item["disputed_amount"] += v_amt
                else:
                    item["pending_amount"] += v_amt
            if r.line_id:
                item["lines"] += 1

        for ck, item in sorted(months.items(), key=lambda x: x[0][0], reverse=True):
            data.append({
                "period": item["period"],
                "company": item["company"],
                "voucher_count": len(item["vouchers"]),
                "line_count": item["lines"],
                "total_amount": round(item["total_amount"], 2),
                "paid_amount": round(item["paid_amount"], 2),
                "pending_amount": round(item["pending_amount"], 2),
                "disputed_amount": round(item["disputed_amount"], 2),
            })

    elif group_by == "Week Wise":
        weeks = {}
        for r in raw_data:
            dt = r.posting_date or getdate()
            week_key = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
            ck = (week_key, r.company or "All")
            if ck not in weeks:
                weeks[ck] = {
                    "period": week_key,
                    "company": r.company,
                    "vouchers": set(),
                    "total_amount": 0.0,
                    "paid_amount": 0.0,
                    "pending_amount": 0.0,
                    "disputed_amount": 0.0,
                }
            item = weeks[ck]
            if r.voucher not in item["vouchers"]:
                item["vouchers"].add(r.voucher)
                v_amt = flt(r.voucher_total)
                item["total_amount"] += v_amt
                if r.status in ("Paid", "Disbursed via IDFC"):
                    item["paid_amount"] += v_amt
                elif r.status in ("Disputed", "Rejected"):
                    item["disputed_amount"] += v_amt
                else:
                    item["pending_amount"] += v_amt

        for ck, item in sorted(weeks.items(), key=lambda x: x[0][0], reverse=True):
            data.append({
                "period": item["period"],
                "company": item["company"],
                "voucher_count": len(item["vouchers"]),
                "total_amount": round(item["total_amount"], 2),
                "paid_amount": round(item["paid_amount"], 2),
                "pending_amount": round(item["pending_amount"], 2),
                "disputed_amount": round(item["disputed_amount"], 2),
            })

    elif group_by == "Company Wise":
        comps = {}
        for r in raw_data:
            c = r.company or "Unassigned"
            if c not in comps:
                comps[c] = {
                    "company": c,
                    "vouchers": set(),
                    "total_amount": 0.0,
                    "paid_amount": 0.0,
                    "pending_amount": 0.0,
                    "disputed_amount": 0.0,
                }
            item = comps[c]
            if r.voucher not in item["vouchers"]:
                item["vouchers"].add(r.voucher)
                v_amt = flt(r.voucher_total)
                item["total_amount"] += v_amt
                if r.status in ("Paid", "Disbursed via IDFC"):
                    item["paid_amount"] += v_amt
                elif r.status in ("Disputed", "Rejected"):
                    item["disputed_amount"] += v_amt
                else:
                    item["pending_amount"] += v_amt

        for c, item in sorted(comps.items(), key=lambda x: x[1]["total_amount"], reverse=True):
            data.append({
                "company": item["company"],
                "voucher_count": len(item["vouchers"]),
                "total_amount": round(item["total_amount"], 2),
                "paid_amount": round(item["paid_amount"], 2),
                "pending_amount": round(item["pending_amount"], 2),
                "disputed_amount": round(item["disputed_amount"], 2),
            })

    elif group_by == "Category Wise":
        cats = {}
        total_spend = 0.0
        for r in raw_data:
            cat = r.category or "Uncategorized"
            amt = flt(r.amount)
            total_spend += amt
            if cat not in cats:
                cats[cat] = {"category": cat, "line_count": 0, "total_amount": 0.0}
            cats[cat]["line_count"] += 1
            cats[cat]["total_amount"] += amt

        for cat, item in sorted(cats.items(), key=lambda x: x[1]["total_amount"], reverse=True):
            data.append({
                "category": item["category"],
                "line_count": item["line_count"],
                "total_amount": round(item["total_amount"], 2),
                "pct_share": round((item["total_amount"] / (total_spend or 1.0)) * 100, 1),
            })

    elif group_by == "Status Wise":
        statuses = {}
        for r in raw_data:
            st = r.status or "Draft"
            if st not in statuses:
                statuses[st] = {"status": st, "vouchers": set(), "total_amount": 0.0}
            if r.voucher not in statuses[st]["vouchers"]:
                statuses[st]["vouchers"].add(r.voucher)
                statuses[st]["total_amount"] += flt(r.voucher_total)

        for st, item in sorted(statuses.items(), key=lambda x: x[1]["total_amount"], reverse=True):
            data.append({
                "status": item["status"],
                "voucher_count": len(item["vouchers"]),
                "total_amount": round(item["total_amount"], 2),
                "pct_share": round((item["total_amount"] / (total_claim_amt or 1.0)) * 100, 1),
            })

    else:
        # None (Detailed Lines)
        for r in raw_data:
            receipt_html = f'<a href="{r.receipt}" target="_blank" style="color:#2563eb; font-weight:600;">🧾 View</a>' if r.receipt else '<span style="color:#94a3b8;">No File</span>'
            data.append({
                "posting_date": r.expense_date or r.posting_date,
                "voucher": r.voucher,
                "claim_title": r.claim_title or "",
                "company": r.company,
                "custodian": r.custodian,
                "category": r.category or "",
                "merchant": r.merchant or "",
                "bill_number": r.bill_number or "",
                "amount": flt(r.amount),
                "remarks": r.remarks or r.description or "",
                "status": r.status,
                "receipt": receipt_html,
            })

    # Visual Chart
    chart = get_chart_data(group_by, data)

    # Summary Cards
    report_summary = [
        {"value": len(unique_vouchers), "label": "Total Vouchers", "datatype": "Int"},
        {"value": round(total_claim_amt, 2), "label": "Total Claimed (₹)", "datatype": "Currency", "indicator": "Blue"},
        {"value": round(total_paid_amt, 2), "label": "Paid / Disbursed (₹)", "datatype": "Currency", "indicator": "Green"},
        {"value": round(total_claim_amt - total_paid_amt - total_disputed_amt, 2), "label": "In Review / Pending (₹)", "datatype": "Currency", "indicator": "Orange"},
        {"value": round(total_disputed_amt, 2), "label": "Disputed / Rejected (₹)", "datatype": "Currency", "indicator": "Red"},
    ]

    return data, chart, report_summary


def get_chart_data(group_by, data):
    if not data:
        return None

    if group_by in ("Month Wise", "Week Wise", "Company Wise"):
        labels = [d.get("period") or d.get("company") for d in data[:8]]
        datasets = [
            {"name": "Total Amount (₹)", "values": [d.get("total_amount", 0) for d in data[:8]]},
            {"name": "Paid Amount (₹)", "values": [d.get("paid_amount", 0) for d in data[:8]]}
        ]
        return {
            "data": {"labels": labels, "datasets": datasets},
            "type": "bar",
            "colors": ["#3b82f6", "#10b981"]
        }
    elif group_by == "Category Wise":
        labels = [d.get("category") for d in data[:7]]
        values = [d.get("total_amount", 0) for d in data[:7]]
        return {
            "data": {"labels": labels, "datasets": [{"name": "Spend", "values": values}]},
            "type": "percentage",
            "colors": ["#6366f1", "#06b6d4", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#94a3b8"]
        }
    elif group_by == "Status Wise":
        labels = [d.get("status") for d in data]
        values = [d.get("total_amount", 0) for d in data]
        return {
            "data": {"labels": labels, "datasets": [{"name": "Status Share", "values": values}]},
            "type": "donut",
            "colors": ["#94a3b8", "#3b82f6", "#6366f1", "#06b6d4", "#10b981", "#ef4444", "#f59e0b"]
        }
    return None
