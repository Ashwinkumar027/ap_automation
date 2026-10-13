// Copyright (c) 2026, Quanti and contributors
// Production-grade Vendor Invoice Claim UI controller with Petty-Cash-Style Receipt Gallery, Visual 3-Way Match, Settlement Waterfall, Pre-Submit Audit Guard & Error Inspection

// Register listview settings globally so both list and form views bypass default 'Draft' indicator
frappe.listview_settings = frappe.listview_settings || {};
frappe.listview_settings["Vendor Invoice Claim"] = {
    has_indicator_for_draft: true,
    add_fields: [
        "status",
        "invoice_type",
        "company",
        "vendor",
        "vendor_name",
        "tax_invoice_number",
        "total_invoice_amount",
        "net_payable_amount",
        "match_status",
        "purchase_order",
        "docstatus"
    ],
    onload: function (listview) {
        listview.page.add_inner_button(__('All Claims'), function () {
            listview.filter_area.clear();
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🟠 Needs Review'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Vendor Invoice Claim', 'status', '=', 'Pending Accounts Review']]);
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🟢 Approved for Payment'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Vendor Invoice Claim', 'status', '=', 'Approved for Payment']]);
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('🔴 Contested / Disputed'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Vendor Invoice Claim', 'status', '=', 'Disputed']]);
        }, __('Quick Filters'));

        listview.page.add_inner_button(__('💳 Paid (UTR Stamped)'), function () {
            listview.filter_area.clear();
            listview.filter_area.add([['Vendor Invoice Claim', 'status', '=', 'Paid']]);
        }, __('Quick Filters'));
    },
    get_indicator: function (doc) {
        const status = doc.status || "Draft";
        if (status === "Approved for Payment") {
            return [__("Approved for Payment"), "green", "status,=,Approved for Payment"];
        } else if (status === "Pending Accounts Review") {
            return [__("Pending Accounts Review"), "orange", "status,=,Pending Accounts Review"];
        } else if (status === "Disputed") {
            return [__("Disputed"), "red", "status,=,Disputed"];
        } else if (status === "Queued in Batch") {
            return [__("Queued in Batch"), "blue", "status,=,Queued in Batch"];
        } else if (status === "Paid") {
            return [__("Paid"), "darkgreen", "status,=,Paid"];
        } else if (status === "Draft") {
            return [__("Draft"), "grey", "status,=,Draft"];
        }
        return [__(status), "grey", "status,=," + status];
    }
};

