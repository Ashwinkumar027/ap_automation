// Copyright (c) 2026, Quanti and contributors
// Event Advance Request Controller (Lane 4 Intake & Governance)
// 100% Mobile & Desktop Responsive

frappe.ui.form.on("Event Advance Request", {
    setup: function(frm) {
        if (window.APReceiptGallery && typeof window.APReceiptGallery.setup === 'function') {
            window.APReceiptGallery.setup(frm);
        }
    },

    refresh: function(frm) {
        render_advance_event_context(frm);
        calculate_imprest_totals(frm);

        // --- Print & View Actions ---
        if (!frm.is_new()) {
            frm.add_custom_button(__('📄 Download Imprest PDF'), function() {
                const pdf_url = frappe.urllib.get_full_url(
                    `/api/method/frappe.utils.print_format.download_pdf?doctype=${encodeURIComponent(frm.doc.doctype)}&name=${encodeURIComponent(frm.doc.name)}&format=Event%20Expense%20Report&no_letterhead=0`
                );
                window.open(pdf_url, '_blank');
            }, __('Print / Download'));

            frm.add_custom_button(__('🖨️ View Print Format'), function() {
                const print_url = `/printview?doctype=${encodeURIComponent(frm.doc.doctype)}&name=${encodeURIComponent(frm.doc.name)}&format=Event%20Expense%20Report&no_letterhead=0`;
                window.open(print_url, '_blank');
            }, __('Print / Download'));
        }

        // --- Workflow Stage Actions ---
        if (frm.doc.docstatus === 1) {
            const user_roles = frappe.user_roles || [];
            const is_sys_mgr = user_roles.includes('System Manager') || frappe.session.user === 'Administrator';
            const is_bh = user_roles.includes('Business Head') || user_roles.includes('Director') || user_roles.includes('Director Tier') || is_sys_mgr;
            const is_accounts = user_roles.includes('Accounts L1 Auditor') || user_roles.includes('Accounts Director') || user_roles.includes('Accounts Manager') || user_roles.includes('Payment Releaser') || is_sys_mgr;

            // STAGE 1: Business Head Sanction Action
            if (frm.doc.status === 'Pending Business Head Approval') {
                frm.page.set_indicator(__('Pending Business Head Approval'), 'orange');
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

            // STAGE 2: Accounts Team Disbursal Action
            else if (frm.doc.status === 'Pending Accounts Disbursal') {
                frm.page.set_indicator(__('Pending Accounts Disbursal'), 'blue');
                if (is_accounts) {
                    frm.add_custom_button(__('💳 Execute Bank Disbursal (Accounts)'), function() {
                        frappe.prompt([
                            {
                                fieldname: 'disbursement_ref',
                                fieldtype: 'Data',
                                label: __('Bank UTR / Disbursal Reference'),
                                default: 'UTR-' + Math.floor(100000 + Math.random() * 900000),
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

            // STAGE 3: Disbursed -> Ready for Post-Event Expense Claim
            else if (frm.doc.status === 'Disbursed') {
                frm.page.set_indicator(__('Disbursed'), 'green');
                frm.add_custom_button(__('📋 Create Expense Claim from Proposal'), function() {
                    frappe.route_options = {
                        "event": frm.doc.event,
                        "company": frm.doc.company
                    };
                    frappe.new_doc("Event Expense Claim");
                }).addClass('btn-primary');
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
                render_advance_event_context(frm);
            });
        }
    }
});

function render_advance_event_context(frm) {
    if (!frm.doc.event) return;

    frappe.db.get_value('Event Master', frm.doc.event, ['event_name', 'allocated_budget', 'remaining_budget', 'total_committed_spend']).then(r => {
        if (!r || !r.message) return;
        const ev = r.message;
        const budget = parseFloat(ev.allocated_budget || 0.0);
        const committed = parseFloat(ev.total_committed_spend || 0.0);
        const remaining = parseFloat(ev.remaining_budget || (budget - committed));

        const format_curr = (val) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(val || 0);

        const banner_html = `
            <div class="ap-advance-context-banner" style="
                background: #f0fdf4;
                border: 1px solid #86efac;
                border-radius: 8px;
                padding: 12px 16px;
                margin-bottom: 16px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                flex-wrap: wrap;
                gap: 10px;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            ">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 20px;">💡</span>
                    <div>
                        <div style="font-size: 13px; font-weight: 700; color: #166534;">Linked Event: ${ev.event_name || frm.doc.event}</div>
                        <div style="font-size: 11px; color: #15803d; margin-top: 2px;">
                            Board Budget: <b>${format_curr(budget)}</b> &nbsp;|&nbsp; Committed: <b>${format_curr(committed)}</b>
                        </div>
                    </div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 11px; text-transform: uppercase; color: #15803d; font-weight: 700;">Available For Advance</div>
                    <div style="font-size: 18px; font-weight: 800; color: #166534;">${format_curr(remaining)}</div>
                </div>
            </div>
        `;

        if (frm.dashboard) {
            frm.dashboard.set_headline(banner_html);
        }
    });
}

function calculate_imprest_totals(frm) {
    let direct = 0.0;
    let cash = 0.0;

    (frm.doc.imprest_items || []).forEach(row => {
        let amt = parseFloat(row.amount || 0.0);
        if (row.payment_mode === "Direct Vendor Payment") {
            direct += amt;
        } else {
            cash += amt;
        }
    });

    if (frm.fields_dict.total_direct_vendor_amount) {
        frm.set_value('total_direct_vendor_amount', direct);
    }
    if (frm.fields_dict.total_cash_imprest_amount) {
        frm.set_value('total_cash_imprest_amount', cash);
    }
    if (frm.fields_dict.requested_advance_amount) {
        frm.set_value('requested_advance_amount', direct + cash);
    }
    if (frm.fields_dict.total_amount) {
        frm.set_value('total_amount', direct + cash);
    }
}

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
