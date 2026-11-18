// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

frappe.ui.form.on("Vendor PO Request", {
	refresh(frm) {
		frm.disable_save();
		frm.set_intro(
			__(
				"This legacy screen is retired. Please use AP Purchase Order for PO advances and Vendor Invoice Claim for all vendor invoices and disbursements."
			),
			"orange"
		);
		frm.add_custom_button(__("Go to AP Purchase Order"), () => {
			frappe.set_route("List", "AP Purchase Order");
		});
		frm.add_custom_button(__("Go to Vendor Invoice Claim"), () => {
			frappe.set_route("List", "Vendor Invoice Claim");
		});
	},
});
