frappe.ui.form.on('AP IDFC Settings', {
    refresh: function(frm) {
        frm.add_custom_button(__('Validate Cryptographic Keys'), function() {
            frappe.call({
                method: 'ap_automation.services.idfc_service.test_idfc_connection',
                freeze: true,
                freeze_message: __('Validating RSA Cryptographic Signatures...'),
                callback: function(r) {
                    if (r.message && r.message.status === 'success') {
                        let msg = `
                            <div style="font-size: 13px; line-height: 1.6;">
                                <p style="color: #274E13; font-weight: bold; margin-bottom: 8px;">
                                    <i class="fa fa-check-circle"></i> ${r.message.message}
                                </p>
                                <table class="table table-bordered table-condensed" style="margin-top: 10px;">
                                    <tr><td style="width: 40%; font-weight: 500;">Environment</td><td><b>${r.message.environment}</b></td></tr>
                                    <tr><td style="font-weight: 500;">Target Gateway</td><td><code>${r.message.base_url}</code></td></tr>
                                    <tr><td style="font-weight: 500;">Client ID</td><td><code>${r.message.client_id}</code></td></tr>
                                    <tr><td style="font-weight: 500;">Algorithm</td><td>${r.message.signature_algorithm}</td></tr>
                                    <tr><td style="font-weight: 500;">Signature Preview</td><td><code style="word-break: break-all;">${r.message.signature_preview}</code></td></tr>
                                </table>
                            </div>
                        `;
                        frappe.msgprint({
                            title: __('IDFC Key Health: Operational'),
                            message: msg,
                            indicator: 'green'
                        });
                    } else {
                        frappe.msgprint({
                            title: __('IDFC Key Validation Failed'),
                            message: r.message ? r.message.message : __('Unknown cryptographic error occurred.'),
                            indicator: 'red'
                        });
                    }
                }
            });
        }).addClass('btn-primary');
    }
});
