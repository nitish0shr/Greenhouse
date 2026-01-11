#!/usr/bin/env python3
"""
Demo script to simulate webhook processing for 10 sample applicants.

This script demonstrates the full pipeline:
1. Simulates Greenhouse webhooks for new applications
2. Processes each application (parse, score, action)
3. Shows scoring results and actions taken

Run with: python scripts/demo.py
"""

import asyncio
import json
import random
from datetime import datetime, timedelta

# Add parent directory to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scoring.engine import ScoringEngine, format_scoring_note
from src.scoring.parser import MockResumeParser
from src.utils.logging import setup_logging, get_logger

# Sample candidate profiles for demo
SAMPLE_CANDIDATES = [
    {
        "id": 1001,
        "name": "Alice Chen",
        "email": "alice.chen@email.com",
        "title": "Senior Software Engineer",
        "resume": """
ALICE CHEN
Senior Software Engineer
alice.chen@email.com | (555) 111-2222 | San Francisco, CA

EXPERIENCE
Senior Software Engineer | Google | 2019 - Present
- Led team of 6 engineers building distributed data pipeline
- Designed microservices architecture processing 50M events/day
- Technologies: Python, Go, Kubernetes, BigQuery, GCP

Software Engineer | Stripe | 2016 - 2019
- Built payment processing APIs handling $10B+ transactions
- Improved system latency by 40% through optimization
- Technologies: Python, Ruby, PostgreSQL, AWS

EDUCATION
M.S. Computer Science | Stanford University | 2016
B.S. Computer Science | MIT | 2014

SKILLS
Python, Go, Java, Kubernetes, AWS, GCP, PostgreSQL, Redis
""",
    },
    {
        "id": 1002,
        "name": "Bob Johnson",
        "email": "bob.j@email.com",
        "title": "Software Engineer",
        "resume": """
BOB JOHNSON
Software Engineer
bob.j@email.com | New York, NY

EXPERIENCE
Software Engineer | Startup Inc | 2021 - Present
- Developed REST APIs using Python and FastAPI
- Implemented CI/CD pipelines with GitHub Actions
- Technologies: Python, Docker, PostgreSQL

Junior Developer | Web Agency | 2019 - 2021
- Built websites using React and Node.js
- Technologies: JavaScript, React, Node.js

EDUCATION
B.S. Computer Science | State University | 2019

SKILLS
Python, JavaScript, React, Docker, PostgreSQL
""",
    },
    {
        "id": 1003,
        "name": "Carol Williams",
        "email": "carol.w@email.com",
        "title": "Staff Engineer",
        "resume": """
CAROL WILLIAMS
Staff Engineer
carol.w@email.com | (555) 333-4444 | Seattle, WA

EXPERIENCE
Staff Engineer | Amazon | 2018 - Present
- Architected services handling 1M+ requests per second
- Managed team of 8 engineers across 3 projects
- Mentored 10+ engineers, 4 promoted to senior
- Technologies: Java, Python, AWS, DynamoDB

Senior Engineer | Microsoft | 2014 - 2018
- Led Azure Kubernetes development team
- Filed 5 patents in distributed systems
- Technologies: C#, Go, Kubernetes, Azure

Software Engineer | Facebook | 2011 - 2014
- Built core infrastructure for News Feed
- Technologies: PHP, Python, MySQL

EDUCATION
Ph.D. Computer Science | UC Berkeley | 2011
B.S. Computer Science | Carnegie Mellon | 2006

CERTIFICATIONS
AWS Solutions Architect Professional
Google Cloud Professional Data Engineer

SKILLS
Java, Python, Go, C#, AWS, Azure, GCP, Kubernetes, System Design
""",
    },
    {
        "id": 1004,
        "name": "David Lee",
        "email": "david.lee@email.com",
        "title": "Junior Developer",
        "resume": """
DAVID LEE
Junior Developer
david.lee@email.com | Austin, TX

EXPERIENCE
Intern | Tech Company | Summer 2023
- Assisted with bug fixes and testing
- Technologies: JavaScript, HTML, CSS

EDUCATION
B.S. Computer Science | University of Texas | 2023 (Expected)

SKILLS
JavaScript, HTML, CSS, Python (basic)
""",
    },
    {
        "id": 1005,
        "name": "Eva Martinez",
        "email": "eva.m@email.com",
        "title": "Senior Backend Engineer",
        "resume": """
EVA MARTINEZ
Senior Backend Engineer
eva.m@email.com | (555) 555-6666 | Denver, CO

EXPERIENCE
Senior Backend Engineer | Uber | 2020 - Present
- Built real-time pricing engine serving 10M+ rides/day
- Reduced infrastructure costs by 30% through optimization
- Technologies: Python, Go, Apache Kafka, Redis

Backend Engineer | Lyft | 2017 - 2020
- Developed driver matching algorithms
- Technologies: Python, PostgreSQL, AWS

Software Developer | Consulting Firm | 2015 - 2017
- Built enterprise applications for Fortune 500 clients
- Technologies: Java, Spring, Oracle

EDUCATION
M.S. Computer Science | CU Boulder | 2015
B.S. Software Engineering | UCLA | 2013

SKILLS
Python, Go, Java, Kafka, Redis, AWS, PostgreSQL, System Design
""",
    },
    {
        "id": 1006,
        "name": "Frank Brown",
        "email": "frank.b@email.com",
        "title": "DevOps Engineer",
        "resume": """
FRANK BROWN
DevOps Engineer
frank.b@email.com | Chicago, IL

EXPERIENCE
DevOps Engineer | Fintech Corp | 2020 - Present
- Managed Kubernetes clusters with 500+ pods
- Implemented infrastructure as code with Terraform
- Technologies: Kubernetes, Docker, Terraform, AWS

SRE | E-commerce Inc | 2018 - 2020
- Maintained 99.99% uptime for critical services
- Technologies: Python, Ansible, AWS

EDUCATION
B.S. Information Technology | DePaul University | 2018

CERTIFICATIONS
Certified Kubernetes Administrator
AWS DevOps Professional

SKILLS
Kubernetes, Docker, Terraform, AWS, Python, CI/CD, Linux
""",
    },
    {
        "id": 1007,
        "name": "Grace Kim",
        "email": "grace.kim@email.com",
        "title": "Full Stack Developer",
        "resume": """
GRACE KIM
Full Stack Developer
grace.kim@email.com | Portland, OR

EXPERIENCE
Full Stack Developer | SaaS Startup | 2021 - Present
- Built customer portal with React and Node.js
- Developed REST APIs handling 100K users
- Technologies: React, Node.js, MongoDB, AWS

Web Developer | Agency | 2019 - 2021
- Created responsive websites for 30+ clients
- Technologies: JavaScript, PHP, MySQL

EDUCATION
B.A. Computer Science | Oregon State | 2019

SKILLS
JavaScript, React, Node.js, Python, MongoDB, PostgreSQL, AWS
""",
    },
    {
        "id": 1008,
        "name": "Henry Wang",
        "email": "henry.w@email.com",
        "title": "ML Engineer",
        "resume": """
HENRY WANG
Machine Learning Engineer
henry.w@email.com | (555) 888-9999 | Boston, MA

EXPERIENCE
ML Engineer | AI Startup | 2020 - Present
- Developed NLP models for document classification
- Deployed ML pipelines serving 1M predictions/day
- Technologies: Python, TensorFlow, PyTorch, AWS

Data Scientist | Research Lab | 2018 - 2020
- Published 3 papers on deep learning
- Technologies: Python, scikit-learn, Keras

EDUCATION
Ph.D. Machine Learning | MIT | 2018
M.S. Statistics | Harvard | 2014
B.S. Mathematics | Tsinghua University | 2012

SKILLS
Python, TensorFlow, PyTorch, scikit-learn, AWS, MLOps
""",
    },
    {
        "id": 1009,
        "name": "Iris Patel",
        "email": "iris.p@email.com",
        "title": "Software Engineer",
        "resume": """
IRIS PATEL
Software Engineer
iris.p@email.com | Atlanta, GA

EXPERIENCE
Software Engineer | Healthcare Tech | 2022 - Present
- Built HIPAA-compliant patient portal
- Developed API integrations with EMR systems
- Technologies: Python, Django, PostgreSQL

Developer Bootcamp Graduate | 2022

EDUCATION
Coding Bootcamp | General Assembly | 2022
B.A. Biology | Emory University | 2020

SKILLS
Python, Django, JavaScript, React, PostgreSQL
""",
    },
    {
        "id": 1010,
        "name": "Jack Thompson",
        "email": "jack.t@email.com",
        "title": "Engineering Manager",
        "resume": """
JACK THOMPSON
Engineering Manager
jack.t@email.com | (555) 000-1111 | Los Angeles, CA

EXPERIENCE
Engineering Manager | Tech Giant | 2019 - Present
- Managed team of 15 engineers across 4 projects
- Delivered 3 major product launches
- Grew team from 5 to 15 engineers

Senior Engineer | Previous Company | 2015 - 2019
- Led architecture redesign reducing costs by 50%
- Mentored 8 junior engineers
- Technologies: Java, Python, AWS

Software Engineer | First Job | 2012 - 2015
- Built core backend services
- Technologies: Java, MySQL

EDUCATION
M.S. Computer Science | USC | 2012
B.S. Computer Science | UCLA | 2010

SKILLS
Java, Python, AWS, System Design, Team Leadership, Agile
""",
    },
]


