from typing import Dict, Any, Optional, List, Union
"""
Payment Batch Controller (Submittable)
Represents a converged IDFC payment release batch with multi-stream lane separation
and 2FA OTP release orchestration.
"""
import hashlib
import json
import frappe
from frappe.model.document import Document
from ap_automation.services import release_auth_service, funnel_service, notification_service


class PaymentBatch(Document):
    """
    Controller for Consolidated Payment Batches.
    """

    def before_submit(self):
        """Validate checksum and non-empty items before submission."""
        if not self.instructions:
            frappe.throw("Cannot submit an empty Payment Batch.")
        if self.status not in ("Pending 2FA Approval", "Dispatched to Bank", "Completed"):
            self.status = "Pending 2FA Approval"

    def on_submit(self):
        """Notify Payment Releaser (CEO & MD / Payment Releaser) that batch is ready for 2FA release."""
        try:
            notification_service.notify_releaser_on_batch_ready(self.name)
        except Exception as e:
            frappe.log_error(f"Error notifying releaser for batch {self.name}: {str(e)}", "AP Notification Error")

    def on_update(self):
        """Notify releaser if status transitions to Pending 2FA Approval."""
        if self.has_value_changed("status") and self.status == "Pending 2FA Approval":
            try:
                notification_service.notify_releaser_on_batch_ready(self.name)
            except Exception as e:
                frappe.log_error(f"Error notifying releaser for batch {self.name}: {str(e)}", "AP Notification Error")


