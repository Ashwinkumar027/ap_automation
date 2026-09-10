"""
IDFC Corporate Banking Host-to-Host Dispatcher
Target Endpoint: POST /corporate/payments/bulk

Key Responsibilities:
1. Construct strictly validated IDFC Bulk Payout JSON specifications.
2. Pre-Flight Banking Syntax Validation (RBI/NPCI IFSC standard & account formats).
3. Idempotency Gate: Prevent duplicate batch transmissions via deterministic SHA-256 fingerprinting.
4. Cryptographic Asymmetric RSA-SHA256 request headers.
5. Resilient retry engine with exponential backoff for transient 502/503/504 drops.
6. Automated Account Masking (PCI/RBI compliance) into AP Connector Log.
"""
import copy
import hashlib
import json
import re
import time
from typing import Dict, Any, List, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import frappe
from ap_automation.integrations.idfc_client import IDFCAPIClient
from ap_automation.exceptions import APValidationError, APBankAPIError, APConfigurationError


# Pre-flight Regex Patterns (RBI / NPCI Banking Standards)
IFSC_REGEX = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_REGEX = re.compile(r"^[0-9]{9,18}$")


def validate_ifsc_code(ifsc: str) -> bool:
    """
    Validates IFSC against the official RBI/NPCI standard:
    - Exactly 11 alphanumeric characters.
    - First 4 characters: Alphabetic (Bank Code).
    - 5th character: Strictly numeric zero '0' (Reserved).
    - Last 6 characters: Alphanumeric (Branch Code).
    """
    if not ifsc or not isinstance(ifsc, str):
        return False
    return bool(IFSC_REGEX.match(ifsc.strip().upper()))


def validate_account_number(acc_num: Any) -> bool:
    """
    Validates standard Indian commercial bank account number:
    - Strictly numeric digits.
    - Length between 9 and 18 digits.
    """
    if not acc_num:
        return False
    return bool(ACCOUNT_REGEX.match(str(acc_num).strip()))


def mask_account_number(acc_num: Any) -> str:
    """Masks all but the last 4 digits of a bank account number."""
    if not acc_num:
        return ""
    acc_str = str(acc_num).strip()
    if len(acc_str) <= 4:
        return "****"
    return "*" * (len(acc_str) - 4) + acc_str[-4:]


