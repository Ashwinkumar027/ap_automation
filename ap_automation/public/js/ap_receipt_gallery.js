/**
 * AP Automation - Universal Receipt & Audit Gallery Manager
 * Provides bank-grade 2-Column In-Tab Modal Lightbox, Date Badges, and ZIP Packaging
 * Active for ALL records across all AP Claim DocTypes.
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

    show: function (frm, opts) {
        opts = opts || {};
        const attachments = this.extractLocalAttachments(frm);
        const start_idx = opts.active_index || opts.index || 0;
        if (attachments && attachments.length > 0) {
            this.openModal(frm, attachments, start_idx);
        } else {
            this.openEmptyModal(frm);
        }
    },

    download_all_zip: function (frm) {
        const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
        window.open(url, '_blank');
    },

    openEmptyModal: function (frm) {
        const d = new frappe.ui.Dialog({
            title: __('Proof & Receipt Gallery - ') + frm.doc.name,
            size: 'large',
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'empty_html',
                    options: `
                        <div style="text-align: center; padding: 60px 20px; color: #64748b;">
                            <div style="font-size: 48px; margin-bottom: 12px;">🧾</div>
                            <h4 style="color: #1e293b; font-weight: 700;">No Receipts Attached Yet</h4>
                            <p style="font-size: 13px; max-width: 400px; margin: 8px auto;">
                                Use the <b>📷 Add Photo</b> button on each row in the expense grid to upload bill receipts.
                            </p>
                        </div>
                    `
                }
            ]
        });
        d.show();
    },

    openModal: function (frm, attachments, initial_index) {
        if (!attachments || attachments.length === 0) {
            this.openEmptyModal(frm);
            return;
        }

        let current_index = initial_index >= 0 && initial_index < attachments.length ? initial_index : 0;

        const d = new frappe.ui.Dialog({
            title: __('Proof & Receipt Gallery — ') + frm.doc.name,
            size: 'extra-large',
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'gallery_html_area'
                }
            ]
        });

        const update_view = () => {
            const active_att = attachments[current_index];
            const active_date_formatted = window.APReceiptGallery.formatDate(active_att.date);

            let preview_content = '';
            if (active_att.is_image) {
                preview_content = `
                    <div style="height: 520px; display: flex; align-items: center; justify-content: center; background: #0f172a; border-radius: 8px; overflow: hidden; position: relative;">
                        <img src="${active_att.file_url}" style="max-width: 100%; max-height: 100%; object-fit: contain; box-shadow: 0 4px 20px rgba(0,0,0,0.4);" alt="Receipt Preview" />
                    </div>
                `;
            } else if (active_att.is_pdf) {
                preview_content = `
                    <div style="height: 520px; background: #f8fafc; border-radius: 8px; overflow: hidden; border: 1px solid #cbd5e1;">
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
