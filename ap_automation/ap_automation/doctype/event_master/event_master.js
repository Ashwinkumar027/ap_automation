// Copyright (c) 2026, Quanti and contributors
// Event Master Interactive Financial Dashboard & Lifecycle Stepper
// 100% Mobile & Desktop Responsive

frappe.ui.form.on("Event Master", {
    refresh: function(frm) {
        if (frm.doc.docstatus === 0) {
            frm.enable_save();
            if (frm.page.btn_primary) {
                frm.page.btn_primary.show().removeClass('hide');
            }
        }
        $(frm.wrapper).off('dirty.ap_em_save_guard').on('dirty.ap_em_save_guard', function() {
            if (frm.doc.docstatus === 0 && frm.page && frm.page.btn_primary) {
                frm.enable_save();
                frm.page.btn_primary.show().removeClass('hide');
            }
        });
        frm.set_df_property('status', 'read_only', 1);
        const ev_colors = {
            'Event Created': 'blue',
            'Planning': 'grey',
            'Budget Approved': 'blue',
            'Advance Disbursed': 'cyan',
            'In Progress': 'orange',
            'Settlement Pending': 'yellow',
            'Closed': 'green',
            'Cancelled': 'red'
        };
        const st = frm.doc.status || 'Event Created';
        frm.page.set_indicator(__(st), ev_colors[st] || 'blue');
        render_event_master_dashboard(frm);
        setup_event_master_actions(frm);
    },

    allocated_budget: function(frm) {
        render_event_master_dashboard(frm);
    }
});

function format_inr(val) {
    return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        maximumFractionDigits: 2
    }).format(val || 0);
}