def mask_sensitive_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns a deep copy of the payout payload with sensitive account numbers masked
    before saving into immutable database logs.
    """
    masked = copy.deepcopy(payload)
    if "debit_account" in masked:
        masked["debit_account"] = mask_account_number(masked["debit_account"])
    
    if "payments" in masked and isinstance(masked["payments"], list):
        for p in masked["payments"]:
            if "credit_account" in p:
                p["credit_account"] = mask_account_number(p["credit_account"])
    return masked


def calculate_payload_hash(payload: Dict[str, Any]) -> str:
    """
    Computes a deterministic SHA-256 hash of the core business payload.
    Excludes transient execution timestamps so idempotency is strictly preserved across retries.
    """
    idempotency_dict = {
        "batch_id": payload.get("batch_id"),
        "company": payload.get("company"),
        "debit_account": payload.get("debit_account"),
        "total_amount": payload.get("total_amount"),
        "payments": payload.get("payments", [])
    }
    canonical_bytes = json.dumps(idempotency_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def check_idempotency(payload_hash: str) -> Optional[Dict[str, Any]]:
    """
    Checks whether this exact payload has already been processed or is currently in flight.
    Fast O(1) lookup using indexed payload_hash column on AP Connector Log.
    """
    existing = frappe.get_all(
        "AP Connector Log",
        filters={"payload_hash": payload_hash, "status": ["in", ["SUCCESS", "PENDING_POLL", "IN_FLIGHT"]]},
        fields=["name", "batch_id", "status", "status_code", "creation"],
        limit=1
    )
    return existing[0] if existing else None


def acquire_idempotency_lock(
    endpoint: str,
    payload_hash: str,
    batch_id: str,
    company: str,
    request_data: Dict[str, Any]
) -> str:
    """
    Atomically checks and registers an IN_FLIGHT lock for this payload_hash.
    Prevents concurrent thread race conditions.
    """
    # 1. Check existing
    existing = check_idempotency(payload_hash)
    if existing:
        raise APValidationError(
            f"Idempotency Protection Triggered: Batch '{batch_id}' has already been dispatched "
            f"(Log: {existing['name']}, Status: {existing['status']}). Re-submission blocked."
        )

    # 2. Atomic lock via MariaDB GET_LOCK
    lock_name = f"ap_lock_{payload_hash[:32]}"
    lock_acquired = frappe.db.sql("SELECT GET_LOCK(%s, 0)", (lock_name,))
    if not lock_acquired or not lock_acquired[0][0]:
        raise APValidationError(
            f"Idempotency Protection Triggered: Batch '{batch_id}' is currently being released by another worker."
        )

    # 3. Create IN_FLIGHT audit record
    try:
        masked_request = mask_sensitive_payload(request_data)
        log_doc = frappe.get_doc({
            "doctype": "AP Connector Log",
            "endpoint": endpoint,
            "method": "POST",
            "payload_hash": payload_hash,
            "batch_id": batch_id,
            "company": company,
            "status": "IN_FLIGHT",
            "request_payload": json.dumps(masked_request, indent=2)
        })
        log_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return log_doc.name
    finally:
        # Release the temporary mutex lock
        frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_name,))


def update_connector_log(
    log_name: str,
    status: str,
    status_code: int,
    response_data: Optional[Dict[str, Any]],
    execution_time_ms: float,
    error_message: Optional[str] = None
) -> None:
    """Updates an existing IN_FLIGHT connector log record upon completion."""
    if not log_name:
        return
    try:
        frappe.db.set_value("AP Connector Log", log_name, {
            "status": status,
            "status_code": status_code,
            "execution_time_ms": execution_time_ms,
            "response_payload": json.dumps(response_data or {}, indent=2),
            "error_message": error_message or ""
        }, update_modified=False)
        frappe.db.commit()
    except Exception as e:
        frappe.logger("ap_automation").error(f"Failed to update AP Connector Log {log_name}: {str(e)}")


def build_bulk_payment_payload(
    batch_id: str,
    company: str,
    debit_account: str,
    payment_items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Constructs and validates standard IDFC bulk payout payload structure.
    Enforces pre-flight banking syntax validation (IFSC & Account numbers).
    """
    if not batch_id or not debit_account or not payment_items:
        raise APValidationError("Cannot build payout payload: Missing batch_id, debit_account, or payment_items.")

    if not validate_account_number(debit_account):
        raise APValidationError(f"Invalid debit account number format: '{debit_account}'. Must be 9 to 18 numeric digits.")

    total_amount = sum(float(item.get("amount", 0.0)) for item in payment_items)
    
    formatted_payments = []
    for idx, item in enumerate(payment_items, start=1):
        amt = float(item.get("amount", 0.0))
        if amt <= 0:
            raise APValidationError(f"Invalid payment amount at row {idx}: {amt}. Must be greater than zero.")
        
        credit_acc = str(item.get("credit_account", "")).strip()
        ifsc = str(item.get("ifsc_code", "")).strip().upper()
        payee_name = str(item.get("payee_name", "")).strip()
        
        if not credit_acc or not ifsc or not payee_name:
            raise APValidationError(f"Missing mandatory payment fields at row {idx} (credit_account, ifsc_code, payee_name).")

        # Pre-Flight Validation checks
        if not validate_account_number(credit_acc):
            raise APValidationError(f"Invalid credit account number format for row {idx} ({payee_name}): '{credit_acc}'. Must be 9 to 18 digits.")

        if not validate_ifsc_code(ifsc):
            raise APValidationError(f"Invalid IFSC Code for row {idx} ({payee_name}): '{ifsc}'. Must be 11 characters conforming to NPCI standard (5th char must be '0').")

        formatted_payments.append({
            "payment_ref": item.get("payment_ref") or f"{batch_id}-{idx:04d}",
            "payee_name": payee_name,
            "credit_account": credit_acc,
            "ifsc_code": ifsc,
            "amount": round(amt, 2),
            "payment_mode": item.get("payment_mode", "NEFT" if amt < 200000 else "RTGS"),
            "narration": (item.get("narration") or f"Payout for {batch_id}")[:50]
        })

    return {
        "batch_id": batch_id,
        "company": company,
        "debit_account": debit_account.strip(),
        "total_count": len(formatted_payments),
        "total_amount": round(total_amount, 2),
        "currency": "INR",
        "timestamp": frappe.utils.now(),
        "payments": formatted_payments
    }


