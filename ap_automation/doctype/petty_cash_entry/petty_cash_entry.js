// Copyright (c) 2026, Quanti and contributors
// Petty Cash Entry Client Script — Ultra User-Friendly Enterprise UI & Process Flow Suite

frappe.ui.form.on("Petty Cash Entry", {
    setup(frm) {
        if (frm.is_new() && !frm.doc.custodian) {
            frm.set_value("custodian", frappe.session.user);
        }
        if (frm.is_new() && !frm.doc.posting_date) {
            frm.set_value("posting_date", frappe.datetime.get_today());
        }
    },

    refresh(frm) {
        recalculate_petty_cash_total(frm);
        render_user_friendly_progress_stepper(frm);
        render_dynamic_next_step_banner(frm);
        setup_friendly_action_buttons(frm);
        setup_receipt_gallery_actions(frm);
        format_smart_grid_cells(frm);
        apply_friendly_ui_css();
    },

    validate(frm) {
        recalculate_petty_cash_total(frm);
    }
});

frappe.ui.form.on("Petty Cash Line Item", {
    amount(frm, cdt, cdn) {
        recalculate_petty_cash_total(frm);
    },
    expense_lines_remove(frm, cdt, cdn) {
        recalculate_petty_cash_total(frm);
        format_smart_grid_cells(frm);
    },
    expense_lines_add(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.expense_date) {
            frappe.model.set_value(cdt, cdn, "expense_date", frm.doc.posting_date || frappe.datetime.get_today());
        }
        recalculate_petty_cash_total(frm);
        setTimeout(() => format_smart_grid_cells(frm), 50);
    }
});

function recalculate_petty_cash_total(frm) {
    let total = 0.0;
    (frm.doc.expense_lines || []).forEach(row => {
        total += flt(row.amount);
    });
    frm.set_value("total_amount", Math.round(total * 100) / 100);
    frm.refresh_field("total_amount");
}

// --------------------------------------------------------------------------------------
// 1. VISUAL 5-STEP PIPELINE TRACKER (Progress Stepper)
// --------------------------------------------------------------------------------------
function render_user_friendly_progress_stepper(frm) {
    if (frm.is_new()) return;

    const status = frm.doc.status || "Draft";
    let active_step = 1;

    if (status === "Draft") active_step = 1;
    else if (status === "Submitted") active_step = 2;
    else if (status === "L1 Verified") active_step = 3;
    else if (status === "Approved for Payment" || status === "Queued in Batch") active_step = 4;
    else if (status === "Dispatched to Bank" || status === "Paid") active_step = 5;
    else if (status === "Disputed") active_step = 2; // Flagged in step 2
    else if (status === "Rejected") active_step = 3;

    const steps = [
        { num: 1, title: "Bill Entry", icon: "📝", desc: "Admin Upload" },
        { num: 2, title: "Accounts Audit", icon: "🔍", desc: "L1 Verification" },
        { num: 3, title: "Director Approval", icon: "✍️", desc: "Anshul Sir" },
        { num: 4, title: "Bank Release", icon: "🏦", desc: "IDFC 2FA (Anish Sir)" },
        { num: 5, title: "Money Received", icon: "💰", desc: "Bank Account" }
    ];

    let steps_html = steps.map((s, idx) => {
        let is_completed = s.num < active_step || (active_step === 5 && s.num === 5);
        let is_current = s.num === active_step && active_step !== 5;
        let is_disputed = status === "Disputed" && s.num === 2;
        let is_rejected = status === "Rejected" && s.num === 3;

        let bg_color = "#f1f5f9";
        let text_color = "#64748b";
        let border_color = "#e2e8f0";
        let badge = s.icon;

        if (is_completed) {
            bg_color = "#ecfdf5";
            text_color = "#047857";
            border_color = "#a7f3d0";
            badge = "✅";
        } else if (is_current) {
            bg_color = "#eff6ff";
            text_color = "#1d4ed8";
            border_color = "#93c5fd";
        }

        if (is_disputed) {
            bg_color = "#fffbeb";
            text_color = "#b45309";
            border_color = "#fcd34d";
            badge = "⚠️";
        } else if (is_rejected) {
            bg_color = "#fef2f2";
            text_color = "#b91c1c";
            border_color = "#fca5a5";
            badge = "❌";
        }

        return `
            <div class="ap-stepper-item ${is_current ? 'ap-stepper-pulse' : ''}" style="
                flex: 1;
                background: ${bg_color};
                border: 1.5px solid ${border_color};
                border-radius: 8px;
                padding: 8px 10px;
                margin: 0 4px;
                display: flex;
                align-items: center;
                gap: 8px;
                box-shadow: 0 1px 2px rgba(0,0,0,0.03);
            ">
                <div style="font-size: 18px; line-height: 1;">${badge}</div>
                <div>
                    <div style="font-size: 12px; font-weight: 700; color: ${text_color};">${s.title}</div>
                    <div style="font-size: 10.5px; color: ${text_color}; opacity: 0.85;">${s.desc}</div>
                </div>
            </div>
        `;
    }).join("");

    const stepper_wrapper = `
        <div id="ap-workflow-stepper-box" style="margin-bottom: 15px; margin-top: 5px;">
            <div style="display: flex; align-items: stretch; justify-content: space-between;">
                ${steps_html}
            </div>
        </div>
    `;

    frm.dashboard.set_headline_alert(stepper_wrapper);
}

