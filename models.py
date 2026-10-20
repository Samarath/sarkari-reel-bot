from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class ScrapedJobNotice(BaseModel):
    # Core Identity
    job_id: str = Field(description="Deterministic MD5 hash of the job URL")
    raw_title: str
    detail_page_url: str

    # Parsed Details
    agency: str
    post_name: str
    vacancies: str = "Refer Notice"
    qualification: str = "Refer Notice"
    age_limit: str = "As per rules"
    last_date: str = "Check Notification"

    # Official Sourcing
    official_apply_url: Optional[str] = None
    official_website: Optional[str] = None

    # Queue & Prioritization Metrics
    status: str = "QUEUED"  # QUEUED | PUBLISHED | FAILED
    priority_score: int = 0
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: Optional[datetime] = None