// Copyright (c) 2026, Quanti and contributors
// For license information, please see license.txt

frappe.ui.form.on('AP Purchase Order', {
    onload: function(frm) {
        if (frm.is_new() && !frm.doc.spoc_user && frappe.session.user && frappe.session.user !== 'Guest') {
            frm.set_value('spoc_user', frappe.session.user);
        }
    },

    refresh: function(frm) {
        if (frm.doc.docstatus === 0) {
            frm.enable_save();
            if (frm.page.btn_primary) {
                frm.page.btn_primary.show().removeClass('hide');
            }
        }
        $(frm.wrapper).off('dirty.ap_po_save_guard').on('dirty.ap_po_save_guard', function() {
            if (frm.doc.docstatus === 0 && frm.page && frm.page.btn_primary) {
                frm.enable_save();
                frm.page.btn_primary.show().removeClass('hide');
            }
        });
        frm.set_df_property('status', 'read_only', 1);
        let is_draft = (!frm.doc.status || frm.doc.status === 'Draft');
        frm.set_df_property('items', 'read_only', !is_draft);
        frm.set_df_property('vendor', 'read_only', !is_draft);
        frm.set_df_property('company_entity', 'read_only', !is_draft);
        frm.set_df_property('advance_percentage', 'read_only', !is_draft);
        frm.set_df_property('payment_terms_clause', 'read_only', !is_draft);
        frm.set_df_property('authorised_signatory', 'read_only', !is_draft);
        frm.set_df_property('signatory_name', 'read_only', !is_draft);

        render_entity_letterhead_banner(frm);
        render_custom_po_actions(frm);
        if (!frm.is_new()) {
            frappe.db.get_list('Vendor Invoice Claim Item', {
                filters: { purchase_order: frm.doc.name, bill_payment_type: 'Advance / Part Payment' },
                fields: ['parent'],
                distinct: 1
            }, function(res) {
                if (res && res.length > 0) {
                    let adv_claims = [...new Set(res.map(x => x.parent))];
                    adv_claims.forEach(cname => {
                        frm.add_custom_button(__('View Advance: {0}', [cname]), function() {
                            frappe.set_route('Form', 'Vendor Invoice Claim', cname);
                        }, __('Linked Advance Claims'));
                    });
                }
            });
        }
        update_dynamic_commercial_pills(frm);
        setup_dynamic_signatory_options(frm);
        if (frm.is_new() && frm.doc.spoc_user && !frm.doc.spoc_department) {
            frm.trigger('spoc_user');
        }
    },

    company_entity: function(frm) {
        if (!frm.doc.company_entity) return;

        frappe.call({
            method: 'ap_automation.services.po_pdf_service.get_company_po_defaults',
            args: {
                company_name: frm.doc.company_entity
            },
            callback: function(r) {
                if (r.message) {
                    let d = r.message;
                    if (d.gstin) frm.set_value('company_gstin', d.gstin);
                    if (d.cin) frm.set_value('company_cin', d.cin);
                    if (d.registered_address) frm.set_value('company_registered_address', d.registered_address);

                    if (d.signatory_name) frm.set_value('signatory_name', d.signatory_name);
                    if (d.signatory_designation) frm.set_value('signatory_designation', d.signatory_designation);
                    if (d.business_head_user) frm.set_value('authorised_signatory', d.business_head_user);

                    // Dynamically build dropdown options from Company record
                    let opts = [];
                    if (d.signatory_name) opts.push(d.signatory_name);
                    if (d.alternate_name && !opts.includes(d.alternate_name)) {
                        opts.push(d.alternate_name);
                    }
                    if (opts.length > 0) {
                        frm.set_df_property('signatory_name', 'options', opts.join('\n'));
                        frm.refresh_field('signatory_name');
                    }
                }
                frm.trigger('calculate_totals');
                render_entity_letterhead_banner(frm);
            }
        });
    },

    signatory_name: function(frm) {
        if (!frm.doc.company_entity || !frm.doc.signatory_name) return;

        frappe.call({
            method: 'ap_automation.services.po_pdf_service.get_signatory_designation_for_company',
            args: {
                company_name: frm.doc.company_entity,
                signatory_name: frm.doc.signatory_name
            },
            callback: function(r) {
                if (r.message) {
                    if (r.message.designation) frm.set_value('signatory_designation', r.message.designation);
                    if (r.message.user) frm.set_value('authorised_signatory', r.message.user);
                }
            }
        });
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
                    if (r.full_name) frm.set_value('spoc_name', r.full_name);
                    if (r.email) frm.set_value('spoc_email', r.email);
                    if (r.mobile_no && !frm.doc.spoc_mobile) frm.set_value('spoc_mobile', r.mobile_no);
                }
            });

            frappe.call({
                method: 'ap_automation.ap_automation.doctype.ap_purchase_order.ap_purchase_order.get_user_department_details',
                args: { user_id: frm.doc.spoc_user },
                callback: function(r) {
                    if (r && r.message) {
                        if (r.message.department && !frm.doc.spoc_department) {
                            frm.set_value('spoc_department', r.message.department);
                        }
                        if (r.message.mobile && !frm.doc.spoc_mobile) {
                            frm.set_value('spoc_mobile', r.message.mobile);
                        }
                    }
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

function setup_dynamic_signatory_options(frm) {
    if (!frm.doc.company_entity) return;
    frappe.db.get_value('Company', frm.doc.company_entity, ['ap_signatory_name', 'ap_alternate_name'], function(r) {
        if (r) {
            let opts = [];
            if (r.ap_signatory_name) opts.push(r.ap_signatory_name);
            if (r.ap_alternate_name && !opts.includes(r.ap_alternate_name)) {
                opts.push(r.ap_alternate_name);
            }
            if (opts.length > 0) {
                frm.set_df_property('signatory_name', 'options', opts.join('\n'));
                frm.refresh_field('signatory_name');
            }
        }
    });
}

function render_entity_letterhead_banner(frm) {
    let entity = frm.doc.company_entity || "Company Entity";
    let gstin = frm.doc.company_gstin || "GSTIN Pending";
    let cin = frm.doc.company_cin || "CIN Pending";
    let addr = frm.doc.company_registered_address || "Registered Address Pending";

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

    let sign_status = frm.doc.status || "Draft";
    let sign_badge = `<span class="badge badge-secondary">${sign_status}</span>`;
    if (sign_status === "Active PO" || frm.doc.signatory_signature_hash) {
        sign_badge = `<span class="badge badge-success" style="background-color: #107C41; color: white;">✔ Digitally Signed & Active</span>`;
    }

    let dashboard_html = `
    <div class="ap-po-dashboard" style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
        <div style="flex: 1; min-width: 200px; background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid #1B365D; padding: 12px 16px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Grand Total (Inc GST)</div>
            <div style="font-size: 20px; font-weight: 800; color: #1e293b; margin: 4px 0;">₹ ${format_currency(grand)}</div>
            <div style="font-size: 11px; color: #475569;">${gst_label}</div>
        </div>

        <div style="flex: 1; min-width: 200px; background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Advance Payable Now</div>
                ${frm.doc.status === "Active PO" ? `<button type="button" class="btn btn-xs ap-card-request-adv-btn" style="background-color: #b45309; color: #ffffff; border: none; border-radius: 4px; font-weight: 700; padding: 2px 8px; font-size: 10px; cursor: pointer;">Request Advance</button>` : ''}
            </div>
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
            <div style="font-size: 11px; color: #475569;">Signatory: <b>${frm.doc.signatory_name || 'Authorised Signatory'}</b></div>
        </div>
    </div>
    `;

    if (frm.dashboard && typeof frm.dashboard.clear_headline === "function") {
        frm.dashboard.clear_headline();
    }
    if (frm.layout && frm.layout.message) {
        frm.layout.message.find(".ap-po-dashboard").closest(".form-message").remove();
        frm.layout.message.find(".ap-po-dashboard").remove();
    }
    $(frm.wrapper).find(".ap-po-dashboard").closest(".form-message").remove();
    $(frm.wrapper).find(".ap-po-dashboard").remove();
    frm.dashboard.set_headline(dashboard_html, "white", true);
    $(frm.wrapper).off("click", ".ap-card-request-adv-btn").on("click", ".ap-card-request-adv-btn", function(e) {
        e.preventDefault();
        open_po_advance_request_dialog(frm);
    });

    if (frm.doc.status === "Active PO" && adv > 0 && !frm.is_new()) {
        frappe.db.get_value("Vendor Invoice Item", {
            purchase_order: frm.doc.name,
            bill_payment_type: "Advance / Part Payment"
        }, ["parent", "line_status"], function(res) {
            if (res && res.parent) {
                frappe.db.get_value("Vendor Invoice Claim", res.parent, ["status", "utr"], function(cres) {
                    if (cres) {
                        let st = cres.status || "Pending";
                        let utr_info = cres.utr ? ` &bull; UTR: <code>${cres.utr}</code>` : "";
                        let adv_pill = `<div style="font-size: 11px; margin-top: 6px; padding: 3px 8px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 4px; color: #92400e; font-weight: 700;">Claim #${res.parent} (${st})${utr_info}</div>`;
                        $(frm.wrapper).find('.ap-po-adv-claim-pill').remove();
                        $(frm.wrapper).find('.ap-po-dashboard').children().eq(1).append(`<div class="ap-po-adv-claim-pill">${adv_pill}</div>`);
                    }
                });
            }
        });
    }
}

function render_custom_po_actions(frm) {
    if (frm.is_new()) return;

    // 1. Download PO PDF Button (Universal)
    frm.add_custom_button(__('Download PO (PDF)'), function() {
        const url = `/api/method/ap_automation.services.po_pdf_service.download_purchase_order_pdf?po_name=${encodeURIComponent(frm.doc.name)}`;
        window.open(url, '_blank');
    }).addClass('btn-secondary');

    // 2. Draft Status: Submit for Dynamic Approval Workflow
    if (frm.doc.status === 'Draft' || !frm.doc.status) {
        frm.add_custom_button(__('Submit for Approval'), function() {
            frappe.confirm(
                `Are you sure you want to submit Purchase Order <strong>#${frm.doc.name}</strong> for approval?`,
                function() {
                    frappe.call({
                        method: 'submit_po',
                        doc: frm.doc,
                        freeze: true,
                        freeze_message: __('Submitting PO for Approval...'),
                        callback: function(r) {
                            if (!r.exc) {
                                frappe.show_alert({ message: __('Purchase Order submitted successfully.'), indicator: 'green' });
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
        }).addClass('btn-primary').css({
            'background-color': '#1d4ed8',
            'border-color': '#1e40af',
            'color': '#ffffff',
            'font-weight': '700'
        });
    }

    // 3. Stage 1: Pending Assistant Manager Review (Admin Dept)
    if (frm.doc.status === 'Pending Assistant Manager Review') {
        frm.add_custom_button(__('Recommend and Forward to Manager'), function() {
            frappe.prompt([
                { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Review Remarks'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'review_by_assistant_manager',
                    doc: frm.doc,
                    args: { remarks: values.remarks },
                    freeze: true,
                    freeze_message: __('Forwarding PO to Manager...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Purchase Order reviewed and forwarded to Manager.'), indicator: 'green' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Assistant Manager Review'), __('Forward to Manager'));
        }).addClass('btn-primary');

        frm.add_custom_button(__('Return to Requester'), function() {
            frappe.prompt([
                { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Return Reason / Discrepancy Remarks'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'return_po',
                    doc: frm.doc,
                    args: { remarks: values.remarks },
                    freeze: true,
                    freeze_message: __('Returning PO to Draft...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Purchase Order returned to Draft.'), indicator: 'orange' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Return Purchase Order'), __('Return to Draft'));
        }).addClass('btn-danger');
    }

    // 4. Stage 2: Pending Manager Review (Admin Manager or Department Manager)
    if (frm.doc.status === 'Pending Manager Review' || frm.doc.status === 'Pending Admin Manager Review') {
        frm.add_custom_button(__('Approve and Forward to Director'), function() {
            frappe.prompt([
                { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Manager Review Remarks'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'review_by_manager',
                    doc: frm.doc,
                    args: { remarks: values.remarks },
                    freeze: true,
                    freeze_message: __('Forwarding PO to Director...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Purchase Order approved and forwarded to Director.'), indicator: 'green' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Manager Approval Review'), __('Forward to Director'));
        }).addClass('btn-primary');

        frm.add_custom_button(__('Return PO'), function() {
            frappe.prompt([
                { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Return Reason / Discrepancy Remarks'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'return_po',
                    doc: frm.doc,
                    args: { remarks: values.remarks },
                    freeze: true,
                    freeze_message: __('Returning PO...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Purchase Order returned.'), indicator: 'orange' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Return Purchase Order'), __('Return PO'));
        }).addClass('btn-danger');
    }

    // 5. Stage 3: Pending HoD / Director Approval
    if (frm.doc.status === 'Pending HoD Approval') {
        let current_user = frappe.session.user;
        let is_signatory = (frm.doc.authorised_signatory && frm.doc.authorised_signatory === current_user);
        let is_admin = frappe.user.has_role('System Manager') || current_user === 'Administrator';
        let is_director = frappe.user.has_role('AP Director') || frappe.user.has_role('Director') || frappe.user.has_role('Accounts Director');

        if (is_signatory || is_admin || is_director) {
            // Approve & Sign Button
            frm.add_custom_button(__('Approve and Sign PO'), function() {
                let current_sig = frm.doc.signatory_name || 'Director';
                frappe.confirm(
                    `Are you sure you want to approve and digitally sign Purchase Order <strong>#${frm.doc.name}</strong> as <strong>${current_sig}</strong>?<br><small style="color: #64748b;">This will apply your digital SHA-256 seal and automatically dispatch the E-Sign link to the vendor.</small>`,
                    function() {
                        frappe.call({
                            method: 'ap_automation.services.po_pdf_service.approve_and_digitally_sign_po',
                            args: {
                                po_name: frm.doc.name,
                                signatory_name: frm.doc.signatory_name
                            },
                            freeze: true,
                            freeze_message: __('Certifying Digital Signature and Dispatching to Vendor...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'success') {
                                    frappe.show_alert({
                                        message: __('Purchase Order approved and certified by ' + r.message.signatory_name + '. Dispatched to vendor.'),
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

            // Return Button
            frm.add_custom_button(__('Return to Reviewer'), function() {
                frappe.prompt([
                    { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Return Reason / Discrepancy Remarks'), reqd: 1 }
                ], function(values) {
                    frappe.call({
                        method: 'return_po',
                        doc: frm.doc,
                        args: { remarks: values.remarks },
                        freeze: true,
                        freeze_message: __('Returning PO...'),
                        callback: function(r) {
                            if (!r.exc) {
                                frappe.show_alert({ message: __('Purchase Order returned.'), indicator: 'orange' });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Return Purchase Order'), __('Return'));
            }).addClass('btn-danger').css({
                'background-color': '#dc2626',
                'border-color': '#b91c1c',
                'color': '#ffffff',
                'font-weight': '700'
            });
        }
    }

    // 6. Active PO Actions: Request Advance & Revise PO
    if (frm.doc.status === 'Active PO') {
        frm.add_custom_button(__('Request PO Advance'), function() {
            open_po_advance_request_dialog(frm);
        }).addClass('btn-primary').css({
            'background-color': '#b45309',
            'border-color': '#92400e',
            'color': '#ffffff',
            'font-weight': '700'
        });

        frm.add_custom_button(__('Request PO Advance'), function() {
            open_po_advance_request_dialog(frm);
        }, __('Actions'));

        frm.add_custom_button(__('Revise Purchase Order'), function() {
            frappe.prompt([
                { fieldname: 'reason', fieldtype: 'Small Text', label: __('Revision Reason / Scope Expansion Details'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'revise_po',
                    doc: frm.doc,
                    args: { reason: values.reason },
                    freeze: true,
                    freeze_message: __('Creating Revision Version...'),
                    callback: function(r) {
                        if (r.message && r.message.new_po_name) {
                            frappe.show_alert({
                                message: __('Purchase Order revised. Opening revision #' + r.message.new_po_name),
                                indicator: 'green'
                            });
                            frappe.set_route('Form', 'AP Purchase Order', r.message.new_po_name);
                        }
                    }
                });
            }, __('Revise Purchase Order'), __('Create Revision'));
        }, __('Actions'));
    }

    // 7. Cancellation Action (Allowed on Draft, Review Stages, or Active PO)
    if (!['Cancelled', 'Superseded / Revised'].includes(frm.doc.status)) {
        frm.add_custom_button(__('Cancel Purchase Order'), function() {
            frappe.prompt([
                { fieldname: 'reason', fieldtype: 'Small Text', label: __('Cancellation Remarks / Reason'), reqd: 1 }
            ], function(values) {
                frappe.call({
                    method: 'cancel_po',
                    doc: frm.doc,
                    args: { reason: values.reason },
                    freeze: true,
                    freeze_message: __('Cancelling Purchase Order...'),
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.show_alert({ message: __('Purchase Order cancelled.'), indicator: 'red' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Cancel Purchase Order'), __('Confirm Cancellation'));
        }, __('Actions'));
    }

    // 8. Awaiting Vendor E-Signature Status
    if (frm.doc.status === 'Awaiting Vendor E-Signature') {
        frm.add_custom_button(__('Resend E-Sign Link'), function() {
            frappe.call({
                method: 'send_po_to_vendor_for_esign',
                doc: frm.doc,
                freeze: true,
                freeze_message: __('Resending E-Sign Link to Vendor...'),
                callback: function() {
                    frappe.show_alert({ message: __('E-Sign link resent to ' + frm.doc.vendor_email), indicator: 'green' });
                }
            });
        }, __('Actions'));
    }

    // 9. Actions menu for link sharing
    if (frm.doc.vendor_sign_url) {
        frm.add_custom_button(__('Copy E-Sign Link'), function() {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(frm.doc.vendor_sign_url).then(() => {
                    frappe.show_alert({
                        message: __('Vendor E-Sign Portal URL copied to clipboard.'),
                        indicator: 'green'
                    }, 5);
                });
            } else {
                frappe.prompt([
                    { fieldname: 'sign_url', fieldtype: 'Small Text', label: 'Vendor Signing URL', default: frm.doc.vendor_sign_url, read_only: 1 }
                ], null, __('Vendor Signing URL'));
            }
        }, __('Actions'));

        frm.add_custom_button(__('Open Signing Portal'), function() {
            window.open(frm.doc.vendor_sign_url, '_blank');
        }, __('Actions'));
    }
}

function open_po_advance_request_dialog(frm) {
    const adv_amt = flt(frm.doc.advance_amount) || 0.0;
    const po_val = flt(frm.doc.grand_total) || flt(frm.doc.net_taxable_value) || 0.0;
    
    let d = new frappe.ui.Dialog({
        title: __('Request Purchase Order Advance Payment'),
        fields: [
            {
                fieldname: 'sec_info',
                fieldtype: 'HTML',
                options: `
                    <div style="background: #fefce8; border: 1px solid #fef08a; border-left: 4px solid #eab308; padding: 12px 14px; border-radius: 6px; margin-bottom: 12px; font-size: 13px; color: #854d0e;">
                        <b>PO Advance Disbursement:</b> Requesting advance payment for <b>${frappe.utils.escape_html(frm.doc.vendor_name || frm.doc.vendor)}</b> against Purchase Order <b>#${frm.doc.name}</b> (Total Value: <b>₹ ${format_currency(po_val)}</b>).
                    </div>
                `
            },
            {
                fieldname: 'advance_amount',
                fieldtype: 'Currency',
                label: __('Advance Amount to Pay (INR)'),
                reqd: 1,
                default: adv_amt > 0 ? adv_amt : '',
                description: __('Enter the advance or milestone amount to disburse (Max: PO Total Value).')
            },
            {
                fieldname: 'gst_rate',
                fieldtype: 'Select',
                label: __('GST Rate on Advance'),
                options: ['0%', '5%', '12%', '18%', '28%'],
                default: (frm.doc.items && frm.doc.items.length > 0 && frm.doc.items[0].gst_rate) ? frm.doc.items[0].gst_rate : '0%',
                reqd: 1,
                description: __('Select GST rate for this advance (defaulted from PO item).')
            },
            {
                fieldname: 'proforma_number',
                fieldtype: 'Data',
                label: __('Vendor Proforma Invoice / Demand Ref #'),
                reqd: 1,
                description: __('Enter the vendor\'s Proforma Invoice number or advance payment request reference.')
            },
            {
                fieldname: 'proforma_date',
                fieldtype: 'Date',
                label: __('Proforma Date'),
                reqd: 1,
                default: frappe.datetime.get_today()
            },
            {
                fieldname: 'proforma_attachment',
                fieldtype: 'Attach',
                label: __('Attach Proforma Invoice / Quotation Copy (PDF / Photo)'),
                reqd: 1
            },
            {
                fieldname: 'remarks',
                fieldtype: 'Small Text',
                label: __('Advance Remarks / Milestone Notes (Optional)'),
                default: `Advance payment requested against ${frm.doc.advance_percentage || 'agreed'} PO terms.`
            }
        ],
        primary_action_label: __('Submit Advance Request'),
        primary_action: function(values) {
            if (flt(values.advance_amount) <= 0) {
                frappe.msgprint(__('Advance Amount must be greater than 0.00.'));
                return;
            }
            if (flt(values.advance_amount) > po_val && po_val > 0) {
                frappe.msgprint(__('Advance Amount cannot exceed the total PO value (₹ {0}).', [format_currency(po_val)]));
                return;
            }
            if (!values.proforma_number || !values.proforma_number.trim()) {
                frappe.msgprint(__('Vendor Proforma Invoice / Demand Ref # is mandatory.'));
                return;
            }
            if (!values.proforma_attachment) {
                frappe.msgprint(__('Please upload the vendor\'s Proforma Invoice or quote copy.'));
                return;
            }

            d.hide();
            frappe.call({
                method: 'ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim.create_po_advance_claim',
                args: {
                    po_name: frm.doc.name,
                    advance_amount: values.advance_amount,
                    gst_rate: values.gst_rate || '0%',
                    proforma_number: values.proforma_number.trim(),
                    proforma_date: values.proforma_date,
                    proforma_attachment: values.proforma_attachment,
                    remarks: values.remarks || ''
                },
                freeze: true,
                freeze_message: __('Creating and Submitting Advance Claim for Accounts Review...'),
                callback: function(r) {
                    if (r && r.message && r.message.status === 'success') {
                        let cname = r.message.claim_name;
                        frappe.show_alert({
                            message: __('Advance Claim #{0} created successfully! Directing to claim...', [cname]),
                            indicator: 'green'
                        }, 5);
                        frappe.set_route('Form', 'Vendor Invoice Claim', cname);
                    }
                }
            });
        }
    });

    d.show();
}

// Global realtime listener for instant desk notification when vendor signs
if (frappe.realtime) {
    frappe.realtime.off('po_vendor_signed');
    frappe.realtime.on('po_vendor_signed', function(data) {
        if (cur_frm && cur_frm.doc && cur_frm.doc.name === data.po_name) {
            frappe.show_alert({
                message: __(data.text || 'Purchase Order digitally signed by vendor. It is now active.'),
                indicator: 'green'
            }, 10);
            cur_frm.reload_doc();
        }
    });
}
