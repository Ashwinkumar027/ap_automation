"""
IDFC Corporate Banking Enterprise API Client
Supports:
1. RSA-SHA256 Asymmetric Request Signing & Payload Canonicalization.
2. Response Digital Signature Verification using Bank Public Key.
3. Dual Credential Mode: Centralized Group Master API vs Company-Individual API Profiles.
4. Environment Switching: UAT/Sandbox vs Production.
"""
import base64
import json
from typing import Dict, Any, Optional, Tuple
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
import frappe
from ap_automation.exceptions import APConfigurationError, APSecurityError, APBankAPIError


class IDFCAPIClient:
    """
    Production cryptographic client for IDFC FIRST Corporate Banking.
    Thread-safe, stateless, and optimized for background execution.
    """

    UAT_BASE_URL = "https://myapiuat.idfcfirstbank.com/corporate"
    PROD_BASE_URL = "https://api.idfcfirstbank.com/corporate"

    def __init__(self, company: Optional[str] = None, settings_override: Optional[Dict[str, Any]] = None):
        """
        Initialize client.
        :param company: Optional company name. If provided, checks for company-specific
                        credentials in IDFC Bank Settings; falls back to Group Master.
        :param settings_override: Optional dict to inject keys directly (for unit testing).
        """
        self.company = company
        self.settings = settings_override or self._load_credentials(company)
        
        self.client_id: str = self.settings.get("client_id")
        self.client_secret: Optional[str] = self.settings.get("client_secret")
        self.environment: str = self.settings.get("environment", "Sandbox")
        
        # Load Private Key for Request Signing
        raw_private_key = self.settings.get("private_key_pem")
        if not raw_private_key:
            raise APConfigurationError(f"Missing private key for IDFC API (Company: {company or 'Group Master'})")
        
        try:
            self.private_key = load_pem_private_key(
                raw_private_key.strip().encode("utf-8") if isinstance(raw_private_key, str) else raw_private_key,
                password=None
            )
        except Exception as e:
            raise APSecurityError(f"Failed to load RSA Private Key: {str(e)}")

        # Load Bank Public Key for Response Verification (Optional in test, mandatory in prod)
        raw_bank_public_key = self.settings.get("bank_public_key_pem")
        self.bank_public_key = None
        if raw_bank_public_key:
            try:
                self.bank_public_key = load_pem_public_key(
                    raw_bank_public_key.strip().encode("utf-8") if isinstance(raw_bank_public_key, str) else raw_bank_public_key
                )
            except Exception as e:
                frappe.logger("ap_automation").warning(f"Could not load Bank Public Key: {str(e)}")

    def _load_credentials(self, company: Optional[str]) -> Dict[str, Any]:
        """
        Loads credentials from IDFC Bank Settings.
        Implements Hierarchical Resolution: Company Override -> Group Master.
        """
        try:
            settings_doc = frappe.get_single("AP IDFC Settings")
        except Exception:
            try:
                settings_doc = frappe.get_single("IDFC Bank Settings")
            except Exception as e:
                raise APConfigurationError(f"Cannot load IDFC Settings: {str(e)}")

        # Resolve Master Credentials
        resolved_client_id = settings_doc.get("client_id")
        resolved_client_secret = settings_doc.get_password("client_secret") if hasattr(settings_doc, "get_password") else settings_doc.get("client_secret")
        resolved_private_key = settings_doc.get_password("private_key") if hasattr(settings_doc, "get_password") and settings_doc.get_password("private_key") else settings_doc.get("private_key")

        # Check Child Table for Company Overrides
        if company and hasattr(settings_doc, "company_credentials"):
            for row in settings_doc.company_credentials:
                if row.company == company and (row.is_active or str(row.is_active) == "1"):
                    # Check if company opted to use individual credentials
                    if getattr(row, "use_individual_credentials", 0):
                        if row.client_id:
                            resolved_client_id = row.client_id
                        
                        # Decrypt child table password fields cleanly
                        try:
                            dec_secret = row.get_password("client_secret")
                            if dec_secret:
                                resolved_client_secret = dec_secret
                        except Exception:
                            if row.client_secret and not row.client_secret.startswith("*"):
                                resolved_client_secret = row.client_secret

                        try:
                            dec_priv = row.get_password("private_key")
                            if dec_priv:
                                resolved_private_key = dec_priv
                        except Exception:
                            if row.private_key and not row.private_key.startswith("*"):
                                resolved_private_key = row.private_key
                    break

        return {
            "client_id": resolved_client_id,
            "client_secret": resolved_client_secret,
            "private_key_pem": resolved_private_key,
            "bank_public_key_pem": settings_doc.get("bank_public_key"),
            "environment": settings_doc.get("environment", "Sandbox")
        }

    @property
    def base_url(self) -> str:
        """Returns target gateway URL based on environment."""
        if self.environment == "Production":
            return self.PROD_BASE_URL
        return self.UAT_BASE_URL

    @staticmethod
    def canonicalize(payload: Dict[str, Any]) -> bytes:
        """Deterministically serializes payload with sorted keys."""
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def sign_payload(self, payload: Dict[str, Any]) -> str:
        """Generates RSA-SHA256 digital signature of canonicalized payload."""
        try:
            canonical_bytes = self.canonicalize(payload)
            signature = self.private_key.sign(
                canonical_bytes,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return base64.b64encode(signature).decode("utf-8")
        except Exception as e:
            raise APSecurityError(f"Error during cryptographic signing: {str(e)}")

    def verify_response_signature(self, response_body: str, signature_b64: str) -> bool:
        """Verifies that a bank response was authentically signed by IDFC Bank."""
        if not self.bank_public_key:
            if self.environment != "Production":
                return True
            raise APSecurityError("Bank public key is missing; cannot verify bank response authenticity.")

        try:
            signature = base64.b64decode(signature_b64)
            data_bytes = response_body.encode("utf-8") if isinstance(response_body, str) else response_body
            self.bank_public_key.verify(
                signature,
                data_bytes,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return True
        except Exception:
            return False

    def generate_headers(self, payload: Dict[str, Any], extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Builds complete, production-ready HTTP request headers."""
        signature = self.sign_payload(payload)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Client-Id": self.client_id,
            "X-Signature": signature,
        }
        if self.client_secret:
            headers["X-Client-Secret"] = self.client_secret
        if extra_headers:
            headers.update(extra_headers)
        return headers