// --------------------------------------------------------------------------------------
// 2. DYNAMIC "WHAT TO DO NEXT?" GUIDANCE CARD
// --------------------------------------------------------------------------------------
function render_dynamic_next_step_banner(frm) {
    if (frm.is_new()) {
        frm.dashboard.clear_headline();
        return;
    }

    const status = frm.doc.status || "Draft";
    const amount_formatted = format_currency(frm.doc.total_amount || 0, "INR");
    let banner_config = null;

    if (status === "Draft") {
        banner_config = {
            icon: "💡",
            title: "Next Step: Submit your bills",
            message: `You have drafted a claim for <b>${amount_formatted}</b>. Please check your bill photos below and click the blue <b>'Submit'</b> button on top right so Accounts can verify.`,
            bg: "#eff6ff",
            border: "#bfdbfe",
            color: "#1e40af"
        };
    } else if (status === "Submitted") {
        banner_config = {
            icon: "⏳",
            title: "Waiting for Accounts Team (L1) Check",
            message: `Your claim of <b>${amount_formatted}</b> has been sent to the Accounts team. They are verifying your receipts. You do not need to take any action right now.`,
            bg: "#f8fafc",
            border: "#cbd5e1",
            color: "#334155"
        };
    } else if (status === "L1 Verified") {
        banner_config = {
            icon: "🔍",
            title: "Accounts Verified — Awaiting Anshul Sir's Approval",
            message: `Accounts team verified all receipts for <b>${amount_formatted}</b>. It is currently in Director's queue for final executive sign-off.`,
            bg: "#f0fdf4",
            border: "#bbf7d0",
            color: "#166534"
        };
    } else if (status === "Approved for Payment" || status === "Queued in Batch") {
        banner_config = {
            icon: "🎉",
            title: "Approved! Money is being batched for Bank Transfer",
            message: `Director approved <b>${amount_formatted}</b> for payment. It is scheduled for release directly to Custodian Bank Account (<b>${frm.doc.custodian_bank_account || 'Registered Account'}</b>).`,
            bg: "#ecfdf5",
            border: "#a7f3d0",
            color: "#065f46"
        };
    } else if (status === "Dispatched to Bank" || status === "Paid") {
        banner_config = {
            icon: "💰",
            title: "Payment Successfully Released via IDFC Bank!",
            message: `Payout of <b>${amount_formatted}</b> was transferred directly to your bank account. Bank UTR / Reference: <b style="color:#059669;">${frm.doc.bank_utr || frm.doc.idfc_batch_ref || 'Bank Confirmed'}</b>.`,
            bg: "#f0fdf4",
            border: "#86efac",
            color: "#14532d"
        };
    } else if (status === "Disputed") {
        banner_config = {
            icon: "⚠️",
            title: "Action Needed: Accounts Flagged a Receipt",
            message: `Accounts team returned this ticket for bill correction. Please check the orange line items below, upload clear tax invoices, and click <b>'Resubmit Claim'</b>.`,
            bg: "#fffbeb",
            border: "#fde68a",
            color: "#92400e"
        };
    } else if (status === "Rejected") {
        banner_config = {
            icon: "❌",
            title: "Claim Rejected",
            message: `This claim was rejected during review. Please contact Accounts for further guidance.`,
            bg: "#fef2f2",
            border: "#fecaca",
            color: "#991b1b"
        };
    }

    if (banner_config) {
        let banner_html = `
            <div style="
                background: ${banner_config.bg};
                border: 1px solid ${banner_config.border};
                border-left: 5px solid ${banner_config.color};
                padding: 10px 14px;
                border-radius: 6px;
                margin-top: 10px;
                margin-bottom: 12px;
                display: flex;
                align-items: center;
                gap: 12px;
            ">
                <div style="font-size: 24px;">${banner_config.icon}</div>
                <div style="flex: 1;">
                    <div style="font-weight: 700; font-size: 13px; color: ${banner_config.color}; margin-bottom: 2px;">
                        ${banner_config.title}
                    </div>
                    <div style="font-size: 12px; color: ${banner_config.color}; line-height: 1.4;">
                        ${banner_config.message}
                    </div>
                </div>
            </div>
        `;

        if (!frm.page.wrapper.find("#ap-dynamic-guidance-card").length) {
            frm.page.wrapper.find(".form-layout").before(`<div id="ap-dynamic-guidance-card">${banner_html}</div>`);
        } else {
            frm.page.wrapper.find("#ap-dynamic-guidance-card").html(banner_html);
        }
    }
}