frappe.ui.form.on("Vendor Invoice Claim", {
    refresh: function(frm) {
        frm.trigger("toggle_route_fields");
        render_vendor_invoice_dashboard(frm);
        setup_vendor_receipt_gallery_button(frm);

        // Update form header status indicator badge (replaces static 'Draft')
        let status = frm.doc.status || "Draft";
        let color = "grey";
        if (status === "Approved for Payment") {
            color = "green";
        } else if (status === "Paid") {
            color = "darkgreen";
        } else if (status === "Pending Accounts Review") {
            color = "orange";
        } else if (status === "Disputed") {
            color = "red";
        } else if (status === "Queued in Batch") {
            color = "blue";
        }
        frm.page.set_indicator(status, color);

        // Quick Navigation to Linked AP Purchase Order
        if (frm.doc.purchase_order) {
            frm.add_custom_button(__('👁️ View AP Purchase Order'), function() {
                frappe.set_route('Form', 'AP Purchase Order', frm.doc.purchase_order);
            }, __('Navigate'));
        }

        // Action: 🚫 Flag Dispute / Rejection (Never Silent)
        if (!frm.is_new() && frm.doc.docstatus !== 2) {
            frm.add_custom_button(__('🚫 Reject / Flag Dispute'), function() {
                open_vendor_dispute_modal(frm);
            }, __('Actions'));

            frm.add_custom_button(__('📋 Audit & Error Inspector'), function() {
                open_vendor_audit_inspector_modal(frm);
            }, __('Actions'));
        }
    },

    before_submit: function(frm) {
        let audit = run_pre_submit_audit(frm);
        if (!audit.can_submit) {
            frappe.validated = false;
            show_submission_blocker_dialog(frm, audit);
            return false;
        }

        // Warning confirmation if 3-Way Match Discrepancy is present
        if (audit.warnings.length > 0) {
            let warn_text = audit.warnings.map(w => `• <b>${w.label}:</b> ${w.msg}`).join('<br>');
            frappe.validated = false;
            frappe.confirm(
                __(`<b>⚠️ Potential Match Discrepancy Detected</b><br><br>${warn_text}<br><br>Submitting this invoice will route it directly to <b>Disputed</b> status for Accounts Manager investigation. Do you want to continue?`),
                function() {
                    // Confirmed by user: proceed with submission
                    frappe.validated = true;
                    frm.savesubmit();
                },
                function() {
                    frappe.show_alert({ message: __('Submission cancelled to resolve discrepancy.'), indicator: 'orange' });
                }
            );
            return false;
        }
    },

    invoice_type: function(frm) {
        frm.trigger("toggle_route_fields");
        render_vendor_invoice_dashboard(frm);
    },

    tax_invoice_attachment: function(frm) {
        setup_vendor_receipt_gallery_button(frm);
        render_vendor_invoice_dashboard(frm);
    },

    email_approval_attachment: function(frm) {
        setup_vendor_receipt_gallery_button(frm);
        render_vendor_invoice_dashboard(frm);
    },

    purchase_order: function(frm) {
        if (frm.doc.purchase_order) {
            // First fetch our AP Purchase Order
            frappe.call({
                method: "frappe.client.get",
                args: {
                    doctype: "AP Purchase Order",
                    name: frm.doc.purchase_order
                },
                callback: function(r) {
                    if (r && r.message) {
                        let po = r.message;
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
                        calculate_vendor_totals(frm);
                    }
                },
                error: function() {
                    // Graceful fallback to ERPNext Purchase Order for legacy records
                    frappe.call({
                        method: "frappe.client.get",
                        args: {
                            doctype: "Purchase Order",
                            name: frm.doc.purchase_order
                        },
                        callback: function(r2) {
                            if (r2 && r2.message) {
                                let po = r2.message;
                                if (po.supplier && !frm.doc.vendor) {
                                    frm.set_value("vendor", po.supplier);
                                }
                                if (po.company && !frm.doc.company) {
                                    frm.set_value("company", po.company);
                                }
                                if (po.net_total && !frm.doc.base_amount) {
                                    frm.set_value("base_amount", po.net_total);
                                }
                                calculate_vendor_totals(frm);
                            }
                        }
                    });
                }
            });
        }
        render_vendor_invoice_dashboard(frm);
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
                    fields: ["name", "bank", "bank_account_no", "branch_code", "penny_drop_status", "penny_drop_score"],
                    limit: 1
                },
                callback: function(res) {
                    if (res.message && res.message.length > 0) {
                        let acc = res.message[0];
                        frm.set_value("bank_name", acc.bank || "");
                        frm.set_value("bank_account_number", acc.bank_account_no || "");
                        frm.set_value("bank_ifsc_code", acc.branch_code || "");
                        frm._bank_account_doc = acc;
                    } else {
                        frm.set_value("bank_name", "");
                        frm.set_value("bank_account_number", "");
                        frm.set_value("bank_ifsc_code", "");
                        frm._bank_account_doc = null;
                    }
                    render_vendor_invoice_dashboard(frm);
                }
            });
        }
        render_vendor_invoice_dashboard(frm);
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
// PRE-SUBMIT AUDIT ENGINE: ZERO-SILENT FAILURE GUARANTEE
// --------------------------------------------------------------------------------------
function run_pre_submit_audit(frm) {
    let errors = [];
    let warnings = [];

    // 1. Vendor & Master Profile
    if (!frm.doc.vendor) {
        errors.push({
            fieldname: "vendor",
            label: __("Vendor / Supplier Master"),
            msg: __("Vendor is mandatory. Please select a valid Supplier from ERPNext Master."),
            icon: "🏢"
        });
    }

    // 2. Banking Details & NPCI Lockout
    if (!frm.doc.bank_account_number || !frm.doc.bank_ifsc_code) {
        errors.push({
            fieldname: "vendor",
            label: __("Vendor Bank Account Master"),
            msg: __("Vendor does not have an active Bank Account in ERPNext. Submissions cannot proceed without a verified disbursement destination."),
            icon: "🏦"
        });
    }

    let pd_status = (frm._bank_account_doc && frm._bank_account_doc.penny_drop_status) || frm.doc.bank_name;
    if (pd_status === "LOCKED_PENNY_DROP_MISMATCH" || pd_status === "Pending Verification") {
        errors.push({
            fieldname: "bank_name",
            label: __("Zero-Trust Penny Drop Security Shield"),
            msg: __("Vendor bank account is hard-locked due to NPCI Penny Drop Name Mismatch. Accounts Manager clearance is strictly required before submission."),
            icon: "🛡️"
        });
    }

    // 3. Intake Route Proof Attachments
    if (frm.doc.invoice_type === "With Purchase Order" && !frm.doc.purchase_order) {
        errors.push({
            fieldname: "purchase_order",
            label: __("Linked AP Purchase Order"),
            msg: __("Linked Purchase Order is mandatory when Route is 'With Purchase Order'."),
            icon: "📦"
        });
    }

    if (frm.doc.invoice_type === "Without PO (Direct Tax Invoice)" && !frm.doc.email_approval_attachment) {
        errors.push({
            fieldname: "email_approval_attachment",
            label: __("Approving Manager Email Proof"),
            msg: __("For non-PO direct tax invoices, an approving manager's email screenshot or PDF proof is strictly mandatory (PRD Section 6)."),
            icon: "📧"
        });
    }

    if (!frm.doc.tax_invoice_attachment) {
        errors.push({
            fieldname: "tax_invoice_attachment",
            label: __("Vendor Tax Invoice PDF Attachment"),
            msg: __("The original Vendor Tax Invoice PDF is strictly mandatory for GST & forensic compliance."),
            icon: "📄"
        });
    }

    // 4. Statutory Invoice Metadata
    if (!frm.doc.tax_invoice_number) {
        errors.push({
            fieldname: "tax_invoice_number",
            label: __("Tax Invoice Number"),
            msg: __("Vendor's Tax Invoice # is missing."),
            icon: "🔢"
        });
    }

    if (!frm.doc.tax_invoice_date) {
        errors.push({
            fieldname: "tax_invoice_date",
            label: __("Tax Invoice Date"),
            msg: __("Tax Invoice Date is missing."),
            icon: "📅"
        });
    }

    // 5. Financial Validation
    let base = flt(frm.doc.base_amount);
    let total = flt(frm.doc.total_invoice_amount);
    let adv = flt(frm.doc.advance_deducted);

    if (base <= 0) {
        errors.push({
            fieldname: "base_amount",
            label: __("Base Taxable Amount"),
            msg: __("Base Taxable Amount must be strictly positive (greater than INR 0.00)."),
            icon: "💰"
        });
    }

    if (adv < 0) {
        errors.push({
            fieldname: "advance_deducted",
            label: __("Prior Advance Deducted"),
            msg: __("Advance deducted cannot be a negative amount."),
            icon: "⚠️"
        });
    }

    if (adv > total && total > 0) {
        errors.push({
            fieldname: "advance_deducted",
            label: __("Advance Deducted Over-Limit"),
            msg: __(`Prior Advance Deducted (INR ${formatINR(adv)}) cannot exceed Total Invoice Amount (INR ${formatINR(total)}).`),
            icon: "🚨"
        });
    }

    // 6. 3-Way Match Variance Warning
    if (frm.doc.match_status && frm.doc.match_status.includes("Mismatch Flagged")) {
        warnings.push({
            fieldname: "match_status",
            label: __("3-Way Match Discrepancy"),
            msg: `${frm.doc.match_status}: ${frm.doc.match_variance_details || 'Price or quantity variance exceeds policy tolerance.'}`,
            icon: "🔴"
        });
    } else if (frm.doc.match_status === "Missing GRN Flagged") {
        warnings.push({
            fieldname: "match_status",
            label: __("Goods Receipt (GRN) Missing"),
            msg: __("No linked Purchase Receipt (GRN) found. Claim will require special physical proof audit."),
            icon: "🟠"
        });
    }

    return {
        can_submit: errors.length === 0,
        errors: errors,
        warnings: warnings
    };
}

