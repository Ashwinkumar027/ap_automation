from typing import Any, Callable, Dict, List, Optional
import io
import frappe
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


def _get_excel_palette() -> Dict[str, Any]:
    """Returns shared corporate openpyxl styles across AP and Event Excel exports."""
    thin_side = Side(style="thin", color="CBD5E1")
    return {
        "title_font": Font(name="Calibri", size=15, bold=True, color="1E3A8A"),
        "sec_font": Font(name="Calibri", size=11, bold=True, color="1E293B"),
        "th_font": Font(name="Calibri", size=10, bold=True, color="FFFFFF"),
        "th_fill": PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid"),
        "trail_fill": PatternFill(start_color="334155", end_color="334155", fill_type="solid"),
        "meta_label_font": Font(name="Calibri", size=10, bold=True, color="475569"),
        "meta_val_font": Font(name="Calibri", size=10, color="0F172A"),
        "total_font": Font(name="Calibri", size=10, bold=True, color="0F172A"),
        "total_fill": PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid"),
        "pivot_head_fill": PatternFill(start_color="D1E7DD", end_color="D1E7DD", fill_type="solid"),
        "link_font": Font(color="2563EB", underline="single"),
        "thin_border": Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side),
    }


def _mask_bank_account(raw_acc: Any) -> str:
    acc = str(raw_acc or "").strip()
    if not acc:
        return "N/A"
    if len(acc) >= 4 and not acc.startswith("••••"):
        return f"•••• •••• •••• {acc[-4:]}"
    return acc


def _init_workbook(sheet_title: str, banner_text: str, merge_range: str, styles: Dict[str, Any]):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]
    ws.views.sheetView[0].showGridLines = True
    ws.merge_cells(merge_range)
    ws["A1"] = banner_text
    ws["A1"].font = styles["title_font"]
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 28
    return wb, ws


def _write_meta_grid(ws, meta_rows: List[tuple], start_row: int, styles: Dict[str, Any]) -> int:
    r = start_row
    for m in meta_rows:
        ws.cell(row=r, column=1, value=m[0]).font = styles["meta_label_font"]
        ws.cell(row=r, column=2, value=m[1]).font = styles["meta_val_font"]
        if len(m) >= 4:
            ws.cell(row=r, column=4, value=m[2]).font = styles["meta_label_font"]
            ws.cell(row=r, column=5, value=m[3]).font = styles["meta_val_font"]
        r += 1
    return r


def _write_table_headers(ws, row_idx: int, headers: List[str], styles: Dict[str, Any], fill=None) -> int:
    header_fill = fill or styles["th_fill"]
    for c_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=row_idx, column=c_idx, value=h)
        cell.font = styles["th_font"]
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = styles["thin_border"]
    ws.row_dimensions[row_idx].height = 24
    return row_idx + 1


def _write_approval_trail(ws, doc: Any, start_row: int, styles: Dict[str, Any]) -> int:
    trail = getattr(doc, "approval_trail", None) or []
    if not trail:
        return start_row

    r = start_row
    ws.cell(row=r, column=1, value="APPROVAL AUDIT TRAIL").font = styles["sec_font"]
    r += 1
    trail_headers = ["Level", "Action", "Action Taken By / Approver", "Timestamp", "Remarks / Notes"]
    r = _write_table_headers(ws, r, trail_headers, styles, fill=styles["trail_fill"])

    for tr in trail:
        lvl_str = f"Level {tr.level_number}" if getattr(tr, "level_number", None) else (getattr(tr, "level_name", None) or "")
        user_str = getattr(tr, "action_taken_by", None) or getattr(tr, "designated_approver", None) or ""
        action_str = getattr(tr, "action", None) or ""
        time_str = str(getattr(tr, "action_timestamp", None) or "")
        rem_str = getattr(tr, "remarks", None) or ""

        ws.cell(row=r, column=1, value=lvl_str).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=2, value=action_str).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=3, value=user_str)
        ws.cell(row=r, column=4, value=time_str).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=5, value=rem_str)
        for c in range(1, 6):
            ws.cell(row=r, column=c).border = styles["thin_border"]
        r += 1
    return r


def _auto_fit_columns(ws) -> None:
    for col in ws.columns:
        vals = [len(str(cell.value or "")) for cell in col if cell.row > 1]
        max_len = max(vals) if vals else 10
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(min(max_len + 4, 38), 12)


def _finalize_workbook_bytes(wb: openpyxl.Workbook) -> bytes:
    for sheet in wb.worksheets:
        _auto_fit_columns(sheet)
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()


def _stream_excel_response(wb: openpyxl.Workbook, filename: str) -> None:
    frappe.response["filename"] = filename
    frappe.response["filecontent"] = _finalize_workbook_bytes(wb)
    frappe.response["type"] = "binary"


@frappe.whitelist()
def download_voucher_excel(doctype: str = "Petty Cash Entry", docname: str = None, voucher_name: str = None):
    """
    Unified entry point for downloading voucher/statement Excel workbooks directly from desk action buttons.
    Supports both docname & voucher_name params across Petty Cash and Event DocTypes.
    """
    target_name = docname or voucher_name
    if not target_name:
        frappe.throw("Voucher name / Docname is required for Excel export.", frappe.ValidationError)

    exporters: Dict[str, Callable[[str], None]] = {
        "Petty Cash Entry": lambda dn: export_petty_cash_excel(voucher_name=dn),
        "Event Master": lambda dn: export_event_master_excel(event_name=dn),
        "Event Advance Request": lambda dn: export_event_advance_excel(advance_name=dn),
        "Event Expense Claim": lambda dn: export_event_expense_excel(claim_name=dn),
        "Event Settlement": lambda dn: export_event_settlement_excel(settlement_name=dn),
    }

    handler = exporters.get(doctype)
    if not handler:
        frappe.throw(f"Excel statement export is not supported for DocType '{doctype}'.", frappe.ValidationError)
    return handler(target_name)


