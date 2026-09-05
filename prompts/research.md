# Weekly Research Task

Research important developments for this single category:

- Research category: {category}
- Inclusive reporting window: {start_date} through {end_date}
- Audience: {audience}

Use web search to inspect the underlying sources for every candidate. Prefer
official company or project announcements, official documentation, official
GitHub repositories and release notes, original papers or arXiv pages, and
university or research-lab publications. Use reputable secondary reporting only
when it supplies necessary context or no suitable primary source is available.
Do not treat a search-result snippet as evidence.

Prioritize technical significance and practical relevance over hype or broad
publicity. Include only developments worth bringing to the audience's attention.

Return only meaningful developments whose event, release, announcement, or
publication occurred inside the reporting window. A web page's update date is
not automatically the event date. It is valid to return zero items when no
well-supported development is found; do not add weak stories for completeness.

For each item:

- State what happened, what it is, who created it, and why it may matter.
- Include concise technical details that the sources directly support.
- Use the exact category shown above.
- Set `published_date` to the verified event date, or null when it cannot be
  established reliably.
- Include benchmark information only when a credible source reports it. State
  whose result it is and preserve important conditions or baselines. Otherwise
  set `benchmark_information` to null.
- Associate at least one directly supporting source with the item. Each source
  needs a descriptive title, its exact URL, and one of these source types:
  `official`, `paper`, `github`, `university`, `benchmark`, or `secondary`.

Never invent or infer release dates, benchmark numbers, specifications, or
research results. Keep summaries factual and understandable to the stated
audience. The response must match the provided structured output schema.
