"""Deterministically verify research evidence before curation."""

from collections import Counter

from ai_weekly_agent.models import (
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


def verify_research_run(research_run: ResearchRun) -> VerificationResult:
    """Return a separately constructed run containing only accepted items."""
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
) -> tuple[NewsItem | None, list[VerificationFinding]]:
    usable_sources, findings = _verified_sources(item.sources, item_id)
    hard_failure = False

    if not usable_sources:
        findings.append(
            _finding(
                item_id,
                "hard_failure",
                "no_usable_source",
                "The item has no usable HTTP or HTTPS source URL.",
            )
        )
        hard_failure = True

    if item.category != containing_category:
        findings.append(
            _finding(
                item_id,
                "hard_failure",
                "category_mismatch",
                "The item category does not match its containing category.",
            )
        )
        hard_failure = True

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
        hard_failure = True

    if usable_sources:
        if any(source.evidence_roles is None for source in usable_sources):
            findings.append(
                _finding(
                    item_id,
                    "warning",
                    "legacy_evidence_roles",
                    "At least one source has no evidence-role metadata.",
                )
            )
        else:
            roles = {
                role
                for source in usable_sources
                for role in (source.evidence_roles or [])
            }
            if "event" not in roles:
                findings.append(
                    _finding(
                        item_id,
                        "hard_failure",
                        "event_evidence_missing",
                        "No usable source is classified as direct event evidence.",
                    )
                )
                hard_failure = True
            if item.published_date is not None and "event_date" not in roles:
                findings.append(
                    _finding(
                        item_id,
                        "hard_failure",
                        "event_date_evidence_missing",
                        "The known event date has no classified date evidence.",
                    )
                )
                hard_failure = True
            if _has_text(item.benchmark_information) and "benchmark" not in roles:
                findings.append(
                    _finding(
                        item_id,
                        "hard_failure",
                        "benchmark_evidence_missing",
                        "Benchmark information has no classified benchmark evidence.",
                    )
                )
                hard_failure = True
            if _has_technical_details(item) and "technical" not in roles:
                findings.append(
                    _finding(
                        item_id,
                        "warning",
                        "technical_evidence_missing",
                        "Technical details have no classified technical evidence.",
                    )
                )

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

    if hard_failure:
        return None, findings

    return item.model_copy(
        update={"sources": usable_sources},
        deep=True,
    ), findings


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
