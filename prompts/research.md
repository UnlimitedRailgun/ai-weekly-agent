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

Never invent or infer release dates, benchmark numbers, specifications, or
research results. Keep summaries factual and understandable to the stated
audience. The response must match the provided structured output schema.
