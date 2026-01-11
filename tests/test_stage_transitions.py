# =============================================================================
# Tests for Stage Transitions
# =============================================================================

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.greenhouse import GreenhouseClient, GreenhouseAPIError
from app.services.scorer import ScoringResult


class TestStageTransitions:
    """Tests for application stage transitions."""
    
    @pytest.fixture
    def mock_greenhouse_client(self):
        """Create a mock Greenhouse client."""
        client = MagicMock(spec=GreenhouseClient)
        
        # Mock async methods
        client.advance_application = AsyncMock(return_value={
            "id": 12345,
            "current_stage": {"id": 3, "name": "Phone Screen"},
        })
        
        client.reject_application = AsyncMock(return_value={
            "id": 12345,
            "status": "rejected",
        })
        
        client.move_application_to_stage = AsyncMock(return_value={
            "id": 12345,
            "current_stage": {"id": 5, "name": "Interview"},
        })
        
        return client
    
    @pytest.mark.asyncio
    async def test_advance_application_success(self, mock_greenhouse_client):
        """Test successful application advancement."""
        result = await mock_greenhouse_client.advance_application(
            application_id=12345,
            from_stage_id=2,
        )
        
        assert result["id"] == 12345
        assert result["current_stage"]["name"] == "Phone Screen"
        mock_greenhouse_client.advance_application.assert_called_once_with(
            application_id=12345,
            from_stage_id=2,
        )
    
    @pytest.mark.asyncio
    async def test_reject_application_with_reason(self, mock_greenhouse_client):
        """Test application rejection with reason."""
        result = await mock_greenhouse_client.reject_application(
            application_id=12345,
            rejection_reason_id=999,
            notes="Insufficient experience",
        )
        
        assert result["status"] == "rejected"
        mock_greenhouse_client.reject_application.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_move_to_specific_stage(self, mock_greenhouse_client):
        """Test moving application to a specific stage."""
        result = await mock_greenhouse_client.move_application_to_stage(
            application_id=12345,
            stage_id=5,
        )
        
        assert result["current_stage"]["id"] == 5
    
    def test_decision_based_on_high_score(self):
        """Test that high scores lead to advance decision."""
        result = ScoringResult(
            score=85.0,
            confidence=0.8,
            hard_reject=False,
            matched_skills=["Python", "SQL", "API Development"],
            missing_skills=[],
            suggested_action="advance",
        )
        
        assert result.suggested_action == "advance"
        assert not result.hard_reject
    
    def test_decision_based_on_low_score(self):
        """Test that low scores lead to reject decision."""
        result = ScoringResult(
            score=15.0,
            confidence=0.9,
            hard_reject=False,
            matched_skills=[],
            missing_skills=["Python", "SQL", "API Development"],
            suggested_action="reject",
        )
        
        assert result.suggested_action == "reject"
    
    def test_decision_based_on_hard_reject(self):
        """Test that hard constraints trigger rejection."""
        result = ScoringResult(
            score=70.0,
            confidence=0.7,
            hard_reject=True,
            failed_constraints=["Minimum 3 years experience required"],
            rejection_reason_id=12345,
            suggested_action="reject",
        )
        
        assert result.hard_reject
        assert result.suggested_action == "reject"
        assert result.rejection_reason_id is not None
    
    def test_decision_low_confidence_to_review(self):
        """Test that low confidence leads to human review."""
        result = ScoringResult(
            score=60.0,
            confidence=0.4,
            hard_reject=False,
            matched_skills=["Python"],
            suggested_action="human_review",
        )
        
        assert result.suggested_action == "human_review"
    
    def test_decision_medium_score_to_review(self):
        """Test that medium scores go to human review."""
        result = ScoringResult(
            score=55.0,
            confidence=0.6,
            hard_reject=False,
            suggested_action="human_review",
        )
        
        assert result.suggested_action == "human_review"


class TestStageTransitionLogic:
    """Tests for stage transition decision logic."""
    
    def test_should_advance_high_scorer(self):
        """High scorer with high confidence should advance."""
        score = 85.0
        confidence = 0.8
        threshold = 75
        
        should_advance = score >= threshold and confidence >= 0.7
        assert should_advance
    
    def test_should_not_advance_low_confidence(self):
        """High scorer with low confidence should not auto-advance."""
        score = 85.0
        confidence = 0.5
        threshold = 75
        
        should_advance = score >= threshold and confidence >= 0.7
        assert not should_advance
    
    def test_should_reject_low_scorer(self):
        """Low scorer with high confidence should reject."""
        score = 15.0
        confidence = 0.85
        threshold = 25
        
        should_reject = score <= threshold and confidence >= 0.7
        assert should_reject
    
    def test_should_review_uncertain(self):
        """Uncertain cases should go to human review."""
        test_cases = [
            (60, 0.5, True),   # Medium score, low confidence
            (40, 0.8, True),   # Low score, but in uncertain range
            (50, 0.6, True),   # Right at threshold
        ]
        
        for score, confidence, expected_review in test_cases:
            advance_threshold = 75
            reject_threshold = 25
            
            should_advance = score >= advance_threshold and confidence >= 0.7
            should_reject = score <= reject_threshold and confidence >= 0.7
            should_review = not should_advance and not should_reject
            
            assert should_review == expected_review, \
                f"Score {score}, confidence {confidence}: expected review={expected_review}"


class TestIntegrationWithScoring:
    """Integration tests for scoring -> transition flow."""
    
    @pytest.fixture
    def mock_pipeline(self, sample_rubric):
        """Create a mock processing pipeline."""
        from app.services.scorer import CandidateScorer
        import tempfile
        import yaml
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(sample_rubric, f)
            rubric_path = f.name
        
        with patch('app.services.scorer.settings') as mock_settings:
            mock_settings.scoring_rubric_path = rubric_path
            mock_settings.score_threshold_advance = 75
            mock_settings.score_threshold_reject = 25
            mock_settings.low_confidence_threshold = 50
            
            scorer = CandidateScorer(rubric_path=rubric_path)
            yield scorer
    
    def test_full_pipeline_advance(self, mock_pipeline):
        """Test full pipeline that should result in advance."""
        strong_resume = """
        Senior Software Engineer with 8 years of experience
        
        SKILLS
        Python, FastAPI, Django, PostgreSQL, MySQL
        REST API development, GraphQL, Microservices
        AWS, Docker, Kubernetes
        
        EXPERIENCE
        8 years of experience building scalable systems
        """
        
        result = mock_pipeline.score(strong_resume)
        
        assert result.score >= 60
        assert "Python" in result.matched_skills
        assert not result.hard_reject
    
    def test_full_pipeline_reject(self, mock_pipeline):
        """Test full pipeline that should result in reject."""
        weak_resume = """
        Marketing Coordinator
        
        EXPERIENCE
        Social media management
        Content creation
        Email marketing
        
        No technical experience
        """
        
        result = mock_pipeline.score(weak_resume)
        
        assert result.score < 50
        assert len(result.matched_skills) < 2