// --------------------------------------------------------------------------------------
// 3. ROLE-BASED FRIENDLY ACTION BUTTONS
// --------------------------------------------------------------------------------------
function setup_friendly_action_buttons(frm) {
    if (frm.is_new()) return;

    const status = frm.doc.status;

    // L1 Verifier Actions (Status = Submitted)
    if (status === "Submitted") {
        frm.add_custom_button(__("✅ Verify All Lines"), () => {
            frappe.confirm(
                __("Are you sure all receipts and amounts are audited and 100% correct?"),
                () => {
                    frm.set_value("status", "L1 Verified");
                    frm.save().then(() => {
                        frappe.show_alert({ message: __("Claim verified & forwarded to Anshul Sir!"), indicator: "green" });
                        frm.reload_doc();
                    });
                }
            );
        }).addClass("btn-success").css({ "font-weight": "700", "background-color": "#10b981", "color": "#fff" });

        frm.add_custom_button(__("⚠️ Dispute A Line"), () => {
            open_friendly_dispute_modal(frm);
        }).addClass("btn-warning").css({ "font-weight": "700" });
    }

    // L2 Executive Actions (Status = L1 Verified)
    if (status === "L1 Verified") {
        frm.add_custom_button(__(`✍️ Approve Payout (${format_currency(frm.doc.total_amount, 'INR')})`), () => {
            frappe.confirm(
                __(`Sanction payout of <b>${format_currency(frm.doc.total_amount, 'INR')}</b> to Custodian <b>${frm.doc.custodian}</b>?`),
                () => {
                    frm.set_value("status", "Approved for Payment");
                    frm.save().then(() => {
                        frappe.show_alert({ message: __("Payout Approved! Payment Instruction generated."), indicator: "green" });
                        frm.reload_doc();
                    });
                }
            );
        }).addClass("btn-primary").css({ "font-weight": "700", "background-color": "#4f46e5", "color": "#fff" });

        frm.add_custom_button(__("❌ Reject Claim"), () => {
            frappe.prompt(
                { label: "Reason for Rejection", fieldtype: "Small Text", reqd: 1 },
                (values) => {
                    frm.set_value("status", "Rejected");
                    frm.save().then(() => {
                        frappe.msgprint(__("Claim has been marked as Rejected."));
                        frm.reload_doc();
                    });
                },
                __("Executive Rejection"),
                __("Reject")
            );
        }).addClass("btn-danger");
    }

    // Disputed Resubmit Action (Status = Disputed)
    if (status === "Disputed") {
        frm.add_custom_button(__("🚀 Resubmit Claim"), () => {
            frm.set_value("status", "Submitted");
            frm.save().then(() => {
                frappe.show_alert({ message: __("Claim resubmitted to Accounts!"), indicator: "green" });
                frm.reload_doc();
            });
        }).addClass("btn-primary").css({ "font-weight": "700" });
    }
}