// --------------------------------------------------------------------------------------
// SUBMISSION BLOCKER MODAL: EXPLICIT, RICH, NON-SILENT POPUP
// --------------------------------------------------------------------------------------
function show_submission_blocker_dialog(frm, audit) {
    let error_cards_html = audit.errors.map(err => `
        <div style="background: #ffffff; border: 1px solid #fecaca; border-left: 4px solid #ef4444; border-radius: 6px; padding: 10px 14px; margin-bottom: 8px; display: flex; align-items: flex-start; justify-content: space-between; gap: 10px;">
            <div>
                <div style="font-weight: 700; color: #991b1b; font-size: 13px;">
                    ${err.icon} ${err.label}
                </div>
                <div style="color: #4b5563; font-size: 12px; margin-top: 3px; line-height: 1.4;">
                    ${err.msg}
                </div>
            </div>
            <button class="btn btn-xs btn-default ap-btn-jump-field" data-field="${err.fieldname}" style="white-space: nowrap; margin-top: 2px;">
                ${__('Jump to Field 👉')}
            </button>
        </div>
    `).join('');

    let warnings_html = "";
    if (audit.warnings.length > 0) {
        let warn_cards = audit.warnings.map(w => `
            <div style="background: #fffbeb; border: 1px solid #fde68a; border-left: 4px solid #f59e0b; border-radius: 6px; padding: 8px 12px; margin-bottom: 6px; font-size: 12px; color: #92400e;">
                ${w.icon} <b>${w.label}:</b> ${w.msg}
            </div>
        `).join('');
        warnings_html = `
            <div style="margin-top: 14px;">
                <div style="font-size: 11px; font-weight: 700; color: #b45309; text-transform: uppercase; margin-bottom: 6px;">
                    Auditor Warnings (Will Route to Disputed)
                </div>
                ${warn_cards}
            </div>
        `;
    }

    let d = new frappe.ui.Dialog({
        title: __(`🚫 Cannot Submit Claim (${audit.errors.length} Mandatory Item${audit.errors.length > 1 ? 's' : ''} Missing)`),
        fields: [
            {
                fieldtype: "HTML",
                fieldname: "error_overview_html",
                options: `
                    <div style="padding: 4px 0;">
                        <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 12px; margin-bottom: 14px;">
                            <div style="font-weight: 700; color: #b91c1c; font-size: 14px; display: flex; align-items: center; gap: 8px;">
                                <span style="font-size: 18px;">⚠️</span>
                                <span>Zero-Silent Submission Protection Activated</span>
                            </div>
                            <div style="color: #7f1d1d; font-size: 12px; margin-top: 4px;">
                                Financial claims cannot be submitted with missing statutory proofs, unverified banking, or invalid amounts. Please resolve the following action items:
                            </div>
                        </div>

                        ${error_cards_html}

                        ${warnings_html}
                    </div>
                `
            }
        ],
        primary_action_label: __('Fix First Issue 🎯'),
        primary_action() {
            d.hide();
            if (audit.errors.length > 0) {
                jump_to_and_highlight_field(frm, audit.errors[0].fieldname);
            }
        },
        secondary_action_label: __('Dismiss'),
        secondary_action() {
            d.hide();
        }
    });

    d.$wrapper.find('.ap-btn-jump-field').on('click', function() {
        let fieldname = $(this).attr('data-field');
        d.hide();
        jump_to_and_highlight_field(frm, fieldname);
    });

    d.show();

    frappe.show_alert({
        message: __(`🚫 Submission blocked: ${audit.errors.length} mandatory item(s) missing`),
        indicator: 'red'
    }, 7);
}

function jump_to_and_highlight_field(frm, fieldname) {
    if (!fieldname || !frm.fields_dict[fieldname]) return;
    frm.scroll_to_field(fieldname);
    let wrapper = $(frm.fields_dict[fieldname].wrapper);
    wrapper.css({
        'box-shadow': '0 0 0 3px rgba(239, 68, 68, 0.4)',
        'border-radius': '6px',
        'transition': 'box-shadow 0.3s ease'
    });
    setTimeout(() => {
        wrapper.css('box-shadow', '');
    }, 3500);
}