function render_event_master_dashboard(frm) {
    if (!frm || !frm.dashboard || frm.is_new()) return;

    // Remove any previous dashboard instances
    $(frm.wrapper).find('.ap-event-master-dashboard').remove();

    const budget = parseFloat(frm.doc.allocated_budget || 0.0);
    const direct_finance = parseFloat(frm.doc.direct_finance_spends || 0.0);
    const disbursed_adv = parseFloat(frm.doc.disbursed_advance || 0.0);
    const spoc_actuals = parseFloat(frm.doc.spoc_actual_spends || 0.0);

    // Dynamic fallback: compute true committed spend if database value is lagging
    const max_ground = Math.max(disbursed_adv, spoc_actuals);
    const calc_committed = direct_finance + max_ground;
    const committed = parseFloat(frm.doc.total_committed_spend || 0.0) > 0 ? parseFloat(frm.doc.total_committed_spend) : calc_committed;
    const remaining = budget > 0 ? Math.round((budget - committed) * 100) / 100 : 0;
    const raw_pct = budget > 0 ? (committed / budget) * 100 : 0;
    const util_pct = budget > 0 ? Math.min(Math.round(raw_pct * 10) / 10, 100) : 0;

    // Overrun status colors
    let bar_color = "#10b981"; // Emerald
    let status_bg = "#ecfdf5";
    let status_border = "#a7f3d0";
    let status_text = "#065f46";
    let status_label = "Within Budget";

    if (raw_pct > 100) {
        bar_color = "#ef4444"; // Red
        status_bg = "#fef2f2";
        status_border = "#fecaca";
        status_text = "#991b1b";
        status_label = "Budget Overrun Alert (>100%)";
    } else if (raw_pct >= 80) {
        bar_color = "#f59e0b"; // Amber
        status_bg = "#fffbeb";
        status_border = "#fde68a";
        status_text = "#92400e";
        status_label = "Approaching Limit (80-100%)";
    }

    // Lifecycle Stepper calculation
    const current_status = frm.doc.status || "Event Created";
    const steps = [
        { key: "Event Created", label: "1. Event Created" },
        { key: "Advance Disbursed", label: "2. Advance Disbursed" },
        { key: "In Progress", label: "3. Ground Spends Active" },
        { key: "Closed", label: "4. Audited & Settled" }
    ];

    let active_step_idx = 0;
    if (current_status === "Closed") {
        active_step_idx = 3;
    } else if (current_status === "In Progress" || spoc_actuals > 0) {
        active_step_idx = 2;
    } else if (current_status === "Advance Disbursed" || parseFloat(frm.doc.disbursed_advance || 0) > 0) {
        active_step_idx = 1;
    } else if (current_status === "Event Created" || current_status === "Budget Approved" || current_status === "Planning") {
        active_step_idx = 0;
    }

    let stepper_html = steps.map((s, idx) => {
        let is_done = idx < active_step_idx || current_status === "Closed";
        let is_current = idx === active_step_idx && current_status !== "Closed";
        let badge_bg = is_current ? "#3b82f6" : is_done ? "#10b981" : "#f1f5f9";
        let badge_text = (is_current || is_done) ? "#ffffff" : "#64748b";
        let icon = is_done ? "✓" : (idx + 1);

        return `
            <div style="flex: 1 1 140px; display: flex; align-items: center; gap: 8px; padding: 6px 10px; background: ${badge_bg}; color: ${badge_text}; border-radius: 6px; font-size: 11px; font-weight: 600; box-shadow: 0 1px 2px rgba(0,0,0,0.05); min-width: 130px;">
                <span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; background: rgba(255,255,255,0.3); font-size: 10px; font-weight: 700;">${icon}</span>
                <span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${s.label}</span>
            </div>
        `;
    }).join("");

    const dashboard_html = `
        <div class="ap-event-master-dashboard" style="
            background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 18px;
            margin-bottom: 20px;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        ">
            <!-- Top Header & Lifecycle Status -->
            <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; border-bottom: 1px solid #f1f5f9; padding-bottom: 12px;">
                <div>
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <span style="font-size: 18px; font-weight: 700; color: #0f172a;">${frm.doc.event_name || frm.doc.name}</span>
                        <span style="background: ${status_bg}; border: 1px solid ${status_border}; color: ${status_text}; font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 14px;">
                            ● ${status_label}
                        </span>
                    </div>
                    <div style="font-size: 12px; color: #64748b; margin-top: 4px;">
                        🏢 Entity: <b>${frm.doc.company || 'Consolidated'}</b> &nbsp;|&nbsp;
                        👤 SPOC: <b>${frm.doc.spoc_name || frm.doc.event_spoc || 'Assigned'}</b> &nbsp;|&nbsp;
                        📍 Venue: <b>${frm.doc.event_location || 'Not Specified'}</b> &nbsp;|&nbsp;
                        📅 Dates: <b>${frm.doc.start_date || 'TBD'}</b> to <b>${frm.doc.end_date || 'TBD'}</b>
                    </div>
                </div>

                <div style="text-align: right; min-width: 140px;">
                    <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 700; letter-spacing: 0.05em;">${remaining >= 0 ? 'Remaining Budget' : 'Over Budget (Reminder)'}</div>
                    <div style="font-size: 24px; font-weight: 800; color: ${remaining >= 0 ? '#10b981' : '#ef4444'}; letter-spacing: -0.02em;">
                        ${format_inr(Math.abs(remaining))}
                    </div>
                </div>
            </div>

            <!-- 4 Responsive Executive KPI Cards -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 16px;">
                <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #1e40af; text-transform: uppercase; letter-spacing: 0.05em;">Event Budget</div>
                    <div style="font-size: 18px; font-weight: 700; color: #1e3a8a; margin-top: 4px;">${format_inr(budget)}</div>
                    <div style="font-size: 11px; color: #3b82f6; margin-top: 2px;">Budget Reminder Only</div>
                </div>

                <div style="background: #f5f3ff; border: 1px solid #ddd6fe; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #6d28d9; text-transform: uppercase; letter-spacing: 0.05em;">Advance Disbursed</div>
                    <div style="font-size: 18px; font-weight: 700; color: #5b21b6; margin-top: 4px;">${format_inr(disbursed_adv)}</div>
                    <div style="font-size: 11px; color: #8b5cf6; margin-top: 2px;">Paid to Event SPOC</div>
                </div>

                <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #b45309; text-transform: uppercase; letter-spacing: 0.05em;">Bills Submitted</div>
                    <div style="font-size: 18px; font-weight: 700; color: #92400e; margin-top: 4px;">${format_inr(spoc_actuals)}</div>
                    <div style="font-size: 11px; color: #f59e0b; margin-top: 2px;">SPOC Expense Claims</div>
                </div>

                <div style="background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #334155; text-transform: uppercase; letter-spacing: 0.05em;">Total Committed</div>
                    <div style="font-size: 18px; font-weight: 700; color: #0f172a; margin-top: 4px;">${format_inr(committed)}</div>
                    <div style="font-size: 11px; color: #64748b; margin-top: 2px;">${direct_finance > 0 ? `Includes Direct Bills ${format_inr(direct_finance)}` : 'max(Advance, Bills)'}</div>
                </div>
            </div>

            <!-- Live Progress Bar -->
            <div style="margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; font-size: 11px; font-weight: 700; color: #475569; margin-bottom: 6px;">
                    <span>Budget Consumption</span>
                    <span>${raw_pct.toFixed(1)}% Utilized</span>
                </div>
                <div style="width: 100%; height: 10px; background: #e2e8f0; border-radius: 5px; overflow: hidden;">
                    <div style="width: ${util_pct}%; height: 100%; background: ${bar_color}; transition: width 0.4s ease-in-out;"></div>
                </div>
            </div>

            <!-- 4-Stage Stepper -->
            <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px;">
                ${stepper_html}
            </div>

            <!-- Unified 1-Stop Command Hub Container -->
            <div id="ap-event-hub-links" style="border-top: 1px solid #e2e8f0; padding-top: 12px;">
                <div style="font-size: 11px; color: #64748b;">Loading linked Advances, Claims &amp; Vendor Invoices...</div>
            </div>
        </div>
    `;

    if (window.APReceiptGallery && typeof window.APReceiptGallery.setHeadlineExclusive === 'function') {
        window.APReceiptGallery.setHeadlineExclusive(frm, dashboard_html);
    } else {
        if (typeof frm.dashboard.clear_headline === 'function') frm.dashboard.clear_headline();
        if (frm.layout && frm.layout.message) frm.layout.message.empty().addClass('hidden');
        frm.dashboard.set_headline(dashboard_html);
    }

    load_event_command_hub_links(frm);
}

