"""
IDFC Banking Gateway Service
Stateless business service for validating credentials, testing connections,
and handling cryptographic key lifecycle without exposing secrets.
"""
from typing import Dict, Any, Optional, Tuple
import frappe
from ap_automation.integrations.idfc_client import IDFCAPIClient
from ap_automation.exceptions import APConfigurationError, APSecurityError


def validate_rsa_private_key(private_key_pem: str) -> Tuple[bool, str]:
    """
    Validates that a PEM string contains a valid, loadable RSA private key.
    Does not log or store the key.
    """
    if not private_key_pem or not private_key_pem.strip():
        return False, "Private key is empty."
    
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key_bytes = private_key_pem.strip().encode("utf-8") if isinstance(private_key_pem, str) else private_key_pem
        load_pem_private_key(key_bytes, password=None)
        return True, "Valid RSA Private Key (PEM format confirmed)."
    except Exception as e:
        return False, f"Invalid RSA Key: {str(e)}"


def test_connection_service(company: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes a dry-run cryptographic signing test against current settings.
    Verifies that credentials resolve, the private key signs, and canonicalization works.
    """
    client = IDFCAPIClient(company=company)
    
    sample_payload = {
        "action": "PING_HEALTH_CHECK",
        "company": company or "Group Master Profile",
        "timestamp": frappe.utils.now(),
        "test_uuid": frappe.generate_hash(length=12)
    }
    
    signature = client.sign_payload(sample_payload)
    headers = client.generate_headers(sample_payload)
    
    return {
        "status": "success",
        "company": company or "Group Master",
        "environment": client.environment,
        "base_url": client.base_url,
        "client_id": client.client_id,
        "has_client_secret": bool(client.client_secret),
        "signature_algorithm": "SHA256withRSA (PKCS#1 v1.5)",
        "signature_preview": f"{signature[:24]}...{signature[-12:]}",
        "message": f"Cryptographic keys validated successfully for {company or 'Group Master'}! Client is ready for IDFC API communication."
    }


@frappe.whitelist()
def test_idfc_connection(company: Optional[str] = None) -> Dict[str, Any]:
    """
    Whitelisted endpoint called from Frappe Desk 'Test Cryptographic Keys' button.
    Enforces strict role permissions.
    """
    # Security: Only System Manager or Accounts Manager may test bank credentials
    user_roles = frappe.get_roles(frappe.session.user)
    authorized_roles = {"System Manager", "Accounts Manager", "Administrator"}
    if not authorized_roles.intersection(set(user_roles)):
        frappe.throw("Access Denied: Only Accounts Managers or System Managers can test banking credentials.", frappe.PermissionError)
    
    try:
        return test_connection_service(company=company)
    except Exception as e:
        frappe.logger("ap_automation").error(f"IDFC Test Connection Failed: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }
