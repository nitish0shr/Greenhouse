# =============================================================================
# Security Utilities - HMAC Verification & Input Sanitization
# =============================================================================

import hashlib
import hmac
import re
from typing import Optional

from app.config import settings


def verify_greenhouse_signature(
    payload: bytes,
    signature: str,
    secret: Optional[str] = None,
) -> bool:
    """
    Verify Greenhouse webhook signature using HMAC-SHA256.
    
    Greenhouse sends a Signature header in the format:
    sha256=<hex_digest>
    
    We need to compute HMAC-SHA256(secret, payload) and compare.
    
    Args:
        payload: Raw request body bytes
        signature: Value of the Signature header
        secret: Webhook secret (defaults to config value)
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not signature:
        return False
    
    secret = secret or settings.greenhouse_webhook_secret
    if not secret:
        return False
    
    # Parse signature format: "sha256 <hex_digest>" (space, not equals) per First Review
    # Handle both formats for compatibility: "sha256 <digest>" or "sha256=<digest>"
    if signature.startswith("sha256 "):
        provided_digest = signature[7:]  # Remove "sha256 " prefix
    elif signature.startswith("sha256="):
        provided_digest = signature[7:]  # Remove "sha256=" prefix (legacy format)
    else:
        provided_digest = signature  # Assume just the digest
    
    # Compute expected digest
    expected_digest = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    
    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected_digest, provided_digest)


def verify_graph_notification_token(
    token: str,
    expected_value: str,
) -> bool:
    """
    Verify Microsoft Graph change notification validation token.
    
    When setting up subscriptions, Graph sends a validation request
    with a validationToken query parameter that must be echoed back.
    
    Args:
        token: The validationToken from the request
        expected_value: What we expect (from our subscription setup)
    
    Returns:
        True if token matches, False otherwise
    """
    return hmac.compare_digest(token, expected_value)


# -----------------------------------------------------------------------------
# Input Sanitization for Resume Content
# -----------------------------------------------------------------------------

# Patterns that might indicate prompt injection attempts
SUSPICIOUS_PATTERNS = [
    # Common LLM injection patterns
    r"ignore\s+(previous|above|all)\s+instructions?",
    r"disregard\s+(previous|above|all)",
    r"forget\s+(everything|previous|above)",
    r"new\s+instructions?:",
    r"system\s*:\s*",
    r"assistant\s*:\s*",
    r"human\s*:\s*",
    r"user\s*:\s*",
    # Jailbreak attempts
    r"do\s+anything\s+now",
    r"pretend\s+you\s+are",
    r"act\s+as\s+if",
    r"roleplay\s+as",
    # Code execution attempts
    r"```\s*python",
    r"```\s*javascript",
    r"exec\s*\(",
    r"eval\s*\(",
    r"import\s+os",
    r"subprocess",
]

# Compile patterns for efficiency
SUSPICIOUS_REGEX = re.compile(
    "|".join(SUSPICIOUS_PATTERNS),
    re.IGNORECASE,
)


def sanitize_resume_text(text: str) -> str:
    """
    Sanitize resume text to prevent prompt injection.
    
    This function:
    1. Removes null bytes and control characters
    2. Normalizes whitespace
    3. Does NOT remove suspicious patterns - we flag but preserve content
    
    We preserve the original content for accurate scoring, but this
    function prepares the text for safe use.
    
    Args:
        text: Raw resume text
    
    Returns:
        Sanitized text
    """
    if not text:
        return ""
    
    # Remove null bytes
    text = text.replace("\x00", "")
    
    # Remove other control characters (except newlines and tabs)
    text = "".join(
        char for char in text
        if char == "\n" or char == "\t" or (ord(char) >= 32)
    )
    
    # Normalize multiple spaces to single space
    text = re.sub(r"[ \t]+", " ", text)
    
    # Normalize multiple newlines to double newline
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    # Strip leading/trailing whitespace
    text = text.strip()
    
    return text


def detect_injection_attempts(text: str) -> list[str]:
    """
    Detect potential prompt injection attempts in text.
    
    This is used for flagging suspicious content, not blocking.
    
    Args:
        text: Text to analyze
    
    Returns:
        List of detected suspicious patterns
    """
    if not text:
        return []
    
    matches = SUSPICIOUS_REGEX.findall(text.lower())
    return list(set(matches))


def is_safe_filename(filename: str) -> bool:
    """
    Check if a filename is safe to use.
    
    Prevents path traversal and other file-based attacks.
    
    Args:
        filename: Filename to check
    
    Returns:
        True if safe, False otherwise
    """
    if not filename:
        return False
    
    # Remove path components
    filename = filename.replace("\\", "/")
    base_name = filename.split("/")[-1]
    
    # Check for path traversal
    if ".." in base_name:
        return False
    
    # Check for null bytes
    if "\x00" in base_name:
        return False
    
    # Check for hidden files
    if base_name.startswith("."):
        return False
    
    return True
