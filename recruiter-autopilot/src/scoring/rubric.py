"""Rubric loading and validation."""

from pathlib import Path
from typing import Any

import yaml

from src.config import settings
from src.utils.logging import get_logger
from src.utils.security import check_protected_traits_in_scoring

logger = get_logger(__name__)


class RubricValidationError(Exception):
    """Raised when rubric validation fails."""
    pass


class RubricLoader:
    """
    Loads and validates scoring rubrics from YAML files.

    Rubric format:
    ```yaml
    name: "Software Engineer Rubric"
    version: "1.0"
    description: "Scoring rubric for software engineering roles"

    dimensions:
      experience:
        weight: 0.30
        description: "Years of relevant experience"
        scoring:
          0-2_years: 3
          2-5_years: 6
          5-10_years: 8
          10+_years: 10

      skills:
        weight: 0.40
        description: "Technical skills alignment"
        required_any:
          - python
          - java
          - go
        preferred:
          - kubernetes
          - aws
        scoring:
          all_required_plus_preferred: 10
          all_required: 7
          some_required: 4
          none: 0

    hard_constraints:
      - name: min_experience
        type: years
        min: 2
        reject_message: "Does not meet minimum experience requirement"

      - name: required_degree
        type: education
        degrees:
          - BS
          - MS
          - PhD
        reject_message: "Does not have required degree"

    tier_thresholds:
      A: 0.85
      B: 0.70
      C: 0.50

    confidence_settings:
      threshold: 0.7
      low_confidence_triggers_review: true

    review_triggers:
      - condition: "tier == 'B' and confidence < 0.8"
      - condition: "missing_info contains 'work_authorization'"
    ```
    """

    def __init__(self, rubrics_dir: str | None = None):
        self.rubrics_dir = Path(rubrics_dir or settings.rubrics_directory)

    def load(self, rubric_path: str | Path) -> dict:
        """
        Load and validate a rubric from a YAML file.

        Args:
            rubric_path: Path to the rubric YAML file

        Returns:
            Validated rubric dictionary

        Raises:
            RubricValidationError: If validation fails
        """
        path = Path(rubric_path)
        if not path.is_absolute():
            path = self.rubrics_dir / path

        if not path.exists():
            raise RubricValidationError(f"Rubric file not found: {path}")

        try:
            with open(path) as f:
                rubric = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise RubricValidationError(f"Invalid YAML in rubric: {e}")

        self._validate(rubric)
        return rubric

    def load_from_dict(self, rubric: dict) -> dict:
        """Load and validate a rubric from a dictionary."""
        self._validate(rubric)
        return rubric

    def _validate(self, rubric: dict) -> None:
        """
        Validate rubric structure and content.

        Checks:
        - Required fields present
        - Weights sum to 1.0
        - No protected traits in criteria
        - Valid threshold values
        """
        # Required fields
        required_fields = ["name", "version", "dimensions", "tier_thresholds"]
        for field in required_fields:
            if field not in rubric:
                raise RubricValidationError(f"Missing required field: {field}")

        # Validate dimensions
        dimensions = rubric.get("dimensions", {})
        if not dimensions:
            raise RubricValidationError("Rubric must have at least one dimension")

        total_weight = 0.0
        for dim_name, dim_config in dimensions.items():
            if "weight" not in dim_config:
                raise RubricValidationError(f"Dimension '{dim_name}' missing weight")

            weight = dim_config["weight"]
            if not 0 < weight <= 1:
                raise RubricValidationError(
                    f"Dimension '{dim_name}' has invalid weight: {weight}"
                )
            total_weight += weight

        # Weights should sum to approximately 1.0
        if abs(total_weight - 1.0) > 0.01:
            raise RubricValidationError(
                f"Dimension weights must sum to 1.0, got {total_weight:.2f}"
            )

        # Validate tier thresholds
        thresholds = rubric.get("tier_thresholds", {})
        required_tiers = {"A", "B", "C"}
        if not required_tiers.issubset(thresholds.keys()):
            raise RubricValidationError(
                f"tier_thresholds must include A, B, and C"
            )

        for tier, threshold in thresholds.items():
            if not 0 <= threshold <= 1:
                raise RubricValidationError(
                    f"Tier '{tier}' has invalid threshold: {threshold}"
                )

        # Check for protected traits (EEOC compliance)
        violations = check_protected_traits_in_scoring(rubric)
        if violations:
            raise RubricValidationError(
                f"Rubric contains protected traits: {violations}"
            )

        logger.debug(
            "Rubric validated",
            name=rubric.get("name"),
            version=rubric.get("version"),
            dimensions=list(dimensions.keys()),
        )


