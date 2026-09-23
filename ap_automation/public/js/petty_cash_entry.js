// Enterprise Petty Cash Entry Client Controller (Production-Ready)
frappe.ui.form.on('Petty Cash Entry', {
    onload: function (frm) {
        auto_update_claim_title(frm);
        setTimeout(() => apply_bank_account_masking(frm), 100);
        setTimeout(() => apply_bank_account_masking(frm), 400);
    },

    refresh: function (frm) {
        frm.set_df_property('posting_date', 'max_date', frappe.datetime.get_today());
        auto_update_claim_title(frm);
        frm.set_df_property('expense_lines', 'read_only', 0);

        // Bank Masking
        apply_bank_account_masking(frm);
        setTimeout(() => apply_bank_account_masking(frm), 150);
        setTimeout(() => apply_bank_account_masking(frm), 500);

        // Filter queries
        frm.set_query('custodian', function () {
            return {
                query: 'ap_automation.ap_automation.doctype.petty_cash_entry.petty_cash_entry.get_all_employees_query'
            };
        });
        frm.set_query('company', function () {
            return {
                query: 'ap_automation.ap_automation.doctype.petty_cash_entry.petty_cash_entry.get_all_companies_query'
            };
        });
        frm.set_query('employee', 'expense_lines', function () {
            return {
                query: 'ap_automation.ap_automation.doctype.petty_cash_entry.petty_cash_entry.get_all_employees_query'
            };
        });

        frm.set_df_property('status', 'read_only', 1);
        apply_petty_cash_styles();
        render_petty_cash_stepper(frm);
        render_status_guidance_banner(frm);
        render_role_based_action_buttons(frm);
        bind_custom_grid_uploaders_and_review(frm);
        setup_dispute_merge_helper(frm);
    },

    company: function (frm) {
        auto_update_claim_title(frm);
    },

    posting_date: function (frm) {
        validate_client_posting_date(frm);
        auto_update_claim_title(frm);
    },

    custodian: function (frm) {
        setTimeout(() => apply_bank_account_masking(frm), 250);
        setTimeout(() => apply_bank_account_masking(frm), 600);
    },

    custodian_bank_account: function (frm) {
        apply_bank_account_masking(frm);
    },

    validate: function (frm) {
        calculate_grid_totals(frm);
        validate_client_posting_date(frm);
        auto_update_claim_title(frm);
    }
});

frappe.ui.form.on('Petty Cash Line Item', {
    is_gst: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.is_gst) {
            frappe.show_alert({
                message: __('🧾 GST Bill selected: Please enter GST Bill Number and 15-digit Merchant GSTIN.'),
                indicator: 'blue'
            }, 4);
        } else {
            frappe.show_alert({
                message: __('💳 Non-GST Expense: Please enter Transaction ID / UPI Ref Number.'),
                indicator: 'orange'
            }, 4);
        }
    },
    bill_number: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.bill_number && !row.transaction_id) {
            frappe.model.set_value(cdt, cdn, 'transaction_id', row.bill_number);
        }
    },
    amount: function (frm) {
        calculate_grid_totals(frm);
    },
    expense_lines_remove: function (frm) {
        calculate_grid_totals(frm);
    },
    expense_lines_add: function (frm) {
        calculate_grid_totals(frm);
        setTimeout(() => bind_custom_grid_uploaders_and_review(frm), 250);
    }
});

// --------------------------------------------------------------------------------------
// 1. AUTO-CALCULATE CLAIM TITLE (Week # - Company Abbreviation)
// --------------------------------------------------------------------------------------
function auto_update_claim_title(frm) {
    if (!frm.doc.posting_date) {
        frm.doc.posting_date = frappe.datetime.get_today();
    }
    const post_date = frappe.datetime.str_to_obj(frm.doc.posting_date);
    const target = new Date(post_date.valueOf());
    const dayNr = (post_date.getDay() + 6) % 7;
    target.setDate(target.getDate() - dayNr + 3);
    const firstThursday = target.valueOf();
    target.setMonth(0, 1);
    if (target.getDay() !== 4) {
        target.setMonth(0, 1 + ((4 - target.getDay()) + 7) % 7);
    }
    const week_num = 1 + Math.ceil((firstThursday - target) / 604800000);

    const company_name = frm.doc.company;
    if (company_name) {
        frappe.db.get_value('Company', company_name, 'abbr').then(r => {
            let abbr = (r.message && r.message.abbr) ? r.message.abbr : company_name.split(' ')[0];
            const title_val = `Week ${week_num} - ${abbr}`;
            if (frm.doc.claim_title !== title_val) {
                frm.set_value('claim_title', title_val);
            }
        });
    } else {
        const title_val = `Week ${week_num} - ACM`;
        if (frm.doc.claim_title !== title_val) {
            frm.set_value('claim_title', title_val);
        }
    }
}

function calculate_grid_totals(frm) {
    let total = 0.0;
    (frm.doc.expense_lines || []).forEach(row => {
        total += flt(row.amount || 0.0);
    });
    frm.set_value('total_amount', total);
}

function validate_client_posting_date(frm) {
    if (!frm.doc.posting_date) return;
    const post_date = frappe.datetime.str_to_obj(frm.doc.posting_date);
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    if (post_date > today) {
        frappe.msgprint({
            title: __('Invalid Posting Date'),
            indicator: 'red',
            message: __('Posting Date cannot be in the future. Resetting to today.')
        });
        frm.set_value('posting_date', frappe.datetime.get_today());
    }
}

// --------------------------------------------------------------------------------------
// 2. BULLETPROOF BANK ACCOUNT MASKING (PERMANENT MASK)
// --------------------------------------------------------------------------------------
function apply_bank_account_masking(frm) {
    const field = frm.fields_dict['custodian_bank_account'];
    if (!field || !field.$wrapper) return;

    const raw_val = String(frm.doc.custodian_bank_account || '').trim();
    field.$wrapper.find('.bank-mask-ui-container').remove();

    if (!raw_val) {
        field.$wrapper.find('.control-value, .like-disabled-input, input, .disp_area').show();
        return;
    }

    const last4 = raw_val.length > 4 ? raw_val.slice(-4) : raw_val;
    const masked = '•••• •••• •••• ' + last4;

    field.$wrapper.find('.control-value, .like-disabled-input, input, .disp_area, .static-data-area').hide();

    const mask_ui = $(`
        <div class="bank-mask-ui-container" style="display: inline-flex; align-items: center; margin-top: 2px;">
            <div class="bank-acc-display" style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 13.5px; font-weight: 700; letter-spacing: 1.5px; color: #0f172a; background: #f1f5f9; padding: 5px 12px; border-radius: 6px; border: 1px solid #cbd5e1; min-width: 150px;">
                ${masked}
            </div>
        </div>
    `);

    const target = field.$wrapper.find('.control-input-wrapper');
    if (target.length) {
        target.append(mask_ui);
    } else {
        field.$wrapper.find('.control-input').append(mask_ui);
    }
}

