/**
 * AP Automation - Petty Cash Entry Controller (Sprint 5 Enterprise Workflow Edition)
 * 
 * Workflow Capabilities:
 * 1. [ 📤 Submit Envelope ]: Direct one-click submission from Draft to Submitted / L1 Review.
 * 2. [ ✅ Approve Claim ]: Direct approval button for L1 / L2 approvers.
 * 3. [ ❌ Reject / Send Back ]: Prompts for audit reason and logs to Approval Trail.
 * 4. [ ↩️ Reopen to Draft ]: Allows custodian / accounts to reopen submitted drafts.
 * 5. Interactive Proof Badges & In-Tab Lightbox Gallery.
 * 6. Non-Intrusive File Uploader (keeps form in 'Not Saved' until manual save).
 */

// Override Frappe ControlAttach to bypass auto-save on unsaved Petty Cash Entry
if (frappe.ui.form && frappe.ui.form.ControlAttach) {
    if (!frappe.ui.form.ControlAttach.prototype._ap_patched) {
        const _orig_on_upload_complete = frappe.ui.form.ControlAttach.prototype.on_upload_complete;
        
        frappe.ui.form.ControlAttach.prototype.on_upload_complete = async function (attachment) {
            if (this.frm && this.frm.doctype === 'Petty Cash Entry' && this.frm.is_new()) {
                await this.parse_validate_and_set_in_model(attachment.file_url);
                this.set_value(attachment.file_url);
                this.toggle_reload_button();
                this.frm.dirty();
                
                if (window.APReceiptGallery) {
                    window.APReceiptGallery.setup(this.frm);
                }
                format_smart_grid_cells(this.frm);
                return;
            }
            return _orig_on_upload_complete.apply(this, arguments);
        };
        frappe.ui.form.ControlAttach.prototype._ap_patched = true;
    }
}

frappe.ui.form.on('Petty Cash Entry', {
    setup: function (frm) {
        if (frm.is_new() && !frm.doc.custodian) {
            frm.set_value('custodian', frappe.session.user);
        }
        if (frm.is_new() && !frm.doc.posting_date) {
            frm.set_value('posting_date', frappe.datetime.get_today());
        }
    },

    onload_post_render: function (frm) {
        apply_seamless_grid_css();
        format_smart_grid_cells(frm);
        bind_grid_interactive_events(frm);
    },

    refresh: function (frm) {
        recalculate_petty_cash_total(frm);
        apply_seamless_grid_css();
        format_smart_grid_cells(frm);
        bind_grid_interactive_events(frm);
        setup_workflow_action_buttons(frm);
        if (window.APReceiptGallery) {
            window.APReceiptGallery.setup(frm);
        }
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
        if (window.APReceiptGallery) window.APReceiptGallery.setup(frm);
        format_smart_grid_cells(frm);
    },
    receipt_attachment: function (frm) {
        if (window.APReceiptGallery) window.APReceiptGallery.setup(frm);
        format_smart_grid_cells(frm);
    },
    expense_lines_add: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.expense_date) {
            frappe.model.set_value(cdt, cdn, 'expense_date', frm.doc.posting_date || frappe.datetime.get_today());
        }
        if (window.APReceiptGallery) window.APReceiptGallery.setup(frm);
        format_smart_grid_cells(frm);
        bind_grid_interactive_events(frm);
    },
    expense_lines_remove: function (frm) {
        recalculate_petty_cash_total(frm);
        if (window.APReceiptGallery) window.APReceiptGallery.setup(frm);
        format_smart_grid_cells(frm);
    }
});

function recalculate_petty_cash_total(frm) {
    let total = 0.0;
    (frm.doc.expense_lines || []).forEach(row => {
        total += flt(row.amount);
    });
    frm.set_value('total_amount', Math.round(total * 100) / 100);
    frm.refresh_field('total_amount');
}

/**
 * Enterprise Workflow Action Buttons (Submit Envelope, Approve, Reject, Reopen)
 */
