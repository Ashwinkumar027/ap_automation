/**
 * AP Automation - Universal Two-Way Audit Clarification Thread Engine
 * Features:
 * 1. Non-disruptive clarification queries between Accounts Director, Accounts L1 (Gokul), Admin & Claimant
 * 2. Zero hardcoding: Stakeholders resolved dynamically from AP Approval Matrix & Document fields
 * 3. Immutable audit query stream with sender identity and role badges
 * 4. Multi-party threading with live desk alerts and email notifications
 * 5. One-click "Mark as Resolved" resolution lifecycle
 * 6. File proof attachment integration
 * 7. Live counter header pill with active unresolved alert
 */

window.APClarificationThread = {
    // Cache per form
    _cache: {},

    getRoleBadgeClass: function (role) {
        const r = (role || '').toLowerCase();
        if (r.includes('director')) return 'ap-badge-director';
        if (r.includes('l1') || r.includes('audit') || r.includes('account')) return 'ap-badge-accounts';
        if (r.includes('admin') || r.includes('manager')) return 'ap-badge-admin';
        if (r.includes('claimant') || r.includes('submitter') || r.includes('custodian')) return 'ap-badge-claimant';
        return 'ap-badge-general';
    },

    escapeHtml: function (text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    },

    formatDateTime: function (dt_str) {
        if (!dt_str) return '';
        try {
            return frappe.datetime.prettyDate(dt_str) + ' (' + frappe.datetime.str_to_user(dt_str) + ')';
        } catch (e) {
            return dt_str;
        }
    },

    render: function (frm, force) {
        if (!frm || !frm.doc || frm.is_new()) return;
        const self = this;
        const dt = frm.doc.doctype;
        const dn = frm.doc.name;
        const now = Date.now();
        const key = `${dt}:${dn}:${frm.doc.modified || ''}`;
        if (!force && frm._ap_clarif_inflight === key && (now - (frm._ap_clarif_ts || 0)) < 400) {
            return;
        }
        frm._ap_clarif_inflight = key;
        frm._ap_clarif_ts = now;

        frappe.call({
            method: 'ap_automation.services.clarification_service.get_clarification_thread',
            args: { doctype: dt, docname: dn },
            callback: function (r) {
                if (frm._ap_clarif_inflight === key) {
                    frm._ap_clarif_inflight = null;
                }
                if (r && r.message && r.message.success) {
                    const data = r.message;
                    frm._clarification_thread_data = data;
                    frm._clarification_unresolved_count = data.summary.pending || 0;

                    self.updateHeaderButton(frm, data);
                    self.mountInlineThread(frm, data);
                }
            }
        });
    },

    updateHeaderButton: function (frm, data) {
        const self = this;
        const pending = data.summary.pending || 0;
        const total = data.summary.total || 0;

        let label = __('💬 Clarifications');
        if (pending > 0) {
            label = __(`💬 Clarifications (🔴 ${pending} Open)`);
        } else if (total > 0) {
            label = __(`💬 Clarifications (${total} ✓)`);
        }

        // Add or update custom button
        if (frm.page && frm.page.has_button && frm.page.has_button(label)) {
            return;
        }

        // Clear previous clarification button if label changed
        ['💬 Clarifications', `💬 Clarifications (${total} ✓)`, `💬 Clarifications (🔴 ${pending} Open)`].forEach(b => {
            frm.page.remove_custom_button(b);
        });

        const $btn = frm.add_custom_button(label, function () {
            self.openModal(frm);
        });

        if (pending > 0) {
            $btn.addClass('btn-warning-light').css({
                'background-color': '#fffbeb',
                'border-color': '#f59e0b',
                'color': '#b45309',
                'font-weight': '600'
            });
        }
    },

    mountInlineThread: function (frm, data) {
        const self = this;
        const main = frm.layout.page.main;
        let $container = main.find('.ap-clarification-thread-container');

        if (!$container.length) {
            $container = $(`
                <div class="ap-clarification-thread-container" style="margin: 24px 0; border: 1px solid #e2e8f0; border-radius: 10px; background: #ffffff; box-shadow: 0 1px 3px rgba(0,0,0,0.05); overflow: hidden;">
                </div>
            `);

            // Place right before form footer/timeline
            const $footer = main.find('.form-footer');
            if ($footer.length) {
                $container.insertBefore($footer);
            } else {
                main.append($container);
            }
        }

        $container.html(self.getThreadHTML(frm, data));
        self.bindEvents(frm, $container, data);
    },

    getThreadHTML: function (frm, data) {
        const self = this;
        const summary = data.summary || { total: 0, pending: 0, resolved: 0 };
        const stakeholders = data.stakeholders || [];
        const queries = data.queries || [];
        const cur = data.current_user || {};

        let stake_html = '';
        stakeholders.forEach(s => {
            const icon = s.role.includes('Director') ? '👑' : s.role.includes('L1') ? '💼' : s.role.includes('Admin') ? '🛡️' : '👤';
            stake_html += `
                <span class="ap-stakeholder-chip" title="${self.escapeHtml(s.email)} (${s.source})" style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 16px; font-size: 11px; font-weight: 500; color: #334155;">
                    <span>${icon}</span>
                    <b>${self.escapeHtml(s.role)}:</b>
                    <span>${self.escapeHtml(s.name)}</span>
                </span>
            `;
        });

        let queries_html = '';
        if (queries.length === 0) {
            queries_html = `
                <div style="text-align: center; padding: 32px 16px; color: #64748b; background: #f8fafc; border-radius: 8px; border: 1px dashed #cbd5e1; margin: 12px 0;">
                    <div style="font-size: 28px; margin-bottom: 6px;">💬</div>
                    <div style="font-weight: 600; color: #334155; font-size: 14px;">No Active Clarification Queries</div>
                    <div style="font-size: 12px; margin-top: 4px; max-width: 480px; margin-left: auto; margin-right: auto;">
                        The Accounts Director, Accounts L1 (Gokul), Admin, and Submitter can ask two-way questions here without returning or rejecting the document.
                    </div>
                </div>
            `;
        } else {
            queries.forEach(q => {
                const is_pending = q.query_status === 'Pending Reply';
                const badge_class = self.getRoleBadgeClass(q.from_role_badge);
                const sender_initial = (q.from_full_name || 'U').charAt(0).toUpperCase();

                let attachment_markup = '';
                if (q.attachment) {
                    const fname = q.attachment.split('/').pop();
                    attachment_markup = `
                        <div style="margin-top: 8px;">
                            <a href="${q.attachment}" target="_blank" class="ap-attachment-pill" style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px; font-size: 12px; color: #0284c7; text-decoration: none; font-weight: 500;">
                                <span>📎</span>
                                <span>${self.escapeHtml(fname)}</span>
                                <span style="font-size: 10px; opacity: 0.8;">&nearr;</span>
                            </a>
                        </div>
                    `;
                }

                let resolve_btn_html = '';
                if (is_pending) {
                    resolve_btn_html = `
                        <button class="btn btn-xs btn-default btn-resolve-query" data-query-name="${q.name}" style="background: #ffffff; border: 1px solid #86efac; color: #16a34a; font-weight: 600; border-radius: 4px; padding: 2px 8px;" title="Mark this question as answered/resolved">
                            ✓ Mark Resolved
                        </button>
                    `;
                }

                queries_html += `
                    <div class="ap-query-card" style="display: flex; gap: 12px; padding: 14px 16px; border-bottom: 1px solid #f1f5f9; background: ${q.is_resolution ? '#f0fdf4' : '#ffffff'}; transition: background 0.2s;">
                        <div class="ap-query-avatar" style="width: 36px; height: 36px; border-radius: 50%; background: #0284c7; color: #ffffff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; flex-shrink: 0;">
                            ${sender_initial}
                        </div>
                        <div class="ap-query-content" style="flex: 1; min-width: 0;">
                            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px; margin-bottom: 4px;">
                                <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                                    <span style="font-weight: 700; color: #0f172a; font-size: 13px;">${self.escapeHtml(q.from_full_name)}</span>
                                    <span class="ap-role-badge ${badge_class}" style="font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 600; text-transform: uppercase;">${self.escapeHtml(q.from_role_badge || 'Reviewer')}</span>
                                    <span style="font-size: 12px; color: #64748b;">&rarr;</span>
                                    <span style="font-size: 12px; font-weight: 600; color: #0284c7;">@${self.escapeHtml(q.target_user_name || q.target_role || 'All')}</span>
                                    ${q.is_resolution ? '<span style="font-size: 10px; background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; padding: 1px 6px; border-radius: 4px; font-weight: 700;">RESOLUTION</span>' : ''}
                                </div>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="font-size: 11px; color: #94a3b8;">${self.formatDateTime(q.creation)}</span>
                                    ${is_pending ? '<span class="badge" style="background: #fef3c7; color: #b45309; border: 1px solid #fde68a; font-size: 10px; font-weight: 600; padding: 2px 6px;">🟡 Open</span>' : '<span class="badge" style="background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; font-size: 10px; font-weight: 600; padding: 2px 6px;">🟢 Resolved</span>'}
                                    ${resolve_btn_html}
                                </div>
                            </div>
                            <div style="color: #334155; font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-break: break-word;">${self.escapeHtml(q.message)}</div>
                            ${attachment_markup}
                        </div>
                    </div>
                `;
            });
        }

        // Target dropdown options
        let target_options = `<option value="">-- Select Specific Recipient (or Broadcast to All) --</option>`;
        target_options += `<option value="__ALL__" data-role="Anyone / Public">📢 Anyone / All Stakeholders</option>`;
        stakeholders.forEach(s => {
            if (s.user !== cur.user) {
                target_options += `<option value="${self.escapeHtml(s.user)}" data-role="${self.escapeHtml(s.role)}" data-name="${self.escapeHtml(s.name)}">
                    ${self.escapeHtml(s.role)}: ${self.escapeHtml(s.name)}
                </option>`;
            }
        });

        return `
            <div class="ap-thread-header" style="display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; border-top-left-radius: 10px; border-top-right-radius: 10px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 20px;">💬</span>
                    <div>
                        <div style="font-size: 14px; font-weight: 700; color: #0f172a;">Two-Way Audit Clarification Thread</div>
                        <div style="font-size: 11px; color: #64748b;">Direct collaboration between Accounts Director, Accounts L1 (Gokul), Admin & Claimant</div>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 11px; font-weight: 600; color: #475569;">Total: ${summary.total}</span>
                    ${summary.pending > 0 ? `<span class="badge" style="background: #fef3c7; color: #b45309; border: 1px solid #fde68a; font-weight: 700; font-size: 11px; padding: 3px 8px;">🟡 ${summary.pending} Open</span>` : `<span class="badge" style="background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; font-weight: 700; font-size: 11px; padding: 3px 8px;">🟢 All Resolved</span>`}
                    <button class="btn btn-xs btn-default btn-refresh-clarification" title="Refresh Messages" style="margin-left: 6px; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 8px;">
                        🔄 Refresh
                    </button>
                </div>
            </div>

            <div class="ap-stakeholders-bar" style="display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 18px; background: #ffffff; border-bottom: 1px solid #f1f5f9;">
                <span style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; align-self: center; margin-right: 4px;">Dynamic Participants:</span>
                ${stake_html}
            </div>

            <div class="ap-queries-stream" style="max-height: 420px; overflow-y: auto; background: #ffffff;">
                ${queries_html}
            </div>

            <div class="ap-composer-bar" style="padding: 16px 18px; background: #f8fafc; border-top: 1px solid #e2e8f0; border-bottom-left-radius: 10px; border-bottom-right-radius: 10px;">
                <div style="margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 260px;">
                        <label style="font-size: 11px; font-weight: 700; color: #475569; margin-bottom: 4px; display: block;">ASK QUESTION / DIRECT TO:</label>
                        <select class="form-control input-sm ap-target-user-select" style="font-size: 12px; font-weight: 500;">
                            ${target_options}
                        </select>
                    </div>
                    <div style="display: flex; align-items: center; gap: 6px; margin-top: 18px;">
                        <label class="checkbox-inline" style="font-size: 12px; font-weight: 600; color: #16a34a; margin: 0; cursor: pointer;">
                            <input type="checkbox" class="ap-is-resolution-chk" style="margin-right: 4px;"> This message is a Resolution / Answer
                        </label>
                    </div>
                </div>

                <div style="margin-bottom: 10px;">
                    <textarea class="form-control ap-query-message-input" rows="3" placeholder="Write your question, clarification request, or answer here... (e.g. 'Gokul, please check Row #2 GST rate' or 'Attached revised invoice copy with PAN details')..." style="font-size: 13px; border-radius: 6px; resize: vertical;"></textarea>
                </div>

                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <button class="btn btn-xs btn-default btn-attach-clarification-proof" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; font-weight: 500; font-size: 12px; padding: 5px 10px;">
                            📎 Attach Proof / File
                        </button>
                        <span class="ap-attached-file-badge" style="font-size: 11px; color: #0284c7; font-weight: 600; display: none;"></span>
                        <input type="hidden" class="ap-attached-file-url" value="">
                    </div>
                    <div>
                        <button class="btn btn-sm btn-primary btn-send-clarification-query" style="background: #0284c7; border-color: #0284c7; font-weight: 600; border-radius: 6px; padding: 6px 16px;">
                            <i class="fa fa-paper-plane" style="margin-right: 4px;"></i> Post Clarification
                        </button>
                    </div>
                </div>
            </div>
        `;
    },

    bindEvents: function (frm, $container, data) {
        const self = this;
        const dt = frm.doc.doctype;
        const dn = frm.doc.name;

        // 1. Refresh Button
        $container.find('.btn-refresh-clarification').off('click').on('click', function () {
            self.render(frm, true);
        });

        // 2. Attach File Button via Frappe native FileUploader
        $container.find('.btn-attach-clarification-proof').off('click').on('click', function () {
            new frappe.ui.FileUploader({
                doctype: dt,
                docname: dn,
                folder: 'Home/Attachments',
                on_success: function (file_doc) {
                    if (file_doc && file_doc.file_url) {
                        $container.find('.ap-attached-file-url').val(file_doc.file_url);
                        const fname = file_doc.file_name || file_doc.file_url.split('/').pop();
                        $container.find('.ap-attached-file-badge')
                            .text('✓ ' + fname)
                            .show();
                        frappe.show_alert({ message: __('Proof attached successfully'), indicator: 'green' });
                    }
                }
            });
        });

        // 3. Mark Resolved Button
        $container.find('.btn-resolve-query').off('click').on('click', function () {
            const qname = $(this).attr('data-query-name');
            frappe.confirm(__('Are you sure you want to mark this clarification query as resolved?'), function () {
                frappe.call({
                    method: 'ap_automation.services.clarification_service.mark_query_resolved',
                    args: { query_name: qname },
                    freeze: true,
                    freeze_message: __('Resolving query...'),
                    callback: function (r) {
                        if (r && r.message && r.message.success) {
                            frappe.show_alert({ message: __('Query marked as resolved'), indicator: 'green' });
                            self.render(frm, true);
                        }
                    }
                });
            });
        });

        // 4. Send Clarification Query Button
        $container.find('.btn-send-clarification-query').off('click').on('click', function () {
            const $btn = $(this);
            const msg = ($container.find('.ap-query-message-input').val() || '').trim();
            if (!msg) {
                frappe.msgprint({
                    title: __('Message Required'),
                    message: __('Please enter a clarification question or response before posting.'),
                    indicator: 'orange'
                });
                return;
            }

            const $sel = $container.find('.ap-target-user-select option:selected');
            const target_user_raw = $container.find('.ap-target-user-select').val();
            let target_user = null;
            let target_role = $sel.attr('data-role') || 'Anyone / Public';

            if (target_user_raw && target_user_raw !== '__ALL__') {
                target_user = target_user_raw;
            }

            const attachment = $container.find('.ap-attached-file-url').val() || null;
            const is_resolution = $container.find('.ap-is-resolution-chk').is(':checked') ? 1 : 0;

            $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Posting...');

            frappe.call({
                method: 'ap_automation.services.clarification_service.post_clarification_query',
                args: {
                    doctype: dt,
                    docname: dn,
                    message: msg,
                    target_role: target_role,
                    target_user: target_user,
                    attachment: attachment,
                    is_resolution: is_resolution
                },
                callback: function (r) {
                    $btn.prop('disabled', false).html('<i class="fa fa-paper-plane"></i> Post Clarification');
                    if (r && r.message && r.message.success) {
                        frappe.show_alert({ message: __('Clarification posted and notifications sent!'), indicator: 'green' });
                        $container.find('.ap-query-message-input').val('');
                        $container.find('.ap-attached-file-url').val('');
                        $container.find('.ap-attached-file-badge').text('').hide();
                        $container.find('.ap-is-resolution-chk').prop('checked', false);
                        self.render(frm, true);
                    }
                },
                error: function () {
                    $btn.prop('disabled', false).html('<i class="fa fa-paper-plane"></i> Post Clarification');
                }
            });
        });
    },

    openModal: function (frm) {
        const self = this;
        if (!frm || !frm.doc) return;

        const d = new frappe.ui.Dialog({
            title: __(`💬 Clarification Thread &bull; ${frm.doc.doctype} #${frm.doc.name}`),
            size: 'large'
        });

        d.$body.html(`
            <div class="ap-modal-thread-wrapper" style="margin: -15px;">
                <div class="ap-clarification-thread-container"></div>
            </div>
        `);

        self.mountInlineThread(frm, frm._clarification_thread_data || {
            summary: { total: 0, pending: 0, resolved: 0 },
            stakeholders: [],
            queries: []
        });

        d.show();
    },

    checkUnresolvedQueries: function (frm, onProceed) {
        const self = this;
        const pending = frm._clarification_unresolved_count || 0;
        if (pending > 0) {
            frappe.confirm(
                __(`⚠️ <b>Audit Attention:</b> There are <b>${pending} open clarification query(ies)</b> awaiting response on this document.<br><br>Would you like to review the clarification thread first, or proceed with approval?`),
                function () {
                    // Confirmed proceed
                    if (typeof onProceed === 'function') {
                        onProceed();
                    }
                },
                function () {
                    // Open clarification modal
                    self.openModal(frm);
                }
            );
            return false;
        }
        if (typeof onProceed === 'function') {
            onProceed();
        }
        return true;
    }
};


// Auto-mount on all supported AP Automation Spend Lanes
(function () {
    const AP_DOCTYPES = [
        'Petty Cash Entry',
        'Employee Reimbursement Claim',
        'Vendor Invoice Claim',
        'Admin Weekly Vendor Claim',
        'Event Master',
        'Event Advance Request',
        'Event Expense Claim',
        'Event Settlement',
        'Pre Travel Request'
    ];

    AP_DOCTYPES.forEach(function (dt) {
        frappe.ui.form.on(dt, {
            refresh: function (frm) {
                if (!frm.is_new()) {
                    window.APClarificationThread.render(frm);
                }
            }
        });
    });
})();