// --------------------------------------------------------------------------------------
// 3. WORKFLOW STEPPER TRACKER
// --------------------------------------------------------------------------------------
function render_petty_cash_stepper(frm) {
    if (frm.fields_dict['sb_header'] && frm.fields_dict['sb_header'].wrapper) {
        const existing = document.getElementById('petty-cash-flow-stepper');
        if (existing) existing.remove();

        const status = frm.doc.status || 'Draft';
        let active_step = 1;

        if (status === 'Pending Admin L1') active_step = 2;
        else if (status === 'Pending Admin L2') active_step = 3;
        else if (status === 'Submitted') active_step = 4;
        else if (status === 'L1 Verified') active_step = 5;
        else if (status === 'Approved for Payment' || status === 'Queued in Batch') active_step = 5;
        else if (status === 'Paid' || status === 'Disbursed via IDFC') active_step = 6;

        const is_rejected = status === 'Rejected' || status === 'Disputed';

        const steps = [
            { num: 1, title: 'Bill Entry', icon: '📝', desc: 'Front Desk' },
            { num: 2, title: 'Admin L1', icon: '👤', desc: 'Lead Review' },
            { num: 3, title: 'Admin L2', icon: '👥', desc: 'Head Sign-off' },
            { num: 4, title: 'Accounts', icon: '🔍', desc: 'L1 Audit' },
            { num: 5, title: 'Director', icon: '⭐', desc: 'L2 Sanction' },
            { num: 6, title: 'Paid', icon: '🎉', desc: 'Bank UTR' }
        ];

        let stepper_html = `<div id="petty-cash-flow-stepper" class="ap-stepper-container">`;

        steps.forEach((step, idx) => {
            let state_class = 'step-pending';
            if (step.num < active_step) state_class = 'step-completed';
            else if (step.num === active_step) state_class = is_rejected ? 'step-error' : 'step-active';

            stepper_html += `
                <div class="ap-step-card ${state_class}">
                    <div class="step-badge">${step.num < active_step ? '✓' : step.num}</div>
                    <div class="step-info">
                        <div class="step-title">${step.icon} ${step.title}</div>
                        <div class="step-sub">${step.desc}</div>
                    </div>
                </div>
            `;
            if (idx < steps.length - 1) {
                stepper_html += `<div class="ap-step-connector ${step.num < active_step ? 'line-completed' : ''}"></div>`;
            }
        });

        stepper_html += `</div>`;
        $(frm.fields_dict['sb_header'].wrapper).prepend(stepper_html);
    }
}

// --------------------------------------------------------------------------------------
// 4. STATUS GUIDANCE BANNERS
// --------------------------------------------------------------------------------------
function render_status_guidance_banner(frm) {
    if (!frm.fields_dict['sb_header'] || !frm.fields_dict['sb_header'].wrapper) return;

    const existing = document.getElementById('petty-cash-status-banner');
    if (existing) existing.remove();

    const status = frm.doc.status || 'Draft';
    const amount_formatted = format_inr_clean(frm.doc.total_amount);
    let banner_config = null;

    if (frm.doc.admin_rejection_reason && (status === 'Draft' || status === 'Pending Admin L1')) {
        banner_config = {
            class: 'banner-rejected',
            icon: '↩️',
            title: `Returned by Admin (${frm.doc.workflow_state || 'Remarks Added'})`,
            message: `<b>Remarks:</b> "${frm.doc.admin_rejection_reason}". Please correct the line items/proofs and resubmit.`
        };
    } else if (status === 'Draft') {
        banner_config = {
            class: 'banner-draft',
            icon: '📝',
            title: 'Draft Petty Cash Voucher (Front Desk / Reception)',
            message: 'Add branch expense lines, enter amounts, attach receipt photos via <b>📷 Add Photo</b>, and submit to Admin Lead.'
        };
    } else if (status === 'Pending Admin L1') {
        banner_config = {
            class: 'banner-submitted',
            icon: '⏳',
            title: 'Stage 1: Awaiting Admin Team Lead (L1) Review',
            message: `Voucher for <b>₹ ${amount_formatted}</b> submitted by <b>${frm.doc.custodian || 'Reception'}</b> is awaiting Admin L1 review.`
        };
    } else if (status === 'Pending Admin L2') {
        banner_config = {
            class: 'banner-submitted',
            icon: '⏳',
            title: 'Stage 2: Awaiting Admin Department Head (L2) Sign-Off',
            message: `Admin Lead (<b>${frm.doc.admin_l1_approver || 'L1'}</b>) approved. Awaiting Admin Head sign-off to dispatch to Accounts.`
        };
    } else if (status === 'Submitted') {
        banner_config = {
            class: 'banner-submitted',
            icon: '🔍',
            title: 'Stage 3: Accounts L1 Audit & Verification',
            message: `Auditing lines. You can dispute individual invalid lines by clicking <b>⚠️ Dispute</b> under the Receipt column.`
        };
    } else if (status === 'L1 Verified') {
        banner_config = {
            class: 'banner-approved',
            icon: '⭐',
            title: 'Stage 4: Audited & Ready for Director Sanction (L2)',
            message: `Accounts verified <b>₹ ${amount_formatted}</b>. Waiting for Director Tier sanction.`
        };
    } else if (status === 'Approved for Payment' || status === 'Queued in Batch') {
        banner_config = {
            class: 'banner-approved',
            icon: '🔐',
            title: 'Sanctioned for Payment Disbursement',
            message: `Director sanctioned <b>₹ ${amount_formatted}</b>. Queued in upcoming corporate bank release batch.`
        };
    } else if (status === 'Paid' || status === 'Disbursed via IDFC') {
        banner_config = {
            class: 'banner-paid',
            icon: '🎉',
            title: 'Disbursed to Custodian Bank Account',
            message: `Payout successfully processed via IDFC Bank API. Imprest float replenished and posted to accounting records.`
        };
    }

    if (banner_config) {
        const banner_html = `
            <div id="petty-cash-status-banner" class="ap-status-banner ${banner_config.class}">
                <div class="banner-icon">${banner_config.icon}</div>
                <div class="banner-content">
                    <div class="banner-title">${banner_config.title}</div>
                    <div class="banner-sub">${banner_config.message}</div>
                </div>
                <div class="banner-stat">
                    <div class="stat-label">Total Amount</div>
                    <div class="stat-val">₹ ${amount_formatted}</div>
                </div>
            </div>
        `;
        $(frm.fields_dict['sb_header'].wrapper).prepend(banner_html);
    }
}

