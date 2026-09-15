# Weekly Report Explanation

Write structured explanations for the supplied curated stories for {audience}.
The reporting window is {start_date} through {end_date}, inclusive.

Use only the facts supplied below. Do not browse, search, call tools, add stories,
re-curate stories, or change their order. The application separately renders
authoritative titles, organizations, dates, summaries, technical details,
benchmark information, and sources. Do not restate or provide alternate versions
of those facts. Do not invent release details, benchmark numbers, specifications,
results, citations, or URLs. Keep interpretation clearly separate from fact,
avoid hype, and state uncertainty when appropriate.

Return plain text in every field: no Markdown headings, lists, links, or URLs.
Return exactly one `story_explanations` entry for every supplied `story_id`, using
only those IDs. Do not repeat a story ID.

For each story provide:

- `what_it_is`: explain the general kind of model, product, research, hardware,
  or system for the target student without repeating its title, organization,
  event date, benchmark values, specifications, or supplied technical details.
- `why_it_matters`: give specific technical, industry, research, developer,
  hardware, or systems significance as interpretation. Avoid generic claims
  about AI growth and do not introduce or repeat story-specific facts.
- `student_takeaway`: give concrete technical learning directions rather than
  generic career advice. Do not restate story facts.

For `concepts`, provide approximately three to five concrete technical concepts
that naturally arise from the stories. Each concept needs a concise name, a
beginner-friendly explanation, and one or more valid `related_story_ids`. Fewer
or no concepts are valid when the supplied material does not support them. Keep
definitions general: do not include story-specific dates, organizations,
benchmark results, specifications, citations, or URLs.

Curated stories:

{stories_json}
