# =============================================================================
# Mock Greenhouse Client - For Testing and Development
# =============================================================================

import logging
from typing import Optional, Any
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)


class MockGreenhouseClient:
    """
    Mock Greenhouse client for testing and mock mode.
    
    Provides the same interface as GreenhouseClient but returns
    deterministic mock data instead of making real API calls.
    """
    
    def __init__(self):
        """Initialize mock client."""
        self.candidates = {}
        self.applications = {}
        self.notes = []
        self.tags = []
        self._setup_mock_data()
    
    def _setup_mock_data(self):
        """Setup initial mock data."""
        # Create a sample candidate
        self.candidates[12345] = {
            "id": 12345,
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@example.com",
            "attachments": [
                {
                    "type": "resume",
                    "filename": "John_Doe_Resume.pdf",
                    "url": "https://mock-greenhouse.com/attachments/12345/resume.pdf",
                },
            ],
            "tags": [],
            "custom_fields": {},
        }
        
        # Create a sample application
        self.applications[67890] = {
            "id": 67890,
            "candidate_id": 12345,
            "job_id": 100,
            "job": {"id": 100, "name": "Software Engineer"},
            "current_stage": {"id": 1, "name": "Application Review"},
            "source": {"id": 1, "name": "Website"},
            "rejected_at": None,
            "rejection_reason": None,
        }
    
    async def get_candidate(self, candidate_id: int) -> dict:
        """Get candidate (mock)."""
        if candidate_id in self.candidates:
            return self.candidates[candidate_id]
        raise Exception(f"Candidate not found: {candidate_id}")
    
    async def get_application(self, application_id: int) -> dict:
        """Get application (mock)."""
        if application_id in self.applications:
            return self.applications[application_id]
        raise Exception(f"Application not found: {application_id}")
    
    async def download_attachment(self, url: str) -> bytes:
        """Download attachment (mock)."""
        # Return mock resume content
        return b"""John Doe
Software Engineer

Experience:
- 5 years of Python development using Django and FastAPI
- Strong background in PostgreSQL and SQL
- Experience with AWS cloud platforms
- CI/CD pipelines with GitHub Actions

Education:
- Bachelor of Science in Computer Science
"""
    
    async def add_note_to_candidate(
        self,
        candidate_id: int,
        note: str,
        visibility: str = "public",
    ) -> dict:
        """Add note (mock)."""
        note_id = len(self.notes) + 1
        note_data = {
            "id": note_id,
            "body": note,
            "visibility": visibility,
            "created_at": datetime.utcnow().isoformat(),
        }
        self.notes.append(note_data)
        return note_data
    
    async def add_tag(self, candidate_id: int, tag: str) -> dict:
        """Add tag (mock)."""
        tag_data = {
            "id": len(self.tags) + 1,
            "name": tag,
            "candidate_id": candidate_id,
        }
        self.tags.append(tag_data)
        
        # Add to candidate
        if candidate_id in self.candidates:
            if "tags" not in self.candidates[candidate_id]:
                self.candidates[candidate_id]["tags"] = []
            self.candidates[candidate_id]["tags"].append(tag)
        
        return tag_data
    
    async def move_application_stage(
        self,
        application_id: int,
        stage_id: int,
    ) -> dict:
        """Move application stage (mock)."""
        if application_id in self.applications:
            self.applications[application_id]["current_stage"] = {
                "id": stage_id,
                "name": f"Stage {stage_id}",
            }
            return self.applications[application_id]
        raise Exception(f"Application not found: {application_id}")
    
    async def reject_application(
        self,
        application_id: int,
        rejection_reason_id: Optional[int] = None,
    ) -> dict:
        """Reject application (mock)."""
        if application_id in self.applications:
            self.applications[application_id]["rejected_at"] = datetime.utcnow().isoformat()
            self.applications[application_id]["rejection_reason"] = {
                "id": rejection_reason_id,
                "name": "Automated Rejection",
            }
            return self.applications[application_id]
        raise Exception(f"Application not found: {application_id}")
