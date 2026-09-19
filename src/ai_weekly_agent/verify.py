"""Deterministically verify research evidence before curation."""

from collections import Counter

from ai_weekly_agent.models import (
    ORIGINAL_EVALUATION_SOURCE_TYPES,
    PRIMARY_EVIDENCE_SOURCE_TYPES,
    CategoryResearchResult,
    NewsItem,
    ResearchRun,
    Source,
    VerificationCode,
    VerificationFinding,
    VerificationResult,
    VerificationSeverity,
)
from ai_weekly_agent.research import RESEARCH_CATEGORIES, normalize_source_url


class VerificationError(RuntimeError):
    """Raised when a research run is structurally unsafe to verify."""


def item_identifier(category_position: int, item_position: int) -> str:
    """Return the stable 1-based ``category_NN:item_NNN`` positional ID."""
    if category_position < 1 or item_position < 1:
        raise ValueError("item identifier positions must be positive")
    return f"category_{category_position:02d}:item_{item_position:03d}"


def verify_research_run(
    research_run: ResearchRun, *, require_provenance: bool = False
) -> VerificationResult:
    """Check reported evidence locally, without establishing page semantics.

    Legacy items retain compatibility behavior unless provenance is required.
    Any item with new metadata receives the complete fact-support checks.
    """
    _validate_category_structure(research_run)

    accepted_categories: list[CategoryResearchResult] = []
    findings: list[VerificationFinding] = []
    rejected_item_ids: list[str] = []

    for category_position, category_result in enumerate(
        research_run.categories, start=1
    ):
        accepted_items: list[NewsItem] = []
        for item_position, item in enumerate(category_result.items, start=1):
            item_id = item_identifier(category_position, item_position)
            accepted_item, item_findings = _verify_item(
                item,
                containing_category=category_result.category,
                research_run=research_run,
                item_id=item_id,
                require_provenance=require_provenance,
            )
            findings.extend(item_findings)
            if accepted_item is None:
                rejected_item_ids.append(item_id)
            else:
                accepted_items.append(accepted_item)

        accepted_categories.append(
            CategoryResearchResult(
                category=category_result.category,
                items=accepted_items,
            )
        )

    accepted_run = ResearchRun(
        date_range=research_run.date_range.model_copy(deep=True),
        categories=accepted_categories,
    )
    return VerificationResult(
        accepted_run=accepted_run,
        findings=findings,
        rejected_item_ids=rejected_item_ids,
    )


def _validate_category_structure(research_run: ResearchRun) -> None:
    category_counts = Counter(
        category_result.category for category_result in research_run.categories
    )
    required = set(RESEARCH_CATEGORIES)
    actual = set(category_counts)
    problems: list[str] = []

    missing = [category for category in RESEARCH_CATEGORIES if category not in actual]
    if missing:
        problems.append("missing categories: " + ", ".join(missing))

    duplicated = [
        category
        for category in RESEARCH_CATEGORIES
        if category_counts[category] > 1
    ]
    if duplicated:
        problems.append("duplicate categories: " + ", ".join(duplicated))

    unsupported = sorted(actual - required)
    if unsupported:
        problems.append("unsupported categories: " + ", ".join(unsupported))

    if problems:
        raise VerificationError(
            "Invalid research category structure; " + "; ".join(problems)
        )


