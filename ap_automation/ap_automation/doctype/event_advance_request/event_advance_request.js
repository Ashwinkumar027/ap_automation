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
            const is_bh = user_roles.includes('Business Head') || user_roles.includes('AP Director') || is_sys_mgr;
            const is_acct_dir = user_roles.includes('Accounts Director') || user_roles.includes('Accounts Manager') || is_sys_mgr;
            const is_maker = user_roles.includes('Accounts L1 Auditor') || user_roles.includes('Accounts User') || user_roles.includes('Accounts Manager') || user_roles.includes('Accounts Director') || is_sys_mgr;
            const is_finance_viewer = is_maker || user_roles.includes('Payment Releaser') || user_roles.includes('AP Director');
            const is_checker = user_roles.includes('Payment Releaser') || user_roles.includes('AP Director') || user_roles.includes('Accounts Director') || user_roles.includes('Accounts Manager') || is_sys_mgr;

            // STAGE 1: Director Sanction Action
            if (frm.doc.status === 'Pending Director Sanction' || frm.doc.status === 'Pending Business Head Approval') {
                frm.page.set_indicator(__('Pending Director Sanction'), 'orange');
                if (is_bh) {
                    frm.add_custom_button(__('✅ Sanction Imprest (Director)'), function() {
                        frappe.prompt([
                            {
                                fieldname: 'comments',
                                fieldtype: 'Small Text',
                                label: __('Director Sanction Notes / Justification (Optional)'),
                                default: 'Sanctioned for event operations.'
                            }
                        ], function(values) {
                            frappe.call({
                                method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.approve_by_business_head',
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
                        }, __('Sanction Event Imprest (Director)'), __('Sanction'));
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
                                method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.reject_event_advance',
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

            // STAGE 2: Accounts Director Sign-off
            if (['Pending Accounts Disbursal', 'Approved by Director', 'Approved by Business Head'].includes(frm.doc.status)) {
                frm.page.set_indicator(__('Sanctioned by Director'), 'blue');
                if (is_acct_dir) {
                    frm.add_custom_button(__('⭐ Accounts Director Sign-Off'), function() {
                        frappe.prompt([
                            {
                                fieldname: 'remarks',
                                fieldtype: 'Small Text',
                                label: __('Authorization Remarks (Optional)'),
                                default: 'All beneficiary accounts verified. Approved for IDFC Disbursal.'
                            }
                        ], function(values) {
                            frappe.call({
                                method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.authorize_event_advance_by_accounts_director',
                                args: {
                                    advance_name: frm.doc.name,
                                    remarks: values.remarks
                                },
                                freeze: true,
                                freeze_message: __('Authorizing Event Advance...'),
                                callback: function(r) {
                                    if (r.message && r.message.status === 'SUCCESS') {
                                        frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }, __('Accounts Director Sign-Off'), __('Authorize'));
                    }).addClass('btn-primary');
                }
            }

            // STAGE 3: Post-Accounts Director Approval -> IDFC Excel, Maker-Checker Payment Release, Checker Disbursal
            if (['Approved for Payment', 'Disbursed'].includes(frm.doc.status) && is_finance_viewer) {
                if (frm.doc.status === 'Approved for Payment') {
                    frm.page.set_indicator(__('Approved for Payment'), 'green');
                }

                // 1. Download IDFC Bank Bulk Disbursal Excel (.xlsx) (Finance/Releaser only, never SPOC/Employee)
                frm.add_custom_button(__('🏛️ IDFC Bank Disbursal Excel (.xlsx)'), function() {
                    const download_url = `/api/method/ap_automation.services.idfc_bank_excel_generator.download_idfc_event_advance_excel?advance_name=${encodeURIComponent(frm.doc.name)}`;
                    window.open(download_url, '_blank');
                    frappe.show_alert({
                        message: __('IDFC Bank Bulk Disbursal Excel downloaded. Please upload to IDFC Netbanking.'),
                        indicator: 'blue'
                    });
                }).addClass('btn-info');

                if (frm.doc.status === 'Approved for Payment') {
                    // 2. Maker-Checker Payment Release Notification (Maker Roles only)
                    if (frm.doc.payment_release_notified) {
                        frm.add_custom_button(__('✓ Payment Release Sent (IDFC Uploaded)'), function() {
                            const notif_date = frm.doc.payment_release_notified_on ? frappe.datetime.str_to_user(frm.doc.payment_release_notified_on) : 'Recently';
                            frappe.msgprint({
                                title: __('Payment Release Already Notified'),
                                message: __('IDFC Disbursal File was uploaded and notification was dispatched on {0} by {1}. Awaiting final bank release by Payment Releaser ({2}).', [notif_date, frm.doc.payment_release_maker || 'Maker', frm.doc.payment_releaser || 'Director']),
                                indicator: 'green'
                            });
                        }).addClass('btn-success disabled');
                    } else if (is_maker) {
                        frm.add_custom_button(__('📤 Payment Release'), function() {
                            frappe.confirm(
                                __('Confirm that the IDFC Disbursal Excel has been uploaded to the IDFC Netbanking portal.<br><br>This will send a high-priority payout alert to the <b>Payment Releaser / AP Director</b> (Checker, TO) with CC to the <b>Accounts Director</b> (Supervisor, CC) from the AP Approval Matrix.<br><br>Proceed with notification dispatch?'),
                                function() {
                                    frappe.call({
                                        method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.trigger_event_advance_payment_release_notification',
                                        args: { advance_name: frm.doc.name },
                                        freeze: true,
                                        freeze_message: __('Dispatching Payment Release Alert to Payment Releaser...'),
                                        callback: function(r) {
                                            if (r.message && r.message.status === 'SUCCESS') {
                                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                                frm.reload_doc();
                                            }
                                        }
                                    });
                                }
                            );
                        }).addClass('btn-warning');
                    }

                    // 3. Bank Disbursal & UTR Stamping (Checker only: after Payment Release notified, and Checker != Maker)
                    const not_same_maker = (frm.doc.payment_release_maker !== frappe.session.user) || frappe.session.user === 'Administrator';
                    if (frm.doc.payment_release_notified && is_checker && not_same_maker) {
                        frm.add_custom_button(__('💳 Release Bank Disbursal (Payment Releaser)'), function() {
                            frappe.prompt([
                                {
                                    fieldname: 'disbursement_ref',
                                    fieldtype: 'Data',
                                    label: __('Bank UTR / Disbursal Reference'),
                                    default: 'IDFC-EVT-' + Math.floor(10000000 + Math.random() * 90000000),
                                    reqd: 1
                                }
                            ], function(values) {
                                frappe.call({
                                    method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.disburse_event_advance',
                                    args: {
                                        advance_name: frm.doc.name,
                                        disbursement_ref: values.disbursement_ref
                                    },
                                    freeze: true,
                                    freeze_message: __('Stamping UTR and Disbursing...'),
                                    callback: function(r) {
                                        if (r.message && r.message.status === 'SUCCESS') {
                                            frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                            frm.reload_doc();
                                        }
                                    }
                                });
                            }, __('Record Bank Disbursal & Stamp UTR'), __('Disburse'));
                        }).addClass('btn-primary');
                    }
                }
            }

            // STAGE 4: Disbursed -> Ready for Post-Event Expense Claim
            if (frm.doc.status === 'Disbursed') {
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
                        <div style="display: flex; gap: 12px; margin-top: 4px; font-size: 11px;">
                            <span style="background: #ffffff; padding: 2px 8px; border-radius: 4px; border: 1px solid #bbf7d0; color: #166534; font-weight: 600;">
                                🏛️ Direct Vendor Payouts: <b>${format_curr(parseFloat(frm.doc.total_direct_vendor_amount || 0))}</b>
                            </span>
                            <span style="background: #ffffff; padding: 2px 8px; border-radius: 4px; border: 1px solid #bbf7d0; color: #166534; font-weight: 600;">
                                💵 SPOC Cash Imprest: <b>${format_curr(parseFloat(frm.doc.total_cash_imprest_amount || 0))}</b>
                            </span>
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
