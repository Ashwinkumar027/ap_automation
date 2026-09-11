/**
 * AP Automation - Petty Cash Entry Master Controller
 * Enterprise Edition (Consolidated Single Source of Truth)
 * 
 * Features:
 * 1. 5-Step Visual Progress Stepper & Dynamic Guidance Banner
 * 2. Clean, Non-Duplicated Action Buttons with Smart Dropdowns
 * 3. Robust 1-Click In-Grid Photo & PDF Receipt Uploader
 * 4. Original Multi-Receipt Split-Pane Gallery (APReceiptGallery) & ZIP Downloader
 * 5. Partial Row Dispute Splitting (Disputed lines fork; approved lines move to L2)
 * 6. NPCI Verified Custodian Bank Summary Card
 */

frappe.ui.form.on('Petty Cash Entry', {
    setup: function (frm) {
        if (frm.is_new() && !frm.doc.custodian) {
            frm.set_value('custodian', frappe.session.user);
        }
        if (frm.is_new() && !frm.doc.posting_date) {
            frm.set_value('posting_date', frappe.datetime.get_today());
        }
    },

    onload: function (frm) {
        apply_petty_cash_styles();
    },

    onload_post_render: function (frm) {
        apply_petty_cash_styles();
        render_stepper_and_guidance(frm);
        format_smart_grid_cells(frm);
        setup_quick_row_uploader(frm);
    },

    refresh: function (frm) {
        apply_petty_cash_styles();
        recalculate_petty_cash_total(frm);
        render_stepper_and_guidance(frm);
        format_smart_grid_cells(frm);
        setup_quick_row_uploader(frm);
        setup_unified_workflow_buttons(frm);
    },

    validate: function (frm) {
        recalculate_petty_cash_total(frm);
    },

    company: function (frm) {
        render_stepper_and_guidance(frm);
    },

    status: function (frm) {
        render_stepper_and_guidance(frm);
        setup_unified_workflow_buttons(frm);
    }
});

frappe.ui.form.on('Petty Cash Line Item', {
    amount: function (frm) {
        recalculate_petty_cash_total(frm);
        format_smart_grid_cells(frm);
    },
    employee: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.employee) {
            frappe.db.get_value('Employee', row.employee, ['employee_name'])
                .then(r => {
                    if (r && r.message) {
                        frappe.model.set_value(cdt, cdn, 'staff_name', r.message.employee_name || '');
                        format_smart_grid_cells(frm);
                    }
                });
        } else {
            frappe.model.set_value(cdt, cdn, 'staff_name', '');
            format_smart_grid_cells(frm);
        }
    },
    attach_receipt: function (frm) {
        format_smart_grid_cells(frm);
    },
    receipt_attachment: function (frm) {
        format_smart_grid_cells(frm);
    },
    expense_lines_add: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.expense_date) {
            frappe.model.set_value(cdt, cdn, 'expense_date', frm.doc.posting_date || frappe.datetime.get_today());
        }
        format_smart_grid_cells(frm);
    },
    expense_lines_remove: function (frm) {
        recalculate_petty_cash_total(frm);
        format_smart_grid_cells(frm);
    }
});

// --------------------------------------------------------------------------------------
// 1. RE-CALCULATION & AUTO-SUMMATION
// --------------------------------------------------------------------------------------
function recalculate_petty_cash_total(frm) {
    let total = 0.0;
    (frm.doc.expense_lines || []).forEach(row => {
        total += flt(row.amount);
    });
    frm.set_value('total_amount', Math.round(total * 100) / 100);
}

function format_inr_clean(val) {
    return parseFloat(val || 0).toLocaleString('en-IN', {
        maximumFractionDigits: 2,
        minimumFractionDigits: 2
    });
}