def _verify_item(
    item: NewsItem,
    *,
    containing_category: str,
    research_run: ResearchRun,
    item_id: str,
    require_provenance: bool,
) -> tuple[NewsItem | None, list[VerificationFinding]]:
    usable_sources, findings = _verified_sources(item.sources, item_id)

    if not usable_sources:
        findings.append(
            _finding(
                item_id,
                "hard_failure",
                "no_usable_source",
                "The item has no usable HTTP or HTTPS source URL.",
            )
        )

    if item.category != containing_category:
        findings.append(
            _finding(
                item_id,
                "hard_failure",
                "category_mismatch",
                "The item category does not match its containing category.",
            )
        )

    if item.published_date is None:
        findings.append(
            _finding(
                item_id,
                "warning",
                "unknown_event_date",
                "The event date is unknown.",
            )
        )
    elif not (
        research_run.date_range.start
        <= item.published_date
        <= research_run.date_range.end
    ):
        findings.append(
            _finding(
                item_id,
                "hard_failure",
                "event_date_out_of_range",
                "The known event date is outside the reporting window.",
            )
        )

    if usable_sources:
        # Discarding a new-metadata source must not downgrade the remaining item.
        use_fact_support = require_provenance or any(
            source.fact_support is not None for source in item.sources
        )
        if use_fact_support:
            findings.extend(_fact_support_findings(item, usable_sources, item_id))
        else:
            findings.extend(_legacy_evidence_findings(item, usable_sources, item_id))

        if all(
            source.source_type.casefold() == "secondary"
            for source in usable_sources
        ):
            findings.append(
                _finding(
                    item_id,
                    "warning",
                    "secondary_sources_only",
                    "All usable sources are classified as secondary.",
                )
            )

    if any(finding.severity == "hard_failure" for finding in findings):
        return None, findings

    return item.model_copy(
        update={"sources": usable_sources},
        deep=True,
    ), findings


def _legacy_evidence_findings(
    item: NewsItem, sources: list[Source], item_id: str
) -> list[VerificationFinding]:
    """Preserve pre-provenance checks and explicitly label lower assurance."""
    findings = [
        _finding(
            item_id,
            "warning",
            "legacy_fact_support",
            "Legacy item has no fact-support metadata; acceptance does not "
            "establish the new provenance policy.",
        )
    ]
    if any(source.evidence_roles is None for source in sources):
        findings.append(
            _finding(
                item_id,
                "warning",
                "legacy_evidence_roles",
                "At least one source has no evidence-role metadata.",
            )
        )
        return findings

    roles = {role for source in sources for role in (source.evidence_roles or [])}
    if "event" not in roles:
        findings.append(
            _finding(
                item_id, "hard_failure", "event_evidence_missing",
                "No usable source is classified as direct event evidence.",
            )
        )
    if item.published_date is not None and "event_date" not in roles:
        findings.append(
            _finding(
                item_id, "hard_failure", "event_date_evidence_missing",
                "The known event date has no classified date evidence.",
            )
        )
    if _has_text(item.benchmark_information) and "benchmark" not in roles:
        findings.append(
            _finding(
                item_id, "hard_failure", "benchmark_evidence_missing",
                "Benchmark information has no classified benchmark evidence.",
            )
        )
    if _has_technical_details(item) and "technical" not in roles:
        findings.append(
            _finding(
                item_id, "warning", "technical_evidence_missing",
                "Technical details have no classified technical evidence.",
            )
        )
    return findings


