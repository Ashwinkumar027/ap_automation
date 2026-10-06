// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

frappe.ui.form.on('AP Purchase Order', {
    refresh: function(frm) {
        render_entity_letterhead_banner(frm);
        render_custom_po_actions(frm);
        update_dynamic_commercial_pills(frm);
    },

    company_entity: function(frm) {
        frm.trigger('calculate_totals');
        render_entity_letterhead_banner(frm);
    },

    vendor: function(frm) {
        if (frm.doc.vendor) {
            frappe.db.get_value('Supplier', frm.doc.vendor, ['supplier_name', 'tax_id', 'email_id', 'mobile_no'], function(r) {
                if (r) {
                    frm.set_value('vendor_name', r.supplier_name);
                    frm.set_value('vendor_gstin', r.tax_id || '');
                    if (!frm.doc.vendor_email && r.email_id) frm.set_value('vendor_email', r.email_id);
                    if (!frm.doc.vendor_mobile && r.mobile_no) frm.set_value('vendor_mobile', r.mobile_no);
                    frm.trigger('calculate_totals');
                }
            });
        }
    },

    spoc_user: function(frm) {
        if (frm.doc.spoc_user) {
            frappe.db.get_value('User', frm.doc.spoc_user, ['full_name', 'email', 'mobile_no'], function(r) {
                if (r) {
                    frm.set_value('spoc_name', r.full_name);
                    frm.set_value('spoc_email', r.email);
                    if (r.mobile_no) frm.set_value('spoc_mobile', r.mobile_no);
                }
            });
        }
    },

    advance_percentage: function(frm) {
        frm.trigger('calculate_totals');
    },

    calculate_totals: function(frm) {
        let net_taxable = 0.0;
        let total_gst = 0.0;

        let comp_state = (frm.doc.company_gstin || "").substring(0, 2).trim();
        let vendor_state = (frm.doc.vendor_gstin || "").substring(0, 2).trim();
        let is_intra = (!comp_state || !vendor_state || comp_state === vendor_state);

        (frm.doc.items || []).forEach(row => {
            let qty = flt(row.qty) || 1.0;
            let rate = flt(row.rate) || 0.0;
            let disc = flt(row.discount_amount) || 0.0;
            let taxable = Math.max((qty * rate) - disc, 0.0);

            let gst_rate_str = row.gst_rate || "18%";
            let gst_pct = flt(gst_rate_str.replace("%", "").trim()) || 18.0;
            let gst_val = taxable * (gst_pct / 100.0);

            row.taxable_amount = taxable;
            row.gst_amount = gst_val;
            row.total_amount = taxable + gst_val;

            net_taxable += taxable;
            total_gst += gst_val;
        });

        frm.set_value('net_taxable_value', net_taxable);
        frm.set_value('total_gst_amount', total_gst);
        let grand = net_taxable + total_gst;
        frm.set_value('grand_total', grand);

        if (is_intra) {
            let half = total_gst / 2.0;
            frm.set_value('cgst_amount', half);
            frm.set_value('sgst_amount', half);
            frm.set_value('igst_amount', 0.0);
            frm.set_value('gst_type', `Intra-State (CGST 9% + SGST 9% - State ${comp_state || '27'})`);
        } else {
            frm.set_value('cgst_amount', 0.0);
            frm.set_value('sgst_amount', 0.0);
            frm.set_value('igst_amount', total_gst);
            frm.set_value('gst_type', `Inter-State (IGST 18% - State ${comp_state} to ${vendor_state})`);
        }

        let adv_pct_str = frm.doc.advance_percentage || "0%";
        let adv_pct = flt(adv_pct_str.replace("%", "").trim()) || 0.0;
        let adv_val = grand * (adv_pct / 100.0);
        frm.set_value('advance_amount', adv_val);
        frm.set_value('balance_due_on_completion', grand - adv_val);

        frm.refresh_fields(['items', 'net_taxable_value', 'total_gst_amount', 'grand_total', 'cgst_amount', 'sgst_amount', 'igst_amount', 'gst_type', 'advance_amount', 'balance_due_on_completion']);
        update_dynamic_commercial_pills(frm);
    }
});

frappe.ui.form.on('AP PO Item', {
    qty: function(frm, cdt, cdn) { frm.trigger('calculate_totals'); },
    rate: function(frm, cdt, cdn) { frm.trigger('calculate_totals'); },
    discount_amount: function(frm, cdt, cdn) { frm.trigger('calculate_totals'); },
    gst_rate: function(frm, cdt, cdn) { frm.trigger('calculate_totals'); },
    items_remove: function(frm) { frm.trigger('calculate_totals'); }
});

function render_entity_letterhead_banner(frm) {
    let entity = frm.doc.company_entity || "Aionion Capital Management";
    let gstin = frm.doc.company_gstin || "27AAACA1234A1Z5";
    let cin = frm.doc.company_cin || "U74999MH2020PTC123456";
    let addr = frm.doc.company_registered_address || "Level 8, Tower B, Peninsula Business Park, Lower Parel, Mumbai, Maharashtra 400013";

    let html = `
    <div style="background: linear-gradient(135deg, #1B365D 0%, #2B547E 100%); color: white; padding: 16px 20px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 4px 12px rgba(27,54,93,0.15);">
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.2); padding-bottom: 10px; margin-bottom: 10px;">
            <div>
                <h3 style="margin: 0; color: #FFFFFF; font-size: 18px; font-weight: 700; letter-spacing: 0.5px;">${entity}</h3>
                <span style="font-size: 12px; color: #D1E0F0;">Corporate Purchase Order & Procurement System</span>
            </div>
            <div style="text-align: right;">
                <span style="background: #E8A838; color: #1B365D; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 700; text-transform: uppercase;">Official PO Form</span>
            </div>
        </div>
        <div style="font-size: 12px; color: #F0F4F8; line-height: 1.5; display: grid; grid-template-columns: 2fr 1fr; gap: 15px;">
            <div><strong>Registered Office:</strong> ${addr}</div>
            <div>
                <div><strong>GSTIN:</strong> ${gstin}</div>
                <div><strong>CIN:</strong> ${cin}</div>
            </div>
        </div>
    </div>
    `;

    frm.set_df_property('letterhead_preview_html', 'options', html);
    frm.refresh_field('letterhead_preview_html');
}

