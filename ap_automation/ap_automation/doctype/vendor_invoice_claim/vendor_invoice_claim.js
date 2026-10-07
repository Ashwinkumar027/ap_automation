// Copyright (c) 2026, Quanti and contributors
// Production-grade Vendor Invoice Claim UI controller with live 3-Way Match, TDS Calculator & Receipt Gallery

frappe.ui.form.on("Vendor Invoice Claim", {
    refresh: function(frm) {
        frm.trigger("toggle_route_fields");
        render_vendor_invoice_header(frm);
        setup_receipt_gallery_button(frm);
    },

    invoice_type: function(frm) {
        frm.trigger("toggle_route_fields");
        render_vendor_invoice_header(frm);
    },

    tax_invoice_attachment: function(frm) {
        setup_receipt_gallery_button(frm);
    },

    email_approval_attachment: function(frm) {
        setup_receipt_gallery_button(frm);
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

function setup_receipt_gallery_button(frm) {
    if (window.APReceiptGallery && typeof window.APReceiptGallery.setup === "function") {
        window.APReceiptGallery.setup(frm);
    } else {
        // Fallback dedicated button
        let has_files = frm.doc.tax_invoice_attachment || frm.doc.email_approval_attachment;
        if (has_files) {
            frm.add_custom_button(__("🖼️ View Attached Receipts"), function () {
                let url = frm.doc.tax_invoice_attachment || frm.doc.email_approval_attachment;
                window.open(url, "_blank");
            }).addClass("btn-primary").css({
                "background": "linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)",
                "color": "#ffffff",
                "font-weight": "600"
            });
        }
    }
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
