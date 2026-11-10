/**
 * AP Automation - Universal Receipt & Audit Gallery Manager
 * Features:
 * 1. Bank-grade In-Tab Modal Lightbox with Zero Scroll Jump
 * 2. De-duplicated Sidebar: Exactly 1 card per line item (Never duplicate "Row #1")
 * 3. Multi-Proof Support: Segmented tabs for Bill, GPay/UPI Proof, and Additional Supporting Docs
 * 4. ⊞ Side-by-Side View: View Invoice and GPay Proof side-by-side for instant audit comparison
 * 5. Smooth Stepper Navigation: [ ◀ Prev Row ] [ Row X of Y ] [ Next Row ▶ ]
 * 6. Floating Edge Arrows: Click [‹] and [›] on viewport edges to glide through 60+ rows smoothly
 * 7. Keyboard Navigation (← and →) with Auto-Scrolling Sidebar
 * 8. Interactive Zoom (50%-400%), Rotate, Pan & High-Fidelity Local PDF.js Multi-Page Viewer
 * 9. In-Modal 1-Click Editing: Expense Head, Expense Type, and In-Place Receipt Replace
 * Active across ALL AP DocTypes (Petty Cash, Reimbursements, Vendor Invoices, Admin Weekly Claims, Events).
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
            const head = row.expense_head || row.head_of_expense || '';
            const cat = row.expense_category || row.category || row.expense_type || 'General Expense';
            const smart_title = self.sanitizeMerchantTitle(row.merchant_name || row.merchant, head, cat);
            const amt = parseFloat(row.amount || row.claim_amount || 0.0);
            const dt = row.expense_date || row.date || frm.doc.posting_date || '';
            const b_no = row.bill_number || row.bill_no || row.invoice_number || '';
            const v_name = row.vendor_name || row.vendor || row.merchant_name || '';

            // 1.1 Primary Bill / Tax Invoice
            const file_url = row.attach_receipt || row.receipt_attachment || row.attachment || row.tax_invoice_attachment || row.bill_attachment;
            if (file_url && typeof file_url === 'string' && file_url.trim()) {
                const clean_url = file_url.trim();
                const file_name = clean_url.split('/').pop().split('?')[0];
                const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
                atts.push({
                    source: 'row',
                    field_source: 'receipt_attachment',
                    proof_type: 'bill',
                    proof_label: '🧾 1. Tax Invoice / Bill',
                    row_idx: row.idx || (idx + 1),
                    merchant: smart_title,
                    subtitle: row.merchant_name || '',
                    vendor: v_name,
                    vendor_name: v_name,
                    category: cat,
                    expense_head: head,
                    custom_ledger_name: row.custom_ledger_name || '',
                    description: row.description || row.remarks || row.particulars || '',
                    amount: amt,
                    date: dt,
                    bill_no: b_no,
                    file_url: clean_url,
                    view_url: self.buildViewUrl(frm, clean_url),
                    file_name: file_name,
                    is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext),
                    is_pdf: ext === '.pdf',
                    extension: ext
                });
            }

            // 1.2 In-row Payment Proof (Google Pay / UPI / Card Slip)
            const pay_url = row.payment_proof_attachment;
            if (pay_url && typeof pay_url === 'string' && pay_url.trim()) {
                const clean_pay = pay_url.trim();
                const pay_name = clean_pay.split('/').pop().split('?')[0];
                const pay_ext = (pay_name.lastIndexOf('.') !== -1 ? pay_name.substring(pay_name.lastIndexOf('.')).toLowerCase() : '');
                atts.push({
                    source: 'row',
                    field_source: 'payment_proof_attachment',
                    proof_type: 'payment',
                    proof_label: '💳 2. Payment Proof (GPay/UPI)',
                    row_idx: row.idx || (idx + 1),
                    merchant: smart_title,
                    subtitle: `Payment Proof • ${row.payment_mode_used || 'UPI / Online'}`,
                    vendor: v_name,
                    vendor_name: v_name,
                    category: 'Payment Confirmation (GPay/UPI)',
                    expense_head: head || 'Payment Proof',
                    custom_ledger_name: row.custom_ledger_name || '',
                    description: `Payment Proof / GPay screenshot for Row #${row.idx || (idx + 1)} (${smart_title})`,
                    amount: amt,
                    date: dt,
                    bill_no: b_no,
                    file_url: clean_pay,
                    view_url: self.buildViewUrl(frm, clean_pay),
                    file_name: pay_name,
                    is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(pay_ext),
                    is_pdf: pay_ext === '.pdf',
                    extension: pay_ext
                });
            }

            // 1.3 In-row Additional Bill / Page 2 Proof
            const add_url = row.additional_proof_attachment;
            if (add_url && typeof add_url === 'string' && add_url.trim()) {
                const clean_add = add_url.trim();
                const add_name = clean_add.split('/').pop().split('?')[0];
                const add_ext = (add_name.lastIndexOf('.') !== -1 ? add_name.substring(add_name.lastIndexOf('.')).toLowerCase() : '');
                atts.push({
                    source: 'row',
                    field_source: 'additional_proof_attachment',
                    proof_type: 'extra',
                    proof_label: '📎 3. Additional Proof',
                    row_idx: row.idx || (idx + 1),
                    merchant: smart_title,
                    subtitle: 'Additional Bill / Page 2',
                    vendor: v_name,
                    vendor_name: v_name,
                    category: 'Additional Supporting Proof',
                    expense_head: head || 'Supporting Document',
                    custom_ledger_name: row.custom_ledger_name || '',
                    description: `Additional Supporting Document for Row #${row.idx || (idx + 1)} (${smart_title})`,
                    amount: amt,
                    date: dt,
                    bill_no: b_no,
                    file_url: clean_add,
                    view_url: self.buildViewUrl(frm, clean_add),
                    file_name: add_name,
                    is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(add_ext),
                    is_pdf: add_ext === '.pdf',
                    extension: add_ext
                });
            }
        });

        // 2. Client Visit Legs (Reimbursements)
        (frm.doc.client_visit_legs || []).forEach((leg, idx) => {
            const travel_title = leg.client_name ? `${leg.client_name} (${leg.mode_of_travel || 'Travel'})` : 'Client Travel';
            const route_cat = (leg.from_location && leg.to_location) ? `Route: ${leg.from_location} → ${leg.to_location}` : 'Travel Proof';
            const leg_amt = parseFloat(leg.leg_amount || 0.0) + parseFloat(leg.toll_parking_amount || 0.0);
            const leg_dt = leg.visit_date || leg.travel_date || frm.doc.posting_date || '';

            // 2.1 Primary Travel Ticket / Bill
            const file_url = leg.receipt_attachment || leg.attachment;
            if (file_url && typeof file_url === 'string' && file_url.trim()) {
                const clean_url = file_url.trim();
                const file_name = clean_url.split('/').pop().split('?')[0];
                const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');
                atts.push({
                    source: 'row',
                    field_source: 'receipt_attachment',
                    proof_type: 'bill',
                    proof_label: '🧾 1. Travel Ticket / Bill',
                    row_idx: leg.idx || (idx + 1),
                    merchant: travel_title,
                    subtitle: leg.client_name || '',
                    vendor: leg.client_name || '',
                    vendor_name: leg.client_name || '',
                    category: route_cat,
                    expense_head: 'TRAVEL EXPENSES',
                    description: leg.purpose_of_visit || leg.description || '',
                    amount: leg_amt,
                    date: leg_dt,
                    bill_no: String(leg.idx || idx + 1),
                    file_url: clean_url,
                    view_url: self.buildViewUrl(frm, clean_url),
                    file_name: file_name,
                    is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext),
                    is_pdf: ext === '.pdf',
                    extension: ext
                });
            }

            // 2.2 Leg Payment Proof / GPay
            const leg_pay = leg.payment_proof_attachment;
            if (leg_pay && typeof leg_pay === 'string' && leg_pay.trim()) {
                const clean_pay = leg_pay.trim();
                const pay_name = clean_pay.split('/').pop().split('?')[0];
                const pay_ext = (pay_name.lastIndexOf('.') !== -1 ? pay_name.substring(pay_name.lastIndexOf('.')).toLowerCase() : '');
                atts.push({
                    source: 'row',
                    field_source: 'payment_proof_attachment',
                    proof_type: 'payment',
                    proof_label: '💳 2. Payment Proof (GPay/UPI)',
                    row_idx: leg.idx || (idx + 1),
                    merchant: travel_title,
                    subtitle: `GPay Travel Proof • ${leg.mode_of_travel || 'Travel'}`,
                    vendor: leg.client_name || '',
                    vendor_name: leg.client_name || '',
                    category: 'Payment Confirmation (GPay/UPI)',
                    expense_head: 'TRAVEL EXPENSES',
                    custom_ledger_name: '',
                    description: `Payment Proof / GPay for Travel Leg #${leg.idx || (idx + 1)}`,
                    amount: leg_amt,
                    date: leg_dt,
                    bill_no: String(leg.idx || idx + 1),
                    file_url: clean_pay,
                    view_url: self.buildViewUrl(frm, clean_pay),
                    file_name: pay_name,
                    is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(pay_ext),
                    is_pdf: pay_ext === '.pdf',
                    extension: pay_ext
                });
            }

            // 2.3 Leg Additional Proof
            const leg_add = leg.additional_proof_attachment;
            if (leg_add && typeof leg_add === 'string' && leg_add.trim()) {
                const clean_add = leg_add.trim();
                const add_name = clean_add.split('/').pop().split('?')[0];
                const add_ext = (add_name.lastIndexOf('.') !== -1 ? add_name.substring(add_name.lastIndexOf('.')).toLowerCase() : '');
                atts.push({
                    source: 'row',
                    field_source: 'additional_proof_attachment',
                    proof_type: 'extra',
                    proof_label: '📎 3. Additional Travel Proof',
                    row_idx: leg.idx || (idx + 1),
                    merchant: travel_title,
                    subtitle: 'Additional Travel Document',
                    vendor: leg.client_name || '',
                    vendor_name: leg.client_name || '',
                    category: 'Additional Supporting Proof',
                    expense_head: 'TRAVEL EXPENSES',
                    custom_ledger_name: '',
                    description: `Additional Travel Proof for Leg #${leg.idx || (idx + 1)}`,
                    amount: leg_amt,
                    date: leg_dt,
                    bill_no: String(leg.idx || idx + 1),
                    file_url: clean_add,
                    view_url: self.buildViewUrl(frm, clean_add),
                    file_name: add_name,
                    is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(add_ext),
                    is_pdf: add_ext === '.pdf',
                    extension: add_ext
                });
            }
        });

        // 3. Child tables for Admin Claims, Events & Items
        ['lines', 'items', 'instructions', 'expense_items', 'imprest_items', 'vendor_lines'].forEach(table_field => {
            const rows = frm.doc[table_field] || [];
            rows.forEach((row, idx) => {
                const raw_v = row.vendor_name || row.beneficiary_name || row.vendor || row.merchant_name || row.merchant || '';
                const head = row.expense_head || row.vendor_category || row.head_of_expense || '';
                const cat = row.vendor_category || row.category || row.expense_category || row.expense_type || row.spend_stream || 'Expense Line';
                const raw_m = raw_v || row.particulars;
                const smart_title = self.sanitizeMerchantTitle(raw_m, head, cat);
                const amt = parseFloat(row.amount || row.total_invoice_amount || row.base_amount || 0.0);
                const dt = row.invoice_date || row.expense_date || row.bill_date || frm.doc.posting_date || '';
                const b_no = row.invoice_number || row.bill_number || row.bill_no || '';

                const file_url = row.attach_receipt || row.receipt_attachment || row.attachment || row.quote_attachment || row.tax_invoice_attachment;
                if (file_url && typeof file_url === 'string' && file_url.trim()) {
                    const clean_url = file_url.trim();
                    const file_name = clean_url.split('/').pop().split('?')[0];
                    const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : '');

                    atts.push({
                        source: 'row',
                        field_source: 'receipt_attachment',
                        proof_type: 'bill',
                        proof_label: '🧾 1. Tax Invoice / Bill',
                        row_idx: row.idx || (idx + 1),
                        merchant: smart_title,
                        subtitle: raw_v || raw_m || '',
                        vendor: raw_v,
                        vendor_name: raw_v,
                        category: cat,
                        expense_head: head,
                        custom_ledger_name: row.custom_ledger_name || '',
                        description: row.description || row.remarks || row.particulars || row.discrepancy_remarks || '',
                        amount: amt,
                        date: dt,
                        bill_no: b_no,
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
                        field_source: 'bank_proof_attachment',
                        proof_type: 'bank',
                        proof_label: '🏦 Bank / Cheque Proof',
                        row_idx: row.idx || (idx + 1),
                        merchant: `Bank Cheque Proof — ${raw_v || 'Vendor'}`,
                        subtitle: raw_v || '',
                        vendor: raw_v,
                        vendor_name: raw_v,
                        category: 'Bank Account Proof (Cancelled Cheque)',
                        expense_head: 'Bank Details Verification',
                        custom_ledger_name: '',
                        description: `Cancelled Cheque / Passbook verification for ${raw_v} (A/C: ${row.bank_account_number || ''})`,
                        amount: amt,
                        date: dt,
                        bill_no: b_no,
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
            { field: 'tax_invoice_attachment', label: parent_vendor ? `Vendor Tax Invoice — ${parent_vendor}` : 'Vendor Tax Invoice', cat: 'Vendor Commercial Invoice', proof_type: 'bill' },
            { field: 'email_approval_attachment', label: 'Manager Email Approval Proof', cat: 'Audit Approval Proof', proof_type: 'approval' },
            { field: 'bank_proof_attachment', label: parent_vendor ? `Bank Cheque Proof — ${parent_vendor}` : 'Bank Account Proof (Cancelled Cheque / Passbook)', cat: 'Bank Details Verification', proof_type: 'bank' },
            { field: 'grn_attachment', label: 'Goods Receipt Note / Delivery Proof', cat: 'Warehouse Receipt', proof_type: 'grn' },
            { field: 'advance_receipt_attachment', label: 'Advance Payment Proof', cat: 'Bank Advance Proof', proof_type: 'payment' },
            { field: 'settlement_statement', label: 'Event Settlement Statement', cat: 'Event Settlement', proof_type: 'extra' },
            { field: 'activity_photo', label: '📸 Team Activity Photo Proof', cat: 'Team Engagement & Recreation', proof_type: 'photo' },
            { field: 'pre_approval_attachment', label: '📋 Pre-Approval Authorization Screenshot', cat: 'Audit Proof Document', proof_type: 'approval' }
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
                    field_source: pf.field,
                    proof_type: pf.proof_type || 'bill',
                    proof_label: pf.label,
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

    openModal: function (frm, attachments, start_idx, opts) {
        const self = this;
        opts = opts || {};
        if (!attachments || attachments.length === 0) {
            this.openEmptyModal(frm);
            return;
        }

        const is_batch_audit = Boolean(
            (frm && frm.doc && frm.doc.doctype === 'Weekly Accounts Audit Batch') || opts.batch_name
        );
        const batch_name = opts.batch_name || (frm && frm.doc && frm.doc.doctype === 'Weekly Accounts Audit Batch' ? frm.doc.name : '');
        const batch_items_meta = opts.batch_items_meta || {};
        const active_blob_urls = [];

        // 1. Normalize attachment objects from all callers & eliminate "nil"
        attachments = attachments.map((att, idx) => {
            const raw_url = (att.file_url || att.receipt_attachment || att.attach_receipt || '').trim();
            const file_name = att.file_name || (raw_url ? raw_url.split('/').pop().split('?')[0] : `receipt_${idx + 1}`);
            const ext = (file_name.lastIndexOf('.') !== -1 ? file_name.substring(file_name.lastIndexOf('.')).toLowerCase() : (att.extension || '')).toLowerCase();
            const is_img = att.is_image !== undefined ? att.is_image : ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext);
            const is_pdf = att.is_pdf !== undefined ? att.is_pdf : (ext === '.pdf' || raw_url.toLowerCase().includes('.pdf'));

            const claim_no = att.claim_name || (frm && frm.doc && frm.doc.doctype !== 'Weekly Accounts Audit Batch' ? frm.doc.name : '') || '';
            const b_meta = batch_items_meta[claim_no] || {};

            const head = is_batch_audit
                ? (att.expense_head !== undefined && att.expense_head !== null && att.expense_head !== '' ? att.expense_head : (b_meta.expense_head || ''))
                : (att.expense_head || att.head_of_expense || att.vendor_category || '');
            const cat = att.category || att.vendor_category || att.expense_category || '';
            const raw_v = att.vendor_name || att.vendor || att.beneficiary_name || (frm && frm.doc && (frm.doc.vendor_name || frm.doc.supplier_name || frm.doc.vendor || frm.doc.supplier)) || '';
            const raw_m = att.merchant || raw_v || att.particulars;
            const smart_title = self.sanitizeMerchantTitle(raw_m, head, cat);

            const resolved_doctype = att.claim_doctype || (is_batch_audit ? 'Employee Reimbursement Claim' : (frm && frm.doc ? frm.doc.doctype : ''));
            const resolved_docname = claim_no || (frm && frm.doc ? frm.doc.name : '');
            const safe_view_url = att.view_url || (raw_url ? `/api/method/ap_automation.services.attachment_service.view_receipt_file?file_url=${encodeURIComponent(raw_url)}&doctype=${encodeURIComponent(resolved_doctype)}&docname=${encodeURIComponent(resolved_docname)}` : '');

            const lower_m = (att.merchant || '').toLowerCase();
            const lower_cat = (cat || '').toLowerCase();
            let inferred_type = att.proof_type;
            if (!inferred_type) {
                if (lower_m.includes('payment proof') || lower_cat.includes('gpay/upi') || lower_cat.includes('payment confirmation')) {
                    inferred_type = 'payment';
                } else if (lower_m.includes('supporting proof') || lower_m.includes('additional') || lower_m.includes('cheque')) {
                    inferred_type = 'extra';
                } else {
                    inferred_type = 'bill';
                }
            }

            return {
                source: att.source || 'row',
                claim_name: claim_no,
                batch_name: att.batch_name || batch_name,
                jv_number: att.jv_number || b_meta.jv_number || '',
                jv_date: att.jv_date || b_meta.jv_date || '',
                field_source: att.field_source || 'receipt_attachment',
                proof_type: inferred_type,
                proof_label: att.proof_label || (inferred_type === 'payment' ? '💳 2. Payment Proof (GPay/UPI)' : (inferred_type === 'extra' ? '📎 3. Additional Proof' : '🧾 1. Tax Invoice / Bill')),
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
                view_url: safe_view_url,
                file_name: file_name,
                is_image: is_img,
                is_pdf: is_pdf,
                extension: ext
            };
        });

        // 2. Group attachments by line item + claim_name to DE-DUPLICATE sidebar (Strictly 1 card per row)
        const groups = [];
        const group_map = new Map();

        attachments.forEach((att) => {
            const claim_prefix = att.claim_name ? `${att.claim_name}_` : '';
            let key;
            if (att.source === 'row' && att.row_idx !== null && att.row_idx !== undefined) {
                key = `${claim_prefix}row_${att.row_idx}`;
            } else {
                key = `${claim_prefix}parent_${att.file_url || att.merchant}`;
            }

            if (!group_map.has(key)) {
                let clean_title = att.merchant;
                if (clean_title) {
                    clean_title = clean_title
                        .replace(/^Payment Proof \(GPay\/UPI\) — /i, '')
                        .replace(/^Payment Proof — /i, '')
                        .replace(/^Supporting Proof — /i, '')
                        .replace(/^Additional Travel Proof — /i, '')
                        .replace(/^Bank Cheque Proof — /i, '');
                }

                const g = {
                    key: key,
                    source: att.source,
                    claim_name: att.claim_name || '',
                    batch_name: att.batch_name || '',
                    jv_number: att.jv_number || '',
                    jv_date: att.jv_date || '',
                    row_idx: att.row_idx,
                    merchant: clean_title || att.merchant,
                    subtitle: att.subtitle,
                    vendor: att.vendor || att.vendor_name || '',
                    vendor_name: att.vendor_name || att.vendor || '',
                    category: att.category,
                    expense_head: att.expense_head,
                    custom_ledger_name: att.custom_ledger_name || '',
                    description: att.description,
                    amount: att.amount,
                    date: att.date,
                    bill_no: att.bill_no,
                    proofs: []
                };
                group_map.set(key, g);
                groups.push(g);
            }

            const g = group_map.get(key);
            if (!g.vendor && (att.vendor || att.vendor_name)) {
                g.vendor = att.vendor || att.vendor_name;
                g.vendor_name = g.vendor;
            }
            if (!g.category && att.category) g.category = att.category;
            if (!g.expense_head && att.expense_head) g.expense_head = att.expense_head;
            if (!g.description && att.description) g.description = att.description;
            if (!g.jv_number && att.jv_number) g.jv_number = att.jv_number;
            if (!g.jv_date && att.jv_date) g.jv_date = att.jv_date;

            let label = att.proof_label;
            if (!label) {
                if (att.proof_type === 'payment') label = '💳 2. Payment Proof (GPay/UPI)';
                else if (att.proof_type === 'extra') label = '📎 3. Additional Proof';
                else if (g.proofs.length === 0) label = '🧾 1. Tax Invoice / Bill';
                else label = `📎 Proof #${g.proofs.length + 1}`;
            }

            g.proofs.push({
                ...att,
                proof_label: label,
                proof_type: att.proof_type || (g.proofs.length === 0 ? 'bill' : 'extra')
            });
        });

        // 3. Determine start indices
        start_idx = start_idx || 0;
        let current_group_idx = 0;
        if (start_idx > 0) {
            const found = groups.findIndex(g => g.row_idx === (start_idx + 1) || g.row_idx === start_idx);
            current_group_idx = found !== -1 ? found : Math.min(start_idx, groups.length - 1);
        }
        let active_proof_idx = 0;
        let is_side_by_side = false;

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

        // Zoom, Pan & Rotation State for active viewer
        let zoom_level = 1.0;
        let rotation_deg = 0;
        let pan_x = 0;
        let pan_y = 0;
        let is_dragging = false;
        let start_drag_x = 0;
        let start_drag_y = 0;

        // Build Left Thumbnail List HTML ONCE (Permanent DOM - never duplicate rows)
        const distinct_claims = new Set(groups.map(g => g.claim_name).filter(Boolean));
        const multi_claim_mode = is_batch_audit && distinct_claims.size > 1;
        let thumb_items_html = '';
        groups.forEach((group, g_idx) => {
            const is_selected = g_idx === current_group_idx;
            const item_date_formatted = self.formatDate(group.date);
            const v_name = group.vendor_name || group.vendor || '';
            const row_title = (group.row_idx ? `Row #${group.row_idx}: ` : '') + (is_batch_audit ? (group.merchant || v_name || 'Expense') : (v_name ? v_name : (group.merchant || 'Expense')));
            const proof_count = group.proofs.length;
            const thumb_subtext = is_batch_audit
                ? (group.expense_head || 'Unclassified')
                : (v_name ? '🏢 ' + v_name : (group.expense_head || group.category || ''));

            thumb_items_html += `
                <div class="ap-receipt-thumb-item ${is_selected ? 'ap-selected-row' : ''}" data-gidx="${g_idx}" data-claim="${group.claim_name || ''}" style="
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 10px 12px;
                    margin-bottom: 8px;
                    border-radius: 8px;
                    cursor: pointer;
                    transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
                    background: ${is_selected ? '#ede9fe' : '#ffffff'};
                    border: ${is_selected ? '2px solid #8b5cf6' : '1px solid #e2e8f0'};
                    box-shadow: ${is_selected ? '0 2px 8px rgba(139, 92, 246, 0.25)' : 'none'};
                ">
                    <div style="font-size: 22px; flex-shrink: 0;">${group.proofs[0] && group.proofs[0].is_pdf ? '📄' : '🧾'}</div>
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
                        ${multi_claim_mode ? `
                            <div style="font-size: 10.5px; font-weight: 700; color: #0369a1; margin-top: 2px;">${group.claim_name}</div>
                        ` : ''}
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px; gap: 8px;">
                            <span style="font-size: 12px; font-weight: 700; color: #059669; flex-shrink: 0;">${self.formatINR(group.amount)}</span>
                            <div style="display: flex; align-items: center; gap: 4px; overflow: hidden;">
                                ${proof_count > 1 ? `
                                    <span class="badge" style="font-size: 10px; font-weight: 700; background: #ede9fe; color: #6d28d9; border: 1px solid #c4b5fd; padding: 1px 5px; border-radius: 4px; white-space: nowrap; flex-shrink: 0;">
                                        ${proof_count} Proofs
                                    </span>
                                ` : ''}
                                <span class="ap-thumb-category-text" style="font-size: 11px; color: #64748b; white-space: nowrap; text-overflow: ellipsis; overflow: hidden;" title="${thumb_subtext}">
                                    ${thumb_subtext}
                                </span>
                            </div>
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
                            Attached Lines (${groups.length})
                        </span>
                        <button class="btn btn-xs btn-default ap-btn-download-all" style="font-size: 11px; font-weight: 600; color: #4f46e5;">
                            📦 ZIP All (${attachments.length})
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

        // Function to render active row & proof in the right pane ONLY
        const render_active_preview = () => {
            const active_group = groups[current_group_idx];
            if (!active_group) return;

            const active_date_formatted = self.formatDate(active_group.date);
            const active_vendor = active_group.vendor_name || active_group.vendor || (frm && frm.doc && (frm.doc.vendor_name || frm.doc.supplier_name || frm.doc.vendor || frm.doc.supplier)) || '';
            const header_title = (active_group.row_idx ? `Row #${active_group.row_idx}: ` : '') + (active_vendor ? `🏢 ${active_vendor}` : (active_group.merchant || 'Expense'));
            const proof_count = active_group.proofs.length;

            if (active_proof_idx >= proof_count) active_proof_idx = 0;
            const active_att = active_group.proofs[active_proof_idx] || active_group.proofs[0];
            const target_url = active_att.view_url || active_att.file_url;

            // Reset zoom & pan for newly selected receipt
            zoom_level = 1.0;
            rotation_deg = 0;
            pan_x = 0;
            pan_y = 0;
            is_dragging = false;

            // 1. Build Multi-Proof Segmented Tab Bar if this row has > 1 proof
            let proof_tabs_html = '';
            if (proof_count > 1) {
                const proof_buttons = active_group.proofs.map((p, p_idx) => {
                    const is_active_pill = (!is_side_by_side && active_proof_idx === p_idx);
                    return `
                        <button type="button" class="btn btn-xs ap-btn-select-proof ${is_active_pill ? 'active' : ''}" data-pidx="${p_idx}" style="font-weight: 700; font-size: 11.5px; padding: 4px 10px; border-radius: 6px; border: 1.5px solid ${is_active_pill ? '#8b5cf6' : '#cbd5e1'}; background: ${is_active_pill ? '#ede9fe' : '#ffffff'}; color: ${is_active_pill ? '#6d28d9' : '#475569'}; cursor: pointer; transition: all 0.15s ease;">
                            ${p.proof_label}
                        </button>
                    `;
                }).join('');

                proof_tabs_html = `
                    <div class="ap-proof-segmented-tabs" style="display: flex; align-items: center; justify-content: space-between; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 6px 12px; margin-bottom: 12px; gap: 8px; flex-wrap: wrap;">
                        <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                            <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-right: 4px;">
                                Proofs for Row #${active_group.row_idx || (current_group_idx + 1)}:
                            </span>
                            ${proof_buttons}
                        </div>
                        <button type="button" class="btn btn-xs ap-btn-toggle-sidebyside ${is_side_by_side ? 'active' : ''}" style="font-weight: 700; font-size: 11.5px; padding: 4px 12px; border-radius: 6px; border: 1.5px solid ${is_side_by_side ? '#059669' : '#cbd5e1'}; background: ${is_side_by_side ? '#ecfdf5' : '#ffffff'}; color: ${is_side_by_side ? '#047857' : '#334155'}; cursor: pointer; display: flex; align-items: center; gap: 5px;">
                            <span style="font-size: 13px;">⊞</span> <b>Side-by-Side View</b>
                        </button>
                    </div>
                `;
            }

            // 2. Build Viewport (Side-by-Side vs Single View)
            let preview_content = '';
            if (is_side_by_side && proof_count >= 2) {
                const proof_left = active_group.proofs[0];
                const proof_right = active_group.proofs[active_proof_idx > 0 ? active_proof_idx : 1];

                preview_content = `
                    <div class="ap-sidebyside-container" style="display: flex; gap: 12px; height: 570px; position: relative;">
                        <!-- Left Column: Primary Bill / Proof 1 -->
                        <div class="ap-sbs-col" style="flex: 1; display: flex; flex-direction: column; background: #0f172a; border-radius: 8px; overflow: hidden; border: 1px solid #334155;">
                            <div class="ap-sbs-col-header" style="display: flex; justify-content: space-between; align-items: center; background: #1e293b; padding: 6px 12px; border-bottom: 1px solid #334155;">
                                <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
                                    <span style="font-size: 12px; font-weight: 700; color: #f8fafc; white-space: nowrap;">${proof_left.proof_label}</span>
                                    <span style="font-size: 11px; color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 150px;">(${proof_left.file_name})</span>
                                </div>
                                <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0;">
                                    <a href="${proof_left.view_url || proof_left.file_url}" download="${proof_left.file_name}" class="btn btn-xs btn-default" style="font-size: 11px; padding: 2px 7px;">⬇️ Download</a>
                                    <a href="${proof_left.view_url || proof_left.file_url}" target="_blank" class="btn btn-xs btn-default" style="font-size: 11px; padding: 2px 6px;" title="Open Full in New Tab">↗️</a>
                                </div>
                            </div>
                            <div class="ap-sbs-viewport" style="flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; padding: 12px; position: relative;">
                                ${proof_left.is_image ? `
                                    <img src="${proof_left.view_url || proof_left.file_url}" alt="${proof_left.file_name}" style="max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 4px; box-shadow: 0 2px 10px rgba(0,0,0,0.5);" />
                                ` : (proof_left.is_pdf ? `
                                    <div class="ap-sbs-pdf-left ap-pdf-pages-mount" style="width: 100%; height: 100%; overflow: auto; display: flex; flex-direction: column; align-items: center; gap: 10px;">
                                        <div style="color: #94a3b8; font-size: 12px; padding: 30px;">⏳ Loading PDF...</div>
                                    </div>
                                ` : `
                                    <div style="color: #94a3b8; text-align: center;">${proof_left.file_name}</div>
                                `)}
                            </div>
                        </div>

                        <!-- Right Column: Secondary Proof / GPay / Extra -->
                        <div class="ap-sbs-col" style="flex: 1; display: flex; flex-direction: column; background: #0f172a; border-radius: 8px; overflow: hidden; border: 1px solid #334155;">
                            <div class="ap-sbs-col-header" style="display: flex; justify-content: space-between; align-items: center; background: #1e293b; padding: 6px 12px; border-bottom: 1px solid #334155;">
                                <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
                                    <span style="font-size: 12px; font-weight: 700; color: #f8fafc; white-space: nowrap;">${proof_right.proof_label}</span>
                                    <span style="font-size: 11px; color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 150px;">(${proof_right.file_name})</span>
                                </div>
                                <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0;">
                                    <a href="${proof_right.view_url || proof_right.file_url}" download="${proof_right.file_name}" class="btn btn-xs btn-default" style="font-size: 11px; padding: 2px 7px;">⬇️ Download</a>
                                    <a href="${proof_right.view_url || proof_right.file_url}" target="_blank" class="btn btn-xs btn-default" style="font-size: 11px; padding: 2px 6px;" title="Open Full in New Tab">↗️</a>
                                </div>
                            </div>
                            <div class="ap-sbs-viewport" style="flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; padding: 12px; position: relative;">
                                ${proof_right.is_image ? `
                                    <img src="${proof_right.view_url || proof_right.file_url}" alt="${proof_right.file_name}" style="max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 4px; box-shadow: 0 2px 10px rgba(0,0,0,0.5);" />
                                ` : (proof_right.is_pdf ? `
                                    <div class="ap-sbs-pdf-right ap-pdf-pages-mount" style="width: 100%; height: 100%; overflow: auto; display: flex; flex-direction: column; align-items: center; gap: 10px;">
                                        <div style="color: #94a3b8; font-size: 12px; padding: 30px;">⏳ Loading PDF...</div>
                                    </div>
                                ` : `
                                    <div style="color: #94a3b8; text-align: center;">${proof_right.file_name}</div>
                                `)}
                            </div>
                        </div>

                        <!-- Floating Nav Arrows in SBS Mode -->
                        ${current_group_idx > 0 ? `
                            <button type="button" class="ap-nav-floating-prev" title="Previous Row (Row #${current_group_idx})" style="position: absolute; left: 14px; top: 50%; transform: translateY(-50%); width: 42px; height: 42px; border-radius: 50%; background: rgba(15, 23, 42, 0.75); color: #ffffff; border: 2px solid rgba(255, 255, 255, 0.4); font-size: 26px; line-height: 1; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 20; transition: all 0.2s; box-shadow: 0 4px 14px rgba(0,0,0,0.5);">
                                ‹
                            </button>
                        ` : ''}
                        ${current_group_idx < groups.length - 1 ? `
                            <button type="button" class="ap-nav-floating-next" title="Next Row (Row #${current_group_idx + 2})" style="position: absolute; right: 14px; top: 50%; transform: translateY(-50%); width: 42px; height: 42px; border-radius: 50%; background: rgba(15, 23, 42, 0.75); color: #ffffff; border: 2px solid rgba(255, 255, 255, 0.4); font-size: 26px; line-height: 1; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 20; transition: all 0.2s; box-shadow: 0 4px 14px rgba(0,0,0,0.5);">
                                ›
                            </button>
                        ` : ''}
                    </div>
                `;
            } else {
                // Single View
                if (active_att.is_image) {
                    preview_content = `
                        <div class="ap-image-viewport" style="display: flex; justify-content: center; align-items: center; background: #0f172a; border-radius: 8px; overflow: hidden; height: 570px; padding: 16px; position: relative; user-select: none; cursor: default;">
                            <img class="ap-preview-img" src="${target_url}" alt="${active_att.merchant}" style="max-width: 100%; max-height: 100%; object-fit: contain; box-shadow: 0 4px 20px rgba(0,0,0,0.5); border-radius: 4px; transform-origin: center center; transition: transform 0.15s ease;" 
                                 onerror="this.onerror=null; this.parentElement.innerHTML='<div style=\\'text-align: center; color: #f87171; padding: 40px;\\'> <div style=\\'font-size: 48px; margin-bottom: 12px;\\'>⚠️</div> <div style=\\'font-size: 16px; font-weight: 700;\\'>Receipt Image Not Found on Server</div> <div style=\\'font-size: 13px; color: #94a3b8; margin-top: 6px;\\'>File: <code>' + escape('${active_att.file_name}') + '</code></div> <div style=\\'font-size: 12px; color: #64748b; margin-top: 8px;\\'>The file path is registered, but the physical file is not present on disk.</div> </div>';" />

                            <!-- Floating Nav Arrows in Single View -->
                            ${current_group_idx > 0 ? `
                                <button type="button" class="ap-nav-floating-prev" title="Previous Row (Row #${current_group_idx})" style="position: absolute; left: 14px; top: 50%; transform: translateY(-50%); width: 42px; height: 42px; border-radius: 50%; background: rgba(15, 23, 42, 0.75); color: #ffffff; border: 2px solid rgba(255, 255, 255, 0.4); font-size: 26px; line-height: 1; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 20; transition: all 0.2s; box-shadow: 0 4px 14px rgba(0,0,0,0.5);">
                                    ‹
                                </button>
                            ` : ''}
                            ${current_group_idx < groups.length - 1 ? `
                                <button type="button" class="ap-nav-floating-next" title="Next Row (Row #${current_group_idx + 2})" style="position: absolute; right: 14px; top: 50%; transform: translateY(-50%); width: 42px; height: 42px; border-radius: 50%; background: rgba(15, 23, 42, 0.75); color: #ffffff; border: 2px solid rgba(255, 255, 255, 0.4); font-size: 26px; line-height: 1; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 20; transition: all 0.2s; box-shadow: 0 4px 14px rgba(0,0,0,0.5);">
                                    ›
                                </button>
                            ` : ''}
                        </div>
                    `;
                } else if (active_att.is_pdf) {
                    preview_content = `
                        <div class="ap-pdf-viewport" style="background: #0f172a; border-radius: 8px; overflow-y: auto; overflow-x: auto; height: 570px; padding: 16px; position: relative; text-align: center;">
                            <div class="ap-pdf-pages-mount" style="display: inline-flex; flex-direction: column; align-items: center; gap: 14px; min-width: 100%; transform-origin: top center; transition: transform 0.15s ease;">
                                <div class="ap-pdf-loading" style="color: #94a3b8; padding: 60px 20px; font-size: 13.5px;">
                                    <div style="font-size: 36px; margin-bottom: 10px;">📄</div>
                                    <div style="font-weight: 700; color: #f8fafc; font-size: 15px; margin-bottom: 4px;">Loading PDF Receipt Pages...</div>
                                    <div style="font-size: 12px; color: #94a3b8;">${active_att.file_name}</div>
                                </div>
                            </div>

                            <!-- Floating Nav Arrows in PDF View -->
                            ${current_group_idx > 0 ? `
                                <button type="button" class="ap-nav-floating-prev" title="Previous Row (Row #${current_group_idx})" style="position: absolute; left: 14px; top: 50%; transform: translateY(-50%); width: 42px; height: 42px; border-radius: 50%; background: rgba(15, 23, 42, 0.75); color: #ffffff; border: 2px solid rgba(255, 255, 255, 0.4); font-size: 26px; line-height: 1; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 20; transition: all 0.2s; box-shadow: 0 4px 14px rgba(0,0,0,0.5);">
                                    ‹
                                </button>
                            ` : ''}
                            ${current_group_idx < groups.length - 1 ? `
                                <button type="button" class="ap-nav-floating-next" title="Next Row (Row #${current_group_idx + 2})" style="position: absolute; right: 14px; top: 50%; transform: translateY(-50%); width: 42px; height: 42px; border-radius: 50%; background: rgba(15, 23, 42, 0.75); color: #ffffff; border: 2px solid rgba(255, 255, 255, 0.4); font-size: 26px; line-height: 1; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 20; transition: all 0.2s; box-shadow: 0 4px 14px rgba(0,0,0,0.5);">
                                    ›
                                </button>
                            ` : ''}
                        </div>
                    `;
                } else {
                    preview_content = `
                        <div style="text-align: center; padding: 80px 20px; background: #f8fafc; border-radius: 8px; border: 2px dashed #cbd5e1; height: 570px; display: flex; flex-direction: column; justify-content: center; align-items: center; position: relative;">
                            <div style="font-size: 48px; margin-bottom: 12px;">📁</div>
                            <div style="font-size: 16px; font-weight: 600; color: #1e293b;">${active_att.file_name}</div>
                            <div style="font-size: 13px; color: #64748b; margin-top: 6px;">Direct preview is not available for .${active_att.extension || 'file'} files.</div>
                            <a href="${active_att.file_url}" download class="btn btn-primary btn-sm" style="margin-top: 16px;">
                                ⬇️ Download File (${(active_att.extension || '').toUpperCase()})
                            </a>

                            ${current_group_idx > 0 ? `
                                <button type="button" class="ap-nav-floating-prev" title="Previous Row (Row #${current_group_idx})" style="position: absolute; left: 14px; top: 50%; transform: translateY(-50%); width: 42px; height: 42px; border-radius: 50%; background: rgba(15, 23, 42, 0.75); color: #ffffff; border: 2px solid rgba(255, 255, 255, 0.4); font-size: 26px; line-height: 1; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 20; transition: all 0.2s; box-shadow: 0 4px 14px rgba(0,0,0,0.5);">
                                    ‹
                                </button>
                            ` : ''}
                            ${current_group_idx < groups.length - 1 ? `
                                <button type="button" class="ap-nav-floating-next" title="Next Row (Row #${current_group_idx + 2})" style="position: absolute; right: 14px; top: 50%; transform: translateY(-50%); width: 42px; height: 42px; border-radius: 50%; background: rgba(15, 23, 42, 0.75); color: #ffffff; border: 2px solid rgba(255, 255, 255, 0.4); font-size: 26px; line-height: 1; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 20; transition: all 0.2s; box-shadow: 0 4px 14px rgba(0,0,0,0.5);">
                                    ›
                                </button>
                            ` : ''}
                        </div>
                    `;
                }
            }

            const is_vendor_claim = (frm && frm.doc && (frm.doc.doctype === 'Admin Weekly Vendor Claim' || frm.doc.doctype === 'Vendor Invoice Claim'));
            const is_event_claim = (frm && frm.doc && frm.doc.doctype === 'Event Expense Claim');
            const dynamic_category_label = is_vendor_claim ? 'Vendor Category' : (is_event_claim ? 'Expense Category' : 'Expense Type');

            const active_html = `
                <!-- Top Header Toolbar -->
                <div class="ap-gallery-toolbar" style="display: flex; justify-content: space-between; align-items: center; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; gap: 10px; flex-wrap: wrap;">
                    <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 8px;">
                        <!-- Stepper Row Navigation -->
                        <div class="ap-row-stepper" style="display: inline-flex; align-items: center; background: #ffffff; border: 1.5px solid #cbd5e1; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,0.05); margin-right: 4px;">
                            <button type="button" class="btn btn-xs ap-btn-prev-row" ${current_group_idx === 0 ? 'disabled' : ''} style="background: ${current_group_idx === 0 ? '#f8fafc' : '#ffffff'}; color: ${current_group_idx === 0 ? '#94a3b8' : '#1e293b'}; font-weight: 700; border: none; padding: 4px 10px; cursor: ${current_group_idx === 0 ? 'not-allowed' : 'pointer'};">
                                ◀ Prev Row
                            </button>
                            <span class="ap-stepper-counter" style="font-size: 11.5px; font-weight: 700; color: #475569; padding: 4px 10px; background: #f8fafc; border-left: 1px solid #e2e8f0; border-right: 1px solid #e2e8f0; min-width: 90px; text-align: center;">
                                Row ${current_group_idx + 1} of ${groups.length}
                            </span>
                            <button type="button" class="btn btn-xs ap-btn-next-row" ${current_group_idx === groups.length - 1 ? 'disabled' : ''} style="background: ${current_group_idx === groups.length - 1 ? '#f8fafc' : '#ffffff'}; color: ${current_group_idx === groups.length - 1 ? '#94a3b8' : '#1e293b'}; font-weight: 700; border: none; padding: 4px 10px; cursor: ${current_group_idx === groups.length - 1 ? 'not-allowed' : 'pointer'};">
                                Next Row ▶
                            </button>
                        </div>

                        <span class="ap-header-title-text" style="font-size: 13.5px; font-weight: 700; color: #0f172a;">
                            ${header_title}
                        </span>
                        ${active_date_formatted ? `
                            <span style="font-size: 11px; font-weight: 700; color: #3730a3; background: #e0e7ff; border: 1px solid #c7d2fe; padding: 2px 7px; border-radius: 4px;">
                                📅 ${active_date_formatted}
                            </span>
                        ` : ''}
                        <span style="font-size: 12px; color: #64748b;">
                            Amount: <b style="color: #059669; font-size: 13px;">${self.formatINR(active_group.amount)}</b>
                        </span>

                        ${(is_batch_audit && active_group.claim_name) ? `
                            <span style="font-size: 11px; font-weight: 700; color: #0369a1; background: #e0f2fe; border: 1px solid #bae6fd; padding: 2px 7px; border-radius: 4px;">
                                🧾 ${active_group.claim_name}
                            </span>
                        ` : ''}

                        <!-- Prominent Vendor Legal Name Pill (Standard Claim Forms Only) -->
                        ${(!is_batch_audit && active_vendor) ? `
                            <div class="ap-vendor-badge-pill" style="display: inline-flex; align-items: center; background: #fffbeb; border: 1.5px solid #fcd34d; border-radius: 6px; padding: 2px 8px; gap: 4px;" title="Vendor Legal Name">
                                <span style="font-size: 11px; font-weight: 700; color: #92400e;">
                                    🏢 <b class="ap-active-vendor-text" style="color: #78350f; font-weight: 800;">${active_vendor}</b>
                                </span>
                            </div>
                        ` : ''}

                        <!-- In-Modal Head Pill (Present on Both, Syncs Batch Table in Batch Mode) -->
                        <div class="ap-head-badge-pill" style="display: inline-flex; align-items: center; background: #eff6ff; border: 1.5px solid #93c5fd; border-radius: 6px; padding: 2px 8px; gap: 6px;">
                            <span style="font-size: 11px; font-weight: 700; color: #1e40af;">
                                💼 Expense Head: <span class="ap-active-head-text">${active_group.expense_head || 'Unassigned'}</span>
                            </span>
                            <button type="button" class="btn btn-xs btn-default ap-btn-edit-head" title="Edit Expenses of Head" style="font-size: 10px; font-weight: 700; color: #1d4ed8; padding: 1px 6px; border: 1px solid #bfdbfe; background: #ffffff; border-radius: 4px; cursor: pointer;">
                                ✏️ Edit
                            </button>
                        </div>

                        <!-- In-Modal JV # Pill (Batch Audit Mode Only) -->
                        ${is_batch_audit ? `
                            <div class="ap-jv-badge-pill" style="display: inline-flex; align-items: center; background: #f0fdf4; border: 1.5px solid #86efac; border-radius: 6px; padding: 2px 8px; gap: 6px;">
                                <span style="font-size: 11px; font-weight: 700; color: #166534;">
                                    📝 JV #: <span class="ap-active-jv-text">${active_group.jv_number ? active_group.jv_number + (active_group.jv_date ? ' (' + self.formatDate(active_group.jv_date) + ')' : '') : 'Unassigned'}</span>
                                </span>
                                <button type="button" class="btn btn-xs btn-default ap-btn-edit-jv" title="Set / Edit JV Number & Date" style="font-size: 10px; font-weight: 700; color: #15803d; padding: 1px 6px; border: 1px solid #bbf7d0; background: #ffffff; border-radius: 4px; cursor: pointer;">
                                    ✏️ Edit
                                </button>
                            </div>
                        ` : `
                            <!-- In-Modal Type Pill (Standard Forms Only) -->
                            <div class="ap-type-badge-pill" style="display: inline-flex; align-items: center; background: #ecfdf5; border: 1.5px solid #a7f3d0; border-radius: 6px; padding: 2px 8px; gap: 6px;">
                                <span style="font-size: 11px; font-weight: 700; color: #047857;">
                                    🏷️ ${dynamic_category_label}: <span class="ap-active-type-text">${active_group.category || (is_vendor_claim ? 'General Vendor Claim' : 'General Expense')}</span>
                                </span>
                                <button type="button" class="btn btn-xs btn-default ap-btn-edit-type" title="Edit ${dynamic_category_label} for this row" style="font-size: 10px; font-weight: 700; color: #047857; padding: 1px 6px; border: 1px solid #a7f3d0; background: #ffffff; border-radius: 4px; cursor: pointer;">
                                    ✏️ Edit
                                </button>
                            </div>

                            <!-- In-Modal Upload / Replace Receipt Button (Standard Forms Only) -->
                            <button type="button" class="btn btn-xs btn-default ap-btn-replace-receipt" title="Upload new / replace receipt proof" style="font-size: 10.5px; font-weight: 700; color: #b45309; padding: 2px 8px; border: 1.5px solid #fde68a; background: #fffbeb; border-radius: 6px; cursor: pointer;">
                                📷 Upload / Replace
                            </button>
                        `}

                        ${active_group.description ? `
                            <span style="font-size: 11px; color: #334155; background: #f8fafc; border: 1px solid #cbd5e1; padding: 2px 8px; border-radius: 4px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${active_group.description}">
                                📝 ${active_group.description}
                            </span>
                        ` : ''}
                        ${(!is_batch_audit && payment_status) ? `
                            <span style="font-size: 11px; font-weight: 700; color: #047857; background: #ecfdf5; border: 1px solid #a7f3d0; padding: 2px 7px; border-radius: 4px;">
                                ● ${payment_status}
                            </span>
                        ` : ''}
                    </div>

                    <!-- Actions & Zoom Controls -->
                    <div class="ap-gallery-toolbar-actions" style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        ${(!is_side_by_side && (active_att.is_image || active_att.is_pdf)) ? `
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
                        ` : ''}

                        <a href="${target_url}" download="${active_att.file_name}" class="btn btn-sm btn-primary" style="font-weight: 600; padding: 4px 10px; font-size: 12px;">
                            ⬇️ Download (${(active_att.extension || '').toUpperCase()})
                        </a>
                        <a href="${target_url}" target="_blank" class="btn btn-sm btn-default" title="Open Full in New Tab" style="padding: 4px 8px; font-size: 12px;">
                            ↗️
                        </a>
                    </div>
                </div>

                <!-- Proof Segmented Tabs (if > 1 proof) -->
                ${proof_tabs_html}

                <!-- Viewer Body -->
                <div class="ap-preview-container" style="flex: 1; position: relative;">
                    ${preview_content}
                </div>
            `;

            $main_content.html(active_html);

            // Render PDF via fetch + PDF.js / Blob in Single View OR Side-by-Side View
            if (is_side_by_side && proof_count >= 2) {
                const p_left = active_group.proofs[0];
                const p_right = active_group.proofs[active_proof_idx > 0 ? active_proof_idx : 1];
                if (p_left && p_left.is_pdf) {
                    render_pdf_with_pdfjs(p_left.view_url || p_left.file_url, $main_content.find('.ap-sbs-pdf-left'), { compact: true });
                }
                if (p_right && p_right.is_pdf) {
                    render_pdf_with_pdfjs(p_right.view_url || p_right.file_url, $main_content.find('.ap-sbs-pdf-right'), { compact: true });
                }
            } else if (!is_side_by_side && active_att.is_pdf) {
                render_pdf_with_pdfjs(target_url, $main_content.find('.ap-pdf-pages-mount'));
            }
        };

        // Bulletproof PDF Renderer: works for ALL private & public PDFs via fetch(Uint8Array) + PDF.js + local Blob fallback
        const render_pdf_with_pdfjs = (url, $mount, pdf_opts) => {
            pdf_opts = pdf_opts || {};
            if (!$mount || !$mount.length) return;

            const show_blob_iframe = (array_buf) => {
                const pdfBlob = new Blob([array_buf], { type: 'application/pdf' });
                const blobUrl = URL.createObjectURL(pdfBlob);
                active_blob_urls.push(blobUrl);
                $mount.html(`
                    <iframe src="${blobUrl}#view=FitH&toolbar=1" style="width: 100%; height: 530px; border: none; border-radius: 6px; background: #ffffff;" title="PDF Preview"></iframe>
                `);
            };

            const render_buffer_with_pdfjs = (array_buf) => {
                if (!window.pdfjsLib) {
                    show_blob_iframe(array_buf);
                    return;
                }

                try {
                    window.pdfjsLib.GlobalWorkerOptions.workerSrc = '/assets/ap_automation/js/libs/pdf.worker.min.js';
                } catch (e) {}

                window.pdfjsLib.getDocument({ data: new Uint8Array(array_buf) }).promise.then(pdf => {
                    $mount.empty();
                    const num_pages = pdf.numPages;
                    const target_width = pdf_opts.compact ? 420 : 780;

                    const renderPage = (pageNum) => {
                        if (pageNum > num_pages) return;
                        pdf.getPage(pageNum).then(page => {
                            const unscaledViewport = page.getViewport({ scale: 1.0 });
                            const scale = Math.min(2.2, Math.max(1.1, target_width / unscaledViewport.width));
                            const viewport = page.getViewport({ scale: scale });

                            const canvas = document.createElement('canvas');
                            canvas.className = 'ap-pdf-page-canvas';
                            canvas.style.maxWidth = '100%';
                            canvas.style.height = 'auto';
                            canvas.style.boxShadow = '0 4px 18px rgba(0,0,0,0.4)';
                            canvas.style.borderRadius = '4px';
                            canvas.style.background = '#ffffff';
                            canvas.style.display = 'block';
                            canvas.style.margin = '0 auto';
                            canvas.height = viewport.height;
                            canvas.width = viewport.width;

                            const pageWrapper = document.createElement('div');
                            pageWrapper.style.position = 'relative';
                            pageWrapper.style.marginBottom = '14px';
                            pageWrapper.appendChild(canvas);

                            if (num_pages > 1) {
                                const badge = document.createElement('div');
                                badge.innerText = `Page ${pageNum} of ${num_pages}`;
                                badge.style.cssText = 'position: absolute; bottom: 8px; right: 8px; background: rgba(15,23,42,0.8); color: #ffffff; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; pointer-events: none;';
                                pageWrapper.appendChild(badge);
                            }

                            $mount.append(pageWrapper);

                            page.render({
                                canvasContext: canvas.getContext('2d'),
                                viewport: viewport
                            }).promise.then(() => {
                                renderPage(pageNum + 1);
                            });
                        });
                    };

                    renderPage(1);
                }).catch(err => {
                    console.warn('[AP Gallery] PDF.js error, using local Blob iframe:', err);
                    show_blob_iframe(array_buf);
                });
            };

            fetch(url, { credentials: 'include' }).then(async (resp) => {
                if (!resp.ok) {
                    throw new Error(`HTTP ${resp.status}`);
                }
                const ct = (resp.headers.get('content-type') || '').toLowerCase();
                const buf = await resp.arrayBuffer();

                // Handle missing-file SVG or image cleanly instead of failing PDF.js
                if (ct.includes('image/svg') || ct.startsWith('image/')) {
                    const imgBlob = new Blob([buf], { type: ct });
                    const imgBlobUrl = URL.createObjectURL(imgBlob);
                    active_blob_urls.push(imgBlobUrl);
                    $mount.html(`<img src="${imgBlobUrl}" style="max-width: 100%; max-height: 520px; border-radius: 6px; object-fit: contain;" />`);
                    return;
                }

                if (!window.pdfjsLib) {
                    frappe.require('/assets/ap_automation/js/libs/pdf.min.js', () => {
                        render_buffer_with_pdfjs(buf);
                    });
                } else {
                    render_buffer_with_pdfjs(buf);
                }
            }).catch(err => {
                console.warn('[AP Gallery] PDF fetch failed, falling back to direct iframe:', err);
                $mount.html(`
                    <div style="text-align: center; padding: 40px 20px; color: #f8fafc;">
                        <div style="font-size: 36px; margin-bottom: 10px;">📄</div>
                        <div style="font-size: 14px; font-weight: 600; margin-bottom: 12px;">Preview Unavailable in Embedded Mode</div>
                        <a href="${url}" target="_blank" class="btn btn-sm btn-primary" style="margin-right: 8px;">↗️ Open PDF in New Tab</a>
                        <a href="${url}" download class="btn btn-sm btn-default">⬇️ Download PDF</a>
                    </div>
                `);
            });
        };

        // Zoom & Pan helper
        const apply_zoom = () => {
            const $img = $main_content.find('.ap-preview-img');
            const $pdf_mount = $main_content.find('.ap-pdf-pages-mount');
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
            } else if ($pdf_mount.length) {
                $pdf_mount.css({
                    'transform': `scale(${zoom_level}) rotate(${rotation_deg}deg)`,
                    'transform-origin': 'top center',
                    'transition': 'transform 0.15s ease'
                });
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

        $main_content.on('dblclick', '.ap-preview-img', function (e) {
            e.stopPropagation();
            zoom_level = zoom_level === 1.0 ? 2.0 : 1.0;
            pan_x = 0;
            pan_y = 0;
            apply_zoom();
        });

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

        // Stepper Navigation Events
        $main_content.on('click', '.ap-btn-prev-row, .ap-nav-floating-prev', function (e) {
            e.stopPropagation();
            if (current_group_idx > 0) {
                select_group(current_group_idx - 1, true);
            }
        });

        $main_content.on('click', '.ap-btn-next-row, .ap-nav-floating-next', function (e) {
            e.stopPropagation();
            if (current_group_idx < groups.length - 1) {
                select_group(current_group_idx + 1, true);
            }
        });

        // Multi-Proof Tab Selector
        $main_content.on('click', '.ap-btn-select-proof', function (e) {
            e.stopPropagation();
            const pidx = parseInt($(this).attr('data-pidx'));
            active_proof_idx = pidx;
            is_side_by_side = false;
            render_active_preview();
        });

        // Side-by-Side Toggle
        $main_content.on('click', '.ap-btn-toggle-sidebyside', function (e) {
            e.stopPropagation();
            is_side_by_side = !is_side_by_side;
            render_active_preview();
        });

        // In-Modal Expense Head Editor (Syncs Weekly Audit Batch or Standard Claim Row)
        $main_content.off('click', '.ap-btn-edit-head').on('click', '.ap-btn-edit-head', function (e) {
            e.stopPropagation();
            const active_group = groups[current_group_idx];
            const current_head = active_group.expense_head || '';
            const row_num = active_group.row_idx || (current_group_idx + 1);
            const target_voucher = active_group.claim_name || (frm && frm.doc ? frm.doc.name : '');

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
                        title: is_batch_audit ? __(`Modify Expense Head — ${target_voucher}`) : __(`Edit Expenses of Head — Row #${row_num}`),
                        fields: [
                            {
                                fieldname: 'expense_head',
                                fieldtype: 'Select',
                                label: __('Expenses of Head'),
                                options: heads,
                                default: heads.includes(current_head) ? current_head : heads[0],
                                reqd: 1,
                                change: function () {
                                    const val = edit_head_dialog.get_value('expense_head');
                                    edit_head_dialog.set_df_property('custom_head', 'hidden', is_batch_audit || val !== 'OTHER / VENDOR LEDGER');
                                }
                            },
                            {
                                fieldname: 'custom_head',
                                fieldtype: 'Data',
                                label: __('Custom Head / Ledger Name (Manual Typing)'),
                                default: active_group.custom_ledger_name || '',
                                hidden: is_batch_audit || current_head !== 'OTHER / VENDOR LEDGER',
                                description: __('Enter custom head or vendor ledger name')
                            }
                        ],
                        primary_action_label: __('Save Head'),
                        primary_action: function (vals) {
                            const selected_head = vals.expense_head;
                            const custom_val = (!is_batch_audit && selected_head === 'OTHER / VENDOR LEDGER') ? (vals.custom_head || '') : '';
                            const final_head_to_save = (!is_batch_audit && selected_head === 'OTHER / VENDOR LEDGER' && custom_val) ? custom_val : selected_head;

                            edit_head_dialog.hide();

                            if (is_batch_audit) {
                                frappe.call({
                                    method: 'ap_automation.services.weekly_accounts_batch_service.update_voucher_expense_head',
                                    args: {
                                        batch_name: active_group.batch_name || batch_name,
                                        voucher_no: target_voucher,
                                        new_expense_head: final_head_to_save,
                                        reason: 'Updated via Proof Gallery modal'
                                    },
                                    freeze: true,
                                    freeze_message: __('Updating Expense Head in Batch...'),
                                    callback: function (res) {
                                        if (res.message && res.message.status === 'SUCCESS') {
                                            groups.forEach((g, idx) => {
                                                if (g.claim_name === target_voucher || idx === current_group_idx) {
                                                    g.expense_head = final_head_to_save;
                                                    $sidebar.find(`.ap-receipt-thumb-item[data-gidx="${idx}"] .ap-thumb-category-text`).text(final_head_to_save);
                                                }
                                            });
                                            $main_content.find('.ap-active-head-text').text(final_head_to_save);
                                            if (typeof opts.on_batch_updated === 'function') {
                                                opts.on_batch_updated({ type: 'head', voucher_no: target_voucher, new_expense_head: final_head_to_save });
                                            }
                                            frappe.show_alert({ message: res.message.message, indicator: 'green' });
                                        }
                                    }
                                });
                            } else {
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
                                            active_group.expense_head = final_head_to_save;
                                            active_group.custom_ledger_name = custom_val;
                                            $main_content.find('.ap-active-head-text').text(final_head_to_save);

                                            const $thumb = $sidebar.find(`.ap-receipt-thumb-item[data-gidx="${current_group_idx}"]`);
                                            $thumb.find('.ap-thumb-category-text').text(final_head_to_save);

                                            if (frm && frm.doc) {
                                                const lines = frm.doc.expense_lines || frm.doc.vendor_lines || frm.doc.expense_items || [];
                                                const target = lines.find(x => x.idx === row_num);
                                                if (target) {
                                                    target.expense_head = final_head_to_save;
                                                    if (custom_val) target.custom_ledger_name = custom_val;
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
                        }
                    });

                    edit_head_dialog.show();
                }
            });
        });

        // In-Modal JV Number & Date Editor (Weekly Accounts Audit Batch Mode)
        $main_content.off('click', '.ap-btn-edit-jv').on('click', '.ap-btn-edit-jv', function (e) {
            e.stopPropagation();
            const active_group = groups[current_group_idx];
            const target_voucher = active_group.claim_name || '';
            const cur_jv = active_group.jv_number || '';
            const cur_date = active_group.jv_date || (frm && frm.doc ? frm.doc.batch_date : '') || frappe.datetime.nowdate();

            frappe.prompt([
                {
                    fieldname: 'jv_number',
                    fieldtype: 'Data',
                    label: __('Journal Voucher (JV) Number'),
                    default: cur_jv,
                    reqd: 1,
                    placeholder: __('e.g. 744 or JV-2026-0012')
                },
                {
                    fieldname: 'jv_date',
                    fieldtype: 'Date',
                    label: __('JV Date'),
                    default: cur_date,
                    reqd: 1
                }
            ], function (values) {
                frappe.call({
                    method: 'ap_automation.services.weekly_accounts_batch_service.set_voucher_jv',
                    args: {
                        batch_name: active_group.batch_name || batch_name,
                        voucher_no: target_voucher,
                        jv_number: values.jv_number,
                        jv_date: values.jv_date
                    },
                    freeze: true,
                    freeze_message: __('Saving JV Number...'),
                    callback: function (res) {
                        if (res.message && res.message.status === 'SUCCESS') {
                            groups.forEach((g, idx) => {
                                if (g.claim_name === target_voucher || idx === current_group_idx) {
                                    g.jv_number = values.jv_number;
                                    g.jv_date = values.jv_date;
                                }
                            });
                            const jv_disp = values.jv_number + (values.jv_date ? ` (${self.formatDate(values.jv_date)})` : '');
                            $main_content.find('.ap-active-jv-text').text(jv_disp);
                            if (typeof opts.on_batch_updated === 'function') {
                                opts.on_batch_updated({ type: 'jv', voucher_no: target_voucher, jv_number: values.jv_number, jv_date: values.jv_date });
                            }
                            frappe.show_alert({ message: res.message.message, indicator: 'green' });
                        }
                    }
                });
            }, __('Set JV Number for ' + target_voucher), __('Save JV'));
        });

        // In-Modal Expense Type Editor (1-Click Dynamic Master Update)
        $main_content.off('click', '.ap-btn-edit-type').on('click', '.ap-btn-edit-type', function (e) {
            e.stopPropagation();
            const active_group = groups[current_group_idx];
            const current_type = active_group.category || '';
            const row_num = active_group.row_idx || (current_group_idx + 1);
            const dt = (frm && frm.doc && frm.doc.doctype) ? frm.doc.doctype : 'Petty Cash Entry';
            const dn = (frm && frm.doc && frm.doc.name) ? frm.doc.name : '';

            let module_scope = 'All';
            if (dt === 'Petty Cash Entry') module_scope = 'Petty Cash';
            else if (dt === 'Admin Weekly Vendor Claim') module_scope = 'Admin Weekly Vendor Claims';
            else if (dt === 'Event Expense Claim') module_scope = 'Events';
            else if (dt === 'Employee Reimbursement Claim') module_scope = 'Employee Reimbursements';

            if (window.APExpenseTypeManager && typeof window.APExpenseTypeManager.openEditRowTypePrompt === 'function') {
                window.APExpenseTypeManager.openEditRowTypePrompt(dt, dn, row_num, current_type, module_scope, function (new_type) {
                    active_group.category = new_type;
                    $main_content.find('.ap-active-type-text').text(new_type);

                    const $thumb = $sidebar.find(`.ap-receipt-thumb-item[data-gidx="${current_group_idx}"]`);
                    if (!active_group.expense_head) {
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
            const active_group = groups[current_group_idx];
            const current_proof = is_side_by_side ? active_group.proofs[0] : (active_group.proofs[active_proof_idx] || active_group.proofs[0]);

            new frappe.ui.FileUploader({
                folder: 'Home/Attachments',
                doctype: frm.doc.doctype,
                docname: frm.doc.name,
                fieldname: 'expense_lines',
                on_success: (file_doc) => {
                    const table_name = frm.doc.doctype === 'Petty Cash Entry' ? 'expense_lines' : (frm.doc.doctype === 'Admin Weekly Vendor Claim' ? 'vendor_lines' : (frm.doc.doctype === 'Employee Reimbursement Claim' ? 'expense_lines' : 'claim_items'));
                    const lines = frm.doc[table_name] || [];
                    const row_num = active_group.row_idx || (current_group_idx + 1);
                    const row = lines.find(x => x.idx === row_num) || lines[current_group_idx] || lines[0];
                    if (row) {
                        let target_field = 'receipt_attachment';
                        if (current_proof && current_proof.proof_type === 'payment') {
                            target_field = 'payment_proof_attachment';
                        } else if (current_proof && current_proof.proof_type === 'extra') {
                            target_field = 'additional_proof_attachment';
                        } else if (row.receipt_attachment !== undefined) {
                            target_field = 'receipt_attachment';
                        } else if (row.attach_receipt !== undefined) {
                            target_field = 'attach_receipt';
                        } else if (row.attachment !== undefined) {
                            target_field = 'attachment';
                        }

                        frappe.model.set_value(row.doctype, row.name, target_field, file_doc.file_url);
                        if (current_proof) {
                            current_proof.file_url = file_doc.file_url;
                            current_proof.view_url = self.buildViewUrl(frm, file_doc.file_url);
                            current_proof.file_name = file_doc.file_url.split('/').pop().split('?')[0];
                            const ext = current_proof.file_name.substring(current_proof.file_name.lastIndexOf('.')).toLowerCase();
                            current_proof.is_image = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext);
                            current_proof.is_pdf = ext === '.pdf';
                            current_proof.extension = ext;
                        }

                        if (frm.fields_dict[table_name]) frm.refresh_field(table_name);
                        render_active_preview();
                        frappe.show_alert({ message: __('Receipt updated successfully!'), indicator: 'green' });
                    }
                }
            });
        });

        // Helper to select a row group
        const select_group = (g_idx, smooth_scroll_if_needed = false) => {
            if (g_idx < 0 || g_idx >= groups.length) return;
            current_group_idx = g_idx;

            // Reset active proof if out of bounds
            if (active_proof_idx >= groups[current_group_idx].proofs.length) {
                active_proof_idx = 0;
            }

            // If side-by-side was on but next row doesn't have 2 proofs, revert to single
            if (is_side_by_side && groups[current_group_idx].proofs.length < 2) {
                is_side_by_side = false;
                active_proof_idx = 0;
            }

            // Highlight selected item in sidebar
            $sidebar.find('.ap-receipt-thumb-item').removeClass('ap-selected-row').css({
                'background': '#ffffff',
                'border': '1px solid #e2e8f0',
                'box-shadow': 'none'
            });

            const $card = $sidebar.find(`.ap-receipt-thumb-item[data-gidx="${g_idx}"]`);
            $card.addClass('ap-selected-row').css({
                'background': '#ede9fe',
                'border': '2px solid #8b5cf6',
                'box-shadow': '0 2px 8px rgba(139, 92, 246, 0.25)'
            });

            // Smooth scroll into view when navigating via stepper or keyboard
            if (smooth_scroll_if_needed && $card.length && $card[0].scrollIntoView) {
                $card[0].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            }

            render_active_preview();
        };

        // Thumbnail Click: Preserves Left Sidebar Scroll Position
        $sidebar.off('click', '.ap-receipt-thumb-item').on('click', '.ap-receipt-thumb-item', function () {
            const gidx = parseInt($(this).attr('data-gidx'));
            select_group(gidx, false);
        });

        // Keyboard Arrow Navigation
        $(document).on('keydown.ap_gallery', function (e) {
            if (!d.$wrapper.is(':visible')) return;
            if ($(e.target).is('input, select, textarea')) return;

            if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
                e.preventDefault();
                if (current_group_idx < groups.length - 1) {
                    select_group(current_group_idx + 1, true);
                }
            } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
                e.preventDefault();
                if (current_group_idx > 0) {
                    select_group(current_group_idx - 1, true);
                }
            }
        });

        // Clean up global listeners and Blob URLs when dialog closes
        d.on_hide = function () {
            $(document).off('.ap_gallery');
            active_blob_urls.forEach((bUrl) => {
                try { URL.revokeObjectURL(bUrl); } catch (e) {}
            });
        };

        // ZIP All Download (Handles both Single Doc & Weekly Accounts Audit Batch multi-vouchers)
        $wrapper.on('click', '.ap-btn-download-all', function () {
            if (is_batch_audit) {
                const claim_list = Array.from(new Set(groups.map(g => g.claim_name).filter(Boolean)));
                if (claim_list.length === 1) {
                    const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent('Employee Reimbursement Claim')}&docname=${encodeURIComponent(claim_list[0])}`;
                    window.location.href = url;
                } else if (claim_list.length > 1) {
                    const lbl = opts.emp_name || batch_name || 'Batch_Receipts';
                    const url = `/api/method/ap_automation.services.attachment_service.download_multiple_claims_receipts_zip?claim_names=${encodeURIComponent(JSON.stringify(claim_list))}&label=${encodeURIComponent(lbl)}`;
                    window.location.href = url;
                }
                return;
            }
            const dt = (frm && frm.doc && frm.doc.doctype) ? frm.doc.doctype : '';
            const dn = (frm && frm.doc && frm.doc.name) ? frm.doc.name : '';
            const url = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(dt)}&docname=${encodeURIComponent(dn)}`;
            window.location.href = url;
        });

        // Initial render
        d.show();
        render_active_preview();

        // Scroll initial item into view if starting beyond row 0
        if (current_group_idx > 0) {
            setTimeout(() => {
                const $initial_item = $sidebar.find(`.ap-receipt-thumb-item[data-gidx="${current_group_idx}"]`);
                if ($initial_item.length && $initial_item[0].scrollIntoView) {
                    $initial_item[0].scrollIntoView({ block: 'center', behavior: 'auto' });
                }
            }, 60);
        }
    }
};