@frappe.whitelist()
def fetch_approved_claims_for_batch(batch_name=None, company=None):
    """
    Finds all approved claims across the 4 lanes ready for payment:
    1. Petty Cash Entry (Lane 1)
    2. Employee Reimbursement Claim (Lane 2)
    3. Vendor Invoice Claim (Lane 3)
    4. Event Advance Request & Event Settlement (Lane 4)
    """
    if batch_name and frappe.db.exists("Payment Batch", batch_name):
        doc = frappe.get_doc("Payment Batch", batch_name)
        if not company:
            company = getattr(doc, "company", None) or getattr(doc, "company_entity", None)
            
        # Security & State Validation
        if doc.status in ["Dispatched to Bank", "Completed", "Released"] or getattr(doc, "idfc_batch_ref", None):
            frappe.throw(
                f"Cannot re-fetch claims for Payment Batch {doc.name} because it has already been processed/dispatched to IDFC Bank (Ref: {doc.idfc_batch_ref or doc.status})."
            )
        if doc.docstatus != 0:
            frappe.throw(f"Cannot modify submitted Payment Batch {doc.name}.")
    else:
        doc = None

    if not company:
        frappe.throw("Please select a Company Entity first.")

    found_instructions = []

    # 1. Petty Cash Entries (Lane 1)
    pc_entries = frappe.db.sql(
        """
        SELECT name, company, total_amount, custodian
        FROM `tabPetty Cash Entry`
        WHERE company = %s
          AND status IN ('Approved for Payment', 'Approved', 'Submitted')
          AND (batch_id IS NULL OR batch_id = '' OR batch_id = %s)
        """,
        (company, batch_name or ""),
        as_dict=True
    )
    for pc in pc_entries:
        pi_name = frappe.db.sql(
            """
            SELECT name FROM `tabPayment Instruction`
            WHERE source_doctype = 'Petty Cash Entry'
              AND source_voucher = %s
              AND (batch_id IS NULL OR batch_id = '' OR batch_id = %s)
            LIMIT 1
            """,
            (pc.name, batch_name or ""),
            as_dict=True
        )
        pi_id = pi_name[0].name if pi_name else None
        if not pi_id:
            try:
                pi_id = funnel_service.create_payment_instruction_from_claim("Petty Cash Entry", pc.name)
            except Exception as e:
                frappe.log_error(f"Error creating PI for {pc.name}: {str(e)}")
        if pi_id:
            pi_doc = frappe.get_doc("Payment Instruction", pi_id)
            found_instructions.append(pi_doc)

    # 2. Employee Reimbursement Claims (Lane 2)
    if frappe.db.exists("DocType", "Employee Reimbursement Claim"):
        emp_claims = frappe.db.sql(
            """
            SELECT name FROM `tabEmployee Reimbursement Claim`
            WHERE company = %s
              AND status IN ('Approved for Payment', 'Approved')
              AND (batch_id IS NULL OR batch_id = '' OR batch_id = %s)
            """,
            (company, batch_name or ""),
            as_dict=True
        )
        for ec in emp_claims:
            pi_name = frappe.db.sql(
                """
                SELECT name FROM `tabPayment Instruction`
                WHERE source_doctype = 'Employee Reimbursement Claim'
                  AND source_voucher = %s
                  AND (batch_id IS NULL OR batch_id = '' OR batch_id = %s)
                LIMIT 1
                """,
                (ec.name, batch_name or ""),
                as_dict=True
            )
            pi_id = pi_name[0].name if pi_name else None
            if not pi_id:
                try:
                    pi_id = funnel_service.create_payment_instruction_from_claim("Employee Reimbursement Claim", ec.name)
                except Exception as e:
                    frappe.log_error(f"Error creating PI for {ec.name}: {str(e)}")
            if pi_id:
                found_instructions.append(frappe.get_doc("Payment Instruction", pi_id))

    # 3. Vendor Invoice Claims (Lane 3)
    if frappe.db.exists("DocType", "Vendor Invoice Claim"):
        vendor_claims = frappe.db.sql(
            """
            SELECT name FROM `tabVendor Invoice Claim`
            WHERE company = %s
              AND status IN ('Approved for Payment', 'Approved')
              AND (batch_id IS NULL OR batch_id = '' OR batch_id = %s)
            """,
            (company, batch_name or ""),
            as_dict=True
        )
        for vc in vendor_claims:
            pi_name = frappe.db.sql(
                """
                SELECT name FROM `tabPayment Instruction`
                WHERE source_doctype = 'Vendor Invoice Claim'
                  AND source_voucher = %s
                  AND (batch_id IS NULL OR batch_id = '' OR batch_id = %s)
                LIMIT 1
                """,
                (vc.name, batch_name or ""),
                as_dict=True
            )
            pi_id = pi_name[0].name if pi_name else None
            if not pi_id:
                try:
                    pi_id = funnel_service.create_payment_instruction_from_claim("Vendor Invoice Claim", vc.name)
                except Exception as e:
                    frappe.log_error(f"Error creating PI for {vc.name}: {str(e)}")
            if pi_id:
                found_instructions.append(frappe.get_doc("Payment Instruction", pi_id))

    # 4. Event Advance Requests (Lane 4)
    if frappe.db.exists("DocType", "Event Advance Request"):
        event_claims = frappe.db.sql(
            """
            SELECT name FROM `tabEvent Advance Request`
            WHERE company = %s
              AND status IN ('Approved for Advance', 'Approved for Payment', 'Approved')
              AND (batch_id IS NULL OR batch_id = '' OR batch_id = %s)
            """,
            (company, batch_name or ""),
            as_dict=True
        )
        for ev in event_claims:
            pi_name = frappe.db.sql(
                """
                SELECT name FROM `tabPayment Instruction`
                WHERE source_doctype = 'Event Advance Request'
                  AND source_voucher = %s
                  AND (batch_id IS NULL OR batch_id = '' OR batch_id = %s)
                LIMIT 1
                """,
                (ev.name, batch_name or ""),
                as_dict=True
            )
            pi_id = pi_name[0].name if pi_name else None
            if not pi_id:
                try:
                    pi_id = funnel_service.create_payment_instruction_from_claim("Event Advance Request", ev.name)
                except Exception as e:
                    frappe.log_error(f"Error creating PI for {ev.name}: {str(e)}")
            if pi_id:
                found_instructions.append(frappe.get_doc("Payment Instruction", pi_id))
    # Populate Batch if batch_name is provided
    items_to_return = []
    tot_amt = 0.0

    if doc and doc.docstatus == 0:
        # If no new claims found but the batch ALREADY has instructions, do NOT erase them!
        if not found_instructions and len(doc.instructions) > 0:
            items_to_return = [
                {
                    "payment_instruction": i.payment_instruction,
                    "source_doctype": getattr(i, "source_doctype", "") or getattr(i, "lane_doctype", ""),
                    "source_voucher": getattr(i, "source_voucher", "") or getattr(i, "voucher_id", ""),
                    "beneficiary_name": i.beneficiary_name,
                    "amount": float(i.amount or 0.0),
                    "account_number": getattr(i, "account_number", ""),
                    "ifsc_code": getattr(i, "ifsc_code", "")
                }
                for i in doc.instructions
            ]
            return {
                "status": "SUCCESS",
                "count": len(items_to_return),
                "total_amount": sum(i["amount"] for i in items_to_return),
                "items": items_to_return,
                "message": "No new pending claims found. Existing batch instructions retained."
            }

        if found_instructions:
            doc.set("instructions", [])
            for pi in found_instructions:
                doc.append("instructions", {
                    "payment_instruction": pi.name,
                    "source_doctype": pi.source_doctype,
                    "source_voucher": pi.source_voucher,
                    "beneficiary_name": pi.beneficiary_name,
                    "account_number": pi.beneficiary_account,
                    "ifsc_code": pi.beneficiary_ifsc,
                    "amount": float(pi.payable_amount or 0.0)
                })
                tot_amt += float(pi.payable_amount or 0.0)

            doc.total_batch_amount = tot_amt
            doc.total_instructions = len(found_instructions)

            # Generate Checksum
            checksum_payload = [
                {"pi": i.payment_instruction, "ac": i.account_number, "amt": str(i.amount)}
                for i in doc.instructions
            ]
            doc.batch_checksum = hashlib.sha256(json.dumps(checksum_payload, sort_keys=True).encode("utf-8")).hexdigest()

            doc.save(ignore_permissions=True)
            frappe.db.commit()

            # Update batch_id on Payment Instructions and source vouchers
            for pi in found_instructions:
                frappe.db.set_value("Payment Instruction", pi.name, {"batch_id": doc.name, "status": "Queued in Batch"})
                if pi.source_doctype and pi.source_voucher and frappe.db.exists(pi.source_doctype, pi.source_voucher):
                    try:
                        frappe.db.set_value(pi.source_doctype, pi.source_voucher, {"batch_id": doc.name, "status": "Queued in Batch"})
                    except Exception:
                        pass
            frappe.db.commit()

    for pi in found_instructions:
        items_to_return.append({
            "payment_instruction": pi.name,
            "source_doctype": pi.source_doctype,
            "source_voucher": pi.source_voucher,
            "beneficiary_name": pi.beneficiary_name,
            "amount": float(pi.payable_amount or 0.0),
            "account_number": pi.beneficiary_account,
            "ifsc_code": pi.beneficiary_ifsc
        })

    return {
        "status": "SUCCESS",
        "count": len(items_to_return),
        "total_amount": sum(i["amount"] for i in items_to_return),
        "items": items_to_return
    }


