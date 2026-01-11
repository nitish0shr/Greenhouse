# =============================================================================
# Candidate Scoring Engine
# =============================================================================

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from app.config import settings
from app.utils.compliance import audit_scoring_decision, validate_rubric
from app.utils.security import detect_injection_attempts, sanitize_resume_text

logger = logging.getLogger(__name__)


@dataclass
class ScoringResult:
    """Result of candidate scoring."""
    
    # Overall score (0-100)
    score: float
    
    # Confidence in the score (0-1)
    confidence: float
    
    # Whether to hard-reject (failed mandatory constraints)
    hard_reject: bool = False
    
    # List of failed hard constraints
    failed_constraints: list[str] = field(default_factory=list)
    
    # Breakdown by category
    score_breakdown: dict[str, float] = field(default_factory=dict)
    
    # Keywords/skills matched
    matched_skills: list[str] = field(default_factory=list)
    
    # Missing required skills
    missing_skills: list[str] = field(default_factory=list)
    
    # Suggested action based on score
    suggested_action: str = "human_review"  # advance, reject, human_review
    
    # Suggested rejection reason ID (if hard_reject)
    rejection_reason_id: Optional[int] = None
    
    # Warnings (e.g., potential injection attempts)
    warnings: list[str] = field(default_factory=list)
    
    # Compliance audit result
    compliance_audit: dict = field(default_factory=dict)


