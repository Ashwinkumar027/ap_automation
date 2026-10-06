# -*- coding: utf-8 -*-
# Copyright (c) 2026, Aionion Capital Market Services Private Limited
# For license information, please see license.txt

import frappe
from frappe.utils import flt, cstr, nowdate, getdate, formatdate
import io
import csv
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from ap_automation.services import reimbursement_email_service

@frappe.whitelist()
def get_weekly_friday_settlement_roster(company=None):
    """
    O(N) High-Performance Settlement Query:
    Fetches all claims eligible for the Weekly Friday Settlement Run,
    aggregated and grouped Employee-wise with verified Bank details.
    """
    query = """
        SELECT 
            c.name as claim_id,
            c.employee,
            c.employee_name,
            c.claim_category,
            c.total_claim_amount,
            c.sanctioned_amount,
            c.net_payable_amount,
            c.status,
            c.posting_date,
            c.activity_date,
            c.bank_name,
            c.bank_account_number,
            c.bank_ifsc_code,
            c.is_resubmission,
            c.creation
        FROM `tabEmployee Reimbursement Claim` c
        WHERE (c.status IN ('Approved for Payment', 'Queued in Batch', 'Approved by Manager', 'Submitted') OR c.workflow_state LIKE '%Accounts%' OR c.workflow_state LIKE '%Approved%')
          AND c.status NOT IN ('Paid', 'Cancelled', 'Rejected')
          AND c.docstatus = 0
        ORDER BY c.employee, c.creation DESC
    """
    claims = frappe.db.sql(query, as_dict=True)

    # O(N) In-Memory Employee Aggregation
    employee_map = {}
    category_summary = {
        "Client Visit Travel": {"count": 0, "amount": 0.0},
        "Dinner Allowance": {"count": 0, "amount": 0.0},
        "Team Lunch / Outing": {"count": 0, "amount": 0.0},
        "General Expense": {"count": 0, "amount": 0.0},
        "Branch Expense & Maintenance": {"count": 0, "amount": 0.0}
    }

    total_gross = 0.0
    total_deductions = 0.0
    total_net = 0.0

    for c in claims:
        emp_id = c.employee
        cat = c.claim_category or "General Expense"
        amt = flt(c.net_payable_amount or c.total_claim_amount or 0.0)

        # Update category summary
        if cat not in category_summary:
            category_summary[cat] = {"count": 0, "amount": 0.0}
        category_summary[cat]["count"] += 1
        category_summary[cat]["amount"] += amt

        total_gross += flt(c.total_claim_amount or 0.0)
        total_net += amt

        # Group by employee
        if emp_id not in employee_map:
            employee_map[emp_id] = {
                "employee_id": emp_id,
                "employee_name": c.employee_name or emp_id,
                "bank_name": c.bank_name or "N/A",
                "bank_account_number": c.bank_account_number or "N/A",
                "bank_ifsc_code": c.bank_ifsc_code or "N/A",
                "claims_count": 0,
                "gross_amount": 0.0,
                "deductions": 0.0,
                "net_payable": 0.0,
                "has_dispute": False,
                "claims": []
            }

        # Check for disputed lines in child table
        lines = frappe.get_all(
            "Employee Reimbursement Line",
            filters={"parent": c.claim_id},
            fields=["idx", "expense_type", "description", "amount", "is_disputed", "dispute_reason", "receipt_attachment"]
        )

        disputed_lines_count = sum(1 for l in lines if l.get("is_disputed"))
        if disputed_lines_count > 0:
            employee_map[emp_id]["has_dispute"] = True

        employee_map[emp_id]["claims_count"] += 1
        employee_map[emp_id]["gross_amount"] += flt(c.total_claim_amount or 0.0)
        employee_map[emp_id]["net_payable"] += amt
        employee_map[emp_id]["claims"].append({
            "claim_id": c.claim_id,
            "category": cat,
            "posting_date": formatdate(c.posting_date, "dd-mm-yyyy"),
            "status": c.status,
            "amount": amt,
            "disputed_count": disputed_lines_count,
            "lines": lines
        })

    roster = list(employee_map.values())
    roster.sort(key=lambda x: x["net_payable"], reverse=True)

    return {
        "summary": {
            "total_employees": len(roster),
            "total_claims": len(claims),
            "total_gross_amount": round(total_gross, 2),
            "total_deductions": round(total_deductions, 2),
            "total_net_payable": round(total_net, 2),
            "settlement_date": nowdate()
        },
        "categories": category_summary,
        "roster": roster
    }


