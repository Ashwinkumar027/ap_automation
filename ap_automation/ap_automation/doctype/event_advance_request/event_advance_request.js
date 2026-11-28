// Copyright (c) 2026, Quanti and contributors
// Event Advance Request Controller (Lane 4 Intake & 4-Tier AP Matrix Approval)
// 100% Mobile & Desktop Responsive

frappe.ui.form.on("Event Advance Request", {
    onload: function(frm) {
        setup_advance_spoc_query(frm);
    },
    refresh: function(frm) {
        setup_advance_spoc_query(frm);
        setTimeout(() => bind_imprest_grid_uploaders(frm), 250);
        frm.set_df_property('status', 'read_only', 1);
        calculate_imprest_totals(frm);
        set_advance_status_indicator(frm);
        if (frm.doc.docstatus === 1 && !frm.is_new()) {
            set_advance_headline(frm, build_advance_stepper_html(frm, '', null));
        } else {
            render_advance_event_context(frm);
        }

        if (window.APReceiptGallery) {
            window.APReceiptGallery.refreshFormButtons(frm);
            if (!frm.is_new()) {
                window.APReceiptGallery.addPrintDownloadButtons(
                    frm,
                    'Event Expense Report',
                    __('📄 Download Imprest PDF'),
                    __('🖨️ View Print Format')
                );
                window.APReceiptGallery.addExcelExportButton(frm);
                window.APReceiptGallery.addTallyXmlButton(frm, ['Approved for Payment', 'Disbursed']);
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

        $(frm.wrapper).off('dirty.ap_ear_save_guard').on('dirty.ap_ear_save_guard', function() {
            if (frm.doc.docstatus === 0 && frm.page && frm.page.btn_primary) {
                frm.enable_save();
                frm.page.set_primary_action(__('Save'), () => frm.save());
                frm.page.btn_primary.show().removeClass('hide');
            }
        });

        if (frm.doc.status === 'Returned to SPOC') {
            const ret_reason = frappe.utils.escape_html(frm.doc.rejection_reason || 'Discrepancy flagged by Accounts.');
            const origin = frappe.utils.escape_html(frm.doc.return_origin_stage || 'Accounts Review');
            const base_amt = flt(frm.doc.rejection_baseline_amount || 0);

            const banner_html = `
                <div class="ap-advance-return-banner" style="background: #fff7ed; border: 1px solid #fed7aa; border-left: 4px solid #ea580c; border-radius: 6px; padding: 12px 16px; margin: 12px 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span style="font-weight: 700; color: #9a3412; font-size: 13px;">⚠️ Request Returned to SPOC for Revision</span>
                        <span style="font-size: 11px; font-weight: 700; background: #ea580c; color: #fff; padding: 2px 8px; border-radius: 4px;">Stage: ${origin}</span>
                    </div>
                    <div style="font-size: 12px; color: #7c2d12; margin-bottom: 6px;"><b>Reviewer Feedback:</b> ${ret_reason}</div>
                    <div style="font-size: 11px; color: #9a3412;">
                        ⚡ <b>Fast-Tracker Active:</b> If revised advance is &le; <b>₹ ${frappe.format(base_amt, { fieldtype: 'Currency' })}</b>, 
                        your resubmission bypasses Stage 1 Director approval and fast-tracks directly back to <b>${origin}</b>.
                    </div>
                </div>
            `;
            $(frm.wrapper).find('.ap-advance-return-banner').remove();
            $(frm.wrapper).find('.form-page').first().prepend(banner_html);

            const is_spoc = frappe.session.user === frm.doc.owner || frappe.session.user === frm.doc.spoc || frappe.session.user === 'Administrator' || frappe.user.has_role(['System Manager', 'Accounts Manager']);
            if (is_spoc) {
                frm.add_custom_button(__('🚀 Fast-Track Resubmit Advance'), function() {
                    frappe.confirm(
                        __('Resubmit this revised Event Advance Request?<br><br><b>Fast-Track:</b> If amount &le; baseline, it routes directly back to Accounts without Director re-approval.'),
                        function() {
                            const do_resubmit = () => {
                                frappe.call({
                                    method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.resubmit_event_advance',
                                    args: { advance_name: frm.doc.name },
                                    freeze: true,
                                    freeze_message: __('Resubmitting Advance...'),
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
                        }
                    );
                }).addClass('btn-primary').css({
                    'background-color': '#059669',
                    'border-color': '#047857',
                    'color': '#ffffff',
                    'font-weight': '700'
                });
            }
        }

        if (frm.doc.docstatus === 0 && (frm.doc.status || 'Draft') === 'Draft') {

            if (frm.doc.event) {
                sync_spoc_salary_bank_in_draft(frm, !frm.doc.spoc || frm.is_new());
            }

            frm.add_custom_button(__('🚀 Submit to Director'), function() {
                if (!frm.doc.event) {
                    frappe.msgprint({
                        title: __('Missing Event'),
                        indicator: 'red',
                        message: __('Please select a <b>Linked Event</b> before submitting.')
                    });
                    frm.scroll_to_field('event');
                    return;
                }

                const items = frm.doc.imprest_items || [];
                if (items.length === 0) {
                    frappe.msgprint({
                        title: __('Missing Imprest Breakdown'),
                        indicator: 'red',
                        message: __('Please add at least one line item in <b>Imprest Items</b> before submitting.')
                    });
                    frm.scroll_to_field('imprest_items');
                    return;
                }

                for (let i = 0; i < items.length; i++) {
                    const row = items[i];
                    if (!flt(row.amount) || flt(row.amount) <= 0) {
                        frappe.msgprint({
                            title: __('Invalid Row Amount'),
                            indicator: 'red',
                            message: __(`Row #${i + 1}: Amount must be strictly greater than zero.`)
                        });
                        return;
                    }
                    const is_upi = row.payment_mode === 'Direct Vendor Payment (UPI)' || !!(row.upi_id && row.upi_id.trim());
                    if (is_upi) {
                        const bene = (row.beneficiary_name || '').trim();
                        const upi = (row.upi_id || '').trim();
                        if (!bene || !upi) {
                            frappe.msgprint({
                                title: __('Missing Vendor UPI Details'),
                                indicator: 'red',
                                message: __(`Row #${i + 1}: Beneficiary Name and UPI ID / VPA are mandatory for UPI Payment.`)
                            });
                            return;
                        }
                        if (!/^[\w.\-_]{2,256}@[\w]{2,64}$/.test(upi)) {
                            frappe.msgprint({
                                title: __('Invalid UPI ID / VPA'),
                                indicator: 'red',
                                message: __(`Row #${i + 1} (${frappe.utils.escape_html(bene)}): Invalid UPI ID '${frappe.utils.escape_html(upi)}'. Must be in format name@bank (e.g. vendor@okhdfcbank).`)
                            });
                            return;
                        }
                    } else if (row.payment_mode === 'Direct Vendor Payment') {
                        const bene = (row.beneficiary_name || '').trim();
                        const ac_no = (row.bank_account_number || '').trim();
                        const ifsc = (row.bank_ifsc_code || '').trim().toUpperCase();
                        if (!bene || !ac_no || !ifsc) {
                            frappe.msgprint({
                                title: __('Missing Vendor Bank Details'),
                                indicator: 'red',
                                message: __(`Row #${i + 1}: Beneficiary Name, Bank Account Number, and IFSC Code are mandatory for Direct Vendor Payment.`)
                            });
                            return;
                        }
                        if (!/^[A-Z]{4}0[A-Z0-9]{6}$/.test(ifsc)) {
                            frappe.msgprint({
                                title: __('Invalid Vendor IFSC Code'),
                                indicator: 'red',
                                message: __(`Row #${i + 1} (${frappe.utils.escape_html(bene)}): Invalid IFSC Code '${frappe.utils.escape_html(ifsc)}'. Must be 11 characters conforming to NPCI standard (5th char must be 0, e.g., IDFB0040101).`)
                            });
                            return;
                        }
                    } else {
                        if (!row.beneficiary_name) {
                            frappe.model.set_value(row.doctype, row.name, 'beneficiary_name', frm.doc.spoc_name || frm.doc.spoc || 'Event SPOC');
                        }
                    }
                }

                frappe.confirm(
                    __('Submit Event Advance Request to <b>Director</b> for approval?<br><br>After Director approval, it will automatically route to <b>Accounts L1 Review</b> and then <b>Accounts Director Sign-Off</b>.'),
                    function() {
                        const do_submit = () => {
                            frappe.call({
                                method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.submit_event_advance',
                                args: { advance_name: frm.doc.name },
                                freeze: true,
                                freeze_message: __('Submitting to Director...'),
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

        // SUBMITTED STAGES (docstatus === 1): Resolve exact Matrix + Role buttons from server
        if (frm.doc.docstatus === 1 && !frm.is_new()) {
            const render_seq = (frm._ap_render_seq || 0) + 1;
            frm._ap_render_seq = render_seq;

            frappe.call({
                method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.get_event_advance_ui_context',
                args: { advance_name: frm.doc.name },
                callback: function(r) {
                    if (frm._ap_render_seq !== render_seq) return;
                    const ctx = (r && r.message) || {};
                    render_advance_event_context(frm, ctx.pending_with || '', ctx);
                    bind_submitted_stage_buttons(frm, ctx);
                }
            });
        }
    },

    event: function(frm) {
        if (frm.doc.event) {
            sync_spoc_salary_bank_in_draft(frm, true);
            render_advance_event_context(frm);
        } else {
            render_advance_event_context(frm);
        }
    }
});

function set_advance_status_indicator(frm) {
    const status = frm.doc.status || 'Draft';
    const color_map = {
        'Draft': 'grey',
        'Pending Director Approval': 'orange',
        'Pending Accounts L1 Review': 'cyan',
        'Pending Accounts Director Approval': 'purple',
        'Approved for Payment': 'blue',
        'Disbursed': 'green',
        'Rejected': 'red'
    };
    frm.page.set_indicator(__(status), color_map[status] || 'grey');
}

function run_advance_with_clarification_gate(frm, callback) {
    if (window.APClarificationThread && typeof window.APClarificationThread.checkUnresolvedQueries === 'function') {
        window.APClarificationThread.checkUnresolvedQueries(frm, callback);
    } else {
        callback();
    }
}

function bind_submitted_stage_buttons(frm, ctx) {
    const status = frm.doc.status;

    // STAGE 1: Director Approval
    if (status === 'Pending Director Approval' && ctx.can_director_approve) {
        frm.add_custom_button(__('✅ Approve (Director)'), function() {
            run_advance_with_clarification_gate(frm, function() {
                frappe.prompt([
                    {
                        fieldname: 'comments',
                        fieldtype: 'Small Text',
                        label: __('Director Approval Notes (Optional)'),
                        default: 'Approved for event operations.'
                    }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.approve_event_advance_by_director',
                        args: {
                            advance_name: frm.doc.name,
                            comments: values.comments
                        },
                        freeze: true,
                        freeze_message: __('Recording Director Approval...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Director Approval'), __('Approve & Forward to Accounts L1'));
            });
        }).addClass('btn-success');
    }

    // STAGE 2: Accounts L1 Review
    if (status === 'Pending Accounts L1 Review' && ctx.can_accounts_l1_verify) {
        frm.add_custom_button(__('✅ Verify & Forward to Accounts Director'), function() {
            run_advance_with_clarification_gate(frm, function() {
                frappe.prompt([
                    {
                        fieldname: 'tally_reference',
                        fieldtype: 'Data',
                        label: __('Tally / Audit Reference (Optional)'),
                        description: __('Enter Tally voucher reference if applicable (optional for advance review).')
                    },
                    {
                        fieldname: 'remarks',
                        fieldtype: 'Small Text',
                        label: __('Accounts L1 Review Remarks (Optional)'),
                        default: 'Beneficiary banking details & quotes verified.'
                    }
                ], function(values) {
                    frappe.call({
                        method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.verify_event_advance_by_accounts_l1',
                        args: {
                            advance_name: frm.doc.name,
                            tally_reference: values.tally_reference || '',
                            remarks: values.remarks || ''
                        },
                        freeze: true,
                        freeze_message: __('Verifying & Escalating to Accounts Director...'),
                        callback: function(r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Accounts L1 Review'), __('Verify & Forward to Accounts Director'));
            });
        }).addClass('btn-primary').css({
            'background-color': '#0284c7',
            'border-color': '#0369a1',
            'color': '#ffffff'
        });
    }

    // STAGE 3: Accounts Director Sign-Off
    if (status === 'Pending Accounts Director Approval' && ctx.can_accounts_director_signoff) {
        frm.add_custom_button(__('⭐ Accounts Director Sign-Off'), function() {
            run_advance_with_clarification_gate(frm, function() {
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
                }, __('Accounts Director Sign-Off'), __('Authorize for Payment'));
            });
        }).addClass('btn-primary').css({
            'background-color': '#7c3aed',
            'border-color': '#6d28d9',
            'color': '#ffffff'
        });
    }

    // Return to SPOC with discrepancy notes (Accounts L1 & Accounts Director)
    if (ctx.can_return_to_spoc && ['Pending Accounts L1 Review', 'Pending Accounts Director Approval'].includes(status)) {
        frm.add_custom_button(__('↩️ Return to SPOC'), function() {
            frappe.prompt([
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Discrepancy / Return Reason (Min 5 characters)'),
                    description: __('Explain what needs correction. Resubmissions within the current amount will fast-track back directly to your stage.'),
                    reqd: 1
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.return_event_advance_to_spoc',
                    args: {
                        advance_name: frm.doc.name,
                        reason: values.reason
                    },
                    freeze: true,
                    freeze_message: __('Returning Advance to SPOC...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: r.message.message, indicator: 'orange' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Return Advance Request to SPOC'), __('Return to SPOC'));
        }).addClass('btn-warning').css({
            'background-color': '#d97706',
            'border-color': '#b45309',
            'color': '#ffffff'
        });
    }

    // Reject button across pending approval tiers (Director / Accounts L1 / Accounts Director)
    if (ctx.can_reject && ['Pending Director Approval', 'Pending Accounts L1 Review', 'Pending Accounts Director Approval'].includes(status)) {
        frm.add_custom_button(__('❌ Reject Proposal'), function() {
            frappe.prompt([
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Rejection Reason (Min 5 characters)'),
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
                    freeze_message: __('Rejecting Request...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: r.message.message, indicator: 'red' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Reject Event Advance Request'), __('Reject'));
        }).addClass('btn-danger');
    }

    // STAGE 4: IDFC Export + Maker Payment Release + Checker Bank Disbursal
    if (['Approved for Payment', 'Disbursed'].includes(status) && ctx.is_finance_viewer) {
        frm.add_custom_button(__('🏛️ IDFC Bank Disbursal Excel (.xlsx)'), function() {
            const download_url = `/api/method/ap_automation.services.idfc_bank_excel_generator.download_idfc_event_advance_excel?advance_name=${encodeURIComponent(frm.doc.name)}`;
            window.open(download_url, '_blank');
            frappe.show_alert({
                message: __('IDFC Bank Bulk Disbursal Excel downloaded. Please upload to IDFC Netbanking.'),
                indicator: 'blue'
            });
        }).addClass('btn-info');

        if (status === 'Approved for Payment') {
            if (frm.doc.payment_release_notified) {
                frm.add_custom_button(__('✓ Payment Release Sent (IDFC Uploaded)'), function() {
                    const notif_date = frm.doc.payment_release_notified_on ? frappe.datetime.str_to_user(frm.doc.payment_release_notified_on) : 'Recently';
                    frappe.msgprint({
                        title: __('Payment Release Already Notified'),
                        message: __('IDFC Disbursal File was uploaded and notification was dispatched on {0} by {1}. Awaiting final release by Payment Releaser ({2}).', [notif_date, frm.doc.payment_release_maker || 'Maker', frm.doc.payment_releaser || 'Payment Releaser']),
                        indicator: 'green'
                    });
                }).addClass('btn-success disabled');
            } else if (ctx.can_maker_release) {
                frm.add_custom_button(__('📤 Payment Release'), function() {
                    frappe.confirm(
                        __('Confirm that the IDFC Disbursal Excel has been uploaded to the IDFC Netbanking portal.<br><br>This will dispatch a payout alert to the <b>Payment Releaser</b> (Checker, TO) with CC to the <b>Accounts Director</b> (CC).<br><br>Proceed?'),
                        function() {
                            frappe.call({
                                method: 'ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.trigger_event_advance_payment_release_notification',
                                args: { advance_name: frm.doc.name },
                                freeze: true,
                                freeze_message: __('Dispatching Payment Release Alert...'),
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

            const is_admin_or_ad = frappe.session.user === 'Administrator' || (frappe.user_roles && (frappe.user_roles.includes('System Manager') || frappe.user_roles.includes('Accounts Director')));
            const not_same_maker = (frm.doc.payment_release_maker !== frappe.session.user) || is_admin_or_ad;
            if (frm.doc.payment_release_notified && (ctx.can_checker_disburse || is_admin_or_ad) && not_same_maker) {
                frm.add_custom_button(__('💳 Release Bank Disbursal (Payment Releaser)'), function() {
                    frappe.prompt([
                        {
                            fieldname: 'disbursement_ref',
                            fieldtype: 'Data',
                            label: __('Bank UTR / Disbursal Reference (Optional)'),
                            default: 'IDFC-EVT-' + Math.floor(10000000 + Math.random() * 90000000),
                            reqd: 0
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

    // STAGE 5: Disbursed -> Post-Event Claim Shortcut
    if (status === 'Disbursed') {
        frm.add_custom_button(__('📋 Create Expense Claim from Proposal'), function() {
            frappe.route_options = {
                "event": frm.doc.event,
                "company": frm.doc.company
            };
            frappe.new_doc("Event Expense Claim");
        }).addClass('btn-primary');
    }
}

function build_advance_stepper_html(frm, pending_with, ctx) {
    const status = frm.doc.status || 'Draft';
    const is_rejected = status === 'Rejected';
    const notified = !!cint(frm.doc.payment_release_notified);
    const stage_owners = (ctx && ctx.stage_owners) || {};

    const stages = [
        { key: 'draft', label: '1. Draft (SPOC)' },
        { key: 'director', label: '2. Director' },
        { key: 'accounts_l1', label: '3. Accounts L1' },
        { key: 'accounts_dir', label: '4. Accounts Director' },
        { key: 'release', label: notified ? '5. Payment Releaser' : '5. IDFC & AD Release' },
        { key: 'disbursed', label: '6. Disbursed' }
    ];

    let active_idx = 0;
    if (status === 'Draft') active_idx = 0;
    else if (status === 'Pending Director Approval') active_idx = 1;
    else if (status === 'Pending Accounts L1 Review') active_idx = 2;
    else if (status === 'Pending Accounts Director Approval') active_idx = 3;
    else if (status === 'Approved for Payment') active_idx = 4;
    else if (status === 'Disbursed') active_idx = 6; // all done
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
        const owner_hint = stage_owners[st.key] ? `Assigned: ${stage_owners[st.key]}` : st.label;
        return `
            <div class="ap-step-item ${cls}" title="${frappe.utils.escape_html(owner_hint)}">
                <div class="ap-step-node">${badge}</div>
                <div class="ap-step-label">${st.label}</div>
            </div>
        `;
    }).join('');

    const guidance_map = {
        'Draft': 'Draft saved by Event SPOC. Click <b>🚀 Submit to Director</b> when imprest items and banking details are ready.',
        'Pending Director Approval': `Awaiting <b>Executive Director</b> approval${pending_with ? ` (${frappe.utils.escape_html(pending_with)})` : ''}.`,
        'Pending Accounts L1 Review': `Director approved. Awaiting <b>Accounts L1 Auditor</b> verification${pending_with ? ` (${frappe.utils.escape_html(pending_with)})` : ''}.`,
        'Pending Accounts Director Approval': `Accounts L1 verified. Awaiting <b>Accounts Director</b> sign-off${pending_with ? ` (${frappe.utils.escape_html(pending_with)})` : ''}.`,
        'Approved for Payment': notified
            ? `IDFC Excel uploaded & notified. Awaiting <b>Payment Releaser</b>${pending_with ? ` (${frappe.utils.escape_html(pending_with)})` : ''} to stamp UTR.`
            : `Accounts Director signed off! Awaiting <b>Accounts Director</b>${pending_with ? ` (${frappe.utils.escape_html(pending_with)})` : ''} to export IDFC Excel and click <b>📤 Payment Release</b>.`,
        'Disbursed': `Disbursed via corporate bank${frm.doc.disbursement_reference ? ` (UTR: <b>${frappe.utils.escape_html(frm.doc.disbursement_reference)}</b>)` : ''}. Proceed with Event Expense Claim after event execution.`,
        'Rejected': `Request rejected. ${frm.doc.business_head_comments ? frappe.utils.escape_html(frm.doc.business_head_comments) : 'Review comments below and amend if needed.'}`
    };

    const banner_tone = is_rejected
        ? { bg: '#fef2f2', border: '#fecaca', text: '#991b1b' }
        : status === 'Disbursed'
            ? { bg: '#ecfdf5', border: '#a7f3d0', text: '#065f46' }
            : { bg: '#eff6ff', border: '#bfdbfe', text: '#1e40af' };

    const is_pending_approval = [
        'Pending Director Approval',
        'Pending Accounts L1 Review',
        'Pending Accounts Director Approval',
        'Approved for Payment'
    ].includes(status);

    let role_chip = '';
    if (frm.doc.docstatus === 1 && is_pending_approval && ctx && typeof ctx.can_act_current_stage === 'boolean') {
        if (ctx.can_act_current_stage) {
            role_chip = `<span style="background: #dcfce7; color: #166534; border: 1px solid #86efac; border-radius: 999px; padding: 2px 10px; font-size: 11px; font-weight: 700; white-space: nowrap;">🟢 Action Required From You</span>`;
        } else {
            const waiter = pending_with ? `Awaiting ${frappe.utils.escape_html(pending_with)}` : 'Awaiting Designated Approver';
            role_chip = `<span style="background: #ffffff; color: #475569; border: 1px solid #cbd5e1; border-radius: 999px; padding: 2px 10px; font-size: 11px; font-weight: 600; white-space: nowrap;">🔒 View Only · ${waiter}</span>`;
        }
    }

    return `
        <div class="ap-stepper-wrapper" style="margin-bottom: 12px;">
            <div class="ap-stepper-trail">${nodes}</div>
            <div style="margin-top: 10px; padding: 8px 12px; border-radius: 8px; background: ${banner_tone.bg}; border: 1px solid ${banner_tone.border}; color: ${banner_tone.text}; font-size: 12px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <div><b>Current Stage (${frappe.utils.escape_html(status)}):</b> ${guidance_map[status] || ''}</div>
                ${role_chip}
            </div>
        </div>
    `;
}

function set_advance_headline(frm, html) {
    if (window.APReceiptGallery && typeof window.APReceiptGallery.setHeadlineExclusive === 'function') {
        window.APReceiptGallery.setHeadlineExclusive(frm, html);
        return;
    }
    if (!frm || !frm.dashboard) return;
    if (typeof frm.dashboard.clear_headline === 'function') {
        frm.dashboard.clear_headline();
    }
    if (frm.layout && frm.layout.message) {
        frm.layout.message.empty().addClass('hidden');
    }
    if (html) {
        frm.dashboard.set_headline(html);
    }
}

function sync_spoc_salary_bank_in_draft(frm, force_event_fields) {
    if (!frm || !frm.doc || !frm.doc.event || frm.doc.docstatus !== 0) return;
    const seq = (frm._ap_bank_sync_seq || 0) + 1;
    frm._ap_bank_sync_seq = seq;

    frappe.call({
        method: 'ap_automation.services.event_budget_service.get_spoc_salary_bank_for_event',
        args: { event_name: frm.doc.event },
        callback: function(r) {
            if (frm._ap_bank_sync_seq !== seq || !r || !r.message || frm.doc.docstatus !== 0) return;
            const d = r.message;
            const fields = ['bank_name', 'bank_account_number', 'bank_ifsc_code'];
            if (force_event_fields) {
                fields.unshift('company', 'spoc', 'spoc_name', 'event_date', 'venue', 'letter_head');
            }
            fields.forEach(f => {
                if (d[f] !== undefined && d[f] !== null && d[f] !== '' && frm.doc[f] !== d[f]) {
                    frm.set_value(f, d[f]);
                }
            });
            if (d.allowed_departments && d.allowed_departments.length && (!frm.doc.allowed_departments || frm.doc.allowed_departments.length === 0)) {
                d.allowed_departments.forEach(dept => {
                    frm.add_child('allowed_departments', { department: dept });
                });
                frm.refresh_field('allowed_departments');
                setup_advance_spoc_query(frm);
            }
            render_advance_event_context(frm);
        }
    });
}

function render_advance_event_context(frm, pending_with, ctx) {
    if (!frm.dashboard) return;
    const seq = (frm._ap_ctx_seq || 0) + 1;
    frm._ap_ctx_seq = seq;
    const stepper_html = build_advance_stepper_html(frm, pending_with || '', ctx || null);

    set_advance_headline(frm, stepper_html);
    if (!frm.doc.event) {
        return;
    }

    frappe.call({
        method: 'ap_automation.services.event_budget_service.get_event_budget_snapshot',
        args: {
            event_name: frm.doc.event,
            exclude_advance_name: frm.is_new() ? '' : frm.doc.name
        },
        callback: function(r) {
            if (frm._ap_ctx_seq !== seq || !r || !r.message) return;
            const ev = r.message;
            const budget = parseFloat(ev.allocated_budget || 0.0);
            const committed_other = parseFloat(ev.committed_with_pipeline || 0.0);
            const req_amt = parseFloat(frm.doc.approved_advance_amount || frm.doc.requested_advance_amount || 0.0);
            const counts_as_new_commit = !['Disbursed', 'Rejected'].includes(frm.doc.status || 'Draft');
            const projected_used = committed_other + (counts_as_new_commit ? req_amt : 0.0);
            const remaining = Math.round((budget - projected_used) * 100) / 100;
            const is_over = remaining < 0;
            const format_curr = (val) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(val || 0);

            const bg = is_over ? '#fef2f2' : '#f0fdf4';
            const border = is_over ? '#fca5a5' : '#86efac';
            const title_col = is_over ? '#991b1b' : '#166534';
            const sub_col = is_over ? '#b91c1c' : '#15803d';
            const chip_border = is_over ? '#fecaca' : '#bbf7d0';
            const rem_label = is_over ? 'Over Budget By (Reminder)' : 'Remaining Budget';
            const rem_val = is_over ? format_curr(Math.abs(remaining)) : format_curr(remaining);
            const icon = is_over ? '⚠️' : '💡';
            const reminder_note = is_over
                ? `<div style="font-size: 11px; color: #b91c1c; font-weight: 700; margin-top: 3px;">Reminder only — submission is allowed for approver review.</div>`
                : '';

            const banner_html = `
                ${build_advance_stepper_html(frm, pending_with || '', ctx || null)}
                <div class="ap-advance-context-banner" style="
                    background: ${bg};
                    border: 1px solid ${border};
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
                        <span style="font-size: 20px;">${icon}</span>
                        <div>
                            <div style="font-size: 13px; font-weight: 700; color: ${title_col};">Linked Event: ${frappe.utils.escape_html(ev.event_name || frm.doc.event)}</div>
                            <div style="font-size: 11px; color: ${sub_col}; margin-top: 2px;">
                                Event Budget: <b>${format_curr(budget)}</b> &nbsp;|&nbsp;
                                Earlier Advances / Spends: <b>${format_curr(committed_other)}</b> &nbsp;|&nbsp;
                                This Request: <b>${format_curr(req_amt)}</b>
                            </div>
                            ${reminder_note}
                            <div style="display: flex; gap: 12px; margin-top: 4px; font-size: 11px; flex-wrap: wrap;">
                                <span style="background: #ffffff; padding: 2px 8px; border-radius: 4px; border: 1px solid ${chip_border}; color: ${title_col}; font-weight: 600;">
                                    🏛️ Direct Vendor Payouts: <b>${format_curr(parseFloat(frm.doc.total_direct_vendor_amount || 0))}</b>
                                </span>
                                <span style="background: #ffffff; padding: 2px 8px; border-radius: 4px; border: 1px solid ${chip_border}; color: ${title_col}; font-weight: 600;">
                                    💵 SPOC Cash Imprest: <b>${format_curr(parseFloat(frm.doc.total_cash_imprest_amount || 0))}</b>
                                </span>
                            </div>
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 11px; text-transform: uppercase; color: ${sub_col}; font-weight: 700;">${rem_label}</div>
                        <div style="font-size: 18px; font-weight: 800; color: ${title_col};">${rem_val}</div>
                    </div>
                </div>
            `;

            set_advance_headline(frm, banner_html);
        }
    });
}

function calculate_imprest_totals(frm) {
    let direct = 0.0;
    let cash = 0.0;
    let base_sum = 0.0;
    let gst_sum = 0.0;

    (frm.doc.imprest_items || []).forEach(row => {
        let amt = parseFloat(row.amount || 0.0);
        let base = parseFloat(row.base_amount || 0.0);
        let gst = parseFloat(row.gst_amount || 0.0);
        base_sum += base;
        gst_sum += gst;

        const is_direct = ['Direct Vendor Payment', 'Direct Vendor Payment (UPI)'].includes(row.payment_mode);
        if (is_direct) {
            direct += amt;
        } else {
            cash += amt;
        }
    });

    direct = Math.round(direct * 100) / 100;
    cash = Math.round(cash * 100) / 100;
    const total = Math.round((direct + cash) * 100) / 100;

    if (frm.doc.docstatus === 0) {
        if (frm.fields_dict.total_direct_vendor_amount && flt(frm.doc.total_direct_vendor_amount) !== direct) {
            frm.set_value('total_direct_vendor_amount', direct);
        }
        if (frm.fields_dict.total_cash_imprest_amount && flt(frm.doc.total_cash_imprest_amount) !== cash) {
            frm.set_value('total_cash_imprest_amount', cash);
        }
        if (frm.fields_dict.requested_advance_amount && flt(frm.doc.requested_advance_amount) !== total) {
            frm.set_value('requested_advance_amount', total);
        }
        if (frm.fields_dict.total_amount && flt(frm.doc.total_amount) !== total) {
            frm.set_value('total_amount', total);
        }
    }
}

function setup_advance_spoc_query(frm) {
    frm.set_query('spoc', function() {
        const depts = (frm.doc.allowed_departments || []).map(d => d.department).filter(Boolean);
        return {
            query: 'ap_automation.services.event_budget_service.get_event_spoc_users',
            filters: {
                departments: depts,
                event: frm.doc.event
            }
        };
    });
}

frappe.ui.form.on("Event Department Item", {
    department: function(frm) {
        setup_advance_spoc_query(frm);
    },
    allowed_departments_remove: function(frm) {
        setup_advance_spoc_query(frm);
    }
});

// Child Table Calculations with automated GST & Beneficiary Defaulting
frappe.ui.form.on("Event Imprest Item", {
    base_amount: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const r = parseFloat((row.gst_rate || '0%').replace('%', '').trim()) || 0;
        const b = flt(row.base_amount);
        row.gst_amount = Math.round(b * r) / 100;
        row.amount = Math.round((b + flt(row.gst_amount)) * 100) / 100;
        frm.refresh_field('imprest_items');
        calculate_imprest_totals(frm);
        render_advance_event_context(frm);
    },

    gst_rate: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const r = parseFloat((row.gst_rate || '0%').replace('%', '').trim()) || 0;
        const b = flt(row.base_amount);
        row.gst_amount = Math.round(b * r) / 100;
        row.amount = Math.round((b + flt(row.gst_amount)) * 100) / 100;
        frm.refresh_field('imprest_items');
        calculate_imprest_totals(frm);
        render_advance_event_context(frm);
    },

    amount: function(frm) {
        calculate_imprest_totals(frm);
        render_advance_event_context(frm);
    },

    payment_mode: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const is_petty = ['Petty Cash', 'Cash / Petty Imprest', 'On-Ground Cash Imprest'].includes(row.payment_mode);
        if (is_petty) {
            row.beneficiary_name = frm.doc.spoc_name || frm.doc.spoc || 'Event SPOC';
            row.bank_name = frm.doc.bank_name || '';
            row.bank_account_number = frm.doc.bank_account_number || '';
            row.bank_ifsc_code = frm.doc.bank_ifsc_code || '';
            row.upi_id = '';
        } else if (row.payment_mode === 'Direct Vendor Payment (UPI)') {
            if (row.beneficiary_name === (frm.doc.spoc_name || frm.doc.spoc)) {
                row.beneficiary_name = '';
            }
        }
        frm.refresh_field('imprest_items');
        calculate_imprest_totals(frm);
        render_advance_event_context(frm);
    },

    quote_attachment: function(frm) {
        if (window.APReceiptGallery) {
            window.APReceiptGallery.refreshFormButtons(frm);
        }
        setTimeout(() => bind_imprest_grid_uploaders(frm), 150);
    },

    imprest_items_remove: function(frm) {
        calculate_imprest_totals(frm);
        render_advance_event_context(frm);
        if (window.APReceiptGallery) {
            window.APReceiptGallery.refreshFormButtons(frm);
        }
        setTimeout(() => bind_imprest_grid_uploaders(frm), 150);
    }
});

// Interactive Multi-Quote Upload & Inspection Modal
function bind_imprest_grid_uploaders(frm) {
    if (!frm || !frm.fields_dict['imprest_items'] || !frm.fields_dict['imprest_items'].grid) return;
    const grid = frm.fields_dict['imprest_items'].grid;
    const is_editable = (frm.doc.docstatus === 0 && (frm.doc.status || 'Draft') === 'Draft');

    $(frm.wrapper).find('.grid-row').each(function(idx) {
        const row_elem = $(this);
        const row_data = (grid.grid_rows && grid.grid_rows[idx] && grid.grid_rows[idx].doc) || (frm.doc.imprest_items || [])[idx];
        if (!row_data) return;

        const cell = row_elem.find('.grid-static-col[data-fieldname="quote_attachment"]');
        if (!cell.length) return;

        let atts = [];
        if (row_data.attachments) {
            try {
                atts = typeof row_data.attachments === 'string' ? JSON.parse(row_data.attachments) : row_data.attachments;
            } catch (e) {
                atts = [];
            }
        }
        if (!Array.isArray(atts)) atts = [];
        if (atts.length === 0 && row_data.quote_attachment) {
            atts = [{ file_url: row_data.quote_attachment, file_name: row_data.quote_attachment.split('/').pop().split('?')[0] }];
        }

        const count = atts.length;
        const state_key = `${count}_${row_data.name || idx}`;
        if (cell.attr('data-rendered-state') === state_key && cell.children().length > 0) return;
        cell.attr('data-rendered-state', state_key);
        cell.empty();

        if (count > 0) {
            const badge = $(`
                <div class="ap-imprest-capsule-badge" style="
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    background: #eff6ff;
                    border: 1px solid #bfdbfe;
                    border-radius: 6px;
                    padding: 2px 8px;
                    cursor: pointer;
                    height: 28px;
                    max-height: 28px;
                    white-space: nowrap;
                    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
                " title="Click to view/add quotes (${count} attached)">
                    <span style="font-size: 11px; font-weight: 700; color: #1e40af;">${count} Quote${count > 1 ? 's' : ''}</span>
                    <span class="ap-row-view-btn" style="
                        display: inline-flex;
                        align-items: center;
                        justify-content: center;
                        padding: 0 4px;
                        height: 20px;
                        border-radius: 4px;
                        background: #dbeafe;
                        color: #1e40af;
                        font-size: 10px;
                        font-weight: 700;
                        margin-left: 2px;
                    " title="View Quotes">View</span>
                </div>
            `);
            badge.on('click', function(e) {
                e.stopPropagation();
                open_imprest_row_quotes_modal(frm, idx);
            });
            cell.append(badge);
        } else if (is_editable) {
            const upload_btn = $(`
                <button type="button" class="btn btn-xs btn-default ap-row-upload-btn" style="
                    border-radius: 6px;
                    font-size: 11px;
                    padding: 3px 8px;
                    background: #f8fafc;
                    border: 1px dashed #94a3b8;
                    color: #475569;
                    cursor: pointer;
                ">+ Quotes</button>
            `);
            upload_btn.on('click', function(e) {
                e.stopPropagation();
                upload_quotes_to_imprest_row(frm, idx);
            });
            cell.append(upload_btn);
        } else {
            cell.html('<span style="color:#94a3b8; font-size:11px;">No Quote</span>');
        }
    });
}

function upload_quotes_to_imprest_row(frm, row_idx) {
    const grid = frm.fields_dict['imprest_items'].grid;
    const row = (grid.grid_rows && grid.grid_rows[row_idx] && grid.grid_rows[row_idx].doc) || (frm.doc.imprest_items || [])[row_idx];
    if (!row) return;

    let existing_atts = [];
    if (row.attachments) {
        try {
            existing_atts = typeof row.attachments === 'string' ? JSON.parse(row.attachments) : row.attachments;
        } catch (e) {
            existing_atts = [];
        }
    }
    if (!Array.isArray(existing_atts)) existing_atts = [];
    if (existing_atts.length === 0 && row.quote_attachment) {
        existing_atts.push({
            file_url: row.quote_attachment,
            file_name: row.quote_attachment.split('/').pop().split('?')[0]
        });
    }

    new frappe.ui.FileUploader({
        folder: 'Home/Attachments',
        doctype: frm.doc.doctype,
        docname: frm.doc.name,
        allow_multiple: true,
        on_success: (file_doc) => {
            const clean_url = file_doc.file_url;
            const f_name = file_doc.file_name || clean_url.split('/').pop().split('?')[0];
            const f_size = file_doc.file_size ? `${Math.round(file_doc.file_size / 1024)} KB` : '';
            existing_atts.push({
                file_url: clean_url,
                file_name: f_name,
                file_size: f_size
            });

            frappe.model.set_value(row.doctype, row.name, 'attachments', JSON.stringify(existing_atts));
            frappe.model.set_value(row.doctype, row.name, 'attachments_count', existing_atts.length);
            if (!row.quote_attachment) {
                frappe.model.set_value(row.doctype, row.name, 'quote_attachment', clean_url);
            }
            frm.refresh_field('imprest_items');
            setTimeout(() => bind_imprest_grid_uploaders(frm), 150);
        }
    });
}

function open_imprest_row_quotes_modal(frm, row_idx) {
    const grid = frm.fields_dict['imprest_items'].grid;
    const row = (grid.grid_rows && grid.grid_rows[row_idx] && grid.grid_rows[row_idx].doc) || (frm.doc.imprest_items || [])[row_idx];
    if (!row) return;

    let atts = [];
    if (row.attachments) {
        try {
            atts = typeof row.attachments === 'string' ? JSON.parse(row.attachments) : row.attachments;
        } catch (e) {
            atts = [];
        }
    }
    if (!Array.isArray(atts)) atts = [];
    if (atts.length === 0 && row.quote_attachment) {
        atts.push({ file_url: row.quote_attachment, file_name: row.quote_attachment.split('/').pop().split('?')[0] });
    }

    const title_str = row.particulars || row.beneficiary_name || `Row #${row_idx + 1}`;
    const is_editable = (frm.doc.docstatus === 0 && (frm.doc.status || 'Draft') === 'Draft');

    const render_cards_html = () => {
        if (atts.length === 0) {
            return `<div style="text-align:center; padding:30px; color:#64748b; font-size:13px;">No quotes attached to this item yet.</div>`;
        }
        return `
            <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 14px; margin-top: 12px; max-height: 460px; overflow-y: auto; padding: 4px;">
                ${atts.map((att, a_idx) => {
                    const u = att.file_url || att.url || '';
                    const fn = att.file_name || u.split('/').pop().split('?')[0];
                    const ext = (fn.lastIndexOf('.') !== -1 ? fn.substring(fn.lastIndexOf('.')).toLowerCase() : '');
                    const is_img = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext);
                    return `
                        <div class="ap-row-quote-card" style="border: 1px solid #e2e8f0; border-radius: 8px; background: #ffffff; padding: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); display: flex; flex-direction: column;">
                            <div style="height: 120px; background: #f8fafc; border-radius: 6px; display: flex; align-items: center; justify-content: center; overflow: hidden; margin-bottom: 8px; cursor: pointer;" onclick="window.open('${u}', '_blank')">
                                ${is_img 
                                    ? `<img src="${u}" style="max-height: 100%; max-width: 100%; object-fit: contain;" />` 
                                    : `<div style="text-align:center; color:#2563eb; font-weight:700; font-size:18px;">[PDF]<div style="font-size:11px; color:#64748b; margin-top:4px;">Document</div></div>`
                                }
                            </div>
                            <div style="font-size: 11px; font-weight: 600; color: #1e293b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 4px;" title="${frappe.utils.escape_html(fn)}">
                                ${frappe.utils.escape_html(fn)}
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: auto; padding-top: 6px; border-top: 1px solid #f1f5f9;">
                                <a href="${u}" target="_blank" style="font-size: 11px; color: #2563eb; text-decoration: none; font-weight: 600;">Open ↗</a>
                                ${is_editable ? `
                                    <button type="button" class="btn btn-xs btn-danger ap-del-quote-btn" data-idx="${a_idx}" style="font-size: 10px; padding: 2px 6px;">Delete</button>
                                ` : ''}
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    };

    const d = new frappe.ui.Dialog({
        title: __('Attached Quotes & Estimates — {0}', [title_str]),
        fields: [
            {
                fieldname: 'cards_area',
                fieldtype: 'HTML'
            }
        ],
        size: 'large'
    });

    if (is_editable) {
        d.set_primary_action(__('Upload More Quotes'), function() {
            new frappe.ui.FileUploader({
                folder: 'Home/Attachments',
                doctype: frm.doc.doctype,
                docname: frm.doc.name,
                allow_multiple: true,
                on_success: (file_doc) => {
                    const clean_url = file_doc.file_url;
                    const f_name = file_doc.file_name || clean_url.split('/').pop().split('?')[0];
                    const f_size = file_doc.file_size ? `${Math.round(file_doc.file_size / 1024)} KB` : '';
                    atts.push({ file_url: clean_url, file_name: f_name, file_size: f_size });

                    frappe.model.set_value(row.doctype, row.name, 'attachments', JSON.stringify(atts));
                    frappe.model.set_value(row.doctype, row.name, 'attachments_count', atts.length);
                    if (!row.quote_attachment) {
                        frappe.model.set_value(row.doctype, row.name, 'quote_attachment', clean_url);
                    }
                    frm.refresh_field('imprest_items');
                    setTimeout(() => bind_imprest_grid_uploaders(frm), 150);
                    d.fields_dict.cards_area.$wrapper.html(render_cards_html());
                }
            });
        });
    }

    d.show();
    d.fields_dict.cards_area.$wrapper.html(render_cards_html());

    d.fields_dict.cards_area.$wrapper.on('click', '.ap-del-quote-btn', function() {
        const del_idx = parseInt($(this).attr('data-idx'));
        if (!isNaN(del_idx)) {
            atts.splice(del_idx, 1);
            frappe.model.set_value(row.doctype, row.name, 'attachments', JSON.stringify(atts));
            frappe.model.set_value(row.doctype, row.name, 'attachments_count', atts.length);
            frappe.model.set_value(row.doctype, row.name, 'quote_attachment', atts.length > 0 ? atts[0].file_url : '');
            frm.refresh_field('imprest_items');
            setTimeout(() => bind_imprest_grid_uploaders(frm), 150);
            d.fields_dict.cards_area.$wrapper.html(render_cards_html());
        }
    });
}