def _assert_read_permission(doctype: str, docname: str, label: str) -> Any:
    if not docname:
        frappe.throw(f"{label} name is required for Excel export.", frappe.ValidationError)
    if not frappe.db.exists(doctype, docname):
        frappe.throw(f"{doctype} '{docname}' not found.", frappe.DoesNotExistError)
    if not frappe.has_permission(doctype, "read", docname):
        frappe.throw(f"You do not have permission to export this {label}.", frappe.PermissionError)
    return frappe.get_doc(doctype, docname)


@frappe.whitelist()
def export_petty_cash_excel(voucher_name: str = None, docname: str = None, doctype: str = None):
    """Generates and downloads a styled Excel workbook for a Petty Cash Voucher."""
    target_name = voucher_name or docname
    doc = _assert_read_permission("Petty Cash Entry", target_name, "Petty Cash Voucher")

    styles = _get_excel_palette()
    thin_border = styles["thin_border"]
    total_font = styles["total_font"]
    total_fill = styles["total_fill"]
    sec_font = styles["sec_font"]

    wb, ws = _init_workbook(
        sheet_title=f"Voucher {doc.name}",
        banner_text=f"PETTY CASH VOUCHER STATEMENT — {doc.name}",
        merge_range="A1:L1",
        styles=styles,
    )

    masked_acc = _mask_bank_account(getattr(doc, "custodian_bank_account", ""))
    meta = [
        ("Voucher ID:", doc.name, "Posting Date:", str(doc.posting_date or "")),
        ("Claim Title:", getattr(doc, "claim_title", None) or "N/A", "Workflow Status:", doc.status or "Draft"),
        ("Company:", doc.company or "N/A", "Payment Batch ID:", getattr(doc, "batch_id", None) or "N/A"),
        ("JV Number (Accounts):", getattr(doc, "jv_number", None) or "Pending Accounts Posting", "Total Amount (₹):", f"₹ {float(doc.total_amount or 0):,.2f}"),
        ("Beneficiary Employee:", getattr(doc, "custodian", None) or "N/A", "Beneficiary Name:", getattr(doc, "beneficiary_name", None) or "N/A"),
        ("Bank Name:", getattr(doc, "bank_name", None) or "N/A", "Bank A/C No:", masked_acc),
        ("Bank IFSC Code:", getattr(doc, "custodian_ifsc_code", None) or "N/A", "Generated On:", str(frappe.utils.today())),
    ]
    r = _write_meta_grid(ws, meta, start_row=3, styles=styles) + 1

    ws.cell(row=r, column=1, value="EXPENSE LINE ITEMS").font = sec_font
    r += 1

    headers = [
        "S.NO",
        "DATE",
        "BRANCH",
        "EXPENSES OF HEAD",
        "PARTICULARS (Merchant / Details)",
        "GST?",
        "MERCHANT GSTIN",
        "BILL # / TXN ID",
        "AMOUNT (₹)",
        "STAFF NAME",
        "RECEIPT",
        "REMARK",
        "DECISION",
    ]
    r = _write_table_headers(ws, r, headers, styles)

    start_line_r = r
    lines = doc.expense_lines or []
    category_summary: Dict[str, float] = {}
    for idx, line in enumerate(lines, 1):
        ws.cell(row=r, column=1, value=idx).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=2, value=str(getattr(line, "expense_date", None) or getattr(doc, "posting_date", "") or "")).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=3, value=getattr(line, "branch", "") or "Head Office").alignment = Alignment(horizontal="center")

        is_before_accounts = doc.status in ("Draft", "Pending Admin L1", "Pending Admin L2", "Rejected")
        raw_head = getattr(line, "expense_head", None)
        if raw_head == "OTHER / VENDOR LEDGER" and getattr(line, "custom_ledger_name", None):
            exp_head = getattr(line, "custom_ledger_name", "OTHER / VENDOR LEDGER")
        elif raw_head:
            exp_head = raw_head
        elif is_before_accounts:
            exp_head = "Pending Accounts Classification"
        else:
            exp_head = getattr(line, "expense_category", "") or "OFFICE EXPENSES"
        ws.cell(row=r, column=4, value=exp_head)
        ws.cell(row=r, column=5, value=getattr(line, "merchant_name", "") or "")

        is_gst = int(getattr(line, "is_gst", 0) or 0)
        ws.cell(row=r, column=6, value="Yes" if is_gst else "No").alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=7, value=getattr(line, "merchant_gstin", "") or "N/A").alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=8, value=getattr(line, "bill_number", "") or getattr(line, "transaction_id", "") or "N/A").alignment = Alignment(horizontal="center")

        line_amt = float(getattr(line, "amount", 0.0) or 0.0)
        amt_cell = ws.cell(row=r, column=9, value=line_amt)
        amt_cell.number_format = "₹ #,##0.00"
        amt_cell.alignment = Alignment(horizontal="right")
        category_summary[exp_head] = category_summary.get(exp_head, 0.0) + line_amt

        staff_disp = getattr(line, "staff_name", "") or getattr(line, "employee", "") or ""
        ws.cell(row=r, column=10, value=staff_disp).alignment = Alignment(horizontal="center")

        receipt_url = getattr(line, "receipt_attachment", None) or ""
        receipt_cell = ws.cell(row=r, column=11, value="View Receipt" if receipt_url else "No Receipt")
        if receipt_url:
            receipt_cell.hyperlink = receipt_url
            receipt_cell.font = styles["link_font"]
        receipt_cell.alignment = Alignment(horizontal="center")

        ws.cell(row=r, column=12, value=getattr(line, "remarks", "") or getattr(line, "description", "") or "BILL")

        if getattr(line, "is_disputed", 0):
            d_val = f"⚠️ Disputed: {getattr(line, 'dispute_reason', '') or 'Disputed'}"
            d_cell = ws.cell(row=r, column=13, value=d_val)
            d_cell.font = Font(name="Calibri", size=10, bold=True, color="B91C1C")
        else:
            d_cell = ws.cell(row=r, column=13, value="✅ OK / Approved")
            d_cell.font = Font(name="Calibri", size=10, color="15803D")
        d_cell.alignment = Alignment(horizontal="center")

        for c in range(1, 14):
            ws.cell(row=r, column=c).border = thin_border
        r += 1

    if lines:
        ws.cell(row=r, column=1, value="TOTAL").font = total_font
        ws.cell(row=r, column=1).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=1).fill = total_fill
        for c in range(2, 9):
            ws.cell(row=r, column=c).fill = total_fill

        tot_cell = ws.cell(row=r, column=9, value=f"=SUM(I{start_line_r}:I{r-1})")
        tot_cell.font = total_font
        tot_cell.fill = total_fill
        tot_cell.number_format = "₹ #,##0.00"
        tot_cell.alignment = Alignment(horizontal="right")

        for c in range(10, 14):
            ws.cell(row=r, column=c).fill = total_fill
        for c in range(1, 14):
            ws.cell(row=r, column=c).border = thin_border
        r += 2

        pivot_head_fill = styles["pivot_head_fill"]
        ws.cell(row=r, column=2, value="ACCOUNTS LEDGER SUMMARY (EXPENSES OF HEAD)").font = sec_font
        r += 1

        jv_val = getattr(doc, "jv_number", None) or "JV Pending"
        post_date_str = str(doc.posting_date or frappe.utils.today())

        for col_idx, label, align, clr in [
            (2, "Row Labels", "left", "0F172A"),
            (3, "Sum of AMOUNT", "right", "0F172A"),
            (4, jv_val, "center", "1E3A8A"),
            (5, post_date_str, "center", "0F172A"),
        ]:
            c = ws.cell(row=r, column=col_idx, value=label)
            c.font = Font(name="Calibri", size=10, bold=True, color=clr)
            c.fill = pivot_head_fill
            c.alignment = Alignment(horizontal=align)
            c.border = thin_border
        r += 1

        pivot_start_r = r
        for cat_label, cat_amt in sorted(category_summary.items()):
            ws.cell(row=r, column=2, value=cat_label).border = thin_border
            p_cell = ws.cell(row=r, column=3, value=cat_amt)
            p_cell.number_format = "₹ #,##0.00"
            p_cell.alignment = Alignment(horizontal="right")
            p_cell.border = thin_border
            ws.cell(row=r, column=4, value="").border = thin_border
            ws.cell(row=r, column=5, value="").border = thin_border
            r += 1

        ws.cell(row=r, column=2, value="Grand Total").font = total_font
        ws.cell(row=r, column=2).fill = total_fill
        ws.cell(row=r, column=2).border = thin_border

        p_tot_cell = ws.cell(row=r, column=3, value=f"=SUM(C{pivot_start_r}:C{r-1})")
        p_tot_cell.font = total_font
        p_tot_cell.fill = total_fill
        p_tot_cell.number_format = "₹ #,##0.00"
        p_tot_cell.alignment = Alignment(horizontal="right")
        p_tot_cell.border = thin_border

        for col_idx in (4, 5):
            ws.cell(row=r, column=col_idx, value="").fill = total_fill
            ws.cell(row=r, column=col_idx).border = thin_border
        r += 2

    _write_approval_trail(ws, doc, r, styles)
    _stream_excel_response(wb, f"Petty_Cash_{doc.name}.xlsx")


