# =============================================================================
# Compliance Utilities - Protected Trait Detection
# =============================================================================

import re
from typing import Any

# -----------------------------------------------------------------------------
# Protected Traits - These must NEVER be used in scoring
# -----------------------------------------------------------------------------

# Based on US EEOC protected categories
PROTECTED_TRAITS = {
    # Race and ethnicity
    "race": ["race", "racial", "ethnicity", "ethnic", "color", "skin"],
    
    # Gender and sex
    "gender": [
        "gender", "sex", "male", "female", "man", "woman", "men", "women",
        "transgender", "trans", "non-binary", "nonbinary", "cisgender",
    ],
    
    # Age
    "age": ["age", "years old", "birth year", "born in", "date of birth", "dob"],
    
    # Religion
    "religion": [
        "religion", "religious", "faith", "christian", "muslim", "jewish",
        "hindu", "buddhist", "atheist", "agnostic", "catholic", "protestant",
    ],
    
    # National origin
    "national_origin": [
        "national origin", "nationality", "country of origin", "birthplace",
        "native language", "mother tongue", "immigration", "immigrant",
        "citizenship status",  # with some exceptions
    ],
    
    # Disability
    "disability": [
        "disability", "disabled", "handicap", "impairment", "medical condition",
        "mental health", "psychiatric", "wheelchair", "deaf", "blind",
    ],
    
    # Pregnancy
    "pregnancy": [
        "pregnant", "pregnancy", "maternity", "paternity", "parental leave",
        "expecting", "baby", "child care",
    ],
    
    # Sexual orientation
    "sexual_orientation": [
        "sexual orientation", "gay", "lesbian", "bisexual", "homosexual",
        "heterosexual", "straight", "lgbtq", "lgbt", "queer",
    ],
    
    # Marital/family status
    "marital_status": [
        "married", "single", "divorced", "widowed", "marital status",
        "spouse", "husband", "wife", "partner", "children", "kids",
        "family status",
    ],
    
    # Military status (protected in many jurisdictions)
    "military": [
        "veteran", "military service", "armed forces", "deployment",
        "national guard", "reserves",
    ],
    
    # Genetic information
    "genetic": [
        "genetic", "dna", "family medical history", "genetic test",
        "genetic information",
    ],
}

# Flatten all protected terms for quick checking
ALL_PROTECTED_TERMS = set()
for terms in PROTECTED_TRAITS.values():
    ALL_PROTECTED_TERMS.update(term.lower() for term in terms)


def validate_rubric(rubric: dict) -> list[str]:
    """
    Validate that a scoring rubric doesn't use protected traits.
    
    This should be run when loading a rubric to ensure compliance
    with anti-discrimination laws.
    
    Args:
        rubric: The scoring rubric dictionary
    
    Returns:
        List of compliance issues found (empty if compliant)
    """
    issues = []
    
    def check_value(value: Any, path: str) -> None:
        """Recursively check values for protected terms."""
        if isinstance(value, str):
            value_lower = value.lower()
            for trait_category, terms in PROTECTED_TRAITS.items():
                for term in terms:
                    if term.lower() in value_lower:
                        issues.append(
                            f"Protected trait '{term}' ({trait_category}) "
                            f"found in rubric at: {path}"
                        )
        elif isinstance(value, dict):
            for k, v in value.items():
                check_value(k, f"{path}.{k}")
                check_value(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                check_value(item, f"{path}[{i}]")
    
    check_value(rubric, "rubric")
    
    return issues


def audit_scoring_decision(
    resume_text: str,
    score_breakdown: dict,
    matched_terms: list[str],
) -> dict:
    """
    Audit a scoring decision for potential bias.
    
    Checks whether any protected traits might have influenced the score.
    This provides transparency and helps identify potential issues.
    
    Args:
        resume_text: The resume text that was scored
        score_breakdown: Dictionary of category scores
        matched_terms: Terms that matched in the resume
    
    Returns:
        Audit result with any warnings
    """
    result = {
        "compliant": True,
        "warnings": [],
        "protected_mentions": [],
    }
    
    # Check if any matched terms are protected
    for term in matched_terms:
        term_lower = term.lower()
        for trait_category, protected_terms in PROTECTED_TRAITS.items():
            for protected in protected_terms:
                if protected.lower() in term_lower:
                    result["warnings"].append(
                        f"Matched term '{term}' may relate to protected trait: "
                        f"{trait_category}"
                    )
                    result["compliant"] = False
    
    # Scan resume for protected trait mentions (for reporting only)
    resume_lower = resume_text.lower()
    for trait_category, terms in PROTECTED_TRAITS.items():
        for term in terms:
            if term.lower() in resume_lower:
                result["protected_mentions"].append({
                    "term": term,
                    "category": trait_category,
                })
    
    return result


def redact_protected_info(text: str) -> str:
    """
    Redact potential protected information from text for logging.
    
    This is used when logging or displaying information to prevent
    inadvertent exposure of protected traits.
    
    Args:
        text: Text to redact
    
    Returns:
        Text with protected information redacted
    """
    result = text
    
    # Create patterns for each protected term
    for trait_category, terms in PROTECTED_TRAITS.items():
        for term in terms:
            # Use word boundaries to avoid partial matches
            pattern = re.compile(
                rf"\b{re.escape(term)}\b",
                re.IGNORECASE,
            )
            result = pattern.sub(f"[REDACTED:{trait_category.upper()}]", result)
    
    return result
