# Codex Handoff

## Task

Implement Phase 2.6: targeted research optimization based on Phase 2.5.

## Status

Completed. Phase 2.7 has not been performed.

## Summary

Added a four-call built-in tool limit per category response and tightened the
research prompt for focused discovery, direct primary sources, and correct
placement of performance claims. Added six offline tests; all 35 tests passed.

## Files Changed

- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/research.py`
- `/home/shanl/ai-weekly-agent/prompts/research.md`
- `/home/shanl/ai-weekly-agent/tests/test_research.py`
- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

## Important Decisions

- `MAX_RESEARCH_TOOL_CALLS = 4` is passed as `max_tool_calls` to
  `client.responses.parse(...)`. This limits total built-in tool calls per
  response, not tokens or returned source URLs. No new configuration was added.
  Confirmed against the [official Responses API reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
  and the installed SDK.
- The prompt requests approximately 0-5 strong candidates, discourages exhaustive
  searching, and instructs the model to stop when enough evidence is available.
  Zero stories remain valid; no deterministic item-count limit was added.
- Direct canonical event pages are preferred over generic indexes, landing pages,
  search results, and tracking URLs. No URL-path rejection rules were introduced.
- Quantitative performance claims belong in `benchmark_information`, with source
  attribution and evaluation conditions. Without reliable evidence, the field
  must be null and the claim omitted from `technical_details`.
- Runtime model selection, Pydantic output, provenance allow-list, date/null-date
  behavior, atomic persistence, category order, and fail-fast behavior are
  unchanged. No curation, reporting, concurrency, or retry changes were made.
- Preserve this Phase 2.5 comparison baseline: model `gpt-5.6-terra`, category
  `AI model releases`, inclusive dates 2026-08-30 through 2026-09-05; one request,
  9 web-search calls, 79,668 input tokens, 3,431 output tokens, 83,099 total tokens,
  107 normalized source URLs, 4 structured and 4 retained stories. Quality issues
  included generic source pages and performance claims outside the benchmark field.

## Commands / Tests Run

- `.venv/bin/python -m pytest`
- `git diff --check`
- `git status --short`

## Test Results

- 35 tests passed in 1.04 seconds, including 22 research tests.
- New coverage checks the four-call request limit, direct-source guidance,
  bounded discovery, zero-result guidance, performance-claim placement, and
  retention of unknown dates.
- Existing web-search/source-metadata, provenance, date, model, structured-output,
  ordering, error, and persistence tests passed.
- `git diff --check` passed.
- Zero live research/Responses API requests were made. Tests were fully offline;
  the requested official documentation was consulted separately.
- No commit was created.

## Known Issues

No implementation issues encountered. Prompt tests verify the instructions sent,
not live model compliance. Token savings and source/benchmark quality improvements
remain unmeasured until Phase 2.7.

## Open Questions

Will the four-call limit and revised prompt improve efficiency and source quality
while preserving useful coverage? Evaluate in Phase 2.7.

## Recommended Next Step

Phase 2.7: repeat the same ONE-category live smoke test using the same model,
category, and date range, then compare search-call count, token usage, source
count, retained story count, and story quality against Phase 2.5. Do not run it
without the user's instruction.