def _fact_support_findings(
    item: NewsItem, sources: list[Source], item_id: str
) -> list[VerificationFinding]:
    """Validate only explicit support on retained sources, never repair facts."""
    findings: list[VerificationFinding] = []
    summary_supported = False
    date_supported = False
    technical_indices: set[int] = set()
    benchmark_supported = False

    for source in sources:
        support = source.fact_support
        roles = set(source.evidence_roles or [])
        missing: list[str] = []
        if support is None:
            missing.append("fact_support")
        if source.evidence_roles is None:
            missing.append("evidence_roles")
        if missing:
            findings.append(
                _finding(
                    item_id, "hard_failure", "provenance_metadata_missing",
                    "Retained source is missing required metadata: "
                    + ", ".join(missing) + ".",
                    source_url=source.url,
                )
            )
        if support is None:
            continue

        contradictions: list[str] = []
        if support.summary and "event" not in roles:
            contradictions.append("summary support requires an event role")
        if support.technical_detail_indices and "technical" not in roles:
            contradictions.append("detail support requires a technical role")
        for index in support.technical_detail_indices:
            if index >= len(item.technical_details):
                contradictions.append(f"technical detail index {index} is out of range")
        if support.benchmark:
            if "benchmark" not in roles:
                contradictions.append("benchmark support requires a benchmark role")
            if not _has_text(item.benchmark_information):
                contradictions.append(
                    "benchmark support requires benchmark information"
                )
        for message in contradictions:
            findings.append(
                _finding(
                    item_id, "hard_failure", "fact_support_inconsistent",
                    message + ".", source_url=source.url,
                )
            )

        source_type = source.source_type.casefold()
        if source_type in PRIMARY_EVIDENCE_SOURCE_TYPES:
            if support.summary and "event" in roles:
                summary_supported = True
            if "event_date" in roles:
                date_supported = True
            if "technical" in roles:
                technical_indices.update(support.technical_detail_indices)
        if (
            source_type in ORIGINAL_EVALUATION_SOURCE_TYPES
            and support.benchmark
            and "benchmark" in roles
        ):
            benchmark_supported = True

    if not summary_supported:
        findings.append(
            _finding(
                item_id, "hard_failure", "event_evidence_missing",
                "The summary has no explicit primary/original event support.",
            )
        )
    if item.published_date is not None and not date_supported:
        findings.append(
            _finding(
                item_id, "hard_failure", "event_date_evidence_missing",
                "The known event date has no primary/original date evidence.",
            )
        )
    for index, detail in enumerate(item.technical_details):
        if not _has_text(detail) or index not in technical_indices:
            findings.append(
                _finding(
                    item_id, "hard_failure", "technical_evidence_missing",
                    f"Technical detail index {index} is blank or lacks explicit "
                    "primary/original technical support.",
                )
            )
    if item.benchmark_information is not None:
        if not _has_text(item.benchmark_information):
            findings.append(
                _finding(
                    item_id, "hard_failure", "fact_support_inconsistent",
                    "Benchmark information must contain text or be null.",
                )
            )
        if not benchmark_supported:
            findings.append(
                _finding(
                    item_id, "hard_failure", "benchmark_evidence_missing",
                    "Benchmark information has no explicit original "
                    "evaluation support.",
                )
            )
    return findings


def _verified_sources(
    sources: list[Source], item_id: str
) -> tuple[list[Source], list[VerificationFinding]]:
    usable: list[Source] = []
    findings: list[VerificationFinding] = []
    seen: set[str] = set()

    for source in sources:
        normalized_url = normalize_source_url(source.url)
        if normalized_url is None:
            findings.append(
                _finding(
                    item_id,
                    "warning",
                    "unusable_source_removed",
                    "A source with an unusable URL was removed from verifier output.",
                    source_url=source.url,
                )
            )
            continue
        if normalized_url in seen:
            findings.append(
                _finding(
                    item_id,
                    "info",
                    "duplicate_source_removed",
                    "A duplicate source URL was removed from verifier output.",
                    source_url=source.url,
                )
            )
            continue

        seen.add(normalized_url)
        if normalized_url != source.url:
            findings.append(
                _finding(
                    item_id,
                    "info",
                    "source_url_normalized",
                    "A source URL was normalized in verifier output.",
                    source_url=source.url,
                )
            )
        usable.append(source.model_copy(update={"url": normalized_url}, deep=True))

    return usable, findings


def _finding(
    item_id: str,
    severity: VerificationSeverity,
    code: VerificationCode,
    message: str,
    *,
    source_url: str | None = None,
) -> VerificationFinding:
    return VerificationFinding(
        item_id=item_id,
        severity=severity,
        code=code,
        message=message,
        source_url=source_url,
    )


def _has_text(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_technical_details(item: NewsItem) -> bool:
    return any(
        isinstance(detail, str) and bool(detail.strip())
        for detail in item.technical_details
    )