class CandidateScorer:
    """
    Score candidates against a configurable rubric.
    
    The rubric is a YAML file that defines:
    - Required skills with weights and keywords
    - Hard constraints (e.g., minimum experience)
    - Score thresholds for actions
    
    IMPORTANT: This scorer uses keyword matching only.
    Resume text is treated as untrusted - never passed to LLM.
    """
    
    def __init__(self, rubric_path: Optional[str] = None):
        """
        Initialize scorer with rubric.
        
        Args:
            rubric_path: Path to rubric YAML file
        """
        self.rubric_path = rubric_path or settings.scoring_rubric_path
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
            logger.warning(f"Rubric file not found: {rubric_path}")
            return self._get_default_rubric()
        
        with open(rubric_path) as f:
            return yaml.safe_load(f)
    
    def _get_default_rubric(self) -> dict:
        """Return a default rubric when none is configured."""
        return {
            "required_skills": [],
            "preferred_skills": [],
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
    ) -> ScoringResult:
        """
        Score a candidate based on resume and application data.
        
        Args:
            resume_text: Extracted resume text
            application_data: Optional structured application data
        
        Returns:
            ScoringResult with score, breakdown, and action
        """
        # Sanitize resume text
        clean_text = sanitize_resume_text(resume_text)
        text_lower = clean_text.lower()
        
        # Detect potential injection attempts
        injection_attempts = detect_injection_attempts(resume_text)
        warnings = []
        if injection_attempts:
            warnings.append(f"Potential injection patterns detected: {injection_attempts}")
            logger.warning(f"Injection patterns in resume: {injection_attempts}")
        
        # Score required skills
        skill_scores = {}
        matched_skills = []
        missing_skills = []
        
        for skill_config in self.rubric.get("required_skills", []):
            skill_name = skill_config["name"]
            weight = skill_config.get("weight", 10)
            keywords = skill_config.get("keywords", [skill_name.lower()])
            
            # Check if any keyword matches
            found = False
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    found = True
                    matched_skills.append(skill_name)
                    break
            
            if found:
                skill_scores[skill_name] = weight
            else:
                skill_scores[skill_name] = 0
                missing_skills.append(skill_name)
        
        # Score preferred skills (lower weight)
        for skill_config in self.rubric.get("preferred_skills", []):
            skill_name = skill_config["name"]
            weight = skill_config.get("weight", 5)
            keywords = skill_config.get("keywords", [skill_name.lower()])
            
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    skill_scores[f"preferred_{skill_name}"] = weight
                    matched_skills.append(skill_name)
                    break
        
        # Calculate total score
        total_weight = sum(
            s.get("weight", 10) for s in self.rubric.get("required_skills", [])
        )
        total_weight += sum(
            s.get("weight", 5) for s in self.rubric.get("preferred_skills", [])
        )
        
        if total_weight > 0:
            raw_score = sum(skill_scores.values())
            score = (raw_score / total_weight) * 100
        else:
            score = 50  # Default when no rubric configured
        
        # Check hard constraints
        hard_reject = False
        failed_constraints = []
        rejection_reason_id = None
        
        for constraint in self.rubric.get("hard_constraints", []):
            constraint_type = constraint.get("type")
            
            if constraint_type == "years_experience":
                min_years = constraint.get("minimum", 0)
                detected_years = self._extract_years_experience(clean_text)
                
                if detected_years is not None and detected_years < min_years:
                    hard_reject = True
                    failed_constraints.append(
                        f"Minimum {min_years} years experience required, "
                        f"detected {detected_years}"
                    )
                    rejection_reason_id = constraint.get("reject_reason_id")
            
            elif constraint_type == "required_keyword":
                required = constraint.get("keyword", "").lower()
                if required and required not in text_lower:
                    hard_reject = True
                    failed_constraints.append(f"Missing required keyword: {required}")
                    rejection_reason_id = constraint.get("reject_reason_id")
            
            elif constraint_type == "education":
                required_level = constraint.get("level", "").lower()
                if required_level:
                    has_education = self._check_education_level(
                        clean_text, required_level
                    )
                    if not has_education:
                        hard_reject = True
                        failed_constraints.append(
                            f"Required education: {required_level}"
                        )
                        rejection_reason_id = constraint.get("reject_reason_id")
        
        # Calculate confidence
        # Higher confidence when we have clear matches/misses
        confidence = self._calculate_confidence(
            score=score,
            matched_count=len(matched_skills),
            total_required=len(self.rubric.get("required_skills", [])),
            text_length=len(clean_text),
        )
        
        # Determine suggested action
        thresholds = self.rubric.get("thresholds", {})
        advance_threshold = thresholds.get("advance", settings.score_threshold_advance)
        reject_threshold = thresholds.get("reject", settings.score_threshold_reject)
        review_threshold = thresholds.get("human_review", settings.low_confidence_threshold)
        
        if hard_reject:
            suggested_action = "reject"
        elif score >= advance_threshold and confidence >= 0.7:
            suggested_action = "advance"
        elif score <= reject_threshold and confidence >= 0.7:
            suggested_action = "reject"
        else:
            suggested_action = "human_review"
        
        # Run compliance audit
        compliance_audit = audit_scoring_decision(
            resume_text=clean_text,
            score_breakdown=skill_scores,
            matched_terms=matched_skills,
        )
        
        if not compliance_audit.get("compliant", True):
            warnings.extend(compliance_audit.get("warnings", []))
        
        return ScoringResult(
            score=round(score, 2),
            confidence=round(confidence, 2),
            hard_reject=hard_reject,
            failed_constraints=failed_constraints,
            score_breakdown=skill_scores,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            suggested_action=suggested_action,
            rejection_reason_id=rejection_reason_id,
            warnings=warnings,
            compliance_audit=compliance_audit,
        )
    
    def _extract_years_experience(self, text: str) -> Optional[int]:
        """
        Extract years of experience from resume text.
        
        Looks for patterns like:
        - "5 years of experience"
        - "5+ years"
        - "five years experience"
        """
        # Numeric patterns
        patterns = [
            r"(\d+)\+?\s*years?\s*(?:of\s+)?experience",
            r"experience[:\s]+(\d+)\+?\s*years?",
            r"(\d+)\+?\s*yrs?\s*(?:of\s+)?experience",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text.lower())
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        
        # Word to number mapping
        word_numbers = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
        }
        
        for word, num in word_numbers.items():
            pattern = rf"{word}\s*years?\s*(?:of\s+)?experience"
            if re.search(pattern, text.lower()):
                return num
        
        return None
    
    def _check_education_level(self, text: str, required_level: str) -> bool:
        """Check if resume mentions required education level."""
        text_lower = text.lower()
        
        education_patterns = {
            "bachelor": [
                "bachelor", "b.s.", "bs", "b.a.", "ba",
                "undergraduate degree", "college degree",
            ],
            "master": [
                "master", "m.s.", "ms", "m.a.", "ma",
                "mba", "graduate degree",
            ],
            "phd": [
                "phd", "ph.d", "doctorate", "doctoral",
            ],
        }
        
        required_level = required_level.lower()
        if required_level in education_patterns:
            keywords = education_patterns[required_level]
            return any(kw in text_lower for kw in keywords)
        
        return required_level in text_lower
    
    def _calculate_confidence(
        self,
        score: float,
        matched_count: int,
        total_required: int,
        text_length: int,
    ) -> float:
        """
        Calculate confidence score.
        
        Factors:
        - Resume length (too short = low confidence)
        - Percentage of skills matched (clear match/miss = high confidence)
        - Score extremity (very high/low = higher confidence)
        """
        confidence = 0.5  # Start neutral
        
        # Adjust for resume length
        if text_length < 500:
            confidence -= 0.2
        elif text_length > 2000:
            confidence += 0.1
        
        # Adjust for skill matching ratio
        if total_required > 0:
            match_ratio = matched_count / total_required
            if match_ratio >= 0.8 or match_ratio <= 0.2:
                confidence += 0.2
            elif match_ratio >= 0.5:
                confidence += 0.1
        
        # Adjust for score extremity
        if score >= 85 or score <= 15:
            confidence += 0.2
        
        # Clamp to valid range
        return max(0.0, min(1.0, confidence))


def get_scorer() -> CandidateScorer:
    """Get scorer instance (creates new one to reload rubric)."""
    return CandidateScorer()