class RubricEvaluator:
    """
    Evaluates extracted facts against a rubric.

    This evaluator uses rule-based scoring. For production,
    consider integrating with an LLM for more nuanced evaluation.
    """

    def __init__(self, rubric: dict):
        self.rubric = rubric
        self.dimensions = rubric.get("dimensions", {})
        self.hard_constraints = rubric.get("hard_constraints", [])
        self.tier_thresholds = rubric.get("tier_thresholds", {})
        self.confidence_settings = rubric.get("confidence_settings", {})
        self.review_triggers = rubric.get("review_triggers", [])

    def evaluate(self, facts: dict) -> dict:
        """
        Evaluate facts against the rubric.

        Args:
            facts: Extracted facts dictionary

        Returns:
            Evaluation result with scores, tier, and recommendations
        """
        result = {
            "dimension_scores": {},
            "total_score": 0.0,
            "max_score": 0.0,
            "percentage": 0.0,
            "tier": "C",
            "confidence": 0.7,
            "hard_constraints_passed": True,
            "failed_constraints": [],
            "evidence": {},
            "missing_info": facts.get("missing_info", []),
            "needs_human_review": False,
            "review_reasons": [],
            "recommendation": "",
        }

        # Check hard constraints first
        for constraint in self.hard_constraints:
            passed, message = self._check_constraint(constraint, facts)
            if not passed:
                result["hard_constraints_passed"] = False
                result["failed_constraints"].append({
                    "name": constraint.get("name"),
                    "message": message,
                })

        # If hard constraints failed, set tier to REJECT
        if not result["hard_constraints_passed"]:
            result["tier"] = "REJECT"
            result["recommendation"] = (
                f"Auto-reject: {result['failed_constraints'][0]['message']}"
            )
            return result

        # Score each dimension
        for dim_name, dim_config in self.dimensions.items():
            score, max_score, evidence = self._score_dimension(
                dim_name, dim_config, facts
            )
            result["dimension_scores"][dim_name] = {
                "score": score,
                "max_score": max_score,
                "weight": dim_config["weight"],
                "weighted_score": score * dim_config["weight"],
                "evidence": evidence,
            }
            result["total_score"] += score * dim_config["weight"]
            result["max_score"] += max_score * dim_config["weight"]

        # Calculate percentage
        if result["max_score"] > 0:
            result["percentage"] = result["total_score"] / result["max_score"]
        else:
            result["percentage"] = 0.0

        # Determine tier
        result["tier"] = self._determine_tier(result["percentage"])

        # Set confidence based on extraction confidence
        result["confidence"] = facts.get("extraction_confidence", 0.7)

        # Check review triggers
        result["needs_human_review"], result["review_reasons"] = self._check_review_triggers(
            result, facts
        )

        # Generate recommendation
        result["recommendation"] = self._generate_recommendation(result)

        return result

    def _check_constraint(self, constraint: dict, facts: dict) -> tuple[bool, str]:
        """Check if a hard constraint is satisfied."""
        constraint_type = constraint.get("type")
        name = constraint.get("name", "unnamed")
        reject_message = constraint.get("reject_message", f"Failed constraint: {name}")

        if constraint_type == "years":
            min_years = constraint.get("min", 0)
            actual_years = facts.get("total_years_experience", 0)
            if actual_years < min_years:
                return False, reject_message
            return True, ""

        if constraint_type == "education":
            required_degrees = set(constraint.get("degrees", []))
            has_degree = facts.get("highest_degree") in required_degrees
            if not has_degree and required_degrees:
                return False, reject_message
            return True, ""

        if constraint_type == "skill":
            required_skills = set(s.lower() for s in constraint.get("skills", []))
            candidate_skills = set(s.lower() for s in facts.get("skills", []))
            if not required_skills.intersection(candidate_skills):
                return False, reject_message
            return True, ""

        # Unknown constraint type - pass by default
        return True, ""

    def _score_dimension(
        self,
        dim_name: str,
        dim_config: dict,
        facts: dict,
    ) -> tuple[float, float, str]:
        """Score a single dimension."""
        max_score = 10.0  # All dimensions scored 0-10
        evidence = ""

        if dim_name == "experience":
            years = facts.get("total_years_experience", 0)
            scoring = dim_config.get("scoring", {})

            if years >= 10:
                score = scoring.get("10+_years", 10)
                evidence = f"{years}+ years of experience"
            elif years >= 5:
                score = scoring.get("5-10_years", 8)
                evidence = f"{years} years of experience"
            elif years >= 2:
                score = scoring.get("2-5_years", 6)
                evidence = f"{years} years of experience"
            else:
                score = scoring.get("0-2_years", 3)
                evidence = f"{years} years of experience"

            return float(score), max_score, evidence

        if dim_name == "skills":
            required_any = set(s.lower() for s in dim_config.get("required_any", []))
            preferred = set(s.lower() for s in dim_config.get("preferred", []))
            candidate_skills = set(s.lower() for s in facts.get("skills", []))

            has_required = bool(required_any.intersection(candidate_skills))
            preferred_count = len(preferred.intersection(candidate_skills))

            if has_required and preferred_count >= 2:
                score = 10.0
                evidence = f"Has required skills + {preferred_count} preferred"
            elif has_required:
                score = 7.0
                evidence = "Has required skills"
            elif candidate_skills:
                score = 4.0
                evidence = f"Has {len(candidate_skills)} relevant skills"
            else:
                score = 0.0
                evidence = "No relevant skills found"

            return score, max_score, evidence

        if dim_name == "education":
            degree = facts.get("highest_degree")
            degree_scores = {"PhD": 10, "MS": 9, "MBA": 9, "MA": 8, "BS": 7, "BA": 7}
            score = float(degree_scores.get(degree, 5))
            evidence = f"Highest degree: {degree}" if degree else "No degree found"
            return score, max_score, evidence

        if dim_name == "leadership":
            has_management = facts.get("has_management_experience", False)
            team_size = facts.get("team_size_managed")
            has_mentoring = facts.get("has_mentoring_experience", False)

            score = 0.0
            evidence_parts = []

            if has_management:
                score += 5.0
                if team_size:
                    evidence_parts.append(f"Managed team of {team_size}")
                else:
                    evidence_parts.append("Has management experience")

            if has_mentoring:
                score += 3.0
                evidence_parts.append("Mentoring experience")

            if not evidence_parts:
                evidence = "No leadership indicators found"
            else:
                evidence = "; ".join(evidence_parts)

            return min(score, max_score), max_score, evidence

        # Default scoring for unknown dimensions
        return 5.0, max_score, "Default score (dimension not specifically evaluated)"

    def _determine_tier(self, percentage: float) -> str:
        """Determine tier based on percentage score."""
        if percentage >= self.tier_thresholds.get("A", 0.85):
            return "A"
        if percentage >= self.tier_thresholds.get("B", 0.70):
            return "B"
        if percentage >= self.tier_thresholds.get("C", 0.50):
            return "C"
        return "REJECT"

    def _check_review_triggers(
        self,
        result: dict,
        facts: dict,
    ) -> tuple[bool, list[str]]:
        """Check if any review triggers are activated."""
        needs_review = False
        reasons = []

        # Low confidence check
        confidence_threshold = self.confidence_settings.get("threshold", 0.7)
        if result["confidence"] < confidence_threshold:
            if self.confidence_settings.get("low_confidence_triggers_review", True):
                needs_review = True
                reasons.append(f"Low extraction confidence ({result['confidence']:.0%})")

        # Borderline tier check
        if result["tier"] == "B":
            percentage = result["percentage"]
            a_threshold = self.tier_thresholds.get("A", 0.85)
            if percentage >= a_threshold - 0.05:
                needs_review = True
                reasons.append("Borderline A/B tier")

        # Missing critical info
        critical_missing = ["work_authorization", "visa_status", "work_experience"]
        for missing in facts.get("missing_info", []):
            if missing in critical_missing:
                needs_review = True
                reasons.append(f"Missing critical info: {missing}")

        return needs_review, reasons

    def _generate_recommendation(self, result: dict) -> str:
        """Generate a recommendation based on evaluation."""
        tier = result["tier"]
        percentage = result["percentage"]
        needs_review = result["needs_human_review"]

        if tier == "REJECT":
            if result["failed_constraints"]:
                return f"Reject: {result['failed_constraints'][0]['message']}"
            return "Reject: Below minimum threshold"

        if tier == "A":
            return f"Strong candidate ({percentage:.0%}). Recommend advancing."

        if tier == "B":
            if needs_review:
                return f"Good candidate ({percentage:.0%}). Needs review: {', '.join(result['review_reasons'])}"
            return f"Good candidate ({percentage:.0%}). Consider for interview."

        return f"Below bar ({percentage:.0%}). Hold for review or reject."