def setup_demo():
    """Setup logging and return scoring engine."""
    setup_logging("INFO", json_logs=False)
    return ScoringEngine(mock_mode=True)


def simulate_webhook(candidate: dict, job_id: int = 99999) -> dict:
    """Simulate a Greenhouse webhook payload."""
    return {
        "action": "new_candidate_application",
        "payload": {
            "application": {
                "id": candidate["id"] * 10,
                "candidate_id": candidate["id"],
                "applied_at": datetime.utcnow().isoformat() + "Z",
                "source": {"public_name": random.choice(["LinkedIn", "Indeed", "Referral", "Direct"])},
                "current_stage": {"id": 1001, "name": "Application Review"},
                "jobs": [{"id": job_id, "name": "Software Engineer"}],
                "attachments": [
                    {
                        "filename": "resume.pdf",
                        "url": f"https://example.com/resumes/{candidate['id']}.pdf",
                        "type": "resume",
                    }
                ],
            },
        },
    }


def process_candidate(engine: ScoringEngine, candidate: dict, logger) -> dict:
    """Process a single candidate through the scoring pipeline."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {candidate['name']} ({candidate['title']})")
    logger.info(f"{'='*60}")

    # Simulate webhook
    webhook = simulate_webhook(candidate)
    logger.info(f"Webhook received: application_id={webhook['payload']['application']['id']}")

    # Score the candidate
    result = engine.score_from_text(
        application_id=webhook["payload"]["application"]["id"],
        resume_text=candidate["resume"],
    )

    # Determine action
    if result.tier == "REJECT":
        action = "AUTO-REJECT" if result.hard_constraints_passed is False else "MANUAL REVIEW FOR REJECTION"
    elif result.tier == "A":
        action = "ADVANCE TO PHONE SCREEN"
    elif result.tier == "B":
        action = "ADVANCE TO REVIEW"
    else:
        action = "HOLD FOR REVIEW"

    # Log results
    logger.info(f"\nScoring Results:")
    logger.info(f"  Tier: {result.tier}")
    logger.info(f"  Score: {result.percentage:.0%}")
    logger.info(f"  Confidence: {result.confidence:.0%}")

    logger.info(f"\nDimension Scores:")
    for dim, data in result.dimension_scores.items():
        logger.info(f"  {dim}: {data['score']:.1f}/{data['max_score']:.0f} - {data.get('evidence', 'N/A')}")

    if result.failed_constraints:
        logger.info(f"\nFailed Constraints:")
        for constraint in result.failed_constraints:
            logger.info(f"  - {constraint['message']}")

    if result.needs_human_review:
        logger.info(f"\nNeeds Human Review:")
        for reason in result.review_reasons:
            logger.info(f"  - {reason}")

    logger.info(f"\nRecommendation: {result.recommendation}")
    logger.info(f"Action: {action}")

    # Simulate Greenhouse writebacks
    logger.info(f"\nSimulated Greenhouse Writebacks:")
    logger.info(f"  - Added tag: tier:{result.tier}")
    if result.needs_human_review:
        logger.info(f"  - Added tag: needs-review")
    logger.info(f"  - Created scoring note")

    if result.tier == "A":
        logger.info(f"  - Simulated: Send interview invite email")
    elif result.tier == "REJECT" and not result.hard_constraints_passed:
        logger.info(f"  - Simulated: Send rejection email")

    return {
        "candidate": candidate["name"],
        "tier": result.tier,
        "score": result.percentage,
        "action": action,
        "needs_review": result.needs_human_review,
    }


def print_summary(results: list, logger):
    """Print summary of all processed candidates."""
    logger.info(f"\n{'='*60}")
    logger.info("PROCESSING SUMMARY")
    logger.info(f"{'='*60}")

    # Group by tier
    by_tier = {"A": [], "B": [], "C": [], "REJECT": []}
    for r in results:
        by_tier[r["tier"]].append(r)

    logger.info(f"\nTotal Processed: {len(results)}")
    logger.info(f"  A-Tier (Advance): {len(by_tier['A'])}")
    logger.info(f"  B-Tier (Review):  {len(by_tier['B'])}")
    logger.info(f"  C-Tier (Hold):    {len(by_tier['C'])}")
    logger.info(f"  Rejected:         {len(by_tier['REJECT'])}")

    needs_review = sum(1 for r in results if r["needs_review"])
    logger.info(f"\nNeeds Human Review: {needs_review}")

    logger.info(f"\nDetailed Results:")
    logger.info(f"{'Candidate':<25} {'Tier':<8} {'Score':<8} {'Action':<30}")
    logger.info(f"{'-'*25} {'-'*8} {'-'*8} {'-'*30}")
    for r in sorted(results, key=lambda x: ({"A": 0, "B": 1, "C": 2, "REJECT": 3}[x["tier"]], -x["score"])):
        logger.info(f"{r['candidate']:<25} {r['tier']:<8} {r['score']:.0%}{'*' if r['needs_review'] else '':<7} {r['action']:<30}")

    logger.info(f"\n* = needs human review")


def main():
    """Run the demo."""
    print("\n" + "="*60)
    print("RECRUITER AUTOPILOT - DEMO")
    print("Processing 10 Sample Applicants")
    print("="*60 + "\n")

    engine = setup_demo()
    logger = get_logger("demo")

    results = []
    for candidate in SAMPLE_CANDIDATES:
        result = process_candidate(engine, candidate, logger)
        results.append(result)

    print_summary(results, logger)

    print("\n" + "="*60)
    print("DEMO COMPLETE")
    print("In production, these actions would be written to Greenhouse")
    print("and emails would be sent via Microsoft Graph.")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
