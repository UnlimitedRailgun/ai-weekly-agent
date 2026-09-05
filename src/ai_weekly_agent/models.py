"""Pydantic models shared by the Version 0.1 pipeline."""

from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DateRange(BaseModel):
    """An inclusive range of calendar dates."""

    start: date
    end: date

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        """Ensure the range does not end before it starts."""
        if self.start > self.end:
            raise ValueError("start must not be after end")
        return self


class Source(BaseModel):
    """A source associated directly with one news item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    source_type: str = Field(min_length=1)


class NewsItem(BaseModel):
    """One candidate development found during research."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    organization: str | None = None
    published_date: date | None = None
    summary: str = Field(min_length=1)
    technical_details: list[str] = Field(default_factory=list)
    benchmark_information: str | None = None
    sources: list[Source] = Field(min_length=1)


class CategoryResearchResult(BaseModel):
    """Structured research output for one category."""

    category: str = Field(min_length=1)
    items: list[NewsItem] = Field(default_factory=list)


class ResearchRun(BaseModel):
    """Structured research output for one complete reporting window."""

    date_range: DateRange
    categories: list[CategoryResearchResult] = Field(default_factory=list)


class CurationAssessment(BaseModel):
    """LLM curation judgments on a 1 (low) to 5 (high) scale."""

    candidate_id: str = Field(min_length=1)
    impact: int = Field(ge=1, le=5)
    technical_significance: int = Field(ge=1, le=5)
    novelty: int = Field(ge=1, le=5)
    student_relevance: int = Field(ge=1, le=5)
    semantic_duplicate_of: str | None = None


class CuratedItem(BaseModel):
    """A selected news item and its deterministic final score."""

    item: NewsItem
    final_score: float = Field(ge=0)
