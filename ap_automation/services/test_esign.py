import frappe
from ap_automation.www.po_sign import submit_vendor_esign
import urllib.parse

def test_esign_submission():
    po = frappe.get_doc("AP Purchase Order", "PO-2026-10-01817")
    print("PO vendor_sign_url:", po.vendor_sign_url)
    parsed = urllib.parse.urlparse(po.vendor_sign_url or "")
    token = urllib.parse.parse_qs(parsed.query).get("token", [None])[0]
    print("Extracted Token from PO:", token)

    res = submit_vendor_esign(
        po_name=po.name,
        token=token,
        signer_name="Ashwin Kumar",
        signer_designation="Director",
        signature_data="data:image/png;base64,mock_signature_data"
    )
    print("Result:", res)
    po.reload()
    print("Updated PO Status:", po.status, "Vendor Sign Status:", po.vendor_sign_status, "Signed By:", po.vendor_signed_by)

if __name__ == "__main__":
    test_esign_submission()