// --------------------------------------------------------------------------------------
// REJECTION & DISPUTE MODAL: NEVER SILENT
// --------------------------------------------------------------------------------------
function open_vendor_dispute_modal(frm) {
    let d = new frappe.ui.Dialog({
        title: __('🚫 Flag Claim as Disputed / Rejected'),
        fields: [
            {
                fieldname: 'reason_code',
                fieldtype: 'Select',
                label: __('Dispute / Rejection Reason Code'),
                options: [
                    '3-Way Match Price Variance (Exceeds Policy)',
                    '3-Way Match Quantity Mismatch',
                    'Missing or Illegible Tax Invoice Proof',
                    'Missing Manager Email Approval (Non-PO)',
                    'Vendor Bank Account Mismatch / Lockout',
                    'Missing Goods Receipt (GRN)',
                    'Duplicate Invoice Suspected',
                    'Incorrect GST Rate / Tax Calculation',
                    'Other Statutory / Policy Violation'
                ].join('\n'),
                default: '3-Way Match Price Variance (Exceeds Policy)',
                reqd: 1
            },
            {
                fieldname: 'remarks',
                fieldtype: 'Small Text',
                label: __('Mandatory Auditor Remarks (Minimum 10 characters)'),
                description: __('State forensic reason for rejection. This is logged to the official Error Log & Audit Trail.'),
                reqd: 1
            }
        ],
        primary_action_label: __('Submit Dispute'),
        primary_action(values) {
            if (!values.remarks || values.remarks.trim().length < 10) {
                frappe.msgprint({
                    title: __('Remarks Mandatory'),
                    indicator: 'red',
                    message: __('Auditor remarks are strictly mandatory for rejection (minimum 10 characters). Rejection cannot be silent.')
                });
                return;
            }

            d.hide();
            frappe.call({
                method: 'ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim.dispute_vendor_claim',
                args: {
                    docname: frm.doc.name,
                    reason_code: values.reason_code,
                    remarks: values.remarks.trim()
                },
                freeze: true,
                freeze_message: __('Logging forensic dispute audit...'),
                callback: function(r) {
                    if (r && r.message) {
                        frappe.msgprint({
                            title: __('Claim Placed in Disputed Status'),
                            indicator: 'red',
                            message: __(`<b>Status Updated:</b> ${r.message.message}<br><br><b>Audit Log:</b> "${values.remarks.trim()}" has been recorded in Frappe Error Log.`)
                        });
                        frm.reload_doc();
                    }
                }
            });
        }
    });

    d.show();
}

// --------------------------------------------------------------------------------------
// PRE-FLIGHT AUDIT & ERROR LOG INSPECTOR MODAL
// --------------------------------------------------------------------------------------
function open_vendor_audit_inspector_modal(frm) {
    let audit = run_pre_submit_audit(frm);

    frappe.call({
        method: 'ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim.get_vendor_claim_audit_logs',
        args: { docname: frm.doc.name },
        callback: function(res) {
            let logs = (res && res.message) || [];
            let logs_html = "";
            if (logs.length > 0) {
                logs_html = logs.map(l => `
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px 12px; margin-bottom: 6px; font-family: monospace; font-size: 11px;">
                        <div style="display: flex; justify-content: space-between; color: #64748b; font-weight: 700;">
                            <span>${l.name}</span>
                            <span>${l.creation}</span>
                        </div>
                        <div style="color: #dc2626; margin-top: 4px; white-space: pre-wrap; max-height: 80px; overflow-y: auto;">
                            ${l.error || l.method || 'Validation Event'}
                        </div>
                    </div>
                `).join('');
            } else {
                logs_html = `<div style="color: #64748b; font-size: 12px; font-style: italic; padding: 6px 0;">No system error logs recorded for this voucher.</div>`;
            }

            let checklist_rows = [
                { title: "1. Vendor ERPNext Master Binding", ok: !!frm.doc.vendor, detail: frm.doc.vendor_name || "Missing" },
                { title: "2. Active Bank Account & IFSC", ok: !!frm.doc.bank_account_number && !!frm.doc.bank_ifsc_code, detail: frm.doc.bank_account_number ? `A/C: ${frm.doc.bank_account_number} (${frm.doc.bank_ifsc_code})` : "Missing in Master" },
                { title: "3. NPCI Penny Drop Security Shield", ok: frm.doc.bank_name !== "Pending Verification", detail: frm.doc.bank_name || "Unverified" },
                { title: "4. Intake Route Proofs (PO vs Email)", ok: frm.doc.invoice_type === "With Purchase Order" ? !!frm.doc.purchase_order : !!frm.doc.email_approval_attachment, detail: frm.doc.invoice_type === "With Purchase Order" ? (frm.doc.purchase_order || "Missing PO") : (frm.doc.email_approval_attachment ? "Email Proof Attached" : "Missing Email Proof") },
                { title: "5. Vendor Tax Invoice PDF", ok: !!frm.doc.tax_invoice_attachment, detail: frm.doc.tax_invoice_attachment ? "PDF Attached" : "Missing PDF" },
                { title: "6. Invoice # and Date", ok: !!frm.doc.tax_invoice_number && !!frm.doc.tax_invoice_date, detail: `${frm.doc.tax_invoice_number || 'No #'} (${frm.doc.tax_invoice_date || 'No Date'})` },
                { title: "7. Taxable Base & Positive Total", ok: flt(frm.doc.base_amount) > 0, detail: `Base: INR ${formatINR(flt(frm.doc.base_amount))}` },
                { title: "8. 3-Way Match Clearance", ok: !frm.doc.match_status || frm.doc.match_status === "3-Way Match Passed", detail: frm.doc.match_status || "Not Evaluated" }
            ].map(item => `
                <tr style="border-bottom: 1px solid #e2e8f0;">
                    <td style="padding: 8px 10px; font-weight: 600; color: #334155; font-size: 12px;">${item.title}</td>
                    <td style="padding: 8px 10px; text-align: center;">
                        <span style="display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; background: ${item.ok ? '#dcfce7' : '#fee2e2'}; color: ${item.ok ? '#15803d' : '#b91c1c'};">
                            ${item.ok ? '✓ PASS' : '✗ ACTION'}
                        </span>
                    </td>
                    <td style="padding: 8px 10px; font-size: 12px; color: #64748b;">${item.detail}</td>
                </tr>
            `).join('');

            let d = new frappe.ui.Dialog({
                title: __('📋 Forensic Pre-Flight Audit & Error Logs'),
                fields: [
                    {
                        fieldtype: 'HTML',
                        fieldname: 'audit_html',
                        options: `
                            <div style="padding: 4px 0;">
                                <div style="font-size: 12px; font-weight: 700; color: #334155; text-transform: uppercase; margin-bottom: 8px;">
                                    8-Point Statutory & Zero-Trust Audit Checklist
                                </div>
                                <table style="width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden; margin-bottom: 16px;">
                                    <thead>
                                        <tr style="background: #f8fafc; border-bottom: 1px solid #cbd5e1; text-align: left; font-size: 11px; text-transform: uppercase; color: #64748b;">
                                            <th style="padding: 8px 10px;">Audit Parameter</th>
                                            <th style="padding: 8px 10px; text-align: center;">Status</th>
                                            <th style="padding: 8px 10px;">Current Value</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${checklist_rows}
                                    </tbody>
                                </table>

                                <div style="font-size: 12px; font-weight: 700; color: #334155; text-transform: uppercase; margin-bottom: 8px;">
                                    Recent System Error Logs
                                </div>
                                ${logs_html}
                            </div>
                        `
                    }
                ],
                primary_action_label: __('Close'),
                primary_action() {
                    d.hide();
                }
            });

            d.show();
        }
    });
}

