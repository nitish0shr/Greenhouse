"""Unit tests for scoring engine."""

import pytest

from src.scoring.extractor import FactExtractor, ExtractedFacts
from src.scoring.rubric import RubricLoader, RubricEvaluator, RubricValidationError
from src.scoring.engine import ScoringEngine


class TestFactExtractor:
    """Tests for fact extraction from resumes."""

    def test_extract_email(self, sample_resume_text):
        """Test email extraction."""
        extractor = FactExtractor()
        facts = extractor.extract(sample_resume_text)

        assert facts.email == "jane.doe@email.com"

    def test_extract_phone(self, sample_resume_text):
        """Test phone number extraction."""
        extractor = FactExtractor()
        facts = extractor.extract(sample_resume_text)

        assert facts.phone is not None
        assert "555" in facts.phone

    def test_extract_skills(self, sample_resume_text):
        """Test skill extraction."""
        extractor = FactExtractor()
        facts = extractor.extract(sample_resume_text)

        # Should find programming languages
        skills_lower = [s.lower() for s in facts.skills]
        assert "python" in skills_lower or "Python" in facts.programming_languages

    def test_extract_experience(self, sample_resume_text):
        """Test experience extraction."""
        extractor = FactExtractor()
        facts = extractor.extract(sample_resume_text)

        # Should extract some experience
        assert facts.total_years_experience >= 0

    def test_extract_education(self, sample_resume_text):
        """Test education extraction."""
        extractor = FactExtractor()
        facts = extractor.extract(sample_resume_text)

        # Should find MS degree
        assert facts.education
        degrees = [e.degree for e in facts.education]
        assert "MS" in degrees or "BS" in degrees

    def test_extract_leadership(self, sample_resume_text):
        """Test leadership indicator extraction."""
        extractor = FactExtractor()
        facts = extractor.extract(sample_resume_text)

        # Resume mentions mentoring
        assert facts.has_mentoring_experience or facts.has_management_experience

    def test_extract_from_minimal_resume(self):
        """Test extraction from minimal resume content."""
        extractor = FactExtractor()

        minimal_resume = """
        John Smith
        john@example.com

        Experience:
        Developer at Company 2020-2023
        """

        facts = extractor.extract(minimal_resume)

        assert facts.email == "john@example.com"
        assert facts.extraction_confidence > 0

    def test_missing_info_detected(self):
        """Test that missing info is detected."""
        extractor = FactExtractor()

        sparse_resume = "Some text without much info"
        facts = extractor.extract(sparse_resume)

        assert len(facts.missing_info) > 0


class TestRubricLoader:
    """Tests for rubric loading and validation."""

    def test_load_valid_rubric(self, sample_rubric):
        """Test loading a valid rubric."""
        loader = RubricLoader()
        rubric = loader.load_from_dict(sample_rubric)

        assert rubric["name"] == "Test Rubric"
        assert rubric["version"] == "1.0"

    def test_reject_rubric_without_dimensions(self):
        """Test that rubric without dimensions is rejected."""
        loader = RubricLoader()

        invalid_rubric = {
            "name": "Invalid",
            "version": "1.0",
            "tier_thresholds": {"A": 0.8, "B": 0.6, "C": 0.4},
        }

        with pytest.raises(RubricValidationError):
            loader.load_from_dict(invalid_rubric)

    def test_reject_rubric_with_wrong_weights(self):
        """Test that rubric with weights not summing to 1.0 is rejected."""
        loader = RubricLoader()

        invalid_rubric = {
            "name": "Invalid",
            "version": "1.0",
            "dimensions": {
                "experience": {"weight": 0.5},
                "skills": {"weight": 0.3},
            },
            "tier_thresholds": {"A": 0.8, "B": 0.6, "C": 0.4},
        }

        with pytest.raises(RubricValidationError):
            loader.load_from_dict(invalid_rubric)

    def test_reject_rubric_with_protected_traits(self):
        """Test that rubric with protected traits is rejected."""
        loader = RubricLoader()

        invalid_rubric = {
            "name": "Invalid",
            "version": "1.0",
            "dimensions": {
                "age": {"weight": 0.5, "description": "Age requirement"},
                "skills": {"weight": 0.5},
            },
            "tier_thresholds": {"A": 0.8, "B": 0.6, "C": 0.4},
        }

        with pytest.raises(RubricValidationError) as exc_info:
            loader.load_from_dict(invalid_rubric)

        assert "protected trait" in str(exc_info.value).lower()