// --------------------------------------------------------------------------------------
// 5. ROLE-BASED ACTION BUTTONS
// --------------------------------------------------------------------------------------
function render_role_based_action_buttons(frm) {
    if (frm.is_new()) return;

    const status = frm.doc.status || 'Draft';
    const lines = frm.doc.expense_lines || [];
    const attachments = get_claim_attachments(frm);

    // 1-Click Excel Export
    frm.add_custom_button(__('📊 Export Excel'), function () {
        const url = `/api/method/ap_automation.services.export_service.download_voucher_excel?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
        window.open(url, '_blank');
    });

    // 1-Click Tally Journal Voucher XML Export
    const is_accounts_or_director = frappe.user.has_role([
        'Accounts L1 Auditor', 'Accounts Manager', 'Accounts Director', 'Director Tier', 'Payment Releaser', 'System Manager'
    ]) || frappe.session.user === 'Administrator';

    if (is_accounts_or_director) {
        frm.add_custom_button(__('📑 Tally Journal XML'), function () {
            frappe.call({
                method: 'ap_automation.services.tally_service.export_tally_journal_xml_for_petty_cash',
                args: { voucher_name: frm.doc.name },
                freeze: true,
                freeze_message: __('Generating Tally Journal XML...'),
                callback: function (r) {
                    if (r.message) {
                        const blob = new Blob([r.message], { type: 'application/xml;charset=utf-8' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `Tally_Journal_${frm.doc.name}.xml`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                        frappe.show_alert({ message: __('✅ Tally Journal XML downloaded! Ready for TallyPrime import.'), indicator: 'green' }, 5);
                    }
                }
            });
        });
    }

    if (attachments.length > 0) {
        frm.add_custom_button(__(`👁️ View Receipts (${attachments.length})`), () => {
            open_unified_receipt_gallery(frm, 0);
        });
        frm.add_custom_button(__('📦 Download ZIP'), () => {
            const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
            window.open(url, '_blank');
        });
    }

    // 1. RECEPTION SUBMISSION
    if (status === 'Draft' || status === 'Returned to Reception') {
        const can_admin_head_direct_submit = frappe.user.has_role([
            'Admin L2 Approver', 'Admin Manager', 'Accounts Director', 'Director Tier', 'System Manager'
        ]) || frappe.session.user === 'Administrator';

        if (can_admin_head_direct_submit) {
            frm.add_custom_button(__('⚡ Direct Submit to Accounts (Admin Head)'), function () {
                if (!lines || lines.length === 0) {
                    frappe.msgprint(__('Please add at least one expense line before submitting.'));
                    return;
                }
                frappe.confirm(__('Admin Head Direct Submission: Dispatch directly to Accounts Audit (skipping Admin L1)?'), function () {
                    frappe.call({
                        method: 'ap_automation.services.admin_approval_service.submit_to_accounts_direct',
                        args: { voucher_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Submitting directly to Accounts Audit...'),
                        callback: function (r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: __('⚡ Submitted directly to Accounts Audit!'), indicator: 'green' }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                });
            }).addClass('btn-primary').css({
                'background': 'linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)',
                'border': 'none',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }
        frm.add_custom_button(__('📤 Submit to Admin Lead'), function () {
            if (!lines || lines.length === 0) {
                frappe.msgprint(__('Please add at least one expense line before submitting.'));
                return;
            }
            frappe.confirm(__('Submit this Petty Cash Envelope to Admin Team Lead for review?'), function () {
                frappe.call({
                    method: 'ap_automation.services.admin_approval_service.submit_to_admin_l1',
                    args: { voucher_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Submitting to Admin Lead...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('✅ Submitted to Admin Lead!'), indicator: 'green' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#2563eb',
            'border-color': '#1d4ed8',
            'color': '#ffffff',
            'font-weight': '700'
        });
    }

    // 2. ADMIN L1 ACTIONS
    if (status === 'Pending Admin L1' && (frappe.user.has_role(['Admin L1 Approver', 'Admin Manager', 'System Manager']) || frappe.session.user === 'Administrator')) {
        frm.add_custom_button(__('✅ Approve (Admin L1)'), function () {
            frappe.confirm(__(`Approve voucher <b>#${frm.doc.name}</b> (₹${format_inr_clean(frm.doc.total_amount)}) and forward to Admin Department Head?`), function () {
                frappe.call({
                    method: 'ap_automation.services.admin_approval_service.approve_admin_l1',
                    args: { voucher_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Approving as Admin L1...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('✅ Approved by Admin L1!'), indicator: 'green' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#ea580c',
            'border-color': '#c2410c',
            'color': '#ffffff',
            'font-weight': '700'
        });

        frm.add_custom_button(__('↩️ Return to Reception'), function () {
            open_rejection_reason_dialog(frm, 'Admin L1', function (reason_code, remarks) {
                frappe.call({
                    method: 'ap_automation.services.admin_approval_service.return_admin_l1',
                    args: { voucher_name: frm.doc.name, reason: `[${reason_code}] ${remarks}` },
                    freeze: true,
                    freeze_message: __('Returning voucher to Reception...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('↩️ Voucher Returned to Reception'), indicator: 'orange' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }).addClass('btn-danger').css({
            'background-color': '#dc2626',
            'border-color': '#b91c1c',
            'color': '#ffffff'
        });
    }

    // 3. ADMIN L2 ACTIONS
    if (status === 'Pending Admin L2' && (frappe.user.has_role(['Admin L2 Approver', 'Admin Manager', 'Accounts Director', 'Director Tier', 'System Manager']) || frappe.session.user === 'Administrator')) {
        frm.add_custom_button(__('✅ Approve & Send to Accounts'), function () {
            frappe.confirm(__(`Final Admin Sign-Off: Dispatch voucher <b>#${frm.doc.name}</b> (₹${format_inr_clean(frm.doc.total_amount)}) to Accounts Audit?`), function () {
                frappe.call({
                    method: 'ap_automation.services.admin_approval_service.approve_admin_l2',
                    args: { voucher_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Dispatching to Accounts...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('✅ Dispatched to Accounts L1 Audit!'), indicator: 'green' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#7c3aed',
            'border-color': '#6d28d9',
            'color': '#ffffff',
            'font-weight': '700'
        });

        frm.add_custom_button(__('↩️ Return Voucher'), function () {
            open_rejection_reason_dialog(frm, 'Admin L2', function (reason_code, remarks) {
                frappe.call({
                    method: 'ap_automation.services.admin_approval_service.return_admin_l2',
                    args: { voucher_name: frm.doc.name, reason: `[${reason_code}] ${remarks}`, return_to: 'Reception' },
                    freeze: true,
                    freeze_message: __('Returning voucher...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('↩️ Voucher Returned'), indicator: 'orange' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }).addClass('btn-danger').css({
            'background-color': '#dc2626',
            'border-color': '#b91c1c',
            'color': '#ffffff'
        });
    }

    // 4. ACCOUNTS AUDIT ACTIONS (Line-by-Line Approve & Dispute Execution)
    if (status === 'Submitted' && (frappe.user.has_role(['Accounts L1 Auditor', 'Accounts Manager', 'Accounts Director', 'Director Tier', 'System Manager']) || frappe.session.user === 'Administrator')) {
        const is_director_tier = frappe.user.has_role(['Accounts Director', 'Director Tier', 'System Manager']) || frappe.session.user === 'Administrator';

        if (is_director_tier) {
            frm.add_custom_button(__('⚡ Direct Director Sanction (Skip L1)'), function () {
                frappe.confirm(__(`Executive Direct Sanction: Sanction payment of <b>₹${format_inr_clean(frm.doc.total_amount)}</b> directly (bypassing Accounts L1)?`), function () {
                    frappe.call({
                        method: 'ap_automation.services.director_approval_service.sanction_accounts_director',
                        args: { voucher_doctype: frm.doc.doctype, voucher_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Sanctioning payment release...'),
                        callback: function (r) {
                            if (!r.exc) {
                                frappe.show_alert({ message: __('⚡ Sanctioned directly for Payment Release!'), indicator: 'green' }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                });
            }).addClass('btn-primary').css({
                'background': 'linear-gradient(135deg, #059669 0%, #047857 100%)',
                'border': 'none',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }
        const disputed_lines = lines.filter(l => l.is_disputed);
        const approved_lines = lines.filter(l => !l.is_disputed);

        if (disputed_lines.length > 0) {
            frm.add_custom_button(__(`⚡ Approve Clean (${approved_lines.length}) & Fork Disputed (${disputed_lines.length})`), function () {
                frappe.confirm(
                    __(`You have marked <b>${disputed_lines.length} disputed line(s)</b> and <b>${approved_lines.length} approved line(s)</b>.<br><br>` +
                       `• Approved lines will advance to <b>Director Tier</b>.<br>` +
                       `• Disputed lines will be forked and returned to <b>Reception</b>.<br><br>Proceed?`),
                    function () {
                        let disputed_indices = [];
                        let dispute_reasons = {};
                        lines.forEach((l, idx) => {
                            if (l.is_disputed) {
                                disputed_indices.push(idx);
                                dispute_reasons[idx] = l.dispute_reason || 'Disputed during Accounts L1 audit';
                            }
                        });

                        frappe.call({
                            method: 'ap_automation.services.dispute_service.api_dispute_split',
                            args: {
                                parent_docname: frm.doc.name,
                                disputed_indices: disputed_indices,
                                dispute_reasons: dispute_reasons
                            },
                            freeze: true,
                            freeze_message: __('Forking disputed lines and forwarding approved lines...'),
                            callback: function (r) {
                                if (r.message && r.message.status === 'split_success') {
                                    frappe.db.set_value('Petty Cash Entry', frm.doc.name, {
                                        status: 'L1 Verified',
                                        workflow_state: 'Audited & Verified by Accounts L1 (Disputed Lines Forked)',
                                        current_approval_level: 2
                                    }).then(() => {
                                        frappe.show_alert({
                                            message: __(`🎉 Split Complete! Approved lines sent to Director. Disputed voucher #${r.message.forked_voucher} returned to submitter.`),
                                            indicator: 'green'
                                        }, 7);
                                        frm.reload_doc();
                                    });
                                }
                            }
                        });
                    }
                );
            }).addClass('btn-primary').css({
                'background': 'linear-gradient(135deg, #16a34a 0%, #0d9488 100%)',
                'color': '#ffffff',
                'font-weight': '700',
                'border': 'none'
            });
        } else {
            frm.add_custom_button(__('✅ Audit & Pass to Director'), function () {
                frappe.confirm(__('Pass all line items as verified and forward to Director for final sanction?'), function () {
                    frm.set_value('status', 'L1 Verified');
                    frm.set_value('workflow_state', 'Audited & Verified by Accounts L1');
                    frm.set_value('current_approval_level', 2);
                    frm.save().then(() => {
                        frappe.show_alert({ message: __('✅ Passed to Director Tier!'), indicator: 'green' }, 5);
                    });
                });
            }).addClass('btn-primary').css({
                'background-color': '#16a34a',
                'border-color': '#15803d',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }

        if (lines.length > 1) {
            frm.add_custom_button(__('⚠️ Dispute Split Helper'), function () {
                open_dispute_split_dialog(frm);
            }).addClass('btn-secondary').css({
                'background-color': '#f59e0b',
                'border-color': '#d97706',
                'color': '#ffffff',
                'font-weight': '600'
            });
        }
    }

    // 5. DIRECTOR TIER ACTIONS
    const can_sanction_or_reject = frappe.user.has_role([
        'Accounts Director', 'Director Tier', 'Payment Releaser', 'System Manager'
    ]) || frappe.session.user === 'Administrator';

    if (status === 'L1 Verified' && can_sanction_or_reject) {
        const disputed_lines = lines.filter(l => l.is_disputed);
        const approved_lines = lines.filter(l => !l.is_disputed);

        if (disputed_lines.length > 0) {
            frm.add_custom_button(__(`⚡ Sanction Clean (${approved_lines.length}) & Fork Disputed (${disputed_lines.length}) for Payment`), function () {
                frappe.confirm(
                    __(`Executive Dispute & Sanction:<br><br>` +
                       `• <b>${approved_lines.length} Clean Line(s)</b> will be <b>Sanctioned for Payment Release</b> immediately.<br>` +
                       `• <b>${disputed_lines.length} Disputed Line(s)</b> will be forked and returned to <b>Reception</b>.<br><br>Proceed?`),
                    function () {
                        let disputed_indices = [];
                        let dispute_reasons = {};
                        lines.forEach((l, idx) => {
                            if (l.is_disputed) {
                                disputed_indices.push(idx);
                                dispute_reasons[idx] = l.dispute_reason || 'Disputed during Director review';
                            }
                        });

                        frappe.call({
                            method: 'ap_automation.services.dispute_service.api_dispute_split',
                            args: {
                                parent_docname: frm.doc.name,
                                disputed_indices: disputed_indices,
                                dispute_reasons: dispute_reasons
                            },
                            freeze: true,
                            freeze_message: __('Forking disputed lines and sanctioning clean lines...'),
                            callback: function (r) {
                                if (r.message && r.message.status === 'split_success') {
                                    frappe.call({
                                        method: 'ap_automation.services.director_approval_service.sanction_accounts_director',
                                        args: { voucher_doctype: frm.doc.doctype, voucher_name: frm.doc.name, comments: 'Clean lines sanctioned for payment release; disputed lines forked to Reception.' },
                                        freeze: true,
                                        callback: function (res) {
                                            frappe.show_alert({
                                                message: __(`🎉 Clean lines sanctioned for Payment Release! Disputed voucher #${r.message.forked_voucher} returned to Reception.`),
                                                indicator: 'green'
                                            }, 7);
                                            frm.reload_doc();
                                        }
                                    });
                                }
                            }
                        });
                    }
                );
            }).addClass('btn-primary').css({
                'background': 'linear-gradient(135deg, #059669 0%, #0d9488 100%)',
                'color': '#ffffff',
                'font-weight': '700',
                'border': 'none'
            });
        }

        if (lines.length > 1) {
            frm.add_custom_button(__('⚠️ Dispute Split Helper'), function () {
                open_dispute_split_dialog(frm);
            }).addClass('btn-secondary').css({
                'background-color': '#f59e0b',
                'border-color': '#d97706',
                'color': '#ffffff',
                'font-weight': '600'
            });
        }

        frm.add_custom_button(__('✅ Sanction Payment'), function () {
            frappe.confirm(__(`Sanction payment of <b>₹${format_inr_clean(frm.doc.total_amount)}</b> for IDFC corporate batch release?`), function () {
                frappe.call({
                    method: 'ap_automation.services.director_approval_service.sanction_accounts_director',
                    args: { voucher_doctype: frm.doc.doctype, voucher_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Sanctioning payment release...'),
                    callback: function (r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('✅ Sanctioned for Payment Release!'), indicator: 'green' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#16a34a',
            'border-color': '#15803d',
            'color': '#ffffff',
            'font-weight': '700'
        });

        frm.add_custom_button(__('🚫 Reject / Return (Director Sign-Off)'), function () {
            open_rejection_reason_dialog(frm, 'Accounts Director / Payment Releaser', function (reason_code, remarks, return_to) {
                frappe.call({
                    method: 'ap_automation.services.director_approval_service.reject_accounts_director',
                    args: {
                        voucher_doctype: frm.doc.doctype,
                        voucher_name: frm.doc.name,
                        reason: `[${reason_code}] ${remarks}`,
                        return_to: return_to || 'Accounts L1'
                    },
                    freeze: true,
                    freeze_message: __('Processing rejection...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('🚫 Voucher Returned / Rejected'), indicator: 'red' }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }).addClass('btn-secondary').css({
            'background-color': '#ef4444',
            'border-color': '#dc2626',
            'color': '#ffffff',
            'font-weight': '700'
        });
    }
}

// --------------------------------------------------------------------------------------
// 6. IN-GRID DEDICATED RECEIPT PHOTO & DEDICATED DECISION COLUMN
// --------------------------------------------------------------------------------------
function bind_custom_grid_uploaders_and_review(frm) {
    if (!frm.fields_dict['expense_lines'] || !frm.fields_dict['expense_lines'].grid) return;

    const grid = frm.fields_dict['expense_lines'].grid;
    const grid_rows = (grid.wrapper || $(grid.parent)).find('.grid-body .grid-row');
    const is_review_stage = ['Pending Admin L1', 'Pending Admin L2', 'Submitted', 'L1 Verified'].includes(frm.doc.status);

    grid_rows.each(function (idx) {
        const row_elem = $(this);
        const row_data = (frm.doc.expense_lines || [])[idx];
        if (!row_data) return;

        // Clean up any row-index badge pollution
        row_elem.find('.row-index .line-dispute-pill').remove();

        // 1. DEDICATED RECEIPT COLUMN (Receipt Photo Only: Attached or Add Photo)
        const cell_receipt = row_elem.find('.grid-static-col[data-fieldname="receipt_attachment"]');
        if (cell_receipt.length) {
            cell_receipt.empty();

            const current_val = row_data.receipt_attachment;
            let receipt_btn_html = '';

            if (current_val) {
                receipt_btn_html = `
                    <div class="ap-attached-badge" style="display:inline-flex; align-items:center; justify-content:center; gap:4px; background:#ecfdf5; border:1px solid #10b981; border-radius:5px; padding:3px 8px; cursor:pointer; width:100%; box-sizing:border-box;" title="Click to view receipt photo">
                        <span style="font-size:11px;">🧾</span>
                        <span style="font-size:11px; font-weight:700; color:#065f46;">Attached</span>
                    </div>
                `;
            } else {
                receipt_btn_html = `
                    <button type="button" class="btn btn-xs btn-default ap-upload-btn" style="border:1px dashed #94a3b8; color:#475569; font-size:11px; font-weight:600; padding:2px 8px; border-radius:4px; background:#f8fafc; cursor:pointer; width:100%; box-sizing:border-box;" title="Upload bill receipt photo">
                        📷 Add Photo
                    </button>
                `;
            }

            const receipt_container = $(receipt_btn_html);

            receipt_container.filter('.ap-attached-badge').add(receipt_container.find('.ap-attached-badge')).on('click', function (e) {
                e.stopPropagation();
                open_unified_receipt_gallery(frm, idx);
            });

            receipt_container.filter('.ap-upload-btn').add(receipt_container.find('.ap-upload-btn')).on('click', function (e) {
                e.stopPropagation();
                new frappe.ui.FileUploader({
                    folder: 'Home/Attachments',
                    on_success: (file_doc) => {
                        frappe.model.set_value(row_data.doctype, row_data.name, 'receipt_attachment', file_doc.file_url);
                        calculate_grid_totals(frm);
                        setTimeout(() => bind_custom_grid_uploaders_and_review(frm), 200);
                    }
                });
            });

            cell_receipt.append(receipt_container);
        }

        // 2. DEDICATED DECISION COLUMN (Separate Column for Approve & Dispute Actions)
        const cell_decision = row_elem.find('.grid-static-col[data-fieldname="line_decision"]');
        if (cell_decision.length) {
            cell_decision.empty();

            let decision_html = '';
            if (is_review_stage) {
                if (row_data.is_disputed) {
                    row_elem.css({ 'background-color': '#fef2f2', 'border-left': '4px solid #ef4444' });
                    decision_html = `
                        <div style="display:flex; align-items:center; justify-content:center; gap:5px; flex-wrap:nowrap;">
                            <span class="badge" style="background:#fee2e2; border:1px solid #f87171; color:#b91c1c; font-size:10px; font-weight:700; padding:3px 7px; border-radius:4px; white-space:nowrap;" title="${row_data.dispute_reason || 'Disputed'}">
                                ⚠️ Disputed
                            </span>
                            <button type="button" class="btn btn-xs btn-default btn-clear-dispute" style="padding:2px 6px; font-size:10px; color:#475569; background:#ffffff; border:1px solid #cbd5e1; border-radius:4px; cursor:pointer;" title="Undo Dispute (Mark OK)">
                                ↩️ Reset
                            </button>
                        </div>
                    `;
                } else {
                    row_elem.css({ 'background-color': '', 'border-left': '' });
                    decision_html = `
                        <div style="display:flex; align-items:center; justify-content:center; gap:6px; flex-wrap:nowrap;">
                            <button type="button" class="btn btn-xs btn-line-ok" style="background:#f0fdf4; border:1px solid #86efac; color:#15803d; font-size:10.5px; font-weight:700; padding:2px 8px; border-radius:4px; cursor:pointer; display:inline-flex; align-items:center; gap:3px;" title="Line is Verified OK">
                                ✅ OK
                            </button>
                            <button type="button" class="btn btn-xs btn-outline-warning btn-line-dispute" style="font-size:10.5px; font-weight:700; padding:2px 8px; border-radius:4px; color:#b45309; background:#fffbeb; border:1px solid #fcd34d; cursor:pointer; display:inline-flex; align-items:center; gap:3px;" title="Dispute this line item">
                                ⚠️ Dispute
                            </button>
                        </div>
                    `;
                }
            } else {
                if (row_data.is_disputed) {
                    decision_html = `
                        <div style="display:flex; align-items:center; justify-content:center;">
                            <span class="badge" style="background:#fee2e2; border:1px solid #f87171; color:#b91c1c; font-size:10px; font-weight:700; padding:3px 7px; border-radius:4px;" title="${row_data.dispute_reason || 'Disputed'}">
                                ⚠️ Disputed
                            </span>
                        </div>
                    `;
                } else {
                    decision_html = `
                        <div style="display:flex; align-items:center; justify-content:center;">
                            <span style="color:#15803d; font-size:11px; font-weight:700; display:inline-flex; align-items:center; gap:3px;">
                                ✅ OK
                            </span>
                        </div>
                    `;
                }
            }

            const decision_container = $(decision_html);

            decision_container.find('.btn-line-ok').add(decision_container.filter('.btn-line-ok')).on('click', function (e) {
                e.stopPropagation();
                frappe.show_alert({ message: __('Line #' + row_data.idx + ' verified OK'), indicator: 'green' }, 2);
            });

            decision_container.find('.btn-line-dispute').add(decision_container.filter('.btn-line-dispute')).on('click', function (e) {
                e.stopPropagation();
                open_single_line_dispute_dialog(frm, row_data);
            });

            decision_container.find('.btn-clear-dispute').add(decision_container.filter('.btn-clear-dispute')).on('click', function (e) {
                e.stopPropagation();
                frappe.model.set_value(row_data.doctype, row_data.name, 'is_disputed', 0);
                frappe.model.set_value(row_data.doctype, row_data.name, 'dispute_reason', '');
                render_role_based_action_buttons(frm);
                setTimeout(() => bind_custom_grid_uploaders_and_review(frm), 150);
            });

            cell_decision.append(decision_container);
        }
    });
}

function open_single_line_dispute_dialog(frm, row_data) {
    let d = new frappe.ui.Dialog({
        title: __(`⚠️ Dispute Line #${row_data.idx}: ${row_data.merchant_name || 'Expense'}`),
        fields: [
            {
                fieldname: 'reason_code',
                fieldtype: 'Select',
                label: __('Dispute Reason Code'),
                options: [
                    'Missing / Illegible Bill Photo',
                    'Incorrect Amount / Tax Rate',
                    'Non-Compliant Expense Category',
                    'Duplicate Expense Entry',
                    'Unapproved Expenditure',
                    'Other Reason'
                ].join('\n'),
                default: 'Missing / Illegible Bill Photo',
                reqd: 1
            },
            {
                fieldname: 'remarks',
                fieldtype: 'Small Text',
                label: __('Specific Remarks for Submitter'),
                reqd: 1,
                description: __('Explain what needs to be corrected so the submitter can fix it.')
            }
        ],
        primary_action_label: __('Mark as Disputed'),
        primary_action(values) {
            frappe.model.set_value(row_data.doctype, row_data.name, 'is_disputed', 1);
            frappe.model.set_value(row_data.doctype, row_data.name, 'dispute_reason', `[${values.reason_code}] ${values.remarks.trim()}`);
            d.hide();
            frappe.show_alert({
                message: __(`⚠️ Line #${row_data.idx} marked as Disputed. Click 'Approve Clean & Fork Disputed' to finalize.`),
                indicator: 'orange'
            }, 5);
            render_role_based_action_buttons(frm);
            setTimeout(() => bind_custom_grid_uploaders_and_review(frm), 150);
        }
    });
    d.show();
}

function open_dispute_split_dialog(frm) {
    let fields = [
        {
            fieldname: "info",
            fieldtype: "HTML",
            options: `
                <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 10px; margin-bottom: 12px; font-size: 12.5px; color: #92400e;">
                    Select lines to dispute. Approved lines advance to Director, while disputed lines fork and return to submitter.
                </div>
            `
        }
    ];

    (frm.doc.expense_lines || []).forEach((row, idx) => {
        fields.push({
            fieldname: `dispute_${idx}`,
            fieldtype: "Check",
            label: `Line #${row.idx || (idx + 1)}: <b>${row.merchant_name}</b> — ₹ ${Number(row.amount || 0).toLocaleString('en-IN')}`,
            default: row.is_disputed || 0
        });
        fields.push({
            fieldname: `reason_${idx}`,
            fieldtype: "Data",
            label: `Dispute Reason for Line #${row.idx || (idx + 1)}`,
            depends_on: `eval:doc.dispute_${idx} == 1`,
            default: row.dispute_reason || ""
        });
    });

    let d = new frappe.ui.Dialog({
        title: __("⚠️ Dispute Lines & Split Voucher"),
        fields: fields,
        primary_action_label: __("Split & Fork Disputed Lines"),
        primary_action(values) {
            let disputed_indices = [];
            let dispute_reasons = {};

            (frm.doc.expense_lines || []).forEach((row, idx) => {
                if (values[`dispute_${idx}`]) {
                    disputed_indices.push(idx);
                    dispute_reasons[idx] = values[`reason_${idx}`] || "Disputed during review";
                }
            });

            if (disputed_indices.length === 0) {
                frappe.msgprint(__("Please select at least one line to dispute."));
                return;
            }

            frappe.call({
                method: "ap_automation.services.dispute_service.api_dispute_split",
                args: {
                    parent_docname: frm.doc.name,
                    disputed_indices: disputed_indices,
                    dispute_reasons: dispute_reasons
                },
                freeze: true,
                freeze_message: __("Splitting voucher..."),
                callback: function (r) {
                    if (r.message && r.message.status === "split_success") {
                        d.hide();
                        frappe.show_alert({
                            message: __(`🎉 Voucher split successfully! Clean lines remain on #${frm.doc.name}.`),
                            indicator: "green"
                        }, 5);
                        frm.reload_doc();
                    }
                }
            });
        }
    });
    d.show();
}

function open_rejection_reason_dialog(frm, role_title, callback) {
    let fields = [
        {
            fieldname: 'reason_code',
            fieldtype: 'Select',
            label: __('Rejection Reason Code'),
            options: [
                'Missing / Illegible Bill',
                'Duplicate Submission',
                'Non-Compliant Category',
                'Incorrect Amount / Tax Head',
                'Unapproved Spend',
                'GST Invoice / GSTIN Mismatch',
                'Other Operational Issue'
            ].join('\n'),
            default: 'Missing / Illegible Bill',
            reqd: 1
        },
        {
            fieldname: 'remarks',
            fieldtype: 'Small Text',
            label: __('Detailed Rejection Remarks (Mandatory)'),
            reqd: 1
        }
    ];

    if (role_title.includes('Admin L2') || role_title.includes('Admin Department Head')) {
        fields.push({
            fieldname: 'return_to',
            fieldtype: 'Select',
            label: __('Return Destination'),
            options: 'Reception (Front Desk)\nAdmin L1 Supervisor',
            default: 'Reception (Front Desk)',
            reqd: 1
        });
    } else if (role_title.includes('Director') || role_title.includes('Payment Releaser')) {
        fields.push({
            fieldname: 'return_to',
            fieldtype: 'Select',
            label: __('Return Destination'),
            options: 'Accounts L1\nReception (Front Desk)',
            default: 'Accounts L1',
            reqd: 1
        });
    }

    let d = new frappe.ui.Dialog({
        title: __(`🚫 Reject / Return Voucher (${role_title})`),
        fields: fields,
        primary_action_label: __('Submit Rejection'),
        primary_action(values) {
            if (!values.remarks || !values.remarks.trim()) {
                frappe.msgprint(__('Detailed remarks are strictly mandatory for rejection.'));
                return;
            }
            d.hide();
            callback(values.reason_code, values.remarks.trim(), values.return_to);
        }
    });
    d.show();
}

function format_inr_clean(amt) {
    return Number(amt || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function get_claim_attachments(frm) {
    const atts = [];
    (frm.doc.expense_lines || []).forEach((row, idx) => {
        if (row.receipt_attachment) {
            atts.push(row.receipt_attachment);
        }
    });
    return atts;
}

function open_unified_receipt_gallery(frm, start_idx) {
    if (typeof window.APReceiptGallery !== 'undefined' && typeof window.APReceiptGallery.show === 'function') {
        window.APReceiptGallery.show(frm, { active_index: start_idx });
        return;
    }
    const atts = [];
    (frm.doc.expense_lines || []).forEach((row, idx) => {
        if (row.receipt_attachment) {
            const clean_url = row.receipt_attachment.trim();
            const file_name = clean_url.split('/').pop();
            const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
            atts.push({
                row_idx: row.idx || (idx + 1),
                merchant: row.merchant_name || 'Expense Line',
                category: row.expense_category || 'General',
                amount: parseFloat(row.amount || 0.0),
                date: row.expense_date || frm.doc.posting_date || '',
                file_url: clean_url,
                file_name: file_name,
                is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext),
                is_pdf: ext === '.pdf',
                extension: ext
            });
        }
    });

    if (atts.length === 0) {
        frappe.msgprint(__('No receipts attached to this voucher.'));
        return;
    }

    let current_index = start_idx >= 0 && start_idx < atts.length ? start_idx : 0;
    const d = new frappe.ui.Dialog({
        title: __('Proof & Receipt Gallery — ') + frm.doc.name,
        size: 'extra-large',
        fields: [{ fieldtype: 'HTML', fieldname: 'gallery_area' }]
    });
    d.show();
}

function apply_petty_cash_styles() {
    if (!document.getElementById('petty-cash-flow-styles')) {
        const style = document.createElement('style');
        style.id = 'petty-cash-flow-styles';
        style.innerHTML = `
            .ap-stepper-container { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 12px; overflow-x: auto; }
            .ap-step-card { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 6px; background: #ffffff; border: 1px solid #e2e8f0; flex: 1; transition: all 0.15s ease; }
            .ap-step-card.step-completed { background: #f0fdf4; border-color: #86efac; }
            .ap-step-card.step-completed .step-badge { background: #16a34a; color: #ffffff; }
            .ap-step-card.step-completed .step-title { color: #15803d; }
            .ap-step-card.step-active { background: #eff6ff; border-color: #93c5fd; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15); }
            .ap-step-card.step-active .step-badge { background: #2563eb; color: #ffffff; }
            .ap-step-card.step-active .step-title { color: #1d4ed8; }
            .ap-step-card.step-error { background: #fef2f2; border-color: #fca5a5; }
            .ap-step-card.step-error .step-badge { background: #dc2626; color: #ffffff; }
            .ap-step-card.step-pending { opacity: 0.65; }
            .step-badge { width: 22px; height: 22px; border-radius: 50%; background: #cbd5e1; color: #475569; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
            .step-title { font-size: 12px; font-weight: 700; color: #334155; line-height: 1.2; }
            .step-sub { font-size: 10.5px; color: #64748b; line-height: 1.2; }
            .ap-step-connector { width: 14px; height: 2px; background: #e2e8f0; flex-shrink: 0; }
            .ap-step-connector.line-completed { background: #86efac; }

            .ap-status-banner { display: flex; align-items: center; gap: 14px; padding: 12px 18px; border-radius: 9px; margin-bottom: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
            .banner-icon { font-size: 24px; flex-shrink: 0; }
            .banner-content { flex: 1; }
            .banner-title { font-size: 13.5px; font-weight: 700; margin-bottom: 2px; }
            .banner-sub { font-size: 12px; opacity: 0.9; }
            .banner-stat { text-align: right; flex-shrink: 0; }
            .stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600; opacity: 0.75; }
            .stat-val { font-size: 17px; font-weight: 800; font-family: inherit; }
            .banner-draft { background: #f8fafc; border: 1.5px solid #e2e8f0; color: #334155; }
            .banner-submitted { background: #eff6ff; border: 1.5px solid #bfdbfe; color: #1e40af; }
            .banner-approved { background: #f0fdf4; border: 1.5px solid #bbf7d0; color: #166534; }
            .banner-paid { background: #f0fdf4; border: 1.5px solid #86efac; color: #14532d; }
            .banner-rejected { background: #fef2f2; border: 1.5px solid #fecaca; color: #991b1b; }
        `;
        document.head.appendChild(style);
    }
}

function setup_dispute_merge_helper(frm) {
    if (frm.is_new() || frm.doc.status !== "Draft") return;

    frappe.call({
        method: "ap_automation.services.dispute_service.get_pending_disputed_vouchers",
        args: { company: frm.doc.company, custodian: frm.doc.custodian },
        callback: function (r) {
            if (r.message && r.message.status === "SUCCESS" && r.message.count > 0) {
                const count = r.message.count;
                const vouchers = r.message.vouchers;
                frm.add_custom_button(__(`📥 Merge Disputed Bills (${count})`), function () {
                    open_dispute_merge_dialog(frm, vouchers);
                }).addClass("btn-warning").css({
                    "background": "linear-gradient(135deg, #f59e0b 0%, #d97706 100%)",
                    "color": "#ffffff",
                    "font-weight": "700",
                    "border": "none"
                });
            }
        }
    });
}

function open_dispute_merge_dialog(frm, vouchers) {
    let fields = [
        {
            fieldname: "info_html",
            fieldtype: "HTML",
            options: `
                <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 12px 16px; margin-bottom: 14px;">
                    <div style="font-weight: 700; color: #92400e; font-size: 13.5px; margin-bottom: 4px;">
                        💡 Absorb Carried-Forward Bills into This Voucher
                    </div>
                    <div style="font-size: 12.5px; color: #78350f; line-height: 1.4;">
                        Select previous disputed vouchers below to merge into <b>#${frm.doc.name}</b>. Disputed lines will be appended so you can attach updated proofs and submit a single consolidated voucher.
                    </div>
                </div>
            `
        }
    ];

    vouchers.forEach((v, idx) => {
        let lines_summary = v.lines.map(l => `• <b>${l.merchant_name}</b> (₹ ${l.amount.toLocaleString('en-IN')}) — <span style="color: #b91c1c;">Reason: ${l.dispute_reason}</span>`).join('<br>');
        fields.push({
            fieldname: `merge_${idx}`,
            fieldtype: "Check",
            label: `<b>${v.name}</b> (${v.claim_title}) — <b>₹ ${v.total_amount.toLocaleString('en-IN')}</b>`,
            default: 1,
            description: `<div style="font-size: 11.5px; color: #475569; margin: 4px 0 8px 24px; padding-left: 8px; border-left: 2px solid #cbd5e1;">${lines_summary}</div>`
        });
    });

    let d = new frappe.ui.Dialog({
        title: __("📥 Merge Disputed Lines into Current Cycle"),
        fields: fields,
        primary_action_label: __("Merge Lines into Voucher"),
        primary_action(values) {
            let selected_vouchers = [];
            vouchers.forEach((v, idx) => {
                if (values[`merge_${idx}`]) selected_vouchers.push(v.name);
            });

            if (selected_vouchers.length === 0) {
                frappe.msgprint(__("Please select at least one disputed voucher to merge."));
                return;
            }

            frappe.call({
                method: "ap_automation.services.dispute_service.merge_disputed_voucher_into_target",
                args: { target_voucher_name: frm.doc.name, source_dispute_voucher_names: selected_vouchers },
                freeze: true,
                freeze_message: __("Merging disputed lines into voucher..."),
                callback: function (r) {
                    if (r.message && r.message.status === "SUCCESS") {
                        d.hide();
                        frappe.show_alert({
                            message: __(`🎉 Successfully merged ${r.message.merged_lines_count} line(s) totaling ₹ ${r.message.merged_amount.toLocaleString('en-IN')}`),
                            indicator: "green"
                        }, 5);
                        frm.reload_doc();
                    }
                }
            });
        }
    });
    d.show();
}