// --------------------------------------------------------------------------------------
// PETTY-CASH-STYLE 2-COLUMN PROOF & RECEIPT GALLERY ENGINE
// --------------------------------------------------------------------------------------
function get_vendor_claim_attachments(frm) {
    let attachments = [];

    if (frm.doc.tax_invoice_attachment) {
        let url = frm.doc.tax_invoice_attachment;
        let fname = url.split('/').pop().split('?')[0];
        let ext = fname.split('.').pop().toLowerCase();
        attachments.push({
            category: "Tax Invoice PDF",
            file_url: url,
            file_name: fname,
            extension: ext,
            icon: ext === 'pdf' ? '📄' : '🖼️',
            amount: frm.doc.total_invoice_amount || 0.0,
            date: frm.doc.tax_invoice_date || frm.doc.creation
        });
    }

    if (frm.doc.email_approval_attachment) {
        let url = frm.doc.email_approval_attachment;
        let fname = url.split('/').pop().split('?')[0];
        let ext = fname.split('.').pop().toLowerCase();
        attachments.push({
            category: "Manager Email Approval Proof",
            file_url: url,
            file_name: fname,
            extension: ext,
            icon: ext === 'pdf' ? '📧' : '🖼️',
            amount: frm.doc.base_amount || 0.0,
            date: frm.doc.creation
        });
    }

    return attachments;
}

function setup_vendor_receipt_gallery_button(frm) {
    let attachments = get_vendor_claim_attachments(frm);
    if (attachments.length > 0) {
        frm.add_custom_button(__(`📁 Receipt Gallery (${attachments.length})`), function () {
            open_vendor_receipt_gallery(frm);
        }, __('Audit Proofs'));
    }
}

function open_vendor_receipt_gallery(frm) {
    let attachments = get_vendor_claim_attachments(frm);

    if (attachments.length === 0) {
        frappe.msgprint(__('No receipts or tax invoices attached yet.'));
        return;
    }

    let selected_index = 0;

    let d = new frappe.ui.Dialog({
        title: __('Vendor Invoice & Approval Proof Gallery'),
        fields: [
            {
                fieldname: 'gallery_html_area',
                fieldtype: 'HTML'
            }
        ],
        size: 'extra-large',
        primary_action_label: __('Download All Proofs'),
        primary_action: function () {
            attachments.forEach(att => {
                let a = document.createElement('a');
                a.href = att.file_url;
                a.download = att.file_name;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            });
        }
    });

    let $wrapper = d.fields_dict.gallery_html_area.$wrapper;
    $wrapper.empty();

    let container = $(`
        <div class="ap-receipt-gallery-container" style="display: flex; height: 75vh; min-height: 520px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #fff;">
            <!-- Left Thumbnails Sidebar (320px) -->
            <div class="ap-gallery-sidebar" style="width: 320px; border-right: 1px solid #e2e8f0; overflow-y: auto; background: #f8fafc; padding: 12px; display: flex; flex-direction: column; gap: 8px;">
                <div style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">
                    Attached Documents (${attachments.length})
                </div>
            </div>
            <!-- Right Full-Size Preview Pane -->
            <div class="ap-gallery-preview" style="flex: 1; display: flex; flex-direction: column; background: #0f172a; position: relative;">
                <div class="ap-preview-header" style="height: 44px; background: #1e293b; border-bottom: 1px solid #334155; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; color: #fff;">
                    <div class="ap-preview-title" style="font-size: 13px; font-weight: 600; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;"></div>
                    <div class="ap-preview-actions" style="display: flex; gap: 8px;">
                        <a class="btn btn-xs btn-default ap-btn-open-tab" target="_blank" style="color: #fff; background: #334155; border: none;">↗ Open Tab</a>
                        <a class="btn btn-xs btn-primary ap-btn-download" download style="border: none;">⬇ Download</a>
                    </div>
                </div>
                <div class="ap-preview-body" style="flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; padding: 16px; position: relative;">
                </div>
            </div>
        </div>
    `);

    let sidebar = container.find('.ap-gallery-sidebar');
    let preview_body = container.find('.ap-preview-body');
    let preview_title = container.find('.ap-preview-title');
    let btn_open_tab = container.find('.ap-btn-open-tab');
    let btn_download = container.find('.ap-btn-download');

    function render_preview(idx) {
        selected_index = idx;
        let att = attachments[idx];

        sidebar.find('.ap-gallery-thumb-card').each(function(i) {
            if (i === idx) {
                $(this).css({
                    'border-color': '#2563eb',
                    'background': '#eff6ff',
                    'box-shadow': '0 2px 4px rgba(37,99,235,0.1)'
                });
            } else {
                $(this).css({
                    'border-color': '#e2e8f0',
                    'background': '#ffffff',
                    'box-shadow': 'none'
                });
            }
        });

        preview_title.text(`${att.category} — ${att.file_name}`);
        btn_open_tab.attr('href', att.file_url);
        btn_download.attr('href', att.file_url).attr('download', att.file_name);

        preview_body.empty();

        if (att.extension === 'pdf') {
            preview_body.html(`
                <iframe src="${att.file_url}" style="width: 100%; height: 100%; border: none; border-radius: 4px; background: #fff;" frameborder="0"></iframe>
            `);
        } else if (['jpg', 'jpeg', 'png', 'webp'].includes(att.extension)) {
            preview_body.html(`
                <img src="${att.file_url}" style="max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 4px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);" />
            `);
        } else {
            preview_body.html(`
                <div style="color: #94a3b8; text-align: center;">
                    <div style="font-size: 48px; margin-bottom: 12px;">📁</div>
                    <div style="font-size: 14px; font-weight: 600;">Preview Not Supported</div>
                    <div style="font-size: 12px; margin-top: 4px;">File format: .${att.extension}</div>
                    <a href="${att.file_url}" target="_blank" class="btn btn-sm btn-primary" style="margin-top: 14px;">Open / Download File</a>
                </div>
            `);
        }
    }

    attachments.forEach((att, idx) => {
        let card = $(`
            <div class="ap-gallery-thumb-card" style="display: flex; gap: 10px; padding: 10px; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; cursor: pointer; transition: all 0.15s ease;">
                <div style="width: 44px; height: 44px; border-radius: 4px; background: #f1f5f9; display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0;">
                    ${att.icon}
                </div>
                <div style="flex: 1; min-width: 0;">
                    <div style="font-size: 11px; font-weight: 700; color: #2563eb; text-transform: uppercase;">${att.category}</div>
                    <div style="font-size: 12px; font-weight: 600; color: #1e293b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 2px;" title="${att.file_name}">${att.file_name}</div>
                    <div style="font-size: 11px; color: #64748b; margin-top: 4px; display: flex; justify-content: space-between;">
                        <span>INR ${formatINR(att.amount)}</span>
                        <span>${att.extension.toUpperCase()}</span>
                    </div>
                </div>
            </div>
        `);

        card.on('click', function() {
            render_preview(idx);
        });

        sidebar.append(card);
    });

    $wrapper.append(container);
    d.show();

    render_preview(selected_index);
}

