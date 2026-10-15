// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

frappe.ui.form.on('AP Purchase Order', {
    refresh: function(frm) {
        render_entity_letterhead_banner(frm);
        render_custom_po_actions(frm);
        update_dynamic_commercial_pills(frm);
    },

    company_entity: function(frm) {
        let ent = (frm.doc.company_entity || "").toLowerCase();
        if (ent.includes("quanticus")) {
            frm.set_value('signatory_name', 'Dileep Keerthi Kumar');
            frm.set_value('signatory_designation', 'Director');
            if (!frm.doc.company_gstin) frm.set_value('company_gstin', '33AAACQ5678Q1Z2');
            if (!frm.doc.company_cin) frm.set_value('company_cin', 'U62090TN2024PTC175627');
            if (!frm.doc.company_registered_address) frm.set_value('company_registered_address', '33, Meerlan Tower, Hanumantha Road, Balaji Nagar, Royapettah, Chennai - 600 014');
        } else if (ent.includes("anshul") || ent.includes("gupta") || ent.includes("aag")) {
            frm.set_value('signatory_name', 'Anish Gupta');
            frm.set_value('signatory_designation', 'Senior Partner');
            if (!frm.doc.company_gstin) frm.set_value('company_gstin', '33BAFPG1837F1Z5');
            if (!frm.doc.company_cin) frm.set_value('company_cin', 'ICAI: FNA295288');
            if (!frm.doc.company_registered_address) frm.set_value('company_registered_address', '2A, 2nd Floor, Meerlan Towers, No.33, Hanumantha Road, Royapettah, Chennai - 600 014');
        } else if (ent.includes("global") || ent.includes("ifsc")) {
            frm.set_value('signatory_name', 'Anish Gupta');
            frm.set_value('signatory_designation', 'Designated Partner');
            if (!frm.doc.company_gstin) frm.set_value('company_gstin', '24AAJFA1234F1Z9');
            if (!frm.doc.company_cin) frm.set_value('company_cin', 'LLPIN: ABR-1234');
            if (!frm.doc.company_registered_address) frm.set_value('company_registered_address', 'Unit 208, Pragya Accelerator II, GIFT City, Gandhinagar, Gujarat 382050');
        } else if (ent.includes("insurance")) {
            frm.set_value('signatory_name', 'Anish Gupta');
            frm.set_value('signatory_designation', 'Director');
            if (!frm.doc.company_gstin) frm.set_value('company_gstin', '33AAACI9876I1Z9');
            if (!frm.doc.company_cin) frm.set_value('company_cin', 'U66000TN2021PTC142985');
            if (!frm.doc.company_registered_address) frm.set_value('company_registered_address', 'No.5/2, Hanumantha Road, Balaji Nagar, Royapettah, Chennai - 600 014');
        } else {
            // Aionion Capital Market Services (ACM / Default)
            frm.set_value('signatory_name', 'Anish Gupta');
            frm.set_value('signatory_designation', 'Director');
            if (!frm.doc.company_gstin) frm.set_value('company_gstin', '27AAACA1234A1Z5');
            if (!frm.doc.company_cin) frm.set_value('company_cin', 'U66120TN2024PTC167864');
            if (!frm.doc.company_registered_address) frm.set_value('company_registered_address', '3rd Floor, Meerlan Towers, No 33, Hanumantha Road, Royapettah, Chennai - 600014');
        }
        frm.trigger('calculate_totals');
        render_entity_letterhead_banner(frm);
    },

    signatory_name: function(frm) {
        let sig = frm.doc.signatory_name || "";
        let ent = (frm.doc.company_entity || "").toLowerCase();
        if (sig.includes("Dileep")) {
            frm.set_value('signatory_designation', 'Director');
        } else if (sig.includes("Anish")) {
            if (ent.includes("anshul") || ent.includes("aag")) {
                frm.set_value('signatory_designation', 'Senior Partner');
            } else if (ent.includes("global") || ent.includes("ifsc")) {
                frm.set_value('signatory_designation', 'Designated Partner');
            } else {
                frm.set_value('signatory_designation', 'Director');
            }
        }
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
            let half = 0.0;
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
    let entity = frm.doc.company_entity || "Aionion Capital Market Services Private Limited";
    let gstin = frm.doc.company_gstin || "27AAACA1234A1Z5";
    let cin = frm.doc.company_cin || "U66120TN2024PTC167864";
    let addr = frm.doc.company_registered_address || "3rd Floor, Meerlan Towers, No 33, Hanumantha Road, Royapettah, Chennai - 600014";

    let bg_grad = "linear-gradient(135deg, #1B365D 0%, #2B547E 100%)";
    let ent_lower = entity.toLowerCase();
    if (ent_lower.includes("quanticus")) {
        bg_grad = "linear-gradient(135deg, #0369a1 0%, #0284c7 100%)";
    } else if (ent_lower.includes("anshul") || ent_lower.includes("aag")) {
        bg_grad = "linear-gradient(135deg, #1e3a8a 0%, #172554 100%)";
    }

    let html = `
    <div style="background: ${bg_grad}; color: white; padding: 16px 20px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 4px 12px rgba(27,54,93,0.15);">
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

    let sign_status = frm.doc.status || "Draft";
    let sign_badge = `<span class="badge badge-secondary">${sign_status}</span>`;
    if (sign_status === "Active PO" || frm.doc.signatory_signature_hash) {
        sign_badge = `<span class="badge badge-success" style="background-color: #107C41; color: white;">✔ Digitally Signed & Active</span>`;
    }

    let dashboard_html = `
    <div style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
        <div style="flex: 1; min-width: 200px; background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid #1B365D; padding: 12px 16px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Grand Total (Inc GST)</div>
            <div style="font-size: 20px; font-weight: 800; color: #1e293b; margin: 4px 0;">₹ ${format_currency(grand)}</div>
            <div style="font-size: 11px; color: #475569;">${gst_label}</div>
        </div>

        <div style="flex: 1; min-width: 200px; background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Advance Payable Now</div>
            <div style="font-size: 20px; font-weight: 800; color: #b45309; margin: 4px 0;">₹ ${format_currency(adv)}</div>
            <div style="font-size: 11px; color: #475569;">Rate: ${frm.doc.advance_percentage || '0%'}</div>
        </div>

        <div style="flex: 1; min-width: 200px; background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid #10b981; padding: 12px 16px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Balance on Completion</div>
            <div style="font-size: 20px; font-weight: 800; color: #047857; margin: 4px 0;">₹ ${format_currency(bal)}</div>
            <div style="font-size: 11px; color: #475569;">Terms: ${frm.doc.payment_terms_clause || 'Milestone Based'}</div>
        </div>

        <div style="flex: 0.8; min-width: 160px; background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid #6366f1; padding: 12px 16px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Status</div>
            <div style="margin: 8px 0;">${sign_badge}</div>
            <div style="font-size: 11px; color: #475569;">Signatory: <b>${frm.doc.signatory_name || 'Anish Gupta'}</b></div>
        </div>
    </div>
    `;

    if (frm.dashboard.headline && frm.dashboard.headline.length) {
        frm.dashboard.headline.empty();
    }
    frm.dashboard.set_headline(dashboard_html);
}

function render_custom_po_actions(frm) {
    if (!frm.is_new()) {
        // 1. Download PO PDF Button
        frm.add_custom_button(__('📄 Download PO (PDF)'), function() {
            const url = `/api/method/ap_automation.services.po_pdf_service.download_purchase_order_pdf?po_name=${encodeURIComponent(frm.doc.name)}`;
            window.open(url, '_blank');
        }).addClass('btn-primary').css({
            'background-color': '#1e3a8a',
            'border-color': '#172554',
            'color': '#ffffff',
            'font-weight': '700'
        });

        // 2. Approve & Digitally Sign PO Button (Option 1)
        if (frm.doc.status !== 'Active PO') {
            frm.add_custom_button(__('✔ Approve & Sign PO'), function() {
                let current_sig = frm.doc.signatory_name || 'Director';
                frappe.confirm(
                    `Are you sure you want to <strong>Approve & Digitally Sign</strong> Purchase Order <strong>#${frm.doc.name}</strong> as <strong>${current_sig}</strong>?`,
                    function() {
                        frappe.call({
                            method: 'ap_automation.services.po_pdf_service.approve_and_digitally_sign_po',
                            args: {
                                po_name: frm.doc.name,
                                signatory_name: frm.doc.signatory_name
                            },
                            freeze: true,
                            freeze_message: __('Certifying Digital Signature & Activating PO...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'success') {
                                    frappe.show_alert({
                                        message: __('🎉 PO Approved & Digitally Certified by ' + r.message.signatory_name),
                                        indicator: 'green'
                                    }, 6);
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            }).addClass('btn-success').css({
                'background-color': '#16a34a',
                'border-color': '#15803d',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }

        // Actions menu for other utilities
        if (frm.doc.grand_total > 0) {
            if (frm.doc.vendor_sign_url) {
                frm.add_custom_button(__('📋 Copy E-Sign Link'), function() {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(frm.doc.vendor_sign_url).then(() => {
                            frappe.show_alert({
                                message: __('📋 Vendor E-Sign Portal URL copied to clipboard!'),
                                indicator: 'green'
                            }, 5);
                        });
                    } else {
                        frappe.prompt([
                            { fieldname: 'sign_url', fieldtype: 'Small Text', label: 'Vendor Signing URL', default: frm.doc.vendor_sign_url, read_only: 1 }
                        ], null, __('Vendor Signing URL'));
                    }
                }, __('Actions'));

                frm.add_custom_button(__('↗️ Open Signing Portal'), function() {
                    window.open(frm.doc.vendor_sign_url, '_blank');
                }, __('Actions'));
            }
        }
    }
}
