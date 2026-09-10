/**
 * AP Automation - Universal Receipt & Audit Gallery Manager
 * Provides bank-grade In-Tab Modal Lightbox, Date Badges, and ZIP Packaging
 * Active for ALL records (Existing, New, and Upcoming) across all AP Claim DocTypes.
 */

window.APReceiptGallery = {
    formatINR: function (val) {
        return new Intl.NumberFormat('en-IN', {
            style: 'currency',
            currency: 'INR',
            maximumFractionDigits: 2
        }).format(val || 0);
    },

    formatDate: function (d_str) {
        if (!d_str) return '';
        try {
            const parts = String(d_str).trim().split('-');
            if (parts.length === 3 && parts[0].length === 4) {
                return parts[2] + '-' + parts[1] + '-' + parts[0];
            }
            return String(d_str);
        } catch (e) {
            return String(d_str);
        }
    },

    extractLocalAttachments: function (frm) {
        const atts = [];
        const child_tables = ['expense_lines', 'lines', 'items', 'instructions'];
        
        child_tables.forEach(table_field => {
            const rows = frm.doc[table_field] || [];
            rows.forEach((row, idx) => {
                const file_url = row.attach_receipt || row.receipt_attachment || row.attachment || row.tax_invoice_attachment || row.bill_attachment;
                if (file_url && typeof file_url === 'string' && file_url.trim()) {
                    const clean_url = file_url.trim();
                    const file_name = clean_url.split('/').pop();
                    const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
                    const is_img = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext);
                    const is_pdf = ext === '.pdf';
                    
                    atts.push({
                        source: 'row',
                        row_idx: row.idx || (idx + 1),
                        merchant: row.merchant_name || row.merchant || row.vendor_name || 'Vendor / Merchant',
                        category: row.expense_category || row.category || row.expense_type || 'General Expense',
                        amount: parseFloat(row.amount || row.claim_amount || 0.0),
                        date: row.expense_date || row.date || frm.doc.posting_date || frm.doc.invoice_date || '',
                        bill_no: row.bill_number || row.bill_no || row.invoice_number || '',
                        file_url: clean_url,
                        file_name: file_name,
                        is_image: is_img,
                        is_pdf: is_pdf,
                        extension: ext
                    });
                }
            });
        });

        // Parent direct attachments
        const parent_fields = [
            { field: 'tax_invoice_attachment', label: 'Vendor Tax Invoice', cat: 'Vendor Commercial Invoice' },
            { field: 'email_approval_attachment', label: 'Manager Email Approval', cat: 'Audit Approval Proof' },
            { field: 'grn_attachment', label: 'Goods Receipt Note / Delivery Proof', cat: 'Warehouse Receipt' },
            { field: 'advance_receipt_attachment', label: 'Advance Payment Proof', cat: 'Bank Advance Proof' },
            { field: 'settlement_statement', label: 'Event Settlement Statement', cat: 'Event Settlement' }
        ];

        parent_fields.forEach(pf => {
            const file_url = frm.doc[pf.field];
            if (file_url && typeof file_url === 'string' && file_url.trim()) {
                const clean_url = file_url.trim();
                const file_name = clean_url.split('/').pop();
                const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
                atts.push({
                    source: 'parent',
                    row_idx: null,
                    merchant: pf.label,
                    category: pf.cat,
                    amount: parseFloat(frm.doc.total_amount || frm.doc.total_invoice_amount || frm.doc.total_claim_amount || 0.0),
                    date: frm.doc.posting_date || frm.doc.invoice_date || '',
                    bill_no: frm.doc.invoice_number || frm.doc.name || '',
                    file_url: clean_url,
                    file_name: file_name,
                    is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext),
                    is_pdf: ext === '.pdf',
                    extension: ext
                });
            }
        });

        return atts;
    },

    setup: function (frm) {
        // Remove prior custom buttons to avoid stacking duplicates
        frm.page.remove_inner_button(__('View All Receipts'), 'Actions');
        frm.page.remove_inner_button(__('Download All Receipts (.ZIP)'), 'Actions');
        frm.page.wrapper.find('.ap-receipt-gallery-btn, .ap-receipt-zip-btn').remove();

        // 1. Compute initial count from local memory (immediate render for new & existing docs)
        const local_atts = this.extractLocalAttachments(frm);
        let current_count = local_atts.length;

        const update_button_ui = (count, attachments) => {
            frm.page.wrapper.find('.ap-receipt-gallery-btn, .ap-receipt-zip-btn').remove();

            // Button 1: 👁️ View All Receipts (N)
            const $btn_view = frm.add_custom_button(__(`👁️ View All Receipts (${count})`), () => {
                if (attachments && attachments.length > 0) {
                    window.APReceiptGallery.openModal(frm, attachments, 0);
                } else {
                    window.APReceiptGallery.openEmptyModal(frm);
                }
            }).addClass('ap-receipt-gallery-btn btn-primary').css({
                'background-color': '#4f46e5',
                'border-color': '#4338ca',
                'color': '#ffffff',
                'font-weight': '600',
                'border-radius': '6px',
                'box-shadow': '0 2px 4px rgba(79, 70, 229, 0.25)'
            });

            // Button 2: 📦 Download All Receipts (.ZIP)
            const $btn_zip = frm.add_custom_button(__('📦 Download All Receipts (.ZIP)'), () => {
                if (!attachments || attachments.length === 0) {
                    frappe.msgprint({
                        title: __('No Receipts Found'),
                        indicator: 'orange',
                        message: __('Please attach at least one receipt to this document before downloading the ZIP package.')
                    });
                    return;
                }
                const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
                window.open(url, '_blank');
            }).addClass('ap-receipt-zip-btn btn-default').css({
                'background-color': '#ffffff',
                'border-color': '#cbd5e1',
                'color': '#334155',
                'font-weight': '600',
                'border-radius': '6px',
                'margin-left': '6px'
            });
        };

        // Render initial state immediately
        update_button_ui(current_count, local_atts);

        // 2. If saved document, query backend service for full sync (including tabFile attachments)
        if (!frm.is_new()) {
            frappe.call({
                method: 'ap_automation.services.attachment_service.get_all_claim_attachments',
                args: {
                    doctype: frm.doc.doctype,
                    docname: frm.doc.name
                },
                callback: (r) => {
                    const server_atts = r.message || [];
                    const final_atts = server_atts.length > 0 ? server_atts : local_atts;
                    update_button_ui(final_atts.length, final_atts);
                }
            });
        }

        // 3. Bind Grid Attachment Link Clicks to Open In-Tab Modal
        frm.page.wrapper.off('click', '.grid-row [data-fieldname="attach_receipt"] a, .grid-row [data-fieldname="receipt_attachment"] a, .grid-row [data-fieldname="tax_invoice_attachment"] a');
        frm.page.wrapper.on('click', '.grid-row [data-fieldname="attach_receipt"] a, .grid-row [data-fieldname="receipt_attachment"] a, .grid-row [data-fieldname="tax_invoice_attachment"] a', function (e) {
            e.preventDefault();
            e.stopPropagation();
            const row_elem = $(this).closest('.grid-row');
            const row_idx = row_elem.attr('data-idx') ? parseInt(row_elem.attr('data-idx')) : 1;
            
            // Re-fetch and open
            const live_atts = window.APReceiptGallery.extractLocalAttachments(frm);
            if (!frm.is_new()) {
                frappe.call({
                    method: 'ap_automation.services.attachment_service.get_all_claim_attachments',
                    args: { doctype: frm.doc.doctype, docname: frm.doc.name },
                    callback: (r) => {
                        const atts = (r.message && r.message.length > 0) ? r.message : live_atts;
                        window.APReceiptGallery.openModal(frm, atts, row_idx);
                    }
                });
            } else {
                window.APReceiptGallery.openModal(frm, live_atts, row_idx);
            }
        });
    },

    openEmptyModal: function (frm) {
        const d = new frappe.ui.Dialog({
            title: `🧾 <b>Receipt Proofs & Audit Gallery</b> — <span style="color: #4f46e5;">${frm.doc.name || 'New Claim'}</span>`,
            size: 'large',
            fields: [
                {
                    fieldname: 'empty_html',
                    fieldtype: 'HTML',
                    options: `
                        <div style="text-align: center; padding: 48px 24px; background: #f8fafc; border-radius: 10px; border: 2px dashed #cbd5e1; margin: 10px 0;">
                            <div style="font-size: 56px; margin-bottom: 16px;">🧾</div>
                            <h4 style="font-size: 18px; font-weight: 700; color: #1e293b; margin-bottom: 8px;">No Receipts Attached Yet</h4>
                            <p style="font-size: 13px; color: #64748b; max-width: 480px; margin: 0 auto 20px auto; line-height: 1.5;">
                                Attach receipt images (PNG, JPG, WEBP) or PDFs to any expense line item in the table below, then click <b>Save</b> to view them here in the audit lightbox.
                            </p>
                            <div style="display: inline-flex; align-items: center; gap: 8px; background: #e0e7ff; color: #3730a3; padding: 8px 16px; border-radius: 6px; font-size: 12px; font-weight: 600;">
                                💡 Tip: You can click directly on any attachment link inside the grid to preview it instantly!
                            </div>
                        </div>
                    `
                }
            ],
            primary_action_label: __('Close'),
            primary_action: () => d.hide()
        });
        d.show();
    },

    openModal: function (frm, attachments, preferred_row_idx = null) {
        if (!attachments || attachments.length === 0) {
            this.openEmptyModal(frm);
            return;
        }

        let current_index = 0;
        if (preferred_row_idx) {
            const found_idx = attachments.findIndex(a => a.row_idx === preferred_row_idx);
            if (found_idx !== -1) current_index = found_idx;
        }

        const d = new frappe.ui.Dialog({
            title: `🧾 <b>Receipt Proofs & Audit Gallery</b> — <span style="color: #4f46e5;">${frm.doc.name || 'Claim Document'}</span>`,
            size: 'extra-large',
            fields: [
                {
                    fieldname: 'gallery_html_area',
                    fieldtype: 'HTML'
                }
            ]
        });

        const update_view = () => {
            const active_att = attachments[current_index];
            const active_date_formatted = window.APReceiptGallery.formatDate(active_att.date);

            let preview_content = '';
            if (active_att.is_image) {
                preview_content = `
                    <div style="display: flex; justify-content: center; align-items: center; min-height: 480px; max-height: 520px; background: #0f172a; border-radius: 8px; overflow: hidden; padding: 16px;">
                        <img src="${active_att.file_url}" alt="Receipt Preview" style="max-height: 490px; max-width: 100%; object-fit: contain; border-radius: 6px; box-shadow: 0 4px 15px rgba(0,0,0,0.5);" />
                    </div>
                `;
            } else if (active_att.is_pdf) {
                preview_content = `
                    <div style="height: 520px; width: 100%; background: #f8fafc; border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0;">
                        <iframe src="${active_att.file_url}" style="width: 100%; height: 100%; border: none;" title="PDF Preview"></iframe>
                    </div>
                `;
            } else {
                preview_content = `
                    <div style="text-align: center; padding: 80px 20px; background: #f8fafc; border-radius: 8px; border: 2px dashed #cbd5e1;">
                        <div style="font-size: 48px; margin-bottom: 12px;">📁</div>
                        <div style="font-size: 16px; font-weight: 600; color: #1e293b;">${active_att.file_name}</div>
                        <div style="font-size: 13px; color: #64748b; margin-top: 6px;">This file type cannot be previewed directly in browser.</div>
                        <a href="${active_att.file_url}" download class="btn btn-primary btn-sm" style="margin-top: 16px;">
                            ⬇️ Download File (${(active_att.extension || '').toUpperCase()})
                        </a>
                    </div>
                `;
            }

            let thumb_items_html = '';
            attachments.forEach((att, idx) => {
                const is_selected = idx === current_index;
                const item_date_formatted = window.APReceiptGallery.formatDate(att.date);
                const row_title = (att.row_idx ? `Row #${att.row_idx}: ` : '') + (att.merchant || 'Expense');

                thumb_items_html += `
                    <div class="ap-receipt-thumb-item" data-idx="${idx}" style="
                        display: flex;
                        align-items: center;
                        gap: 12px;
                        padding: 10px 12px;
                        margin-bottom: 8px;
                        border-radius: 8px;
                        cursor: pointer;
                        transition: all 0.15s ease-in-out;
                        background: ${is_selected ? '#ede9fe' : '#ffffff'};
                        border: ${is_selected ? '2px solid #8b5cf6' : '1px solid #e2e8f0'};
                        box-shadow: ${is_selected ? '0 2px 8px rgba(139, 92, 246, 0.25)' : 'none'};
                    ">
                        <div style="font-size: 22px;">${att.is_pdf ? '📄' : '🧾'}</div>
                        <div style="flex: 1; overflow: hidden;">
                            <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px;">
                                <span style="font-size: 13px; font-weight: 700; color: #1e293b; white-space: nowrap; text-overflow: ellipsis; overflow: hidden;">
                                    ${row_title}
                                </span>
                                ${item_date_formatted ? `
                                    <span style="font-size: 11px; font-weight: 700; color: #4338ca; background: #e0e7ff; border: 1px solid #c7d2fe; padding: 2px 6px; border-radius: 4px; white-space: nowrap; flex-shrink: 0;">
                                        📅 ${item_date_formatted}
                                    </span>
                                ` : ''}
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px;">
                                <span style="font-size: 12px; font-weight: 700; color: #059669;">${window.APReceiptGallery.formatINR(att.amount)}</span>
                                <span style="font-size: 11px; color: #64748b; white-space: nowrap; text-overflow: ellipsis; overflow: hidden;">${att.category}</span>
                            </div>
                        </div>
                    </div>
                `;
            });

            const header_title = (active_att.row_idx ? `Row #${active_att.row_idx}: ` : '') + active_att.merchant;

            const full_html = `
                <div style="display: flex; gap: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                    <!-- Left Sidebar (Receipts List) -->
                    <div style="width: 350px; max-height: 540px; overflow-y: auto; padding-right: 8px; border-right: 1px solid #e2e8f0;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                            <span style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b;">
                                Attached Proofs (${attachments.length})
                            </span>
                            <button class="btn btn-xs btn-default ap-btn-download-all" style="font-size: 11px; font-weight: 600; color: #4f46e5;">
                                📦 ZIP All
                            </button>
                        </div>
                        <div class="ap-receipts-list">
                            ${thumb_items_html}
                        </div>
                    </div>

                    <!-- Right Main Viewer Area -->
                    <div style="flex: 1; display: flex; flex-direction: column;">
                        <!-- Active Receipt Toolbar -->
                        <div style="display: flex; justify-content: space-between; align-items: center; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 16px; margin-bottom: 14px;">
                            <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 10px;">
                                <span style="font-size: 14px; font-weight: 700; color: #0f172a;">
                                    ${header_title}
                                </span>
                                ${active_date_formatted ? `
                                    <span style="font-size: 12px; font-weight: 700; color: #3730a3; background: #e0e7ff; border: 1px solid #c7d2fe; padding: 3px 10px; border-radius: 6px;">
                                        📅 Expense Date: <b>${active_date_formatted}</b>
                                    </span>
                                ` : ''}
                                <span style="font-size: 12px; color: #64748b;">
                                    Amount: <b style="color: #059669; font-size: 13px;">${window.APReceiptGallery.formatINR(active_att.amount)}</b> | Category: <b style="color: #1e293b;">${active_att.category}</b>
                                </span>
                            </div>
                            <div style="display: flex; gap: 8px;">
                                <a href="${active_att.file_url}" download="${active_att.file_name}" class="btn btn-sm btn-primary" style="font-weight: 600;">
                                    ⬇️ Download This (${(active_att.extension || '').toUpperCase()})
                                </a>
                                <a href="${active_att.file_url}" target="_blank" class="btn btn-sm btn-default" title="Open Full in New Tab">
                                    ↗️
                                </a>
                            </div>
                        </div>

                        <!-- Viewer Box -->
                        <div class="ap-preview-container" style="flex: 1;">
                            ${preview_content}
                        </div>
                    </div>
                </div>
            `;

            d.fields_dict.gallery_html_area.$wrapper.html(full_html);
        };

        d.show();
        update_view();

        // Attach click events
        d.$wrapper.off('click', '.ap-receipt-thumb-item').on('click', '.ap-receipt-thumb-item', function () {
            current_index = parseInt($(this).attr('data-idx'));
            update_view();
        });

        d.$wrapper.off('click', '.ap-btn-download-all').on('click', '.ap-btn-download-all', function () {
            const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
            window.location.href = url;
        });
    }
};

