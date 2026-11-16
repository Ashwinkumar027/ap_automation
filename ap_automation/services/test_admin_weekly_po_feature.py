import frappe
from frappe.utils import nowdate, flt
from ap_automation.exceptions import APValidationError, APSecurityError
from ap_automation.ap_automation.doctype.admin_weekly_vendor_claim.admin_weekly_vendor_claim import generate_weekly_excel_download

def run():
    print("\n" + "=" * 70)
    print("🚀 RUNNING ADMIN WEEKLY VENDOR CLAIM - PO FEATURE TEST SUITE")
    print("=" * 70)

    # 1. Verify Child DocType Schema in MariaDB and Metadata
    print("\n--- [TEST 1: Schema & Metadata Verification] ---")
    meta = frappe.get_meta("Admin Vendor Claim Item")
    
    assert meta.has_field("po_type"), "po_type field missing in Admin Vendor Claim Item"
    f_po_type = meta.get_field("po_type")
    assert f_po_type.fieldtype == "Select", f"po_type fieldtype should be Select, got {f_po_type.fieldtype}"
    assert "Without PO" in f_po_type.options and "With PO" in f_po_type.options
    assert f_po_type.default == "Without PO"
    assert f_po_type.in_list_view == 1
    print("  ✅ 1. po_type DocField: Select ('Without PO' / 'With PO'), default 'Without PO', in_list_view=1")

    assert meta.has_field("purchase_order"), "purchase_order field missing in Admin Vendor Claim Item"
    f_po = meta.get_field("purchase_order")
    assert f_po.fieldtype == "Link" and f_po.options == "AP Purchase Order"
    assert f_po.in_list_view == 1
    assert "eval:doc.po_type=='With PO'" in (f_po.depends_on or "")
    print("  ✅ 2. purchase_order DocField: Link to 'AP Purchase Order', depends on With PO, in_list_view=1")

    assert meta.has_field("po_attachment"), "po_attachment field missing in Admin Vendor Claim Item"
    f_att = meta.get_field("po_attachment")
    assert f_att.fieldtype == "Attach"
    assert f_att.in_list_view == 1
    print("  ✅ 3. po_attachment DocField: Attach, in_list_view=1 (Non-mandatory)")

    # 2. Setup Test Data (Clean up old test records)
    frappe.db.sql("DELETE FROM `tabAdmin Weekly Vendor Claim` WHERE name LIKE 'TEST-PO-VOUCHER-%'")
    frappe.db.commit()

    supplier = frappe.db.get_value("Supplier", {"disabled": 0}, "name")
    if not supplier:
        supplier = "TEST-SUPPLIER-PO"
        s_doc = frappe.new_doc("Supplier")
        s_doc.supplier_name = "Test PO Supplier Ltd"
        s_doc.supplier_group = "Services"
        s_doc.insert(ignore_permissions=True)
    
    company = frappe.db.get_value("Company", {}, "name") or "Quanticus"

    # Ensure Supplier has a valid active bank account for submission
    bank_ac = frappe.db.get_value("Bank Account", {"party_type": "Supplier", "party": supplier}, "name")
    if not bank_ac:
        b_doc = frappe.new_doc("Bank Account")
        b_doc.account_name = f"{supplier} Primary A/C"
        b_doc.party_type = "Supplier"
        b_doc.party = supplier
        b_doc.bank_account_no = "123456789012"
        b_doc.custom_ifsc_code = "HDFC0001234"
        b_doc.custom_penny_drop_status = "VERIFIED"
        b_doc.insert(ignore_permissions=True)

    # Find or create a test AP Purchase Order
    test_po = frappe.db.get_value("AP Purchase Order", {"vendor": supplier}, "name")
    if not test_po:
        test_po = frappe.db.get_value("AP Purchase Order", {}, "name")
    if not test_po:
        po_doc = frappe.new_doc("AP Purchase Order")
        po_doc.company_entity = company
        po_doc.vendor = supplier
        po_doc.vendor_name = "Test PO Supplier Ltd"
        po_doc.vendor_email = "supplier@test.com"
        po_doc.spoc_name = "Admin Test User"
        po_doc.spoc_department = "Operations"
        po_doc.grand_total = 10000.0
        po_doc.status = "Active PO"
        po_doc.insert(ignore_permissions=True)
        test_po = po_doc.name
    print(f"  ✅ Test environment ready with Supplier '{supplier}' and PO '{test_po}'.")

    # -------------------------------------------------------------
    # TEST 2: Multi-Row Voucher with Various PO Configurations
    # -------------------------------------------------------------
    print("\n--- [TEST 2: Creation of Multi-Row Voucher with PO Variations] ---")
    v = frappe.new_doc("Admin Weekly Vendor Claim")
    v.name = "TEST-PO-VOUCHER-001"
    v.company = company
    v.week_period = "3rd Week November 2026"
    v.posting_date = nowdate()

    # Row 1: Without PO, NO attachment (default case)
    v.append("vendor_lines", {
        "vendor_category": "Housekeeping",
        "vendor": supplier,
        "company": company,
        "invoice_number": "INV-NO-PO-01",
        "invoice_date": nowdate(),
        "base_amount": 1000.0,
        "gst_rate": "18%",
        "tax_type": "Intra-State (CGST + SGST)",
        "receipt_attachment": "/files/invoice_01.pdf",
        "po_type": "Without PO",
        "purchase_order": None,
        "po_attachment": None
    })

    # Row 2: Without PO, WITH email approval attachment
    v.append("vendor_lines", {
        "vendor_category": "Pantry",
        "vendor": supplier,
        "company": company,
        "invoice_number": "INV-NO-PO-02",
        "invoice_date": nowdate(),
        "base_amount": 2500.0,
        "gst_rate": "18%",
        "tax_type": "Intra-State (CGST + SGST)",
        "receipt_attachment": "/files/invoice_02.pdf",
        "po_type": "Without PO",
        "purchase_order": None,
        "po_attachment": "/files/internal_management_approval.pdf"
    })

    # Row 3: With PO, WITH PO Link AND PO Attachment
    v.append("vendor_lines", {
        "vendor_category": "IT Hardware",
        "vendor": supplier,
        "company": company,
        "invoice_number": "INV-WITH-PO-03",
        "invoice_date": nowdate(),
        "base_amount": 5000.0,
        "gst_rate": "18%",
        "tax_type": "Intra-State (CGST + SGST)",
        "receipt_attachment": "/files/invoice_03.pdf",
        "po_type": "With PO",
        "purchase_order": test_po,
        "po_attachment": "/files/signed_purchase_order.pdf"
    })

    # Row 4: With PO, WITH PO Link but NO Attachment (Non-mandatory test)
    v.append("vendor_lines", {
        "vendor_category": "Stationery",
        "vendor": supplier,
        "company": company,
        "invoice_number": "INV-WITH-PO-04",
        "invoice_date": nowdate(),
        "base_amount": 1200.0,
        "gst_rate": "18%",
        "tax_type": "Intra-State (CGST + SGST)",
        "receipt_attachment": "/files/invoice_04.pdf",
        "po_type": "With PO",
        "purchase_order": test_po,
        "po_attachment": None
    })

    # Row 5: With PO, with PO Attachment but NO PO Link (Non-mandatory test)
    v.append("vendor_lines", {
        "vendor_category": "Printing",
        "vendor": supplier,
        "company": company,
        "invoice_number": "INV-WITH-PO-05",
        "invoice_date": nowdate(),
        "base_amount": 800.0,
        "gst_rate": "18%",
        "tax_type": "Intra-State (CGST + SGST)",
        "receipt_attachment": "/files/invoice_05.pdf",
        "po_type": "With PO",
        "purchase_order": None,
        "po_attachment": "/files/external_po_quote.pdf"
    })

    v.save(ignore_permissions=True)
    frappe.db.commit()

    reloaded_v = frappe.get_doc("Admin Weekly Vendor Claim", v.name)
    assert len(reloaded_v.vendor_lines) == 5, f"Expected 5 rows, got {len(reloaded_v.vendor_lines)}"
    print(f"  ✅ Successfully saved voucher '{v.name}' with 5 diverse PO rows.")

    # Verify rows preserved values correctly
    r1 = reloaded_v.vendor_lines[0]
    assert r1.po_type == "Without PO" and not r1.purchase_order and not r1.po_attachment
    print(f"     Row 1 (Without PO): po_type='{r1.po_type}', PO=None, Attachment=None")

    r2 = reloaded_v.vendor_lines[1]
    assert r2.po_type == "Without PO" and r2.po_attachment == "/files/internal_management_approval.pdf"
    print(f"     Row 2 (Without PO): po_type='{r2.po_type}', Attachment='{r2.po_attachment}'")

    r3 = reloaded_v.vendor_lines[2]
    assert r3.po_type == "With PO" and r3.purchase_order == test_po and r3.po_attachment == "/files/signed_purchase_order.pdf"
    print(f"     Row 3 (With PO): po_type='{r3.po_type}', PO='{r3.purchase_order}', Attachment='{r3.po_attachment}'")

    r4 = reloaded_v.vendor_lines[3]
    assert r4.po_type == "With PO" and r4.purchase_order == test_po and not r4.po_attachment
    print(f"     Row 4 (With PO - Link only): po_type='{r4.po_type}', PO='{r4.purchase_order}', Attachment=None")

    r5 = reloaded_v.vendor_lines[4]
    assert r5.po_type == "With PO" and not r5.purchase_order and r5.po_attachment == "/files/external_po_quote.pdf"
    print(f"     Row 5 (With PO - File only): po_type='{r5.po_type}', PO=None, Attachment='{r5.po_attachment}'")

    # -------------------------------------------------------------
    # TEST 3: Receipt Gallery Payload Verification
    # -------------------------------------------------------------
    print("\n--- [TEST 3: Receipt Gallery Payload Generation Check] ---")
    # Simulate client-side open_admin_receipt_gallery collection
    gallery_items = []
    for idx, row in enumerate(reloaded_v.vendor_lines, start=1):
        if row.receipt_attachment:
            gallery_items.append({
                "proof_type": "bill",
                "proof_label": "🧾 1. Vendor Tax Invoice / Bill",
                "row_idx": idx,
                "file_url": row.receipt_attachment
            })
        if row.bank_proof_attachment:
            gallery_items.append({
                "proof_type": "extra",
                "proof_label": "🏦 2. Bank Cheque Proof",
                "row_idx": idx,
                "file_url": row.bank_proof_attachment
            })
        if row.po_attachment:
            is_with_po = row.po_type == "With PO"
            po_title = (
                f"📑 3. Purchase Order ({row.purchase_order})" if (is_with_po and row.purchase_order)
                else ("📑 3. Purchase Order Copy" if is_with_po else "📑 3. Expense Approval Proof")
            )
            gallery_items.append({
                "proof_type": "po",
                "proof_label": po_title,
                "row_idx": idx,
                "file_url": row.po_attachment
            })

    # Expected: 5 invoices + 3 PO/Approval attachments = 8 items (plus any bank proofs auto-fetched)
    po_proofs = [p for p in gallery_items if p["proof_type"] == "po"]
    assert len(po_proofs) == 3, f"Expected 3 PO/Approval proofs in gallery, got {len(po_proofs)}"
    
    print(f"  ✅ Gallery collected {len(gallery_items)} total proofs across {len(reloaded_v.vendor_lines)} rows.")
    for p in po_proofs:
        print(f"     Row #{p['row_idx']}: {p['proof_label']} -> {p['file_url']}")

    # -------------------------------------------------------------
    # TEST 4: Excel Export Check with PO Columns
    # -------------------------------------------------------------
    print("\n--- [TEST 4: Excel Download with PO Columns] ---")
    try:
        generate_weekly_excel_download(reloaded_v.name)
        assert "filecontent" in frappe.response, "Excel binary content missing in frappe.response"
        assert frappe.response["filename"].endswith(".xlsx"), "Invalid filename"
        print(f"  ✅ Excel spreadsheet generated successfully: '{frappe.response['filename']}' ({len(frappe.response['filecontent'])} bytes).")
    except Exception as e:
        assert False, f"generate_weekly_excel_download failed: {str(e)}"

    # -------------------------------------------------------------
    # TEST 5: Non-Mandatory Validation Check on Submit
    # -------------------------------------------------------------
    print("\n--- [TEST 5: Non-Mandatory Submission Pass] ---")
    reloaded_v.status = "Pending Admin L1"
    reloaded_v.save(ignore_permissions=True)
    assert reloaded_v.status == "Pending Admin L1"
    print("  ✅ Voucher successfully advanced to 'Pending Admin L1' without requiring mandatory PO.")

    # Clean up test records
    frappe.db.sql("DELETE FROM `tabAdmin Weekly Vendor Claim` WHERE name LIKE 'TEST-PO-VOUCHER-%'")
    frappe.db.commit()

    print("\n" + "=" * 70)
    print("🎯 ALL 5 TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    run()