// --------------------------------------------------------------------------------------
// 2. UNIFIED ACTION BUTTONS (NO DUPLICATES)
// --------------------------------------------------------------------------------------
function setup_unified_workflow_buttons(frm) {
    frm.clear_custom_buttons();

    if (frm.is_new()) return;

    const status = frm.doc.status || 'Draft';
    const lines = frm.doc.expense_lines || [];

    // Extract all attached receipts across all rows
    const attachments = window.APReceiptGallery ? window.APReceiptGallery.extractLocalAttachments(frm) : [];

    // --- RECEIPT UTILITY BUTTONS (Original 2-Column Gallery) ---
    if (attachments.length > 0) {
        frm.add_custom_button(__(`👁️ View Receipts (${attachments.length})`), () => {
            if (window.APReceiptGallery) {
                window.APReceiptGallery.openModal(frm, attachments, 0);
            }
        }).addClass('btn-secondary').css({
            'background': '#e0e7ff',
            'color': '#4338ca',
            'border-color': '#c7d2fe',
            'font-weight': '600'
        });

        frm.add_custom_button(__('📦 Download ZIP'), () => {
            window.location.href = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
        });
    }

    // --- WORKFLOW STATE BUTTONS ---
    if (status === 'Draft') {
        frm.add_custom_button(__('📤 Submit Envelope'), function () {
            if (lines.length === 0) {
                frappe.msgprint({
                    title: __('Cannot Submit Empty Envelope'),
                    indicator: 'red',
                    message: __('Please add at least one expense line item before submitting.')
                });
                return;
            }

            if (flt(frm.doc.total_amount) <= 0) {
                frappe.msgprint({
                    title: __('Invalid Total Amount'),
                    indicator: 'red',
                    message: __('Total amount must be greater than zero.')
                });
                return;
            }

            frappe.confirm(
                __(`Submit this Petty Cash Envelope (<b>${lines.length} lines</b> totaling <b>₹${format_inr_clean(frm.doc.total_amount)}</b>) for L1 Review?`),
                function () {
                    frm.set_value('status', 'Submitted');
                    frm.set_value('workflow_state', 'Pending L1 Review');
                    frm.set_value('current_approval_level', 1);
                    frm.save().then(() => {
                        frappe.show_alert({
                            message: __('🎉 Petty Cash Envelope submitted for L1 Review!'),
                            indicator: 'green'
                        }, 5);
                    });
                }
            );
        }).addClass('btn-primary').css({
            'background-color': '#16a34a',
            'border-color': '#15803d',
            'color': '#ffffff',
            'font-weight': '700',
            'box-shadow': '0 2px 4px rgba(22, 163, 74, 0.3)'
        });
    } else if (status === 'Submitted') {
        // 1. APPROVE CLAIM
        frm.add_custom_button(__('✅ Approve Claim'), function () {
            frappe.confirm(__('Approve this Petty Cash Claim and queue for payment disbursement?'), function () {
                frm.set_value('status', 'Approved for Payment');
                frm.set_value('workflow_state', 'Approved for Payment');
                frm.set_value('current_approval_level', 2);
                frm.save().then(() => {
                    frappe.show_alert({
                        message: __('✅ Claim Approved and Queued for Payment!'),
                        indicator: 'green'
                    }, 5);
                });
            });
        }).addClass('btn-primary').css({
            'background-color': '#16a34a',
            'border-color': '#15803d',
            'color': '#ffffff',
            'font-weight': '700'
        });

        // 2. DISPUTE LINES / SPLIT (if multiple lines exist)
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

        // 3. REJECT / SEND BACK
        frm.add_custom_button(__('❌ Reject / Return'), function () {
            frappe.prompt(
                [
                    {
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        label: __('Reason for Rejection / Return Notes'),
                        reqd: 1
                    }
                ],
                function (values) {
                    frm.set_value('status', 'Draft');
                    frm.set_value('workflow_state', 'Draft (Reopened)');
                    frm.save().then(() => {
                        frappe.show_alert({
                            message: __('Claim returned to Draft with notes: ' + values.reason),
                            indicator: 'orange'
                        }, 6);
                    });
                },
                __('Reject or Return to Admin'),
                __('Return to Draft')
            );
        }).addClass('btn-danger').css({
            'background-color': '#dc2626',
            'border-color': '#b91c1c',
            'color': '#ffffff',
            'font-weight': '700'
        });
    } else if (status === 'Rejected' || status === 'Disputed') {
        frm.add_custom_button(__('↩️ Reopen to Draft'), function () {
            frm.set_value('status', 'Draft');
            frm.set_value('workflow_state', 'Draft');
            frm.save().then(() => {
                frappe.show_alert({
                    message: __('Voucher reopened to Draft. You can now edit and resubmit.'),
                    indicator: 'blue'
                }, 5);
            });
        }).addClass('btn-secondary');
    }
}