def _write_category_pivot(ws, start_row: int, title: str, summary: Dict[str, float], styles: Dict[str, Any]) -> int:
    if not summary:
        return start_row
    r = start_row
    thin_border = styles["thin_border"]
    total_fill = styles["total_fill"]
    total_font = styles["total_font"]

    ws.cell(row=r, column=2, value=title).font = styles["sec_font"]
    r += 1

    for col_idx, label, align in [(2, "Category / Head", "left"), (3, "Sum of Amount (₹)", "right")]:
        c = ws.cell(row=r, column=col_idx, value=label)
        c.font = Font(name="Calibri", size=10, bold=True, color="0F172A")
        c.fill = styles["pivot_head_fill"]
        c.alignment = Alignment(horizontal=align)
        c.border = thin_border
    r += 1

    pivot_start = r
    for cat_label, amt in sorted(summary.items()):
        ws.cell(row=r, column=2, value=cat_label).border = thin_border
        val_cell = ws.cell(row=r, column=3, value=amt)
        val_cell.number_format = "₹ #,##0.00"
        val_cell.alignment = Alignment(horizontal="right")
        val_cell.border = thin_border
        r += 1

    ws.cell(row=r, column=2, value="Grand Total").font = total_font
    ws.cell(row=r, column=2).fill = total_fill
    ws.cell(row=r, column=2).border = thin_border

    tot_cell = ws.cell(row=r, column=3, value=f"=SUM(C{pivot_start}:C{r-1})")
    tot_cell.font = total_font
    tot_cell.fill = total_fill
    tot_cell.number_format = "₹ #,##0.00"
    tot_cell.alignment = Alignment(horizontal="right")
    tot_cell.border = thin_border
    return r + 2


