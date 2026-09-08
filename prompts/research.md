# Weekly Research Task

Research important developments for this single category:

- Research category: {category}
- Inclusive reporting window: {start_date} through {end_date}
- Audience: {audience}

This is weekly-news discovery, not an exhaustive deep-research task. Identify
only the most important technically meaningful events in the supplied reporting
window, normally seven days. Avoid exhaustive searching. Stop researching when
you have enough evidence for a small set of high-confidence stories. Aim for
approximately 0-5 strong candidate stories for this category; do not force a
minimum or exactly five items. Prioritize quality over coverage, and technical
significance and practical relevance over hype or broad publicity.

Return only meaningful developments whose event, release, announcement, or
publication occurred inside the reporting window. A web page's update date is
not automatically the event date. Return zero items when nothing important
occurred or no well-supported development is found; do not add weak stories for
completeness.

Use web search to open and inspect the underlying sources for every candidate.
For a specific event, prefer a direct canonical primary-source page that supports
that event, such as:

- A direct official company or organization announcement.
- A direct documentation or release page.
- An official GitHub release or repository page.
- A direct paper or arXiv page.
- A direct university or research-lab publication.
- A direct benchmark or technical report.

When a specific page exists, avoid using an organization homepage, generic
newsroom index, generic blog index, generic product landing page, search-results
page, or URL-shortener/tracking URL as the main source. Cite the direct canonical
URL instead. Use reputable secondary reporting only when it supplies necessary
context or no suitable primary source is available; it must not replace a
primary source when one exists. Do not treat a search-result snippet as evidence.

For time-sensitive claims about announcement dates, release dates, initial
availability, capabilities available at launch, benchmark results announced at
launch, or version-specific behavior, prefer dated/version-specific evidence:
a direct launch announcement, dated release notes, versioned documentation,
a dated model card, a paper/arXiv version, a dated GitHub release, or a dated
university/lab publication. Check that the evidence supports the claimed version
and availability at the time of the event in the reporting window.

A mutable generic product page may be used for current background context, but
must not be the sole evidence for a historical launch-time claim when dated
release evidence should exist. Do not treat a later page update or current
availability as proof of what was available at launch.

For each item:

- State what happened, what it is, who created it, and why it may matter.
- Use `technical_details` for source-supported architecture, capabilities,
  algorithms, hardware, APIs, modalities, context window, training/inference
  methods, and implementation details.
- Use the exact category shown above.
- Set `published_date` to the verified event date, or null when it cannot be
  established reliably.
- Put all quantitative performance claims in `benchmark_information`, not in
  `technical_details`. This includes benchmark scores, quantitative comparisons,
  measured latency, measured throughput, accuracy/performance percentages, and
  other quantitative performance claims, such as fewer tool calls or tokens for
  the same workload. Include them only when reliable evidence exists in the cited
  sources. State whose result it is, label company- or paper-reported results,
  and preserve important evaluation conditions and comparison baselines.
- If reliable benchmark/performance evidence is unavailable, set
  `benchmark_information` to null and omit those claims rather than moving them
  into `technical_details`. Never invent or infer benchmark numbers.
- Associate at least one directly supporting source with the item. Each source
  needs a descriptive title, its exact URL, and one of these source types:
  `official`, `paper`, `github`, `university`, `benchmark`, or `secondary`.
- Populate `evidence_roles` for every source with the claims that particular
  source actually supports. A source may have more than one role. Use only:
  - `event`: directly supports that the event, release, or update occurred.
  - `event_date`: supports the date or date range of the event.
  - `technical`: supports concrete technical details, specifications,
    architecture, capabilities, or implementation facts.
  - `benchmark`: supports a concrete benchmark, evaluation, measured result,
    or quantitative performance comparison.
  - `background`: provides context but is not sufficient by itself to establish
    the current event.
  For example, an official release page may use
  `["event", "event_date", "technical"]`; a benchmark/evaluation page may use
  `["benchmark", "technical"]`; and general background documentation should
  use `["background"]`. Do not assign a role unless that specific source
  supports it. These roles report source coverage; they do not indicate that a
  separate verifier independently reopened or fact-checked the page.

Never invent or infer release dates, benchmark numbers, specifications, or
research results. Keep summaries factual and understandable to the stated
audience. The response must match the provided structured output schema.
