import io
import frappe
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


@frappe.whitelist()
def export_petty_cash_excel(voucher_name):
    """Generates and downloads a beautifully styled Excel workbook for a Petty Cash Voucher."""
    if not frappe.has_permission("Petty Cash Entry", "read", voucher_name):
        frappe.throw("You do not have permission to export this Petty Cash Voucher.", frappe.PermissionError)

    doc = frappe.get_doc("Petty Cash Entry", voucher_name)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Voucher {doc.name}"
    ws.views.sheetView[0].showGridLines = True

    # Palette
    title_font = Font(name="Calibri", size=15, bold=True, color="1E3A8A")
    sec_font = Font(name="Calibri", size=11, bold=True, color="1E293B")
    th_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    th_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    meta_label_font = Font(name="Calibri", size=10, bold=True, color="475569")
    meta_val_font = Font(name="Calibri", size=10, color="0F172A")
    total_font = Font(name="Calibri", size=10, bold=True, color="0F172A")
    total_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    # 1. Title Banner
    ws.merge_cells("A1:I1")
    ws["A1"] = f"PETTY CASH VOUCHER STATEMENT — {doc.name}"
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 28

    # 2. Metadata Section
    meta = [
        ("Voucher ID:", doc.name, "Posting Date:", str(doc.posting_date or "")),
        ("Claim Title:", doc.claim_title or "N/A", "Workflow Status:", doc.status or "Draft"),
        ("Company:", doc.company or "N/A", "Payment Batch ID:", doc.batch_id or "N/A"),
        ("Beneficiary Employee:", doc.custodian or "N/A", "Beneficiary Name:", doc.beneficiary_name or "N/A"),
        ("Bank Name:", doc.bank_name or "N/A", "Bank A/C No:", doc.custodian_bank_account or "N/A"),
        ("Bank IFSC Code:", doc.custodian_ifsc_code or "N/A", "Total Amount (₹):", f"₹ {float(doc.total_amount or 0):,.2f}")
    ]

    r = 3
    for m in meta:
        ws.cell(row=r, column=1, value=m[0]).font = meta_label_font
        ws.cell(row=r, column=2, value=m[1]).font = meta_val_font
        ws.cell(row=r, column=4, value=m[2]).font = meta_label_font
        ws.cell(row=r, column=5, value=m[3]).font = meta_val_font
        r += 1

    r += 1
    # 3. Line Items Table
    ws.cell(row=r, column=1, value="EXPENSE LINE ITEMS").font = sec_font
    r += 1

    headers = ["#", "Date", "Category", "Merchant / Payee", "Bill #", "Amount (₹)", "Staff Name", "Remarks", "Receipt Attachment"]
    for c_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=r, column=c_idx, value=h)
        cell.font = th_font
        cell.fill = th_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
    ws.row_dimensions[r].height = 22

    r += 1
    start_line_r = r
    lines = doc.expense_lines or []
    for idx, line in enumerate(lines, 1):
        ws.cell(row=r, column=1, value=idx).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=2, value=str(line.expense_date or "")).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=3, value=line.expense_category or "")
        ws.cell(row=r, column=4, value=line.merchant_name or "")
        ws.cell(row=r, column=5, value=line.bill_number or "N/A").alignment = Alignment(horizontal="center")
        amt_cell = ws.cell(row=r, column=6, value=float(line.amount or 0.0))
        amt_cell.number_format = '₹ #,##0.00'
        amt_cell.alignment = Alignment(horizontal="right")
        ws.cell(row=r, column=7, value=line.employee or "")
        ws.cell(row=r, column=8, value=getattr(line, "remarks", "") or getattr(line, "description", "") or "")

        receipt_url = line.receipt_attachment or ""
        receipt_cell = ws.cell(row=r, column=9, value="View Receipt" if receipt_url else "No Receipt")
        if receipt_url:
            receipt_cell.hyperlink = receipt_url
            receipt_cell.font = Font(color="2563EB", underline="single")
        receipt_cell.alignment = Alignment(horizontal="center")

        for c in range(1, 10):
            ws.cell(row=r, column=c).border = thin_border
        r += 1

    if lines:
        # Total Summary Row
        ws.cell(row=r, column=1, value="TOTAL").font = total_font
        ws.cell(row=r, column=1).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=1).fill = total_fill
        for c in range(2, 6):
            ws.cell(row=r, column=c).fill = total_fill
        tot_cell = ws.cell(row=r, column=6, value=f"=SUM(F{start_line_r}:F{r-1})")
        tot_cell.font = total_font
        tot_cell.fill = total_fill
        tot_cell.number_format = '₹ #,##0.00'
        tot_cell.alignment = Alignment(horizontal="right")
        for c in range(7, 10):
            ws.cell(row=r, column=c).fill = total_fill
        for c in range(1, 10):
            ws.cell(row=r, column=c).border = thin_border
        r += 2

    # 4. Approval Audit Trail
    if getattr(doc, "approval_trail", None) and len(doc.approval_trail) > 0:
        ws.cell(row=r, column=1, value="APPROVAL AUDIT TRAIL").font = sec_font
        r += 1
        trail_headers = ["Level", "Action / Status", "Approver User", "Timestamp", "Remarks"]
        for c_idx, h in enumerate(trail_headers, 1):
            cell = ws.cell(row=r, column=c_idx, value=h)
            cell.font = th_font
            cell.fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border
        r += 1
        for tr in doc.approval_trail:
            ws.cell(row=r, column=1, value=tr.approval_level or "").alignment = Alignment(horizontal="center")
            ws.cell(row=r, column=2, value=tr.action or "")
            ws.cell(row=r, column=3, value=tr.approver or "")
            ws.cell(row=r, column=4, value=str(tr.action_timestamp or "")).alignment = Alignment(horizontal="center")
            ws.cell(row=r, column=5, value=tr.comments or "")
            for c in range(1, 6):
                ws.cell(row=r, column=c).border = thin_border
            r += 1

    # Adjust widths
    for col in ws.columns:
        vals = [len(str(cell.value or '')) for cell in col if cell.row > 1]
        max_len = max(vals) if vals else 10
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(min(max_len + 4, 40), 12)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)

    frappe.response['filename'] = f"Petty_Cash_{doc.name}.xlsx"
    frappe.response['filecontent'] = out.getvalue()
    frappe.response['type'] = 'binary'
