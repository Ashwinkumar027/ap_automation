// Copyright (c) 2026, Quanti and contributors
// Event Settlement Controller (Lane 4 Settlement & Closure)
// 100% Mobile & Desktop Responsive

function format_inr(val) {
    return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        maximumFractionDigits: 2
    }).format(val || 0);
}

frappe.ui.form.on("Event Settlement", {
    onload: function(frm) {
        if (frm.is_new() && !frm.doc.settlement_date) {
            frm.set_value('settlement_date', frappe.datetime.get_today());
        }
        if (frm.is_new() && frm.doc.event) {
            frm.trigger('event');
        }
    },

    refresh: function(frm) {
        frm.set_df_property('status', 'read_only', 1);
        set_settlement_status_indicator(frm);
        render_settlement_verdict_card(frm);

        if (!frm.is_new() && window.APReceiptGallery) {
            window.APReceiptGallery.addPrintDownloadButtons(
                frm,
                'Event Settlement Report',
                __('📄 Download Settlement PDF'),
                __('🖨️ View Print Format')
            );
            window.APReceiptGallery.addExcelExportButton(frm);
            window.APReceiptGallery.addTallyXmlButton(frm, ['Approved for Payment', 'Settled']);
            if (frm.doc.event) {
                window.APReceiptGallery.refreshEventAggregatedButtons(frm, frm.doc.event);
            } else {
                window.APReceiptGallery.refreshFormButtons(frm);
            }
        }

        setup_settlement_workflow_actions(frm);
    },

    event: function(frm) {
        if (frm.doc.event) {
            frappe.call({
                method: "ap_automation.services.event_settlement_service.calculate_event_settlement_delta",
                args: { event_name: frm.doc.event },
                callback: function(r) {
                    if (r.message) {
                        const d = r.message;
                        frm.set_value('company', d.company);
                        frm.set_value('spoc', d.spoc);
                        frm.set_value('spoc_name', d.spoc_name);
                        frm.set_value('event_end_date', d.event_end_date);
                        frm.set_value('disbursed_advance', d.disbursed_advance);
                        frm.set_value('spoc_actual_spends', d.spoc_actual_spends);
                        frm.set_value('settlement_delta', d.settlement_delta);
                        frm.set_value('settlement_type', d.settlement_type);
                        frm.set_value('net_payable_to_spoc', d.net_payable_to_spoc);
                        frm.set_value('refund_receivable_from_spoc', d.refund_receivable_from_spoc);
                        render_settlement_verdict_card(frm);
                    }
                }
            });
        }
    }
});

function set_settlement_status_indicator(frm) {
    const status = frm.doc.status || 'Draft';
    const color_map = {
        'Draft': 'grey',
        'Under Accounts Review': 'orange',
        'Approved for Payment': 'blue',
        'Settled': 'green',
        'Rejected': 'red'
    };
    frm.page.set_indicator(__(status), color_map[status] || 'grey');
}

function build_settlement_stepper_html(frm) {
    const status = frm.doc.status || 'Draft';
    const s_type = frm.doc.settlement_type || 'PAYABLE_TO_SPOC';
    const is_rejected = status === 'Rejected';

    let stages;
    if (s_type === 'REFUND_FROM_SPOC') {
        stages = [
            { label: '1. Draft (SPOC + Refund UTR)' },
            { label: '2. Accounts Refund Audit' },
            { label: '3. Settled & Closed' }
        ];
    } else if (s_type === 'ZERO_BALANCE_BALANCED') {
        stages = [
            { label: '1. Draft (SPOC)' },
            { label: '2. Balanced & Closed' }
        ];
    } else {
        stages = [
            { label: '1. Draft (SPOC)' },
            { label: '2. Accounts Director Approval' },
            { label: '3. IDFC & Payment Release' },
            { label: '4. Settled & Closed' }
        ];
    }

    let active_idx = 0;
    if (status === 'Under Accounts Review') active_idx = 1;
    else if (status === 'Approved for Payment') active_idx = 2;
    else if (status === 'Settled') active_idx = stages.length;
    else if (is_rejected) active_idx = -1;

    const nodes = stages.map((st, idx) => {
        let cls = '';
        let badge = idx + 1;
        if (is_rejected) {
            cls = idx === 0 ? 'step-completed' : 'step-rejected';
            badge = idx === 0 ? '✓' : '✕';
        } else if (idx < active_idx) {
            cls = 'step-completed';
            badge = '✓';
        } else if (idx === active_idx) {
            cls = 'step-active';
        }
        return `<div class="ap-step-item ${cls}"><div class="ap-step-node">${badge}</div><div class="ap-step-label">${st.label}</div></div>`;
    }).join('');

    return `<div class="ap-stepper-wrapper" style="margin-bottom: 12px;"><div class="ap-stepper-trail">${nodes}</div></div>`;
}

