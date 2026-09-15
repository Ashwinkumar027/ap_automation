// Petty Cash Entry Master Controller (Lane 1 - Imprest Flow)
// 6-Step Corporate Lifecycle:
// Front Desk Submission -> Assistant Admin Manager Approval -> Admin Manager Approval -> Accounts Audit -> Director Approval -> IDFC 2FA Payment Release

frappe.ui.form.on('Petty Cash Entry', {
    onload: function (frm) {
        if (frm.is_new()) {
            if (!frm.doc.submitted_by) {
                frm.set_value('submitted_by', frappe.session.user);
            }
            if (!frm.doc.posting_date) {
                frm.set_value('posting_date', frappe.datetime.get_today());
            }
        }

        // Filter Beneficiary Employee by Company
        frm.set_query('beneficiary_employee', function() {
            if (frm.doc.company) {
                return {
                    filters: {
                        company: frm.doc.company,
                        status: 'Active'
                    }
                };
            }
            return {
                filters: {
                    status: 'Active'
                }
            };
        });
    },

    company: function(frm) {
        if (frm.doc.company) {
            frm.set_value('beneficiary_employee', '');
            frm.set_value('beneficiary_name', '');
            frm.set_value('custodian_bank_account', '');
            frm.set_value('custodian_ifsc_code', '');
            frm.set_value('bank_name', '');
        }
    },

    beneficiary_employee: function(frm) {
        if (frm.doc.beneficiary_employee) {
            frappe.db.get_value('Employee', frm.doc.beneficiary_employee, [
                'employee_name', 'bank_name', 'bank_ac_no', 'ifsc_code', 'user_id', 'prefered_email'
            ], (r) => {
                if (r) {
                    frm.set_value('beneficiary_name', r.employee_name || '');
                    frm.set_value('custodian_bank_account', r.bank_ac_no || '');
                    frm.set_value('custodian_ifsc_code', r.ifsc_code || '');
                    frm.set_value('bank_name', r.bank_name || 'IDFC FIRST Bank');
                    if (r.user_id || r.prefered_email) {
                        frm.set_value('custodian', r.user_id || r.prefered_email);
                    }

                    if (r.bank_ac_no && r.ifsc_code) {
                        frappe.show_alert({
                            message: __(`🏦 Bank Details Loaded for <b>${r.employee_name}</b> (A/C: ${r.bank_ac_no})`),
                            indicator: 'green'
                        }, 4);
                    } else {
                        frappe.show_alert({
                            message: __(`⚠️ Bank account details not found in HRMS for ${r.employee_name}. Please update in Employee master.`),
                            indicator: 'orange'
                        }, 5);
                    }
                }
            });
        }
    },

    refresh: function (frm) {
        apply_petty_cash_styles();
        render_petty_cash_stepper(frm);
        render_status_guidance_banner(frm);
        render_role_based_action_buttons(frm);
        bind_custom_grid_uploaders(frm);
    },

    validate: function (frm) {
        calculate_grid_totals(frm);
    }
});

frappe.ui.form.on('Petty Cash Line Item', {
    amount: function (frm) {
        calculate_grid_totals(frm);
    },
    expense_lines_remove: function (frm) {
        calculate_grid_totals(frm);
    },
    expense_lines_add: function (frm) {
        calculate_grid_totals(frm);
        setTimeout(() => bind_custom_grid_uploaders(frm), 250);
    }
});

// --------------------------------------------------------------------------------------
// 1. DYNAMIC GRID TOTALS CALCULATION
// --------------------------------------------------------------------------------------
function calculate_grid_totals(frm) {
    let total = 0.0;
    (frm.doc.expense_lines || []).forEach(row => {
        total += flt(row.amount || 0.0);
    });
    frm.set_value('total_amount', total);
}