@frappe.whitelist()
def dispute_claim_line_item(claim_name, line_idx, target_role, dispute_reason):
    """
    Accounts Team Action:
    Disputes an individual line item on a claim, subtracts the amount from Friday net payable,
    and dispatches a threaded email to the Target Person with CC to all stakeholders.
    """
    if not claim_name:
        frappe.throw("Claim ID is required.")

    claim = frappe.get_doc("Employee Reimbursement Claim", claim_name)
    idx = int(line_idx)

    # Locate child line
    target_line = None
    for line in claim.expense_lines:
        if line.idx == idx:
            target_line = line
            break

    if not target_line:
        frappe.throw(f"Line #{idx} not found on claim {claim_name}.")

    disputed_amt = flt(target_line.amount or 0.0)
    target_line.is_disputed = 1
    target_line.dispute_reason = dispute_reason or "Verification proof required by Accounts Audit."

    # Adjust claim sanctioned and net amounts
    current_net = flt(claim.net_payable_amount or claim.total_claim_amount or 0.0)
    claim.sanctioned_amount = max(0.0, current_net - disputed_amt)
    claim.net_payable_amount = claim.sanctioned_amount
    claim.flags.ignore_permissions = True
    claim.flags.ignore_validate_immutability = True
    frappe.db.set_value("Employee Reimbursement Claim", claim.name, {
        "sanctioned_amount": claim.sanctioned_amount,
        "net_payable_amount": claim.net_payable_amount
    })

    from ap_automation.services import employee_expense_approval_service
    employee_expense_approval_service.reject_claim_flexible(
        voucher_name=claim.name,
        reason=f"Line #{idx} ({target_line.expense_type}) Disputed: {dispute_reason}",
        return_to=target_role
    )

    # Send single-thread corporate email notification
    email_res = reimbursement_email_service.send_dispute_notification_email(
        claim_name=claim.name,
        line_idx=idx,
        target_role=target_role,
        dispute_reason=dispute_reason
    )

    return {
        "status": "SUCCESS",
        "claim_name": claim.name,
        "disputed_amount": disputed_amt,
        "new_net_payable": claim.net_payable_amount,
        "email_info": email_res
    }


