# =============================================================================
# Scoring Engine Tests
# =============================================================================

import pytest
import tempfile
import yaml
from pathlib import Path

from app.services.scoring_engine import ScoringEngine
from app.schemas.scoring import validate_scoring_output


class TestScoringEngine:
    """Test scoring engine functionality."""
    
    @pytest.fixture
    def sample_rubric(self):
        """Create a sample rubric for testing."""
        return {
            "dimensions": [
                {
                    "name": "technical_skills",
                    "weight": 40,
                    "scoring_method": "keyword_match",
                    "criteria": [
                        {
                            "keywords": ["python", "django", "fastapi"],
                            "required": True,
                        },
                        {
                            "keywords": ["postgresql", "sql"],
                            "required": False,
                        },
                    ],
                },
                {
                    "name": "experience_years",
                    "weight": 30,
                    "scoring_method": "numeric_range",
                    "minimum": 3,
                    "ideal": 5,
                },
            ],
            "hard_constraints": [
                {
                    "type": "years_experience",
                    "minimum": 3,
                },
            ],
        }
    
    @pytest.fixture
    def rubric_file(self, sample_rubric, tmp_path):
        """Create a temporary rubric file."""
        rubric_path = tmp_path / "rubric.yaml"
        with open(rubric_path, "w") as f:
            yaml.dump(sample_rubric, f)
        return str(rubric_path)
    
    def test_score_with_keyword_match(self, rubric_file, sample_resume_text):
        """Test scoring with keyword matching."""
        engine = ScoringEngine(rubric_path=rubric_file)
        result = engine.score(sample_resume_text)
        
        # Validate output schema
        validate_scoring_output(result)
        
        # Check structure
        assert "hard_reject" in result
        assert "dimension_scores" in result
        assert "weighted_score" in result
        assert "tier" in result
        assert "confidence" in result
    
    def test_score_hard_reject_insufficient_experience(self, rubric_file):
        """Test hard reject for insufficient experience."""
        resume_text = "John Doe\n1 year of experience"
        engine = ScoringEngine(rubric_path=rubric_file)
        result = engine.score(resume_text)
        
        assert result["hard_reject"] is True
        assert len(result["hard_reject_reasons"]) > 0
        assert result["tier"] == "REJECT"
    
    def test_score_output_schema(self, rubric_file, sample_resume_text):
        """Test that output conforms to strict schema."""
        engine = ScoringEngine(rubric_path=rubric_file)
        result = engine.score(sample_resume_text)
        
        # Should not raise exception
        validate_scoring_output(result)
        
        # Check required fields
        assert isinstance(result["hard_reject"], bool)
        assert isinstance(result["hard_reject_reasons"], list)
        assert isinstance(result["dimension_scores"], dict)
        assert isinstance(result["weighted_score"], int)
        assert result["weighted_score"] >= 0 and result["weighted_score"] <= 100
        assert result["tier"] in ["A", "B", "C", "REJECT"]
        assert isinstance(result["confidence"], float)
        assert result["confidence"] >= 0.0 and result["confidence"] <= 1.0
    
    def test_score_with_missing_rubric(self, sample_resume_text):
        """Test scoring with missing rubric file (uses defaults)."""
        engine = ScoringEngine(rubric_path="/nonexistent/path.yaml")
        result = engine.score(sample_resume_text)
        
        # Should still produce valid output
        validate_scoring_output(result)
        assert "rubric_version" in result
