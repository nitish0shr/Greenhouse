# =============================================================================
# Scoring Engine - Rubric-Based Scoring with Strict JSON Schema Output
# =============================================================================

import logging
from typing import Any, Optional
import yaml
from pathlib import Path

from app.config import settings
from app.schemas.scoring import ScoringOutput, DimensionScore, EvidenceSnippet, validate_scoring_output
from app.utils.compliance import validate_rubric
from app.utils.security import sanitize_resume_text, detect_injection_attempts

logger = logging.getLogger(__name__)


class ScoringEngine:
    """
    Scoring engine that produces strict JSON schema output per First Review.
    
    This engine:
    1. Loads rubric YAML
    2. Scores candidate against rubric
    3. Produces strict JSON schema output (validated)
    4. Never uses LLM (keyword matching only)
    """
    
    def __init__(self, rubric_path: Optional[str] = None, rubric_version: str = "1.0.0"):
        """
        Initialize scoring engine.
        
        Args:
            rubric_path: Path to rubric YAML file
            rubric_version: Version string for rubric
        """
        self.rubric_path = rubric_path or settings.scoring_rubric_path
        self.rubric_version = rubric_version
        self.rubric = self._load_rubric()
        
        # Validate rubric for compliance
        compliance_issues = validate_rubric(self.rubric)
        if compliance_issues:
            logger.error(f"Rubric compliance issues: {compliance_issues}")
            raise ValueError(f"Rubric contains protected traits: {compliance_issues}")
    
    def _load_rubric(self) -> dict:
        """Load rubric from YAML file."""
        rubric_path = Path(self.rubric_path)
        
        if not rubric_path.exists():
            logger.warning(f"Rubric file not found: {rubric_path}, using defaults")
            return self._get_default_rubric()
        
        with open(rubric_path) as f:
            return yaml.safe_load(f)
    
    def _get_default_rubric(self) -> dict:
        """Return default rubric."""
        return {
            "dimensions": [],
            "hard_constraints": [],
            "thresholds": {
                "advance": settings.score_threshold_advance,
                "reject": settings.score_threshold_reject,
                "human_review": settings.low_confidence_threshold,
            },
        }
    
    def score(
        self,
        resume_text: str,
        application_data: Optional[dict] = None,
    ) -> dict:
        """
        Score candidate and return strict JSON schema output.
        
        Args:
            resume_text: Extracted resume text
            application_data: Optional application data
        
        Returns:
            Dict conforming to ScoringOutput schema (validated)
        """
        # Sanitize resume text
        clean_text = sanitize_resume_text(resume_text)
        text_lower = clean_text.lower()
        
        # Detect injection attempts
        injection_attempts = detect_injection_attempts(resume_text)
        warnings = []
        if injection_attempts:
            warnings.append(f"Potential injection patterns detected")
            logger.warning(f"Injection patterns in resume: {injection_attempts}")
        
        # Check hard constraints first
        hard_reject = False
        hard_reject_reasons = []
        
        for constraint in self.rubric.get("hard_constraints", []):
            constraint_type = constraint.get("type")
            
            if constraint_type == "years_experience":
                minimum = constraint.get("minimum", 0)
                # Extract years of experience from resume (simple regex)
                import re
                years_match = re.search(r'(\d+)\+?\s*years?\s*(?:of\s*)?experience', text_lower)
                if years_match:
                    years = int(years_match.group(1))
                    if years < minimum:
                        hard_reject = True
                        hard_reject_reasons.append(f"Less than {minimum} years experience")
            
            elif constraint_type == "keyword_required":
                keywords = constraint.get("keywords", [])
                if not any(keyword.lower() in text_lower for keyword in keywords):
                    hard_reject = True
                    hard_reject_reasons.append(f"Missing required keywords: {keywords}")
        
        # Score dimensions
        dimension_scores = {}
        all_evidence = []
        total_weighted_score = 0.0
        total_weight = 0.0
        
        for dimension in self.rubric.get("dimensions", []):
            dim_name = dimension.get("name")
            weight = dimension.get("weight", 10)
            scoring_method = dimension.get("scoring_method", "keyword_match")
            criteria = dimension.get("criteria", [])
            
            dim_score = 0
            dim_evidence = []
            
            if scoring_method == "keyword_match":
                for criterion in criteria:
                    keywords = criterion.get("keywords", [])
                    required = criterion.get("required", False)
                    
                    found = False
                    matched_keyword = None
                    for keyword in keywords:
                        if keyword.lower() in text_lower:
                            found = True
                            matched_keyword = keyword
                            break
                    
                    if found:
                        dim_score = 100  # Full score if keyword found
                        # Extract snippet as evidence
                        import re
                        pattern = re.compile(re.escape(matched_keyword), re.IGNORECASE)
                        matches = list(pattern.finditer(clean_text))
                        if matches:
                            match = matches[0]
                            start = max(0, match.start() - 50)
                            end = min(len(clean_text), match.end() + 50)
                            snippet = clean_text[start:end].strip()
                            dim_evidence.append(EvidenceSnippet(
                                snippet=snippet,
                                source="resume"
                            ))
                    elif required:
                        hard_reject = True
                        hard_reject_reasons.append(f"Missing required keyword: {keywords}")
            
            elif scoring_method == "numeric_range":
                # Extract numeric value and score based on range
                field = dimension.get("field", "")
                # Simple extraction (can be enhanced)
                if field == "years_experience":
                    import re
                    years_match = re.search(r'(\d+)\+?\s*years?\s*(?:of\s*)?experience', text_lower)
                    if years_match:
                        years = int(years_match.group(1))
                        minimum = dimension.get("minimum", 0)
                        ideal = dimension.get("ideal", minimum + 2)
                        
                        if years >= ideal:
                            dim_score = 100
                        elif years >= minimum:
                            # Linear interpolation
                            dim_score = int((years - minimum) / (ideal - minimum) * 100)
                        else:
                            dim_score = 0
                        
                        snippet = f"{years} years of experience"
                        dim_evidence.append(EvidenceSnippet(
                            snippet=snippet,
                            source="resume"
                        ))
            
            dimension_scores[dim_name] = DimensionScore(
                score=dim_score,
                evidence=dim_evidence
            )
            all_evidence.extend(dim_evidence)
            
            total_weighted_score += dim_score * weight
            total_weight += weight
        
        # Calculate weighted score
        if total_weight > 0:
            weighted_score = int(total_weighted_score / total_weight)
        else:
            weighted_score = 0
        
        # Determine tier
        if hard_reject:
            tier = "REJECT"
        elif weighted_score >= 85:
            tier = "A"
        elif weighted_score >= 70:
            tier = "B"
        elif weighted_score >= 50:
            tier = "C"
        else:
            tier = "REJECT"
        
        # Calculate confidence (simple heuristic)
        evidence_count = len(all_evidence)
        dimension_count = len(self.rubric.get("dimensions", []))
        if dimension_count > 0:
            confidence = min(1.0, evidence_count / dimension_count)
        else:
            confidence = 0.5
        
        # Determine if human review needed
        needs_human_review = (
            confidence < 0.7 or
            weighted_score >= 50 and weighted_score < 75 or
            len(warnings) > 0
        )
        needs_human_review_reasons = []
        if confidence < 0.7:
            needs_human_review_reasons.append(f"Low confidence: {confidence:.2f}")
        if weighted_score >= 50 and weighted_score < 75:
            needs_human_review_reasons.append(f"Score in review range: {weighted_score}")
        if warnings:
            needs_human_review_reasons.extend(warnings)
        
        # Build output dict
        output_dict = {
            "hard_reject": hard_reject,
            "hard_reject_reasons": hard_reject_reasons,
            "dimension_scores": {
                name: {
                    "score": score.score,
                    "evidence": [{"snippet": e.snippet, "source": e.source} for e in score.evidence]
                }
                for name, score in dimension_scores.items()
            },
            "weighted_score": weighted_score,
            "tier": tier,
            "confidence": confidence,
            "needs_human_review": needs_human_review,
            "needs_human_review_reasons": needs_human_review_reasons,
            "evidence_snippets": [{"snippet": e.snippet, "source": e.source} for e in all_evidence],
            "missing_info_questions": [],  # Can be enhanced to detect missing info
            "rubric_version": self.rubric_version,
        }
        
        # Validate against strict schema
        validated = validate_scoring_output(output_dict)
        
        # Return as dict (for JSON serialization)
        return validated.model_dump()
