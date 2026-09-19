"""Pydantic models shared by the application pipeline."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


PRIMARY_EVIDENCE_SOURCE_TYPES = frozenset(
    {"official", "paper", "github", "university"}
)
ORIGINAL_EVALUATION_SOURCE_TYPES = PRIMARY_EVIDENCE_SOURCE_TYPES | {"benchmark"}


EvidenceRole = Literal[
    "event",
    "event_date",
    "technical",
    "benchmark",
    "background",
]
VerificationSeverity = Literal["hard_failure", "warning", "info"]
VerificationCode = Literal[
    "no_usable_source",
    "category_mismatch",
    "event_date_out_of_range",
    "event_evidence_missing",
    "event_date_evidence_missing",
    "benchmark_evidence_missing",
    "legacy_evidence_roles",
    "unknown_event_date",
    "unusable_source_removed",
    "secondary_sources_only",
    "technical_evidence_missing",
    "source_url_normalized",
    "duplicate_source_removed",
    "legacy_fact_support",
    "provenance_metadata_missing",
    "fact_support_inconsistent",
]


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


class FactSupport(BaseModel):
    """Model-reported coverage of facts in one containing news item."""

    model_config = ConfigDict(extra="forbid", strict=True)

    summary: bool
    technical_detail_indices: list[Annotated[int, Field(ge=0)]]
    benchmark: bool

    @field_validator("technical_detail_indices")
    @classmethod
    def validate_unique_indices(cls, indices: list[int]) -> list[int]:
        """Keep zero-based detail references unambiguous."""
        if len(indices) != len(set(indices)):
            raise ValueError("technical_detail_indices must not contain duplicates")
        return indices


class Source(BaseModel):
    """A source associated directly with one news item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    evidence_roles: list[EvidenceRole] | None = None
    fact_support: FactSupport | None = None

    @field_validator("evidence_roles")
    @classmethod
    def validate_unique_evidence_roles(
        cls, roles: list[EvidenceRole] | None
    ) -> list[EvidenceRole] | None:
        """Reject ambiguous duplicate evidence classifications."""
        if roles is not None and len(roles) != len(set(roles)):
            raise ValueError("evidence_roles must not contain duplicates")
        return roles


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


class VerificationFinding(BaseModel):
    """One deterministic evidence or structure finding for a research item."""

    item_id: str = Field(min_length=1)
    severity: VerificationSeverity
    code: VerificationCode
    message: str = Field(min_length=1)
    source_url: str | None = None


class VerificationResult(BaseModel):
    """Accepted research and diagnostics produced without mutating the input."""

    accepted_run: ResearchRun
    findings: list[VerificationFinding] = Field(default_factory=list)
    rejected_item_ids: list[str] = Field(default_factory=list)


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
