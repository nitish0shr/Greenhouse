"""Security utilities: HMAC verification, PII redaction, and helpers."""

import hashlib
import hmac
import re
import secrets
from typing import Any


def verify_hmac_signature(
    payload: bytes,
    signature: str,
    secret: str,
    algorithm: str = "sha256",
) -> bool:
    """
    Verify HMAC signature for webhook payloads.

    Greenhouse uses: Signature = HMAC-SHA256(secret, raw_body)
    The signature header format is: "Signature: sha256=<hex_digest>"

    Args:
        payload: Raw request body bytes
        signature: The signature from the header (may include algorithm prefix)
        secret: The webhook secret key
        algorithm: Hash algorithm (default sha256)

    Returns:
        True if signature is valid, False otherwise
    """
    if not payload or not signature or not secret:
        return False

    # Handle signature format with algorithm prefix
    if "=" in signature:
        parts = signature.split("=", 1)
        if len(parts) == 2:
            sig_algo, sig_value = parts
            # Verify algorithm matches
            if sig_algo.lower() != algorithm:
                return False
            signature = sig_value

    # Compute expected signature
    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        getattr(hashlib, algorithm),
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected.lower(), signature.lower())


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for request tracing."""
    return secrets.token_hex(16)


# Patterns for PII detection
PII_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
}

# Fields that should be redacted in logs
SENSITIVE_FIELDS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "ssn",
    "social_security",
    "credit_card",
    "card_number",
    "cvv",
    "pin",
}

# Protected traits that must never be used for scoring (EEOC compliance)
PROTECTED_TRAITS = {
    "race",
    "color",
    "religion",
    "sex",
    "gender",
    "national_origin",
    "nationality",
    "age",
    "disability",
    "genetic_information",
    "pregnancy",
    "veteran_status",
    "marital_status",
    "sexual_orientation",
}


def redact_pii(text: str, replacement: str = "[REDACTED]") -> str:
    """
    Redact personally identifiable information from text.

    Args:
        text: The text to redact
        replacement: The replacement string for PII

    Returns:
        Text with PII replaced
    """
    result = text
    for pattern_name, pattern in PII_PATTERNS.items():
        result = pattern.sub(replacement, result)
    return result


def redact_sensitive_dict(
    data: dict[str, Any],
    replacement: str = "[REDACTED]",
) -> dict[str, Any]:
    """
    Recursively redact sensitive fields from a dictionary.

    Used for logging payloads safely.
    """
    result = {}
    for key, value in data.items():
        key_lower = key.lower()

        # Check if key contains sensitive terms
        if any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS):
            result[key] = replacement
        elif isinstance(value, dict):
            result[key] = redact_sensitive_dict(value, replacement)
        elif isinstance(value, list):
            result[key] = [
                redact_sensitive_dict(item, replacement) if isinstance(item, dict) else item
                for item in value
            ]
        elif isinstance(value, str):
            result[key] = redact_pii(value, replacement)
        else:
            result[key] = value

    return result


def sanitize_resume_content(content: str) -> str:
    """
    Sanitize resume content to prevent prompt injection.

    Removes potential instruction-like patterns that could be used
    to manipulate LLM-based processing.

    Args:
        content: Raw resume text content

    Returns:
        Sanitized content safe for processing
    """
    # Remove common prompt injection patterns
    dangerous_patterns = [
        r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
        r"(?i)disregard\s+(all\s+)?(previous|prior|above)\s+instructions?",
        r"(?i)forget\s+(all\s+)?(previous|prior|above)\s+instructions?",
        r"(?i)you\s+are\s+now\s+(?:a|an)\s+",
        r"(?i)system\s*:\s*",
        r"(?i)assistant\s*:\s*",
        r"(?i)\[INST\]",
        r"(?i)<<SYS>>",
        r"(?i)</s>",
        r"(?i)<\|im_start\|>",
        r"(?i)<\|im_end\|>",
    ]

    result = content
    for pattern in dangerous_patterns:
        result = re.sub(pattern, "[FILTERED]", result)

    return result


def check_protected_traits_in_scoring(scoring_criteria: dict[str, Any]) -> list[str]:
    """
    Check if scoring criteria contain protected trait references.

    Returns a list of violations if any protected traits are found.
    """
    violations = []

    def check_dict(d: dict[str, Any], path: str = "") -> None:
        for key, value in d.items():
            current_path = f"{path}.{key}" if path else key
            key_lower = key.lower()

            # Check if key matches protected trait
            if key_lower in PROTECTED_TRAITS:
                violations.append(f"Protected trait '{key}' found at {current_path}")

            # Check string values for protected trait mentions
            if isinstance(value, str):
                value_lower = value.lower()
                for trait in PROTECTED_TRAITS:
                    if trait in value_lower:
                        violations.append(
                            f"Protected trait '{trait}' mentioned in value at {current_path}"
                        )

            # Recurse into nested dicts
            elif isinstance(value, dict):
                check_dict(value, current_path)

            # Check list items
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        check_dict(item, f"{current_path}[{i}]")
                    elif isinstance(item, str):
                        item_lower = item.lower()
                        for trait in PROTECTED_TRAITS:
                            if trait in item_lower:
                                violations.append(
                                    f"Protected trait '{trait}' mentioned at {current_path}[{i}]"
                                )

    check_dict(scoring_criteria)
    return violations
