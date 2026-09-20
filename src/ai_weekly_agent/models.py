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
HistoricalStatus = Literal["NEW", "FOLLOW_UP", "REPEAT", "UNCERTAIN"]
HistoricalMatchReason = Literal[
    "shared_source_url",
    "exact_title",
    "organization_title_terms",
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


class CurrentFactReference(BaseModel):
    """A strict pointer to one authoritative fact on a current NewsItem."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    field: Literal["summary", "technical_detail", "benchmark_information"]
    technical_detail_index: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def validate_field_and_index(self) -> Self:
        """Require an index only, and always, for a technical detail."""
        if self.field == "technical_detail":
            if self.technical_detail_index is None:
                raise ValueError(
                    "technical_detail requires technical_detail_index"
                )
        elif self.technical_detail_index is not None:
            raise ValueError(
                "technical_detail_index is only valid for technical_detail"
            )
        return self


class HistoricalStory(BaseModel):
    """One prior report story reconciled to its upstream structured item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    history_id: str = Field(min_length=1)
    report_date_range: DateRange
    report_position: int = Field(ge=1)
    item: NewsItem


class HistoricalMatch(BaseModel):
    """A retrieved history candidate and its deterministic match reasons."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story: HistoricalStory
    match_reasons: list[HistoricalMatchReason] = Field(min_length=1)

    @field_validator("match_reasons")
    @classmethod
    def validate_unique_match_reasons(
        cls, reasons: list[HistoricalMatchReason]
    ) -> list[HistoricalMatchReason]:
        """Keep retrieval explanations deterministic and unambiguous."""
        if len(reasons) != len(set(reasons)):
            raise ValueError("match_reasons must not contain duplicates")
        return reasons


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

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    impact: int = Field(ge=1, le=5)
    technical_significance: int = Field(ge=1, le=5)
    novelty: int = Field(ge=1, le=5)
    student_relevance: int = Field(ge=1, le=5)
    semantic_duplicate_of: str | None = None
    historical_status: HistoricalStatus | None = None
    historical_match_id: Annotated[str, Field(min_length=1)] | None = None
    material_change_refs: list[CurrentFactReference] = Field(
        default_factory=list
    )

    @field_validator("material_change_refs")
    @classmethod
    def validate_unique_material_change_refs(
        cls, references: list[CurrentFactReference]
    ) -> list[CurrentFactReference]:
        """Reject repeated pointers instead of silently inflating evidence."""
        if len(references) != len(set(references)):
            raise ValueError("material_change_refs must not contain duplicates")
        return references

    @model_validator(mode="after")
    def validate_historical_assessment_shape(self) -> Self:
        """Enforce status-level shape before Curate resolves supplied IDs."""
        if self.historical_status is None:
            if self.historical_match_id is not None or self.material_change_refs:
                raise ValueError(
                    "historical fields require historical_status"
                )
        elif self.historical_status == "NEW":
            if self.historical_match_id is not None or self.material_change_refs:
                raise ValueError(
                    "NEW cannot include a match ID or material change references"
                )
        elif self.historical_status == "FOLLOW_UP":
            if self.historical_match_id is None or not self.material_change_refs:
                raise ValueError(
                    "FOLLOW_UP requires a match ID and material change references"
                )
        elif self.historical_status == "REPEAT":
            if self.historical_match_id is None or self.material_change_refs:
                raise ValueError(
                    "REPEAT requires a match ID and no material change references"
                )
        elif self.material_change_refs:
            raise ValueError("UNCERTAIN cannot include material change references")
        return self


class HistoricalContext(BaseModel):
    """Grounded historical continuity attached to one selected current item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: HistoricalStatus
    historical_match_id: Annotated[str, Field(min_length=1)] | None = None
    prior_report_date_range: DateRange | None = None
    prior_title: Annotated[str, Field(min_length=1)] | None = None
    material_change_facts: list[Annotated[str, Field(min_length=1)]] = Field(
        default_factory=list
    )

    @field_validator("material_change_facts")
    @classmethod
    def validate_unique_material_change_facts(
        cls, facts: list[str]
    ) -> list[str]:
        """Keep resolved current facts concise and deterministic."""
        if len(facts) != len(set(facts)):
            raise ValueError("material_change_facts must not contain duplicates")
        return facts

    @model_validator(mode="after")
    def validate_context_shape(self) -> Self:
        """Keep prior metadata and current change facts mutually consistent."""
        prior_values = (
            self.historical_match_id,
            self.prior_report_date_range,
            self.prior_title,
        )
        has_all_prior = all(value is not None for value in prior_values)
        has_any_prior = any(value is not None for value in prior_values)

        if self.status == "NEW":
            if has_any_prior or self.material_change_facts:
                raise ValueError("NEW cannot include prior or change context")
        elif self.status == "FOLLOW_UP":
            if not has_all_prior or not self.material_change_facts:
                raise ValueError(
                    "FOLLOW_UP requires complete prior context and change facts"
                )
        elif self.status == "REPEAT":
            if not has_all_prior or self.material_change_facts:
                raise ValueError(
                    "REPEAT requires complete prior context and no change facts"
                )
        else:
            if has_any_prior and not has_all_prior:
                raise ValueError(
                    "UNCERTAIN prior context must be complete when supplied"
                )
            if self.material_change_facts:
                raise ValueError("UNCERTAIN cannot include change facts")
        return self


class CuratedItem(BaseModel):
    """A selected news item and its deterministic final score."""

    item: NewsItem
    final_score: float = Field(ge=0)
    historical_context: HistoricalContext | None = None

    @model_validator(mode="after")
    def reject_selected_repeat(self) -> Self:
        """A previously covered repeat cannot be a selected CuratedItem."""
        if (
            self.historical_context is not None
            and self.historical_context.status == "REPEAT"
        ):
            raise ValueError("REPEAT cannot appear in selected curated items")
        return self
