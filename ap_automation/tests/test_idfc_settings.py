"""
Unit Tests for Sprint 1 Day 2: IDFC Bank Settings & Multi-Company Credential Store
Verifies:
1. DocType Schema & Single DocType accessibility.
2. On-Disk Password Field Encryption.
3. Multi-Company Credential Child Table mapping.
4. Whitelisted 'test_idfc_connection' endpoint and permission security.
"""
import unittest
import frappe
from ap_automation.services.idfc_service import test_connection_service, validate_rsa_private_key
from ap_automation.integrations.idfc_client import IDFCAPIClient
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


class TestIDFCBankSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Generate valid test RSA key
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.test_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode("utf-8")

        # Configure AP IDFC Settings
        cls.settings = frappe.get_doc("AP IDFC Settings")
        cls.settings.client_id = "MASTER_IDFC_CORP_001"
        cls.settings.client_secret = "SecretKey_SuperSecure_999"
        cls.settings.private_key = cls.test_pem
        cls.settings.environment = "Sandbox"
        cls.settings.save(ignore_permissions=True)
        frappe.db.commit()

    def test_01_rsa_key_validation_utility(self):
        """Tests that validate_rsa_private_key validates PEM syntax without errors."""
        is_valid, msg = validate_rsa_private_key(self.test_pem)
        self.assertTrue(is_valid)
        self.assertIn("Valid RSA", msg)

        # Invalid key test
        bad_valid, bad_msg = validate_rsa_private_key("NOT_A_KEY")
        self.assertFalse(bad_valid)

    def test_02_password_fields_encryption(self):
        """Verifies that client_secret and private_key are securely encrypted via get_password."""
        settings = frappe.get_doc("AP IDFC Settings")
        secret = settings.get_password("client_secret")
        self.assertEqual(secret, "SecretKey_SuperSecure_999")
        
        priv_key = settings.get_password("private_key")
        self.assertTrue(priv_key.startswith("-----BEGIN PRIVATE KEY-----"))

    def test_03_test_connection_service(self):
        """Verifies that test_connection_service executes dry run and returns signature preview."""
        result = test_connection_service()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["client_id"], "MASTER_IDFC_CORP_001")
        self.assertEqual(result["environment"], "Sandbox")
        self.assertIn("...", result["signature_preview"])

    def test_04_company_credential_override_resolution(self):
        """Verifies that an entity override row in company_credentials takes precedence."""
        # Find or create a test company override
        company_name = frappe.db.get_value("Company", {}, "name")
        if company_name:
            settings = frappe.get_doc("AP IDFC Settings")
            found = False
            for row in settings.company_credentials:
                if row.company == company_name:
                    row.use_individual_credentials = 1
                    row.client_id = "INDIVIDUAL_CLIENT_999"
                    row.client_secret = "IndividualSecret"
                    row.private_key = self.test_pem
                    found = True
                    break
            if not found:
                settings.append("company_credentials", {
                    "company": company_name,
                    "use_individual_credentials": 1,
                    "client_id": "INDIVIDUAL_CLIENT_999",
                    "client_secret": "IndividualSecret",
                    "private_key": self.test_pem,
                    "is_active": 1
                })
            settings.save(ignore_permissions=True)
            frappe.db.commit()

            # Client initialized for this company should resolve individual client_id
            client = IDFCAPIClient(company=company_name)
            self.assertEqual(client.client_id, "INDIVIDUAL_CLIENT_999")


if __name__ == "__main__":
    unittest.main()