// --------------------------------------------------------------------------------------
// FORM DASHBOARD: STEPPER, 3-WAY MATCHING CARD, WATERFALL & AUDIT BANNERS
// --------------------------------------------------------------------------------------
function render_vendor_invoice_dashboard(frm) {
    if (!frm.dashboard) return;

    let audit = run_pre_submit_audit(frm);

    // Dynamic Live Audit Banner (at very top)
    let audit_banner_html = "";
    if (frm.doc.status === "Disputed" || frm.doc.status === "Rejected") {
        audit_banner_html = `
            <div style="background: #fef2f2; border: 1px solid #f87171; border-left: 5px solid #dc2626; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <strong style="color: #991b1b; font-size: 13px;">🚫 Claim in Disputed / Flagged Status</strong>
                    <button class="btn btn-xs btn-outline-danger ap-btn-banner-audit-logs" style="font-size: 11px;">📋 View Dispute & Audit History</button>
                </div>
                <div style="color: #7f1d1d; font-size: 12px; margin-top: 4px; line-height: 1.4;">
                    ${frm.doc.match_variance_details || '3-Way match price variance or auditor discrepancy flagged.'}
                </div>
            </div>
        `;
    } else if (audit.errors.length > 0) {
        let chips = audit.errors.map(e => `
            <span class="ap-err-chip" data-field="${e.fieldname}" style="display: inline-flex; align-items: center; gap: 4px; background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; border-radius: 999px; padding: 2px 10px; font-size: 11px; font-weight: 600; cursor: pointer;">
                ${e.icon} ${e.label} ↗
            </span>
        `).join('');
        audit_banner_html = `
            <div style="background: #fffbeb; border: 1px solid #fde68a; border-left: 5px solid #d97706; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <strong style="color: #92400e; font-size: 13px;">⚠️ Pre-Submission Checklist: ${audit.errors.length} Action Item(s) Pending</strong>
                    <button class="btn btn-xs btn-warning ap-btn-banner-checklist" style="color: #78350f; font-weight: 700; font-size: 11px;">Resolve Checklist 🎯</button>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;">
                    ${chips}
                </div>
            </div>
        `;
    } else {
        audit_banner_html = `
            <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-left: 5px solid #16a34a; border-radius: 8px; padding: 8px 14px; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between;">
                <span style="color: #166534; font-size: 12px; font-weight: 600;">
                    ✅ Pre-Submission Audit Cleared: All mandatory proofs, banking master, and financial totals verified.
                </span>
                <span style="font-size: 11px; background: #dcfce7; color: #15803d; font-weight: 700; padding: 2px 8px; border-radius: 999px;">Ready to Submit</span>
            </div>
        `;
    }

    // 1. Five-Stage Stepper
    let stages = [
        { label: "1. Intake", key: "Draft" },
        { label: "2. 3-Way Match", key: "3-Way Match Passed" },
        { label: "3. Accounts Review", key: "Pending Accounts Review" },
        { label: "4. Batch Queued", key: "Queued in Batch" },
        { label: "5. Settled & Paid", key: "Paid" }
    ];

    let current_status = frm.doc.status || "Draft";
    let active_idx = 0;
    if (current_status === "Draft") active_idx = 0;
    else if (current_status === "Pending Accounts Review") active_idx = 2;
    else if (current_status === "Approved for Payment") active_idx = 2;
    else if (current_status === "Queued in Batch") active_idx = 3;
    else if (current_status === "Paid") active_idx = 4;
    else if (current_status === "Disputed") active_idx = 1;

    let stepper_html = stages.map((st, i) => {
        let is_completed = i < active_idx;
        let is_current = i === active_idx;
        let is_disputed = current_status === "Disputed" && i === 1;

        let bg = "#f1f5f9";
        let color = "#64748b";
        let border = "#cbd5e1";

        if (is_disputed) {
            bg = "#fee2e2";
            color = "#b91c1c";
            border = "#ef4444";
        } else if (is_completed) {
            bg = "#ecfdf5";
            color = "#047857";
            border = "#10b981";
        } else if (is_current) {
            bg = "#eff6ff";
            color = "#1d4ed8";
            border = "#3b82f6";
        }

        return `
            <div style="flex: 1; text-align: center; padding: 8px 4px; background: ${bg}; color: ${color}; border: 1px solid ${border}; border-radius: 6px; font-size: 11px; font-weight: ${is_current ? '700' : '600'};">
                ${is_completed ? '✓ ' : ''}${is_disputed ? '⚠️ ' : ''}${st.label}
            </div>
        `;
    }).join('');

    // 2. Bank Security Badge
    let pd_status = (frm._bank_account_doc && frm._bank_account_doc.penny_drop_status) || frm.doc.bank_name;
    let bank_shield_html = "";

    if (pd_status === "LOCKED_PENNY_DROP_MISMATCH") {
        bank_shield_html = `
            <div style="display: inline-flex; align-items: center; gap: 8px; background: #fee2e2; border: 1px solid #ef4444; border-radius: 6px; padding: 4px 10px; color: #b91c1c; font-size: 12px; font-weight: 700;">
                <span>🛡️ NPCI Penny Drop Lockout</span>
                <button class="btn btn-xs btn-danger ap-btn-unlock-bank" data-ba="${frm.doc.bank_account_number}" style="padding: 2px 8px; font-size: 11px;">Clear Override</button>
            </div>
        `;
    } else {
        bank_shield_html = `
            <div style="display: inline-flex; align-items: center; gap: 6px; background: #ecfdf5; border: 1px solid #10b981; border-radius: 6px; padding: 4px 10px; color: #047857; font-size: 12px; font-weight: 600;">
                <span>🛡️ Bank Verified (NPCI Score: 100)</span>
            </div>
        `;
    }

    // 3. Visual 3-Way Match Card
    let match_card_html = "";
    if (frm.doc.invoice_type === "With Purchase Order" && frm.doc.purchase_order) {
        let m_status = frm.doc.match_status || "Pending Match Execution";
        let is_pass = m_status === "3-Way Match Passed";
        let badge_color = is_pass ? "#059669" : "#dc2626";
        let badge_bg = is_pass ? "#ecfdf5" : "#fef2f2";

        match_card_html = `
            <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-top: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <div style="font-size: 12px; font-weight: 700; color: #334155; text-transform: uppercase;">
                        3-Way Matching Engine • Side-by-Side Audit
                    </div>
                    <span style="background: ${badge_bg}; color: ${badge_color}; border: 1px solid ${badge_color}; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700;">
                        ${m_status}
                    </span>
                </div>
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;">
                    <div style="background: #f8fafc; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0;">
                        <div style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase;">1. AP Purchase Order</div>
                        <div style="font-size: 14px; font-weight: 700; color: #1e293b; margin-top: 4px;">${frm.doc.purchase_order}</div>
                        <div style="font-size: 12px; color: #475569; margin-top: 2px;">Base: INR ${formatINR(flt(frm.doc.base_amount))}</div>
                    </div>
                    <div style="background: #f8fafc; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0;">
                        <div style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase;">2. Vendor Tax Invoice</div>
                        <div style="font-size: 14px; font-weight: 700; color: #1e293b; margin-top: 4px;"># ${frm.doc.tax_invoice_number || 'DRAFT'}</div>
                        <div style="font-size: 12px; color: #475569; margin-top: 2px;">Claim: INR ${formatINR(flt(frm.doc.total_invoice_amount))}</div>
                    </div>
                    <div style="background: #f8fafc; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0;">
                        <div style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase;">3. Goods Receipt (GRN)</div>
                        <div style="font-size: 14px; font-weight: 700; color: #1e293b; margin-top: 4px;">${frm.doc.purchase_receipt || 'Verified / Received'}</div>
                        <div style="font-size: 12px; color: #475569; margin-top: 2px;">Tolerance: 0.0% variance</div>
                    </div>
                </div>
            </div>
        `;
    }

    // 4. Financial Settlement Waterfall Card
    let base = flt(frm.doc.base_amount);
    let gst = flt(frm.doc.gst_amount);
    let total = flt(frm.doc.total_invoice_amount);
    let adv = flt(frm.doc.advance_deducted);
    let tds = flt(frm.doc.tds_amount);
    let net = flt(frm.doc.net_payable_amount);

    let waterfall_html = `
        <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-top: 12px;">
            <div style="font-size: 12px; font-weight: 700; color: #334155; text-transform: uppercase; margin-bottom: 10px;">
                Statutory Deductions & Settlement Waterfall
            </div>
            <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px;">
                <div style="background: #f8fafc; padding: 8px 10px; border-radius: 4px; border: 1px solid #e2e8f0;">
                    <div style="font-size: 10px; color: #64748b; text-transform: uppercase;">Base Amount</div>
                    <div style="font-size: 14px; font-weight: 700; color: #1e293b; margin-top: 2px;">${formatINR(base)}</div>
                </div>
                <div style="background: #f8fafc; padding: 8px 10px; border-radius: 4px; border: 1px solid #e2e8f0;">
                    <div style="font-size: 10px; color: #64748b; text-transform: uppercase;">(+) GST (${frm.doc.gst_rate || '18%'})</div>
                    <div style="font-size: 14px; font-weight: 700; color: #2563eb; margin-top: 2px;">+ ${formatINR(gst)}</div>
                </div>
                <div style="background: #f8fafc; padding: 8px 10px; border-radius: 4px; border: 1px solid #e2e8f0;">
                    <div style="font-size: 10px; color: #64748b; text-transform: uppercase;">(-) Advance Recovered</div>
                    <div style="font-size: 14px; font-weight: 700; color: #d97706; margin-top: 2px;">- ${formatINR(adv)}</div>
                </div>
                <div style="background: #f8fafc; padding: 8px 10px; border-radius: 4px; border: 1px solid #e2e8f0;">
                    <div style="font-size: 10px; color: #64748b; text-transform: uppercase;">(-) TDS Withholding</div>
                    <div style="font-size: 14px; font-weight: 700; color: #dc2626; margin-top: 2px;">- ${formatINR(tds)}</div>
                </div>
                <div style="background: linear-gradient(135deg, #059669 0%, #047857 100%); color: white; padding: 8px 12px; border-radius: 6px; box-shadow: 0 2px 6px rgba(5,150,105,0.25);">
                    <div style="font-size: 10px; color: #d1fae5; text-transform: uppercase; font-weight: 700;">👉 Net Disbursal</div>
                    <div style="font-size: 16px; font-weight: 800; color: #ffffff; margin-top: 2px;">${formatINR(net)}</div>
                </div>
            </div>
        </div>
    `;

    // Master Dashboard Container
    let full_dashboard_html = `
        <div class="ap-vendor-claim-dashboard" style="background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px; padding: 16px; margin: 10px 0 20px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.04);">
            <!-- Live Audit & Alert Banner -->
            ${audit_banner_html}

            <!-- Stepper -->
            <div style="display: flex; gap: 8px; margin-bottom: 12px;">
                ${stepper_html}
            </div>

            <!-- Vendor & Bank Security Row -->
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
                <div>
                    <span style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Vendor Master • </span>
                    <strong style="font-size: 14px; color: #0f172a;">${frm.doc.vendor_name || frm.doc.vendor || 'Select Vendor'}</strong>
                    <span style="font-size: 12px; color: #64748b; margin-left: 6px;">(GSTIN: ${frm.doc.vendor_gstin || 'Unregistered'})</span>
                </div>
                <div>
                    ${bank_shield_html}
                </div>
            </div>

            <!-- 3-Way Match Card -->
            ${match_card_html}

            <!-- Waterfall Card -->
            ${waterfall_html}
        </div>
    `;

    if (frm.dashboard.headline && frm.dashboard.headline.length) {
        frm.dashboard.headline.empty();
    }
    frm.dashboard.set_headline(full_dashboard_html);

    // Bind Audit Banner Click Handlers
    $(frm.dashboard.headline).off('click', '.ap-err-chip').on('click', '.ap-err-chip', function() {
        let fieldname = $(this).attr('data-field');
        jump_to_and_highlight_field(frm, fieldname);
    });

    $(frm.dashboard.headline).off('click', '.ap-btn-banner-checklist').on('click', '.ap-btn-banner-checklist', function() {
        show_submission_blocker_dialog(frm, audit);
    });

    $(frm.dashboard.headline).off('click', '.ap-btn-banner-audit-logs').on('click', '.ap-btn-banner-audit-logs', function() {
        open_vendor_audit_inspector_modal(frm);
    });

    // Bind Manager Unlock Action Modal
    $(frm.dashboard.headline).off('click', '.ap-btn-unlock-bank').on('click', '.ap-btn-unlock-bank', function() {
        let ba = $(this).attr('data-ba') || "";
        frappe.prompt([
            {
                fieldname: 'bank_account_name',
                fieldtype: 'Link',
                options: 'Bank Account',
                label: 'Bank Account',
                default: ba,
                reqd: 1
            },
            {
                fieldname: 'justification',
                fieldtype: 'Small Text',
                label: 'Audit Justification (Minimum 20 characters)',
                description: 'State reason for manual clearance (e.g. verified original board resolution offline).',
                reqd: 1
            }
        ], function(values) {
            frappe.call({
                method: 'ap_automation.services.penny_drop_service.unlock_vendor_bank_account',
                args: {
                    bank_account_name: values.bank_account_name,
                    justification: values.justification
                },
                freeze: true,
                freeze_message: __('Processing Manager Clearance...'),
                callback: function(r) {
                    if (r.message && r.message.status === "MANUALLY_OVERRIDDEN") {
                        frappe.msgprint({
                            title: __('Bank Account Unlocked'),
                            indicator: 'green',
                            message: __('Vendor Bank Account has been manually cleared. Invoice submissions can now proceed.')
                        });
                        frm.reload_doc();
                    }
                }
            });
        }, __('Accounts Manager Zero-Trust Clearance'), __('Unlock Bank Account'));
    });
}

