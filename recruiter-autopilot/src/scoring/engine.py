"""Main scoring engine that orchestrates parsing, extraction, and evaluation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.config import settings
from src.scoring.parser import ResumeParser, MockResumeParser
from src.scoring.extractor import FactExtractor, ExtractedFacts
from src.scoring.rubric import RubricLoader, RubricEvaluator
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ScoringResult:
    """Complete scoring result for an application."""

    # Identification
    application_id: int
    rubric_name: str
    rubric_version: str
    scored_at: datetime

    # Scores
    total_score: float
    max_score: float
    percentage: float
    tier: str  # A, B, C, REJECT
    confidence: float

    # Dimension breakdown
    dimension_scores: dict[str, dict]

    # Constraints
    hard_constraints_passed: bool
    failed_constraints: list[dict]

    # Evidence
    evidence: dict
    missing_info: list[str]

    # Review flags
    needs_human_review: bool
    review_reasons: list[str]

    # Recommendation
    recommendation: str

    # Raw data (for debugging)
    extracted_facts: dict

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "application_id": self.application_id,
            "rubric_name": self.rubric_name,
            "rubric_version": self.rubric_version,
            "scored_at": self.scored_at.isoformat(),
            "total_score": self.total_score,
            "max_score": self.max_score,
            "percentage": self.percentage,
            "tier": self.tier,
            "confidence": self.confidence,
            "dimension_scores": self.dimension_scores,
            "hard_constraints_passed": self.hard_constraints_passed,
            "failed_constraints": self.failed_constraints,
            "evidence": self.evidence,
            "missing_info": self.missing_info,
            "needs_human_review": self.needs_human_review,
            "review_reasons": self.review_reasons,
            "recommendation": self.recommendation,
        }


class ScoringEngine:
    """
    Main scoring engine that processes applications.

    Pipeline:
    1. Parse resume content (PDF/DOCX to text)
    2. Extract structured facts from text
    3. Evaluate facts against rubric
    4. Generate scoring result with recommendation
    """

    def __init__(
        self,
        rubric_path: str | None = None,
        rubric_dict: dict | None = None,
        mock_mode: bool = False,
    ):
        """
        Initialize the scoring engine.

        Args:
            rubric_path: Path to rubric YAML file
            rubric_dict: Rubric as dictionary (alternative to path)
            mock_mode: Use mock parser for testing
        """
        self.mock_mode = mock_mode or settings.mock_mode

        # Initialize parser
        if self.mock_mode:
            self.parser = MockResumeParser()
        else:
            self.parser = ResumeParser()

        # Initialize extractor
        self.extractor = FactExtractor()

        # Load rubric
        if rubric_dict:
            self.rubric = RubricLoader().load_from_dict(rubric_dict)
        elif rubric_path:
            self.rubric = RubricLoader().load(rubric_path)
        else:
            # Use default rubric
            self.rubric = self._get_default_rubric()

        self.evaluator = RubricEvaluator(self.rubric)

    def score(
        self,
        application_id: int,
        resume_content: bytes,
        resume_filename: str,
    ) -> ScoringResult:
        """
        Score an application based on resume.

        Args:
            application_id: The application ID
            resume_content: Raw resume file bytes
            resume_filename: Original filename (for type detection)

        Returns:
            ScoringResult with complete evaluation
        """
        logger.info(
            "Starting scoring",
            application_id=application_id,
            filename=resume_filename,
        )

        # Step 1: Parse resume
        try:
            resume_text = self.parser.parse(resume_content, resume_filename)
        except Exception as e:
            logger.error(
                "Resume parsing failed",
                application_id=application_id,
                error=str(e),
            )
            return self._create_error_result(
                application_id,
                error=f"Parse error: {str(e)}",
            )

        # Step 2: Extract facts
        try:
            facts = self.extractor.extract(resume_text)
        except Exception as e:
            logger.error(
                "Fact extraction failed",
                application_id=application_id,
                error=str(e),
            )
            return self._create_error_result(
                application_id,
                error=f"Extraction error: {str(e)}",
            )

        # Step 3: Evaluate against rubric
        try:
            evaluation = self.evaluator.evaluate(facts.to_dict())
        except Exception as e:
            logger.error(
                "Rubric evaluation failed",
                application_id=application_id,
                error=str(e),
            )
            return self._create_error_result(
                application_id,
                error=f"Evaluation error: {str(e)}",
            )

        # Create result
        result = ScoringResult(
            application_id=application_id,
            rubric_name=self.rubric.get("name", "default"),
            rubric_version=self.rubric.get("version", "1.0"),
            scored_at=datetime.utcnow(),
            total_score=evaluation["total_score"],
            max_score=evaluation["max_score"],
            percentage=evaluation["percentage"],
            tier=evaluation["tier"],
            confidence=evaluation["confidence"],
            dimension_scores=evaluation["dimension_scores"],
            hard_constraints_passed=evaluation["hard_constraints_passed"],
            failed_constraints=evaluation["failed_constraints"],
            evidence=evaluation["evidence"],
            missing_info=evaluation["missing_info"],
            needs_human_review=evaluation["needs_human_review"],
            review_reasons=evaluation["review_reasons"],
            recommendation=evaluation["recommendation"],
            extracted_facts=facts.to_dict(),
        )

        logger.info(
            "Scoring complete",
            application_id=application_id,
            tier=result.tier,
            percentage=f"{result.percentage:.0%}",
            confidence=f"{result.confidence:.0%}",
            needs_review=result.needs_human_review,
        )

        return result

    def score_from_text(
        self,
        application_id: int,
        resume_text: str,
    ) -> ScoringResult:
        """
        Score an application from pre-extracted resume text.

        Useful for re-scoring or when text is already available.
        """
        logger.info(
            "Starting scoring from text",
            application_id=application_id,
        )

        # Extract facts
        facts = self.extractor.extract(resume_text)

        # Evaluate
        evaluation = self.evaluator.evaluate(facts.to_dict())

        # Create result
        result = ScoringResult(
            application_id=application_id,
            rubric_name=self.rubric.get("name", "default"),
            rubric_version=self.rubric.get("version", "1.0"),
            scored_at=datetime.utcnow(),
            total_score=evaluation["total_score"],
            max_score=evaluation["max_score"],
            percentage=evaluation["percentage"],
            tier=evaluation["tier"],
            confidence=evaluation["confidence"],
            dimension_scores=evaluation["dimension_scores"],
            hard_constraints_passed=evaluation["hard_constraints_passed"],
            failed_constraints=evaluation["failed_constraints"],
            evidence=evaluation["evidence"],
            missing_info=evaluation["missing_info"],
            needs_human_review=evaluation["needs_human_review"],
            review_reasons=evaluation["review_reasons"],
            recommendation=evaluation["recommendation"],
            extracted_facts=facts.to_dict(),
        )

        return result

    def _create_error_result(
        self,
        application_id: int,
        error: str,
    ) -> ScoringResult:
        """Create a result for processing errors."""
        return ScoringResult(
            application_id=application_id,
            rubric_name=self.rubric.get("name", "default"),
            rubric_version=self.rubric.get("version", "1.0"),
            scored_at=datetime.utcnow(),
            total_score=0.0,
            max_score=10.0,
            percentage=0.0,
            tier="REJECT",
            confidence=0.0,
            dimension_scores={},
            hard_constraints_passed=False,
            failed_constraints=[{"name": "processing_error", "message": error}],
            evidence={},
            missing_info=["processing_error"],
            needs_human_review=True,
            review_reasons=[f"Processing error: {error}"],
            recommendation=f"Error during processing: {error}",
            extracted_facts={},
        )

    def _get_default_rubric(self) -> dict:
        """Return a default rubric for general software engineering roles."""
        return {
            "name": "Default Software Engineer Rubric",
            "version": "1.0",
            "description": "Generic rubric for software engineering positions",
            "dimensions": {
                "experience": {
                    "weight": 0.35,
                    "description": "Years of relevant experience",
                    "scoring": {
                        "0-2_years": 3,
                        "2-5_years": 6,
                        "5-10_years": 8,
                        "10+_years": 10,
                    },
                },
                "skills": {
                    "weight": 0.40,
                    "description": "Technical skills alignment",
                    "required_any": ["python", "java", "javascript", "go", "c++"],
                    "preferred": ["kubernetes", "aws", "docker", "postgresql"],
                },
                "education": {
                    "weight": 0.15,
                    "description": "Educational background",
                },
                "leadership": {
                    "weight": 0.10,
                    "description": "Leadership and mentoring experience",
                },
            },
            "hard_constraints": [
                {
                    "name": "min_experience",
                    "type": "years",
                    "min": 1,
                    "reject_message": "Less than 1 year of experience",
                },
            ],
            "tier_thresholds": {
                "A": 0.80,
                "B": 0.65,
                "C": 0.45,
            },
            "confidence_settings": {
                "threshold": 0.7,
                "low_confidence_triggers_review": True,
            },
            "review_triggers": [
                {"condition": "tier == 'B' and confidence < 0.75"},
            ],
        }


def format_scoring_note(result: ScoringResult) -> str:
    """
    Format scoring result as a Greenhouse note.

    Creates a structured, readable note for the application timeline.
    """
    lines = [
        "## Automated Scoring Results",
        "",
        f"**Rubric:** {result.rubric_name} v{result.rubric_version}",
        f"**Scored:** {result.scored_at.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "---",
        "",
        f"### Overall: **{result.tier}** ({result.percentage:.0%})",
        f"**Confidence:** {result.confidence:.0%}",
        "",
    ]

    # Dimension breakdown
    lines.append("### Dimension Scores")
    for dim_name, dim_data in result.dimension_scores.items():
        score = dim_data.get("score", 0)
        max_score = dim_data.get("max_score", 10)
        evidence = dim_data.get("evidence", "")
        lines.append(f"- **{dim_name.title()}:** {score:.1f}/{max_score:.0f} - {evidence}")

    lines.append("")

    # Hard constraints
    if not result.hard_constraints_passed:
        lines.append("### Failed Constraints")
        for constraint in result.failed_constraints:
            lines.append(f"- ❌ {constraint.get('message', 'Unknown constraint')}")
        lines.append("")

    # Review flags
    if result.needs_human_review:
        lines.append("### ⚠️ Needs Human Review")
        for reason in result.review_reasons:
            lines.append(f"- {reason}")
        lines.append("")

    # Recommendation
    lines.append("### Recommendation")
    lines.append(result.recommendation)
    lines.append("")
    lines.append("---")
    lines.append("*Generated by Recruiter Autopilot*")

    return "\n".join(lines)
