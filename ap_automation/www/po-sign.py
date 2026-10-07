# Copyright (c) 2026, Quanti and contributors
import urllib.parse
import frappe

no_cache = 1

def normalize_token(t: str) -> str:
    if not t:
        return ""
    return str(t).strip().replace("I", "l").replace("1", "l").lower()

def is_token_matching(stored_token: str, input_token: str) -> bool:
    if not stored_token or not input_token:
        return False
    s = str(stored_token).strip()
    i = str(input_token).strip()
    if s == i:
        return True
    return normalize_token(s) == normalize_token(i)

def get_context(context):
    po_name = frappe.form_dict.get("po") or frappe.form_dict.get("name")
    token = frappe.form_dict.get("token")

    context.no_cache = 1
    context.show_sidebar = False
    context.title = "Purchase Order Digital Signature Portal"
    context.csrf_token = frappe.session.csrf_token if hasattr(frappe, "session") else ""

    if not po_name or not token:
        context.error_message = "Invalid link parameters. Purchase Order # and Token are required."
        return context

    if not frappe.db.exists("AP Purchase Order", po_name):
        context.error_message = f"Purchase Order '{po_name}' does not exist in the system."
        return context

    po = frappe.get_doc("AP Purchase Order", po_name)

    token_in_doc = getattr(po, "vendor_sign_token", None)
    if not token_in_doc and getattr(po, "vendor_sign_url", None):
        parsed = urllib.parse.urlparse(po.vendor_sign_url)
        params = urllib.parse.parse_qs(parsed.query)
        token_in_doc = params.get("token", [None])[0]

    if token_in_doc and not is_token_matching(token_in_doc, token):
        context.error_message = "Security token mismatch or link has expired. Please contact the company SPOC for a refreshed link."
        return context

    context.po = po
    context.items = po.items or []
    context.is_signed = po.vendor_sign_status == "Digitally Signed"
    return context


@frappe.whitelist(allow_guest=True)
def submit_vendor_esign(po_name: str = None, token: str = None, signer_name: str = None, signer_designation: str = None, signature_data: str = None):
    """Whitelisted endpoint to record vendor e-signature securely from public portal."""
    po_name = po_name or frappe.form_dict.get("po_name") or frappe.form_dict.get("po")
    token = token or frappe.form_dict.get("token")
    signer_name = signer_name or frappe.form_dict.get("signer_name")
    signer_designation = signer_designation or frappe.form_dict.get("signer_designation") or "Authorized Signatory"
    signature_data = signature_data or frappe.form_dict.get("signature_data")

    if not po_name or not token or not signer_name:
        frappe.throw("Signer Name, Purchase Order #, and Security Token are strictly mandatory.")

    if not frappe.db.exists("AP Purchase Order", po_name):
        frappe.throw(f"Purchase Order '{po_name}' not found.")

    po = frappe.get_doc("AP Purchase Order", po_name)

    token_in_doc = getattr(po, "vendor_sign_token", None)
    if not token_in_doc and getattr(po, "vendor_sign_url", None):
        parsed = urllib.parse.urlparse(po.vendor_sign_url)
        params = urllib.parse.parse_qs(parsed.query)
        token_in_doc = params.get("token", [None])[0]

    if token_in_doc and not is_token_matching(token_in_doc, token):
        frappe.throw("Invalid or expired digital signature token.")

    if po.vendor_sign_status == "Digitally Signed":
        return {
            "status": "already_signed",
            "message": f"This Purchase Order has already been digitally signed on {po.vendor_signed_timestamp} by {po.vendor_signed_by}."
        }

    client_ip = frappe.local.request_ip if hasattr(frappe.local, "request_ip") else "127.0.0.1"

    po.vendor_signed_by = f"{signer_name.strip()} ({signer_designation.strip() or 'Authorized Signatory'})"
    po.vendor_signed_ip = client_ip
    po.vendor_signed_timestamp = frappe.utils.now_datetime()
    po.vendor_sign_status = "Digitally Signed"
    po.status = "Active PO"
    if signature_data:
        po.vendor_signature_image = signature_data
    po.save(ignore_permissions=True)
    frappe.db.commit()

    # Trigger Automated Multi-Party Notifications
    try:
        from ap_automation.services import notification_service
        if hasattr(notification_service, "notify_on_vendor_po_signed"):
            notification_service.notify_on_vendor_po_signed(po.name)
    except Exception as e:
        frappe.log_error(f"Failed to dispatch post-signature notification: {e}")

    return {
        "status": "success",
        "po_name": po.name,
        "signed_by": po.vendor_signed_by,
        "signed_at": str(po.vendor_signed_timestamp),
        "message": f"Purchase Order #{po.name} successfully signed and activated."
    }
