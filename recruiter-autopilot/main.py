#!/usr/bin/env python3
"""Main entry point for Recruiter Autopilot."""

import uvicorn

from src.config import settings


def main():
    """Run the FastAPI application."""
    uvicorn.run(
        "src.api.app:create_app",
        host=settings.api_host,
        port=settings.api_port,
        workers=settings.api_workers,
        reload=settings.is_development,
        factory=True,
    )


if __name__ == "__main__":
    main()