// --------------------------------------------------------------------------------------
// 3. 5-STEP VISUAL STEPPER & GUIDANCE BANNER
// --------------------------------------------------------------------------------------
function render_stepper_and_guidance(frm) {
    if (!frm.fields_dict.guidance_banner_html || !frm.fields_dict.stepper_html) return;

    const status = frm.doc.status || 'Draft';
    const amount_str = `₹ ${format_inr_clean(frm.doc.total_amount)}`;

    let banner_html = '';
    let step_states = ['pending', 'pending', 'pending', 'pending', 'pending'];

    if (status === 'Draft') {
        step_states = ['active', 'pending', 'pending', 'pending', 'pending'];
        banner_html = `
            <div class="ap-status-banner banner-draft">
                <div class="banner-icon">📝</div>
                <div class="banner-content">
                    <div class="banner-title">Draft Mode — Add & Save Bills</div>
                    <div class="banner-sub">Add all your expense receipts in the table below. When ready, click <b>Submit Envelope</b> to send to the Accounts team for verification.</div>
                </div>
                <div class="banner-stat">
                    <div class="stat-label">Envelope Total</div>
                    <div class="stat-val">${amount_str}</div>
                </div>
            </div>
        `;
    } else if (status === 'Submitted') {
        step_states = ['completed', 'active', 'pending', 'pending', 'pending'];
        banner_html = `
            <div class="ap-status-banner banner-submitted">
                <div class="banner-icon">⏳</div>
                <div class="banner-content">
                    <div class="banner-title">Waiting for Accounts Team (L1) Check</div>
                    <div class="banner-sub">Your claim of <b>${amount_str}</b> is under verification by the Accounts team. Once verified, it will be queued for payment.</div>
                </div>
                <div class="banner-stat">
                    <div class="stat-label">Pending Liability</div>
                    <div class="stat-val" style="color: #2563eb;">${amount_str}</div>
                </div>
            </div>
        `;
    } else if (status === 'Approved for Payment') {
        step_states = ['completed', 'completed', 'completed', 'active', 'pending'];
        banner_html = `
            <div class="ap-status-banner banner-approved">
                <div class="banner-icon">✅</div>
                <div class="banner-content">
                    <div class="banner-title">Claim Approved — Queued for Bank Payout</div>
                    <div class="banner-sub">Claim verified and approved for <b>${amount_str}</b>. Payout will be dispatched in the next IDFC 2FA release batch.</div>
                </div>
                <div class="banner-stat">
                    <div class="stat-label">Approved Payout</div>
                    <div class="stat-val" style="color: #059669;">${amount_str}</div>
                </div>
            </div>
        `;
    } else if (status === 'Paid') {
        step_states = ['completed', 'completed', 'completed', 'completed', 'completed'];
        banner_html = `
            <div class="ap-status-banner banner-paid">
                <div class="banner-icon">💰</div>
                <div class="banner-content">
                    <div class="banner-title">Payment Successfully Released via IDFC Bank!</div>
                    <div class="banner-sub">Payout of <b>${amount_str}</b> was transferred directly to the custodian's bank account. Bank Reference: <b>${frm.doc.bank_reference || frm.doc.batch_id || 'Bank Confirmed'}</b>.</div>
                </div>
                <div class="banner-stat">
                    <div class="stat-label">Disbursed</div>
                    <div class="stat-val" style="color: #059669;">${amount_str}</div>
                </div>
            </div>
        `;
    } else if (status === 'Disputed' || status === 'Rejected') {
        step_states = ['completed', 'error', 'pending', 'pending', 'pending'];
        banner_html = `
            <div class="ap-status-banner banner-rejected">
                <div class="banner-icon">⚠️</div>
                <div class="banner-content">
                    <div class="banner-title">Line Items Disputed / Returned</div>
                    <div class="banner-sub">Accounts flagged discrepancies in this claim. Click <b>Reopen to Draft</b> to correct line items and re-submit.</div>
                </div>
                <div class="banner-stat">
                    <div class="stat-label">Disputed Amount</div>
                    <div class="stat-val" style="color: #dc2626;">${amount_str}</div>
                </div>
            </div>
        `;
    }

    frm.fields_dict.guidance_banner_html.$wrapper.html(banner_html);

    // 5-Step Stepper HTML
    const steps = [
        { num: 1, title: 'Bill Entry', sub: 'Admin Upload', icon: '📝' },
        { num: 2, title: 'Accounts Audit', sub: 'L1 Verification', icon: '🔍' },
        { num: 3, title: 'Director Approval', sub: 'Anshul Sir', icon: '✍️' },
        { num: 4, title: 'Bank Release', sub: 'IDFC 2FA (Anish Sir)', icon: '🏛️' },
        { num: 5, title: 'Money Received', sub: 'Bank Account', icon: '💰' }
    ];

    let stepper_html = '<div class="ap-stepper-container">';
    steps.forEach((step, idx) => {
        const state = step_states[idx];
        let state_class = `step-${state}`;
        let badge_content = state === 'completed' ? '✓' : step.num;

        stepper_html += `
            <div class="ap-step-card ${state_class}">
                <div class="step-badge">${badge_content}</div>
                <div class="step-info">
                    <div class="step-title">${step.title}</div>
                    <div class="step-sub">${step.sub}</div>
                </div>
            </div>
        `;
        if (idx < steps.length - 1) {
            const line_class = (step_states[idx] === 'completed' && (step_states[idx + 1] === 'completed' || step_states[idx + 1] === 'active')) ? 'line-completed' : '';
            stepper_html += `<div class="ap-step-connector ${line_class}"></div>`;
        }
    });
    stepper_html += '</div>';

    frm.fields_dict.stepper_html.$wrapper.html(stepper_html);
}