function update_dynamic_commercial_pills(frm) {
    if (!frm.dashboard) return;
    
    let grand = flt(frm.doc.grand_total) || 0.0;
    let adv = flt(frm.doc.advance_amount) || 0.0;
    let bal = flt(frm.doc.balance_due_on_completion) || 0.0;
    let gst_label = frm.doc.gst_type || "Intra-State GST";

    let sign_status = frm.doc.vendor_sign_status || "Not Sent";
    let sign_badge = `<span class="badge badge-secondary">${sign_status}</span>`;
    if (sign_status === "Digitally Signed") sign_badge = `<span class="badge badge-success" style="background-color: #107C41; color: white;">🖋️ Digitally Signed</span>`;
    if (sign_status === "Sent to Vendor") sign_badge = `<span class="badge badge-warning" style="background-color: #E8A838; color: #1B365D;">📩 Awaiting Signature</span>`;

    let dashboard_html = `
    <div class="custom-po-dashboard" style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 5px 0;">
        <div style="background: #F8FAFC; border-left: 4px solid #1B365D; padding: 10px 14px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-size: 11px; color: #64748B; font-weight: 700; text-transform: uppercase;">Grand Total (inc GST)</div>
            <div style="font-size: 17px; font-weight: 800; color: #1B365D; margin: 2px 0;">₹ ${format_number(grand, null, 2)}</div>
            <div style="font-size: 11px; color: #475569; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${gst_label}</div>
        </div>
        <div style="background: #F8FAFC; border-left: 4px solid #D97706; padding: 10px 14px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-size: 11px; color: #64748B; font-weight: 700; text-transform: uppercase;">Advance Payable Now</div>
            <div style="font-size: 17px; font-weight: 800; color: #D97706; margin: 2px 0;">₹ ${format_number(adv, null, 2)}</div>
            <div style="font-size: 11px; color: #475569;">Rate: ${frm.doc.advance_percentage || '0%'}</div>
        </div>
        <div style="background: #F8FAFC; border-left: 4px solid #107C41; padding: 10px 14px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-size: 11px; color: #64748B; font-weight: 700; text-transform: uppercase;">Balance on Completion</div>
            <div style="font-size: 17px; font-weight: 800; color: #107C41; margin: 2px 0;">₹ ${format_number(bal, null, 2)}</div>
            <div style="font-size: 11px; color: #475569;">Terms: ${frm.doc.payment_terms || 'Net 30'}</div>
        </div>
        <div style="background: #F8FAFC; border-left: 4px solid #6366F1; padding: 10px 14px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-size: 11px; color: #64748B; font-weight: 700; text-transform: uppercase;">Vendor E-Sign Status</div>
            <div style="margin-top: 4px;">${sign_badge}</div>
            <div style="font-size: 11px; color: #475569; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">SPOC: ${frm.doc.spoc_name || 'Assigned'}</div>
        </div>
    </div>
    `;

    // Clear previous custom headline to prevent duplicates
    if (frm.dashboard.headline && frm.dashboard.headline.length) {
        frm.dashboard.headline.empty();
    }
    frm.dashboard.set_headline(dashboard_html);
}

function render_custom_po_actions(frm) {
    if (!frm.is_new() && frm.doc.docstatus === 0 && frm.doc.grand_total > 0) {
        frm.add_custom_button(__('📩 Send to Vendor for E-Sign'), function() {
            frappe.confirm(
                `Are you sure you want to email Purchase Order <strong>#${frm.doc.name}</strong> to Vendor (${frm.doc.vendor_email}) for digital signature?`,
                function() {
                    frappe.call({
                        method: 'send_po_to_vendor_for_esign',
                        doc: frm.doc,
                        freeze: true,
                        freeze_message: __('Dispatching Purchase Order to Vendor...'),
                        callback: function(r) {
                            frm.reload_doc();
                        }
                    });
                }
            );
        }, __('Actions')).addClass('btn-primary');

        frm.add_custom_button(__('🖋️ Mock Test Vendor E-Sign'), function() {
            frappe.prompt([
                { fieldname: 'signer_name', fieldtype: 'Data', label: 'Signer Name', reqd: 1, default: frm.doc.vendor_contact_person || frm.doc.vendor_name },
                { fieldname: 'signer_ip', fieldtype: 'Data', label: 'Signer IP Address', reqd: 1, default: '192.168.1.108' }
            ], function(values) {
                frappe.call({
                    method: 'record_vendor_esign',
                    doc: frm.doc,
                    args: {
                        signer_name: values.signer_name,
                        signer_ip: values.signer_ip
                    },
                    callback: function() {
                        frm.reload_doc();
                        frappe.msgprint(__('🎉 Purchase Order successfully marked as Digitally Signed & Active!'));
                    }
                });
            }, __('Digital Signature Test Console'), __('Apply Digital Signature'));
        }, __('Actions'));
    }
}
