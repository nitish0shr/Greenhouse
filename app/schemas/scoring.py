# =============================================================================
# Scoring Output Schema - Strict JSON Validation
# =============================================================================

from typing import Literal
from pydantic import BaseModel, Field, field_validator


class EvidenceSnippet(BaseModel):
    """Evidence snippet with source."""
    snippet: str = Field(..., description="Text snippet as evidence")
    source: str = Field(..., description="Source of evidence (e.g., 'resume', 'application')")


class DimensionScore(BaseModel):
    """Score for a single dimension."""
    score: int = Field(..., ge=0, le=100, description="Score from 0-100")
    evidence: list[EvidenceSnippet] = Field(default_factory=list, description="Evidence snippets")


class ScoringOutput(BaseModel):
    """
    Strict JSON schema for scoring engine output.
    
    Per First Review requirements, this schema is enforced with no extra keys.
    """
    
    hard_reject: bool = Field(..., description="Whether to hard reject")
    hard_reject_reasons: list[str] = Field(default_factory=list, description="List of hard reject reasons")
    
    dimension_scores: dict[str, DimensionScore] = Field(..., description="Scores by dimension name")
    
    weighted_score: int = Field(..., ge=0, le=100, description="Weighted score 0-100")
    tier: Literal["A", "B", "C", "REJECT"] = Field(..., description="Tier assignment")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence 0.0-1.0")
    
    needs_human_review: bool = Field(..., description="Whether human review is needed")
    needs_human_review_reasons: list[str] = Field(default_factory=list, description="Reasons for human review")
    
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list, description="Overall evidence snippets")
    missing_info_questions: list[str] = Field(default_factory=list, description="Missing information questions")
    
    rubric_version: str = Field(..., description="Rubric version used")
    
    @field_validator("dimension_scores")
    @classmethod
    def validate_dimension_scores(cls, v: dict) -> dict:
        """Ensure dimension_scores is a dict with DimensionScore values."""
        if not isinstance(v, dict):
            raise ValueError("dimension_scores must be a dictionary")
        return v
    
    class Config:
        extra = "forbid"  # No extra keys allowed


def validate_scoring_output(data: dict) -> ScoringOutput:
    """
    Validate scoring output against strict schema.
    
    Args:
        data: Scoring output dictionary
    
    Returns:
        Validated ScoringOutput object
    
    Raises:
        ValueError: If validation fails
    """
    try:
        return ScoringOutput(**data)
    except Exception as e:
        raise ValueError(f"Scoring output validation failed: {str(e)}")
