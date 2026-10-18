// Copyright (c) 2026, Quanti and contributors
// Production Event Advance Request (Imprest Proposal) UI Controller
// Supports:
// 1. Dynamic Row-Wise Imprest Table Calculations (Direct Vendor Pay vs Cash Imprest).
// 2. Business Head Sanction Action (Anish Sir / Dileep Sir).
// 3. Accounts Team IDFC Disbursal Action (Gokulnath / Accounts Director).
// 4. One-Click Expense Claim Generator.

function calculate_imprest_totals(frm) {
    let direct_total = 0.0;
    let cash_total = 0.0;

    (frm.doc.imprest_items || []).forEach(row => {
        let amt = flt(row.amount);
        if (row.payment_mode === 'Direct Vendor Payment') {
            direct_total += amt;
        } else {
            cash_total += amt;
        }
    });

    frm.set_value('total_direct_vendor_amount', direct_total);
    frm.set_value('total_cash_imprest_amount', cash_total);
    frm.set_value('requested_advance_amount', direct_total + cash_total);
}

frappe.ui.form.on("Event Advance Request", {
    setup: function(frm) {
        if (window.APReceiptGallery && typeof window.APReceiptGallery.setup === 'function') {
            window.APReceiptGallery.setup(frm);
        }
    },

    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            const user_roles = frappe.user_roles || [];
            const is_sys_mgr = user_roles.includes('System Manager') || frappe.session.user === 'Administrator';
            const is_bh = user_roles.includes('Business Head') || user_roles.includes('Director') || user_roles.includes('Director Tier') || is_sys_mgr;
            const is_accounts = user_roles.includes('Accounts L1 Auditor') || user_roles.includes('Accounts Director') || user_roles.includes('Accounts Manager') || user_roles.includes('Payment Releaser') || is_sys_mgr;

            // 1. Business Head Approval Action
            if (frm.doc.status === 'Pending Business Head Approval') {
                if (is_bh) {
                    frm.add_custom_button(__('✅ Sanction Imprest (Business Head)'), function() {
                        frappe.prompt([
                            {
                                fieldname: 'comments',
                                fieldtype: 'Small Text',
                                label: __('Sanction Notes / Justification (Optional)'),
                                default: 'Approved for event operations.'
                            }
                        ], function(values) {
                            frappe.call({
                                method: 'ap_automation.controllers.event_advance_request.approve_by_business_head',
                                args: {
                                    advance_name: frm.doc.name,
                                    comments: values.comments
                                },
                                freeze: true,
                                freeze_message: __('Sanctioning Event Imprest...'),
                                callback: function(r) {
                                    if (r.message && r.message.status === 'SUCCESS') {
                                        frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }, __('Sanction Event Imprest'), __('Sanction'));
                    }).addClass('btn-success');

                    frm.add_custom_button(__('❌ Reject Proposal'), function() {
                        frappe.prompt([
                            {
                                fieldname: 'reason',
                                fieldtype: 'Small Text',
                                label: __('Rejection Reason'),
                                reqd: 1
                            }
                        ], function(values) {
                            frappe.call({
                                method: 'ap_automation.controllers.event_advance_request.reject_event_advance',
                                args: {
                                    advance_name: frm.doc.name,
                                    reason: values.reason
                                },
                                freeze: true,
                                freeze_message: __('Rejecting Proposal...'),
                                callback: function(r) {
                                    if (r.message && r.message.status === 'SUCCESS') {
                                        frappe.show_alert({ message: r.message.message, indicator: 'red' });
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }, __('Reject Proposal'), __('Reject'));
                    }).addClass('btn-danger');
                }
            }

            // 2. Accounts Team Disbursal Action
            if (frm.doc.status === 'Pending Accounts Disbursal') {
                if (is_accounts) {
                    frm.add_custom_button(__('💳 Disburse via IDFC (Accounts)'), function() {
                        frappe.prompt([
                            {
                                fieldname: 'disbursement_ref',
                                fieldtype: 'Data',
                                label: __('Bank UTR / Disbursal Reference'),
                                default: 'IDFC-TXN-' + Math.floor(100000 + Math.random() * 900000),
                                reqd: 1
                            }
                        ], function(values) {
                            frappe.call({
                                method: 'ap_automation.controllers.event_advance_request.disburse_event_advance',
                                args: {
                                    advance_name: frm.doc.name,
                                    disbursement_ref: values.disbursement_ref
                                },
                                freeze: true,
                                freeze_message: __('Disbursing Event Imprest...'),
                                callback: function(r) {
                                    if (r.message && r.message.status === 'SUCCESS') {
                                        frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }, __('Execute Bank Disbursal'), __('Disburse Funds'));
                    }).addClass('btn-primary');
                }
            }

            // 3. One-Click Expense Claim Generator
            if (frm.doc.status === 'Disbursed via IDFC') {
                frm.add_custom_button(__('📋 Create Expense Claim from Proposal'), function() {
                    frappe.route_options = {
                        "event": frm.doc.event,
                        "company": frm.doc.company
                    };
                    frappe.new_doc("Event Expense Claim");
                }).addClass('btn-default');
            }
        }
    },

    event: function(frm) {
        if (frm.doc.event) {
            frappe.db.get_doc('Event Master', frm.doc.event).then(ev => {
                frm.set_value('company', ev.company);
                frm.set_value('spoc', ev.event_spoc);
                frm.set_value('spoc_name', ev.spoc_name);
                frm.set_value('event_date', ev.start_date);
                if (ev.event_location) {
                    frm.set_value('venue', ev.event_location);
                }
                if (ev.company) {
                    frappe.db.get_value('Company', ev.company, 'default_letter_head').then(r => {
                        if (r && r.message && r.message.default_letter_head) {
                            frm.set_value('letter_head', r.message.default_letter_head);
                        }
                    });
                }
            });
        }
    }
});

// Child Table Calculations
frappe.ui.form.on("Event Imprest Item", {
    amount: function(frm, cdt, cdn) {
        calculate_imprest_totals(frm);
    },
    payment_mode: function(frm, cdt, cdn) {
        calculate_imprest_totals(frm);
    },
    imprest_items_remove: function(frm) {
        calculate_imprest_totals(frm);
    }
});