@frappe.whitelist()
def get_batch_summary(batch_name: str):
    """
    Returns a rich multi-lane summary of the payment batch separated by spend stream:
    - Lane 1: Petty Cash
    - Lane 2: Employee Reimbursements
    - Lane 3: Vendor Payments
    - Lane 4: Event Spends & Advances
    """
    if not frappe.db.exists("Payment Batch", batch_name):
        frappe.throw(f"Payment Batch '{batch_name}' not found.")

    doc = frappe.get_doc("Payment Batch", batch_name)

    lane_map = {
        "vendor": {"label": "Vendor Invoices (Lane 3)", "count": 0, "amount": 0.0, "icon": "truck", "color": "#3B82F6", "items": []},
        "reimbursement": {"label": "Employee Reimbursements (Lane 2)", "count": 0, "amount": 0.0, "icon": "user", "color": "#F59E0B", "items": []},
        "event": {"label": "Event Spends (Lane 4)", "count": 0, "amount": 0.0, "icon": "calendar", "color": "#8B5CF6", "items": []},
        "petty_cash": {"label": "Petty Cash (Lane 1)", "count": 0, "amount": 0.0, "icon": "cash", "color": "#10B981", "items": []},
        "other": {"label": "General Claims", "count": 0, "amount": 0.0, "icon": "file-text", "color": "#6B7280", "items": []}
    }

    for row in doc.instructions:
        src_dt = (getattr(row, "source_doctype", None) or getattr(row, "lane_doctype", None) or "").strip()
        amt = float(row.amount or 0.0)

        item_data = {
            "idx": row.idx,
            "payment_instruction": row.payment_instruction,
            "source_doctype": src_dt,
            "source_voucher": getattr(row, "source_voucher", None) or getattr(row, "voucher_id", None),
            "beneficiary_name": row.beneficiary_name,
            "amount": amt,
            "account_number": getattr(row, "account_number", None),
            "ifsc_code": getattr(row, "ifsc_code", None),
            "utr": getattr(row, "utr", None) or getattr(row, "bank_utr", None)
        }

        if "Vendor" in src_dt:
            lane_map["vendor"]["count"] += 1
            lane_map["vendor"]["amount"] += amt
            lane_map["vendor"]["items"].append(item_data)
        elif "Reimbursement" in src_dt or "Travel" in src_dt:
            lane_map["reimbursement"]["count"] += 1
            lane_map["reimbursement"]["amount"] += amt
            lane_map["reimbursement"]["items"].append(item_data)
        elif "Event" in src_dt:
            lane_map["event"]["count"] += 1
            lane_map["event"]["amount"] += amt
            lane_map["event"]["items"].append(item_data)
        elif "Petty" in src_dt:
            lane_map["petty_cash"]["count"] += 1
            lane_map["petty_cash"]["amount"] += amt
            lane_map["petty_cash"]["items"].append(item_data)
        else:
            lane_map["other"]["count"] += 1
            lane_map["other"]["amount"] += amt
            lane_map["other"]["items"].append(item_data)

    return {
        "batch_name": doc.name,
        "company": getattr(doc, "company", None) or getattr(doc, "company_entity", ""),
        "posting_date": str(getattr(doc, "posting_date", None) or getattr(doc, "batch_creation_date", "")),
        "total_batch_amount": float(doc.total_batch_amount or 0.0),
        "total_instructions": int(getattr(doc, "total_instructions", 0) or getattr(doc, "total_payment_count", 0) or len(doc.instructions)),
        "status": doc.status or "Draft",
        "docstatus": doc.docstatus,
        "batch_checksum": getattr(doc, "batch_checksum", None) or getattr(doc, "sha256_integrity_checksum", None),
        "idfc_batch_ref": getattr(doc, "idfc_batch_ref", None),
        "lanes": lane_map
    }