// --------------------------------------------------------------------------------------
// 4. FRIENDLY DISPUTE MODAL (Zero Technical Jargon)
// --------------------------------------------------------------------------------------
function open_friendly_dispute_modal(frm) {
    const lines = frm.doc.expense_lines || [];
    if (!lines.length) {
        frappe.msgprint(__("No expense lines found to dispute."));
        return;
    }

    let fields = lines.map((row, idx) => ({
        label: `Row #${idx + 1}: ${row.merchant_name || 'Vendor'} — ${format_currency(row.amount, 'INR')} (${row.expense_category})`,
        fieldname: `dispute_${row.name}`,
        fieldtype: "Check"
    }));

    fields.push({
        label: "Dispute Reason / Guidance for Admin",
        fieldname: "common_reason",
        fieldtype: "Small Text",
        reqd: 1,
        default: "Receipt blurred / missing original GST invoice. Please replace with clear bill."
    });

    const d = new frappe.ui.Dialog({
        title: "⚠️ Flag a Problem Bill (Dispute Line)",
        fields: fields,
        primary_action_label: "Dispute & Split Ticket",
        primary_action(values) {
            let disputed_row_names = [];
            let dispute_reasons = {};

            lines.forEach(row => {
                if (values[`dispute_${row.name}`]) {
                    disputed_row_names.push(row.name);
                    dispute_reasons[row.name] = values.common_reason;
                }
            });

            if (!disputed_row_names.length) {
                frappe.msgprint(__("Please check at least one line item to dispute."));
                return;
            }

            d.hide();
            frappe.call({
                method: "ap_automation.services.dispute_service.dispute_and_fork_petty_cash_lines",
                args: {
                    parent_docname: frm.doc.name,
                    disputed_row_names: disputed_row_names,
                    dispute_reasons: dispute_reasons,
                    disputed_by: frappe.session.user
                },
                freeze: true,
                freeze_message: __("Splitting ticket and notifying Branch Admin..."),
                callback(r) {
                    if (r.message && r.message.status === "SUCCESS") {
                        frappe.msgprint({
                            title: __("Dispute Split Complete"),
                            message: `<b>Parent Ticket:</b> ${r.message.parent_voucher} (Verified: ₹${r.message.verified_amount})<br><b>Disputed Ticket:</b> ${r.message.forked_voucher} (Disputed: ₹${r.message.disputed_amount})`,
                            indicator: "green"
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
// 5. RECEIPT PREVIEW & SMART GRID FORMATTER
// --------------------------------------------------------------------------------------
function setup_receipt_gallery_actions(frm) {
    if (frm.is_new()) return;

    frappe.call({
        method: "ap_automation.services.attachment_service.get_all_claim_attachments",
        args: { doctype: frm.doc.doctype, docname: frm.doc.name },
        callback: (r) => {
            const attachments = r.message || [];
            if (attachments.length > 0) {
                frm.add_custom_button(__(`👁️ View All Receipts (${attachments.length})`), () => {
                    open_receipt_gallery_dialog(frm, attachments, 0);
                }).addClass("btn-primary").css({
                    "background-color": "#4f46e5",
                    "color": "#ffffff",
                    "font-weight": "600"
                });

                frm.add_custom_button(__(`📦 Download All (.ZIP)`), () => {
                    window.location.href = `/api/method/ap_automation.services.attachment_service.download_all_claim_attachments_zip?doctype=${encodeURIComponent(frm.doc.doctype)}&docname=${encodeURIComponent(frm.doc.name)}`;
                });
            }
        }
    });
}

function open_receipt_gallery_dialog(frm, attachments, start_idx) {
    let current_idx = start_idx || 0;
    const total = attachments.length;

    function build_gallery_html(idx) {
        const item = attachments[idx];
        const is_pdf = item.file_url.toLowerCase().endsWith(".pdf");
        const file_src = item.file_url;

        return `
            <div style="text-align: center; background: #0f172a; border-radius: 8px; padding: 15px; min-height: 480px;">
                <div style="display: flex; justify-content: space-between; color: #fff; margin-bottom: 12px; font-weight: 600;">
                    <span>🧾 Receipt ${idx + 1} of ${total} — ${item.file_name}</span>
                    <a href="${file_src}" target="_blank" style="color: #60a5fa; text-decoration: underline;">🔗 Open Full Size</a>
                </div>
                <div style="height: 420px; display: flex; align-items: center; justify-content: center;">
                    ${is_pdf 
                        ? `<iframe src="${file_src}" style="width: 100%; height: 100%; border: none; border-radius: 6px; background: #fff;"></iframe>`
                        : `<img src="${file_src}" style="max-height: 100%; max-width: 100%; object-fit: contain; border-radius: 6px; box-shadow: 0 4px 6px rgba(0,0,0,0.3);" />`
                    }
                </div>
            </div>
        `;
    }

    const d = new frappe.ui.Dialog({
        title: `Receipts for ${frm.doc.name}`,
        size: "large",
        fields: [{ fieldtype: "HTML", fieldname: "gallery_html" }]
    });

    d.set_value("gallery_html", build_gallery_html(current_idx));

    if (total > 1) {
        d.set_secondary_action_label("⬅️ Previous");
        d.set_secondary_action(() => {
            current_idx = (current_idx - 1 + total) % total;
            d.set_value("gallery_html", build_gallery_html(current_idx));
        });
        d.set_primary_action_label("Next ➡️");
        d.set_primary_action(() => {
            current_idx = (current_idx + 1) % total;
            d.set_value("gallery_html", build_gallery_html(current_idx));
        });
    }

    d.show();
}

function format_smart_grid_cells(frm) {
    if (!frm.page || !frm.page.wrapper) return;

    setTimeout(() => {
        frm.page.wrapper.find('.grid-row [data-fieldname="receipt_attachment"]').each(function () {
            const $cell = $(this);
            const $link = $cell.find('a');
            const href = $link.attr('href') || $cell.text().trim();

            if (href && (href.startsWith('/files/') || href.startsWith('/private/files/'))) {
                const is_pdf = href.toLowerCase().endsWith('.pdf');
                $cell.html(`
                    <span class="ap-grid-receipt-badge" style="
                        display: inline-flex;
                        align-items: center;
                        gap: 4px;
                        background: #ecfdf5;
                        color: #047857;
                        border: 1px solid #a7f3d0;
                        padding: 3px 8px;
                        border-radius: 6px;
                        font-size: 11.5px;
                        font-weight: 700;
                        cursor: pointer;
                    ">
                        ${is_pdf ? '📄 PDF Bill' : '🧾 Photo Bill'}
                    </span>
                `);
            } else if (!href) {
                $cell.html(`
                    <span style="
                        display: inline-flex;
                        align-items: center;
                        gap: 4px;
                        background: #fff1f2;
                        color: #e11d48;
                        border: 1px dashed #fecdd3;
                        padding: 3px 8px;
                        border-radius: 6px;
                        font-size: 11.5px;
                        font-weight: 600;
                    ">
                        📷 Missing Bill
                    </span>
                `);
            }
        });
    }, 60);
}

function apply_friendly_ui_css() {
    if (!document.getElementById('ap-friendly-ui-style')) {
        const style = document.createElement('style');
        style.id = 'ap-friendly-ui-style';
        style.innerHTML = `
            @keyframes pulse-border {
                0% { box-shadow: 0 0 0 0 rgba(79, 70, 229, 0.4); }
                70% { box-shadow: 0 0 0 6px rgba(79, 70, 229, 0); }
                100% { box-shadow: 0 0 0 0 rgba(79, 70, 229, 0); }
            }
            .ap-stepper-pulse {
                animation: pulse-border 2s infinite ease-in-out;
            }
        `;
        document.head.appendChild(style);
    }
}
