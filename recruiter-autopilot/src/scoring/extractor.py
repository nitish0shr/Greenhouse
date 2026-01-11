"""Structured fact extraction from resume text."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExperienceEntry:
    """A single work experience entry."""

    title: str
    company: str
    start_year: int | None = None
    end_year: int | None = None
    is_current: bool = False
    duration_years: float = 0.0
    description: str = ""
    technologies: list[str] = field(default_factory=list)
    confidence: float = 0.8


@dataclass
class EducationEntry:
    """A single education entry."""

    degree: str
    institution: str
    year: int | None = None
    field_of_study: str = ""
    confidence: float = 0.8


@dataclass
class ExtractedFacts:
    """Structured facts extracted from a resume."""

    # Contact
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None

    # Experience
    total_years_experience: float = 0.0
    experiences: list[ExperienceEntry] = field(default_factory=list)
    current_title: str | None = None
    current_company: str | None = None

    # Education
    education: list[EducationEntry] = field(default_factory=list)
    highest_degree: str | None = None

    # Skills
    skills: list[str] = field(default_factory=list)
    programming_languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    databases: list[str] = field(default_factory=list)
    cloud_platforms: list[str] = field(default_factory=list)

    # Certifications
    certifications: list[str] = field(default_factory=list)

    # Metrics (from resume content)
    mentioned_metrics: list[str] = field(default_factory=list)

    # Leadership indicators
    has_management_experience: bool = False
    team_size_managed: int | None = None
    has_mentoring_experience: bool = False

    # Overall confidence
    extraction_confidence: float = 0.7

    # Missing information
    missing_info: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "email": self.email,
            "phone": self.phone,
            "location": self.location,
            "linkedin_url": self.linkedin_url,
            "github_url": self.github_url,
            "total_years_experience": self.total_years_experience,
            "experiences": [
                {
                    "title": e.title,
                    "company": e.company,
                    "start_year": e.start_year,
                    "end_year": e.end_year,
                    "is_current": e.is_current,
                    "duration_years": e.duration_years,
                    "technologies": e.technologies,
                    "confidence": e.confidence,
                }
                for e in self.experiences
            ],
            "current_title": self.current_title,
            "current_company": self.current_company,
            "education": [
                {
                    "degree": e.degree,
                    "institution": e.institution,
                    "year": e.year,
                    "field_of_study": e.field_of_study,
                    "confidence": e.confidence,
                }
                for e in self.education
            ],
            "highest_degree": self.highest_degree,
            "skills": self.skills,
            "programming_languages": self.programming_languages,
            "frameworks": self.frameworks,
            "databases": self.databases,
            "cloud_platforms": self.cloud_platforms,
            "certifications": self.certifications,
            "mentioned_metrics": self.mentioned_metrics,
            "has_management_experience": self.has_management_experience,
            "team_size_managed": self.team_size_managed,
            "has_mentoring_experience": self.has_mentoring_experience,
            "extraction_confidence": self.extraction_confidence,
            "missing_info": self.missing_info,
        }


class FactExtractor:
    """
    Extracts structured facts from resume text using pattern matching.

    This is a rule-based extractor. For production use with better accuracy,
    consider integrating with an LLM for extraction.
    """

    # Common programming languages
    PROGRAMMING_LANGUAGES = {
        "python", "java", "javascript", "typescript", "go", "golang", "rust",
        "c++", "c#", "ruby", "php", "swift", "kotlin", "scala", "r",
        "matlab", "perl", "haskell", "elixir", "clojure", "lua", "dart",
    }

    # Common frameworks
    FRAMEWORKS = {
        "react", "angular", "vue", "django", "flask", "fastapi", "spring",
        "rails", "express", "next.js", "nextjs", "nuxt", "svelte",
        "tensorflow", "pytorch", "keras", "pandas", "numpy", "scikit-learn",
        "node.js", "nodejs", ".net", "asp.net", "laravel", "symfony",
    }

    # Cloud platforms
    CLOUD_PLATFORMS = {
        "aws", "amazon web services", "gcp", "google cloud", "azure",
        "digitalocean", "heroku", "vercel", "netlify", "cloudflare",
    }

    # Databases
    DATABASES = {
        "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch",
        "cassandra", "dynamodb", "sqlite", "oracle", "sql server", "mariadb",
        "neo4j", "couchbase", "firebase", "supabase",
    }

    # Degree patterns
    DEGREE_PATTERNS = [
        (r"ph\.?d\.?", "PhD"),
        (r"doctor(?:ate)?", "PhD"),
        (r"m\.?s\.?(?:\s|$)", "MS"),
        (r"master(?:'s)?", "MS"),
        (r"m\.?b\.?a\.?", "MBA"),
        (r"b\.?s\.?(?:\s|$)", "BS"),
        (r"bachelor(?:'s)?", "BS"),
        (r"b\.?a\.?(?:\s|$)", "BA"),
    ]

    # Leadership indicators
    LEADERSHIP_KEYWORDS = {
        "led", "managed", "directed", "oversaw", "supervised",
        "mentored", "coached", "guided", "trained",
    }

    def __init__(self):
        self.current_year = datetime.now().year

    def extract(self, resume_text: str) -> ExtractedFacts:
        """
        Extract structured facts from resume text.

        Args:
            resume_text: Plain text resume content

        Returns:
            ExtractedFacts with extracted information
        """
        text_lower = resume_text.lower()
        facts = ExtractedFacts()

        # Extract contact info
        facts.email = self._extract_email(resume_text)
        facts.phone = self._extract_phone(resume_text)
        facts.location = self._extract_location(resume_text)
        facts.linkedin_url = self._extract_linkedin(resume_text)
        facts.github_url = self._extract_github(resume_text)

        # Extract skills
        facts.programming_languages = self._extract_from_set(
            text_lower, self.PROGRAMMING_LANGUAGES
        )
        facts.frameworks = self._extract_from_set(text_lower, self.FRAMEWORKS)
        facts.cloud_platforms = self._extract_from_set(text_lower, self.CLOUD_PLATFORMS)
        facts.databases = self._extract_from_set(text_lower, self.DATABASES)

        # Combine all skills
        facts.skills = list(set(
            facts.programming_languages +
            facts.frameworks +
            facts.cloud_platforms +
            facts.databases
        ))

        # Extract experience
        facts.experiences = self._extract_experiences(resume_text)
        facts.total_years_experience = self._calculate_total_experience(facts.experiences)

        if facts.experiences:
            current = next((e for e in facts.experiences if e.is_current), None)
            if current:
                facts.current_title = current.title
                facts.current_company = current.company
            else:
                # Assume first is most recent
                facts.current_title = facts.experiences[0].title
                facts.current_company = facts.experiences[0].company

        # Extract education
        facts.education = self._extract_education(resume_text)
        if facts.education:
            # Determine highest degree
            degree_order = {"PhD": 4, "MBA": 3, "MS": 3, "MA": 3, "BS": 2, "BA": 2}
            sorted_edu = sorted(
                facts.education,
                key=lambda e: degree_order.get(e.degree, 0),
                reverse=True,
            )
            facts.highest_degree = sorted_edu[0].degree

        # Extract certifications
        facts.certifications = self._extract_certifications(resume_text)

        # Extract metrics
        facts.mentioned_metrics = self._extract_metrics(resume_text)

        # Check leadership
        facts.has_management_experience = self._check_management(text_lower)
        facts.has_mentoring_experience = any(
            kw in text_lower for kw in ["mentor", "coach", "train"]
        )
        facts.team_size_managed = self._extract_team_size(text_lower)

        # Identify missing info
        facts.missing_info = self._identify_missing_info(facts)

        # Calculate confidence
        facts.extraction_confidence = self._calculate_confidence(facts)

        logger.debug(
            "Facts extracted",
            experience_years=facts.total_years_experience,
            skills_count=len(facts.skills),
            confidence=facts.extraction_confidence,
        )

        return facts

    def _extract_email(self, text: str) -> str | None:
        """Extract email address."""
        pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        match = re.search(pattern, text)
        return match.group(0) if match else None

    def _extract_phone(self, text: str) -> str | None:
        """Extract phone number."""
        patterns = [
            r"\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
            r"\d{3}[-.\s]?\d{3}[-.\s]?\d{4}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None

    def _extract_location(self, text: str) -> str | None:
        """Extract location (city, state/country)."""
        # Common patterns: "San Francisco, CA" or "New York, NY"
        pattern = r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)*),\s*([A-Z]{2}|[A-Z][a-z]+)"
        match = re.search(pattern, text)
        return match.group(0) if match else None

    def _extract_linkedin(self, text: str) -> str | None:
        """Extract LinkedIn URL."""
        pattern = r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+"
        match = re.search(pattern, text.lower())
        return match.group(0) if match else None

    def _extract_github(self, text: str) -> str | None:
        """Extract GitHub URL."""
        pattern = r"(?:https?://)?(?:www\.)?github\.com/[\w-]+"
        match = re.search(pattern, text.lower())
        return match.group(0) if match else None

    def _extract_from_set(self, text: str, items: set[str]) -> list[str]:
        """Extract items from a predefined set."""
        found = []
        for item in items:
            # Word boundary matching
            pattern = rf"\b{re.escape(item)}\b"
            if re.search(pattern, text, re.IGNORECASE):
                found.append(item.title() if len(item) > 3 else item.upper())
        return found

    def _extract_experiences(self, text: str) -> list[ExperienceEntry]:
        """Extract work experiences."""
        experiences = []

        # Pattern for job entries: Title | Company | Date range
        # This is simplified - production would need more sophisticated parsing
        lines = text.split("\n")

        # Look for patterns like "Senior Engineer | Company | 2020 - Present"
        for i, line in enumerate(lines):
            # Check for year patterns
            year_pattern = r"(20\d{2}|19\d{2})\s*[-–]\s*(20\d{2}|19\d{2}|[Pp]resent|[Cc]urrent)"
            year_match = re.search(year_pattern, line)

            if year_match:
                start_year = int(year_match.group(1))
                end_str = year_match.group(2).lower()
                is_current = end_str in ("present", "current")
                end_year = self.current_year if is_current else int(year_match.group(2))

                # Try to extract title and company from the line
                # Remove the date part
                clean_line = re.sub(year_pattern, "", line).strip()

                # Split by common separators
                parts = re.split(r"\s*[|•·]\s*", clean_line)
                parts = [p.strip() for p in parts if p.strip()]

                if len(parts) >= 2:
                    title = parts[0]
                    company = parts[1]
                elif len(parts) == 1:
                    title = parts[0]
                    company = "Unknown"
                else:
                    continue

                # Get description from following lines
                description_lines = []
                for j in range(i + 1, min(i + 10, len(lines))):
                    next_line = lines[j].strip()
                    if next_line.startswith("-") or next_line.startswith("•"):
                        description_lines.append(next_line)
                    elif re.search(year_pattern, next_line):
                        break

                # Extract technologies from description
                description = " ".join(description_lines)
                technologies = []
                for tech_set in [self.PROGRAMMING_LANGUAGES, self.FRAMEWORKS,
                                 self.DATABASES, self.CLOUD_PLATFORMS]:
                    technologies.extend(self._extract_from_set(description.lower(), tech_set))

                experiences.append(ExperienceEntry(
                    title=title,
                    company=company,
                    start_year=start_year,
                    end_year=end_year,
                    is_current=is_current,
                    duration_years=end_year - start_year,
                    description=description[:500],  # Limit size
                    technologies=list(set(technologies)),
                ))

        return experiences

    def _calculate_total_experience(self, experiences: list[ExperienceEntry]) -> float:
        """Calculate total years of experience."""
        if not experiences:
            return 0.0

        # Sum up durations (this is simplified - doesn't account for overlaps)
        total = sum(e.duration_years for e in experiences)

        # Also check for explicit mentions
        return max(total, 0.0)

    def _extract_education(self, text: str) -> list[EducationEntry]:
        """Extract education entries."""
        education = []

        for pattern, degree_name in self.DEGREE_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                # Try to find year near the match
                context = text[max(0, match.start() - 50):match.end() + 100]
                year_match = re.search(r"20\d{2}|19\d{2}", context)
                year = int(year_match.group(0)) if year_match else None

                # Try to find institution
                # Look for common university indicators
                institution = "Unknown"
                inst_pattern = r"(?:University|College|Institute|School)\s+(?:of\s+)?[\w\s]+"
                inst_match = re.search(inst_pattern, context, re.IGNORECASE)
                if inst_match:
                    institution = inst_match.group(0).strip()

                education.append(EducationEntry(
                    degree=degree_name,
                    institution=institution,
                    year=year,
                ))

        # Deduplicate by degree
        seen = set()
        unique = []
        for e in education:
            if e.degree not in seen:
                seen.add(e.degree)
                unique.append(e)

        return unique

    def _extract_certifications(self, text: str) -> list[str]:
        """Extract certifications."""
        certs = []

        cert_patterns = [
            r"AWS\s+(?:Certified\s+)?[\w\s]+(?:Professional|Associate)",
            r"Google\s+Cloud\s+(?:Professional\s+)?[\w\s]+",
            r"Azure\s+[\w\s]+(?:Expert|Associate)",
            r"PMP|CISSP|CISM|CCNA|CCNP",
            r"Certified\s+(?:Kubernetes|Scrum|Agile)[\w\s]*",
        ]

        for pattern in cert_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            certs.extend(matches)

        return list(set(certs))

    def _extract_metrics(self, text: str) -> list[str]:
        """Extract quantitative metrics mentioned in resume."""
        metrics = []

        # Patterns for metrics
        patterns = [
            r"\d+[%+]\s*(?:increase|decrease|improvement|reduction)",
            r"\d+[KkMm]?\+?\s*(?:users|requests|customers|clients)",
            r"\$\d+[KkMmBb]?\+?\s*(?:revenue|savings|budget)",
            r"\d+x\s*(?:faster|improvement|increase)",
            r"(?:reduced|improved|increased)[\w\s]*by\s*\d+%",
            r"\d+\s*(?:team members?|engineers?|developers?)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            metrics.extend(matches[:5])  # Limit per pattern

        return metrics[:10]  # Overall limit

    def _check_management(self, text: str) -> bool:
        """Check for management experience."""
        management_patterns = [
            r"managed\s+(?:a\s+)?team",
            r"led\s+(?:a\s+)?team",
            r"supervised\s+\d+",
            r"direct\s+reports?",
            r"engineering\s+manager",
            r"team\s+lead",
            r"tech\s+lead",
        ]

        for pattern in management_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _extract_team_size(self, text: str) -> int | None:
        """Extract team size managed."""
        patterns = [
            r"(?:managed|led|supervised)\s+(?:a\s+)?(?:team\s+of\s+)?(\d+)",
            r"(\d+)\s+(?:direct\s+)?reports?",
            r"team\s+of\s+(\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    def _identify_missing_info(self, facts: ExtractedFacts) -> list[str]:
        """Identify important missing information."""
        missing = []

        if not facts.email:
            missing.append("email")
        if facts.total_years_experience == 0:
            missing.append("work_experience")
        if not facts.education:
            missing.append("education")
        if not facts.skills:
            missing.append("skills")

        return missing

    def _calculate_confidence(self, facts: ExtractedFacts) -> float:
        """Calculate overall extraction confidence."""
        score = 0.5  # Base score

        # Boost for found information
        if facts.email:
            score += 0.1
        if facts.experiences:
            score += 0.15
        if facts.education:
            score += 0.1
        if facts.skills:
            score += 0.1
        if not facts.missing_info:
            score += 0.05

        return min(score, 1.0)
