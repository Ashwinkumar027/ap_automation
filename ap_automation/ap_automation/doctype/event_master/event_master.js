// Copyright (c) 2026, Quanti and contributors
// Event Master Interactive Financial Dashboard & Lifecycle Stepper
// 100% Mobile & Desktop Responsive

frappe.ui.form.on("Event Master", {
    refresh: function(frm) {
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
    const spoc_actuals = parseFloat(frm.doc.spoc_actual_spends || 0.0);
    const committed = parseFloat(frm.doc.total_committed_spend || 0.0);
    const remaining = parseFloat(frm.doc.remaining_budget || (budget - committed));
    const util_pct = budget > 0 ? Math.min(Math.round((committed / budget) * 1000) / 10, 100) : 0;
    const raw_pct = budget > 0 ? (committed / budget) * 100 : 0;

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
    const current_status = frm.doc.status || "Planning";
    const steps = [
        { key: "Budget Approved", label: "1. Budget Sanctioned" },
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
    } else if (current_status === "Budget Approved") {
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
                    <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 700; letter-spacing: 0.05em;">Remaining Uncommitted</div>
                    <div style="font-size: 24px; font-weight: 800; color: ${remaining >= 0 ? '#10b981' : '#ef4444'}; letter-spacing: -0.02em;">
                        ${format_inr(remaining)}
                    </div>
                </div>
            </div>

            <!-- 4 Responsive Executive KPI Cards -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 16px;">
                <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #1e40af; text-transform: uppercase; letter-spacing: 0.05em;">Approved Budget</div>
                    <div style="font-size: 18px; font-weight: 700; color: #1e3a8a; margin-top: 4px;">${format_inr(budget)}</div>
                    <div style="font-size: 11px; color: #3b82f6; margin-top: 2px;">Total Board Allocation</div>
                </div>

                <div style="background: #f5f3ff; border: 1px solid #ddd6fe; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #6d28d9; text-transform: uppercase; letter-spacing: 0.05em;">Stream A: Finance Pay</div>
                    <div style="font-size: 18px; font-weight: 700; color: #5b21b6; margin-top: 4px;">${format_inr(direct_finance)}</div>
                    <div style="font-size: 11px; color: #8b5cf6; margin-top: 2px;">Direct Vendor Invoices</div>
                </div>

                <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #b45309; text-transform: uppercase; letter-spacing: 0.05em;">Stream B: SPOC Spends</div>
                    <div style="font-size: 18px; font-weight: 700; color: #92400e; margin-top: 4px;">${format_inr(spoc_actuals)}</div>
                    <div style="font-size: 11px; color: #f59e0b; margin-top: 2px;">Ground Spends & Claims</div>
                </div>

                <div style="background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px;">
                    <div style="font-size: 11px; font-weight: 700; color: #334155; text-transform: uppercase; letter-spacing: 0.05em;">Committed Total</div>
                    <div style="font-size: 18px; font-weight: 700; color: #0f172a; margin-top: 4px;">${format_inr(committed)}</div>
                    <div style="font-size: 11px; color: #64748b; margin-top: 2px;">Stream A + max(Adv, Ground)</div>
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
            <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                ${stepper_html}
            </div>
        </div>
    `;

    frm.dashboard.set_headline(dashboard_html);
}

function setup_event_master_actions(frm) {
    if (frm.is_new()) return;

    // Clear prior custom buttons to prevent duplicates
    frm.page.clear_inner_toolbar();

    const is_closed = frm.doc.status === "Closed" || frm.doc.status === "Cancelled";

    if (!is_closed) {
        // Quick Action 1: Request Advance
        frm.add_custom_button(__('➕ Request Imprest Advance'), function() {
            frappe.route_options = {
                "event": frm.doc.name,
                "company": frm.doc.company
            };
            frappe.new_doc("Event Advance Request");
        }, __('Actions'));

        // Quick Action 2: File Expense Claim
        frm.add_custom_button(__('📋 File Ground Expense Claim'), function() {
            frappe.route_options = {
                "event": frm.doc.name,
                "company": frm.doc.company
            };
            frappe.new_doc("Event Expense Claim");
        }, __('Actions'));

        // Quick Action 3: Settle Event
        frm.add_custom_button(__('⚖️ Reconcile & Settle Event'), function() {
            frappe.route_options = {
                "event": frm.doc.name,
                "company": frm.doc.company
            };
            frappe.new_doc("Event Settlement");
        }, __('Actions'));
    }

    // View Live Report
    frm.add_custom_button(__('📊 View Spend Statement'), function() {
        const print_url = `/printview?doctype=Event%20Master&name=${encodeURIComponent(frm.doc.name)}&format=Event%20Expense%20Report&no_letterhead=0`;
        window.open(print_url, '_blank');
    }, __('Print / Download'));
}
