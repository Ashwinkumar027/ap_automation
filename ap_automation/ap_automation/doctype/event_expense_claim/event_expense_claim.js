// Copyright (c) 2026, Quanti and contributors
// Event Expense Claim Controller
// Supports:
// 1. One-Click Population from Approved Imprest Proposal.
// 2. Receipt Gallery Preview for Attached Bills.
// 3. Automated Line Item Total Calculation.

frappe.ui.form.on("Event Expense Claim", {
    setup: function(frm) {
        if (window.APReceiptGallery && typeof window.APReceiptGallery.setup === 'function') {
            window.APReceiptGallery.setup(frm);
        }
    },

    refresh: function(frm) {
        if (frm.doc.docstatus === 0 && frm.doc.event) {
            frm.add_custom_button(__('📋 Populate from Imprest Proposal'), function() {
                frappe.call({
                    method: 'ap_automation.controllers.event_expense_claim.populate_from_imprest_proposal',
                    args: { event_name: frm.doc.event },
                    freeze: true,
                    freeze_message: __('Loading Imprest Items...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frm.clear_table('expense_items');
                            r.message.items.forEach(item => {
                                let row = frm.add_child('expense_items');
                                row.particulars = item.particulars;
                                row.vendor_name = item.vendor_name;
                                row.bill_number = item.bill_number;
                                row.bill_date = item.bill_date;
                                row.amount = item.amount;
                                row.spend_stream = item.spend_stream;
                                row.expense_category = item.expense_category;
                                row.remarks = item.remarks;
                            });
                            frm.refresh_field('expense_items');
                            frappe.show_alert({
                                message: __(`✅ Loaded ${r.message.items_count} items from Imprest #${r.message.advance_name}! Please attach receipt proofs.`),
                                indicator: 'green'
                            }, 5);
                        }
                    }
                });
            }).addClass('btn-primary');
        }
    },

    event: function(frm) {
        if (frm.doc.event) {
            frappe.db.get_doc('Event Master', frm.doc.event).then(ev => {
                frm.set_value('company', ev.company);
                frm.set_value('spoc', ev.event_spoc);
                frm.set_value('spoc_name', ev.spoc_name);
            });
        }
    }
});
