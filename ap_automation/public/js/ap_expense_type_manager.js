/**
 * AP Automation - Enterprise Dynamic Expense Type Master Manager
 * Centralized Add, Edit, Delete / Deactivate & In-Grid Option Sync
 * Works seamlessly across Petty Cash, Admin Weekly Vendor Claims, Event Spends, Employee Reimbursements, and View Receipt Gallery.
 */

window.APExpenseTypeManager = {
    triggerOption: '➕ Add New Expense Type...',

    getTypes: function (module_scope, callback) {
        frappe.call({
            method: 'ap_automation.services.attachment_service.get_active_expense_types',
            args: { module_scope: module_scope || 'All' },
            callback: function (r) {
                if (callback) callback(r.message || []);
            }
        });
    },

    getRecords: function (module_scope, callback) {
        frappe.call({
            method: 'ap_automation.services.attachment_service.get_expense_type_records',
            args: { module_scope: module_scope || 'All' },
            callback: function (r) {
                if (callback) callback(r.message || []);
            }
        });
    },

    refreshGridOptions: function (frm, table_field, column_field, module_scope, callback) {
        const self = this;
        self.getTypes(module_scope, function (types) {
            const all_options = [''].concat(types);
            if (frm && frm.fields_dict && frm.fields_dict[table_field] && frm.fields_dict[table_field].grid) {
                const grid = frm.fields_dict[table_field].grid;
                const df = grid.docfields ? grid.docfields.find(f => f.fieldname === column_field) : null;
                if (df) {
                    df.options = all_options.join('\n');
                }
            }
            if (callback) callback(types);
        });
    },

    handleGridAddPrompt: function (frm, cdt, cdn, column_field, module_scope) {
        const self = this;
        const row = locals[cdt][cdn];
        if (row[column_field] !== self.triggerOption) return;

        // Reset the cell immediately so trigger string is not stored in data model
        frappe.model.set_value(cdt, cdn, column_field, '');

        // Determine table_field
        let table_field = '';
        if (frm && frm.fields_dict) {
            if (frm.fields_dict['expense_lines']) table_field = 'expense_lines';
            else if (frm.fields_dict['vendor_lines']) table_field = 'vendor_lines';
            else if (frm.fields_dict['expense_items']) table_field = 'expense_items';
            else if (frm.fields_dict['reimbursement_lines']) table_field = 'reimbursement_lines';
        }

        const is_vendor_grid = (column_field === 'vendor_category' || module_scope === 'Admin Weekly Vendor Claims');
        const grid_label = is_vendor_grid ? __('Vendor Category') : (module_scope === 'Events' ? __('Expense Category') : __('Expense Type'));

        const d = new frappe.ui.Dialog({
            title: __(`➕ Add New ${grid_label}`),
            fields: [
                {
                    fieldname: 'type_name',
                    fieldtype: 'Data',
                    label: __(`${grid_label} Name`),
                    placeholder: is_vendor_grid ? __('e.g. Courier & Logistics, Office Pantry, IT Support') : __('e.g. Courier & Logistics, Pantry, Event Catering'),
                    reqd: 1
                },
                {
                    fieldname: 'module_scope',
                    fieldtype: 'Select',
                    label: __('Module Scope'),
                    options: 'All\nPetty Cash\nAdmin Weekly Vendor Claims\nEvents\nEmployee Reimbursements\nVendor Invoices',
                    default: module_scope || 'All',
                    reqd: 1
                },
                {
                    fieldname: 'description',
                    fieldtype: 'Small Text',
                    label: __('Description / Guidelines (Optional)')
                }
            ],
            primary_action_label: __('Save & Apply'),
            primary_action: function (values) {
                const type_name = (values.type_name || '').trim();
                if (!type_name) {
                    frappe.msgprint(__('Please provide a valid Expense Type name.'));
                    return;
                }
                d.hide();

                frappe.call({
                    method: 'ap_automation.services.attachment_service.create_or_edit_expense_type',
                    args: {
                        type_name: type_name,
                        module_scope: values.module_scope || module_scope || 'All',
                        description: values.description || ''
                    },
                    freeze: true,
                    freeze_message: __('Saving Expense Type...'),
                    callback: function (res) {
                        if (res.message && (res.message.status === 'created' || res.message.status === 'updated')) {
                            const final_name = res.message.type_name;

                            // 1. Immediately inject the new type into grid docfield options BEFORE model update
                            let grid = null;
                            if (table_field && frm.fields_dict[table_field] && frm.fields_dict[table_field].grid) {
                                grid = frm.fields_dict[table_field].grid;
                                const df = grid.docfields ? grid.docfields.find(f => f.fieldname === column_field) : null;
                                if (df) {
                                    let opts = (typeof df.options === 'string') ? df.options.split('\n') : (df.options || []);
                                    if (!opts.includes(final_name)) {
                                        const trigger_idx = opts.indexOf(self.triggerOption);
                                        if (trigger_idx !== -1) {
                                            opts.splice(trigger_idx, 0, final_name);
                                        } else {
                                            opts.push(final_name);
                                        }
                                        df.options = Array.isArray(df.options) ? opts : opts.join('\n');
                                    }
                                }
                            }

                            // 2. Set the model value
                            frappe.model.set_value(cdt, cdn, column_field, final_name);

                            // 3. Immediately update the active DOM cell in the grid row so it renders without delay!
                            if (grid) {
                                const grid_row = grid.grid_rows_by_docname ? grid.grid_rows_by_docname[cdn] : null;
                                if (grid_row) {
                                    if (grid_row.doc) {
                                        grid_row.doc[column_field] = final_name;
                                    }

                                    // If cell has active select control in DOM, inject option and set value
                                    const $cell = $(grid_row.row).find(`[data-fieldname="${column_field}"]`);
                                    const $select = $cell.find('select');
                                    if ($select.length) {
                                        if (!$select.find(`option[value="${final_name}"]`).length) {
                                            const $triggerOpt = $select.find(`option:contains("${self.triggerOption}")`);
                                            if ($triggerOpt.length) {
                                                $(`<option value="${final_name}">${final_name}</option>`).insertBefore($triggerOpt);
                                            } else {
                                                $select.append(`<option value="${final_name}">${final_name}</option>`);
                                            }
                                        }
                                        $select.val(final_name);
                                        $select.trigger('change');
                                    }

                                    // If static text area is present, update text directly
                                    const $static = $cell.find('.static-area, .grid-static-col, .ellipsis');
                                    if ($static.length) {
                                        $static.text(final_name);
                                    }

                                    if (typeof grid_row.refresh_field === 'function') {
                                        grid_row.refresh_field(column_field);
                                    }
                                }

                                frm.refresh_field(table_field);
                            }

                            frappe.show_alert({
                                message: __(`✅ Expense Type <b>${final_name}</b> added and selected!`),
                                indicator: 'green'
                            }, 4);

                            // 4. Background sync full options from server
                            if (table_field) {
                                self.refreshGridOptions(frm, table_field, column_field, module_scope);
                            }
                        }
                    }
                });
            }
        });
        d.show();
    },

    openManageDialog: function (frm, table_field, column_field, module_scope) {
        const self = this;
        self.getRecords(module_scope, function (records) {
            let filter_query = '';

            const render_list = function ($container) {
                const filtered = records.filter(r => {
                    if (!filter_query) return true;
                    return (r.type_name || '').toLowerCase().includes(filter_query.toLowerCase()) ||
                           (r.module_scope || '').toLowerCase().includes(filter_query.toLowerCase());
                });

                if (filtered.length === 0) {
                    $container.html(`
                        <div style="padding: 24px; text-align: center; color: #64748b; font-size: 13px;">
                            No expense types found. Add one below!
                        </div>
                    `);
                    return;
                }

                let html = filtered.map((item, idx) => {
                    const is_active = parseInt(item.is_active) === 1;
                    const status_badge = is_active ?
                        '<span style="background: #dcfce7; color: #15803d; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">● Active</span>' :
                        '<span style="background: #fee2e2; color: #b91c1c; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">○ Inactive</span>';

                    return `
                        <div class="ap-type-row-item" data-name="${item.name}" style="
                            display: flex; justify-content: space-between; align-items: center;
                            padding: 8px 12px; border-bottom: 1px solid #f1f5f9;
                            background: ${idx % 2 === 0 ? '#ffffff' : '#f8fafc'};
                        ">
                            <div style="display: flex; flex-direction: column; gap: 2px;">
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="font-size: 13px; font-weight: 600; color: #0f172a;">🏷️ ${item.type_name}</span>
                                    <span style="background: #e2e8f0; color: #334155; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 3px;">
                                        ${item.module_scope || 'All'}
                                    </span>
                                </div>
                                ${item.description ? `<span style="font-size: 11px; color: #64748b;">${item.description}</span>` : ''}
                            </div>
                            <div style="display: flex; align-items: center; gap: 8px;">
                                ${status_badge}
                                <button class="btn btn-xs btn-default ap-edit-type-master-btn" data-name="${item.name}" style="padding: 2px 8px; font-size: 11px; border-radius: 4px; cursor: pointer;">
                                    ✏️ Edit
                                </button>
                                <button class="btn btn-xs ${is_active ? 'btn-danger' : 'btn-primary'} ap-toggle-type-master-btn" data-name="${item.name}" data-active="${item.is_active}" style="padding: 2px 8px; font-size: 11px; border-radius: 4px; cursor: pointer;">
                                    ${is_active ? '🗑️ Deactivate' : '✓ Activate'}
                                </button>
                            </div>
                        </div>
                    `;
                }).join('');

                $container.html(html);

                // Bind Edit action
                $container.find('.ap-edit-type-master-btn').on('click', function () {
                    const docname = $(this).attr('data-name');
                    const target = records.find(r => r.name === docname);
                    if (!target) return;

                    frappe.prompt([
                        {
                            fieldname: 'type_name',
                            fieldtype: 'Data',
                            label: __('Expense Type Name'),
                            default: target.type_name,
                            reqd: 1
                        },
                        {
                            fieldname: 'module_scope',
                            fieldtype: 'Select',
                            label: __('Module Scope'),
                            options: 'All\nPetty Cash\nAdmin Weekly Vendor Claims\nEvents\nEmployee Reimbursements\nVendor Invoices',
                            default: target.module_scope || 'All',
                            reqd: 1
                        },
                        {
                            fieldname: 'is_active',
                            fieldtype: 'Check',
                            label: __('Is Active'),
                            default: target.is_active
                        },
                        {
                            fieldname: 'description',
                            fieldtype: 'Small Text',
                            label: __('Description / Guidelines'),
                            default: target.description || ''
                        }
                    ], function (vals) {
                        frappe.call({
                            method: 'ap_automation.services.attachment_service.create_or_edit_expense_type',
                            args: {
                                type_name: vals.type_name,
                                old_name: target.name,
                                module_scope: vals.module_scope,
                                is_active: vals.is_active,
                                description: vals.description
                            },
                            freeze: true,
                            freeze_message: __('Updating Expense Type...'),
                            callback: function (res) {
                                if (res.message) {
                                    target.type_name = vals.type_name;
                                    target.name = res.message.type_name;
                                    target.module_scope = vals.module_scope;
                                    target.is_active = vals.is_active;
                                    target.description = vals.description;
                                    render_list($container);
                                    if (table_field && column_field) {
                                        self.refreshGridOptions(frm, table_field, column_field, module_scope);
                                    }
                                    frappe.show_alert({ message: __('✅ Expense Type updated!'), indicator: 'green' }, 3);
                                }
                            }
                        });
                    }, __('Edit Expense Type: ' + target.type_name), __('Save Changes'));
                });

                // Bind Toggle / Delete action
                $container.find('.ap-toggle-type-master-btn').on('click', function () {
                    const docname = $(this).attr('data-name');
                    const target = records.find(r => r.name === docname);
                    if (!target) return;

                    const current_active = parseInt(target.is_active) === 1;
                    const action_text = current_active ? __('deactivate') : __('activate');

                    frappe.confirm(
                        __(`Are you sure you want to ${action_text} Expense Type <b>${target.type_name}</b>?`),
                        function () {
                            const new_active = current_active ? 0 : 1;
                            frappe.call({
                                method: 'ap_automation.services.attachment_service.create_or_edit_expense_type',
                                args: {
                                    type_name: target.type_name,
                                    old_name: target.name,
                                    module_scope: target.module_scope,
                                    is_active: new_active,
                                    description: target.description
                                },
                                callback: function (res) {
                                    if (res.message) {
                                        target.is_active = new_active;
                                        render_list($container);
                                        if (table_field && column_field) {
                                            self.refreshGridOptions(frm, table_field, column_field, module_scope);
                                        }
                                        frappe.show_alert({
                                            message: __(`Expense Type ${target.type_name} is now ${new_active ? 'Active' : 'Inactive'}.`),
                                            indicator: new_active ? 'green' : 'orange'
                                        }, 3);
                                    }
                                }
                            });
                        }
                    );
                });
            };

            const manage_dialog = new frappe.ui.Dialog({
                title: __('⚙️ Manage Expense Types Master'),
                fields: [
                    {
                        fieldname: 'search_types',
                        fieldtype: 'Data',
                        label: __('Search Types'),
                        placeholder: __('Type to filter list...'),
                        change: function () {
                            filter_query = manage_dialog.get_value('search_types') || '';
                            const $list = manage_dialog.$wrapper.find('.ap-types-scroll-box');
                            render_list($list);
                        }
                    },
                    {
                        fieldtype: 'HTML',
                        fieldname: 'types_list_view',
                        options: `
                            <div class="ap-types-scroll-box" style="
                                border: 1px solid #e2e8f0; border-radius: 8px;
                                max-height: 260px; overflow-y: auto; margin-bottom: 16px;
                            "></div>
                        `
                    },
                    {
                        fieldname: 'sb_add',
                        fieldtype: 'Section Break',
                        label: __('➕ Add New Expense Type')
                    },
                    {
                        fieldname: 'new_type_name',
                        fieldtype: 'Data',
                        label: __('Type Name'),
                        placeholder: __('e.g. Courier & Logistics, Venue Spends, Travel Meals')
                    },
                    {
                        fieldname: 'new_type_scope',
                        fieldtype: 'Select',
                        label: __('Module Scope'),
                        options: 'All\nPetty Cash\nAdmin Weekly Vendor Claims\nEvents\nEmployee Reimbursements\nVendor Invoices',
                        default: module_scope || 'All'
                    },
                    {
                        fieldname: 'new_type_notes',
                        fieldtype: 'Small Text',
                        label: __('Guidelines / Notes (Optional)')
                    }
                ],
                primary_action_label: __('➕ Create Expense Type'),
                primary_action: function (values) {
                    const name = (values.new_type_name || '').trim();
                    if (!name) {
                        frappe.msgprint(__('Please enter a name for the new Expense Type.'));
                        return;
                    }

                    frappe.call({
                        method: 'ap_automation.services.attachment_service.create_or_edit_expense_type',
                        args: {
                            type_name: name,
                            module_scope: values.new_type_scope || module_scope || 'All',
                            description: values.new_type_notes || '',
                            is_active: 1
                        },
                        freeze: true,
                        freeze_message: __('Creating Expense Type...'),
                        callback: function (res) {
                            if (res.message && (res.message.status === 'created' || res.message.status === 'updated')) {
                                frappe.show_alert({
                                    message: __(`✅ Expense Type <b>${res.message.type_name}</b> saved!`),
                                    indicator: 'green'
                                }, 4);

                                manage_dialog.set_value('new_type_name', '');
                                manage_dialog.set_value('new_type_notes', '');

                                // Re-query records and re-render
                                self.getRecords(module_scope, function (updated_records) {
                                    records.length = 0;
                                    updated_records.forEach(r => records.push(r));
                                    const $list = manage_dialog.$wrapper.find('.ap-types-scroll-box');
                                    render_list($list);

                                    if (table_field && column_field) {
                                        self.refreshGridOptions(frm, table_field, column_field, module_scope);
                                    }
                                });
                            }
                        }
                    });
                }
            });

            manage_dialog.show();
            const $list = manage_dialog.$wrapper.find('.ap-types-scroll-box');
            render_list($list);
        });
    },

    openEditRowTypePrompt: function (doctype, docname, row_idx, current_type, module_scope, callback, custom_label) {
        const self = this;
        const is_vendor = (doctype === 'Admin Weekly Vendor Claim' || doctype === 'Vendor Invoice Claim' || module_scope === 'Admin Weekly Vendor Claims');
        const is_event = (doctype === 'Event Expense Claim' || module_scope === 'Events');
        const label_text = custom_label || (is_vendor ? __('Vendor Category') : (is_event ? __('Expense Category') : __('Expense Type')));

        self.getTypes(module_scope, function (types) {
            let options = types.slice();
            if (current_type && !options.includes(current_type)) {
                options.unshift(current_type);
            }

            const d = new frappe.ui.Dialog({
                title: __(`Edit ${label_text} — Row #${row_idx}`),
                fields: [
                    {
                        fieldname: 'expense_type',
                        fieldtype: 'Select',
                        label: label_text,
                        options: options,
                        default: current_type || options[0],
                        reqd: 1
                    }
                ],
                primary_action_label: __(`Save ${label_text}`),
                primary_action: function (vals) {
                    let final_type = vals.expense_type;
                    d.hide();

                    frappe.call({
                        method: 'ap_automation.services.attachment_service.update_claim_row_expense_type',
                        args: {
                            doctype: doctype,
                            docname: docname,
                            row_idx: row_idx,
                            expense_type: final_type
                        },
                        freeze: true,
                        freeze_message: __(`Updating ${label_text}...`),
                        callback: function (res) {
                            if (res.message && res.message.status === 'success') {
                                frappe.show_alert({
                                    message: __(`✅ Row #${row_idx} ${label_text} updated to <b>${final_type}</b>`),
                                    indicator: 'green'
                                }, 4);
                                if (callback) callback(final_type);
                            }
                        }
                    });
                }
            });

            d.show();
        });
    }
};
