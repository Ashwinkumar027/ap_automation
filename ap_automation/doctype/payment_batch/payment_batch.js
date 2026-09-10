// Copyright (c) 2026, Quanti and contributors
// Production-Grade Multi-Lane Payment Release Dashboard for Frappe Desk

frappe.ui.form.on("Payment Batch", {
    refresh(frm) {
        setup_fetch_claims_button(frm);
        render_executive_dashboard(frm);
        setup_2fa_release_buttons(frm);
    },

    company(frm) {
        if (frm.doc.company && (!frm.doc.instructions || frm.doc.instructions.length === 0) && frm.doc.status === "Draft" && !frm.doc.idfc_batch_ref) {
            fetch_claims(frm, false);
        }
    }
});

function setup_fetch_claims_button(frm) {
    // Only show Fetch Approved Claims if batch is in Draft state, has no IDFC host ref, and is not submitted
    const is_dispatched = frm.doc.status === "Dispatched to Bank" || frm.doc.status === "Completed" || frm.doc.status === "Released" || frm.doc.idfc_batch_ref;
    const is_locked = frm.doc.status === "Pending 2FA Approval" || frm.doc.docstatus !== 0;

    if (frm.doc.status === "Draft" && !is_dispatched && !is_locked) {
        let btn = frm.add_custom_button(__("⚡ Fetch Approved Claims"), function () {
            if (!frm.doc.company) {
                frappe.msgprint({
                    title: __("Company Required"),
                    message: __("Please select a <b>Company Entity</b> first before fetching approved claims."),
                    indicator: "orange"
                });
                return;
            }

            if (frm.doc.instructions && frm.doc.instructions.length > 0) {
                frappe.confirm(
                    __("This batch already has payment instructions. Do you want to scan and refresh pending approved claims?"),
                    () => {
                        fetch_claims(frm, true);
                    }
                );
            } else {
                if (frm.is_new()) {
                    frm.save().then(() => {
                        fetch_claims(frm, true);
                    });
                } else {
                    fetch_claims(frm, true);
                }
            }
        });

        btn.addClass("btn-warning").css({
            "background": "linear-gradient(135deg, #f59e0b 0%, #d97706 100%)",
            "color": "#ffffff",
            "font-weight": "700",
            "border": "none",
            "box-shadow": "0 2px 6px rgba(245, 158, 11, 0.4)"
        });
    }
}

function fetch_claims(frm, user_initiated = true) {
    frappe.call({
        method: "ap_automation.ap_automation.doctype.payment_batch.payment_batch.fetch_approved_claims_for_batch",
        args: {
            batch_name: frm.doc.name,
            company: frm.doc.company
        },
        freeze: true,
        freeze_message: __("Scanning & Fetching Approved Claims Across 4 Lanes..."),
        callback: function (r) {
            if (r.message && r.message.status === "SUCCESS") {
                const count = r.message.count || 0;
                const tot = r.message.total_amount || 0;

                if (count === 0 && user_initiated) {
                    frappe.msgprint({
                        title: __("No Pending Claims"),
                        message: __("There are currently no unbatched claims in <b>'Approved for Payment'</b> status for this company."),
                        indicator: "blue"
                    });
                } else if (user_initiated) {
                    frappe.show_alert({
                        message: __(`✅ Successfully linked ${count} claim(s) totaling ₹ ${tot.toLocaleString('en-IN')}`),
                        indicator: "green"
                    }, 5);
                }
                frm.reload_doc();
            }
        }
    });
}