function render_settlement_verdict_card(frm) {
    if (!frm.dashboard) return;
    const stepper_html = build_settlement_stepper_html(frm);

    if (!frm.doc.settlement_type) {
        if (window.APReceiptGallery && typeof window.APReceiptGallery.setHeadlineExclusive === 'function') {
            window.APReceiptGallery.setHeadlineExclusive(frm, stepper_html);
        } else {
            if (typeof frm.dashboard.clear_headline === 'function') frm.dashboard.clear_headline();
            frm.dashboard.set_headline(stepper_html);
        }
        return;
    }

    const s_type = frm.doc.settlement_type;
    const adv = parseFloat(frm.doc.disbursed_advance || 0.0);
    const actuals = parseFloat(frm.doc.spoc_actual_spends || 0.0);
    const payable = parseFloat(frm.doc.net_payable_to_spoc || 0.0);
    const refund = parseFloat(frm.doc.refund_receivable_from_spoc || 0.0);

    let card_html = "";

    if (s_type === "REFUND_FROM_SPOC") {
        card_html = `
            <div class="ap-settlement-verdict-card" style="
                background: linear-gradient(135deg, #fffbeb 0%, #fef2f2 100%);
                border: 1px solid #fecaca;
                border-radius: 12px;
                padding: 18px 20px;
                margin-bottom: 20px;
                box-shadow: 0 4px 10px rgba(239, 68, 68, 0.06);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            ">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;">
                    <div style="display: flex; align-items: flex-start; gap: 14px;">
                        <span style="font-size: 32px; line-height: 1;">⚠️</span>
                        <div>
                            <div style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #dc2626; letter-spacing: 0.05em;">
                                Settlement Verdict: SPOC Cash Return Required
                            </div>
                            <div style="font-size: 16px; font-weight: 800; color: #991b1b; margin-top: 2px;">
                                SPOC owes ${format_inr(refund)} back to Quanti Corporate Account
                            </div>
                            <div style="font-size: 12px; color: #7f1d1d; margin-top: 4px; max-width: 580px;">
                                Disbursed Advance was <b>${format_inr(adv)}</b>, but total ground spends filed was <b>${format_inr(actuals)}</b>.
                                The SPOC must deposit <b>${format_inr(refund)}</b> and enter the verified Bank UTR reference below for Accounts audit.
                            </div>
                        </div>
                    </div>
                    <div style="text-align: right; background: #ffffff; border: 1px solid #fca5a5; border-radius: 8px; padding: 10px 16px;">
                        <div style="font-size: 11px; font-weight: 700; color: #dc2626; text-transform: uppercase;">Refund Receivable</div>
                        <div style="font-size: 24px; font-weight: 800; color: #b91c1c;">${format_inr(refund)}</div>
                    </div>
                </div>
            </div>
        `;
    } else if (s_type === "PAYABLE_TO_SPOC") {
        card_html = `
            <div class="ap-settlement-verdict-card" style="
                background: linear-gradient(135deg, #eff6ff 0%, #ecfdf5 100%);
                border: 1px solid #bfdbfe;
                border-radius: 12px;
                padding: 18px 20px;
                margin-bottom: 20px;
                box-shadow: 0 4px 10px rgba(59, 130, 246, 0.06);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            ">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;">
                    <div style="display: flex; align-items: flex-start; gap: 14px;">
                        <span style="font-size: 32px; line-height: 1;">💳</span>
                        <div>
                            <div style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #2563eb; letter-spacing: 0.05em;">
                                Settlement Verdict: Net Reimbursement Due to SPOC
                            </div>
                            <div style="font-size: 16px; font-weight: 800; color: #1e3a8a; margin-top: 2px;">
                                Quanti owes SPOC ${format_inr(payable)} for out-of-pocket expenses
                            </div>
                            <div style="font-size: 12px; color: #1e40af; margin-top: 4px; max-width: 580px;">
                                SPOC actual ground spends were <b>${format_inr(actuals)}</b>, exceeding the advance of <b>${format_inr(adv)}</b>.
                                Accounts will disburse this balance to the SPOC's HRMS-verified salary account.
                            </div>
                        </div>
                    </div>
                    <div style="text-align: right; background: #ffffff; border: 1px solid #93c5fd; border-radius: 8px; padding: 10px 16px;">
                        <div style="font-size: 11px; font-weight: 700; color: #2563eb; text-transform: uppercase;">Reimbursement Due</div>
                        <div style="font-size: 24px; font-weight: 800; color: #1d4ed8;">${format_inr(payable)}</div>
                    </div>
                </div>
            </div>
        `;
    } else {
        card_html = `
            <div class="ap-settlement-verdict-card" style="
                background: linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 100%);
                border: 1px solid #a7f3d0;
                border-radius: 12px;
                padding: 18px 20px;
                margin-bottom: 20px;
                box-shadow: 0 4px 10px rgba(16, 185, 129, 0.06);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            ">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;">
                    <div style="display: flex; align-items: center; gap: 14px;">
                        <span style="font-size: 32px; line-height: 1;">🎯</span>
                        <div>
                            <div style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #059669; letter-spacing: 0.05em;">
                                Settlement Verdict: Perfectly Balanced
                            </div>
                            <div style="font-size: 16px; font-weight: 800; color: #065f46; margin-top: 2px;">
                                Exact Match (INR 0.00 Outstanding Balance)
                            </div>
                            <div style="font-size: 12px; color: #047857; margin-top: 4px;">
                                Disbursed Advance (<b>${format_inr(adv)}</b>) matches actual ground spends exactly. Ready for final closure.
                            </div>
                        </div>
                    </div>
                    <div style="text-align: right; background: #ffffff; border: 1px solid #86efac; border-radius: 8px; padding: 8px 14px;">
                        <div style="font-size: 12px; font-weight: 700; color: #059669;">● Balanced</div>
                    </div>
                </div>
            </div>
        `;
    }

    if (window.APReceiptGallery && typeof window.APReceiptGallery.setHeadlineExclusive === 'function') {
        window.APReceiptGallery.setHeadlineExclusive(frm, stepper_html + card_html);
    } else {
        if (typeof frm.dashboard.clear_headline === 'function') frm.dashboard.clear_headline();
        frm.dashboard.set_headline(stepper_html + card_html);
    }
}