// --------------------------------------------------------------------------------------
// 2. 6-STEP VISUAL WORKFLOW STEPPER TRACKER
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
            { num: 2, title: 'Admin L1', icon: '👤', desc: 'Asst. Admin Mgr' },
            { num: 3, title: 'Admin L2', icon: '👥', desc: 'Admin Mgr' },
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
// 3. STATUS GUIDANCE & RETURN ALERT BANNERS
// --------------------------------------------------------------------------------------
function render_status_guidance_banner(frm) {
    if (!frm.fields_dict['sb_header'] || !frm.fields_dict['sb_header'].wrapper) return;

    const existing = document.getElementById('petty-cash-status-banner');
    if (existing) existing.remove();

    const status = frm.doc.status || 'Draft';
    const amount_formatted = format_inr_clean(frm.doc.total_amount);
    const payee_display = frm.doc.beneficiary_name ? ` (Payee: <b>${frm.doc.beneficiary_name}</b>)` : '';
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
            title: 'Draft Petty Cash Voucher (Front Desk / Reception Entry)',
            message: `Enter branch expenses, select the <b>Beneficiary Employee (Admin Head)</b>${payee_display}, attach receipt photos, and submit to Assistant Admin Manager.`
        };
    } else if (status === 'Pending Admin L1') {
        banner_config = {
            class: 'banner-submitted',
            icon: '⏳',
            title: 'Stage 1: Awaiting Assistant Admin Manager (L1) Review',
            message: `Voucher for <b>₹ ${amount_formatted}</b>${payee_display} submitted by <b>${frm.doc.submitted_by || frm.doc.custodian || 'Reception'}</b> is awaiting Assistant Admin Manager review.`
        };
    } else if (status === 'Pending Admin L2') {
        banner_config = {
            class: 'banner-submitted',
            icon: '⏳',
            title: 'Stage 2: Awaiting Admin Manager (L2) Sign-Off',
            message: `Assistant Admin Manager (<b>${frm.doc.admin_l1_approver || 'L1'}</b>) approved. Awaiting Admin Manager sign-off to dispatch to Accounts.`
        };
    } else if (status === 'Submitted') {
        banner_config = {
            class: 'banner-submitted',
            icon: '🔍',
            title: 'Stage 3: Awaiting Accounts Audit (Finance L1)',
            message: `Admin pre-approvals complete. Accounts team is verifying tax compliance, receipts, and GST for payout to <b>${frm.doc.beneficiary_name || 'Admin Head'}</b>.`
        };
    } else if (status === 'L1 Verified') {
        banner_config = {
            class: 'banner-approved',
            icon: '⭐',
            title: 'Stage 4: Audited & Ready for Director Sanction (L2)',
            message: `Accounts verified <b>₹ ${amount_formatted}</b> with zero discrepancies. Waiting for Director Tier (Anshul Sir) sanction.`
        };
    } else if (status === 'Approved for Payment' || status === 'Queued in Batch') {
        banner_config = {
            class: 'banner-approved',
            icon: '🔐',
            title: 'Sanctioned for Payment Disbursement',
            message: `Director sanctioned <b>₹ ${amount_formatted}</b> for <b>${frm.doc.beneficiary_name || 'Admin Head'}</b>. Queued in upcoming Thursday corporate bank release batch.`
        };
    } else if (status === 'Paid' || status === 'Disbursed via IDFC') {
        banner_config = {
            class: 'banner-paid',
            icon: '🎉',
            title: 'Disbursed to Beneficiary Bank Account',
            message: `Payout successfully processed via IDFC Bank API to <b>${frm.doc.beneficiary_name || 'Admin Head'}</b> (A/C: ${frm.doc.custodian_bank_account || ''}). Float replenished.`
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
                    <div class="stat-label">Claim Total</div>
                    <div class="stat-val">₹ ${amount_formatted}</div>
                </div>
            </div>
        `;
        $(frm.fields_dict['sb_header'].wrapper).prepend(banner_html);
    }
}

// --------------------------------------------------------------------------------------
// 4. ROLE-BASED DYNAMIC ACTION BUTTONS
// --------------------------------------------------------------------------------------
function render_role_based_action_buttons(frm) {
    if (frm.is_new()) return;

    frm.clear_custom_buttons();
    const status = frm.doc.status || 'Draft';
    const lines = frm.doc.expense_lines || [];
    const attachments = lines.filter(r => r.receipt_attachment);

    // Common Proof Viewers
    if (attachments.length > 0) {
        frm.add_custom_button(__(`👁️ View Receipts (${attachments.length})`), () => {
            open_unified_receipt_gallery(frm, 0);
        });

        frm.add_custom_button(__('📦 Download ZIP'), () => {
            const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
            window.open(url, '_blank');
        });
    }

    // 1. RECEPTION / DRAFT SUBMISSION TO ASSISTANT ADMIN MANAGER
    if (status === 'Draft' || status === 'Returned to Reception' || status === 'Returned by Admin L1') {
        frm.add_custom_button(__('📤 Submit to Asst. Admin Mgr'), function () {
            if (!lines || lines.length === 0) {
                frappe.msgprint(__('Please add at least one expense line before submitting.'));
                return;
            }
            if (!frm.doc.beneficiary_employee) {
                frappe.msgprint(__('Please select the Beneficiary Employee (Admin Head) receiving the payout.'));
                return;
            }
            frappe.confirm(__('Submit this Petty Cash Voucher to Assistant Admin Manager for review?'), function () {
                frappe.call({
                    method: 'ap_automation.services.admin_approval_service.submit_to_admin_l1',
                    args: { voucher_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Submitting to Assistant Admin Manager...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('✅ Submitted to Assistant Admin Manager!'), indicator: 'green' }, 5);
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

    // 2. ASSISTANT ADMIN MANAGER ACTIONS
    if (status === 'Pending Admin L1' && (frappe.user.has_role(['Assistant Admin Manager', 'Admin L1 Approver', 'Admin Manager', 'System Manager']) || frappe.session.user === 'Administrator')) {
        frm.add_custom_button(__('✅ Approve & Forward to Admin Mgr'), function () {
            frappe.confirm(__(`Approve voucher <b>#${frm.doc.name}</b> (₹${format_inr_clean(frm.doc.total_amount)}) and forward to Admin Manager?`), function () {
                frappe.call({
                    method: 'ap_automation.services.admin_approval_service.approve_admin_l1',
                    args: { voucher_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Approving as Assistant Admin Manager...'),
                    callback: function (r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: __('✅ Approved by Assistant Admin Manager!'), indicator: 'green' }, 5);
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
            frappe.prompt(
                [
                    {
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        label: __('Reason for Returning to Reception'),
                        reqd: 1
                    }
                ],
                function (values) {
                    frappe.call({
                        method: 'ap_automation.services.admin_approval_service.return_admin_l1',
                        args: {
                            voucher_name: frm.doc.name,
                            reason: values.reason
                        },
                        freeze: true,
                        freeze_message: __('Returning voucher to Reception...'),
                        callback: function (r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: __('↩️ Voucher Returned to Reception'), indicator: 'orange' }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                },
                __('Return Voucher to Reception'),
                __('Return Voucher')
            );
        }).addClass('btn-danger').css({
            'background-color': '#dc2626',
            'border-color': '#b91c1c',
            'color': '#ffffff'
        });
    }

    // 3. ADMIN MANAGER ACTIONS
    if (status === 'Pending Admin L2' && (frappe.user.has_role(['Admin Manager', 'Admin L2 Approver', 'Director Tier', 'System Manager']) || frappe.session.user === 'Administrator')) {
        frm.add_custom_button(__('✅ Approve & Forward to Accounts'), function () {
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
            frappe.prompt(
                [
                    {
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        label: __('Reason for Returning Voucher'),
                        reqd: 1
                    },
                    {
                        fieldname: 'return_to',
                        fieldtype: 'Select',
                        label: __('Return To'),
                        options: 'Reception\nAdmin L1',
                        default: 'Reception',
                        reqd: 1
                    }
                ],
                function (values) {
                    frappe.call({
                        method: 'ap_automation.services.admin_approval_service.return_admin_l2',
                        args: {
                            voucher_name: frm.doc.name,
                            reason: values.reason,
                            return_to: values.return_to
                        },
                        freeze: true,
                        freeze_message: __('Returning voucher...'),
                        callback: function (r) {
                            if (r.message && r.message.status === 'SUCCESS') {
                                frappe.show_alert({ message: __('↩️ Voucher Returned'), indicator: 'orange' }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                },
                __('Return Voucher'),
                __('Submit Return')
            );
        }).addClass('btn-danger').css({
            'background-color': '#dc2626',
            'border-color': '#b91c1c',
            'color': '#ffffff'
        });
    }

    // 4. ACCOUNTS AUDIT ACTIONS (Status == 'Submitted')
    if (status === 'Submitted' && (frappe.user.has_role(['Accounts L1 Auditor', 'Accounts User', 'Accounts Manager', 'System Manager']) || frappe.session.user === 'Administrator')) {
        frm.add_custom_button(__('✅ Audit & Pass to Director'), function () {
            frappe.confirm(__('Pass line-item audit and forward to Director (Anshul Sir) for final sanction?'), function () {
                frm.set_value('status', 'L1 Verified');
                frm.set_value('workflow_state', 'Audited & Verified by Accounts L1');
                frm.set_value('current_approval_level', 2);
                frm.save().then(() => {
                    frappe.show_alert({ message: __('✅ Passed to Director Tier (Anshul Sir)!'), indicator: 'green' }, 5);
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#16a34a',
            'border-color': '#15803d',
            'color': '#ffffff',
            'font-weight': '700'
        });

        if (lines.length > 1) {
            frm.add_custom_button(__('⚠️ Dispute Lines'), function () {
                open_dispute_split_dialog(frm);
            }).addClass('btn-secondary').css({
                'background-color': '#f59e0b',
                'border-color': '#d97706',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }
    }

    // 5. DIRECTOR TIER SANCTION (Status == 'L1 Verified')
    if (status === 'L1 Verified' && (frappe.user.has_role(['Director', 'Accounts L2 Approver', 'Director Tier', 'Dileep Director', 'System Manager']) || frappe.session.user === 'Administrator')) {
        frm.add_custom_button(__('✅ Sanction Payment'), function () {
            frappe.confirm(__(`Sanction payment of <b>₹${format_inr_clean(frm.doc.total_amount)}</b> for IDFC corporate batch release?`), function () {
                frm.set_value('status', 'Approved for Payment');
                frm.set_value('workflow_state', 'Approved for Thursday Payment Batch');
                frm.save().then(() => {
                    frappe.show_alert({ message: __('✅ Sanctioned for Payment Release!'), indicator: 'green' }, 5);
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#16a34a',
            'border-color': '#15803d',
            'color': '#ffffff',
            'font-weight': '700'
        });
    }
}

// --------------------------------------------------------------------------------------
// 5. 1-CLICK IN-GRID PHOTO UPLOADER
// --------------------------------------------------------------------------------------
function bind_custom_grid_uploaders(frm) {
    if (!frm.fields_dict['expense_lines'] || !frm.fields_dict['expense_lines'].grid) return;

    const grid = frm.fields_dict['expense_lines'].grid;
    const grid_rows = (grid.wrapper || $(grid.parent)).find('.grid-body .grid-row');

    grid_rows.each(function (idx) {
        const row_elem = $(this);
        const doc_row = (frm.doc.expense_lines || [])[idx];
        if (!doc_row) return;

        let action_cell = row_elem.find('.grid-static-col[data-fieldname="receipt_attachment"]');
        if (!action_cell.length) {
            action_cell = row_elem.find('.grid-static-col').last();
        }

        if (action_cell.length && !action_cell.find('.custom-photo-btn').length) {
            const has_file = Boolean(doc_row.receipt_attachment);
            const btn_label = has_file ? '🧾 Attached' : '📷 Add Photo';
            const btn_class = has_file ? 'btn-default has-photo' : 'btn-primary no-photo';

            const btn = $(`
                <button type="button" class="btn btn-xs ${btn_class} custom-photo-btn" style="margin-left: 4px; font-weight: 600; border-radius: 4px;">
                    ${btn_label}
                </button>
            `);

            btn.on('click', function (e) {
                e.stopPropagation();
                if (has_file) {
                    open_unified_receipt_gallery(frm, idx);
                } else {
                    new frappe.ui.FileUploader({
                        doctype: frm.doc.doctype,
                        docname: frm.doc.name,
                        allow_multiple: false,
                        on_success: (file_doc) => {
                            frappe.model.set_value(doc_row.doctype, doc_row.name, 'receipt_attachment', file_doc.file_url);
                            frm.dirty();
                            frm.save().then(() => {
                                frappe.show_alert({ message: __('Bill Receipt Uploaded!'), indicator: 'green' }, 3);
                            });
                        }
                    });
                }
            });

            action_cell.append(btn);
        }
    });
}

// --------------------------------------------------------------------------------------
// 6. 2-COLUMN SPLIT-PANE RECEIPT GALLERY
// --------------------------------------------------------------------------------------
function open_unified_receipt_gallery(frm, initial_index = 0) {
    if (window.APReceiptGallery && typeof window.APReceiptGallery.show === 'function') {
        window.APReceiptGallery.show(frm, { active_index: initial_index });
    } else if (window.APReceiptGallery && typeof window.APReceiptGallery.openModal === 'function') {
        const lines = frm.doc.expense_lines || [];
        const atts = lines.map((r, i) => ({
            idx: i,
            url: r.receipt_attachment || '',
            category: r.expense_category || 'Expense',
            merchant: r.merchant_name || 'Vendor',
            amount: r.amount || 0,
            date: r.expense_date || frm.doc.posting_date,
            bill_no: r.bill_number || ''
        })).filter(x => x.url);

        window.APReceiptGallery.openModal(frm, atts, initial_index);
    } else {
        open_fallback_receipt_modal(frm, initial_index);
    }
}

function open_fallback_receipt_modal(frm, initial_index = 0) {
    const lines = (frm.doc.expense_lines || []).filter(r => r.receipt_attachment);
    if (!lines.length) {
        frappe.msgprint(__('No receipts attached to this voucher.'));
        return;
    }

    let active_idx = initial_index < lines.length ? initial_index : 0;
    const d = new frappe.ui.Dialog({
        title: __(`🧾 Receipts Viewer - #${frm.doc.name}`),
        size: 'extra-large'
    });

    function render_modal_body() {
        const current = lines[active_idx];
        const is_pdf = current.receipt_attachment.toLowerCase().endsWith('.pdf');
        const media_preview = is_pdf
            ? `<iframe src="${current.receipt_attachment}" style="width: 100%; height: 500px; border: none; border-radius: 8px;"></iframe>`
            : `<img src="${current.receipt_attachment}" style="max-width: 100%; max-height: 500px; object-fit: contain; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);" />`;

        let list_items = '';
        lines.forEach((r, i) => {
            const is_sel = i === active_idx;
            list_items += `
                <div class="gallery-thumb-row ${is_sel ? 'selected-thumb' : ''}" data-idx="${i}" style="padding: 10px; margin-bottom: 6px; border-radius: 6px; cursor: pointer; border: 1.5px solid ${is_sel ? '#3b82f6' : '#e2e8f0'}; background: ${is_sel ? '#eff6ff' : '#ffffff'};">
                    <div style="font-weight: 700; font-size: 12px; color: ${is_sel ? '#1d4ed8' : '#1e293b'};">${r.expense_category || 'Expense'} - ₹${format_inr_clean(r.amount)}</div>
                    <div style="font-size: 11px; color: #64748b;">${r.merchant_name || 'Vendor'} | ${r.expense_date || ''}</div>
                </div>
            `;
        });

        d.$body.html(`
            <div style="display: flex; gap: 16px; height: 520px;">
                <div style="width: 280px; overflow-y: auto; border-right: 1px solid #e2e8f0; padding-right: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; margin-bottom: 8px;">Attached Receipts (${lines.length})</div>
                    ${list_items}
                </div>
                <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #0f172a; border-radius: 8px; padding: 12px;">
                    ${media_preview}
                    <div style="margin-top: 8px;">
                        <a href="${current.receipt_attachment}" target="_blank" class="btn btn-default btn-xs" style="color: #ffffff; background: rgba(255,255,255,0.15); border: none;">
                            ↗️ Open Full Screen
                        </a>
                    </div>
                </div>
            </div>
        `);

        d.$body.find('.gallery-thumb-row').on('click', function () {
            active_idx = parseInt($(this).attr('data-idx'));
            render_modal_body();
        });
    }

    render_modal_body();
    d.set_primary_action(__('Download ZIP'), () => {
        const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
        window.open(url, '_blank');
    });
    d.show();
}

// --------------------------------------------------------------------------------------
// 7. DISPUTE SPLIT DIALOG FOR ACCOUNTS
// --------------------------------------------------------------------------------------
function open_dispute_split_dialog(frm) {
    const lines = frm.doc.expense_lines || [];
    let fields = [
        {
            fieldtype: 'HTML',
            fieldname: 'dispute_info',
            options: `
                <div style="background: #fff1f2; border: 1px solid #fecdd3; border-radius: 6px; padding: 12px; margin-bottom: 14px; font-size: 13px; color: #881337;">
                    <b>⚠️ Dispute Line Items:</b> Select the rows with invalid or missing bills. Clean rows will remain in <b>#${frm.doc.name}</b> and move forward to Director L2, while disputed lines will be separated into a new linked child voucher for rectification.
                </div>
            `
        }
    ];

    lines.forEach((row, i) => {
        const row_label = `Row #${i + 1}: ${row.merchant_name || 'Item'} - ₹${format_inr_clean(row.amount)} (${row.expense_category || 'General'})`;
        fields.push({
            fieldtype: 'Check',
            fieldname: `dispute_row_${i}`,
            label: row_label,
            default: 0
        });
        fields.push({
            fieldtype: 'Small Text',
            fieldname: `reason_row_${i}`,
            label: `Dispute Reason for Row #${i + 1}`,
            depends_on: `eval:doc.dispute_row_${i} == 1`
        });
    });

    const d = new frappe.ui.Dialog({
        title: __('Dispute Specific Line Items'),
        fields: fields,
        primary_action_label: __('Execute Dispute Split'),
        primary_action: function () {
            const values = d.get_values();
            let disputed_indices = [];
            let dispute_reasons = {};

            lines.forEach((_, i) => {
                if (values[`dispute_row_${i}`]) {
                    disputed_indices.push(i);
                    dispute_reasons[i] = values[`reason_row_${i}`] || 'Missing valid receipt proof';
                }
            });

            if (disputed_indices.length === 0) {
                frappe.msgprint(__('Please select at least one row to dispute, or click Audit & Pass if all rows are valid.'));
                return;
            }

            d.hide();
            frappe.call({
                method: 'ap_automation.services.dispute_service.api_dispute_split',
                args: {
                    parent_docname: frm.doc.name,
                    disputed_indices: JSON.stringify(disputed_indices),
                    dispute_reasons: JSON.stringify(dispute_reasons)
                },
                freeze: true,
                freeze_message: __('Splitting disputed line items...'),
                callback: function (r) {
                    if (r.message && r.message.status === 'split_success') {
                        frappe.msgprint({
                            title: __('Dispute Split Completed'),
                            indicator: 'green',
                            message: `
                                <b>✅ ${r.message.approved_line_count} Clean Rows</b> (₹${format_inr_clean(r.message.approved_amount)}) retained.<br>
                                <b>⚠️ ${r.message.disputed_line_count} Disputed Rows</b> (₹${format_inr_clean(r.message.disputed_amount)}) forked into child voucher <b>${r.message.forked_voucher}</b>.
                            `
                        });
                        frm.reload_doc();
                    }
                }
            });
        }
    });

    d.show();
}

function format_inr_clean(val) {
    return parseFloat(val || 0).toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

// --------------------------------------------------------------------------------------
// 8. RESPONSIVE CSS & VISUAL DESIGN SYSTEM
// --------------------------------------------------------------------------------------
function apply_petty_cash_styles() {
    if (!document.getElementById('ap-petty-cash-unified-styles')) {
        const style = document.createElement('style');
        style.id = 'ap-petty-cash-unified-styles';
        style.innerHTML = `
            .ap-stepper-container {
                display: flex;
                align-items: center;
                gap: 8px;
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                padding: 12px 16px;
                margin-bottom: 14px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.04);
                overflow-x: auto;
            }
            .ap-step-card {
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 6px 10px;
                border-radius: 8px;
                border: 1.5px solid #e2e8f0;
                background: #f8fafc;
                min-width: 120px;
                flex: 1;
                transition: all 0.15s ease;
            }
            .ap-step-card.step-completed {
                background: #f0fdf4;
                border-color: #86efac;
            }
            .ap-step-card.step-completed .step-badge {
                background: #16a34a;
                color: #ffffff;
            }
            .ap-step-card.step-completed .step-title {
                color: #15803d;
            }
            .ap-step-card.step-active {
                background: #eff6ff;
                border-color: #93c5fd;
                box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
            }
            .ap-step-card.step-active .step-badge {
                background: #2563eb;
                color: #ffffff;
            }
            .ap-step-card.step-active .step-title {
                color: #1d4ed8;
            }
            .ap-step-card.step-error {
                background: #fef2f2;
                border-color: #fca5a5;
            }
            .ap-step-card.step-error .step-badge {
                background: #dc2626;
                color: #ffffff;
            }
            .ap-step-card.step-pending {
                opacity: 0.65;
            }
            .step-badge {
                width: 22px;
                height: 22px;
                border-radius: 50%;
                background: #cbd5e1;
                color: #475569;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 11px;
                font-weight: 700;
                flex-shrink: 0;
            }
            .step-title {
                font-size: 12px;
                font-weight: 700;
                color: #334155;
                line-height: 1.2;
            }
            .step-sub {
                font-size: 10.5px;
                color: #64748b;
                line-height: 1.2;
            }
            .ap-step-connector {
                width: 14px;
                height: 2px;
                background: #e2e8f0;
                flex-shrink: 0;
            }
            .ap-step-connector.line-completed {
                background: #86efac;
            }

            .ap-status-banner {
                display: flex;
                align-items: center;
                gap: 14px;
                padding: 12px 18px;
                border-radius: 9px;
                margin-bottom: 14px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }
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