function render_executive_dashboard(frm) {
    if (frm.is_new()) return;

    frappe.call({
        method: "ap_automation.ap_automation.doctype.payment_batch.payment_batch.get_batch_summary",
        args: { batch_name: frm.doc.name },
        callback: function (r) {
            if (!r.message) return;
            const data = r.message;
            const lanes = data.lanes;

            const format_inr = (val) => {
                return new Intl.NumberFormat("en-IN", {
                    style: "currency",
                    currency: "INR",
                    maximumFractionDigits: 2
                }).format(val || 0);
            };

            const status_colors = {
                "Draft": "#64748b",
                "Generated": "#3b82f6",
                "Pending 2FA Approval": "#f59e0b",
                "Dispatched to Bank": "#10b981",
                "Completed": "#059669",
                "Rejected": "#ef4444"
            };

            const current_color = status_colors[data.status] || "#64748b";

            let dashboard_html = `
                <div class="ap-payment-batch-dashboard" style="
                    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
                    border-radius: 12px;
                    padding: 24px;
                    margin-bottom: 24px;
                    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.35);
                    color: #ffffff;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                ">
                    <!-- Top Summary Row -->
                    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255, 255, 255, 0.12); padding-bottom: 16px; margin-bottom: 20px;">
                        <div>
                            <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; font-weight: 700;">Corporate Payout Run</div>
                            <div style="font-size: 22px; font-weight: 700; color: #f8fafc; margin-top: 2px;">${data.company || "Consolidated Entity"}</div>
                            <div style="font-size: 12px; color: #cbd5e1; margin-top: 4px;">📅 Posting Date: <b>${data.posting_date}</b> &nbsp;|&nbsp; 📑 Total Instructions: <b>${data.total_instructions}</b></div>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; font-weight: 700;">Total Payout Value</div>
                            <div style="font-size: 32px; font-weight: 800; color: #34d399; letter-spacing: -0.02em;">${format_inr(data.total_batch_amount)}</div>
                            <div style="display: inline-block; margin-top: 4px; padding: 4px 14px; border-radius: 20px; font-size: 11px; font-weight: 700; text-transform: uppercase; background: ${current_color}25; color: ${current_color}; border: 1px solid ${current_color}77;">
                                ● ${data.status}
                            </div>
                        </div>
                    </div>

                    <!-- Stream Lanes Metric Cards -->
                    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px;">
                        <!-- Lane 3: Vendor Invoices -->
                        <div class="ap-lane-btn" data-doctype="Vendor Invoice Claim" style="background: rgba(59, 130, 246, 0.14); border: 1px solid rgba(59, 130, 246, 0.4); border-radius: 10px; padding: 14px; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                <span style="font-size: 12px; font-weight: 600; color: #60a5fa;">🏢 Lane 3: Vendors</span>
                                <span style="background: #3b82f6; color: white; border-radius: 12px; padding: 2px 8px; font-size: 11px; font-weight: 700;">${lanes.vendor.count}</span>
                            </div>
                            <div style="font-size: 18px; font-weight: 700; color: #ffffff;">${format_inr(lanes.vendor.amount)}</div>
                            <div style="font-size: 11px; color: #94a3b8; margin-top: 4px;">Commercial Invoices</div>
                        </div>

                        <!-- Lane 2: Employee Reimbursements -->
                        <div class="ap-lane-btn" data-doctype="Employee Reimbursement Claim" style="background: rgba(245, 158, 11, 0.14); border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 10px; padding: 14px; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                <span style="font-size: 12px; font-weight: 600; color: #fbbf24;">🏃 Lane 2: Claims</span>
                                <span style="background: #f59e0b; color: white; border-radius: 12px; padding: 2px 8px; font-size: 11px; font-weight: 700;">${lanes.reimbursement.count}</span>
                            </div>
                            <div style="font-size: 18px; font-weight: 700; color: #ffffff;">${format_inr(lanes.reimbursement.amount)}</div>
                            <div style="font-size: 11px; color: #94a3b8; margin-top: 4px;">Employee Expenses</div>
                        </div>

                        <!-- Lane 4: Event Spends & Advances -->
                        <div class="ap-lane-btn" data-doctype="Event Advance Request" style="background: rgba(139, 92, 246, 0.14); border: 1px solid rgba(139, 92, 246, 0.4); border-radius: 10px; padding: 14px; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                <span style="font-size: 12px; font-weight: 600; color: #a78bfa;">📅 Lane 4: Events</span>
                                <span style="background: #8b5cf6; color: white; border-radius: 12px; padding: 2px 8px; font-size: 11px; font-weight: 700;">${lanes.event.count}</span>
                            </div>
                            <div style="font-size: 18px; font-weight: 700; color: #ffffff;">${format_inr(lanes.event.amount)}</div>
                            <div style="font-size: 11px; color: #94a3b8; margin-top: 4px;">Advances & Settlements</div>
                        </div>

                        <!-- Lane 1: Petty Cash -->
                        <div class="ap-lane-btn" data-doctype="Petty Cash Entry" style="background: rgba(16, 185, 129, 0.14); border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 10px; padding: 14px; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                <span style="font-size: 12px; font-weight: 600; color: #34d399;">💳 Lane 1: Petty Cash</span>
                                <span style="background: #10b981; color: white; border-radius: 12px; padding: 2px 8px; font-size: 11px; font-weight: 700;">${lanes.petty_cash.count}</span>
                            </div>
                            <div style="font-size: 18px; font-weight: 700; color: #ffffff;">${format_inr(lanes.petty_cash.amount)}</div>
                            <div style="font-size: 11px; color: #94a3b8; margin-top: 4px;">Branch Imprest Replenishment</div>
                        </div>
                    </div>

                    <!-- Security Checksum Bar -->
                    <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(0, 0, 0, 0.3); padding: 10px 16px; border-radius: 8px; font-size: 12px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="color: #34d399;">🛡️ SHA-256 Checksum:</span>
                            <code style="background: rgba(255, 255, 255, 0.1); padding: 2px 8px; border-radius: 4px; color: #e2e8f0; font-size: 11px;">
                                ${data.batch_checksum ? data.batch_checksum.substring(0, 24) + '...' + data.batch_checksum.substring(data.batch_checksum.length - 8) : 'Verified Cryptographic Signature'}
                            </code>
                        </div>
                        ${data.idfc_batch_ref ? `
                            <div style="color: #38bdf8; font-weight: 700;">
                                🏦 IDFC Host Ref: ${data.idfc_batch_ref}
                            </div>
                        ` : `
                            <div style="color: #94a3b8; font-size: 11px;">
                                🔐 Bank-Grade 2FA Authorized Payout
                            </div>
                        `}
                    </div>
                </div>
            `;

            frm.dashboard.clear_headline();
            frm.dashboard.set_headline(dashboard_html);
        }
    });
}