function run_settlement_with_clarification_gate(frm, callback) {
    if (window.APClarificationThread && typeof window.APClarificationThread.checkUnresolvedQueries === 'function') {
        window.APClarificationThread.checkUnresolvedQueries(frm, callback);
    } else {
        callback();
    }
}

function setup_settlement_workflow_actions(frm) {
    if (frm.doc.docstatus === 0 && (frm.doc.status || 'Draft') === 'Draft') {
        if (frm.page.btn_primary && frm.page.btn_primary.text().trim() === __('Submit')) {
            frm.page.set_primary_action(__('Save'), () => frm.save());
        }

        frm.add_custom_button(__('🚀 Submit Event Settlement'), function() {
            if (!frm.doc.event) {
                frappe.msgprint({
                    title: __('Missing Event'),
                    indicator: 'red',
                    message: __('Please select a <b>Linked Event Master</b> before submitting.')
                });
                frm.scroll_to_field('event');
                return;
            }
            if (frm.doc.settlement_type === 'REFUND_FROM_SPOC' && !(frm.doc.refund_received_reference || '').trim()) {
                frappe.msgprint({
                    title: __('Refund UTR Reference Mandatory'),
                    indicator: 'red',
                    message: __('Unspent cash advance must be returned to Quanti Corporate Account and the verified Bank Refund UTR entered before submitting.')
                });
                frm.scroll_to_field('refund_received_reference');
                return;
            }

            frappe.confirm(
                __('Submit Post-Event Settlement for <b>Accounts Review & Event Closure</b>?'),
                function() {
                    const do_submit = () => {
                        frappe.call({
                            method: 'ap_automation.ap_automation.doctype.event_settlement.event_settlement.submit_event_settlement',
                            args: { settlement_name: frm.doc.name },
                            freeze: true,
                            freeze_message: __('Submitting Event Settlement...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'SUCCESS') {
                                    frappe.show_alert({ message: r.message.message, indicator: 'green' }, 5);
                                    frm.reload_doc();
                                }
                            }
                        });
                    };
                    if (frm.is_new() || frm.is_dirty()) {
                        frm.save().then(() => do_submit());
                    } else {
                        do_submit();
                    }
                }
            );
        }).addClass('btn-primary').css({
            'background-color': '#2563eb',
            'border-color': '#1d4ed8',
            'color': '#ffffff',
            'font-weight': '700'
        });
        return;
    }

    if (frm.doc.docstatus === 1) {
        const user_roles = frappe.user_roles || [];
        const is_sys_mgr = user_roles.includes('System Manager') || frappe.session.user === 'Administrator';
        const is_acct_dir = user_roles.includes('Accounts Director') || user_roles.includes('Accounts Manager') || is_sys_mgr;
        const is_maker = user_roles.includes('Accounts L1 Auditor') || user_roles.includes('Accounts User') || user_roles.includes('Accounts Manager') || user_roles.includes('Accounts Director') || is_sys_mgr;
        const is_finance_viewer = is_maker || user_roles.includes('Payment Releaser') || user_roles.includes('AP Director');
        const is_checker = user_roles.includes('Payment Releaser') || user_roles.includes('AP Director') || user_roles.includes('Accounts Director') || user_roles.includes('Accounts Manager') || is_sys_mgr;

        if (frm.doc.status === 'Under Accounts Review') {
            frm.page.set_indicator(__('Under Accounts Review'), 'orange');

            if (frm.doc.settlement_type === 'REFUND_FROM_SPOC' && (is_maker || user_roles.includes('Payment Releaser'))) {
                frm.add_custom_button(__('✅ Audit & Verify Bank Refund'), function() {
                    run_settlement_with_clarification_gate(frm, function() {
                        frappe.prompt([
                            {
                                fieldname: 'verified_utr',
                                fieldtype: 'Data',
                                label: __('Verified Bank Credit UTR Reference'),
                                default: frm.doc.refund_received_reference || '',
                                reqd: 1
                            }
                        ], function(vals) {
                            frappe.call({
                                method: 'ap_automation.services.event_settlement_service.audit_and_settle_refund',
                                args: {
                                    settlement_name: frm.doc.name,
                                    verified_utr: vals.verified_utr
                                },
                                freeze: true,
                                freeze_message: __('Verifying Bank Credit & Closing Event...'),
                                callback: function(r) {
                                    if (r.message && r.message.status === 'SUCCESS') {
                                        frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }, __('Verify Bank Credit & Close Settlement'), __('Audit & Close'));
                    });
                }).addClass('btn-success');
            } else if (frm.doc.settlement_type === 'PAYABLE_TO_SPOC' && is_acct_dir) {
                frm.add_custom_button(__('⭐ Accounts Director Sign-Off'), function() {
                    run_settlement_with_clarification_gate(frm, function() {
                        frappe.prompt([
                            {
                                fieldname: 'remarks',
                                fieldtype: 'Small Text',
                                label: __('Authorization Remarks (Optional)'),
                                default: 'Settlement variance verified. Approved for IDFC SPOC Reimbursement.'
                            }
                        ], function(vals) {
                            frappe.call({
                                method: 'ap_automation.services.event_settlement_service.authorize_event_settlement_by_accounts_director',
                                args: {
                                    settlement_name: frm.doc.name,
                                    remarks: vals.remarks
                                },
                                freeze: true,
                                freeze_message: __('Authorizing Settlement Payout...'),
                                callback: function(r) {
                                    if (r.message && r.message.status === 'SUCCESS') {
                                        frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }, __('Accounts Director Sign-Off'), __('Authorize'));
                    });
                }).addClass('btn-primary');
            }
        } else if (frm.doc.status === 'Approved for Payment' && frm.doc.settlement_type === 'PAYABLE_TO_SPOC' && is_finance_viewer) {
            frm.page.set_indicator(__('Approved for Payment'), 'blue');

            frm.add_custom_button(__('🏛️ IDFC Bank Disbursal Excel (.xlsx)'), function() {
                const url = `/api/method/ap_automation.services.idfc_bank_excel_generator.download_idfc_event_settlement_excel?settlement_name=${encodeURIComponent(frm.doc.name)}`;
                window.open(url, '_blank');
                frappe.show_alert({ message: __('IDFC SPOC Settlement Excel downloaded.'), indicator: 'blue' });
            }).addClass('btn-info');

            if (frm.doc.payment_release_notified) {
                frm.add_custom_button(__('✓ Payment Release Sent (IDFC Uploaded)'), function() {
                    const notif_date = frm.doc.payment_release_notified_on ? frappe.datetime.str_to_user(frm.doc.payment_release_notified_on) : 'Recently';
                    frappe.msgprint({
                        title: __('Payment Release Already Notified'),
                        message: __('Uploaded on {0} by {1}. Awaiting final payout release by Payment Releaser ({2}).', [notif_date, frm.doc.payment_release_maker || 'Maker', frm.doc.payment_releaser || 'Director']),
                        indicator: 'green'
                    });
                }).addClass('btn-success disabled');
            } else if (is_maker) {
                frm.add_custom_button(__('📤 Payment Release'), function() {
                    frappe.confirm(
                        __('Confirm that the IDFC Disbursal Excel has been uploaded to the IDFC Netbanking portal.<br><br>This will notify the Payment Releaser (Checker) to release SPOC reimbursement.'),
                        function() {
                            frappe.call({
                                method: 'ap_automation.services.event_settlement_service.trigger_event_settlement_payment_release_notification',
                                args: { settlement_name: frm.doc.name },
                                freeze: true,
                                freeze_message: __('Dispatching Payment Release Notification...'),
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

            const not_same_maker = (frm.doc.payment_release_maker !== frappe.session.user) || frappe.session.user === 'Administrator';
            if (frm.doc.payment_release_notified && is_checker && not_same_maker) {
                frm.add_custom_button(__('💳 Execute SPOC Reimbursement'), function() {
                    frappe.prompt([
                        {
                            fieldname: 'payment_ref',
                            fieldtype: 'Data',
                            label: __('Bank Disbursal UTR / Transaction Reference'),
                            default: 'UTR-SPOC-' + Math.floor(100000 + Math.random() * 900000),
                            reqd: 1
                        }
                    ], function(vals) {
                        frappe.call({
                            method: 'ap_automation.services.event_settlement_service.disburse_event_settlement_spoc_payout',
                            args: {
                                settlement_name: frm.doc.name,
                                payment_reference: vals.payment_ref
                            },
                            freeze: true,
                            freeze_message: __('Releasing SPOC Reimbursement & Closing Event...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'SUCCESS') {
                                    frappe.show_alert({ message: __('Reimbursement executed successfully! Event closed.'), indicator: 'green' });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }, __('Execute SPOC Reimbursement'), __('Disburse Funds'));
                }).addClass('btn-primary');
            }
        } else if (frm.doc.status === 'Settled') {
            frm.page.set_indicator(__('Settled & Closed'), 'green');
            if (frm.doc.settlement_type === 'PAYABLE_TO_SPOC' && is_finance_viewer) {
                frm.add_custom_button(__('🏛️ IDFC Bank Disbursal Excel (.xlsx)'), function() {
                    const url = `/api/method/ap_automation.services.idfc_bank_excel_generator.download_idfc_event_settlement_excel?settlement_name=${encodeURIComponent(frm.doc.name)}`;
                    window.open(url, '_blank');
                }).addClass('btn-info');
            }
        }
    }
}