frappe.ui.form.on("Employee Reimbursement Claim", {
    onload: function(frm) {
        if (frm.is_new() && !frm.doc.employee) {
            frappe.db.get_value("Employee", {"user_id": frappe.session.user}, ["name", "employee_name", "company", "department", "bank_name", "bank_ac_no", "ifsc_code"])
                .then(r => {
                    if (r && r.message) {
                        frm.set_value("employee", r.message.name);
                        frm.set_value("employee_name", r.message.employee_name);
                        frm.set_value("company", r.message.company);
                        frm.set_value("department", r.message.department);
                        frm.set_value("bank_name", r.message.bank_name);
                        frm.set_value("bank_account_number", r.message.bank_ac_no);
                        frm.set_value("bank_ifsc_code", r.message.ifsc_code);
                    }
                });
        }
    },

    refresh: function(frm) {
        calculate_reimbursement_totals(frm);
        window.APReceiptGallery.setup(frm);
    },

    advance_amount: function(frm) {
        calculate_reimbursement_totals(frm);
    }
});

frappe.ui.form.on("Employee Reimbursement Line", {
    amount: function(frm) {
        calculate_reimbursement_totals(frm);
    },
    attach_receipt: function(frm) {
        window.APReceiptGallery.setup(frm);
    },
    receipt_attachment: function(frm) {
        window.APReceiptGallery.setup(frm);
    },
    expense_lines_add: function(frm) {
        window.APReceiptGallery.setup(frm);
    },
    expense_lines_remove: function(frm) {
        calculate_reimbursement_totals(frm);
        window.APReceiptGallery.setup(frm);
    }
});

function calculate_reimbursement_totals(frm) {
    let total = 0.0;
    (frm.doc.expense_lines || []).forEach(row => {
        total += parseFloat(row.amount || 0.0);
    });
    let advance = parseFloat(frm.doc.advance_amount || 0.0);
    let net = Math.max(total - advance, 0.0);

    frm.set_value("total_claim_amount", Math.round(total * 100) / 100);
    frm.set_value("net_payable_amount", Math.round(net * 100) / 100);
}
