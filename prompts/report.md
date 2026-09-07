# Weekly Report Explanation

Write structured explanations for the supplied curated stories for {audience}.
The reporting window is {start_date} through {end_date}, inclusive.

Use only the facts supplied below. Do not browse, search, call tools, add stories,
re-curate stories, or change their order. Do not invent release details,
benchmark numbers, specifications, results, citations, or URLs. Distinguish
source-reported facts from interpretation, avoid hype, and state clearly when
information is unavailable.

Return plain text in every field: no Markdown headings, lists, links, or URLs.
Return exactly one `story_explanations` entry for every supplied `story_id`, using
only those IDs. Do not repeat a story ID.

For each story provide:

- `what_happened`: concisely describe the actual event in this reporting window.
- `what_is_it`: explain the model, product, research, hardware, or system for the
  target student.
- `why_it_matters`: give specific technical, industry, research, developer,
  hardware, or systems significance. Avoid generic claims about AI growth.
- `technical_explanation`: explain relevant architecture, algorithms, hardware,
  APIs, frameworks, training or inference methods, robotics, or systems concepts,
  using only supplied details.
- `benchmark_explanation`: when `benchmark_information` exists, explain what it
  means and retain its supplied caveats. When it is null, say: "No reliable
  benchmark information was available in the researched sources."
- `student_takeaway`: give concrete technical learning directions rather than
  generic career advice.

For `week_summary`, provide approximately three to five concise synthesis
bullets as separate strings. Use fewer when fewer than three stories are supplied.
Do not introduce facts absent from the stories.

For `concepts`, provide approximately three to five concrete technical concepts
that naturally arise from the stories. Each concept needs a concise name, a
beginner-friendly explanation, and one or more valid `related_story_ids`. Fewer
or no concepts are valid when the supplied material does not support them.

Curated stories:

{stories_json}