// --------------------------------------------------------------------------------------
// 4. SMART GRID FORMATTING (HEADER-PROTECTED & ANTI-DUPLICATION)
// --------------------------------------------------------------------------------------
function format_smart_grid_cells(frm) {
    if (!frm.page || !frm.page.wrapper) return;

    setTimeout(() => {
        const lines = frm.doc.expense_lines || [];
        
        frm.page.wrapper.find('.frappe-control[data-fieldname="expense_lines"] .grid-body .grid-row').each(function () {
            const $row_elem = $(this);
            
            if ($row_elem.hasClass('grid-heading-row') || $row_elem.closest('.grid-heading-row').length) {
                return;
            }

            const row_name = $row_elem.attr('data-name');
            let row = lines.find(r => r.name === row_name);

            if (!row) {
                const row_idx = $row_elem.attr('data-idx') ? parseInt($row_elem.attr('data-idx')) : 1;
                row = lines[row_idx - 1];
            }

            if (!row) return;

            const $cell = $row_elem.find('.grid-static-col[data-fieldname="receipt_attachment"]');
            if (!$cell.length) return;

            const file_url = row.receipt_attachment || row.attach_receipt || '';
            const current_rendered = $cell.attr('data-rendered-url');

            if (current_rendered === file_url && $cell.find('.ap-grid-receipt-thumb, .ap-grid-receipt-badge, .ap-upload-trigger').length > 0) {
                return;
            }

            $cell.attr('data-rendered-url', file_url);

            if (file_url && (file_url.startsWith('/files/') || file_url.startsWith('/private/files/') || file_url.startsWith('http'))) {
                const is_pdf = file_url.toLowerCase().endsWith('.pdf');
                if (is_pdf) {
                    $cell.html(`
                        <span class="ap-grid-receipt-badge" data-url="${file_url}" style="
                            display: inline-flex; align-items: center; gap: 4px;
                            background: #ede9fe; color: #5b21b6; border: 1px solid #ddd6fe;
                            padding: 2px 7px; border-radius: 5px; font-size: 11px; font-weight: 700; cursor: pointer;
                        ">📄 PDF Bill</span>
                    `);
                } else {
                    $cell.html(`
                        <div class="ap-grid-receipt-thumb" data-url="${file_url}" style="display: inline-flex; align-items: center; gap: 5px; cursor: pointer;" title="Click to view in receipt gallery">
                            <img src="${file_url}" style="width: 24px; height: 24px; object-fit: cover; border-radius: 4px; border: 1.5px solid #10b981; box-shadow: 0 1px 2px rgba(16, 185, 129, 0.2);" />
                            <span style="font-size: 11px; font-weight: 700; color: #047857;">🧾 Attached</span>
                        </div>
                    `);
                }
            } else {
                $cell.html(`
                    <span class="ap-upload-trigger" style="
                        display: inline-flex; align-items: center; gap: 4px;
                        background: #fdf2f8; color: #db2777; border: 1px dashed #fbcfe8;
                        padding: 2px 7px; border-radius: 5px; font-size: 11px; font-weight: 600; cursor: pointer;
                    ">📷 Add Photo</span>
                `);
            }
        });
    }, 60);
}

