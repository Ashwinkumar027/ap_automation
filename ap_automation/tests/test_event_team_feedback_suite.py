# Copyright (c) 2026, Quanti and contributors
# Test suite for Event Team Feedback & Dynamic UI Department Filtering

import unittest
from unittest.mock import MagicMock, patch
import json
import frappe
from ap_automation.exceptions import APValidationError


class TestEventTeamFeedbackSuite(unittest.TestCase):
    def setUp(self):
        frappe.local.session = MagicMock(user="test_admin@aionioncapital.com")
        frappe.local.request_ip = "127.0.0.1"
        frappe.local.site = "accpay1.local"
        frappe.local.flags = frappe._dict(mute_messages=True, in_test=True, in_install=False, in_migrate=False)
        frappe.flags = frappe.local.flags
        frappe.local.db = MagicMock()
        frappe.db = frappe.local.db

    def test_get_event_spoc_users_with_ui_departments(self):
        """Verifies get_event_spoc_users filters dynamically by UI-provided departments."""
        from ap_automation.services.event_budget_service import get_event_spoc_users

        frappe.db.sql.return_value = [
            ["event_lead@company.com", "Event Lead (Event Management - ACM)"],
            ["comm_lead@company.com", "Comm Lead (Corporate Communication & Marketing)"]
        ]

        # Pass multiple departments selected in UI
        ui_departments = ["Event Management - ACM", "Corporate Communication & Marketing"]
        results = get_event_spoc_users(
            doctype="User",
            txt="",
            searchfield="user_id",
            start=0,
            page_len=20,
            filters={"departments": ui_departments}
        )

        self.assertEqual(len(results), 2)
        frappe.db.sql.assert_called_once()
        call_args = frappe.db.sql.call_args[0]
        query = call_args[0]
        params = call_args[1]
        self.assertIn("e.department IN %(departments)s", query)
        self.assertEqual(params["departments"], tuple(ui_departments))

    @patch("frappe.get_all")
    def test_validate_event_spoc_department_allowed_and_blocked(self, mock_get_all):
        """Verifies validate_event_spoc_department enforces allowed departments."""
        from ap_automation.services.event_budget_service import validate_event_spoc_department

        allowed_depts = ["Event Management - ACM", "Corporate Communication & Marketing"]

        # Case 1: Employee is in allowed department
        frappe.db.get_value.return_value = {
            "name": "EMP-001",
            "employee_name": "Event Specialist",
            "department": "Event Management - ACM"
        }
        # Should not raise exception
        validate_event_spoc_department("event_emp@company.com", allowed_depts, "Event Master")

        # Case 2: Employee is in unauthorized department (e.g. IT - QSSPL)
        frappe.db.get_value.return_value = {
            "name": "EMP-002",
            "employee_name": "IT Admin",
            "department": "IT - QSSPL"
        }
        mock_get_all.return_value = ["Event Management", "Corporate Communication & Marketing"]

        with self.assertRaises(APValidationError) as ctx:
            validate_event_spoc_department("it_user@company.com", allowed_depts, "Event Master")
        self.assertIn("SPOC Department Restriction", str(ctx.exception))
        self.assertIn("IT - QSSPL", str(ctx.exception))

    def test_event_imprest_gst_auto_calculation(self):
        """Verifies GST amount and Total Amount formula in EventAdvanceRequest.validate()."""
        from ap_automation.ap_automation.doctype.event_advance_request.event_advance_request import EventAdvanceRequest

        frappe.db.get_value.side_effect = lambda dt, dn, fn=None: {
            ("Event Master", "EVT-TEST"): "Planning",
            ("Company", "Company A"): "Letter Head A"
        }.get((dt, dn), "Test")

        ear = EventAdvanceRequest.__new__(EventAdvanceRequest)
        ear.doctype = "Event Advance Request"
        ear.name = "EAR-2026-TEST01"
        ear.event = "EVT-TEST"
        ear.company = "Company A"
        ear.spoc = "spoc@company.com"
        ear.spoc_name = "SPOC User"
        ear.allowed_departments = []
        ear.flags = MagicMock()
        ear.imprest_items = [
            MagicMock(
                particulars="Sound & Stage Setup",
                base_amount=10000.0,
                gst_rate="18%",
                gst_amount=0.0,
                amount=0.0,
                payment_mode="Direct Vendor Payment",
                beneficiary_name="Stage Vendor",
                bank_account_number="98765432101",
                bank_ifsc_code="IDFB0040101"
            ),
            MagicMock(
                particulars="Per Diem Food Cash",
                base_amount=5000.0,
                gst_rate="0%",
                gst_amount=0.0,
                amount=0.0,
                payment_mode="Petty Cash",
                beneficiary_name=""
            )
        ]

        with patch("ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.validate_advance_request"), \
             patch("ap_automation.controllers.ap_document.APDocument.validate"):
            ear.validate()

        row1 = ear.imprest_items[0]
        self.assertEqual(row1.gst_amount, 1800.0)  # 10000 * 18%
        self.assertEqual(row1.amount, 11800.0)      # 10000 + 1800

        row2 = ear.imprest_items[1]
        self.assertEqual(row2.gst_amount, 0.0)
        self.assertEqual(row2.amount, 5000.0)
        # Beneficiary should default to SPOC name
        self.assertEqual(row2.beneficiary_name, "SPOC User")

        # Check doc totals
        self.assertEqual(ear.total_direct_vendor_amount, 11800.0)
        self.assertEqual(ear.total_cash_imprest_amount, 5000.0)
        self.assertEqual(ear.requested_advance_amount, 16800.0)

    def test_event_imprest_upi_vendor_payment(self):
        """Verifies Direct Vendor Payment (UPI) accepts valid VPA and blocks invalid format."""
        from ap_automation.ap_automation.doctype.event_advance_request.event_advance_request import EventAdvanceRequest

        frappe.db.get_value.return_value = "Planning"

        ear = EventAdvanceRequest.__new__(EventAdvanceRequest)
        ear.doctype = "Event Advance Request"
        ear.name = "EAR-2026-UPI"
        ear.event = "EVT-TEST"
        ear.company = "Company A"
        ear.spoc = "spoc@company.com"
        ear.allowed_departments = []
        ear.status = "Pending Director Approval"
        ear.flags = MagicMock()

        # Valid UPI ID
        ear.imprest_items = [
            MagicMock(
                particulars="Catering Vendor via UPI",
                base_amount=4000.0,
                gst_rate="5%",
                gst_amount=0.0,
                amount=0.0,
                payment_mode="Direct Vendor Payment (UPI)",
                beneficiary_name="Quick Caterer",
                upi_id="caterer@okhdfcbank",
                bank_account_number="",
                bank_ifsc_code=""
            )
        ]

        with patch("ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.validate_advance_request"), \
             patch("ap_automation.controllers.ap_document.APDocument.validate"):
            ear.validate()

        self.assertEqual(ear.imprest_items[0].gst_amount, 200.0)
        self.assertEqual(ear.imprest_items[0].amount, 4200.0)

        # Invalid UPI format
        ear.imprest_items[0].upi_id = "invalid-vpa-format"
        with self.assertRaises(APValidationError) as ctx:
            with patch("ap_automation.ap_automation.doctype.event_advance_request.event_advance_request.validate_advance_request"), \
                 patch("ap_automation.controllers.ap_document.APDocument.validate"):
                ear.validate()
        self.assertIn("Invalid UPI ID / VPA", str(ctx.exception))

    def test_json_schemas_contain_all_feedback_modifications(self):
        """Verifies JSON schema definitions for all 8 feedback requirements."""
        base_dir = "/home/ashwinkumark_quanti/frappe/my-bench/apps/ap_automation/ap_automation/ap_automation/doctype"

        # 1. Event Imprest Item
        with open(f"{base_dir}/event_imprest_item/event_imprest_item.json") as f:
            eii = json.load(f)
        fields_eii = {fld["fieldname"]: fld for fld in eii["fields"]}
        self.assertIn("base_amount", fields_eii)
        self.assertIn("gst_rate", fields_eii)
        self.assertIn("gst_amount", fields_eii)
        self.assertIn("upi_id", fields_eii)
        self.assertIn("attachments", fields_eii)
        self.assertIn("attachments_count", fields_eii)
        self.assertEqual(fields_eii["amount"]["label"], "Total Amount (Incl. GST)")
        self.assertIn("Direct Vendor Payment (UPI)", fields_eii["payment_mode"]["options"])
        self.assertIn("Petty Cash", fields_eii["payment_mode"]["options"])

        # 2. Event Master
        with open(f"{base_dir}/event_master/event_master.json") as f:
            em = json.load(f)
        fields_em = {fld["fieldname"]: fld for fld in em["fields"]}
        self.assertIn("allowed_departments", fields_em)
        self.assertEqual(fields_em["allowed_departments"]["fieldtype"], "Table MultiSelect")

        # 3. Event Advance Request
        with open(f"{base_dir}/event_advance_request/event_advance_request.json") as f:
            ear = json.load(f)
        fields_ear = {fld["fieldname"]: fld for fld in ear["fields"]}
        self.assertIn("allowed_departments", fields_ear)
        self.assertEqual(fields_ear["requested_advance_amount"]["label"], "Total Advance Amount (INR)")

        # 4. Event Expense Item (Registered Supplier hidden)
        with open(f"{base_dir}/event_expense_item/event_expense_item.json") as f:
            eei = json.load(f)
        fields_eei = {fld["fieldname"]: fld for fld in eei["fields"]}
        self.assertEqual(fields_eei["vendor"].get("hidden"), 1)
        self.assertEqual(fields_eei["vendor"].get("in_list_view"), 0)

        # 5. Event Expense Claim (Total Advance Disbursed label)
        with open(f"{base_dir}/event_expense_claim/event_expense_claim.json") as f:
            eec = json.load(f)
        fields_eec = {fld["fieldname"]: fld for fld in eec["fields"]}
        self.assertEqual(fields_eec["disbursed_advance"]["label"], "Total Advance Disbursed (INR)")


if __name__ == "__main__":
    unittest.main()