class TestRubricEvaluator:
    """Tests for rubric evaluation."""

    def test_evaluate_strong_candidate(self, sample_rubric):
        """Test evaluation of a strong candidate."""
        evaluator = RubricEvaluator(sample_rubric)

        facts = {
            "total_years_experience": 7,
            "skills": ["python", "go", "kubernetes", "aws"],
            "highest_degree": "MS",
            "has_management_experience": True,
            "has_mentoring_experience": True,
            "extraction_confidence": 0.9,
            "missing_info": [],
        }

        result = evaluator.evaluate(facts)

        assert result["tier"] == "A"
        assert result["percentage"] >= 0.8
        assert result["hard_constraints_passed"]

    def test_evaluate_weak_candidate(self, sample_rubric):
        """Test evaluation of a weak candidate."""
        evaluator = RubricEvaluator(sample_rubric)

        facts = {
            "total_years_experience": 1,
            "skills": ["html", "css"],
            "highest_degree": None,
            "has_management_experience": False,
            "has_mentoring_experience": False,
            "extraction_confidence": 0.8,
            "missing_info": ["education"],
        }

        result = evaluator.evaluate(facts)

        assert result["tier"] in ("C", "REJECT")
        assert result["percentage"] < 0.65

    def test_hard_constraint_rejection(self, sample_rubric):
        """Test that hard constraint failure leads to rejection."""
        evaluator = RubricEvaluator(sample_rubric)

        facts = {
            "total_years_experience": 0.5,  # Below minimum
            "skills": ["python", "aws"],
            "highest_degree": "MS",
            "extraction_confidence": 0.9,
            "missing_info": [],
        }

        result = evaluator.evaluate(facts)

        assert result["tier"] == "REJECT"
        assert not result["hard_constraints_passed"]
        assert len(result["failed_constraints"]) > 0

    def test_low_confidence_triggers_review(self, sample_rubric):
        """Test that low confidence triggers human review."""
        evaluator = RubricEvaluator(sample_rubric)

        facts = {
            "total_years_experience": 5,
            "skills": ["python", "kubernetes"],
            "highest_degree": "BS",
            "extraction_confidence": 0.5,  # Below threshold
            "missing_info": [],
        }

        result = evaluator.evaluate(facts)

        assert result["needs_human_review"]
        assert "confidence" in str(result["review_reasons"]).lower()


class TestScoringEngine:
    """Tests for the complete scoring engine."""

    def test_score_from_text(self, sample_resume_text, sample_rubric):
        """Test scoring from resume text."""
        engine = ScoringEngine(rubric_dict=sample_rubric, mock_mode=True)

        result = engine.score_from_text(
            application_id=12345,
            resume_text=sample_resume_text,
        )

        assert result.application_id == 12345
        assert result.tier in ("A", "B", "C", "REJECT")
        assert 0 <= result.percentage <= 1
        assert 0 <= result.confidence <= 1

    def test_score_with_mock_parser(self, sample_rubric):
        """Test scoring using mock resume parser."""
        engine = ScoringEngine(rubric_dict=sample_rubric, mock_mode=True)

        result = engine.score(
            application_id=12345,
            resume_content=b"mock pdf content",
            resume_filename="resume.pdf",
        )

        # Mock parser returns synthetic resume that should score well
        assert result.tier in ("A", "B")
        assert result.extracted_facts

    def test_error_handling(self, sample_rubric):
        """Test that errors are handled gracefully."""
        engine = ScoringEngine(rubric_dict=sample_rubric, mock_mode=False)

        # Empty content should be handled
        result = engine.score(
            application_id=12345,
            resume_content=b"",
            resume_filename="empty.pdf",
        )

        assert result.needs_human_review
        assert not result.hard_constraints_passed


class TestDimensionScoring:
    """Tests for individual dimension scoring."""

    def test_experience_scoring(self, sample_rubric):
        """Test experience dimension scoring."""
        evaluator = RubricEvaluator(sample_rubric)

        # Test different experience levels
        test_cases = [
            (1, 3),   # 0-2 years
            (3, 6),   # 2-5 years
            (7, 8),   # 5-10 years
            (12, 10), # 10+ years
        ]

        for years, expected_score in test_cases:
            facts = {
                "total_years_experience": years,
                "skills": ["python"],
                "highest_degree": "BS",
                "extraction_confidence": 0.9,
                "missing_info": [],
            }

            result = evaluator.evaluate(facts)
            exp_score = result["dimension_scores"]["experience"]["score"]

            assert exp_score == expected_score, f"Expected {expected_score} for {years} years, got {exp_score}"

    def test_skills_scoring(self, sample_rubric):
        """Test skills dimension scoring."""
        evaluator = RubricEvaluator(sample_rubric)

        # Test with required + preferred skills
        facts = {
            "total_years_experience": 5,
            "skills": ["python", "kubernetes", "aws"],
            "highest_degree": "BS",
            "extraction_confidence": 0.9,
            "missing_info": [],
        }

        result = evaluator.evaluate(facts)
        skills_score = result["dimension_scores"]["skills"]["score"]

        assert skills_score >= 7  # Should score well with required + preferred