def _populate_event_advance_sheet(ws, doc: Any, styles: Dict[str, Any], event_title: str = "") -> None:
    thin_border = styles["thin_border"]
    total_font = styles["total_font"]
    total_fill = styles["total_fill"]

    meta = [
        ("Advance Request ID:", doc.name, "Status:", doc.status or "Draft"),
        ("Linked Event:", f"{doc.event} ({event_title})" if event_title else (doc.event or "N/A"), "Event Date:", str(getattr(doc, "event_date", "") or "")),
        ("Company:", doc.company or "N/A", "Event Venue:", getattr(doc, "venue", None) or "N/A"),
        ("Event SPOC:", doc.spoc_name or doc.spoc or "N/A", "Contact Phone:", getattr(doc, "contact_phone", None) or "N/A"),
        ("Direct Vendor Total (₹):", f"₹ {float(getattr(doc, 'total_direct_vendor_amount', 0) or 0):,.2f}", "Cash Imprest Total (₹):", f"₹ {float(getattr(doc, 'total_cash_imprest_amount', 0) or 0):,.2f}"),
        ("Requested Advance (₹):", f"₹ {float(getattr(doc, 'requested_advance_amount', 0) or 0):,.2f}", "Approved Advance (₹):", f"₹ {float(getattr(doc, 'approved_advance_amount', 0) or 0):,.2f}"),
        ("Approved By (Director):", getattr(doc, "approved_by_business_head", None) or "Pending", "Verified By (Accounts L1):", getattr(doc, "accounts_l1_verifier", None) or "Pending"),
        ("Accounts Director:", getattr(doc, "accounts_director", None) or "Pending", "Bank UTR / Ref:", getattr(doc, "disbursement_reference", None) or getattr(doc, "utr", None) or "Pending"),
        ("SPOC Bank Name:", getattr(doc, "bank_name", None) or "N/A", "SPOC Bank A/C & IFSC:", f"{_mask_bank_account(getattr(doc, 'bank_account_number', ''))} | {getattr(doc, 'bank_ifsc_code', None) or 'N/A'}"),
    ]
    r = _write_meta_grid(ws, meta, start_row=3, styles=styles) + 1

    ws.cell(row=r, column=1, value="ITEMIZED IMPREST PROPOSAL").font = styles["sec_font"]
    r += 1
    headers = [
        "S.NO",
        "PARTICULARS / PURPOSE",
        "PAYMENT MODE",
        "BENEFICIARY / PAYEE",
        "BANK NAME",
        "BANK A/C NO",
        "IFSC CODE",
        "AMOUNT (₹)",
        "QUOTE / PROOF",
        "REMARKS",
    ]
    r = _write_table_headers(ws, r, headers, styles)

    start_r = r
    items = getattr(doc, "imprest_items", None) or []
    mode_summary: Dict[str, float] = {}
    for idx, row in enumerate(items, 1):
        mode = getattr(row, "payment_mode", "") or "On-Ground Cash Imprest"
        amt = float(getattr(row, "amount", 0.0) or 0.0)
        mode_summary[mode] = mode_summary.get(mode, 0.0) + amt

        ws.cell(row=r, column=1, value=idx).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=2, value=getattr(row, "particulars", "") or "")
        ws.cell(row=r, column=3, value=mode).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=4, value=getattr(row, "beneficiary_name", "") or "")
        ws.cell(row=r, column=5, value=getattr(row, "bank_name", "") or "N/A")
        ws.cell(row=r, column=6, value=_mask_bank_account(getattr(row, "bank_account_number", ""))).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=7, value=getattr(row, "bank_ifsc_code", "") or "N/A").alignment = Alignment(horizontal="center")

        amt_cell = ws.cell(row=r, column=8, value=amt)
        amt_cell.number_format = "₹ #,##0.00"
        amt_cell.alignment = Alignment(horizontal="right")

        quote_url = getattr(row, "quote_attachment", None) or ""
        q_cell = ws.cell(row=r, column=9, value="View Quote" if quote_url else "No Attachment")
        if quote_url:
            q_cell.hyperlink = quote_url
            q_cell.font = styles["link_font"]
        q_cell.alignment = Alignment(horizontal="center")

        ws.cell(row=r, column=10, value=getattr(row, "remarks", "") or "")
        for c in range(1, 11):
            ws.cell(row=r, column=c).border = thin_border
        r += 1

    if items:
        ws.cell(row=r, column=1, value="TOTAL").font = total_font
        ws.cell(row=r, column=1).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=1).fill = total_fill
        for c in range(2, 8):
            ws.cell(row=r, column=c).fill = total_fill
        tot_cell = ws.cell(row=r, column=8, value=f"=SUM(H{start_r}:H{r-1})")
        tot_cell.font = total_font
        tot_cell.fill = total_fill
        tot_cell.number_format = "₹ #,##0.00"
        tot_cell.alignment = Alignment(horizontal="right")
        for c in (9, 10):
            ws.cell(row=r, column=c).fill = total_fill
        for c in range(1, 11):
            ws.cell(row=r, column=c).border = thin_border
        r += 2
        r = _write_category_pivot(ws, r, "PAYMENT MODE BREAKDOWN", mode_summary, styles)

    _write_approval_trail(ws, doc, r, styles)


@frappe.whitelist()
def export_event_advance_excel(advance_name: str = None, docname: str = None):
    """Generates and downloads an Excel statement workbook for an Event Advance Request."""
    target = advance_name or docname
    doc = _assert_read_permission("Event Advance Request", target, "Event Advance Request")
    styles = _get_excel_palette()
    wb, ws = _init_workbook(
        sheet_title=f"Advance {doc.name}",
        banner_text=f"EVENT IMPREST ADVANCE REQUEST STATEMENT — {doc.name}",
        merge_range="A1:J1",
        styles=styles,
    )
    event_title = frappe.db.get_value("Event Master", doc.event, "event_name") if doc.event else ""
    _populate_event_advance_sheet(ws, doc, styles, event_title=event_title or "")
    _stream_excel_response(wb, f"Event_Advance_{doc.name}.xlsx")


