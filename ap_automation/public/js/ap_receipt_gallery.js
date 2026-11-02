/**
 * AP Automation - Universal Receipt & Audit Gallery Manager
 * Provides bank-grade 2-Column In-Tab Modal Lightbox, Zero Scroll Jump, Interactive Zoom In/Out/Pan, Direct In-App PDF Viewer,
 * Prominent Expenses of Head Badge with In-Modal 1-Click Editing, and Smart Subtitles (Never "nil").
 * Active across ALL AP DocTypes (Petty Cash, Employee Reimbursements, Vendor Invoices, Admin Weekly Claims, Events).
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
            const parts = String(d_str).trim().split(' ')[0].split('-');
            if (parts.length === 3 && parts[0].length === 4) {
                return parts[2] + '-' + parts[1] + '-' + parts[0];
            }
            return String(d_str).trim().split(' ')[0];
        } catch (e) {
            return String(d_str);
        }
    },

    sanitizeMerchantTitle: function (raw_name, fallback_head, fallback_cat) {
        if (!raw_name) {
            return fallback_head || fallback_cat || 'Expense Line';
        }
        const s = String(raw_name).trim();
        const lower = s.toLowerCase();
        if (['nil', 'null', 'none', '-', 'n/a', 'na'].includes(lower)) {
            return fallback_head || fallback_cat || 'Expense Line';
        }
        return s;
    },

    buildViewUrl: function (frm, clean_url) {
        if (!clean_url) return '';
        const dt = (frm && frm.doc && frm.doc.doctype) ? frm.doc.doctype : '';
        const dn = (frm && frm.doc && frm.doc.name) ? frm.doc.name : '';
        return `/api/method/ap_automation.services.attachment_service.view_receipt_file?file_url=${encodeURIComponent(clean_url)}&doctype=${encodeURIComponent(dt)}&docname=${encodeURIComponent(dn)}`;
    },

    extractLocalAttachments: function (frm) {
        const atts = [];
        const self = this;

        if (!frm || !frm.doc) return atts;

        // 1. Expense Lines (Petty Cash, Reimbursements)
        (frm.doc.expense_lines || []).forEach((row, idx) => {
            const file_url = row.attach_receipt || row.receipt_attachment || row.attachment || row.tax_invoice_attachment || row.bill_attachment;
            if (file_url && typeof file_url === 'string' && file_url.trim()) {
                const clean_url = file_url.trim();
                const file_name = clean_url.split('/').pop().split('?')[0];
                const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
                const is_img = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext);
                const is_pdf = ext === '.pdf';

                const head = row.expense_head || row.head_of_expense || '';
                const cat = row.expense_category || row.category || row.expense_type || 'General Expense';
                const smart_title = self.sanitizeMerchantTitle(row.merchant_name || row.merchant, head, cat);

                atts.push({
                    source: 'row',
                    row_idx: row.idx || (idx + 1),
                    merchant: smart_title,
                    subtitle: row.merchant_name || '',
                    vendor: row.vendor_name || row.vendor || '',
                    category: cat,
                    expense_head: head,
                    custom_ledger_name: row.custom_ledger_name || '',
                    description: row.description || row.remarks || row.particulars || '',
                    amount: parseFloat(row.amount || row.claim_amount || 0.0),
                    date: row.expense_date || row.date || frm.doc.posting_date || '',
                    bill_no: row.bill_number || row.bill_no || row.invoice_number || '',
                    file_url: clean_url,
                    view_url: self.buildViewUrl(frm, clean_url),
                    file_name: file_name,
                    is_image: is_img,
                    is_pdf: is_pdf,
                    extension: ext
                });
            }
        });

        // 2. Client Visit Legs (Reimbursements)
        (frm.doc.client_visit_legs || []).forEach((leg, idx) => {
            const file_url = leg.receipt_attachment || leg.attachment;
            if (file_url && typeof file_url === 'string' && file_url.trim()) {
                const clean_url = file_url.trim();
                const file_name = clean_url.split('/').pop().split('?')[0];
                const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
                const is_img = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext);
                const is_pdf = ext === '.pdf';

                const travel_title = leg.client_name ? `${leg.client_name} (${leg.mode_of_travel || 'Travel'})` : 'Client Travel';
                const route_cat = (leg.from_location && leg.to_location) ? `Route: ${leg.from_location} → ${leg.to_location}` : 'Travel Proof';

                atts.push({
                    source: 'row',
                    row_idx: leg.idx || (idx + 1),
                    merchant: travel_title,
                    subtitle: leg.client_name || '',
                    vendor: leg.client_name || '',
                    category: route_cat,
                    expense_head: 'TRAVEL EXPENSES',
                    description: leg.purpose_of_visit || leg.description || '',
                    amount: parseFloat(leg.leg_amount || 0.0) + parseFloat(leg.toll_parking_amount || 0.0),
                    date: leg.visit_date || leg.travel_date || frm.doc.posting_date || '',
                    bill_no: String(leg.idx || idx + 1),
                    file_url: clean_url,
                    view_url: self.buildViewUrl(frm, clean_url),
                    file_name: file_name,
                    is_image: is_img,
                    is_pdf: is_pdf,
                    extension: ext
                });
            }
        });

        // 3. Child tables for Admin Claims, Events & Items
        ['lines', 'items', 'instructions', 'expense_items', 'imprest_items', 'vendor_lines'].forEach(table_field => {
            const rows = frm.doc[table_field] || [];
            rows.forEach((row, idx) => {
                const file_url = row.attach_receipt || row.receipt_attachment || row.attachment || row.quote_attachment || row.tax_invoice_attachment;
                const raw_v = row.vendor_name || row.beneficiary_name || row.vendor || row.merchant_name || row.merchant || '';
                if (file_url && typeof file_url === 'string' && file_url.trim()) {
                    const clean_url = file_url.trim();
                    const file_name = clean_url.split('/').pop().split('?')[0];
                    const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');

                    const head = row.expense_head || row.vendor_category || row.head_of_expense || '';
                    const cat = row.vendor_category || row.category || row.expense_category || row.expense_type || row.spend_stream || 'Expense Line';
                    const raw_m = raw_v || row.particulars;
                    const smart_title = self.sanitizeMerchantTitle(raw_m, head, cat);

                    atts.push({
                        source: 'row',
                        row_idx: row.idx || (idx + 1),
                        merchant: smart_title,
                        subtitle: raw_v || raw_m || '',
                        vendor: raw_v,
                        vendor_name: raw_v,
                        category: cat,
                        expense_head: head,
                        custom_ledger_name: row.custom_ledger_name || '',
                        description: row.description || row.remarks || row.particulars || row.discrepancy_remarks || '',
                        amount: parseFloat(row.amount || row.total_invoice_amount || row.base_amount || 0.0),
                        date: row.invoice_date || row.expense_date || row.bill_date || frm.doc.posting_date || '',
                        bill_no: row.invoice_number || row.bill_number || row.bill_no || '',
                        file_url: clean_url,
                        view_url: self.buildViewUrl(frm, clean_url),
                        file_name: file_name,
                        is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext),
                        is_pdf: ext === '.pdf',
                        extension: ext
                    });
                }

                // In-row Bank Proof / Cancelled Cheque Display
                if (row.bank_proof_attachment && typeof row.bank_proof_attachment === 'string' && row.bank_proof_attachment.trim()) {
                    const bp_url = row.bank_proof_attachment.trim();
                    const bp_name = bp_url.split('/').pop().split('?')[0];
                    const bp_ext = (bp_name.lastIndexOf('.') !== -1 ? bp_name.substring(bp_name.lastIndexOf('.')).toLowerCase() : '');
                    atts.push({
                        source: 'row',
                        row_idx: row.idx || (idx + 1),
                        merchant: `Bank Cheque Proof — ${raw_v || 'Vendor'}`,
                        subtitle: raw_v || '',
                        vendor: raw_v,
                        vendor_name: raw_v,
                        category: 'Bank Account Proof (Cancelled Cheque)',
                        expense_head: 'Bank Details Verification',
                        custom_ledger_name: '',
                        description: `Cancelled Cheque / Passbook verification for ${raw_v} (A/C: ${row.bank_account_number || ''})`,
                        amount: parseFloat(row.amount || row.total_invoice_amount || row.base_amount || 0.0),
                        date: row.invoice_date || frm.doc.posting_date || '',
                        bill_no: row.invoice_number || '',
                        file_url: bp_url,
                        view_url: self.buildViewUrl(frm, bp_url),
                        file_name: bp_name,
                        is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(bp_ext),
                        is_pdf: bp_ext === '.pdf',
                        extension: bp_ext
                    });
                }
            });
        });

        // 4. Parent direct attachments (Invoices, Approvals, Proofs across all modules)
        const parent_vendor = frm.doc.vendor_name || frm.doc.supplier_name || frm.doc.vendor || frm.doc.supplier || '';
        const parent_fields = [
            { field: 'tax_invoice_attachment', label: parent_vendor ? `Vendor Tax Invoice — ${parent_vendor}` : 'Vendor Tax Invoice', cat: 'Vendor Commercial Invoice' },
            { field: 'email_approval_attachment', label: 'Manager Email Approval Proof', cat: 'Audit Approval Proof' },
            { field: 'bank_proof_attachment', label: parent_vendor ? `Bank Cheque Proof — ${parent_vendor}` : 'Bank Account Proof (Cancelled Cheque / Passbook)', cat: 'Bank Details Verification' },
            { field: 'grn_attachment', label: 'Goods Receipt Note / Delivery Proof', cat: 'Warehouse Receipt' },
            { field: 'advance_receipt_attachment', label: 'Advance Payment Proof', cat: 'Bank Advance Proof' },
            { field: 'settlement_statement', label: 'Event Settlement Statement', cat: 'Event Settlement' },
            { field: 'activity_photo', label: '📸 Team Activity Photo Proof', cat: 'Team Engagement & Recreation' },
            { field: 'pre_approval_attachment', label: '📋 Pre-Approval Authorization Screenshot', cat: 'Audit Proof Document' }
        ];

        parent_fields.forEach(pf => {
            let file_url = frm.doc[pf.field];
            if (!file_url && pf.field === 'bank_proof_attachment' && frm._bank_account_doc && frm._bank_account_doc.bank_proof_attachment) {
                file_url = frm._bank_account_doc.bank_proof_attachment;
            }
            if (file_url && typeof file_url === 'string' && file_url.trim()) {
                const clean_url = file_url.trim();
                const file_name = clean_url.split('/').pop().split('?')[0];
                const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
                atts.push({
                    source: 'parent',
                    row_idx: null,
                    merchant: pf.label,
                    subtitle: parent_vendor,
                    vendor: parent_vendor,
                    vendor_name: parent_vendor,
                    category: pf.cat,
                    expense_head: frm.doc.expense_head || frm.doc.service_type || pf.cat,
                    custom_ledger_name: '',
                    description: frm.doc.remarks || frm.doc.purpose || '',
                    amount: parseFloat(frm.doc.total_claim_amount || frm.doc.total_amount || frm.doc.total_invoice_amount || frm.doc.grand_total || 0.0),
                    date: frm.doc.posting_date || frm.doc.tax_invoice_date || frm.doc.activity_date || frm.doc.creation || '',
                    bill_no: frm.doc.invoice_number || frm.doc.tax_invoice_number || frm.doc.name || '',
                    file_url: clean_url,
                    view_url: self.buildViewUrl(frm, clean_url),
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
        const atts = this.extractLocalAttachments(frm);
        if (!atts || atts.length === 0) {
            this.openEmptyModal(frm);
            return;
        }
        this.openModal(frm, atts, opts.active_index || 0);
    },

    setup: function (frm) {
        if (!frm) return;
        const self = this;
        setTimeout(() => {
            const atts = self.extractLocalAttachments(frm);
            if (atts && atts.length > 0) {
                frm.add_custom_button(__(`🧾 Proof Gallery (${atts.length})`), function () {
                    self.show(frm);
                }, __('Audit Proofs')).addClass('btn-info');
            }
        }, 500);
    },

    download_all_zip: function (frm) {
        const dt = (frm && frm.doc && frm.doc.doctype) ? frm.doc.doctype : '';
        const dn = (frm && frm.doc && frm.doc.name) ? frm.doc.name : '';
        const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(dt)}&docname=${encodeURIComponent(dn)}`;
        window.open(url, '_blank');
    },

    openEmptyModal: function (frm) {
        const d = new frappe.ui.Dialog({
            title: __('Proof & Receipt Gallery — ') + (frm && frm.doc ? frm.doc.name : ''),
            size: 'large',
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'gallery_empty_view',
                    options: `
                        <div style="text-align: center; padding: 60px 20px;">
                            <div style="font-size: 54px; margin-bottom: 16px;">📂</div>
                            <div style="font-size: 18px; font-weight: 700; color: #1e293b;">No Proofs or Receipts Attached</div>
                            <div style="font-size: 14px; color: #64748b; margin-top: 8px;">
                                This document does not contain any uploaded tax invoices, bill receipts, or photo proofs yet.
                            </div>
                        </div>
                    `
                }
            ]
        });
        d.show();
    },

    openModal: function (frm, attachments, start_idx) {
        const self = this;
        if (!attachments || attachments.length === 0) {
            this.openEmptyModal(frm);
            return;
        }

        start_idx = start_idx || 0;
        let current_index = Math.min(Math.max(0, start_idx), attachments.length - 1);

        // Normalize attachment objects from all callers & eliminate "nil"
        attachments = attachments.map((att, idx) => {
            const raw_url = (att.file_url || att.receipt_attachment || att.attach_receipt || '').trim();
            const file_name = att.file_name || (raw_url ? raw_url.split('/').pop().split('?')[0] : `receipt_${idx + 1}`);
            const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : (att.extension || ''));
            const is_img = att.is_image !== undefined ? att.is_image : ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext);
            const is_pdf = att.is_pdf !== undefined ? att.is_pdf : ext === '.pdf';

            const head = att.expense_head || att.head_of_expense || att.vendor_category || '';
            const cat = att.category || att.vendor_category || att.expense_category || '';
            const raw_v = att.vendor_name || att.vendor || att.beneficiary_name || (frm && frm.doc && (frm.doc.vendor_name || frm.doc.supplier_name || frm.doc.vendor || frm.doc.supplier)) || '';
            const raw_m = raw_v || att.merchant || att.particulars;
            const smart_title = self.sanitizeMerchantTitle(raw_m, head, cat);

            return {
                source: att.source || 'row',
                row_idx: att.row_idx !== undefined ? att.row_idx : (idx + 1),
                merchant: smart_title,
                subtitle: att.subtitle || (raw_v || ''),
                vendor: raw_v,
                vendor_name: raw_v,
                category: cat,
                expense_head: head,
                custom_ledger_name: att.custom_ledger_name || '',
                description: att.description || att.remarks || att.particulars || att.discrepancy_remarks || '',
                amount: parseFloat(att.amount || att.total_invoice_amount || att.base_amount || 0.0),
                date: att.date || att.invoice_date || att.bill_date || att.expense_date || '',
                bill_no: att.bill_no || att.invoice_number || att.bill_number || '',
                file_url: raw_url,
                view_url: att.view_url || (raw_url ? self.buildViewUrl(frm, raw_url) : ''),
                file_name: file_name,
                is_image: is_img,
                is_pdf: is_pdf,
                extension: ext
            };
        });

        // Top Document Level Metadata (Staff, Status, DocName)
        const staff_name = (frm && frm.doc) ? (frm.doc.employee_name || frm.doc.staff_name || frm.doc.custodian || frm.doc.spoc_name || frm.doc.spoc || frm.doc.owner || '') : '';
        const payment_status = (frm && frm.doc) ? (frm.doc.status || frm.doc.payment_status || 'Draft') : '';
        const doc_title = (frm && frm.doc) ? frm.doc.name : 'Claim';

        const d = new frappe.ui.Dialog({
            title: __('Proof & Receipt Gallery — ') + doc_title,
            size: 'extra-large',
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'gallery_html_area'
                }
            ]
        });

        // Zoom, Pan & Rotation State
        let zoom_level = 1.0;
        let rotation_deg = 0;
        let pan_x = 0;
        let pan_y = 0;
        let is_dragging = false;
        let start_drag_x = 0;
        let start_drag_y = 0;

        // Build Left Thumbnail List HTML ONCE (Permanent DOM - never destroyed on row clicks)
        let thumb_items_html = '';
        attachments.forEach((att, idx) => {
            const is_selected = idx === current_index;
            const item_date_formatted = self.formatDate(att.date);
            const v_name = att.vendor_name || att.vendor || '';
            const row_title = (att.row_idx ? `Row #${att.row_idx}: ` : '') + (v_name ? v_name : (att.merchant || 'Expense'));

            thumb_items_html += `
                <div class="ap-receipt-thumb-item ${is_selected ? 'ap-selected-row' : ''}" data-idx="${idx}" style="
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 10px 12px;
                    margin-bottom: 8px;
                    border-radius: 8px;
                    cursor: pointer;
                    transition: background 0.15s ease, border-color 0.15s ease;
                    background: ${is_selected ? '#ede9fe' : '#ffffff'};
                    border: ${is_selected ? '2px solid #8b5cf6' : '1px solid #e2e8f0'};
                    box-shadow: ${is_selected ? '0 2px 8px rgba(139, 92, 246, 0.25)' : 'none'};
                ">
                    <div style="font-size: 22px; flex-shrink: 0;">${att.is_pdf ? '📄' : '🧾'}</div>
                    <div style="flex: 1; min-width: 0; overflow: hidden;">
                        <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px;">
                            <span class="ap-thumb-title-text" style="font-size: 13px; font-weight: 700; color: #1e293b; white-space: nowrap; text-overflow: ellipsis; overflow: hidden;" title="${row_title}">
                                ${row_title}
                            </span>
                            ${item_date_formatted ? `
                                <span style="font-size: 11px; font-weight: 700; color: #4338ca; background: #e0e7ff; border: 1px solid #c7d2fe; padding: 2px 6px; border-radius: 4px; white-space: nowrap; flex-shrink: 0;">
                                    📅 ${item_date_formatted}
                                </span>
                            ` : ''}
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px; gap: 8px;">
                            <span style="font-size: 12px; font-weight: 700; color: #059669; flex-shrink: 0;">${self.formatINR(att.amount)}</span>
                            <span class="ap-thumb-category-text" style="font-size: 11px; color: #64748b; white-space: nowrap; text-overflow: ellipsis; overflow: hidden;" title="${v_name ? 'Vendor: ' + v_name + ' • ' : ''}${att.category || att.expense_head || ''}">
                                ${v_name ? '🏢 ' + v_name : (att.expense_head || att.category || '')}
                            </span>
                        </div>
                    </div>
                </div>
            `;
        });

        // Base Shell Structure (Injected into dialog ONCE)
        const base_shell_html = `
            <div class="ap-gallery-wrapper" style="display: flex; gap: 16px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                <!-- Left Sidebar: Static DOM preserving scroll position permanently -->
                <div class="ap-gallery-sidebar" style="width: 320px; max-height: 640px; overflow-y: auto; padding-right: 8px; border-right: 1px solid #e2e8f0; flex-shrink: 0;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding: 0 4px;">
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

                <!-- Right Main Area: Re-rendered dynamically on row selection without touching sidebar -->
                <div class="ap-gallery-main" style="flex: 1; display: flex; flex-direction: column; min-width: 0;">
                    <div class="ap-gallery-main-content">
                        <!-- Populated by render_active_preview() -->
                    </div>
                </div>
            </div>
        `;

        d.fields_dict.gallery_html_area.$wrapper.html(base_shell_html);
        const $wrapper = d.$wrapper;
        const $sidebar = $wrapper.find('.ap-gallery-sidebar');
        const $main_content = $wrapper.find('.ap-gallery-main-content');

        // Function to render active receipt view in the right pane ONLY
        const render_active_preview = () => {
            const active_att = attachments[current_index];
            const active_date_formatted = self.formatDate(active_att.date);
            const active_vendor = active_att.vendor_name || active_att.vendor || (frm && frm.doc && (frm.doc.vendor_name || frm.doc.supplier_name || frm.doc.vendor || frm.doc.supplier)) || '';
            const header_title = (active_att.row_idx ? `Row #${active_att.row_idx}: ` : '') + (active_vendor ? `🏢 ${active_vendor}` : (active_att.merchant || 'Expense'));
            const target_url = active_att.view_url || active_att.file_url;

            // Reset zoom & pan for newly selected receipt
            zoom_level = 1.0;
            rotation_deg = 0;
            pan_x = 0;
            pan_y = 0;
            is_dragging = false;

            let preview_content = '';
            if (active_att.is_image) {
                preview_content = `
                    <div class="ap-image-viewport" style="display: flex; justify-content: center; align-items: center; background: #0f172a; border-radius: 8px; overflow: hidden; height: 570px; padding: 16px; position: relative; user-select: none; cursor: default;">
                        <img class="ap-preview-img" src="${target_url}" alt="${active_att.merchant}" style="max-width: 100%; max-height: 100%; object-fit: contain; box-shadow: 0 4px 20px rgba(0,0,0,0.5); border-radius: 4px; transform-origin: center center; transition: transform 0.15s ease;" 
                             onerror="this.onerror=null; this.parentElement.innerHTML='<div style=\'text-align: center; color: #f87171; padding: 40px;\'> <div style=\'font-size: 48px; margin-bottom: 12px;\'>⚠️</div> <div style=\'font-size: 16px; font-weight: 700;\'>Receipt Image Not Found on Server</div> <div style=\'font-size: 13px; color: #94a3b8; margin-top: 6px;\'>File: <code>' + escape('${active_att.file_name}') + '</code></div> <div style=\'font-size: 12px; color: #64748b; margin-top: 8px;\'>The file path is registered, but the physical file is not present on disk.</div> </div>';" />
                    </div>
                `;
            } else if (active_att.is_pdf) {
                // Direct In-App Interactive PDF Viewer (No Forced Downloads)
                preview_content = `
                    <div class="ap-pdf-viewport" style="background: #0f172a; border-radius: 8px; overflow: hidden; height: 570px; position: relative;">
                        <object data="${target_url}#toolbar=1&navpanes=0&scrollbar=1" type="application/pdf" style="width: 100%; height: 100%; border: none; border-radius: 6px; background: #ffffff;" class="ap-preview-pdf">
                            <iframe src="${target_url}#toolbar=1&navpanes=0" style="width: 100%; height: 100%; border: none; background: #ffffff;" title="PDF Preview" class="ap-preview-pdf">
                                <div style="text-align: center; color: #ffffff; padding: 60px 20px;">
                                    <div style="font-size: 48px; margin-bottom: 12px;">📄</div>
                                    <div style="font-size: 16px; font-weight: 700;">PDF Document View</div>
                                    <div style="font-size: 13px; color: #94a3b8; margin-top: 6px;">${active_att.file_name}</div>
                                    <a href="${target_url}" target="_blank" class="btn btn-sm btn-primary" style="margin-top: 16px;">
                                        ↗ Open PDF in Browser Tab
                                    </a>
                                </div>
                            </iframe>
                        </object>
                    </div>
                `;
            } else {
                preview_content = `
                    <div style="text-align: center; padding: 80px 20px; background: #f8fafc; border-radius: 8px; border: 2px dashed #cbd5e1; height: 570px; display: flex; flex-direction: column; justify-content: center; align-items: center;">
                        <div style="font-size: 48px; margin-bottom: 12px;">📁</div>
                        <div style="font-size: 16px; font-weight: 600; color: #1e293b;">${active_att.file_name}</div>
                        <div style="font-size: 13px; color: #64748b; margin-top: 6px;">Direct preview is not available for .${active_att.extension || 'file'} files.</div>
                        <a href="${active_att.file_url}" download class="btn btn-primary btn-sm" style="margin-top: 16px;">
                            ⬇️ Download File (${(active_att.extension || '').toUpperCase()})
                        </a>
                    </div>
                `;
            }

            const active_html = `
                <!-- Top Header & Universal Metadata Banner -->
                <div class="ap-gallery-toolbar" style="display: flex; justify-content: space-between; align-items: center; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; gap: 10px; flex-wrap: wrap;">
                    <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 8px;">
                        <span class="ap-header-title-text" style="font-size: 14px; font-weight: 700; color: #0f172a;">
                            ${header_title}
                        </span>
                        ${active_date_formatted ? `
                            <span style="font-size: 11px; font-weight: 700; color: #3730a3; background: #e0e7ff; border: 1px solid #c7d2fe; padding: 2px 7px; border-radius: 4px;">
                                📅 ${active_date_formatted}
                            </span>
                        ` : ''}
                        <span style="font-size: 12px; color: #64748b;">
                            Amount: <b style="color: #059669; font-size: 13px;">${self.formatINR(active_att.amount)}</b>
                        </span>

                        <!-- Prominent Vendor Legal Name Pill -->
                        ${active_vendor ? `
                            <div class="ap-vendor-badge-pill" style="display: inline-flex; align-items: center; background: #fffbeb; border: 1.5px solid #fcd34d; border-radius: 6px; padding: 2px 10px; gap: 6px;" title="Vendor Legal Name">
                                <span style="font-size: 11.5px; font-weight: 700; color: #92400e;">
                                    🏢 Vendor: <b class="ap-active-vendor-text" style="color: #78350f; font-weight: 800;">${active_vendor}</b>
                                </span>
                            </div>
                        ` : ''}

                        <!-- Prominent Expenses of Head Badge with In-Modal 1-Click Edit Button -->
                        <div class="ap-head-badge-pill" style="display: inline-flex; align-items: center; background: #eff6ff; border: 1.5px solid #93c5fd; border-radius: 6px; padding: 2px 8px; gap: 6px;">
                            <span style="font-size: 11px; font-weight: 700; color: #1e40af;">
                                💼 Head: <span class="ap-active-head-text">${active_att.expense_head || 'Unassigned'}</span>
                            </span>
                            <button type="button" class="btn btn-xs btn-default ap-btn-edit-head" data-idx="${current_index}" title="Edit Expenses of Head for this row" style="font-size: 10.5px; font-weight: 700; color: #1d4ed8; padding: 1px 7px; border: 1px solid #bfdbfe; background: #ffffff; border-radius: 4px; cursor: pointer;">
                                ✏️ Edit
                            </button>
                        </div>

                        <!-- Prominent Expense Type Badge with In-Modal 1-Click Edit Button -->
                        <div class="ap-type-badge-pill" style="display: inline-flex; align-items: center; background: #ecfdf5; border: 1.5px solid #a7f3d0; border-radius: 6px; padding: 2px 8px; gap: 6px;">
                            <span style="font-size: 11px; font-weight: 700; color: #047857;">
                                🏷️ Type: <span class="ap-active-type-text">${active_att.category || 'General Expense'}</span>
                            </span>
                            <button type="button" class="btn btn-xs btn-default ap-btn-edit-type" data-idx="${current_index}" title="Edit Expense Type for this row" style="font-size: 10.5px; font-weight: 700; color: #047857; padding: 1px 7px; border: 1px solid #a7f3d0; background: #ffffff; border-radius: 4px; cursor: pointer;">
                                ✏️ Edit
                            </button>
                        </div>

                        <!-- In-Modal Upload / Replace Receipt Proof Button -->
                        <button type="button" class="btn btn-xs btn-default ap-btn-replace-receipt" data-idx="${current_index}" title="Upload new / replace receipt proof" style="font-size: 10.5px; font-weight: 700; color: #b45309; padding: 2px 8px; border: 1.5px solid #fde68a; background: #fffbeb; border-radius: 6px; cursor: pointer;">
                            📷 Upload / Replace
                        </button>
                        ${active_att.description ? `
                            <span style="font-size: 11px; color: #334155; background: #f8fafc; border: 1px solid #cbd5e1; padding: 2px 8px; border-radius: 4px; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${active_att.description}">
                                📝 ${active_att.description}
                            </span>
                        ` : ''}
                        ${staff_name ? `
                            <span style="font-size: 11px; color: #475569;">
                                👤 <b>${staff_name}</b>
                            </span>
                        ` : ''}
                        ${payment_status ? `
                            <span style="font-size: 11px; font-weight: 700; color: #047857; background: #ecfdf5; border: 1px solid #a7f3d0; padding: 2px 7px; border-radius: 4px;">
                                ● ${payment_status}
                            </span>
                        ` : ''}
                    </div>

                    <!-- Actions & Zoom Controls -->
                    <div class="ap-gallery-toolbar-actions" style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        ${active_att.is_image ? `
                            <!-- Interactive Zoom Toolbar -->
                            <div class="ap-zoom-toolbar" style="display: inline-flex; align-items: center; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 4px; gap: 2px;">
                                <button type="button" class="btn btn-xs btn-default ap-zoom-out-btn" title="Zoom Out (-25%)" style="border: none; padding: 3px 7px; font-weight: 700; color: #334155; font-size: 12px;">
                                    🔍 -
                                </button>
                                <span class="ap-zoom-level-text" style="font-size: 11px; font-weight: 700; color: #475569; min-width: 44px; text-align: center;">
                                    100%
                                </span>
                                <button type="button" class="btn btn-xs btn-default ap-zoom-in-btn" title="Zoom In (+25%)" style="border: none; padding: 3px 7px; font-weight: 700; color: #334155; font-size: 12px;">
                                    🔍 +
                                </button>
                                <button type="button" class="btn btn-xs btn-default ap-zoom-reset-btn" title="Reset Zoom to 100%" style="border: none; padding: 3px 6px; font-weight: 600; font-size: 10.5px; color: #64748b; border-left: 1px solid #e2e8f0;">
                                    1:1
                                </button>
                                <button type="button" class="btn btn-xs btn-default ap-zoom-rotate-btn" title="Rotate 90 degrees" style="border: none; padding: 3px 6px; font-weight: 600; font-size: 11px; color: #64748b; border-left: 1px solid #e2e8f0;">
                                    ⟳
                                </button>
                            </div>
                        ` : `
                            <span style="font-size: 11px; font-weight: 600; color: #475569; background: #f1f5f9; border: 1px solid #e2e8f0; padding: 3px 8px; border-radius: 4px;">
                                📄 Multi-Page PDF Viewer
                            </span>
                        `}

                        <a href="${target_url}" download="${active_att.file_name}" class="btn btn-sm btn-primary" style="font-weight: 600; padding: 4px 10px; font-size: 12px;">
                            ⬇️ Download (${(active_att.extension || '').toUpperCase()})
                        </a>
                        <a href="${target_url}" target="_blank" class="btn btn-sm btn-default" title="Open Full in New Tab" style="padding: 4px 8px; font-size: 12px;">
                            ↗️
                        </a>
                    </div>
                </div>

                <!-- Viewer Body -->
                <div class="ap-preview-container" style="flex: 1;">
                    ${preview_content}
                </div>
            `;

            $main_content.html(active_html);
        };

        // Zoom & Pan helper
        const apply_zoom = () => {
            const $img = $main_content.find('.ap-preview-img');
            const $viewport = $main_content.find('.ap-image-viewport');
            $main_content.find('.ap-zoom-level-text').text(Math.round(zoom_level * 100) + '%');
            if ($img.length) {
                $img.css({
                    'transform': `translate(${pan_x}px, ${pan_y}px) scale(${zoom_level}) rotate(${rotation_deg}deg)`,
                    'transform-origin': 'center center',
                    'transition': is_dragging ? 'none' : 'transform 0.15s ease'
                });
                if (zoom_level > 1.0) {
                    $viewport.css('cursor', is_dragging ? 'grabbing' : 'grab');
                } else {
                    $viewport.css('cursor', 'default');
                    pan_x = 0;
                    pan_y = 0;
                }
            }
        };

        // Wire zoom events on $main_content
        $main_content.on('click', '.ap-zoom-in-btn', function (e) {
            e.stopPropagation();
            zoom_level = Math.min(4.0, Math.round((zoom_level + 0.25) * 100) / 100);
            apply_zoom();
        });

        $main_content.on('click', '.ap-zoom-out-btn', function (e) {
            e.stopPropagation();
            zoom_level = Math.max(0.5, Math.round((zoom_level - 0.25) * 100) / 100);
            if (zoom_level <= 1.0) {
                pan_x = 0;
                pan_y = 0;
            }
            apply_zoom();
        });

        $main_content.on('click', '.ap-zoom-reset-btn', function (e) {
            e.stopPropagation();
            zoom_level = 1.0;
            rotation_deg = 0;
            pan_x = 0;
            pan_y = 0;
            apply_zoom();
        });

        $main_content.on('click', '.ap-zoom-rotate-btn', function (e) {
            e.stopPropagation();
            rotation_deg = (rotation_deg + 90) % 360;
            apply_zoom();
        });

        // Double click image to toggle 100% vs 200%
        $main_content.on('dblclick', '.ap-preview-img', function (e) {
            e.stopPropagation();
            zoom_level = zoom_level === 1.0 ? 2.0 : 1.0;
            pan_x = 0;
            pan_y = 0;
            apply_zoom();
        });

        // Mouse Wheel Zoom
        $main_content.on('wheel', '.ap-image-viewport', function (e) {
            e.preventDefault();
            if (e.originalEvent.deltaY < 0) {
                zoom_level = Math.min(4.0, Math.round((zoom_level + 0.2) * 100) / 100);
            } else {
                zoom_level = Math.max(0.5, Math.round((zoom_level - 0.2) * 100) / 100);
                if (zoom_level <= 1.0) {
                    pan_x = 0;
                    pan_y = 0;
                }
            }
            apply_zoom();
        });

        // Click & Drag Panning when zoomed in
        $main_content.on('mousedown', '.ap-image-viewport', function (e) {
            if (zoom_level > 1.0 && e.button === 0) {
                is_dragging = true;
                start_drag_x = e.clientX - pan_x;
                start_drag_y = e.clientY - pan_y;
                $(this).css('cursor', 'grabbing');
                e.preventDefault();
            }
        });

        $(document).on('mousemove.ap_gallery', function (e) {
            if (is_dragging) {
                pan_x = e.clientX - start_drag_x;
                pan_y = e.clientY - start_drag_y;
                apply_zoom();
            }
        });

        $(document).on('mouseup.ap_gallery mouseleave.ap_gallery', function () {
            if (is_dragging) {
                is_dragging = false;
                apply_zoom();
            }
        });

        // In-Modal Expense Head Editor (1-Click Update)
        $main_content.off('click', '.ap-btn-edit-head').on('click', '.ap-btn-edit-head', function (e) {
            e.stopPropagation();
            const active_att = attachments[current_index];
            const current_head = active_att.expense_head || '';
            const row_num = active_att.row_idx || (current_index + 1);

            frappe.call({
                method: 'ap_automation.services.attachment_service.get_active_expense_heads',
                callback: function (r) {
                    const heads = (r.message && r.message.length) ? r.message : [
                        'STAFF WELFARE', 'FOOD EXPENSES', 'OFFICE EXPENSES',
                        'OFFICE EXPENSES - GROCERY', 'OFFICE EXPENSES - POOJA',
                        'PRINTING & STATIONARY', 'COURIER CHARGES', 'POWER & FUEL EXPENSES',
                        'TRAVEL EXPENSES', 'OTHER EXPENSES', 'OTHER / VENDOR LEDGER'
                    ];

                    const edit_head_dialog = new frappe.ui.Dialog({
                        title: __(`Edit Expenses of Head — Row #${row_num}`),
                        fields: [
                            {
                                fieldname: 'expense_head',
                                fieldtype: 'Select',
                                label: __('Expenses of Head'),
                                options: heads,
                                default: current_head || heads[0],
                                reqd: 1,
                                change: function () {
                                    const val = edit_head_dialog.get_value('expense_head');
                                    edit_head_dialog.set_df_property('custom_head', 'hidden', val !== 'OTHER / VENDOR LEDGER');
                                }
                            },
                            {
                                fieldname: 'custom_head',
                                fieldtype: 'Data',
                                label: __('Custom Head / Ledger Name (Manual Typing)'),
                                default: active_att.custom_ledger_name || '',
                                hidden: current_head !== 'OTHER / VENDOR LEDGER',
                                description: __('Enter custom head or vendor ledger name')
                            }
                        ],
                        primary_action_label: __('Save Head'),
                        primary_action: function (vals) {
                            const selected_head = vals.expense_head;
                            const custom_val = (selected_head === 'OTHER / VENDOR LEDGER') ? (vals.custom_head || '') : '';
                            const final_head_to_save = (selected_head === 'OTHER / VENDOR LEDGER' && custom_val) ? custom_val : selected_head;

                            edit_head_dialog.hide();

                            frappe.call({
                                method: 'ap_automation.services.attachment_service.update_claim_row_expense_head',
                                args: {
                                    doctype: (frm && frm.doc) ? frm.doc.doctype : 'Petty Cash Entry',
                                    docname: (frm && frm.doc) ? frm.doc.name : '',
                                    row_idx: row_num,
                                    expense_head: final_head_to_save,
                                    custom_ledger_name: custom_val
                                },
                                freeze: true,
                                freeze_message: __('Updating Expenses of Head...'),
                                callback: function (res) {
                                    if (res.message && res.message.status === 'success') {
                                        // 1. Update active memory model
                                        active_att.expense_head = final_head_to_save;
                                        active_att.custom_ledger_name = custom_val;

                                        // 2. Update top header badge text
                                        $main_content.find('.ap-active-head-text').text(final_head_to_save);

                                        // 3. Update left sidebar thumbnail subtitle
                                        const $thumb = $sidebar.find(`.ap-receipt-thumb-item[data-idx="${current_index}"]`);
                                        $thumb.find('.ap-thumb-category-text').text(final_head_to_save);

                                        // 4. Update underlying Desk form grid model if accessible
                                        if (frm && frm.doc) {
                                            const lines = frm.doc.expense_lines || frm.doc.vendor_lines || frm.doc.expense_items || [];
                                            const r = lines.find(x => x.idx === row_num);
                                            if (r) {
                                                r.expense_head = final_head_to_save;
                                                if (custom_val) r.custom_ledger_name = custom_val;
                                                if (frm.fields_dict['expense_lines']) frm.refresh_field('expense_lines');
                                                if (frm.fields_dict['vendor_lines']) frm.refresh_field('vendor_lines');
                                            }
                                        }

                                        frappe.show_alert({
                                            message: __(`✅ Row #${row_num} Expenses of Head updated to <b>${final_head_to_save}</b>`),
                                            indicator: 'green'
                                        }, 4);
                                    }
                                }
                            });
                        }
                    });

                    edit_head_dialog.show();
                }
            });
        });

        // In-Modal Expense Type Editor (1-Click Dynamic Master Update)
        $main_content.off('click', '.ap-btn-edit-type').on('click', '.ap-btn-edit-type', function (e) {
            e.stopPropagation();
            const active_att = attachments[current_index];
            const current_type = active_att.category || '';
            const row_num = active_att.row_idx || (current_index + 1);
            const dt = (frm && frm.doc && frm.doc.doctype) ? frm.doc.doctype : 'Petty Cash Entry';
            const dn = (frm && frm.doc && frm.doc.name) ? frm.doc.name : '';

            let module_scope = 'All';
            if (dt === 'Petty Cash Entry') module_scope = 'Petty Cash';
            else if (dt === 'Admin Weekly Vendor Claim') module_scope = 'Admin Weekly Vendor Claims';
            else if (dt === 'Event Expense Claim') module_scope = 'Events';
            else if (dt === 'Employee Reimbursement Claim') module_scope = 'Employee Reimbursements';

            if (window.APExpenseTypeManager && typeof window.APExpenseTypeManager.openEditRowTypePrompt === 'function') {
                window.APExpenseTypeManager.openEditRowTypePrompt(dt, dn, row_num, current_type, module_scope, function (new_type) {
                    active_att.category = new_type;
                    $main_content.find('.ap-active-type-text').text(new_type);

                    const $thumb = $sidebar.find(`.ap-receipt-thumb-item[data-idx="${current_index}"]`);
                    if (!active_att.expense_head) {
                        $thumb.find('.ap-thumb-category-text').text(new_type);
                    }

                    if (frm && frm.doc) {
                        const lines = frm.doc.expense_lines || frm.doc.vendor_lines || frm.doc.expense_items || frm.doc.reimbursement_lines || [];
                        const r = lines.find(x => x.idx === row_num);
                        if (r) {
                            if (r.expense_category !== undefined) r.expense_category = new_type;
                            if (r.vendor_category !== undefined) r.vendor_category = new_type;
                            if (r.expense_type !== undefined) r.expense_type = new_type;
                            if (frm.fields_dict['expense_lines']) frm.refresh_field('expense_lines');
                            if (frm.fields_dict['vendor_lines']) frm.refresh_field('vendor_lines');
                            if (frm.fields_dict['expense_items']) frm.refresh_field('expense_items');
                            if (frm.fields_dict['reimbursement_lines']) frm.refresh_field('reimbursement_lines');
                        }
                    }
                });
            }
        });

        // In-Modal Receipt Upload & Replace
        $main_content.off('click', '.ap-btn-replace-receipt').on('click', '.ap-btn-replace-receipt', function (e) {
            e.stopPropagation();
            const active_att = attachments[current_index];
            new frappe.ui.FileUploader({
                folder: 'Home/Attachments',
                doctype: frm.doc.doctype,
                docname: frm.doc.name,
                fieldname: 'expense_lines',
                on_success: (file_doc) => {
                    const table_name = frm.doc.doctype === 'Petty Cash Entry' ? 'expense_lines' : (frm.doc.doctype === 'Admin Weekly Vendor Claim' ? 'vendor_lines' : 'claim_items');
                    const lines = frm.doc[table_name] || [];
                    const row_num = active_att.row_idx || (current_index + 1);
                    const row = lines.find(x => x.idx === row_num) || lines[current_index] || lines[0];
                    if (row) {
                        const target_field = row.receipt_attachment !== undefined ? 'receipt_attachment' : (row.attach_receipt !== undefined ? 'attach_receipt' : 'attachment');
                        frappe.model.set_value(row.doctype, row.name, target_field, file_doc.file_url);
                        active_att.file_url = file_doc.file_url;
                        active_att.view_url = self.buildViewUrl(frm, file_doc.file_url);
                        if (frm.fields_dict[table_name]) frm.refresh_field(table_name);
                        render_active_preview();
                        frappe.show_alert({ message: __('Receipt updated successfully!'), indicator: 'green' });
                    }
                }
            });
        });


        // Helper to select an item with zero scroll reset
        const select_item = (idx, smooth_scroll_if_needed = false) => {
            current_index = idx;

            // Highlight selected item in sidebar without touching scroll
            $sidebar.find('.ap-receipt-thumb-item').removeClass('ap-selected-row').css({
                'background': '#ffffff',
                'border': '1px solid #e2e8f0',
                'box-shadow': 'none'
            });

            const $card = $sidebar.find(`.ap-receipt-thumb-item[data-idx="${idx}"]`);
            $card.addClass('ap-selected-row').css({
                'background': '#ede9fe',
                'border': '2px solid #8b5cf6',
                'box-shadow': '0 2px 8px rgba(139, 92, 246, 0.25)'
            });

            // Smooth scroll into view ONLY if required by keyboard nav
            if (smooth_scroll_if_needed && $card.length && $card[0].scrollIntoView) {
                $card[0].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            }

            render_active_preview();
        };

        // Thumbnail Click: Preserves Left Sidebar Scroll Position 100%
        $sidebar.on('click', '.ap-receipt-thumb-item', function () {
            const idx = parseInt($(this).attr('data-idx'));
            // DO NOT TOUCH $sidebar.scrollTop() -> USER'S VIEWPORT REMAINS LOCKED
            select_item(idx, false);
        });

        // Keyboard Arrow Navigation
        $(document).on('keydown.ap_gallery', function (e) {
            if (!d.$wrapper.is(':visible')) return;
            if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
                e.preventDefault();
                if (current_index < attachments.length - 1) {
                    select_item(current_index + 1, true);
                }
            } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
                e.preventDefault();
                if (current_index > 0) {
                    select_item(current_index - 1, true);
                }
            }
        });

        // Clean up global listeners when dialog closes
        d.on_hide = function () {
            $(document).off('.ap_gallery');
        };

        // ZIP All Download
        $wrapper.on('click', '.ap-btn-download-all', function () {
            const dt = (frm && frm.doc && frm.doc.doctype) ? frm.doc.doctype : '';
            const dn = (frm && frm.doc && frm.doc.name) ? frm.doc.name : '';
            const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(dt)}&docname=${encodeURIComponent(dn)}`;
            window.location.href = url;
        });

        // Initial render
        d.show();
        render_active_preview();

        // Scroll initial item into view if starting beyond row 0 (e.g. Row #30 clicked from desk table)
        if (current_index > 0) {
            setTimeout(() => {
                const $initial_item = $sidebar.find(`.ap-receipt-thumb-item[data-idx="${current_index}"]`);
                if ($initial_item.length && $initial_item[0].scrollIntoView) {
                    $initial_item[0].scrollIntoView({ block: 'center', behavior: 'auto' });
                }
            }, 60);
        }
    }
};
