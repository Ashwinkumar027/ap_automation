// Copyright (c) 2026, Quanti and contributors
// Unified Event Expense & Settlement Claim Controller (Stream B Ground Spends + Reconciliation + AD Sign-Off + IDFC Payout + Closure)
// 100% Mobile & Desktop Responsive

frappe.ui.form.on("Event Expense Claim", {
    onload: function(frm) {
        if (frm.is_new() && !frm.doc.posting_date) {
            frm.set_value('posting_date', frappe.datetime.get_today());
        }
    },

    refresh: function(frm) {
        frm.set_df_property('status', 'read_only', 1);
        if (frm.is_new() && !frm.doc.posting_date) {
            frm.set_value('posting_date', frappe.datetime.get_today());
        }

        const is_zero_refund = cint(frm.doc.is_zero_spend_refund) === 1;
        if (is_zero_refund && cint(frm.doc.is_final_settlement) !== 1 && frm.doc.docstatus === 0) {
            frm.set_value('is_final_settlement', 1);
        }
        frm.set_df_property('is_final_settlement', 'read_only', is_zero_refund ? 1 : 0);

        set_expense_claim_indicator(frm);
        frm.set_query('service_type', 'expense_items', function() {
            return { filters: { is_active: 1 } };
        });

        frappe.call({
            method: 'ap_automation.services.tds_service.get_all_active_tds_sections',
            callback: function(r) {
                if (r.message && r.message.length) {
                    const opts = r.message.map(m => m.display_label || m.name);
                    if (!opts.includes('None / Exempt')) opts.unshift('None / Exempt');
                    const opt_str = opts.join('\n');
                    const grid = frm.get_field('expense_items') && frm.get_field('expense_items').grid;
                    if (grid) {
                        const df = frappe.meta.get_docfield('Event Expense Item', 'tds_section', frm.doc.name);
                        if (df) df.options = opt_str;
                        frm.refresh_field('expense_items');
                    }
                }
            }
        });

        fetch_event_budget_snapshot(frm);

        if (frm.doc.docstatus === 1 && !frm.is_new()) {
            render_unified_claim_banner(frm, null);
            sync_submitted_claim_context(frm);
        } else {
            calculate_all_event_rows(frm, false);
            sync_live_claim_reconciliation(frm);
        }

        if (window.APReceiptGallery) {
            window.APReceiptGallery.refreshFormButtons(frm);
            if (!frm.is_new()) {
                window.APReceiptGallery.addPrintDownloadButtons(
                    frm,
                    'Event Expense Claim Report',
                    __('📄 Download Claim & Settlement PDF'),
                    __('🖨️ View Print Format')
                );
                window.APReceiptGallery.addExcelExportButton(frm);
                if (!is_zero_refund && (frm.doc.expense_items || []).length > 0) {
                    window.APReceiptGallery.addTallyXmlButton(
                        frm,
                        ['Submitted', 'Accounts Verified', 'Under Accounts Director Review', 'Approved for Payment', 'Settled']
                    );
                }
                if (['PAYABLE_TO_SPOC', 'REFUND_FROM_SPOC'].includes(frm.doc.settlement_type)) {
                    window.APReceiptGallery.addTallyXmlButton(
                        frm,
                        ['Approved for Payment', 'Settled'],
                        {
                            label: __('📑 Tally Settlement XML'),
                            voucher_mode: 'settlement',
                            filename: `Tally_Settlement_${frm.doc.name}.xml`
                        }
                    );
                }
            }
        }

        // DRAFT & IN-FLIGHT ACTIONS (docstatus === 0): Always keep Save active & visible
        if (frm.doc.docstatus === 0) {
            frm.page.set_primary_action(__('Save'), () => frm.save());
            frm.enable_save();
            if (frm.page.btn_primary) {
                frm.page.btn_primary.show().removeClass('hide');
            }
        }

        $(frm.wrapper).off('dirty.ap_eec_save_guard').on('dirty.ap_eec_save_guard', function() {
            if (frm.doc.docstatus === 0 && frm.page && frm.page.btn_primary) {
                frm.enable_save();
                frm.page.set_primary_action(__('Save'), () => frm.save());
                frm.page.btn_primary.show().removeClass('hide');
            }
        });

        if (frm.doc.docstatus === 0 && (frm.doc.status || 'Draft') === 'Draft') {

            if (frm.doc.event && !is_zero_refund) {
                frm.add_custom_button(__('📋 Populate from Imprest Proposal'), function() {
                    frappe.call({
                        method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.populate_from_imprest_proposal',
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
                                    row.base_amount = item.base_amount || item.amount;
                                    row.tax_type = item.tax_type || 'No GST / Exempt';
                                    row.gst_rate = item.gst_rate || '0%';
                                    row.tds_section = item.tds_section || 'None / Exempt';
                                    row.amount = item.amount;
                                    row.spend_stream = item.spend_stream;
                                    row.expense_category = item.expense_category;
                                    row.remarks = item.remarks;
                                });
                                calculate_all_event_rows(frm, false);
                                frm.refresh_field('expense_items');
                                frappe.show_alert({
                                    message: __(`✅ Loaded ${r.message.items_count} items from Advance #${r.message.advance_name}! Please attach receipt proofs.`),
                                    indicator: 'green'
                                }, 5);
                                sync_live_claim_reconciliation(frm);
                            }
                        }
                    });
                }).addClass('btn-default');
            }

            const submit_btn_label = is_zero_refund
                ? __('↩️ Submit Full Advance Refund')
                : __('🚀 Submit Expense & Settlement');

            frm.add_custom_button(submit_btn_label, function() {
                if (!validate_claim_before_submit(frm)) return;

                const confirm_msg = is_zero_refund
                    ? __('Submit Zero-Spend Full Advance Refund to <b>Accounts L1</b> for bank credit verification &amp; Event closure?')
                    : __('Submit Event Expense &amp; Settlement Claim for <b>Accounts Verification &amp; Reconciliation</b>?');

                frappe.confirm(confirm_msg, function() {
                    const do_submit = () => {
                        frappe.call({
                            method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.submit_event_expense_claim',
                            args: { claim_name: frm.doc.name },
                            freeze: true,
                            freeze_message: __('Submitting Claim & Reconciliation...'),
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
                });
            }).addClass('btn-primary').css({
                'background-color': '#2563eb',
                'border-color': '#1d4ed8',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }

        // Submitted Stages (docstatus === 1) are rendered cleanly via sync_submitted_claim_context(frm)
        // using live reconciliation math + AP Approval Matrix & HRMS Leave Delegate context.

        // RESUBMIT FOR SPOC WHEN RETURNED
        const is_spoc_or_owner = (frm.doc.spoc === frappe.session.user || frm.doc.owner === frappe.session.user || frappe.user.has_role(['Accounts Manager', 'System Manager']) || frappe.session.user === 'Administrator');
        if (frm.doc.status === 'Returned to SPOC') {
            const ret_reason = frappe.utils.escape_html(frm.doc.rejection_reason || 'Discrepancy flagged by Accounts.');
            const origin = frappe.utils.escape_html(frm.doc.return_origin_stage || 'Accounts Review');
            const base_amt = flt(frm.doc.rejection_baseline_amount || 0);
            const is_ad_stage = origin === 'Under Accounts Director Review';

            const banner_html = `
                <div class="ap-claim-return-banner" style="background: #fff7ed; border: 1px solid #fed7aa; border-left: 4px solid #ea580c; border-radius: 6px; padding: 12px 16px; margin: 12px 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span style="font-weight: 700; color: #9a3412; font-size: 13px;">⚠️ Claim Returned to SPOC for Revision</span>
                        <span style="font-size: 11px; font-weight: 700; background: #ea580c; color: #fff; padding: 2px 8px; border-radius: 4px;">Stage: ${origin}</span>
                    </div>
                    <div style="font-size: 12px; color: #7c2d12; margin-bottom: 6px;"><b>Reviewer Feedback:</b> ${ret_reason}</div>
                    <div style="font-size: 11px; color: #9a3412;">
                        ⚡ <b>Fast-Tracker Active:</b> If revised claim total is &le; <b>₹ ${frappe.format(base_amt, { fieldtype: 'Currency' })}</b>, 
                        resubmission fast-tracks directly back to <b>${is_ad_stage ? 'Accounts Director (Bypasses Accounts L1 Audit)' : origin}</b>.
                    </div>
                </div>
            `;
            $(frm.wrapper).find('.ap-claim-return-banner').remove();
            $(frm.wrapper).find('.form-page').first().prepend(banner_html);
        }

        if (frm.doc.status === 'Returned to SPOC' && is_spoc_or_owner) {
            if (frm.page.btn_primary && frm.page.btn_primary.text().trim() === __('Submit')) {
                frm.page.set_primary_action(__('Save'), () => frm.save());
            }
            const is_ad_origin = frm.doc.return_origin_stage === 'Under Accounts Director Review';
            const btn_label = is_ad_origin ? __('🚀 Fast-Track Resubmit to Accounts Director') : __('🚀 Resubmit Corrected Claim');
            frm.add_custom_button(btn_label, function() {
                if (!validate_claim_before_submit(frm)) return;
                const do_resubmit = () => {
                    frappe.call({
                        method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.resubmit_event_claim',
                        args: { claim_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Resubmitting Corrected Claim...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                };
                if (frm.is_dirty()) {
                    frm.save().then(() => do_resubmit());
                } else {
                    do_resubmit();
                }
            }).addClass('btn-primary').css({
                'background-color': '#059669',
                'border-color': '#047857',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }

        // Strictly pin Event Expense Item.expense_category options to valid Event categories
        const event_categories = [
            '',
            'Venue & Stage',
            'Travel & Flights',
            'Local Conveyance',
            'Food & Catering',
            'Marketing & Collateral',
            'Stationery & Props',
            'Incidentals'
        ];
        if (frm.fields_dict && frm.fields_dict.expense_items && frm.fields_dict.expense_items.grid) {
            const grid = frm.fields_dict.expense_items.grid;
            const cat_df = grid.docfields ? grid.docfields.find(f => f.fieldname === 'expense_category') : null;
            const joined = event_categories.join('\n');
            if (cat_df && cat_df.options !== joined) {
                cat_df.options = joined;
                frm.refresh_field('expense_items');
            }
        }
    },

    event: function(frm) {
        if (frm.doc.event) {
            frappe.db.get_doc('Event Master', frm.doc.event).then(ev => {
                frm.set_value('company', ev.company);
                frm.set_value('spoc', ev.event_spoc);
                frm.set_value('spoc_name', ev.spoc_name);
                fetch_event_budget_snapshot(frm);
                sync_live_claim_reconciliation(frm);
            });
        } else {
            frm._event_budget_snap = null;
            render_unified_claim_banner(frm, null);
        }
    },

    is_final_settlement: function(frm) {
        sync_live_claim_reconciliation(frm);
    },

    is_zero_spend_refund: function(frm) {
        if (cint(frm.doc.is_zero_spend_refund) === 1) {
            frm.set_value('is_final_settlement', 1);
            frm.set_df_property('is_final_settlement', 'read_only', 1);
            frm.set_value('total_claim_amount', 0);
        } else {
            frm.set_df_property('is_final_settlement', 'read_only', 0);
        }
        sync_live_claim_reconciliation(frm);
    }
});

function add_return_to_spoc_button(frm) {
    return frm.add_custom_button(__('↩ Return to SPOC'), function() {
        frappe.prompt([
            {
                fieldname: 'reason',
                fieldtype: 'Small Text',
                label: __('Discrepancy / Return Reason'),
                reqd: 1
            }
        ], function(values) {
            frappe.call({
                method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.reject_or_return_event_claim',
                args: {
                    claim_name: frm.doc.name,
                    reason: values.reason
                },
                freeze: true,
                callback: function(r) {
                    if (r.message && r.message.status === 'SUCCESS') {
                        frappe.show_alert({ message: __('Claim returned to SPOC'), indicator: 'orange' });
                        frm.reload_doc();
                    }
                }
            });
        }, __('Return Claim for Revision'), __('Submit Return'));
    }).addClass('btn-danger');
}

function sync_submitted_claim_context(frm) {
    const seq = (frm._recon_seq || 0) + 1;
    frm._recon_seq = seq;

    frappe.call({
        method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.get_event_expense_ui_context',
        args: { claim_name: frm.doc.name },
        callback: function(r) {
            if (frm._recon_seq !== seq || !r.message) return;
            const ctx = r.message;
            const recon = ctx.reconciliation || null;
            if (recon && recon.settlement_type) {
                frm._live_recon_type = recon.settlement_type;
            }
            render_unified_claim_banner(frm, recon);
            bind_submitted_claim_buttons(frm, ctx, recon);
        }
    });
}

function bind_submitted_claim_buttons(frm, ctx, recon) {
    (frm._ap_eec_stage_btns || []).forEach($btn => {
        if ($btn && typeof $btn.remove === 'function') $btn.remove();
    });
    frm._ap_eec_stage_btns = [];

    if (frm.doc.docstatus !== 1) return;
    const add_stage_btn = ($btn) => {
        if ($btn) frm._ap_eec_stage_btns.push($btn);
        return $btn;
    };

    const status = frm.doc.status;
    const is_zero_refund = cint(frm.doc.is_zero_spend_refund) === 1;
    const is_final = cint(frm.doc.is_final_settlement) === 1 || is_zero_refund;
    const recon_type = (recon && recon.settlement_type) || frm._live_recon_type || frm.doc.settlement_type || 'PAYABLE_TO_SPOC';

    // STAGE 2: ACCOUNTS L1 AUDIT ON SUBMITTED CLAIM
    if (status === 'Submitted' && ctx.can_verify_l1) {
        let l1_btn_label = __('✅ Verify Ground Bills (Accounts L1)');
        let l1_default_remark = 'All ground receipts and expense categories verified.';
        if (!is_final || recon_type === 'INTERMEDIATE_CLAIM') {
            l1_btn_label = __('✅ Verify Intermediate Bills (Accounts L1)');
        } else if (recon_type === 'PAYABLE_TO_SPOC') {
            l1_btn_label = __('✅ Verify & Forward to Accounts Director');
            l1_default_remark = 'Ground bills & variance verified. Forwarded to Accounts Director for SPOC payout sign-off.';
        } else if (recon_type === 'REFUND_FROM_SPOC') {
            l1_btn_label = __('✅ Verify Bills & Confirm Bank Refund');
            l1_default_remark = 'Ground bills and SPOC bank refund credit UTR verified.';
        } else if (recon_type === 'ZERO_BALANCE_BALANCED') {
            l1_btn_label = __('✅ Verify & Close Balanced Event');
            l1_default_remark = 'All bills verified and matched advance (₹ 0.00 balance).';
        }

        add_stage_btn(frm.add_custom_button(l1_btn_label, function() {
            const prompt_fields = [
                {
                    fieldname: 'remarks',
                    fieldtype: 'Small Text',
                    label: __('Accounts L1 Verification Notes (Optional)'),
                    default: l1_default_remark
                }
            ];
            if (is_final && recon_type === 'REFUND_FROM_SPOC') {
                prompt_fields.unshift({
                    fieldname: 'verified_utr',
                    fieldtype: 'Data',
                    label: __('Verified Bank Credit UTR Reference (Refund)'),
                    default: frm.doc.refund_received_reference || '',
                    reqd: 1
                });
            }

            const open_l1_prompt = function() {
                frappe.prompt(prompt_fields, function(values) {
                    frappe.call({
                        method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.verify_event_expense_claim',
                        args: {
                            claim_name: frm.doc.name,
                            remarks: values.remarks,
                            verified_utr: values.verified_utr || ''
                        },
                        freeze: true,
                        freeze_message: __('Verifying & Updating Event Settlement...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Accounts L1 Audit & Reconciliation'), __('Confirm'));
            };

            const has_missing = (frm.doc.expense_items || []).some(row => !row.line_status || row.line_status === 'Pending' || row.is_disputed);
            if (has_missing) {
                frappe.confirm(
                    __('Some line items still have Pending/Disputed status. Mark claim verified anyway?'),
                    open_l1_prompt
                );
            } else {
                open_l1_prompt();
            }
        }).addClass('btn-primary'));

        if (!is_zero_refund && (frm.doc.expense_items || []).length > 0) {
            add_stage_btn(frm.add_custom_button(__('🏷️ Review / Edit GST & TDS'), function() {
                open_event_claim_tax_review_dialog(frm);
            }).addClass('btn-default'));
        }

        if (ctx.can_return_to_spoc) {
            add_stage_btn(add_return_to_spoc_button(frm));
        }
    }

    // STAGE 3: ACCOUNTS DIRECTOR SIGN-OFF ON PAYABLE_TO_SPOC
    if (status === 'Under Accounts Director Review' && ctx.can_ad_sign_off) {
        add_stage_btn(frm.add_custom_button(__('⭐ Accounts Director Sign-Off'), function() {
            frappe.prompt([
                {
                    fieldname: 'remarks',
                    fieldtype: 'Small Text',
                    label: __('Accounts Director Sign-Off Remarks (Optional)'),
                    default: 'Verified bills & settlement variance. Approved for IDFC SPOC Reimbursement.'
                }
            ], function(vals) {
                frappe.call({
                    method: 'ap_automation.services.event_settlement_service.authorize_event_claim_by_accounts_director',
                    args: {
                        claim_name: frm.doc.name,
                        remarks: vals.remarks
                    },
                    freeze: true,
                    freeze_message: __('Signing Off & Moving to Payment Release...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: r.message.message, indicator: 'green' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Accounts Director Sign-Off'), __('Authorize Payout'));
        }).addClass('btn-primary'));

        if (ctx.can_return_to_spoc) {
            add_stage_btn(add_return_to_spoc_button(frm));
        }
    }

    // STAGE 4: IDFC EXCEL EXPORT + MAKER PAYMENT RELEASE + CHECKER EXECUTE PAYOUT
    if (status === 'Approved for Payment' && frm.doc.settlement_type === 'PAYABLE_TO_SPOC' && ctx.is_finance_viewer) {
        add_stage_btn(frm.add_custom_button(__('🏛️ IDFC Bank Disbursal Excel (.xlsx)'), function() {
            const url = `/api/method/ap_automation.services.idfc_bank_excel_generator.download_idfc_event_expense_claim_excel?claim_name=${encodeURIComponent(frm.doc.name)}`;
            window.open(url, '_blank');
            frappe.show_alert({ message: __('IDFC SPOC Net Reimbursement Excel (.xlsx) downloaded.'), indicator: 'blue' });
        }).addClass('btn-info'));

        if (frm.doc.payment_release_notified) {
            add_stage_btn(frm.add_custom_button(__('✓ Payment Release Sent (IDFC Uploaded)'), function() {
                const notif_date = frm.doc.payment_release_notified_on ? frappe.datetime.str_to_user(frm.doc.payment_release_notified_on) : 'Recently';
                frappe.msgprint({
                    title: __('Payment Release Already Notified'),
                    message: __('Uploaded on {0} by {1}. Awaiting Payment Releaser ({2}) to execute SPOC reimbursement.', [notif_date, frm.doc.payment_release_maker || 'Maker', frm.doc.payment_releaser || 'Checker']),
                    indicator: 'green'
                });
            }).addClass('btn-success disabled'));
        } else if (ctx.can_maker_release) {
            add_stage_btn(frm.add_custom_button(__('📤 Payment Release'), function() {
                frappe.confirm(
                    __('Confirm the IDFC Disbursal Excel (.xlsx) has been uploaded to IDFC Netbanking.<br><br>This notifies the designated <b>Payment Releaser (Checker)</b> to release the net SPOC reimbursement.'),
                    function() {
                        frappe.call({
                            method: 'ap_automation.services.event_settlement_service.trigger_event_claim_payment_release_notification',
                            args: { claim_name: frm.doc.name },
                            freeze: true,
                            freeze_message: __('Notifying Payment Releaser...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'SUCCESS') {
                                    frappe.show_alert({ message: r.message.message, indicator: 'green' }, 5);
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            }).addClass('btn-warning'));
        }

        const not_same_maker = (frm.doc.payment_release_maker !== frappe.session.user) || frappe.session.user === 'Administrator';
        if (frm.doc.payment_release_notified && ctx.can_checker_disburse && not_same_maker) {
            add_stage_btn(frm.add_custom_button(__('💳 Execute SPOC Reimbursement'), function() {
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
                        method: 'ap_automation.services.event_settlement_service.disburse_event_claim_spoc_payout',
                        args: {
                            claim_name: frm.doc.name,
                            payment_reference: vals.payment_ref
                        },
                        freeze: true,
                        freeze_message: __('Recording SPOC Payout & Closing Event...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Execute SPOC Reimbursement'), __('Confirm & Close Event'));
            }).addClass('btn-primary'));
        }
    }

    // STAGE 5: SETTLED & CLOSED -> Keep IDFC Export accessible for audit
    if (status === 'Settled' && frm.doc.settlement_type === 'PAYABLE_TO_SPOC' && ctx.is_finance_viewer) {
        add_stage_btn(frm.add_custom_button(__('🏛️ IDFC Bank Disbursal Excel (.xlsx)'), function() {
            const url = `/api/method/ap_automation.services.idfc_bank_excel_generator.download_idfc_event_expense_claim_excel?claim_name=${encodeURIComponent(frm.doc.name)}`;
            window.open(url, '_blank');
        }).addClass('btn-info'));
    }
}

function validate_claim_before_submit(frm) {
    if (!frm.doc.event) {
        frappe.msgprint({
            title: __('Missing Event'),
            indicator: 'red',
            message: __('Please select a <b>Linked Event Master</b> before submitting.')
        });
        frm.scroll_to_field('event');
        return false;
    }

    if (cint(frm.doc.is_zero_spend_refund) === 1) {
        const utr = (frm.doc.refund_received_reference || '').trim();
        if (utr.length < 4) {
            frappe.msgprint({
                title: __('Missing Refund UTR'),
                indicator: 'red',
                message: __('Please enter the <b>Corporate Bank Refund UTR / Ref</b> (at least 4 characters) before submitting a Zero-Spend Advance Refund.')
            });
            frm.scroll_to_field('refund_received_reference');
            return false;
        }
        return true;
    }

    const items = frm.doc.expense_items || [];
    if (items.length === 0) {
        frappe.msgprint({
            title: __('Missing Expense Items'),
            indicator: 'red',
            message: __('Please add at least one expense line item with a receipt (or enable <b>Zero-Spend Full Advance Refund</b> if returning unused advance with zero bills).')
        });
        frm.scroll_to_field('expense_items');
        return false;
    }

    for (let i = 0; i < items.length; i++) {
        const row = items[i];
        if (!row.expense_category) {
            frappe.msgprint({
                title: __('Missing Expense Category'),
                indicator: 'red',
                message: __(`Row #${i + 1}: Expense Category is mandatory.`)
            });
            return false;
        }
        if (!row.receipt_attachment) {
            frappe.msgprint({
                title: __('Missing Receipt Proof'),
                indicator: 'red',
                message: __(`Row #${i + 1}: Receipt attachment is mandatory before submitting.`)
            });
            return false;
        }
    }
    return true;
}

function set_expense_claim_indicator(frm) {
    const status = frm.doc.status || 'Draft';
    const colors = {
        'Draft': 'grey',
        'Submitted': 'blue',
        'Returned to SPOC': 'orange',
        'Accounts Verified': 'teal',
        'Under Accounts Director Review': 'purple',
        'Approved for Payment': 'blue',
        'Settled': 'green',
        'Rejected': 'red'
    };
    frm.page.set_indicator(__(status), colors[status] || 'grey');
}

function compute_local_items_total(frm) {
    if (cint(frm.doc.is_zero_spend_refund) === 1) return 0.0;
    let total = 0.0;
    (frm.doc.expense_items || []).forEach(row => {
        total += parseFloat(row.amount || 0.0);
    });
    return Math.round(total * 100) / 100;
}

function sync_live_claim_reconciliation(frm) {
    const local_total = compute_local_items_total(frm);
    if (!frm.doc.event) {
        render_unified_claim_banner(frm, null);
        return;
    }

    // Immediate paint from existing doc / local rows while fresh reconciliation loads
    render_unified_claim_banner(frm, null);

    const seq = (frm._recon_seq || 0) + 1;
    frm._recon_seq = seq;

    frappe.call({
        method: 'ap_automation.services.event_settlement_service.calculate_event_claim_reconciliation',
        args: {
            event_name: frm.doc.event,
            current_claim_name: frm.is_new() ? '' : frm.doc.name,
            current_claim_amount: local_total,
            is_final_settlement: cint(frm.doc.is_final_settlement) ? 1 : 0,
            is_zero_spend_refund: cint(frm.doc.is_zero_spend_refund) ? 1 : 0
        },
        callback: function(r) {
            if (frm._recon_seq !== seq || !r.message) return;
            const d = r.message;
            frm._live_recon_type = d.settlement_type;

            if (frm.doc.docstatus === 0) {
                frm.doc.disbursed_advance = d.disbursed_advance;
                frm.doc.prior_verified_claims = d.prior_verified_claims;
                frm.doc.cumulative_spoc_spends = d.cumulative_spoc_spends;
                frm.doc.settlement_delta = d.settlement_delta;
                frm.doc.settlement_type = d.settlement_type;
                frm.doc.net_payable_to_spoc = d.net_payable_to_spoc;
                frm.doc.refund_receivable_from_spoc = d.refund_receivable_from_spoc;
                ['disbursed_advance', 'prior_verified_claims', 'cumulative_spoc_spends', 'settlement_delta', 'settlement_type', 'net_payable_to_spoc', 'refund_receivable_from_spoc'].forEach(fn => {
                    frm.refresh_field(fn);
                });
            }
            render_unified_claim_banner(frm, d);
        }
    });
}

function render_unified_claim_banner(frm, recon) {
    if (!frm.dashboard) return;

    const status = frm.doc.status || 'Draft';
    const is_zero_refund = cint(frm.doc.is_zero_spend_refund) === 1;
    const is_final = is_zero_refund || cint(frm.doc.is_final_settlement) === 1;
    const s_type = (recon && recon.settlement_type) || frm.doc.settlement_type || (is_final ? 'PAYABLE_TO_SPOC' : 'INTERMEDIATE_CLAIM');
    const local_total = compute_local_items_total(frm);

    const adv = recon ? parseFloat(recon.disbursed_advance || 0) : parseFloat(frm.doc.disbursed_advance || 0);
    const prior = recon ? parseFloat(recon.prior_verified_claims || 0) : parseFloat(frm.doc.prior_verified_claims || 0);
    const cum_spends = recon ? parseFloat(recon.cumulative_spoc_spends || 0) : (prior + local_total);
    const payable = recon ? parseFloat(recon.net_payable_to_spoc || 0) : parseFloat(frm.doc.net_payable_to_spoc || 0);
    const refund = recon ? parseFloat(recon.refund_receivable_from_spoc || 0) : parseFloat(frm.doc.refund_receivable_from_spoc || 0);
    const rem_adv = recon ? parseFloat(recon.remaining_advance_balance || 0) : Math.max(adv - cum_spends, 0);

    const is_payable_path = is_final && s_type === 'PAYABLE_TO_SPOC';
    const steps = is_payable_path ? [
        { label: '1. Draft (SPOC)' },
        { label: '2. Accounts L1 Audit' },
        { label: '3. Accounts Director' },
        { label: '4. IDFC & Release' },
        { label: '5. Settled & Closed' }
    ] : [
        { label: '1. Draft (SPOC)' },
        { label: '2. Accounts L1 Audit' },
        { label: is_final ? '3. Settled & Closed' : '3. Accounts Verified' }
    ];

    let active_idx = 0;
    if (is_payable_path) {
        if (status === 'Submitted') active_idx = 1;
        else if (status === 'Under Accounts Director Review') active_idx = 2;
        else if (status === 'Approved for Payment') active_idx = 3;
        else if (status === 'Settled') active_idx = 5;
        else if (status === 'Returned to SPOC' || status === 'Rejected') active_idx = -1;
    } else {
        if (status === 'Submitted') active_idx = 1;
        else if (status === 'Accounts Verified' || status === 'Settled') active_idx = 3;
        else if (status === 'Returned to SPOC' || status === 'Rejected') active_idx = -1;
    }

    const stepper_nodes = steps.map((s, idx) => {
        let cls = '';
        let badge = idx + 1;
        if (status === 'Rejected') {
            cls = idx === 0 ? 'step-completed' : 'step-rejected';
            badge = idx === 0 ? '✓' : '✕';
        } else if (status === 'Returned to SPOC') {
            cls = idx === 0 ? 'step-returned' : '';
            badge = idx === 0 ? '↩' : idx + 1;
        } else if (idx < active_idx) {
            cls = 'step-completed';
            badge = '✓';
        } else if (idx === active_idx) {
            cls = 'step-active';
        }
        return `<div class="ap-step-item ${cls}"><div class="ap-step-node">${badge}</div><div class="ap-step-label">${s.label}</div></div>`;
    }).join('');

    let items_count = (frm.doc.expense_items || []).length;
    let missing_receipts = 0;
    if (!is_zero_refund) {
        (frm.doc.expense_items || []).forEach(row => {
            if (!row.receipt_attachment) missing_receipts++;
        });
    }

    const format_curr = (val) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(val || 0);

    let tot_base = 0.0, tot_gst = 0.0, tot_tds = 0.0;
    if (!is_zero_refund) {
        (frm.doc.expense_items || []).forEach(row => {
            const b = parseFloat(row.base_amount || 0) > 0 ? parseFloat(row.base_amount || 0) : parseFloat(row.amount || 0);
            tot_base += b;
            tot_gst += parseFloat(row.gst_amount || 0);
            tot_tds += parseFloat(row.tds_amount || 0);
        });
    }

    const b_snap = frm._event_budget_snap || null;
    let budget_pill_html = '';
    if (b_snap && parseFloat(b_snap.allocated_budget || 0) > 0) {
        const alloc = parseFloat(b_snap.allocated_budget || 0);
        const committed = Math.max(parseFloat(b_snap.committed_with_pipeline || b_snap.total_committed_spend || 0), cum_spends);
        const rem = Math.round((alloc - committed) * 100) / 100;
        const is_over = rem < 0;
        budget_pill_html = `
            <div style="margin-top: 8px; padding: 6px 10px; border-radius: 6px; background: ${is_over ? '#fef2f2' : '#f0fdf4'}; border: 1px solid ${is_over ? '#fecaca' : '#bbf7d0'}; color: ${is_over ? '#991b1b' : '#166534'}; font-size: 11px; font-weight: 700;">
                ${is_over
                    ? `⚠️ Budget Reminder (Not Blocked): Event Budget ${format_curr(alloc)} &bull; Total Committed ${format_curr(committed)} &bull; Over Budget by ${format_curr(Math.abs(rem))}`
                    : `📊 Budget Snapshot: Event Budget ${format_curr(alloc)} &bull; Total Committed ${format_curr(committed)} &bull; Remaining ${format_curr(rem)}`}
            </div>
        `;
    }

    let bg = '#eff6ff', border = '#bfdbfe', text = '#1e40af', badge_bg = '#dbeafe';
    let verdict_title = 'SETTLEMENT SUMMARY: PAYABLE TO SPOC';
    let verdict_desc = `Total Bills (${format_curr(cum_spends)}) exceeded Cash Advance (${format_curr(adv)}). Accounts Director sign-off & payout happen right here.`;
    let metric_label = 'NET PAYABLE';
    let metric_val = format_curr(payable);

    if (!is_final || s_type === 'INTERMEDIATE_CLAIM') {
        bg = '#f8fafc'; border = '#cbd5e1'; text = '#334155'; badge_bg = '#e2e8f0';
        verdict_title = 'PARTIAL EXPENSE BATCH (MORE BILLS COMING)';
        verdict_desc = `Bills verified against Advance (${format_curr(adv)}). Remaining advance after this batch: ${format_curr(rem_adv)}. Event stays open until final claim.`;
        metric_label = 'THIS CLAIM';
        metric_val = format_curr(local_total);
    } else if (s_type === 'REFUND_FROM_SPOC') {
        bg = '#fff7ed'; border = '#fed7aa'; text = '#c2410c'; badge_bg = '#ffedd5';
        verdict_title = is_zero_refund ? 'FULL ADVANCE REFUND DUE FROM SPOC' : 'UNSPENT ADVANCE REFUND DUE FROM SPOC';
        verdict_desc = `Cash Advance (${format_curr(adv)}) exceeded Total Bills (${format_curr(cum_spends)}). Enter Corporate Bank Refund UTR; closes once Accounts L1 confirms credit.`;
        metric_label = 'REFUND TO COMPANY';
        metric_val = format_curr(refund);
    } else if (s_type === 'ZERO_BALANCE_BALANCED') {
        bg = '#ecfdf5'; border = '#a7f3d0'; text = '#047857'; badge_bg = '#d1fae5';
        verdict_title = 'BALANCED SETTLEMENT (₹ 0.00 DIFFERENCE)';
        verdict_desc = `Total Bills (${format_curr(cum_spends)}) match Disbursed Cash Advance (${format_curr(adv)}). Closes immediately after Accounts L1 verification.`;
        metric_label = 'NET DIFFERENCE';
        metric_val = format_curr(0);
    }

    const blocking_html = (recon && recon.blocking_open_claims && recon.blocking_open_claims.length)
        ? `<div style="margin-top: 8px; padding: 6px 10px; border-radius: 6px; background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; font-size: 11px; font-weight: 700;">⚠️ Other open claim(s) still in review on this Event: ${recon.blocking_open_claims.join(', ')}. Complete or return them before closing Event.</div>`
        : '';

    const banner_html = `
        <div class="ap-stepper-wrapper" style="margin-bottom: 12px;">
            <div class="ap-stepper-trail">${stepper_nodes}</div>
        </div>
        <div class="ap-stream-demarcation-card" style="
            background: ${bg};
            border: 1px solid ${border};
            border-radius: 10px;
            padding: 14px 18px;
            margin-bottom: 16px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        ">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
                <div style="flex: 1; min-width: 240px;">
                    <div style="font-size: 11px; font-weight: 800; color: ${text}; letter-spacing: 0.04em; text-transform: uppercase;">
                        ${verdict_title} &bull; ${frappe.utils.escape_html(status)}
                    </div>
                    <div style="font-size: 12px; color: #334155; margin-top: 4px; line-height: 1.4;">
                        ${verdict_desc}
                    </div>
                    <div style="display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; font-size: 11px; font-weight: 700; color: #475569;">
                        <span>💵 Cash Advance: ${format_curr(adv)}</span>
                        <span>|</span>
                        <span>🧾 Prior Bills: ${format_curr(prior)}</span>
                        <span>|</span>
                        <span>📝 This Claim Net: ${format_curr(local_total)}</span>
                        ${(!is_zero_refund && items_count > 0) ? `<span>|</span><span>🏷️ Base ${format_curr(tot_base)} + GST ${format_curr(tot_gst)} - TDS ${format_curr(tot_tds)}</span>` : ''}
                        ${(!is_zero_refund && items_count > 0) ? `<span>|</span><span style="color: ${missing_receipts > 0 ? '#b91c1c' : '#047857'};">${missing_receipts > 0 ? `⚠️ ${missing_receipts}/${items_count} missing receipts` : `✅ ${items_count} receipts attached`}</span>` : ''}
                    </div>
                    ${budget_pill_html}
                    ${blocking_html}
                </div>

                <div style="background: #ffffff; border: 1.5px solid ${border}; border-radius: 8px; padding: 8px 14px; text-align: right; min-width: 145px;">
                    <div style="font-size: 10px; font-weight: 800; color: ${text}; text-transform: uppercase;">${metric_label}</div>
                    <div style="font-size: 19px; font-weight: 800; color: ${text};">${metric_val}</div>
                </div>
            </div>
        </div>
    `;

    if (window.APReceiptGallery && typeof window.APReceiptGallery.setHeadlineExclusive === 'function') {
        window.APReceiptGallery.setHeadlineExclusive(frm, banner_html);
    } else {
        if (typeof frm.dashboard.clear_headline === 'function') frm.dashboard.clear_headline();
        if (frm.layout && frm.layout.message) frm.layout.message.empty().addClass('hidden');
        frm.dashboard.set_headline(banner_html);
    }
}

function fetch_event_budget_snapshot(frm) {
    if (!frm.doc.event) {
        frm._event_budget_snap = null;
        return;
    }
    frappe.call({
        method: 'ap_automation.services.event_budget_service.get_event_budget_snapshot',
        args: { event_name: frm.doc.event },
        callback: function(r) {
            if (r.message) {
                frm._event_budget_snap = r.message;
                render_unified_claim_banner(frm, null);
            }
        }
    });
}

function get_tds_rate_from_section(section) {
    if (!section || section === 'None / Exempt') return 0.0;
    const m = String(section).match(/\((\d+(?:\.\d+)?)\s*%\)/);
    return m ? parseFloat(m[1]) : 0.0;
}

function calculate_event_row_statutory(frm, cdt, cdn, sync_recon = true) {
    const row = locals[cdt] && locals[cdt][cdn];
    if (!row) return;

    let base = flt(row.base_amount);
    if (base <= 0 && flt(row.amount) > 0) {
        base = flt(row.amount);
        row.base_amount = base;
    }

    const tax_type = (row.tax_type || 'No GST / Exempt').trim();
    let gst_amt = 0.0, cgst = 0.0, sgst = 0.0, igst = 0.0;
    if (tax_type === 'No GST / Exempt') {
        row.gst_rate = '0%';
    } else {
        const gst_pct = flt(String(row.gst_rate || '0%').replace('%', '').trim());
        gst_amt = Math.round(base * (gst_pct / 100.0) * 100) / 100;
        if (tax_type.indexOf('Inter-State') !== -1 || tax_type.indexOf('IGST') !== -1) {
            igst = gst_amt;
        } else {
            cgst = Math.round((gst_amt / 2.0) * 100) / 100;
            sgst = Math.round((gst_amt - cgst) * 100) / 100;
        }
    }

    const total_bill = Math.round((base + gst_amt) * 100) / 100;
    const tds_rate = get_tds_rate_from_section(row.tds_section);
    const tds_amt = Math.round(base * (tds_rate / 100.0) * 100) / 100;
    const net_amt = Math.round((total_bill - tds_amt) * 100) / 100;

    row.cgst_amount = cgst;
    row.sgst_amount = sgst;
    row.igst_amount = igst;
    row.gst_amount = gst_amt;
    row.total_invoice_amount = total_bill;
    row.tds_rate = tds_rate;
    row.tds_amount = tds_amt;
    row.amount = net_amt;

    frm.refresh_field('expense_items');
    calculate_all_event_rows(frm, sync_recon);
}

function calculate_all_event_rows(frm, sync_recon = true) {
    if (cint(frm.doc.is_zero_spend_refund) === 1) return;
    let tot_base = 0, tot_cgst = 0, tot_sgst = 0, tot_igst = 0, tot_gst = 0, tot_tds = 0, tot_net = 0;
    (frm.doc.expense_items || []).forEach(row => {
        let base = flt(row.base_amount);
        if (base <= 0 && flt(row.amount) > 0) {
            base = flt(row.amount);
            row.base_amount = base;
        }
        tot_base += base;
        tot_cgst += flt(row.cgst_amount);
        tot_sgst += flt(row.sgst_amount);
        tot_igst += flt(row.igst_amount);
        tot_gst += flt(row.gst_amount);
        tot_tds += flt(row.tds_amount);
        tot_net += flt(row.amount);
    });
    if (frm.doc.docstatus === 0) {
        frm.doc.total_base_amount = Math.round(tot_base * 100) / 100;
        frm.doc.total_cgst_amount = Math.round(tot_cgst * 100) / 100;
        frm.doc.total_sgst_amount = Math.round(tot_sgst * 100) / 100;
        frm.doc.total_igst_amount = Math.round(tot_igst * 100) / 100;
        frm.doc.total_gst_amount = Math.round(tot_gst * 100) / 100;
        frm.doc.total_tds_amount = Math.round(tot_tds * 100) / 100;
        frm.doc.total_claim_amount = Math.round(tot_net * 100) / 100;
        frm.doc.total_amount = Math.round(tot_net * 100) / 100;
        ['total_base_amount', 'total_cgst_amount', 'total_sgst_amount', 'total_igst_amount', 'total_gst_amount', 'total_tds_amount', 'total_claim_amount'].forEach(fn => frm.refresh_field(fn));
    }
    if (sync_recon) {
        sync_live_claim_reconciliation(frm);
    } else {
        render_unified_claim_banner(frm, null);
    }
}

function open_event_claim_tax_review_dialog(frm) {
    const items = frm.doc.expense_items || [];
    if (!items.length) return;

    const tds_df = frappe.meta.get_docfield('Event Expense Item', 'tds_section', frm.doc.name);
    const tds_opts = (tds_df && tds_df.options) || 'None / Exempt';

    const d = new frappe.ui.Dialog({
        title: __('Accounts GST & TDS Review — {0}', [frm.doc.name]),
        size: 'extra-large',
        fields: [
            {
                fieldname: 'info_html',
                fieldtype: 'HTML',
                options: '<div style="font-size:12px;color:#475569;margin-bottom:8px;">Review or reclassify GST Type, GST %, and TDS Section per bill. Net Claim, Advance Settlement Balance, and Event Master ledger update automatically on save.</div>'
            },
            {
                fieldname: 'rows',
                fieldtype: 'Table',
                label: __('Expense Bills'),
                cannot_add_rows: true,
                cannot_delete_rows: true,
                in_place_edit: true,
                data: items.map(r => ({
                    row_name: r.name,
                    vendor_name: r.vendor_name,
                    bill_number: r.bill_number,
                    expense_category: r.expense_category,
                    base_amount: flt(r.base_amount) || flt(r.amount),
                    tax_type: r.tax_type || 'No GST / Exempt',
                    gst_rate: r.gst_rate || '0%',
                    tds_section: r.tds_section || 'None / Exempt',
                    tax_id: r.tax_id || ''
                })),
                fields: [
                    { fieldname: 'row_name', fieldtype: 'Data', label: 'Row ID', hidden: 1 },
                    { fieldname: 'vendor_name', fieldtype: 'Data', label: 'Vendor', read_only: 1, in_list_view: 1, columns: 2 },
                    { fieldname: 'bill_number', fieldtype: 'Data', label: 'Bill #', read_only: 1, in_list_view: 1, columns: 1 },
                    { fieldname: 'base_amount', fieldtype: 'Currency', label: 'Base (₹)', in_list_view: 1, columns: 1 },
                    { fieldname: 'tax_type', fieldtype: 'Select', label: 'GST Type', options: 'No GST / Exempt\nIntra-State (CGST + SGST)\nInter-State (IGST)', in_list_view: 1, columns: 2 },
                    { fieldname: 'gst_rate', fieldtype: 'Select', label: 'GST %', options: '0%\n5%\n12%\n18%\n28%', in_list_view: 1, columns: 1 },
                    { fieldname: 'tds_section', fieldtype: 'Select', label: 'TDS Section', options: tds_opts, in_list_view: 1, columns: 2 },
                    { fieldname: 'tax_id', fieldtype: 'Data', label: 'GSTIN', in_list_view: 1, columns: 1 }
                ]
            }
        ],
        primary_action_label: __('Apply GST & TDS Updates'),
        primary_action(vals) {
            const payload = (vals.rows || []).map(r => ({
                name: r.row_name,
                base_amount: flt(r.base_amount),
                tax_type: r.tax_type,
                gst_rate: r.gst_rate,
                tds_section: r.tds_section,
                tax_id: r.tax_id
            }));
            frappe.call({
                method: 'ap_automation.ap_automation.doctype.event_expense_claim.event_expense_claim.update_event_claim_tax_classification',
                args: {
                    claim_name: frm.doc.name,
                    items_json: JSON.stringify(payload)
                },
                freeze: true,
                freeze_message: __('Recalculating GST, TDS & Settlement Ledger...'),
                callback: function(r) {
                    if (r.message && r.message.status === 'SUCCESS') {
                        d.hide();
                        frappe.show_alert({ message: __('✅ GST & TDS updated and synced.'), indicator: 'green' }, 5);
                        frm.reload_doc();
                    }
                }
            });
        }
    });
    d.show();
}

frappe.ui.form.on("Event Expense Item", {
    vendor: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.vendor) {
            frappe.db.get_value('Supplier', row.vendor, ['supplier_name', 'gstin', 'tax_id'], r => {
                if (r) {
                    if (r.supplier_name) frappe.model.set_value(cdt, cdn, 'vendor_name', r.supplier_name);
                    if (r.gstin || r.tax_id) frappe.model.set_value(cdt, cdn, 'tax_id', r.gstin || r.tax_id);
                }
            });
        }
    },
    service_type: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.service_type) {
            frappe.db.get_value('AP Service Type Master', row.service_type, 'default_tds_section', r => {
                if (r && r.default_tds_section) {
                    frappe.model.set_value(cdt, cdn, 'tds_section', r.default_tds_section);
                }
            });
        }
    },
    base_amount: function(frm, cdt, cdn) {
        calculate_event_row_statutory(frm, cdt, cdn);
    },
    tax_type: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row.tax_type !== 'No GST / Exempt' && (!row.gst_rate || row.gst_rate === '0%')) {
            row.gst_rate = '18%';
        }
        calculate_event_row_statutory(frm, cdt, cdn);
    },
    gst_rate: function(frm, cdt, cdn) {
        calculate_event_row_statutory(frm, cdt, cdn);
    },
    tds_section: function(frm, cdt, cdn) {
        calculate_event_row_statutory(frm, cdt, cdn);
    },
    amount: function(frm) {
        calculate_all_event_rows(frm, true);
    },
    receipt_attachment: function(frm) {
        render_unified_claim_banner(frm, null);
        if (window.APReceiptGallery) {
            window.APReceiptGallery.refreshFormButtons(frm);
        }
    },
    expense_items_remove: function(frm) {
        calculate_all_event_rows(frm, true);
        if (window.APReceiptGallery) {
            window.APReceiptGallery.refreshFormButtons(frm);
        }
    }
});