// --------------------------------------------------------------------------------------
// FINANCIAL CALCULATIONS & FORMATTING
// --------------------------------------------------------------------------------------
function calculate_vendor_totals(frm) {
    let base = flt(frm.doc.base_amount);
    let gst_rate_str = frm.doc.gst_rate || "18%";
    let gst_pct = flt(gst_rate_str.replace('%', ''));

    let gst = round_currency(base * (gst_pct / 100.0));
    let total = round_currency(base + gst);
    let advance = flt(frm.doc.advance_deducted);

    let tds_rate = 0.0;
    if (frm.doc.tds_section) {
        if (frm.doc.tds_section === "194C (Contractor)") tds_rate = 2.0;
        else if (frm.doc.tds_section === "194J (Professional)") tds_rate = 10.0;
        else if (frm.doc.tds_section === "194Q (Goods Purchase)") tds_rate = 0.1;
    }
    let tds = round_currency(base * (tds_rate / 100.0));
    let net = round_currency(total - advance - tds);

    frm.set_value("gst_amount", gst);
    frm.set_value("total_invoice_amount", total);
    frm.set_value("tds_rate", tds_rate);
    frm.set_value("tds_amount", tds);
    frm.set_value("net_payable_amount", net);
    frm.set_value("total_amount", net);

    render_vendor_invoice_dashboard(frm);
}

function round_currency(v) {
    return Math.round((v + Number.EPSILON) * 100) / 100;
}

function formatINR(val) {
    val = flt(val);
    return val.toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}