def _populate_event_expense_sheet(ws, doc: Any, styles: Dict[str, Any], event_title: str = "") -> None:
    thin_border = styles["thin_border"]
    total_font = styles["total_font"]
    total_fill = styles["total_fill"]

    meta = [
        ("Expense Claim ID:", doc.name, "Status:", doc.status or "Draft"),
        ("Linked Event:", f"{doc.event} ({event_title})" if event_title else (doc.event or "N/A"), "Claim Date:", str(getattr(doc, "posting_date", "") or "")),
        ("Company:", doc.company or "N/A", "Event SPOC:", doc.spoc_name or doc.spoc or "N/A"),
        ("Total Claim Amount (₹):", f"₹ {float(getattr(doc, 'total_claim_amount', 0) or 0):,.2f}", "Generated On:", str(frappe.utils.today())),
    ]
    r = _write_meta_grid(ws, meta, start_row=3, styles=styles) + 1

    ws.cell(row=r, column=1, value="ITEMIZED GROUND EXPENSE BILLS (STREAM B)").font = styles["sec_font"]
    r += 1
    headers = [
        "S.NO",
        "BILL DATE",
        "SPEND STREAM",
        "EXPENSE CATEGORY",
        "VENDOR / PAYEE NAME",
        "VENDOR GSTIN",
        "BILL # / RECEIPT #",
        "AMOUNT (₹)",
        "RECEIPT PROOF",
        "LINE STATUS",
        "DISPUTE REASON",
    ]
    r = _write_table_headers(ws, r, headers, styles)

    start_r = r
    items = getattr(doc, "expense_items", None) or []
    cat_summary: Dict[str, float] = {}
    for idx, row in enumerate(items, 1):
        cat = getattr(row, "expense_category", "") or "Incidentals"
        amt = float(getattr(row, "amount", 0.0) or 0.0)
        cat_summary[cat] = cat_summary.get(cat, 0.0) + amt

        ws.cell(row=r, column=1, value=idx).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=2, value=str(getattr(row, "bill_date", "") or doc.posting_date or "")).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=3, value=getattr(row, "spend_stream", "") or "SPOC On-Ground Cash Spend")
        ws.cell(row=r, column=4, value=cat)
        ws.cell(row=r, column=5, value=getattr(row, "vendor_name", "") or "")
        ws.cell(row=r, column=6, value=getattr(row, "tax_id", "") or "N/A").alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=7, value=getattr(row, "bill_number", "") or "N/A").alignment = Alignment(horizontal="center")

        amt_cell = ws.cell(row=r, column=8, value=amt)
        amt_cell.number_format = "₹ #,##0.00"
        amt_cell.alignment = Alignment(horizontal="right")

        rec_url = getattr(row, "receipt_attachment", None) or ""
        rec_cell = ws.cell(row=r, column=9, value="View Receipt" if rec_url else "No Receipt")
        if rec_url:
            rec_cell.hyperlink = rec_url
            rec_cell.font = styles["link_font"]
        rec_cell.alignment = Alignment(horizontal="center")

        line_st = getattr(row, "line_status", "") or ("Disputed" if getattr(row, "is_disputed", 0) else "Verified")
        ws.cell(row=r, column=10, value=line_st).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=11, value=getattr(row, "dispute_reason", "") or "")
        for c in range(1, 12):
            ws.cell(row=r, column=c).border = thin_border
        r += 1

    if items:
        ws.cell(row=r, column=1, value="TOTAL").font = total_font
        ws.cell(row=r, column=1).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=1).fill = total_fill
        for c in range(2, 8):
            ws.cell(row=r, column=c).fill = total_fill
        tot_cell = ws.cell(row=r, column=8, value=f"=SUM(H{start_r}:H{r-1})")
        tot_cell.font = total_font
        tot_cell.fill = total_fill
        tot_cell.number_format = "₹ #,##0.00"
        tot_cell.alignment = Alignment(horizontal="right")
        for c in range(9, 12):
            ws.cell(row=r, column=c).fill = total_fill
        for c in range(1, 12):
            ws.cell(row=r, column=c).border = thin_border
        r += 2
        r = _write_category_pivot(ws, r, "EXPENSE CATEGORY SUMMARY", cat_summary, styles)

    # Advance & Settlement Delta Reconciliation Block
    ws.cell(row=r, column=1, value="ADVANCE RECONCILIATION & SETTLEMENT VERDICT").font = styles["sec_font"]
    r += 1
    r = _write_table_headers(ws, r, ["RECONCILIATION METRIC", "VALUE / AMOUNT (₹)", "NOTES"], styles)
    s_type = getattr(doc, "settlement_type", None) or "N/A"
    recon_rows = [
        ("Total Cash Advance Disbursed", float(getattr(doc, "disbursed_advance", 0.0) or 0.0), "Disbursed Event Advance Requests"),
        ("Prior Verified Claim Spends", float(getattr(doc, "prior_verified_claims", 0.0) or 0.0), "Earlier submitted claims for this Event"),
        ("Current Claimed Ground Spends", float(getattr(doc, "total_claim_amount", 0.0) or 0.0), "Zero-Spend Refund Mode" if getattr(doc, "is_zero_spend_refund", 0) else "Bills on this voucher"),
        ("Cumulative SPOC Ground Spends", float(getattr(doc, "cumulative_spoc_spends", 0.0) or getattr(doc, "total_claim_amount", 0.0) or 0.0), "Cumulative Event actuals"),
        ("Net Settlement Delta (Actuals - Advance)", float(getattr(doc, "settlement_delta", 0.0) or 0.0), s_type),
        ("Net Payable to SPOC", float(getattr(doc, "net_payable_to_spoc", 0.0) or 0.0), "IDFC Payout Reference: " + (getattr(doc, "payout_utr_reference", None) or "Pending")),
        ("Refund Receivable from SPOC", float(getattr(doc, "refund_receivable_from_spoc", 0.0) or 0.0), "Bank Refund UTR: " + (getattr(doc, "refund_received_reference", None) or "Pending")),
    ]
    for lbl, val, note in recon_rows:
        ws.cell(row=r, column=1, value=lbl).font = styles["meta_label_font"]
        c_v = ws.cell(row=r, column=2, value=val)
        c_v.number_format = "₹ #,##0.00"
        c_v.alignment = Alignment(horizontal="right")
        c_v.font = total_font
        ws.cell(row=r, column=3, value=note)
        for c in range(1, 4):
            ws.cell(row=r, column=c).border = thin_border
        r += 1
    r += 1

    _write_approval_trail(ws, doc, r, styles)


