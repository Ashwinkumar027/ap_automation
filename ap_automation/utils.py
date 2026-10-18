import frappe

def check_app_permission(user: str = None) -> bool:
    """
    Colleague's Bug 2 Method:
    Dynamically verifies if the active user possesses at least one of the authorized
    roles configured on the 'AP Automation' Workspace.
    """
    if not user:
        user = frappe.session.user

    if user == "Guest":
        return False

    if user == "Administrator":
        return True

    user_roles = frappe.get_roles(user)

    # If System Manager, always allow
    if "System Manager" in user_roles:
        return True

    # Pull allowed roles dynamically from AP Automation Workspace (Single Source of Truth)
    if frappe.db.exists("Workspace", "AP Automation"):
        ws = frappe.get_doc("Workspace", "AP Automation")
        allowed_roles = [r.role for r in ws.roles]
        if not allowed_roles:
            return True
        return bool(set(user_roles).intersection(set(allowed_roles)))

    # Fallback to standard financial/desk roles
    standard_allowed = ["Accounts Manager", "Accounts User", "Employee", "Desk User"]
    return bool(set(user_roles).intersection(set(standard_allowed)))


import os
import base64
import mimetypes

@frappe.whitelist()
def get_file_as_base64(file_url: str) -> str:
    """
    Reads a public or private file from disk and returns a data:image/...;base64 string.
    Ensures private pictures render seamlessly in wkhtmltopdf and print formats without 403 errors.
    """
    if not file_url:
        return ""

    if file_url.startswith("data:image"):
        return file_url

    clean_url = file_url.split("?")[0]
    if clean_url.startswith("/private/files/"):
        fname = clean_url.replace("/private/files/", "")
        full_path = frappe.get_site_path("private", "files", fname)
    elif clean_url.startswith("/files/"):
        fname = clean_url.replace("/files/", "")
        full_path = frappe.get_site_path("public", "files", fname)
    else:
        full_path = frappe.get_site_path("public", "files", clean_url)

    if os.path.exists(full_path):
        try:
            mime_type, _ = mimetypes.guess_type(full_path)
            if not mime_type:
                mime_type = "image/png"
            with open(full_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
                return f"data:{mime_type};base64,{encoded}"
        except Exception:
            return file_url

    return file_url

@frappe.whitelist()
def get_company_print_settings(company: str) -> dict:
    """
    Fetches dynamic company logo and regulatory header details from Offer Letter Print Settings.
    Converts private logo to base64 so it renders perfectly in PDF / print previews.
    """
    if not company:
        return {}

    if frappe.db.exists("Offer Letter Print Settings", company):
        settings = frappe.get_doc("Offer Letter Print Settings", company)
        logo_url = settings.company_logo
        logo_base64 = None
        if logo_url:
            logo_base64 = get_file_as_base64(logo_url)

        return {
            "source": "Offer Letter Print Settings",
            "company_name": company,
            "company_logo_url": logo_url,
            "company_logo_base64": logo_base64,
            "registered_address": getattr(settings, "registered_address", ""),
            "compliance_email": getattr(settings, "compliance_email", ""),
            "cin_number": getattr(settings, "cin_number", ""),
            "sebi_registration_no": getattr(settings, "sebi_registration_no", ""),
            "amfi_registration_no": getattr(settings, "amfi_registration_no", ""),
            "signatory_name": getattr(settings, "signatory_name", ""),
            "signatory_designation": getattr(settings, "signatory_designation", ""),
        }

    return {}