function setup_quick_row_uploader(frm) {
    if (!frm.page || !frm.page.wrapper) return;

    // 1-Click Upload Trigger
    frm.page.wrapper.off('click.ap_upload').on('click.ap_upload', '.ap-upload-trigger', function (e) {
        e.preventDefault();
        e.stopPropagation();

        const $row_elem = $(this).closest('.grid-row');
        if ($row_elem.hasClass('grid-heading-row')) return;

        const row_name = $row_elem.attr('data-name');
        let row = (frm.doc.expense_lines || []).find(r => r.name === row_name);

        if (!row) {
            const row_idx = $row_elem.attr('data-idx') ? parseInt($row_elem.attr('data-idx')) : 1;
            row = (frm.doc.expense_lines || [])[row_idx - 1];
        }

        if (!row) return;

        new frappe.ui.FileUploader({
            doctype: frm.doctype,
            docname: frm.is_new() ? undefined : frm.docname,
            folder: 'Home/Attachments',
            allow_multiple: false,
            make_attachments_public: 1,
            restrictions: {
                allowed_file_types: ['image/*', '.pdf', '.png', '.jpg', '.jpeg', '.webp']
            },
            on_success: (file_doc) => {
                frappe.model.set_value(row.doctype, row.name, 'receipt_attachment', file_doc.file_url);
                frm.refresh_field('expense_lines');
                frm.dirty();
                setTimeout(() => {
                    format_smart_grid_cells(frm);
                }, 80);
                frappe.show_alert({
                    message: __('🧾 Photo receipt attached successfully!'),
                    indicator: 'green'
                }, 4);
            }
        });
    });

    // In-Grid Thumbnail Lightbox Click -> Opens the Original 2-Column Split-Pane Gallery
    frm.page.wrapper.off('click.ap_thumb').on('click.ap_thumb', '.ap-grid-receipt-thumb, .ap-grid-receipt-badge', function (e) {
        e.preventDefault();
        e.stopPropagation();
        const clicked_url = $(this).attr('data-url');
        
        const attachments = window.APReceiptGallery ? window.APReceiptGallery.extractLocalAttachments(frm) : [];
        let start_idx = 0;

        if (attachments && attachments.length > 0) {
            attachments.forEach((att, idx) => {
                if (att.file_url === clicked_url) {
                    start_idx = idx;
                }
            });
            window.APReceiptGallery.openModal(frm, attachments, start_idx);
        }
    });
}

