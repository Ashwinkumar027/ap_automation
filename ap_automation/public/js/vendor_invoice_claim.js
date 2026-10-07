// Copyright (c) 2026, Quanti and contributors
// Production-grade Vendor Invoice Claim UI controller with Petty-Cash-Style Receipt Gallery & 3-Way Match

frappe.ui.form.on("Vendor Invoice Claim", {
    refresh: function(frm) {
        frm.trigger("toggle_route_fields");
        render_vendor_invoice_header(frm);
        setup_vendor_receipt_gallery_button(frm);
    },

    invoice_type: function(frm) {
        frm.trigger("toggle_route_fields");
        render_vendor_invoice_header(frm);
    },

    tax_invoice_attachment: function(frm) {
        setup_vendor_receipt_gallery_button(frm);
    },

    email_approval_attachment: function(frm) {
        setup_vendor_receipt_gallery_button(frm);
    },

    purchase_order: function(frm) {
        if (frm.doc.purchase_order) {
            frappe.call({
                method: "frappe.client.get",
                args: {
                    doctype: frappe.db.exists("AP Purchase Order", frm.doc.purchase_order) ? "AP Purchase Order" : "Purchase Order",
                    name: frm.doc.purchase_order
                },
                callback: function(r) {
                    if (r.message) {
                        let po = r.message;
                        if (po.doctype === "AP Purchase Order") {
                            if (po.vendor && !frm.doc.vendor) {
                                frm.set_value("vendor", po.vendor);
                            }
                            if (po.company_entity && !frm.doc.company) {
                                frm.set_value("company", po.company_entity);
                            }
                            if (po.net_taxable_value && !frm.doc.base_amount) {
                                frm.set_value("base_amount", po.net_taxable_value);
                            }
                            if (po.advance_amount && (!frm.doc.advance_deducted || frm.doc.advance_deducted === 0)) {
                                frm.set_value("advance_deducted", po.advance_amount);
                            }
                        } else {
                            if (po.supplier && !frm.doc.vendor) {
                                frm.set_value("vendor", po.supplier);
                            }
                            if (po.company && !frm.doc.company) {
                                frm.set_value("company", po.company);
                            }
                            if (po.net_total && !frm.doc.base_amount) {
                                frm.set_value("base_amount", po.net_total);
                            }
                        }
                        calculate_vendor_totals(frm);
                    }
                }
            });
        }
        render_vendor_invoice_header(frm);
    },

    vendor: function(frm) {
        if (frm.doc.vendor) {
            frappe.db.get_value("Supplier", frm.doc.vendor, ["supplier_name", "tax_id"]).then(r => {
                if (r && r.message) {
                    frm.set_value("vendor_name", r.message.supplier_name);
                    frm.set_value("vendor_gstin", r.message.tax_id || "");
                }
            });

            // Fetch Bank Account
            frappe.call({
                method: "frappe.client.get_list",
                args: {
                    doctype: "Bank Account",
                    filters: { party_type: "Supplier", party: frm.doc.vendor },
                    fields: ["bank", "bank_account_no", "branch_code", "penny_drop_status"],
                    limit: 1
                },
                callback: function(res) {
                    if (res.message && res.message.length > 0) {
                        let acc = res.message[0];
                        frm.set_value("bank_name", acc.bank || "");
                        frm.set_value("bank_account_number", acc.bank_account_no || "");
                        frm.set_value("bank_ifsc_code", acc.branch_code || "");
                    }
                }
            });
        }
        render_vendor_invoice_header(frm);
    },

    base_amount: function(frm) {
        calculate_vendor_totals(frm);
    },

    gst_rate: function(frm) {
        calculate_vendor_totals(frm);
    },

    advance_deducted: function(frm) {
        calculate_vendor_totals(frm);
    },

    tds_section: function(frm) {
        calculate_vendor_totals(frm);
    },

    toggle_route_fields: function(frm) {
        let is_po = frm.doc.invoice_type === "With Purchase Order";
        frm.toggle_reqd("purchase_order", is_po);
        frm.toggle_reqd("email_approval_attachment", !is_po);
    }
});

// --------------------------------------------------------------------------------------
// PETTY-CASH-STYLE 2-COLUMN PROOF & RECEIPT GALLERY ENGINE
// --------------------------------------------------------------------------------------
function get_vendor_claim_attachments(frm) {
    const atts = [];

    const parent_fields = [
        { field: 'tax_invoice_attachment', label: '📄 Vendor Tax Invoice', cat: 'Vendor Commercial Tax Bill' },
        { field: 'email_approval_attachment', label: '📧 Manager Email Approval Proof', cat: 'Internal Audit Proof' },
        { field: 'grn_attachment', label: '📦 Goods Receipt Note / Delivery Proof', cat: 'Warehouse Receipt' },
        { field: 'advance_receipt_attachment', label: '🏦 Advance Payment Proof', cat: 'Bank Advance Reference' }
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
                amount: parseFloat(frm.doc.net_payable_amount || frm.doc.total_invoice_amount || frm.doc.base_amount || 0.0),
                date: frm.doc.tax_invoice_date || frm.doc.posting_date || '',
                bill_no: frm.doc.tax_invoice_number || frm.doc.name || '',
                file_url: clean_url,
                file_name: file_name,
                is_image: ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'].includes(ext),
                is_pdf: ext === '.pdf',
                extension: ext
            });
        }
    });

    return atts;
}