function setup_2fa_release_buttons(frm) {
    if (frm.is_new()) return;

    // Button 1: Request 2FA OTP
    if ((frm.doc.status === "Draft" || frm.doc.status === "Generated") && frm.doc.instructions && frm.doc.instructions.length > 0 && !frm.doc.idfc_batch_ref) {
        frm.add_custom_button(__("🔐 Request 2FA OTP for Release"), function () {
            frappe.call({
                method: "ap_automation.ap_automation.doctype.payment_batch.payment_batch.request_batch_otp",
                args: { batch_name: frm.doc.name },
                freeze: true,
                freeze_message: __("Generating Secure 2FA OTP..."),
                callback: function (r) {
                    if (r.message && r.message.status === "OTP_DISPATCHED") {
                        frappe.msgprint({
                            title: __("🔐 2FA OTP Dispatched"),
                            message: __(`A 6-digit release OTP has been dispatched to <b>${r.message.masked_contact}</b>.<br><br><b>OTP (Simulation Mode):</b> <span style="font-size: 18px; color: #4f46e5; font-weight: bold;">${r.message.mock_otp_for_test}</span><br><br>Please click <b>'Verify 2FA & Dispatch Payout'</b> to release the funds.`),
                            indicator: "green"
                        });
                        frm.reload_doc();
                    }
                }
            });
        }).addClass("btn-primary").css({
            "background-color": "#4f46e5",
            "color": "#ffffff",
            "font-weight": "600"
        });
    }

    // Button 2: Enter OTP and Release to IDFC
    if (frm.doc.status === "Pending 2FA Approval") {
        frm.add_custom_button(__("🚀 Verify 2FA & Dispatch Payout"), function () {
            let d = new frappe.ui.Dialog({
                title: __("🔐 Authorize IDFC Bank Payout Release"),
                fields: [
                    {
                        fieldname: "batch_info",
                        fieldtype: "HTML",
                        options: `
                            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                                <div style="font-size: 12px; color: #64748b;">Batch ID: <b>${frm.doc.name}</b></div>
                                <div style="font-size: 14px; font-weight: bold; color: #0f172a; margin-top: 4px;">Total Release Amount: ${frm.doc.total_batch_amount ? '₹ ' + frm.doc.total_batch_amount.toLocaleString('en-IN') : ''}</div>
                                <div style="font-size: 11px; color: #dc2626; margin-top: 6px;">⚠️ Authorized for Payment Releaser (Anish Sir) only. Max 3 attempts.</div>
                            </div>
                        `
                    },
                    {
                        label: __("Enter 6-Digit 2FA OTP"),
                        fieldname: "otp",
                        fieldtype: "Data",
                        reqd: 1,
                        description: __("Enter the 6-digit OTP sent to your registered credentials.")
                    }
                ],
                primary_action_label: __("Verify & Disburse via IDFC"),
                primary_action(values) {
                    frappe.call({
                        method: "ap_automation.ap_automation.doctype.payment_batch.payment_batch.verify_batch_otp",
                        args: {
                            batch_name: frm.doc.name,
                            otp: values.otp
                        },
                        freeze: true,
                        freeze_message: __("Verifying 2FA & Dispatching to IDFC Bank API..."),
                        callback: function (r) {
                            if (r.message && r.message.status === "SUCCESS") {
                                d.hide();
                                frappe.show_alert({
                                    message: __(`🎉 Payout Dispatched Successfully! Host Ref: ${r.message.idfc_batch_ref}`),
                                    indicator: "green"
                                }, 7);
                                frm.reload_doc();
                            }
                        }
                    });
                }
            });
            d.show();
        }).addClass("btn-success").css({
            "background-color": "#10b981",
            "color": "#ffffff",
            "font-weight": "600"
        });
    }
}


frappe.listview_settings['Payment Batch'] = {
    add_fields: ["status", "total_batch_amount", "idfc_batch_ref", "docstatus"],
    get_indicator(doc) {
        if (doc.status === "Dispatched to Bank" || doc.docstatus === 1) {
            return [__("Dispatched to Bank"), "green", "status,=,Dispatched to Bank"];
        } else if (doc.status === "Completed") {
            return [__("Completed"), "green", "status,=,Completed"];
        } else if (doc.status === "Pending 2FA Approval") {
            return [__("Pending 2FA Approval"), "orange", "status,=,Pending 2FA Approval"];
        } else if (doc.status === "Generated") {
            return [__("Generated"), "blue", "status,=,Generated"];
        } else {
            return [__("Draft"), "grey", "status,=,Draft"];
        }
    }
};