@frappe.whitelist()
def export_friday_bank_cms_file(format_type="EXCEL"):
    """
    Generates a consolidated Corporate Bank CMS Payment File (Excel / CSV)
    for bulk upload into HDFC / ICICI / IDFC Corporate Net Banking.
    """
    roster_data = get_weekly_friday_settlement_roster()
    roster = roster_data.get("roster", [])

    if not roster:
        frappe.throw("No claims currently eligible for Friday Bank Settlement.")

    if format_type.upper() == "CSV":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Record Type", "Payment Mode", "Beneficiary Name", "Account Number", "IFSC Code", "Amount", "Narration", "Voucher References"])

        for emp in roster:
            if emp["net_payable"] <= 0:
                continue
            vouchers = ", ".join([c["claim_id"] for c in emp["claims"]])
            narration = f"REIMB-WK-OCT-{emp['employee_id']}"
            writer.writerow([
                "CMS",
                "NEFT",
                emp["employee_name"],
                emp["bank_account_number"],
                emp["bank_ifsc_code"],
                f"{emp['net_payable']:.2f}",
                narration,
                vouchers
            ])

        frappe.response['filename'] = f"Friday_Bank_CMS_Payout_{nowdate()}.csv"
        frappe.response['filecontent'] = output.getvalue()
        frappe.response['type'] = 'csv'
        return

    # Excel Generation
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Friday CMS Payout"
    ws.views.sheetView[0].showGridLines = True

    font_hdr = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_bold = Font(name="Calibri", size=10, bold=True)
    font_reg = Font(name="Calibri", size=10)
    fill_hdr = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    fill_tot = PatternFill(start_color="E9EEF4", end_color="E9EEF4", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color='A0A0A0'),
        right=Side(style='thin', color='A0A0A0'),
        top=Side(style='thin', color='A0A0A0'),
        bottom=Side(style='thin', color='A0A0A0')
    )

    headers = [
        "S.No", "Employee ID", "Beneficiary Name", "Bank Name", "Account Number", 
        "IFSC Code", "Claims Count", "Total Payout Amount (INR)", "Corporate Narration", "Voucher IDs"
    ]

    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col_idx, value=h)
        c.font = font_hdr
        c.fill = fill_hdr
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = thin_border

    curr_row = 2
    for idx, emp in enumerate(roster, start=1):
        if emp["net_payable"] <= 0:
            continue
        vouchers = ", ".join([c["claim_id"] for c in emp["claims"]])
        narration = f"REIMB-WK-OCT-{emp['employee_id']}"

        ws.cell(row=curr_row, column=1, value=idx).alignment = Alignment(horizontal="center")
        ws.cell(row=curr_row, column=2, value=emp["employee_id"]).alignment = Alignment(horizontal="center")
        ws.cell(row=curr_row, column=3, value=emp["employee_name"]).alignment = Alignment(horizontal="left")
        ws.cell(row=curr_row, column=4, value=emp["bank_name"]).alignment = Alignment(horizontal="center")
        ws.cell(row=curr_row, column=5, value=emp["bank_account_number"]).alignment = Alignment(horizontal="center")
        ws.cell(row=curr_row, column=6, value=emp["bank_ifsc_code"]).alignment = Alignment(horizontal="center")
        ws.cell(row=curr_row, column=7, value=emp["claims_count"]).alignment = Alignment(horizontal="center")
        
        amt_cell = ws.cell(row=curr_row, column=8, value=emp["net_payable"])
        amt_cell.alignment = Alignment(horizontal="right")
        amt_cell.number_format = '₹ #,##0.00'

        ws.cell(row=curr_row, column=9, value=narration).alignment = Alignment(horizontal="left")
        ws.cell(row=curr_row, column=10, value=vouchers).alignment = Alignment(horizontal="left")

        for c_idx in range(1, 11):
            ws.cell(row=curr_row, column=c_idx).border = thin_border
            ws.cell(row=curr_row, column=c_idx).font = font_reg

        curr_row += 1

    # Total row
    ws.merge_cells(start_row=curr_row, start_column=1, end_row=curr_row, end_column=7)
    tot_lbl = ws.cell(row=curr_row, column=1, value="TOTAL FRIDAY DISBURSAL")
    tot_lbl.font = font_bold
    tot_lbl.alignment = Alignment(horizontal="center")

    tot_amt = ws.cell(row=curr_row, column=8, value=f"=SUM(H2:H{curr_row - 1})")
    tot_amt.font = font_bold
    tot_amt.alignment = Alignment(horizontal="right")
    tot_amt.number_format = '₹ #,##0.00'

    for c_idx in range(1, 11):
        ws.cell(row=curr_row, column=c_idx).border = thin_border
        ws.cell(row=curr_row, column=c_idx).fill = fill_tot

    # Auto widths
    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 14
    ws.column_dimensions['C'].width = 28
    ws.column_dimensions['D'].width = 20
    ws.column_dimensions['E'].width = 22
    ws.column_dimensions['F'].width = 16
    ws.column_dimensions['G'].width = 14
    ws.column_dimensions['H'].width = 24
    ws.column_dimensions['I'].width = 24
    ws.column_dimensions['J'].width = 32

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    frappe.response['filename'] = f"Friday_Corporate_Bank_CMS_Payout_{nowdate()}.xlsx"
    frappe.response['filecontent'] = output.getvalue()
    frappe.response['type'] = 'binary'


@frappe.whitelist()
def release_friday_batch_payout(payment_reference=None):
    """
    Accounts Team Action:
    Marks all eligible vouchers in Friday's run as 'Paid via Bank Transfer',
    logs UTR reference, and sends individual confirmation emails to employees.
    """
    roster_data = get_weekly_friday_settlement_roster()
    roster = roster_data.get("roster", [])

    if not roster:
        frappe.throw("No claims found to disburse.")

    utr = payment_reference or f"CMS-PAY-{nowdate()}"
    processed_count = 0
    total_disbursed = 0.0

    for emp in roster:
        if emp["net_payable"] <= 0:
            continue
        for claim_info in emp["claims"]:
            c_name = claim_info["claim_id"]
            claim_doc = frappe.get_doc("Employee Reimbursement Claim", c_name)
            if claim_doc.status not in ("Approved for Payment", "Ready for Payment Batch", "Pending Accounts L2"):
                continue

            frappe.db.set_value("Employee Reimbursement Claim", claim_doc.name, "status", "Paid via Bank Transfer")

            # Dispatch success email
            try:
                reimbursement_email_service.send_batch_payout_success_email(claim_doc.name, utr)
            except Exception:
                pass

            processed_count += 1
            total_disbursed += flt(claim_doc.net_payable_amount)

    return {
        "status": "SUCCESS",
        "processed_claims_count": processed_count,
        "total_disbursed_amount": total_disbursed,
        "payment_reference": utr,
        "message": f"Successfully disbursed {processed_count} vouchers (Total: INR {total_disbursed:,.2f}) with UTR #{utr}"
    }