// --------------------------------------------------------------------------------------
// 6. DISPUTE FORKING & SPLIT DIALOG
// --------------------------------------------------------------------------------------
function open_dispute_split_dialog(frm) {
    const lines = frm.doc.expense_lines || [];
    if (lines.length < 2) {
        frappe.msgprint(__('Dispute split requires at least 2 line items in the claim.'));
        return;
    }

    let fields = [
        {
            fieldtype: 'HTML',
            fieldname: 'dispute_instructions',
            options: `
                <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 10px 14px; margin-bottom: 12px; font-size: 12.5px; color: #92400e;">
                    <b>Dispute Splitting Engine</b>: Select the line item(s) you wish to dispute.
                    Clean approved lines will automatically proceed to L2, while disputed lines will fork into a child ticket returned to the admin custodian.
                </div>
            `
        }
    ];

    lines.forEach((line, idx) => {
        fields.push({
            fieldtype: 'Check',
            fieldname: `dispute_row_${idx}`,
            label: `Row #${idx + 1}: ${line.expense_category || 'Expense'} - ${line.description || line.merchant_name || 'Item'} (₹${format_inr_clean(line.amount)})`
        });
        fields.push({
            fieldtype: 'Data',
            fieldname: `reason_row_${idx}`,
            label: `Reason for Row #${idx + 1} Dispute`,
            depends_on: `eval:doc.dispute_row_${idx}==1`
        });
    });

    const d = new frappe.ui.Dialog({
        title: __('Dispute & Split Line Items'),
        fields: fields,
        primary_action_label: __('Split & Move Approved to L2'),
        primary_action: function (values) {
            let disputed_indices = [];
            let dispute_reasons = {};

            lines.forEach((line, idx) => {
                if (values[`dispute_row_${idx}`]) {
                    disputed_indices.push(idx);
                    dispute_reasons[idx] = values[`reason_row_${idx}`] || 'Disputed during L1 audit';
                }
            });

            if (disputed_indices.length === 0) {
                frappe.msgprint(__('Please select at least one row to dispute, or click Approve Claim if all rows are valid.'));
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
                                <b>✅ ${r.message.approved_line_count} Approved Rows</b> (₹${format_inr_clean(r.message.approved_amount)}) moved to L2.<br>
                                <b>⚠️ ${r.message.disputed_line_count} Disputed Rows</b> (₹${format_inr_clean(r.message.disputed_amount)}) forked into linked voucher <b>${r.message.forked_voucher}</b>.
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

// --------------------------------------------------------------------------------------
// 7. RESPONSIVE CSS & VISUAL DESIGN SYSTEM
// --------------------------------------------------------------------------------------
function apply_petty_cash_styles() {
    if (!document.getElementById('ap-petty-cash-unified-styles')) {
        const style = document.createElement('style');
        style.id = 'ap-petty-cash-unified-styles';
        style.innerHTML = `
            /* Stepper Container */
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
                gap: 10px;
                padding: 8px 12px;
                border-radius: 8px;
                border: 1.5px solid #e2e8f0;
                background: #f8fafc;
                min-width: 140px;
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
                width: 24px;
                height: 24px;
                border-radius: 50%;
                background: #cbd5e1;
                color: #475569;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 11.5px;
                font-weight: 700;
                flex-shrink: 0;
            }
            .step-title {
                font-size: 12.5px;
                font-weight: 700;
                color: #334155;
                line-height: 1.2;
            }
            .step-sub {
                font-size: 11px;
                color: #64748b;
                line-height: 1.2;
            }
            .ap-step-connector {
                width: 18px;
                height: 2px;
                background: #e2e8f0;
                flex-shrink: 0;
            }
            .ap-step-connector.line-completed {
                background: #86efac;
            }

            /* Guidance Banners */
            .ap-status-banner {
                display: flex;
                align-items: center;
                gap: 14px;
                padding: 12px 18px;
                border-radius: 9px;
                margin-bottom: 14px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }
            .banner-icon {
                font-size: 24px;
                flex-shrink: 0;
            }
            .banner-content {
                flex: 1;
            }
            .banner-title {
                font-size: 13.5px;
                font-weight: 700;
                margin-bottom: 2px;
            }
            .banner-sub {
                font-size: 12px;
                opacity: 0.9;
            }
            .banner-stat {
                text-align: right;
                flex-shrink: 0;
            }
            .stat-label {
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                font-weight: 600;
                opacity: 0.75;
            }
            .stat-val {
                font-size: 17px;
                font-weight: 800;
                font-family: inherit;
            }
            .banner-draft { background: #f8fafc; border: 1.5px solid #e2e8f0; color: #334155; }
            .banner-submitted { background: #eff6ff; border: 1.5px solid #bfdbfe; color: #1e40af; }
            .banner-approved { background: #f0fdf4; border: 1.5px solid #bbf7d0; color: #166534; }
            .banner-paid { background: #f0fdf4; border: 1.5px solid #86efac; color: #14532d; }
            .banner-rejected { background: #fef2f2; border: 1.5px solid #fecaca; color: #991b1b; }

            /* Seamless Table Styling */
            .frappe-control[data-fieldname="expense_lines"] .form-grid {
                border: 1px solid #e2e8f0 !important;
                border-radius: 8px !important;
                background: #ffffff !important;
                overflow: hidden !important;
            }
            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-heading-row {
                background: #f8fafc !important;
                border-bottom: 1.5px solid #e2e8f0 !important;
            }
            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-heading-row .grid-static-col {
                font-weight: 700 !important;
                font-size: 12px !important;
                color: #475569 !important;
                text-transform: uppercase !important;
            }
            .frappe-control[data-fieldname="expense_lines"] .form-grid [data-fieldname="amount"] {
                font-weight: 700 !important;
                color: #059669 !important;
            }
            .frappe-control[data-fieldname="expense_lines"] .grid-body .grid-static-col[data-fieldname="receipt_attachment"] {
                display: flex !important;
                align-items: center !important;
                min-height: 28px !important;
                padding: 2px 4px !important;
            }
        `;
        document.head.appendChild(style);
    }
}
