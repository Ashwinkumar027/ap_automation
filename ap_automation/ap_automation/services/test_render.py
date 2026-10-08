import frappe
from ap_automation.www.po_sign import get_context

def test_render():
    pos = frappe.get_all("AP Purchase Order", fields=["name", "vendor_sign_url"], limit=3)
    print("Found POs in DB:", [p.name for p in pos])
    
    if pos:
        target_po = pos[0].name
        # extract token
        import urllib.parse
        parsed = urllib.parse.urlparse(pos[0].vendor_sign_url or "")
        token = urllib.parse.parse_qs(parsed.query).get("token", ["mock_token"])[0]
        
        frappe.form_dict.po = target_po
        frappe.form_dict.token = token
        ctx = frappe._dict()
        get_context(ctx)
        print("Valid Context loaded:", ctx.keys(), "is_signed:", ctx.get("is_signed"))
        res = frappe.render_template("ap_automation/www/po-sign.html", ctx)
        print("Rendered valid PO template successfully, length:", len(res))

    # Test error context
    frappe.form_dict.po = "NON-EXISTENT-PO"
    frappe.form_dict.token = "wrong_token"
    err_ctx = frappe._dict()
    get_context(err_ctx)
    print("Error Context loaded:", err_ctx.keys(), "error_msg:", err_ctx.get("error_message"))
    err_res = frappe.render_template("ap_automation/www/po-sign.html", err_ctx)
    print("Rendered error template successfully, length:", len(err_res))

if __name__ == "__main__":
    test_render()