@frappe.whitelist()
def request_batch_otp(batch_name: str):
    """Triggers 2FA OTP for the batch."""
    return release_auth_service.request_release_otp(batch_name, frappe.session.user)


@frappe.whitelist()
def verify_batch_otp(batch_name: str, otp: str):
    """Verifies OTP and authorizes IDFC release."""
    return release_auth_service.verify_otp_and_authorize_release(batch_name, otp, frappe.session.user)


@frappe.whitelist()
def mark_bank_file_exported(batch_name: str) -> Dict[str, Any]:
    """
    Transitions the Payment Batch to 'Bank File Exported' status
    when accounts operator downloads the bank upload CSV / TXT.
    """
    if not frappe.db.exists("Payment Batch", batch_name):
        frappe.throw(f"Payment Batch '{batch_name}' not found.")

    batch = frappe.get_doc("Payment Batch", batch_name)
    if batch.status in ("Dispatched to Bank", "Completed", "Paid"):
        return {"status": "SUCCESS", "current_status": batch.status}

    batch.status = "Bank File Exported"
    batch.add_comment("Comment", f"Bank upload payment file exported by {frappe.session.user}.")
    batch.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "SUCCESS",
        "batch_name": batch.name,
        "new_status": batch.status,
        "message": f"Payment Batch #{batch.name} marked as 'Bank File Exported'."
    }