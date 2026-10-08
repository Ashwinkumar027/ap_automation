import frappe

def inspect_po():
    po = frappe.get_doc("AP Purchase Order", "PO-2026-10-01817")
    print("vendor_sign_url:", repr(po.vendor_sign_url))
    print("vendor_sign_token:", repr(getattr(po, "vendor_sign_token", None)))

if __name__ == "__main__":
    inspect_po()