@frappe.whitelist()
def export_event_expense_excel(claim_name: str = None, docname: str = None):
    """Generates and downloads an Excel statement workbook for an Event Expense Claim."""
    target = claim_name or docname
    doc = _assert_read_permission("Event Expense Claim", target, "Event Expense Claim")
    styles = _get_excel_palette()
    wb, ws = _init_workbook(
        sheet_title=f"Claim {doc.name}",
        banner_text=f"EVENT EXPENSE CLAIM STATEMENT — {doc.name}",
        merge_range="A1:K1",
        styles=styles,
    )
    event_title = frappe.db.get_value("Event Master", doc.event, "event_name") if doc.event else ""
    _populate_event_expense_sheet(ws, doc, styles, event_title=event_title or "")
    _stream_excel_response(wb, f"Event_Expense_Claim_{doc.name}.xlsx")


@frappe.whitelist()
def export_event_settlement_excel(settlement_name: str = None, docname: str = None):
    """Generates and downloads a reconciliation Excel workbook for an Event Settlement."""
    target = settlement_name or docname
    doc = _assert_read_permission("Event Settlement", target, "Event Settlement")
    styles = _get_excel_palette()
    thin_border = styles["thin_border"]

    wb, ws = _init_workbook(
        sheet_title=f"Settlement {doc.name}",
        banner_text=f"POST-EVENT FINANCIAL SETTLEMENT STATEMENT — {doc.name}",
        merge_range="A1:G1",
        styles=styles,
    )
    event_title = frappe.db.get_value("Event Master", doc.event, "event_name") if doc.event else ""

    meta = [
        ("Settlement ID:", doc.name, "Status:", doc.status or "Draft"),
        ("Linked Event:", f"{doc.event} ({event_title})" if event_title else (doc.event or "N/A"), "Settlement Date:", str(getattr(doc, "settlement_date", "") or "")),
        ("Company:", doc.company or "N/A", "Event Concluded Date:", str(getattr(doc, "event_end_date", "") or "")),
        ("Event SPOC:", doc.spoc_name or doc.spoc or "N/A", "Settlement Type:", getattr(doc, "settlement_type", "") or "N/A"),
        ("Accounts Director:", getattr(doc, "accounts_director", None) or "Pending", "Payment Releaser:", getattr(doc, "payment_releaser", None) or "N/A"),
        ("Bank Refund / Disbursal UTR:", getattr(doc, "refund_received_reference", None) or "Pending", "Refund / Payout Date:", str(getattr(doc, "refund_date", "") or "N/A")),
    ]
    r = _write_meta_grid(ws, meta, start_row=3, styles=styles) + 1

    ws.cell(row=r, column=1, value="SETTLEMENT DELTA RECONCILIATION").font = styles["sec_font"]
    r += 1
    r = _write_table_headers(ws, r, ["METRIC", "AMOUNT (₹)", "NOTES"], styles)

    math_rows = [
        ("Total Advance Disbursed (INR)", float(getattr(doc, "disbursed_advance", 0) or 0), "Sum of Disbursed Event Advance Requests"),
        ("Total SPOC Actual Spends (INR)", float(getattr(doc, "spoc_actual_spends", 0) or 0), "Sum of Submitted / Verified Ground Expense Claims"),
        ("Settlement Delta (Actual - Advance)", float(getattr(doc, "settlement_delta", 0) or 0), doc.settlement_type or ""),
        ("Net Payable to SPOC (INR)", float(getattr(doc, "net_payable_to_spoc", 0) or 0), "Reimbursable via IDFC if Delta > 0"),
        ("Refund Receivable from SPOC (INR)", float(getattr(doc, "refund_receivable_from_spoc", 0) or 0), "Returned by SPOC via UTR if Delta < 0"),
    ]
    for label, val, note in math_rows:
        ws.cell(row=r, column=1, value=label).font = styles["meta_label_font"]
        c_val = ws.cell(row=r, column=2, value=val)
        c_val.number_format = "₹ #,##0.00"
        c_val.alignment = Alignment(horizontal="right")
        c_val.font = styles["total_font"]
        ws.cell(row=r, column=3, value=note)
        for c in range(1, 4):
            ws.cell(row=r, column=c).border = thin_border
        r += 1

    r += 1
    if doc.event:
        claims = frappe.get_all(
            "Event Expense Claim",
            filters={"event": doc.event, "docstatus": 1},
            fields=["name", "posting_date", "total_claim_amount", "status"],
            order_by="posting_date asc",
        )
        if claims:
            ws.cell(row=r, column=1, value="LINKED GROUND EXPENSE CLAIMS").font = styles["sec_font"]
            r += 1
            r = _write_table_headers(ws, r, ["Claim ID", "Claim Date", "Status", "Total Amount (₹)"], styles)
            c_start = r
            for cl in claims:
                if not frappe.has_permission("Event Expense Claim", "read", cl["name"]):
                    continue
                ws.cell(row=r, column=1, value=cl["name"])
                ws.cell(row=r, column=2, value=str(cl["posting_date"] or "")).alignment = Alignment(horizontal="center")
                ws.cell(row=r, column=3, value=cl["status"] or "").alignment = Alignment(horizontal="center")
                amt_c = ws.cell(row=r, column=4, value=float(cl["total_claim_amount"] or 0))
                amt_c.number_format = "₹ #,##0.00"
                amt_c.alignment = Alignment(horizontal="right")
                for c in range(1, 5):
                    ws.cell(row=r, column=c).border = thin_border
                r += 1
            if r > c_start:
                ws.cell(row=r, column=1, value="TOTAL").font = styles["total_font"]
                for c in (1, 2, 3):
                    ws.cell(row=r, column=c).fill = styles["total_fill"]
                tot_c = ws.cell(row=r, column=4, value=f"=SUM(D{c_start}:D{r-1})")
                tot_c.font = styles["total_font"]
                tot_c.fill = styles["total_fill"]
                tot_c.number_format = "₹ #,##0.00"
                tot_c.alignment = Alignment(horizontal="right")
                for c in range(1, 5):
                    ws.cell(row=r, column=c).border = thin_border
                r += 2

    _write_approval_trail(ws, doc, r, styles)
    _stream_excel_response(wb, f"Event_Settlement_{doc.name}.xlsx")


