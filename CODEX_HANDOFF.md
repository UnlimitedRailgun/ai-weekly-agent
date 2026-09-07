# Codex Handoff

## Task

Implement Phase 4: Report / Explain stage for Version 0.1.

## Status

Completed. Report explanation generation, deterministic Markdown rendering, and
atomic local persistence are implemented. The full CLI pipeline and Phase 4.5
were not implemented.

## Summary

Added a single-request, non-search report stage. A typed LLM response supplies
only explanatory prose keyed by stable story IDs. Local Python validates that
mapping, renders all Markdown and trusted source links, and saves the report
under its ISO-week filename.

## Files Changed

- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/report.py`
- `/home/shanl/ai-weekly-agent/prompts/report.md`
- `/home/shanl/ai-weekly-agent/tests/test_report.py`
- `/home/shanl/ai-weekly-agent/README.md`
- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

The frozen Research and Curator modules, prompts, and tests were not changed.

## Important Decisions

- Public APIs are `generate_report(date_range, curated_items, config, *,
  client=None) -> str`, `render_markdown(date_range, curated_items, content=None)
  -> str`, and `save_report(date_range, markdown, output_dir=Path("reports"), *,
  overwrite=False) -> Path`.
- Report-specific Structured Output models are `StoryExplanation`,
  `ConceptExplanation`, and `ReportContent`. Stable `story_001` IDs map prose to
  final CuratedItem order without changing `NewsItem`.
- Every non-empty run uses one `responses.parse()` call with runtime
  `OPENAI_MODEL`, Pydantic Structured Outputs, client injection, and no tools,
  `tool_choice`, or `web_search`. One-story runs use the same flow; no batching
  or per-story calls were added.
- The LLM owns only week-summary prose, story explanations, benchmark explanation
  when evidence exists, student takeaways, and concept explanations. Python owns
  report structure, dates, titles, categories, organizations, scores, story
  order, source labels/URLs/order, the Source Index, filename, and persistence.
- The prompt receives researched facts and source titles/types but no source
  URLs. Structured prose containing URL syntax fails closed with `ReportError`,
  so the final report cannot acquire an unvalidated model-generated URL.
- Every expected story ID must have exactly one explanation. Unknown, missing,
  or duplicate story IDs and invalid concept references fail clearly.
- Sources render in the deterministic order official, paper, GitHub, university,
  benchmark, secondary, then unknown types. Unknown types remain valid. The
  consolidated Source Index deduplicates normalized URLs and prefers the stronger
  source type for duplicate entries.
- When research has `benchmark_information=None`, Python renders exactly: “No
  reliable benchmark information was available in the researched sources.” It
  does not render model-supplied benchmark claims for that story.
- Empty CuratedItem input requires no configuration or API call and returns a
  dated Markdown report stating that no stories passed curation.
- `save_report()` writes UTF-8 to a temporary file in the destination directory
  and then uses `os.replace`. Existing reports are not overwritten unless the
  caller explicitly sets `overwrite=True`; a failed replacement preserves the
  previous report and cleans up the temporary file.
- README now records that the three stages are implemented independently while
  `main.py` remains an unconnected placeholder.

## Commands / Tests Run

- `.venv/bin/python -m pytest tests/test_report.py`
- `.venv/bin/python -m pytest`
- `awk 'length($0) > 88 { print FNR ":" length($0) ":" $0 }' src/ai_weekly_agent/report.py tests/test_report.py`
- `PYTHONPATH=src .venv/bin/python -c "import ai_weekly_agent.report; print('report import: ok')"`
- `git diff --check`
- `git status --short`

## Test Results

- 42 report tests passed.
- 146 total offline tests passed in 0.91 seconds, including all frozen-layer
  regressions.
- The report import check passed.
- `git diff --check` passed.
- Tests made zero live OpenAI API, `web_search`, or other network calls. No live
  application request was made and no commit was created.

## Known Issues

- The full `main.py` pipeline is still a placeholder and does not connect the
  implemented Research, Curator, and Report stages.
- Report response quality has not yet been checked with a controlled live call.

## Open Questions

None blocking Phase 4.5. The URL rejection and fixed null-benchmark rendering are
intentional fail-closed safety behavior, not prompt-only guarantees.

## Recommended Next Step

Phase 4.5: controlled live Report smoke test using a small synthetic CuratedItem
set and exactly ONE non-search Responses API request.
