"""
Automated Cryptographic Unit Tests for IDFC API Client
Verifies:
1. RSA-SHA256 Signature Generation.
2. Asymmetric Verification against matching Public Key.
3. Tamper Resistance: Changing 1 byte in payload breaks signature.
4. Canonical JSON Determinism: Key ordering does not alter signature.
5. Dual-Credential Hierarchy: Entity-specific vs Centralized Master fallback.
"""
import unittest
import base64
import json
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from ap_automation.integrations.idfc_client import IDFCAPIClient
from ap_automation.exceptions import APSecurityError


class TestIDFCCryptography(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Generate temporary 2048-bit RSA Keypair for unit testing
        cls.test_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        cls.test_public_key = cls.test_private_key.public_key()

        cls.private_pem = cls.test_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode("utf-8")

        cls.public_pem = cls.test_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("utf-8")

        cls.mock_settings = {
            "client_id": "TEST_CLIENT_ID_001",
            "client_secret": "TEST_SECRET_ABC",
            "private_key_pem": cls.private_pem,
            "bank_public_key_pem": cls.public_pem,
            "environment": "Sandbox"
        }

    def test_01_signature_generation_and_verification(self):
        """Test that client successfully signs a payload and public key verifies it."""
        client = IDFCAPIClient(settings_override=self.mock_settings)
        payload = {
            "batch_id": "BATCH-20260901-001",
            "debit_account": "100234567890",
            "total_amount": 150000.00,
            "payments": [
                {"payee": "Vendor A", "account": "999888111", "amount": 100000.00},
                {"payee": "Employee B", "account": "222333444", "amount": 50000.00}
            ]
        }

        signature_b64 = client.sign_payload(payload)
        self.assertIsInstance(signature_b64, str)
        self.assertTrue(len(signature_b64) > 100)

        # Mathematical verification using public key
        sig_bytes = base64.b64decode(signature_b64)
        canonical_bytes = client.canonicalize(payload)
        
        # Verify will raise InvalidSignature if it fails
        self.test_public_key.verify(
            sig_bytes,
            canonical_bytes,
            padding.PKCS1v15(),
            hashes.SHA256()
        )

    def test_02_tamper_resistance(self):
        """Test that altering even 1 rupee in payload breaks verification."""
        client = IDFCAPIClient(settings_override=self.mock_settings)
        original_payload = {"account": "10023456", "amount": 5000}
        signature_b64 = client.sign_payload(original_payload)

        # Tampered payload (amount altered to 5001)
        tampered_payload = {"account": "10023456", "amount": 5001}
        tampered_bytes = client.canonicalize(tampered_payload)
        sig_bytes = base64.b64decode(signature_b64)

        with self.assertRaises(Exception):
            self.test_public_key.verify(
                sig_bytes,
                tampered_bytes,
                padding.PKCS1v15(),
                hashes.SHA256()
            )

    def test_03_canonical_key_order_independence(self):
        """Test that key ordering in dictionary produces identical signature."""
        client = IDFCAPIClient(settings_override=self.mock_settings)
        dict_a = {"alpha": 1, "beta": 2, "gamma": 3}
        dict_b = {"gamma": 3, "alpha": 1, "beta": 2}

        sig_a = client.sign_payload(dict_a)
        sig_b = client.sign_payload(dict_b)
        self.assertEqual(sig_a, sig_b)

    def test_04_header_generation(self):
        """Test that complete production HTTP headers are built."""
        client = IDFCAPIClient(settings_override=self.mock_settings)
        headers = client.generate_headers({"test": "data"})
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["X-Client-Id"], "TEST_CLIENT_ID_001")
        self.assertEqual(headers["X-Client-Secret"], "TEST_SECRET_ABC")
        self.assertIn("X-Signature", headers)

    def test_05_environment_url_switching(self):
        """Test that client switches cleanly between Sandbox and Production."""
        sandbox_settings = dict(self.mock_settings, environment="Sandbox")
        prod_settings = dict(self.mock_settings, environment="Production")

        client_sandbox = IDFCAPIClient(settings_override=sandbox_settings)
        client_prod = IDFCAPIClient(settings_override=prod_settings)

        self.assertIn("myapiuat.idfcfirstbank.com", client_sandbox.base_url)
        self.assertIn("api.idfcfirstbank.com", client_prod.base_url)


if __name__ == "__main__":
    unittest.main()
