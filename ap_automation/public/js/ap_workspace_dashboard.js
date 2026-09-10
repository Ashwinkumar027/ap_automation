/**
 * AP Automation Hub - Executive Real-Time Command Dashboard
 * Production-grade interactive visual dashboard for /desk/ap-automation
 */

(function () {
    if (window.AP_HUB_DASHBOARD_INITIALIZED) return;
    window.AP_HUB_DASHBOARD_INITIALIZED = true;

    function formatINR(val) {
        let num = parseFloat(val || 0);
        return '₹ ' + num.toLocaleString('en-IN', {
            maximumFractionDigits: 2,
            minimumFractionDigits: 2
        });
    }

    function isAPHubWorkspace() {
        const route = frappe.get_route();
        if (!route || route.length === 0) return false;
        
        const r0 = (route[0] || '').toLowerCase();
        const r1 = (route[1] || '').toLowerCase();
        if (r0 === 'ap-automation' || r0 === 'ap_automation') return true;
        if (r0 === 'workspaces' && (r1 === 'ap-automation' || r1 === 'ap automation' || r1 === 'ap_automation')) return true;
        if (r0 === 'workspace' && (r1 === 'ap-automation' || r1 === 'ap automation' || r1 === 'ap_automation')) return true;
        if (window.location.pathname.includes('/desk/ap-automation') || window.location.hash.includes('ap-automation')) return true;
        
        return false;
    }

    let cachedData = null;

    function showApprovalsModal() {
        if (!cachedData) return;
        const lanes = cachedData.lanes || {};
        const summary = cachedData.summary || {};

        const d = new frappe.ui.Dialog({
            title: __('Pending Approvals Across 4 Spend Lanes (' + summary.total_pending_approvals + ' Total)'),
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'lane_breakdown_html'
                }
            ],
            primary_action_label: __('Close'),
            primary_action: function () {
                d.hide();
            }
        });

        const html = `
            <div style="display: flex; flex-direction: column; gap: 12px; padding: 6px 0;">
                <!-- Lane 1 -->
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #10b981; border-radius: 8px;">
                    <div>
                        <div style="font-weight: 700; color: #1e293b; font-size: 14px;">Lane 1: Petty Cash Entries</div>
                        <div style="font-size: 12px; color: #64748b;">Pending branch vouchers in review</div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="font-size: 13px; font-weight: 700; color: #b45309; background: #fef3c7; padding: 4px 10px; border-radius: 6px;">
                            ${lanes.petty_cash.pending_count} In Review
                        </span>
                        <button class="btn btn-sm btn-default" onclick="frappe.set_route('List', 'Petty Cash Entry', 'List'); cur_dialog.hide();">
                            View Lane <i class="fa fa-arrow-right" style="margin-left: 4px;"></i>
                        </button>
                    </div>
                </div>

                <!-- Lane 2 -->
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #3b82f6; border-radius: 8px;">
                    <div>
                        <div style="font-weight: 700; color: #1e293b; font-size: 14px;">Lane 2: Employee Claims</div>
                        <div style="font-size: 12px; color: #64748b;">Travel & reimbursement claims in review</div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="font-size: 13px; font-weight: 700; color: #b45309; background: #fef3c7; padding: 4px 10px; border-radius: 6px;">
                            ${lanes.employee_claims.pending_count} In Review
                        </span>
                        <button class="btn btn-sm btn-default" onclick="frappe.set_route('List', 'Employee Reimbursement Claim', 'List'); cur_dialog.hide();">
                            View Lane <i class="fa fa-arrow-right" style="margin-left: 4px;"></i>
                        </button>
                    </div>
                </div>

                <!-- Lane 3 -->
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #8b5cf6; border-radius: 8px;">
                    <div>
                        <div style="font-weight: 700; color: #1e293b; font-size: 14px;">Lane 3: Vendor Invoices</div>
                        <div style="font-size: 12px; color: #64748b;">Vendor invoices awaiting PO/3-Way match & review</div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="font-size: 13px; font-weight: 700; color: #b45309; background: #fef3c7; padding: 4px 10px; border-radius: 6px;">
                            ${lanes.vendor_invoices.pending_count} In Review
                        </span>
                        <button class="btn btn-sm btn-default" onclick="frappe.set_route('List', 'Vendor Invoice Claim', 'List'); cur_dialog.hide();">
                            View Lane <i class="fa fa-arrow-right" style="margin-left: 4px;"></i>
                        </button>
                    </div>
                </div>

                <!-- Lane 4 -->
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #f59e0b; border-radius: 8px;">
                    <div>
                        <div style="font-weight: 700; color: #1e293b; font-size: 14px;">Lane 4: Event Spends</div>
                        <div style="font-size: 12px; color: #64748b;">Event budget & advance requests in review</div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="font-size: 13px; font-weight: 700; color: #b45309; background: #fef3c7; padding: 4px 10px; border-radius: 6px;">
                            ${lanes.event_spends.pending_count} In Review
                        </span>
                        <button class="btn btn-sm btn-default" onclick="frappe.set_route('List', 'Event Advance Request', 'List'); cur_dialog.hide();">
                            View Lane <i class="fa fa-arrow-right" style="margin-left: 4px;"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;

        d.fields_dict.lane_breakdown_html.$wrapper.html(html);
        d.show();
    }

    function showLiabilityModal() {
        if (!cachedData) return;
        const lanes = cachedData.lanes || {};
        const summary = cachedData.summary || {};

        const d = new frappe.ui.Dialog({
            title: __('Active Approved Liabilities (' + formatINR(summary.total_approved_liability) + ')'),
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'liability_html'
                }
            ],
            primary_action_label: __('Create Payment Batch'),
            primary_action: function () {
                d.hide();
                frappe.new_doc('Payment Batch');
            }
        });

        const html = `
            <div style="display: flex; flex-direction: column; gap: 12px; padding: 6px 0;">
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #10b981; border-radius: 8px;">
                    <div>
                        <div style="font-weight: 700; color: #1e293b;">Lane 1: Petty Cash</div>
                        <div style="font-size: 12px; color: #64748b;">${lanes.petty_cash.approved_count} Approved Entries</div>
                    </div>
                    <div style="font-size: 14px; font-weight: 700; color: #10b981;">${formatINR(lanes.petty_cash.approved_amount)}</div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #3b82f6; border-radius: 8px;">
                    <div>
                        <div style="font-weight: 700; color: #1e293b;">Lane 2: Employee Claims</div>
                        <div style="font-size: 12px; color: #64748b;">${lanes.employee_claims.approved_count} Approved Claims</div>
                    </div>
                    <div style="font-size: 14px; font-weight: 700; color: #3b82f6;">${formatINR(lanes.employee_claims.approved_amount)}</div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #8b5cf6; border-radius: 8px;">
                    <div>
                        <div style="font-weight: 700; color: #1e293b;">Lane 3: Vendor Invoices</div>
                        <div style="font-size: 12px; color: #64748b;">${lanes.vendor_invoices.approved_count} Approved Invoices</div>
                    </div>
                    <div style="font-size: 14px; font-weight: 700; color: #8b5cf6;">${formatINR(lanes.vendor_invoices.approved_amount)}</div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #f59e0b; border-radius: 8px;">
                    <div>
                        <div style="font-weight: 700; color: #1e293b;">Lane 4: Event Spends</div>
                        <div style="font-size: 12px; color: #64748b;">${lanes.event_spends.approved_count} Approved Advances</div>
                    </div>
                    <div style="font-size: 14px; font-weight: 700; color: #f59e0b;">${formatINR(lanes.event_spends.approved_amount)}</div>
                </div>
            </div>
        `;

        d.fields_dict.liability_html.$wrapper.html(html);
        d.show();
    }

    function renderExecutiveDashboard(isManualRefresh) {
        if (!isAPHubWorkspace()) {
            $('#ap-executive-hub-dashboard').remove();
            return;
        }

        let $target = $('.layout-main-section, .workspace-page, .page-container, #page-ap-automation .page-body').first();
        if ($target.length === 0) return;

        if ($('#ap-executive-hub-dashboard').length === 0) {
            $target.prepend(`
                <div id="ap-executive-hub-dashboard" style="margin-bottom: 24px;">
                    <div id="ap-hub-loading" style="padding: 24px; text-align: center; background: #0b1120; border-radius: 14px; color: #94a3b8; border: 1px solid rgba(255,255,255,0.1);">
                        <i class="fa fa-spinner fa-spin" style="font-size: 20px; margin-right: 8px; color: #818cf8;"></i> Loading Real-Time AP Command Hub Metrics...
                    </div>
                </div>
            `);
        } else if (isManualRefresh) {
            $('#ap-refresh-btn i').addClass('fa-spin');
        }

        frappe.call({
            method: 'ap_automation.services.release_dashboard_service.get_executive_hub_metrics',
            callback: function (r) {
                $('#ap-refresh-btn i').removeClass('fa-spin');
                if (!r.message) return;
                cachedData = r.message;
                const data = r.message;
                const summary = data.summary || {};
                const lanes = data.lanes || {};

                if (isManualRefresh) {
                    frappe.show_alert({
                        message: __('AP Metrics Updated in Real-Time'),
                        indicator: 'green'
                    }, 3);
                }

                const html = `
                <style>
                    #ap-executive-hub-dashboard {
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                    }
                    .ap-command-hero {
                        background: linear-gradient(135deg, #0b1120 0%, #1e1b4b 50%, #0f172a 100%);
                        border: 1px solid rgba(255, 255, 255, 0.14);
                        border-radius: 16px;
                        padding: 24px 28px;
                        color: #ffffff;
                        box-shadow: 0 12px 30px -5px rgba(0, 0, 0, 0.35), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
                        position: relative;
                        overflow: hidden;
                        margin-bottom: 22px;
                    }
                    .ap-command-hero::before {
                        content: "";
                        position: absolute;
                        top: -50%;
                        left: -20%;
                        width: 140%;
                        height: 200%;
                        background: radial-gradient(circle, rgba(99, 102, 241, 0.18) 0%, transparent 60%);
                        pointer-events: none;
                    }
                    .ap-hero-header {
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        border-bottom: 1px solid rgba(255, 255, 255, 0.12);
                        padding-bottom: 16px;
                        margin-bottom: 20px;
                    }
                    .ap-hero-title-group {
                        display: flex;
                        align-items: center;
                        gap: 12px;
                    }
                    .ap-hub-badge {
                        background: rgba(99, 102, 241, 0.25);
                        border: 1px solid rgba(129, 140, 248, 0.45);
                        color: #c7d2fe;
                        padding: 4px 10px;
                        border-radius: 20px;
                        font-size: 11px;
                        font-weight: 700;
                        letter-spacing: 0.5px;
                        text-transform: uppercase;
                    }
                    .ap-bank-status {
                        display: flex;
                        align-items: center;
                        gap: 8px;
                        background: rgba(16, 185, 129, 0.12);
                        border: 1px solid rgba(16, 185, 129, 0.3);
                        color: #6ee7b7;
                        padding: 6px 14px;
                        border-radius: 20px;
                        font-size: 12px;
                        font-weight: 600;
                        cursor: default;
                        user-select: none;
                    }
                    .ap-pulse-dot {
                        width: 8px;
                        height: 8px;
                        background: #10b981;
                        border-radius: 50%;
                        box-shadow: 0 0 0 rgba(16, 185, 129, 0.7);
                        animation: ap-pulse 2s infinite;
                    }
                    @keyframes ap-pulse {
                        0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
                        70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
                        100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
                    }
                    .ap-hero-metrics {
                        display: grid;
                        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
                        gap: 18px;
                        margin-bottom: 20px;
                    }
                    .ap-metric-box {
                        background: rgba(255, 255, 255, 0.05);
                        border: 1px solid rgba(255, 255, 255, 0.1);
                        border-radius: 12px;
                        padding: 16px;
                        backdrop-filter: blur(8px);
                        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                        cursor: pointer;
                        user-select: none;
                    }
                    .ap-metric-box:hover {
                        transform: translateY(-3px);
                        background: rgba(255, 255, 255, 0.09);
                        border-color: rgba(255, 255, 255, 0.25);
                        box-shadow: 0 6px 15px rgba(0, 0, 0, 0.25);
                    }
                    .ap-metric-label {
                        color: #94a3b8;
                        font-size: 12px;
                        font-weight: 600;
                        margin-bottom: 6px;
                        display: flex;
                        align-items: center;
                        gap: 6px;
                    }
                    .ap-metric-val {
                        color: #f8fafc;
                        font-size: 22px;
                        font-weight: 800;
                        letter-spacing: -0.5px;
                    }
                    .ap-metric-sub {
                        color: #cbd5e1;
                        font-size: 11px;
                        margin-top: 5px;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                    }
                    .ap-metric-sub i {
                        opacity: 0.7;
                        transition: opacity 0.2s, transform 0.2s;
                    }
                    .ap-metric-box:hover .ap-metric-sub i {
                        opacity: 1;
                        transform: translateX(3px);
                    }
                    .ap-hero-actions {
                        display: flex;
                        flex-wrap: wrap;
                        gap: 12px;
                        align-items: center;
                        padding-top: 16px;
                        border-top: 1px solid rgba(255, 255, 255, 0.12);
                    }
                    .ap-btn-hero {
                        background: #4f46e5;
                        color: #ffffff !important;
                        border: none;
                        padding: 9px 18px;
                        border-radius: 8px;
                        font-size: 12px;
                        font-weight: 700;
                        display: inline-flex;
                        align-items: center;
                        gap: 7px;
                        cursor: pointer;
                        transition: all 0.2s ease;
                        text-decoration: none;
                        box-shadow: 0 4px 10px rgba(79, 70, 229, 0.35);
                    }
                    .ap-btn-hero:hover {
                        background: #4338ca;
                        transform: translateY(-2px);
                        box-shadow: 0 6px 14px rgba(79, 70, 229, 0.45);
                    }
                    .ap-btn-hero-secondary {
                        background: rgba(255, 255, 255, 0.08);
                        color: #f1f5f9 !important;
                        border: 1px solid rgba(255, 255, 255, 0.2);
                        padding: 8px 16px;
                        border-radius: 8px;
                        font-size: 12px;
                        font-weight: 600;
                        display: inline-flex;
                        align-items: center;
                        gap: 6px;
                        cursor: pointer;
                        transition: all 0.2s ease;
                        text-decoration: none;
                    }
                    .ap-btn-hero-secondary:hover {
                        background: rgba(255, 255, 255, 0.18);
                        border-color: rgba(255, 255, 255, 0.35);
                        transform: translateY(-2px);
                    }
                    /* Lane Cards Grid */
                    .ap-lanes-grid {
                        display: grid;
                        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                        gap: 16px;
                        margin-bottom: 24px;
                    }
                    .ap-lane-card {
                        background: var(--card-bg, #ffffff);
                        border: 1px solid var(--border-color, #e2e8f0);
                        border-radius: 14px;
                        padding: 18px;
                        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
                        position: relative;
                        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                        display: flex;
                        flex-direction: column;
                        justify-content: space-between;
                    }
                    .ap-lane-card:hover {
                        transform: translateY(-4px);
                        box-shadow: 0 12px 20px -3px rgba(0, 0, 0, 0.09);
                        border-color: #cbd5e1;
                    }
                    .ap-lane-top {
                        display: flex;
                        justify-content: space-between;
                        align-items: flex-start;
                        margin-bottom: 12px;
                    }
                    .ap-lane-title {
                        font-size: 14px;
                        font-weight: 700;
                        color: var(--text-color, #1e293b);
                    }
                    .ap-lane-icon {
                        width: 36px;
                        height: 36px;
                        border-radius: 10px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 16px;
                    }
                    .ap-lane-stat {
                        margin-bottom: 8px;
                    }
                    .ap-lane-amount {
                        font-size: 18px;
                        font-weight: 800;
                        color: var(--text-color, #0f172a);
                    }
                    .ap-lane-count-tag {
                        display: inline-flex;
                        align-items: center;
                        gap: 4px;
                        font-size: 11px;
                        padding: 4px 9px;
                        border-radius: 6px;
                        font-weight: 600;
                        cursor: pointer;
                        transition: transform 0.15s;
                    }
                    .ap-lane-count-tag:hover {
                        transform: scale(1.05);
                    }
                    .ap-lane-actions {
                        display: flex;
                        gap: 8px;
                        margin-top: 14px;
                        padding-top: 12px;
                        border-top: 1px solid var(--border-color, #f1f5f9);
                    }
                    .ap-lane-btn {
                        flex: 1;
                        text-align: center;
                        padding: 7px 10px;
                        border-radius: 6px;
                        font-size: 11px;
                        font-weight: 700;
                        border: 1px solid #cbd5e1;
                        background: var(--btn-default-bg, #f8fafc);
                        color: var(--text-color, #334155);
                        cursor: pointer;
                        text-decoration: none;
                        transition: all 0.15s ease;
                        display: inline-flex;
                        align-items: center;
                        justify-content: center;
                        gap: 5px;
                    }
                    .ap-lane-btn:hover {
                        background: #e2e8f0;
                        color: #0f172a;
                        transform: translateY(-1px);
                    }
                    .ap-lane-btn.primary {
                        background: #3b82f6;
                        color: #ffffff !important;
                        border-color: #3b82f6;
                        box-shadow: 0 2px 4px rgba(59, 130, 246, 0.25);
                    }
                    .ap-lane-btn.primary:hover {
                        background: #2563eb;
                        box-shadow: 0 4px 8px rgba(59, 130, 246, 0.35);
                    }
                </style>

                <!-- Hero Section -->
                <div class="ap-command-hero">
                    <div class="ap-hero-header">
                        <div class="ap-hero-title-group">
                            <i class="fa fa-layer-group" style="font-size: 24px; color: #818cf8;"></i>
                            <div>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <h2 style="margin: 0; font-size: 20px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px;">AP Automation Command Hub</h2>
                                    <span class="ap-hub-badge">Executive View</span>
                                </div>
                                <div style="font-size: 12px; color: #94a3b8; margin-top: 2px;">Real-Time Financial Liability & Multi-Lane Payment Gateway</div>
                            </div>
                        </div>
                        <!-- Confidential View-Only Bank Status Indicator -->
                        <div class="ap-bank-status" title="IDFC First Bank Host-to-Host Integration Active">
                            <span class="ap-pulse-dot"></span>
                            <span>IDFC First Bank Connected</span>
                        </div>
                    </div>

                    <div class="ap-hero-metrics">
                        <!-- Metric 1: Active Approved Liability -->
                        <div class="ap-metric-box ap-interactive-btn" data-action="modal_liability" title="View Approved Liability Breakdown">
                            <div class="ap-metric-label"><i class="fa fa-shield-alt" style="color: #34d399;"></i> Active Approved Liability</div>
                            <div class="ap-metric-val" style="color: #34d399;">${formatINR(summary.total_approved_liability)}</div>
                            <div class="ap-metric-sub">
                                <span>Pending Batch Allocation</span>
                                <i class="fa fa-chevron-right"></i>
                            </div>
                        </div>

                        <!-- Metric 2: Approvals in Review (79 Claims Across 4 Lanes) -->
                        <div class="ap-metric-box ap-interactive-btn" data-action="modal_approvals" title="Click to view pending breakdown across all 4 spend lanes">
                            <div class="ap-metric-label"><i class="fa fa-clock" style="color: #fbbf24;"></i> Approvals in Review</div>
                            <div class="ap-metric-val" style="color: #fbbf24;">${summary.total_pending_approvals} Claims</div>
                            <div class="ap-metric-sub">
                                <span>Across 4 Spend Lanes</span>
                                <i class="fa fa-chevron-right"></i>
                            </div>
                        </div>

                        <!-- Metric 3: Unbatched Instructions -->
                        <div class="ap-metric-box ap-interactive-btn" data-action="route" data-route="List/Payment Instruction" title="View Payment Instructions">
                            <div class="ap-metric-label"><i class="fa fa-boxes" style="color: #60a5fa;"></i> Unbatched Instructions</div>
                            <div class="ap-metric-val" style="color: #60a5fa;">${summary.unbatched_instructions_count} (${formatINR(summary.unbatched_instructions_amount)})</div>
                            <div class="ap-metric-sub">
                                <span>Ready for ⚡ Batch Fetch</span>
                                <i class="fa fa-chevron-right"></i>
                            </div>
                        </div>

                        <!-- Metric 4: Batches Pending Release -->
                        <div class="ap-metric-box ap-interactive-btn" data-action="route" data-route="List/Payment Batch" title="Open Payment Batches">
                            <div class="ap-metric-label"><i class="fa fa-file-signature" style="color: #c084fc;"></i> Batches Pending Release</div>
                            <div class="ap-metric-val" style="color: #c084fc;">${summary.pending_batch_release_count} Batches</div>
                            <div class="ap-metric-sub">
                                <span>${formatINR(summary.pending_batch_release_amount)} Awaiting 2FA</span>
                                <i class="fa fa-chevron-right"></i>
                            </div>
                        </div>
                    </div>

                    <div class="ap-hero-actions">
                        <button class="ap-btn-hero ap-interactive-btn" data-action="new_doc" data-doctype="Payment Batch">
                            <i class="fa fa-plus-circle"></i> Create Payment Batch
                        </button>
                        <button class="ap-btn-hero-secondary ap-interactive-btn" data-action="route" data-route="List/Payment Batch">
                            <i class="fa fa-stream"></i> Open Payment Batches
                        </button>
                        <button class="ap-btn-hero-secondary ap-interactive-btn" data-action="route" data-route="List/Payment Instruction">
                            <i class="fa fa-receipt"></i> Payment Instructions
                        </button>
                        <button id="ap-refresh-btn" class="ap-btn-hero-secondary ap-interactive-btn" style="margin-left: auto;" data-action="refresh">
                            <i class="fa fa-sync-alt"></i> Refresh Metrics
                        </button>
                    </div>
                </div>

                <!-- 4 Operational Spend Lanes -->
                <div class="ap-lanes-grid">
                    <!-- Lane 1: Petty Cash -->
                    <div class="ap-lane-card" style="border-top: 4px solid #10b981;">
                        <div>
                            <div class="ap-lane-top">
                                <div>
                                    <div class="ap-lane-title">Lane 1: Petty Cash</div>
                                    <div style="font-size: 11px; color: #64748b;">Branch imprest & vouchers</div>
                                </div>
                                <div class="ap-lane-icon" style="background: rgba(16, 185, 129, 0.12); color: #10b981;">
                                    <i class="fa fa-wallet"></i>
                                </div>
                            </div>
                            <div class="ap-lane-stat">
                                <div style="font-size: 11px; color: #64748b;">Approved Liability:</div>
                                <div class="ap-lane-amount" style="color: #10b981;">${formatINR(lanes.petty_cash.approved_amount)}</div>
                            </div>
                            <div style="margin-top: 6px;">
                                <span class="ap-lane-count-tag ap-interactive-btn" data-action="route" data-route="List/Petty Cash Entry" style="background: #f1f5f9; color: #475569;" title="View Approved Petty Cash Entries">
                                    <i class="fa fa-check-circle" style="color: #10b981;"></i> ${lanes.petty_cash.approved_count} Approved
                                </span>
                                <span class="ap-lane-count-tag ap-interactive-btn" data-action="route" data-route="List/Petty Cash Entry" style="background: #fef3c7; color: #b45309;" title="View Draft/Pending Petty Cash Entries">
                                    <i class="fa fa-clock"></i> ${lanes.petty_cash.pending_count} In Review
                                </span>
                            </div>
                        </div>
                        <div class="ap-lane-actions">
                            <button class="ap-lane-btn primary ap-interactive-btn" data-action="new_doc" data-doctype="Petty Cash Entry">
                                <i class="fa fa-plus"></i> New Entry
                            </button>
                            <button class="ap-lane-btn ap-interactive-btn" data-action="route" data-route="List/Petty Cash Entry">
                                <i class="fa fa-list"></i> View Lane
                            </button>
                        </div>
                    </div>

                    <!-- Lane 2: Employee Claims -->
                    <div class="ap-lane-card" style="border-top: 4px solid #3b82f6;">
                        <div>
                            <div class="ap-lane-top">
                                <div>
                                    <div class="ap-lane-title">Lane 2: Employee Claims</div>
                                    <div style="font-size: 11px; color: #64748b;">Travel & reimbursements</div>
                                </div>
                                <div class="ap-lane-icon" style="background: rgba(59, 130, 246, 0.12); color: #3b82f6;">
                                    <i class="fa fa-user-check"></i>
                                </div>
                            </div>
                            <div class="ap-lane-stat">
                                <div style="font-size: 11px; color: #64748b;">Approved Liability:</div>
                                <div class="ap-lane-amount" style="color: #3b82f6;">${formatINR(lanes.employee_claims.approved_amount)}</div>
                            </div>
                            <div style="margin-top: 6px;">
                                <span class="ap-lane-count-tag ap-interactive-btn" data-action="route" data-route="List/Employee Reimbursement Claim" style="background: #f1f5f9; color: #475569;" title="View Approved Claims">
                                    <i class="fa fa-check-circle" style="color: #3b82f6;"></i> ${lanes.employee_claims.approved_count} Approved
                                </span>
                                <span class="ap-lane-count-tag ap-interactive-btn" data-action="route" data-route="List/Employee Reimbursement Claim" style="background: #fef3c7; color: #b45309;" title="View Pending Claims">
                                    <i class="fa fa-clock"></i> ${lanes.employee_claims.pending_count} In Review
                                </span>
                            </div>
                        </div>
                        <div class="ap-lane-actions">
                            <button class="ap-lane-btn primary ap-interactive-btn" data-action="new_doc" data-doctype="Employee Reimbursement Claim">
                                <i class="fa fa-plus"></i> Submit Claim
                            </button>
                            <button class="ap-lane-btn ap-interactive-btn" data-action="route" data-route="List/Employee Reimbursement Claim">
                                <i class="fa fa-list"></i> View Lane
                            </button>
                        </div>
                    </div>

                    <!-- Lane 3: Vendor Invoices -->
                    <div class="ap-lane-card" style="border-top: 4px solid #8b5cf6;">
                        <div>
                            <div class="ap-lane-top">
                                <div>
                                    <div class="ap-lane-title">Lane 3: Vendor Invoices</div>
                                    <div style="font-size: 11px; color: #64748b;">PO matching & 3-way audit</div>
                                </div>
                                <div class="ap-lane-icon" style="background: rgba(139, 92, 246, 0.12); color: #8b5cf6;">
                                    <i class="fa fa-file-invoice-dollar"></i>
                                </div>
                            </div>
                            <div class="ap-lane-stat">
                                <div style="font-size: 11px; color: #64748b;">Approved Liability:</div>
                                <div class="ap-lane-amount" style="color: #8b5cf6;">${formatINR(lanes.vendor_invoices.approved_amount)}</div>
                            </div>
                            <div style="margin-top: 6px;">
                                <span class="ap-lane-count-tag ap-interactive-btn" data-action="route" data-route="List/Vendor Invoice Claim" style="background: #f1f5f9; color: #475569;" title="View Approved Invoices">
                                    <i class="fa fa-check-circle" style="color: #8b5cf6;"></i> ${lanes.vendor_invoices.approved_count} Approved
                                </span>
                                <span class="ap-lane-count-tag ap-interactive-btn" data-action="route" data-route="List/Vendor Invoice Claim" style="background: #fef3c7; color: #b45309;" title="View Pending Invoices">
                                    <i class="fa fa-clock"></i> ${lanes.vendor_invoices.pending_count} In Review
                                </span>
                            </div>
                        </div>
                        <div class="ap-lane-actions">
                            <button class="ap-lane-btn primary ap-interactive-btn" data-action="new_doc" data-doctype="Vendor Invoice Claim">
                                <i class="fa fa-plus"></i> Upload Invoice
                            </button>
                            <button class="ap-lane-btn ap-interactive-btn" data-action="route" data-route="List/Vendor Invoice Claim">
                                <i class="fa fa-list"></i> View Lane
                            </button>
                        </div>
                    </div>

                    <!-- Lane 4: Event Spends -->
                    <div class="ap-lane-card" style="border-top: 4px solid #f59e0b;">
                        <div>
                            <div class="ap-lane-top">
                                <div>
                                    <div class="ap-lane-title">Lane 4: Event Spends</div>
                                    <div style="font-size: 11px; color: #64748b;">Budgets & advance releases</div>
                                </div>
                                <div class="ap-lane-icon" style="background: rgba(245, 158, 11, 0.12); color: #f59e0b;">
                                    <i class="fa fa-calendar-alt"></i>
                                </div>
                            </div>
                            <div class="ap-lane-stat">
                                <div style="font-size: 11px; color: #64748b;">Approved Liability:</div>
                                <div class="ap-lane-amount" style="color: #f59e0b;">${formatINR(lanes.event_spends.approved_amount)}</div>
                            </div>
                            <div style="margin-top: 6px;">
                                <span class="ap-lane-count-tag ap-interactive-btn" data-action="route" data-route="List/Event Advance Request" style="background: #f1f5f9; color: #475569;" title="View Approved Event Advances">
                                    <i class="fa fa-check-circle" style="color: #f59e0b;"></i> ${lanes.event_spends.approved_count} Approved
                                </span>
                                <span class="ap-lane-count-tag ap-interactive-btn" data-action="route" data-route="List/Event Advance Request" style="background: #fef3c7; color: #b45309;" title="View Pending Event Advances">
                                    <i class="fa fa-clock"></i> ${lanes.event_spends.pending_count} In Review
                                </span>
                            </div>
                        </div>
                        <div class="ap-lane-actions">
                            <button class="ap-lane-btn primary ap-interactive-btn" data-action="new_doc" data-doctype="Event Advance Request">
                                <i class="fa fa-plus"></i> Request Advance
                            </button>
                            <button class="ap-lane-btn ap-interactive-btn" data-action="route" data-route="List/Event Advance Request">
                                <i class="fa fa-list"></i> View Lane
                            </button>
                        </div>
                    </div>
                </div>
                `;

                $('#ap-executive-hub-dashboard').html(html);
            }
        });
    }

    // Delegated Global Click Listener for all Dashboard Buttons, Cards & Actions
    $(document).on('click', '#ap-executive-hub-dashboard .ap-interactive-btn', function (e) {
        e.preventDefault();
        e.stopPropagation();

        const $el = $(this);
        const action = $el.data('action');

        if (action === 'new_doc') {
            const doctype = $el.data('doctype');
            if (doctype) {
                frappe.new_doc(doctype);
            }
        } else if (action === 'route') {
            const routeStr = $el.data('route');
            if (routeStr) {
                const parts = routeStr.split('/');
                frappe.set_route(parts);
            }
        } else if (action === 'modal_approvals') {
            showApprovalsModal();
        } else if (action === 'modal_liability') {
            showLiabilityModal();
        } else if (action === 'refresh') {
            renderExecutiveDashboard(true);
        }
    });

    window.AP_HUB_REFRESH = function () {
        renderExecutiveDashboard(true);
    };

    // Router listeners
    $(document).on('page-change', function () {
        setTimeout(renderExecutiveDashboard, 150);
    });

    if (frappe && frappe.router) {
        frappe.router.on('change', function () {
            setTimeout(renderExecutiveDashboard, 150);
        });
    }

    // Initial mount
    $(document).ready(function () {
        setTimeout(renderExecutiveDashboard, 300);
    });

})();