function setup_vendor_receipt_gallery_button(frm) {
    const atts = get_vendor_claim_attachments(frm);
    const count = atts.length;

    let btn_label = count > 0 ? __(`🖼️ View Attached Receipts (${count})`) : __(`🖼️ View Attached Receipts`);
    let btn = frm.add_custom_button(btn_label, function () {
        open_vendor_receipt_gallery_modal(frm, atts);
    });

    btn.addClass("btn-primary").css({
        "background": "linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)",
        "border": "none",
        "color": "#ffffff",
        "font-weight": "600",
        "box-shadow": "0 2px 6px rgba(124, 58, 237, 0.3)"
    });
}

function open_vendor_receipt_gallery_modal(frm, attachments, start_idx) {
    if (!attachments || attachments.length === 0) {
        const empty_d = new frappe.ui.Dialog({
            title: __('Proof & Receipt Gallery — ') + (frm.doc.name || 'New Claim'),
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'empty_html',
                    options: `
                        <div style="text-align: center; padding: 60px 20px;">
                            <div style="font-size: 54px; margin-bottom: 16px;">📂</div>
                            <div style="font-size: 18px; font-weight: 700; color: #1e293b;">No Proofs or Receipts Attached</div>
                            <div style="font-size: 14px; color: #64748b; margin-top: 8px;">
                                Please upload a <b>Vendor Tax Invoice PDF</b> or <b>Email Approval Proof</b> to view them in the gallery.
                            </div>
                        </div>
                    `
                }
            ]
        });
        empty_d.show();
        return;
    }

    start_idx = start_idx || 0;
    let current_index = Math.min(start_idx, attachments.length - 1);

    const d = new frappe.ui.Dialog({
        title: __('Proof & Receipt Gallery — ') + (frm.doc.name || 'Vendor Invoice'),
        size: 'extra-large',
        fields: [
            {
                fieldtype: 'HTML',
                fieldname: 'gallery_html_area'
            }
        ]
    });

    const formatINR = function(val) {
        return new Intl.NumberFormat('en-IN', {
            style: 'currency',
            currency: 'INR',
            maximumFractionDigits: 2
        }).format(val || 0);
    };

    const formatDate = function(d_str) {
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
    };

    const update_view = () => {
        const active_att = attachments[current_index];
        const active_date_formatted = formatDate(active_att.date);

        let preview_content = '';
        if (active_att.is_image) {
            preview_content = `
                <div style="display: flex; justify-content: center; align-items: center; background: #0f172a; border-radius: 8px; overflow: hidden; min-height: 480px; max-height: 600px; padding: 12px;">
                    <img src="${active_att.file_url}" alt="${active_att.merchant}" style="max-width: 100%; max-height: 570px; object-fit: contain; box-shadow: 0 4px 20px rgba(0,0,0,0.5); border-radius: 4px;" />
                </div>
            `;
        } else if (active_att.is_pdf) {
            preview_content = `
                <div style="background: #0f172a; border-radius: 8px; overflow: hidden; height: 580px;">
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
            const item_date_formatted = formatDate(att.date);
            const row_title = att.merchant;

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
                    <div style="font-size: 24px;">${att.is_pdf ? '📄' : '🧾'}</div>
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
                            <span style="font-size: 12px; font-weight: 700; color: #059669;">${formatINR(att.amount)}</span>
                            <span style="font-size: 11px; color: #64748b; white-space: nowrap; text-overflow: ellipsis; overflow: hidden;">${att.category}</span>
                        </div>
                    </div>
                </div>
            `;
        });

        const header_title = active_att.merchant;

        const full_html = `
            <div style="display: flex; gap: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                <!-- Left Sidebar (Receipts List) -->
                <div style="width: 340px; max-height: 580px; overflow-y: auto; padding-right: 8px; border-right: 1px solid #e2e8f0;">
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
                                    📅 Invoice Date: <b>${active_date_formatted}</b>
                                </span>
                            ` : ''}
                            <span style="font-size: 12px; color: #64748b;">
                                Payable: <b style="color: #059669; font-size: 13px;">${formatINR(active_att.amount)}</b> | Type: <b style="color: #1e293b;">${active_att.category}</b>
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

