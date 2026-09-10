"""
AP Automation Enterprise Exception Hierarchy
Standardized error handling across domain, integration, and security layers.
"""
import frappe

class APBaseException(frappe.ValidationError):
    """Base exception for all AP Automation errors."""
    default_message = "An unexpected error occurred in the AP Automation system."

    def __init__(self, message: str = None, error_code: str = None, http_status: int = 400):
        self.message = message or self.default_message
        self.error_code = error_code or "AP_GENERAL_ERROR"
        self.http_status = http_status
        super().__init__(self.message)


class APConfigurationError(APBaseException):
    """Raised when required system, banking, or entity settings are missing or invalid."""
    default_message = "AP Configuration Error: Required settings are missing."


class APSecurityError(APBaseException):
    """Raised when cryptographic operations, signature verification, or tamper checks fail."""
    default_message = "Security Alert: Cryptographic validation failed."


class APPermissionError(APBaseException):
    """Raised when a user lacks required role or document permissions."""
    default_message = "Permission Denied: You do not have permission to access this AP document."


class APValidationError(APBaseException):
    """Raised when business domain validation (duplicate check, amount mismatch) fails."""
    default_message = "Validation Error: Document failed AP business validation rules."


class APBankAPIError(APBaseException):
    """Raised when external banking gateway rejects a payload or returns a non-200 response."""
    default_message = "IDFC Bank Gateway communication failure."
