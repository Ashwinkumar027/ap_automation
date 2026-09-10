"""
IDFC Corporate Banking API Client Wrapper
Maintains backward compatibility while exposing the enterprise IDFCAPIClient.
"""
from ap_automation.integrations.idfc_client import IDFCAPIClient
from ap_automation.exceptions import APConfigurationError, APSecurityError, APBankAPIError

__all__ = ["IDFCAPIClient", "APConfigurationError", "APSecurityError", "APBankAPIError"]