function load_event_command_hub_links(frm) {
    if (!frm || frm.is_new()) return;
    const seq = (frm._hub_seq || 0) + 1;
    frm._hub_seq = seq;

    frappe.call({
        method: 'ap_automation.services.event_settlement_service.get_event_command_center_summary',
        args: { event_name: frm.doc.name },
        callback: function(r) {
            if (frm._hub_seq !== seq || !r.message) return;
            const d = r.message;
            frm._active_event_claim = d.active_claim || null;
            const $container = $(frm.wrapper).find('#ap-event-hub-links');
            if (!$container.length) return;

            const pill_row = (title, items, dt, fmt_fn) => {
                if (!items || !items.length) {
                    return `<div style="font-size: 11px; color: #94a3b8; margin-bottom: 6px;"><b>${title}:</b> None filed yet</div>`;
                }
                const chips = items.map(it => {
                    const label = fmt_fn(it);
                    const safe_name = frappe.utils.escape_html(it.name);
                    return `<a href="#" class="ap-hub-doc-link" data-dt="${dt}" data-dn="${safe_name}" style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; background: #ffffff; border: 1px solid #cbd5e1; color: #0f172a; font-size: 11px; font-weight: 700; text-decoration: none; margin: 2px 6px 2px 0;">${label}</a>`;
                }).join('');
                return `<div style="margin-bottom: 8px;"><div style="font-size: 10.5px; font-weight: 700; text-transform: uppercase; color: #475569; margin-bottom: 3px;">${title}</div><div>${chips}</div></div>`;
            };

            const html = `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px;">
                    ${pill_row('1. Event Advances (Pre-Event)', d.advances, 'Event Advance Request', a => `${frappe.utils.escape_html(a.name)} &bull; ${format_inr(a.approved_advance_amount || a.requested_advance_amount)} <span style="color:#475569;">(${frappe.utils.escape_html(a.status || 'Draft')})</span>`)}
                    ${pill_row('2. Expense & Settlement Claims (Post-Event)', d.claims, 'Event Expense Claim', c => {
                        let extra = '';
                        if (parseFloat(c.net_payable_to_spoc || 0) > 0) extra = ` &bull; <span style="color:#1d4ed8;">Pay ${format_inr(c.net_payable_to_spoc)}</span>`;
                        else if (parseFloat(c.refund_receivable_from_spoc || 0) > 0) extra = ` &bull; <span style="color:#c2410c;">Refund ${format_inr(c.refund_receivable_from_spoc)}</span>`;
                        return `${frappe.utils.escape_html(c.name)} &bull; ${format_inr(c.total_claim_amount)}${extra} <span style="color:#475569;">(${frappe.utils.escape_html(c.status || 'Draft')})</span>`;
                    })}
                    ${(d.vendor_invoices && d.vendor_invoices.length) ? pill_row('Linked Vendor Invoices', d.vendor_invoices, 'Vendor Invoice Claim', v => `${frappe.utils.escape_html(v.vendor_name || v.name)} &bull; ${format_inr(v.net_payable_amount || v.total_invoice_amount)} <span style="color:#475569;">(${frappe.utils.escape_html(v.status || 'Draft')})</span>`) : ''}
                    ${(d.legacy_settlements && d.legacy_settlements.length) ? pill_row('Legacy Settlements', d.legacy_settlements, 'Event Settlement', s => `${frappe.utils.escape_html(s.name)} <span style="color:#475569;">(${frappe.utils.escape_html(s.status || 'Draft')})</span>`) : ''}
                </div>
            `;
            $container.html(html);
            $container.off('click', '.ap-hub-doc-link').on('click', '.ap-hub-doc-link', function(e) {
                e.preventDefault();
                const dt = $(this).attr('data-dt');
                const dn = $(this).attr('data-dn');
                if (dt && dn) frappe.set_route('Form', dt, dn);
            });
        }
    });
}

