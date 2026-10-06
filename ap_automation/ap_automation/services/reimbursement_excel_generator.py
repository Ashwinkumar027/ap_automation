# -*- coding: utf-8 -*-
# Copyright (c) 2026, Aionion Capital Market Services Private Limited
# For license information, please see license.txt

import frappe
from frappe.utils import getdate, flt, cstr, formatdate
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
import io

@frappe.whitelist()
def download_reimbursement_excel(voucher_name):
    """
    Dynamically generates the official Aionion Petty Cash Expenses / Reimbursement Form
    in Microsoft Excel (.xlsx) format matching the exact company template.
    """
    if not voucher_name:
        frappe.throw("Voucher name is required.")

    doc = frappe.get_doc("Employee Reimbursement Claim", voucher_name)

    # Fetch employee bank details if not present on doc
    emp_id = doc.employee
    emp = frappe.db.get_value("Employee", emp_id, ["employee_name", "bank_name", "bank_ac_no", "ifsc_code", "department"], as_dict=True) or {}
    
    emp_name = doc.get("employee_name") or emp.get("employee_name") or emp_id
    id_number = emp_id or ""
    bank_name = doc.get("bank_name") or emp.get("bank_name") or ""
    ac_number = doc.get("bank_account_number") or emp.get("bank_ac_no") or ""
    ifsc_code = doc.get("bank_ifsc_code") or emp.get("ifsc_code") or ""
    name_as_per_bank = emp_name

    category = doc.get("claim_category") or "General Expense"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reimbursement Voucher"
    ws.views.sheetView[0].showGridLines = True

    # Styling definitions
    font_title = Font(name="Calibri", size=13, bold=True)
    font_header_bold = Font(name="Calibri", size=10, bold=True)
    font_regular = Font(name="Calibri", size=10)
    font_notes_bold = Font(name="Calibri", size=10, bold=True)
    font_notes = Font(name="Calibri", size=9)

    fill_header = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    fill_section = PatternFill(start_color="E9EEF4", end_color="E9EEF4", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color='A0A0A0'),
        right=Side(style='thin', color='A0A0A0'),
        top=Side(style='thin', color='A0A0A0'),
        bottom=Side(style='thin', color='A0A0A0')
    )
    thick_bottom = Border(
        left=Side(style='thin', color='A0A0A0'),
        right=Side(style='thin', color='A0A0A0'),
        top=Side(style='thin', color='A0A0A0'),
        bottom=Side(style='medium', color='000000')
    )

    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    align_right = Alignment(horizontal="right", vertical="center", wrap_text=True)

    # Determine max columns based on category
    if category == "Dinner Allowance":
        max_col = 7
    else:
        max_col = 6

    curr_row = 2

    # Title: Petty Cash Expenses
    ws.merge_cells(start_row=curr_row, start_column=1, end_row=curr_row, end_column=max_col)
    title_cell = ws.cell(row=curr_row, column=1, value="Petty Cash Expenses")
    title_cell.font = font_title
    title_cell.alignment = align_center
    curr_row += 2

    # --- TOP EMPLOYEE BANK DETAILS TABLE ---
    bank_headers = ["Employee Name", "ID Number", "Name as per Bank", "Bank Name", "Account Number", "IFSC Code"]
    bank_values = [emp_name, id_number, name_as_per_bank, bank_name, ac_number, ifsc_code]

    if max_col == 7:
        bank_headers.append("")
        bank_values.append("")

    for col_idx, h in enumerate(bank_headers, start=1):
        c = ws.cell(row=curr_row, column=col_idx, value=h)
        c.font = font_header_bold
        c.alignment = align_center
        c.fill = fill_header
        c.border = thin_border

    curr_row += 1
    for col_idx, val in enumerate(bank_values, start=1):
        c = ws.cell(row=curr_row, column=col_idx, value=val)
        c.font = font_regular
        c.alignment = align_center
        c.border = thin_border

    curr_row += 2

    # --- EXPENSE ITEMS TABLE HEADERS ---
    if category == "Dinner Allowance":
        table_headers = ["S. No", "Expense Date", "Expense Description", "Invoice Amount", "Remarks If any", "Company Name", "OUT TIME"]
    else:
        table_headers = ["S. No", "Expense Date", "Expense Description", "Invoice Amount", "Remarks If any", "Company Name"]

    table_start_row = curr_row
    for col_idx, h in enumerate(table_headers, start=1):
        c = ws.cell(row=curr_row, column=col_idx, value=h)
        c.font = font_header_bold
        c.alignment = align_center
        c.fill = fill_header
        c.border = thin_border

    curr_row += 1

    # Extract lines depending on category
    lines_data = []
    if category == "Client Visit Travel" and (doc.get("client_visit_legs") or []):
        for idx, leg in enumerate(doc.get("client_visit_legs") or [], start=1):
            dt_str = formatdate(leg.visit_date, "dd-mm-yyyy") if leg.visit_date else ""
            desc = f"{leg.from_location or ''} to {leg.to_location or ''} ({flt(leg.distance_km)} kms, {leg.mode_of_travel or ''})"
            amt = flt(leg.leg_amount or 0.0) + flt(leg.toll_parking_amount or 0.0)
            rem = f"Mileage + Tolls | {leg.client_name or ''}"
            lines_data.append({
                "sno": idx,
                "date": dt_str,
                "desc": desc,
                "amount": amt,
                "remarks": rem,
                "company": "ACM",
                "out_time": ""
            })
    else:
        for idx, line in enumerate(doc.get("expense_lines") or [], start=1):
            dt_str = formatdate(line.expense_date, "dd-mm-yyyy") if line.expense_date else ""
            desc = line.description or line.expense_type or "Expense"
            amt = flt(line.amount or 0.0)
            rem = line.payment_mode_used or line.description or "Bill attached"
            out_t = line.out_time or doc.get("swipe_out_time") or ""
            lines_data.append({
                "sno": idx,
                "date": dt_str,
                "desc": desc,
                "amount": amt,
                "remarks": rem,
                "company": line.get("company_name") or "ACM",
                "out_time": out_t
            })

    if not lines_data:
        # Placeholder row if empty
        lines_data.append({
            "sno": 1,
            "date": formatdate(doc.posting_date, "dd-mm-yyyy"),
            "desc": category,
            "amount": flt(doc.total_claim_amount or 0.0),
            "remarks": "Bill attached",
            "company": "ACM",
            "out_time": ""
        })

    row_data_start = curr_row
    for line in lines_data:
        ws.cell(row=curr_row, column=1, value=line["sno"]).alignment = align_center
        ws.cell(row=curr_row, column=2, value=line["date"]).alignment = align_center
        ws.cell(row=curr_row, column=3, value=line["desc"]).alignment = align_left
        
        amt_cell = ws.cell(row=curr_row, column=4, value=line["amount"])
        amt_cell.alignment = align_right
        amt_cell.number_format = '₹ #,##0.00'
        
        ws.cell(row=curr_row, column=5, value=line["remarks"]).alignment = align_left
        ws.cell(row=curr_row, column=6, value=line["company"]).alignment = align_center
        
        if max_col == 7:
            ws.cell(row=curr_row, column=7, value=line["out_time"]).alignment = align_center

        for c_idx in range(1, max_col + 1):
            ws.cell(row=curr_row, column=c_idx).border = thin_border
            ws.cell(row=curr_row, column=c_idx).font = font_regular

        curr_row += 1

    row_data_end = curr_row - 1

    # --- TOTAL ROW ---
    ws.merge_cells(start_row=curr_row, start_column=1, end_row=curr_row, end_column=3)
    total_label = ws.cell(row=curr_row, column=1, value="TOTAL")
    total_label.font = font_header_bold
    total_label.alignment = align_center

    total_amt_cell = ws.cell(row=curr_row, column=4, value=f"=SUM(D{row_data_start}:D{row_data_end})")
    total_amt_cell.font = font_header_bold
    total_amt_cell.alignment = align_right
    total_amt_cell.number_format = '₹ #,##0.00'

    # If team lunch with cap, show remarks in total row
    if category == "Team Lunch / Outing" and doc.get("prior_quarter_claimed"):
        ws.cell(row=curr_row, column=5, value=f"Claimed in quarter: ₹{doc.prior_quarter_claimed:,.2f}").font = font_notes

    for c_idx in range(1, max_col + 1):
        ws.cell(row=curr_row, column=c_idx).border = thick_bottom
        ws.cell(row=curr_row, column=c_idx).fill = fill_section

    curr_row += 2

    # --- CATEGORY SPECIFIC SUB-SECTIONS ---
    # 1. Client Visit Details Box
    if category == "Client Visit Travel" and (doc.get("client_name") or doc.get("client_code")):
        ws.cell(row=curr_row, column=1, value="Client details:").font = font_header_bold
        curr_row += 1
        ws.cell(row=curr_row, column=1, value=f"Client Name: {doc.client_name or ''}").font = font_regular
        curr_row += 1
        ws.cell(row=curr_row, column=1, value=f"Client ID: {doc.client_code or ''}").font = font_regular
        curr_row += 1
        ws.cell(row=curr_row, column=1, value=f"Phone Number: {doc.client_phone or ''}").font = font_regular
        curr_row += 2

    # 2. Team Participants Table
    if category == "Team Lunch / Outing" and (doc.get("participants") or []):
        ws.cell(row=curr_row, column=1, value="Employees Names:").font = font_header_bold
        curr_row += 1
        
        # Sub-table headers
        ws.cell(row=curr_row, column=1, value="S.No").border = thin_border
        ws.cell(row=curr_row, column=1).font = font_header_bold
        ws.cell(row=curr_row, column=1).fill = fill_header
        
        ws.cell(row=curr_row, column=2, value="ID Number").border = thin_border
        ws.cell(row=curr_row, column=2).font = font_header_bold
        ws.cell(row=curr_row, column=2).fill = fill_header
        
        ws.merge_cells(start_row=curr_row, start_column=3, end_row=curr_row, end_column=4)
        p_name_hdr = ws.cell(row=curr_row, column=3, value="Employee Name")
        p_name_hdr.border = thin_border
        p_name_hdr.font = font_header_bold
        p_name_hdr.fill = fill_header
        ws.cell(row=curr_row, column=4).border = thin_border

        ws.cell(row=curr_row, column=5, value="Branch").border = thin_border
        ws.cell(row=curr_row, column=5).font = font_header_bold
        ws.cell(row=curr_row, column=5).fill = fill_header

        ws.cell(row=curr_row, column=6, value="Allocated Share").border = thin_border
        ws.cell(row=curr_row, column=6).font = font_header_bold
        ws.cell(row=curr_row, column=6).fill = fill_header

        curr_row += 1
        for p_idx, p in enumerate(doc.get("participants") or [], start=1):
            ws.cell(row=curr_row, column=1, value=p_idx).alignment = align_center
            ws.cell(row=curr_row, column=2, value=p.employee_id).alignment = align_center
            
            ws.merge_cells(start_row=curr_row, start_column=3, end_row=curr_row, end_column=4)
            ws.cell(row=curr_row, column=3, value=p.employee_name).alignment = align_left

            ws.cell(row=curr_row, column=5, value=p.branch_location or "Bangalore").alignment = align_center
            
            share_c = ws.cell(row=curr_row, column=6, value=flt(p.allocated_share or 0.0))
            share_c.alignment = align_right
            share_c.number_format = '₹ #,##0.00'

            for c_idx in range(1, max_col + 1):
                ws.cell(row=curr_row, column=c_idx).border = thin_border
                ws.cell(row=curr_row, column=c_idx).font = font_regular
            curr_row += 1

        curr_row += 2

    # --- IMPORTANT NOTES FOOTER ---
    ws.cell(row=curr_row, column=1, value="Important Notes:").font = font_notes_bold
    curr_row += 1

    notes = [
        "• Attach the respective Invoices and CC the reporting head.",
        "• Payments will only be made to the respective employee's bank account; third-party payments are not allowed.",
        "• Reimbursements will be rejected if the invoice does not match the submitted expense description or date.",
        "• Invoices must be clear, legible, and include all necessary details.",
        "• Ensure that all expense claims are submitted within the weekly cycle for timely processing.",
        "• Crosscheck the account number before sending."
    ]

    for note in notes:
        ws.cell(row=curr_row, column=1, value=note).font = font_notes
        curr_row += 1

    # Auto-adjust column widths
    ws.column_dimensions['A'].width = 8   # S.No
    ws.column_dimensions['B'].width = 16  # Date / ID Number
    ws.column_dimensions['C'].width = 38  # Description / Route
    ws.column_dimensions['D'].width = 18  # Amount
    ws.column_dimensions['E'].width = 24  # Remarks
    ws.column_dimensions['F'].width = 16  # Company Name
    if max_col == 7:
        ws.column_dimensions['G'].width = 14  # Out Time

    # Save to buffer
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"Reimbursement_Voucher_{voucher_name}.xlsx"
    frappe.response['filename'] = filename
    frappe.response['filecontent'] = output.getvalue()
    frappe.response['type'] = 'binary'