function calculate_vendor_totals(frm) {
    let base = parseFloat(frm.doc.base_amount || 0.0);
    let rate_str = frm.doc.gst_rate || "18%";
    let rate = parseFloat(rate_str.replace("%", "").trim() || 0.0);

    let gst = Math.round((base * (rate / 100.0)) * 100) / 100;
    let total = Math.round((base + gst) * 100) / 100;
    let advance = parseFloat(frm.doc.advance_deducted || 0.0);

    // Calculate TDS
    let tds_rate = 0.0;
    let tds_sec = frm.doc.tds_section || "None / Exempt";
    if (tds_sec.includes("194J - Professional Fees (10%)") || tds_sec.includes("194I - Rent (10%)")) {
        tds_rate = 10.0;
    } else if (tds_sec.includes("194C - Contractor (2%)") || tds_sec.includes("194J - Technical Fees (2%)")) {
        tds_rate = 2.0;
    } else if (tds_sec.includes("194C - Contractor (1%)")) {
        tds_rate = 1.0;
    } else if (tds_sec.includes("194Q - Purchase of Goods (0.1%)")) {
        tds_rate = 0.1;
    } else if (tds_sec.includes("206AB - Higher Non-Filer (20%)")) {
        tds_rate = 20.0;
    }

    let tds_amt = Math.round((base * (tds_rate / 100.0)) * 100) / 100;
    let net = Math.max(Math.round((total - advance - tds_amt) * 100) / 100, 0.0);

    frm.set_value("gst_amount", gst);
    frm.set_value("total_invoice_amount", total);
    frm.set_value("tds_amount", tds_amt);
    frm.set_value("net_payable_amount", net);
    render_vendor_invoice_header(frm);
}

function render_vendor_invoice_header(frm) {
    if (frm.fields_dict.header_html) {
        let match_status = frm.doc.match_status || "Pending Verification";
        let badge_bg = "#e0f2fe";
        let badge_color = "#0369a1";
        let badge_icon = "⏳";

        if (match_status.includes("Passed")) {
            badge_bg = "#ecfdf5";
            badge_color = "#047857";
            badge_icon = "✅";
        } else if (match_status.includes("Flagged") || match_status.includes("Mismatch")) {
            badge_bg = "#fef2f2";
            badge_color = "#b91c1c";
            badge_icon = "🚨";
        }

        let net_fmt = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(frm.doc.net_payable_amount || 0.0);
        let tds_fmt = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(frm.doc.tds_amount || 0.0);
        let total_fmt = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(frm.doc.total_invoice_amount || 0.0);

        let html = `
            <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); color: white; border-radius: 10px; padding: 16px 20px; margin-bottom: 15px; box-shadow: 0 4px 12px rgba(15,23,42,0.15);">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
                    <div>
                        <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; font-weight: 700;">
                            Vendor Invoice Verification Center • Lane 3
                        </div>
                        <div style="font-size: 18px; font-weight: 800; color: #f8fafc; margin-top: 2px;">
                            ${frm.doc.vendor_name || frm.doc.vendor || "Select Vendor"}
                        </div>
                        <div style="font-size: 12px; color: #cbd5e1; margin-top: 2px;">
                            Invoice #: <strong>${frm.doc.tax_invoice_number || "Draft"}</strong> | Route: <span style="background: rgba(255,255,255,0.15); padding: 2px 8px; border-radius: 4px;">${frm.doc.invoice_type || "Standard"}</span>
                        </div>
                    </div>
                    <div style="display: flex; gap: 12px; align-items: center;">
                        <div style="background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; padding: 8px 14px; text-align: right;">
                            <div style="font-size: 10px; color: #94a3b8; text-transform: uppercase;">Total Invoice</div>
                            <div style="font-size: 14px; font-weight: 700; color: #f8fafc;">${total_fmt}</div>
                        </div>
                        <div style="background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; padding: 8px 14px; text-align: right;">
                            <div style="font-size: 10px; color: #fbbf24; text-transform: uppercase;">TDS Withholding</div>
                            <div style="font-size: 14px; font-weight: 700; color: #fbbf24;">- ${tds_fmt}</div>
                        </div>
                        <div style="background: linear-gradient(135deg, #059669 0%, #047857 100%); border-radius: 8px; padding: 8px 16px; text-align: right; box-shadow: 0 2px 8px rgba(5,150,105,0.3);">
                            <div style="font-size: 10px; color: #d1fae5; text-transform: uppercase; font-weight: 700;">Net Payable</div>
                            <div style="font-size: 17px; font-weight: 800; color: #ffffff;">${net_fmt}</div>
                        </div>
                    </div>
                </div>
                <div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.1); display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-size: 12px; color: #cbd5e1;">
                        <span style="background: ${badge_bg}; color: ${badge_color}; padding: 3px 10px; border-radius: 12px; font-weight: 700; font-size: 11px; margin-right: 8px;">
                            ${badge_icon} 3-Way Match: ${match_status}
                        </span>
                        ${frm.doc.purchase_order ? `Linked PO: <strong>${frm.doc.purchase_order}</strong>` : 'Direct Tax Invoice'}
                    </div>
                    <div style="font-size: 11px; color: #94a3b8;">
                        Zero-Trust Security & Duplicate Lock Active 🔒
                    </div>
                </div>
            </div>
        `;
        frm.fields_dict.header_html.$wrapper.html(html);
    }
}