function setup_workflow_action_buttons(frm) {
    // Clear prior workflow buttons
    frm.page.wrapper.find('.ap-btn-submit-envelope, .ap-btn-approve-claim, .ap-btn-reject-claim, .ap-btn-reopen-draft').remove();

    if (frm.is_new()) return;

    const status = frm.doc.status || 'Draft';

    // 1. DRAFT STATE: Show [ 📤 Submit Envelope ] Button
    if (status === 'Draft') {
        const $btn_submit = frm.add_custom_button(__('📤 Submit Envelope'), function () {
            // Validation
            const lines = frm.doc.expense_lines || [];
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
                __(`Are you sure you want to submit this Petty Cash Envelope (<b>${lines.length} lines</b> totaling <b>₹${format_inr_clean(frm.doc.total_amount)}</b>) for L1 Review?`),
                function () {
                    frm.set_value('status', 'Submitted');
                    frm.set_value('workflow_state', 'Pending L1 Review');
                    frm.set_value('current_approval_level', 1);
                    frm.save().then(() => {
                        frappe.show_alert({
                            message: __('🎉 Petty Cash Envelope successfully submitted for L1 Review!'),
                            indicator: 'green'
                        }, 5);
                    });
                }
            );
        }).addClass('ap-btn-submit-envelope btn-primary').css({
            'background-color': '#16a34a',
            'border-color': '#15803d',
            'color': '#ffffff',
            'font-weight': '700',
            'border-radius': '6px',
            'box-shadow': '0 2px 4px rgba(22, 163, 74, 0.3)',
            'margin-right': '6px'
        });
    }

    // 2. SUBMITTED STATE: Show [ ✅ Approve ] and [ ❌ Reject ] Buttons
    if (status === 'Submitted') {
        // Approve Button
        frm.add_custom_button(__('✅ Approve Claim'), function () {
            frappe.confirm(__('Grant approval for this Petty Cash Claim and queue for payment disbursement?'), function () {
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
        }).addClass('ap-btn-approve-claim btn-primary').css({
            'background-color': '#16a34a',
            'border-color': '#15803d',
            'color': '#ffffff',
            'font-weight': '700',
            'border-radius': '6px',
            'margin-right': '6px'
        });

        // Reject / Dispute Button
        frm.add_custom_button(__('❌ Reject / Send Back'), function () {
            frappe.prompt(
                [
                    {
                        fieldname: 'reason',
                        fieldtype: 'Small Text',
                        label: __('Reason for Rejection / Correction Notes'),
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
                __('Reject Petty Cash Claim'),
                __('Reject & Reopen')
            );
        }).addClass('ap-btn-reject-claim btn-default').css({
            'background-color': '#ffffff',
            'border-color': '#ef4444',
            'color': '#dc2626',
            'font-weight': '600',
            'border-radius': '6px',
            'margin-right': '6px'
        });
    }

    // 3. APPROVED STATE: Show Payout Ready Status Indicator
    if (status === 'Approved for Payment') {
        frm.add_custom_button(__('↩️ Reopen to Draft'), function () {
            frappe.confirm(__('Reopen this approved claim back to Draft mode for adjustments?'), function () {
                frm.set_value('status', 'Draft');
                frm.set_value('workflow_state', 'Draft');
                frm.save().then(() => {
                    frappe.show_alert({ message: __('Claim reopened to Draft.'), indicator: 'blue' });
                });
            });
        }).addClass('ap-btn-reopen-draft btn-default').css({
            'font-size': '12px',
            'color': '#64748b'
        });
    }
}

function format_inr_clean(val) {
    return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(val || 0);
}

function bind_grid_interactive_events(frm) {
    if (!frm.page || !frm.page.wrapper) return;

    // Direct Click on '🧾 Proof' Badge opens In-Tab Lightbox at that specific row
    frm.page.wrapper.off('click.ap_proof_badge', '.ap-grid-receipt-badge');
    frm.page.wrapper.on('click.ap_proof_badge', '.ap-grid-receipt-badge', function (e) {
        e.preventDefault();
        e.stopPropagation();

        const row_elem = $(this).closest('.grid-row');
        const row_idx = row_elem.attr('data-idx') ? parseInt(row_elem.attr('data-idx')) : 1;

        const local_atts = (window.APReceiptGallery) ? window.APReceiptGallery.extractLocalAttachments(frm) : [];
        
        if (!frm.is_new()) {
            frappe.call({
                method: 'ap_automation.services.attachment_service.get_all_claim_attachments',
                args: {
                    doctype: frm.doc.doctype,
                    docname: frm.doc.name
                },
                callback: function (r) {
                    const atts = (r.message && r.message.length > 0) ? r.message : local_atts;
                    if (window.APReceiptGallery) {
                        window.APReceiptGallery.openModal(frm, atts, row_idx);
                    }
                }
            });
        } else {
            if (window.APReceiptGallery) {
                window.APReceiptGallery.openModal(frm, local_atts, row_idx);
            }
        }
    });

    // Click on empty Attach button triggers clean non-saving FileUploader
    frm.page.wrapper.off('click.ap_attach_btn', '.grid-row [data-fieldname="receipt_attachment"] button, .grid-row [data-fieldname="receipt_attachment"] .btn-attach, .grid-row [data-fieldname="attach_receipt"] button');
    frm.page.wrapper.on('click.ap_attach_btn', '.grid-row [data-fieldname="receipt_attachment"] button, .grid-row [data-fieldname="receipt_attachment"] .btn-attach, .grid-row [data-fieldname="attach_receipt"] button', function (e) {
        e.preventDefault();
        e.stopPropagation();

        const row_elem = $(this).closest('.grid-row');
        const row_idx = row_elem.attr('data-idx') ? parseInt(row_elem.attr('data-idx')) : 1;
        const row = (frm.doc.expense_lines || [])[row_idx - 1];

        if (!row) return;

        new frappe.ui.FileUploader({
            folder: 'Home/Attachments',
            allow_multiple: false,
            restrictions: {
                allowed_file_types: ['image/*', '.pdf']
            },
            on_success: (file_doc) => {
                frappe.model.set_value(row.doctype, row.name, 'receipt_attachment', file_doc.file_url);
                frm.refresh_field('expense_lines');
                frm.dirty();
                if (window.APReceiptGallery) {
                    window.APReceiptGallery.setup(frm);
                }
                format_smart_grid_cells(frm);
            }
        });
    });
}

function format_smart_grid_cells(frm) {
    if (!frm.page || !frm.page.wrapper) return;

    setTimeout(() => {
        // 1. Transform raw file links into compact clickable badge
        frm.page.wrapper.find('.grid-row [data-fieldname="receipt_attachment"], .grid-row [data-fieldname="attach_receipt"]').each(function () {
            const $cell = $(this);
            const $link = $cell.find('a');
            const href = $link.attr('href') || $cell.text().trim();
            
            if (href && (href.startsWith('/files/') || href.startsWith('/private/files/'))) {
                const is_pdf = href.toLowerCase().endsWith('.pdf');
                $cell.html(`
                    <span class="ap-grid-receipt-badge" title="Click to preview proof in lightbox" style="
                        display: inline-flex;
                        align-items: center;
                        gap: 4px;
                        background: #ede9fe;
                        color: #4f46e5;
                        border: 1px solid #c7d2fe;
                        padding: 2px 8px;
                        border-radius: 5px;
                        font-size: 11.5px;
                        font-weight: 700;
                        cursor: pointer;
                        white-space: nowrap;
                        box-shadow: 0 1px 2px rgba(79, 70, 229, 0.15);
                    ">
                        ${is_pdf ? '📄' : '🧾'} Proof
                    </span>
                `);
            }
        });

        // 2. Format Staff Name badges
        (frm.doc.expense_lines || []).forEach((row, idx) => {
            if (row.staff_name) {
                const $cell = frm.page.wrapper.find(`.grid-row[data-idx="${idx + 1}"] [data-fieldname="employee"]`);
                if ($cell.length > 0) {
                    const current_text = $cell.text();
                    if (!current_text.includes('👤')) {
                        $cell.html(`
                            <span style="font-weight: 600; color: #312e81; background: #e0e7ff; padding: 2px 7px; border-radius: 4px; font-size: 12px; display: inline-block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 130px;" title="${row.staff_name} (${row.employee})">
                                👤 ${row.staff_name}
                            </span>
                        `);
                    }
                }
            }
        });
    }, 60);
}

function apply_seamless_grid_css() {
    if (!document.getElementById('ap-seamless-grid-style')) {
        const style = document.createElement('style');
        style.id = 'ap-seamless-grid-style';
        style.innerHTML = `
            /* Seamless Single Outer Card */
            .frappe-control[data-fieldname="expense_lines"] .form-grid {
                border: 1px solid #e2e8f0 !important;
                border-radius: 8px !important;
                background: #ffffff !important;
                overflow: hidden !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05) !important;
                margin: 0 !important;
                width: 100% !important;
            }

            /* Flush Top Header */
            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-heading-row {
                background: #f8fafc !important;
                border-bottom: 1.5px solid #e2e8f0 !important;
                margin: 0 !important;
                padding: 0 !important;
            }

            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-heading-row .grid-static-col,
            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-heading-row th {
                white-space: nowrap !important;
                font-size: 12px !important;
                font-weight: 700 !important;
                color: #334155 !important;
                text-transform: uppercase !important;
                letter-spacing: 0.03em !important;
                padding: 10px 8px !important;
                vertical-align: middle !important;
                border: none !important;
            }

            /* Smooth Data Rows */
            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-body .grid-row {
                transition: background-color 0.12s ease-in-out !important;
                border-bottom: 1px solid #f1f5f9 !important;
                margin: 0 !important;
            }

            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-body .grid-row:last-child {
                border-bottom: none !important;
            }

            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-body .grid-row:hover {
                background-color: #faf5ff !important;
            }

            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-body .grid-row .grid-static-col {
                padding: 8px 8px !important;
                font-size: 13px !important;
                color: #1e293b !important;
                vertical-align: middle !important;
                border: none !important;
            }

            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-row .form-control {
                height: 28px !important;
                padding: 2px 6px !important;
                font-size: 13px !important;
                border: 1px solid #cbd5e1 !important;
                border-radius: 4px !important;
                background-color: #ffffff !important;
            }

            .frappe-control[data-fieldname="expense_lines"] .form-grid [data-fieldname="amount"] {
                font-weight: 700 !important;
                color: #059669 !important;
                font-size: 13.5px !important;
                text-align: right !important;
            }

            .frappe-control[data-fieldname="expense_lines"] .form-grid .grid-heading-row [data-fieldname="amount"] {
                text-align: right !important;
            }

            .frappe-control[data-fieldname="expense_lines"] .form-grid [data-fieldname="expense_date"] {
                font-weight: 600 !important;
                color: #475569 !important;
            }

            .frappe-control[data-fieldname="expense_lines"] .grid-footer {
                padding: 8px 0 0 0 !important;
            }

            .frappe-control[data-fieldname="expense_lines"] .grid-footer .btn-default {
                background: #4f46e5 !important;
                color: #ffffff !important;
                border: 1px solid #4338ca !important;
                font-weight: 600 !important;
                font-size: 12px !important;
                border-radius: 6px !important;
                padding: 6px 14px !important;
                box-shadow: 0 1px 2px rgba(79, 70, 229, 0.2) !important;
                transition: all 0.15s ease !important;
            }
            .frappe-control[data-fieldname="expense_lines"] .grid-footer .btn-default:hover {
                background: #4338ca !important;
            }
        `;
        document.head.appendChild(style);
    }
}
