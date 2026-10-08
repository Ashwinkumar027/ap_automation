import frappe

def fix_po_tokens():
    # Update PO-2026-10-01817 to match user's email link
    token = "LmOe1gePg5H73gIxDFkqSNOvmIHW9oQ1IfGZphKWo8o"
    url = f"http://hrms1.local:8000/po-sign?token={token}&po=PO-2026-10-01817"
    frappe.db.sql("""
        UPDATE `tabAP Purchase Order`
        SET vendor_sign_url = %s
        WHERE name = 'PO-2026-10-01817'
    """, (url,))
    frappe.db.commit()
    print("Fixed PO-2026-10-01817 sign URL to:", url)

if __name__ == "__main__":
    fix_po_tokens()
