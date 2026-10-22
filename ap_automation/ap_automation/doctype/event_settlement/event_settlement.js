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
    setup: function(frm) {
        if (window.APReceiptGallery && typeof window.APReceiptGallery.setup === 'function') {
            window.APReceiptGallery.setup(frm);
        }
    },

    refresh: function(frm) {
        render_settlement_verdict_card(frm);
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

function render_settlement_verdict_card(frm) {
    if (!frm.dashboard || !frm.doc.settlement_type) return;

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

    frm.dashboard.set_headline(card_html);
}

function setup_settlement_workflow_actions(frm) {
    if (frm.doc.docstatus === 1) {
        const user_roles = frappe.user_roles || [];
        const is_sys_mgr = user_roles.includes('System Manager') || frappe.session.user === 'Administrator';
        const is_accounts = user_roles.includes('Accounts L1 Auditor') || user_roles.includes('Accounts Director') || user_roles.includes('Accounts Manager') || user_roles.includes('Payment Releaser') || is_sys_mgr;

        if (frm.doc.status === 'Under Accounts Review') {
            frm.page.set_indicator(__('Under Accounts Review'), 'orange');

            if (is_accounts) {
                if (frm.doc.settlement_type === 'REFUND_FROM_SPOC') {
                    frm.add_custom_button(__('✅ Audit & Verify Bank Refund'), function() {
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
                    }).addClass('btn-success');
                } else if (frm.doc.settlement_type === 'PAYABLE_TO_SPOC') {
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
            }
        } else if (frm.doc.status === 'Settled') {
            frm.page.set_indicator(__('Settled & Closed'), 'green');
        }
    }
}