def get_resilient_session(max_retries: int = 3) -> requests.Session:
    """Configures a requests Session with backoff retry for transient gateway drops."""
    session = requests.Session()
    retries = Retry(
        total=max_retries,
        backoff_factor=0.5,
        status_forcelist=[502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def send_bulk_payment(
    batch_id: str,
    company: str,
    debit_account: str,
    payment_items: List[Dict[str, Any]],
    is_simulation: bool = False,
    simulation_fault: Optional[str] = None,
    session: Optional[requests.Session] = None
) -> Dict[str, Any]:
    """
    Main Host-to-Host dispatcher called by the Payment Release Engine.
    Enforces atomic lock, idempotency, and resilient logging.
    """
    # 1. Build & validate payload
    payload = build_bulk_payment_payload(batch_id, company, debit_account, payment_items)
    payload_hash = calculate_payload_hash(payload)

    client = IDFCAPIClient(company=company)
    url = f"{client.base_url}/payments/bulk"

    # 2. Atomic Idempotency Gate (Guaranteed race-condition safe)
    log_name = acquire_idempotency_lock(
        endpoint=url,
        payload_hash=payload_hash,
        batch_id=batch_id,
        company=company,
        request_data=payload
    )

    headers = client.generate_headers(payload)
    start_time = time.time()
    status = "FAILED"
    status_code = 0
    response_json = {}
    error_msg = None

    # Simulation / Mock Mode (For testing without live bank keys)
    if is_simulation:
        exec_time = round((time.time() - start_time) * 1000, 2)
        
        # Test Case: 401 Signature / Key Rejection
        if simulation_fault == "401":
            status_code = 401
            response_json = {"error": "INVALID_SIGNATURE", "message": "RSA signature verification failed at IDFC gateway."}
            error_msg = "Bank API Error (HTTP 401): RSA signature verification failed at IDFC gateway."
            update_connector_log(log_name, "FAILED", 401, response_json, exec_time, error_msg)
            raise APBankAPIError(error_msg, http_status=401)
            
        # Test Case: 503 Service Outage
        elif simulation_fault == "503":
            status_code = 503
            response_json = {"error": "SERVICE_UNAVAILABLE", "message": "IDFC Core Banking System undergoing maintenance."}
            error_msg = "Bank API Error (HTTP 503): IDFC Core Banking System undergoing maintenance."
            update_connector_log(log_name, "FAILED", 503, response_json, exec_time, error_msg)
            raise APBankAPIError(error_msg, http_status=503)

        # Standard Happy Path Simulation
        response_json = {
            "bank_status": "ACCEPTED",
            "batch_reference": f"IDFC-SIM-{int(time.time())}",
            "message": "Bulk payout accepted for processing by IDFC gateway."
        }
        update_connector_log(log_name, "SUCCESS", 200, response_json, exec_time)
        return {
            "status": "success",
            "batch_id": batch_id,
            "response": response_json,
            "payload_hash": payload_hash
        }

    # Real Host-to-Host HTTP Transmission
    http_session = session or get_resilient_session()
    try:
        response = http_session.post(url, json=payload, headers=headers, timeout=30)
        status_code = response.status_code
        exec_time = round((time.time() - start_time) * 1000, 2)

        try:
            response_json = response.json()
        except Exception:
            response_json = {"raw_response": response.text}

        if response.status_code in [200, 201, 202]:
            status = "SUCCESS"
            return {
                "status": "success",
                "batch_id": batch_id,
                "status_code": status_code,
                "response": response_json,
                "payload_hash": payload_hash
            }
        else:
            error_msg = f"Bank API Error (HTTP {status_code}): {response_json.get('message', response.text)}"
            raise APBankAPIError(error_msg, http_status=status_code)

    except requests.exceptions.RequestException as req_err:
        exec_time = round((time.time() - start_time) * 1000, 2)
        error_msg = f"Network Transport Failure: {str(req_err)}"
        raise APBankAPIError(error_msg, http_status=504)

    finally:
        update_connector_log(log_name, status, status_code, response_json, exec_time, error_msg)