@frappe.whitelist()
def export_event_master_excel(event_name: str = None, docname: str = None):
    """Generates a multi-sheet consolidated audit workbook for an Event Master."""
    target = event_name or docname
    doc = _assert_read_permission("Event Master", target, "Event Master")
    styles = _get_excel_palette()
    thin_border = styles["thin_border"]

    wb, ws = _init_workbook(
        sheet_title="Event Budget Ledger",
        banner_text=f"CONSOLIDATED EVENT BUDGET & SPEND LEDGER — {doc.event_name or doc.name}",
        merge_range="A1:H1",
        styles=styles,
    )

    meta = [
        ("Event ID:", doc.name, "Status:", doc.status or "Planning"),
        ("Event Title:", doc.event_name or doc.name, "Company:", doc.company or "N/A"),
        ("Event SPOC:", doc.spoc_name or doc.event_spoc or "N/A", "Venue:", getattr(doc, "event_location", None) or "N/A"),
        ("Start Date:", str(getattr(doc, "start_date", "") or ""), "End Date:", str(getattr(doc, "end_date", "") or "")),
        ("Overrun Status:", getattr(doc, "budget_overrun_status", None) or "WITHIN_BUDGET", "Utilization %:", f"{float(getattr(doc, 'budget_utilization_pct', 0) or 0):.1f}%"),
    ]
    r = _write_meta_grid(ws, meta, start_row=3, styles=styles) + 1

    ws.cell(row=r, column=1, value="BUDGET VS COMMITTED SPEND SUMMARY").font = styles["sec_font"]
    r += 1
    r = _write_table_headers(ws, r, ["KPI Metric", "Amount (₹)", "Formula / Notes"], styles)
    kpis = [
        ("Board Approved Budget", float(getattr(doc, "allocated_budget", 0) or 0), "Total sanctioned ceiling"),
        ("Stream A: Direct Finance Vendor Spends", float(getattr(doc, "direct_finance_spends", 0) or 0), "Vendor Invoice Claims linked to Event"),
        ("Disbursed SPOC Advances", float(getattr(doc, "disbursed_advance", 0) or 0), "Disbursed Event Advance Requests"),
        ("Stream B: SPOC Actual Ground Spends", float(getattr(doc, "spoc_actual_spends", 0) or 0), "Submitted Event Expense Claims"),
        ("Total Committed Spend", float(getattr(doc, "total_committed_spend", 0) or 0), "Stream A + max(Disbursed Advance, Ground Spends)"),
        ("Remaining Uncommitted Budget", float(getattr(doc, "remaining_budget", 0) or 0), "Board Budget - Total Committed"),
    ]
    for lbl, val, note in kpis:
        ws.cell(row=r, column=1, value=lbl).font = styles["meta_label_font"]
        c_val = ws.cell(row=r, column=2, value=val)
        c_val.number_format = "₹ #,##0.00"
        c_val.alignment = Alignment(horizontal="right")
        c_val.font = styles["total_font"]
        ws.cell(row=r, column=3, value=note)
        for c in range(1, 4):
            ws.cell(row=r, column=c).border = thin_border
        r += 1

    # Sheet 2: Stream B Advance Requests
    ws_adv = wb.create_sheet("Stream B Advances")
    ws_adv.merge_cells("A1:I1")
    ws_adv["A1"] = f"EVENT IMPREST ADVANCE REQUESTS — {doc.name}"
    ws_adv["A1"].font = styles["title_font"]
    ws_adv.row_dimensions[1].height = 26
    ar = _write_table_headers(
        ws_adv,
        3,
        ["Advance ID", "Particulars", "Payment Mode", "Beneficiary", "Requested (₹)", "Approved (₹)", "Status", "Bank UTR", "Quote"],
        styles,
    )
    advances = frappe.get_all(
        "Event Advance Request",
        filters={"event": doc.name, "docstatus": ["!=", 2]},
        pluck="name",
        order_by="creation asc",
    )
    for adv_name in advances:
        if not frappe.has_permission("Event Advance Request", "read", adv_name):
            continue
        adv_doc = frappe.get_doc("Event Advance Request", adv_name)
        for row in getattr(adv_doc, "imprest_items", None) or [None]:
            ws_adv.cell(row=ar, column=1, value=adv_doc.name)
            ws_adv.cell(row=ar, column=2, value=getattr(row, "particulars", "") if row else (adv_doc.purpose or ""))
            ws_adv.cell(row=ar, column=3, value=getattr(row, "payment_mode", "") if row else "")
            ws_adv.cell(row=ar, column=4, value=getattr(row, "beneficiary_name", "") if row else (adv_doc.spoc_name or ""))
            req_val = float(getattr(row, "amount", 0) if row else (adv_doc.requested_advance_amount or 0))
            c_req = ws_adv.cell(row=ar, column=5, value=req_val)
            c_req.number_format = "₹ #,##0.00"
            c_req.alignment = Alignment(horizontal="right")
            c_app = ws_adv.cell(row=ar, column=6, value=float(adv_doc.approved_advance_amount or 0))
            c_app.number_format = "₹ #,##0.00"
            c_app.alignment = Alignment(horizontal="right")
            ws_adv.cell(row=ar, column=7, value=adv_doc.status or "").alignment = Alignment(horizontal="center")
            ws_adv.cell(row=ar, column=8, value=getattr(adv_doc, "disbursement_reference", "") or getattr(adv_doc, "utr", "") or "")
            q_url = getattr(row, "quote_attachment", "") if row else ""
            q_c = ws_adv.cell(row=ar, column=9, value="View Quote" if q_url else "N/A")
            if q_url:
                q_c.hyperlink = q_url
                q_c.font = styles["link_font"]
            for c in range(1, 10):
                ws_adv.cell(row=ar, column=c).border = thin_border
            ar += 1

    # Sheet 3: Stream B Ground Expense Claims
    ws_clm = wb.create_sheet("Stream B Ground Claims")
    ws_clm.merge_cells("A1:I1")
    ws_clm["A1"] = f"EVENT ON-GROUND EXPENSE CLAIMS — {doc.name}"
    ws_clm["A1"].font = styles["title_font"]
    ws_clm.row_dimensions[1].height = 26
    cr = _write_table_headers(
        ws_clm,
        3,
        ["Claim ID", "Claim Date", "Category", "Vendor / Payee", "Bill #", "GSTIN", "Amount (₹)", "Claim Status", "Receipt"],
        styles,
    )
    claims = frappe.get_all(
        "Event Expense Claim",
        filters={"event": doc.name, "docstatus": ["!=", 2]},
        pluck="name",
        order_by="creation asc",
    )
    cat_totals: Dict[str, float] = {}
    c_start = cr
    for clm_name in claims:
        if not frappe.has_permission("Event Expense Claim", "read", clm_name):
            continue
        clm_doc = frappe.get_doc("Event Expense Claim", clm_name)
        for row in getattr(clm_doc, "expense_items", None) or []:
            cat = getattr(row, "expense_category", "") or "Incidentals"
            amt = float(getattr(row, "amount", 0) or 0)
            cat_totals[cat] = cat_totals.get(cat, 0.0) + amt
            ws_clm.cell(row=cr, column=1, value=clm_doc.name)
            ws_clm.cell(row=cr, column=2, value=str(getattr(row, "bill_date", "") or clm_doc.posting_date or "")).alignment = Alignment(horizontal="center")
            ws_clm.cell(row=cr, column=3, value=cat)
            ws_clm.cell(row=cr, column=4, value=getattr(row, "vendor_name", "") or "")
            ws_clm.cell(row=cr, column=5, value=getattr(row, "bill_number", "") or "").alignment = Alignment(horizontal="center")
            ws_clm.cell(row=cr, column=6, value=getattr(row, "tax_id", "") or "N/A").alignment = Alignment(horizontal="center")
            amt_c = ws_clm.cell(row=cr, column=7, value=amt)
            amt_c.number_format = "₹ #,##0.00"
            amt_c.alignment = Alignment(horizontal="right")
            ws_clm.cell(row=cr, column=8, value=clm_doc.status or "").alignment = Alignment(horizontal="center")
            r_url = getattr(row, "receipt_attachment", "") or ""
            r_c = ws_clm.cell(row=cr, column=9, value="View Receipt" if r_url else "N/A")
            if r_url:
                r_c.hyperlink = r_url
                r_c.font = styles["link_font"]
            for c in range(1, 10):
                ws_clm.cell(row=cr, column=c).border = thin_border
            cr += 1

    if cr > c_start:
        ws_clm.cell(row=cr, column=1, value="TOTAL").font = styles["total_font"]
        for c in range(1, 7):
            ws_clm.cell(row=cr, column=c).fill = styles["total_fill"]
        tot_c = ws_clm.cell(row=cr, column=7, value=f"=SUM(G{c_start}:G{cr-1})")
        tot_c.font = styles["total_font"]
        tot_c.fill = styles["total_fill"]
        tot_c.number_format = "₹ #,##0.00"
        tot_c.alignment = Alignment(horizontal="right")
        for c in (8, 9):
            ws_clm.cell(row=cr, column=c).fill = styles["total_fill"]
        for c in range(1, 10):
            ws_clm.cell(row=cr, column=c).border = thin_border
        _write_category_pivot(ws_clm, cr + 2, "GROUND CLAIM CATEGORY SUMMARY", cat_totals, styles)

    # Sheet 4: Stream A Direct Vendor Invoices
    ws_vinv = wb.create_sheet("Stream A Vendor Invoices")
    ws_vinv.merge_cells("A1:J1")
    ws_vinv["A1"] = f"STREAM A: DIRECT VENDOR INVOICES — {doc.name}"
    ws_vinv["A1"].font = styles["title_font"]
    ws_vinv.row_dimensions[1].height = 26
    vr = _write_table_headers(
        ws_vinv,
        3,
        ["Invoice Claim ID", "Vendor Name", "Tax Invoice #", "Invoice Date", "Base Taxable (₹)", "GST (₹)", "Total Invoice (₹)", "TDS (₹)", "Net Payable (₹)", "Status"],
        styles,
    )
    vinvs = frappe.get_all(
        "Vendor Invoice Claim",
        filters={"event": doc.name, "docstatus": ["!=", 2]},
        fields=[
            "name", "vendor_name", "vendor", "tax_invoice_number", "tax_invoice_date",
            "base_amount", "gst_amount", "total_invoice_amount", "tds_amount", "net_payable_amount", "status",
        ],
        order_by="creation asc",
    )
    for v in vinvs:
        if not frappe.has_permission("Vendor Invoice Claim", "read", v["name"]):
            continue
        ws_vinv.cell(row=vr, column=1, value=v["name"])
        ws_vinv.cell(row=vr, column=2, value=v.get("vendor_name") or v.get("vendor") or "")
        ws_vinv.cell(row=vr, column=3, value=v.get("tax_invoice_number") or "N/A").alignment = Alignment(horizontal="center")
        ws_vinv.cell(row=vr, column=4, value=str(v.get("tax_invoice_date") or "")).alignment = Alignment(horizontal="center")
        for col_idx, field_key in [
            (5, "base_amount"),
            (6, "gst_amount"),
            (7, "total_invoice_amount"),
            (8, "tds_amount"),
            (9, "net_payable_amount"),
        ]:
            c_amt = ws_vinv.cell(row=vr, column=col_idx, value=float(v.get(field_key) or 0))
            c_amt.number_format = "₹ #,##0.00"
            c_amt.alignment = Alignment(horizontal="right")
        ws_vinv.cell(row=vr, column=10, value=v.get("status") or "").alignment = Alignment(horizontal="center")
        for c in range(1, 11):
            ws_vinv.cell(row=vr, column=c).border = thin_border
        vr += 1

    _stream_excel_response(wb, f"Event_Ledger_{doc.name}.xlsx")
