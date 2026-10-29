# Copyright (c) 2026, Quanti and contributors
# For license information, please see license.txt

import frappe
from frappe import _

no_cache = 1


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/ap"
        raise frappe.Redirect

    context.site_name = frappe.local.site
    context.boot = get_boot()
    return context


def get_boot():
    user = frappe.session.user
    roles = frappe.get_roles(user)

    # Accessible companies
    companies = frappe.get_all(
        "Company", fields=["name", "company_name", "default_currency"]
    )
    user_doc = frappe.get_cached_doc("User", user)

    return {
        "site_name": frappe.local.site,
        "session_user": user,
        "user_fullname": user_doc.full_name or user,
        "user_email": user_doc.email or user,
        "user_roles": roles,
        "csrf_token": frappe.sessions.get_csrf_token(),
        "date_format": frappe.get_system_settings("date_format") or "dd-mm-yyyy",
        "time_format": frappe.get_system_settings("time_format") or "HH:mm:ss",
        "companies": [c.name for c in companies],
        "default_company": companies[0].name if companies else "",
        "default_currency": "INR",
    }