function setup_event_master_actions(frm) {
    if (frm.is_new()) return;

    // Clear prior custom buttons to prevent duplicates
    frm.page.clear_inner_toolbar();

    const is_closed = frm.doc.status === "Closed" || frm.doc.status === "Cancelled";
    const is_sys = frappe.session.user === 'Administrator' || frappe.user.has_role('System Manager');
    const is_spoc_or_owner = (frm.doc.event_spoc === frappe.session.user || frm.doc.owner === frappe.session.user);
    const is_accounts = frappe.user.has_role(['Accounts L1 Auditor', 'Accounts Director', 'Accounts Manager', 'AP Director']) || is_sys;
    const can_intake = is_spoc_or_owner || frappe.user.has_role(['Employee', 'Receptionist', 'Accounts L1 Auditor', 'Accounts Manager', 'AP Director']) || is_sys;

    if (!is_closed && can_intake) {
        // Quick Action 1: Open / File Unified Expense & Settlement Claim (Stream B)
        frm.add_custom_button(__('📋 File Expense & Settlement'), function() {
            if (frm._active_event_claim) {
                frappe.set_route('Form', 'Event Expense Claim', frm._active_event_claim);
                return;
            }
            frappe.route_options = {
                "event": frm.doc.name,
                "company": frm.doc.company
            };
            frappe.new_doc("Event Expense Claim");
        }).addClass('btn-primary');

        // Quick Action 2: Request Advance (Pre-Event)
        frm.add_custom_button(__('➕ Request Advance'), function() {
            frappe.route_options = {
                "event": frm.doc.name,
                "company": frm.doc.company
            };
            frappe.new_doc("Event Advance Request");
        }, __('Actions'));

        // Quick Action 3: Zero-Spend Full Advance Refund (if advance was disbursed)
        if (parseFloat(frm.doc.disbursed_advance || 0) > 0) {
            frm.add_custom_button(__('↩️ Full Advance Refund (₹0 Spend)'), function() {
                frappe.route_options = {
                    "event": frm.doc.name,
                    "company": frm.doc.company,
                    "is_zero_spend_refund": 1,
                    "is_final_settlement": 1
                };
                frappe.new_doc("Event Expense Claim");
            }, __('Actions'));
        }

    }

    // Quick Action 5: Refresh Live Ledger (SPOC / Accounts / Director)
    if (is_spoc_or_owner || is_accounts) {
        frm.add_custom_button(__('🔄 Sync Live Ledger'), function() {
            frappe.call({
                method: 'ap_automation.services.event_budget_service.update_event_budget_ledger',
                args: { event_name: frm.doc.name },
                freeze: true,
                freeze_message: __('Synchronizing Event Ledger...'),
                callback: function(r) {
                    if (r.message) {
                        frm.reload_doc();
                        frappe.show_alert({ message: __('Event budget ledger synchronized successfully!'), indicator: 'green' });
                    }
                }
            });
        }, __('Actions'));
    }

    // Cancel Event (Director / Accounts Director / Accounts Manager only)
    const can_cancel_event = frappe.user.has_role(['AP Director', 'Director', 'Accounts Director', 'Accounts Manager', 'System Manager']) || frappe.session.user === 'Administrator';
    if (!is_closed && can_cancel_event) {
        frm.add_custom_button(__('🚫 Cancel Event'), function() {
            frappe.prompt([
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Cancellation Reason'),
                    reqd: 1
                }
            ], function(values) {
                frappe.call({
                    method: 'ap_automation.ap_automation.doctype.event_master.event_master.cancel_event_master',
                    args: {
                        event_name: frm.doc.name,
                        reason: values.reason
                    },
                    freeze: true,
                    freeze_message: __('Cancelling Event...'),
                    callback: function(r) {
                        if (r.message && r.message.status === 'SUCCESS') {
                            frappe.show_alert({ message: r.message.message, indicator: 'orange' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Cancel Event Master'), __('Cancel Event'));
        }, __('Actions'));
    }

    // View & Export Statements + Aggregated Proofs
    if (window.APReceiptGallery) {
        window.APReceiptGallery.addPrintDownloadButtons(
            frm,
            'Event Master Spend Statement',
            __('📄 Download Statement PDF'),
            __('📊 View Spend Statement')
        );
        window.APReceiptGallery.addExcelExportButton(frm);
        window.APReceiptGallery.refreshEventAggregatedButtons(frm, frm.doc.name);
    }
}
