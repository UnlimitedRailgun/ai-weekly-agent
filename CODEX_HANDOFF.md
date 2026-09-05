# Codex Handoff

## Task
Implement Phase 2: Research Layer for Version 0.1.

## Status
Completed.

## Summary
Implemented the research-only stage for all six approved categories. It uses one
sequential Responses API request per category, validates structured Pydantic
output, retains only web-search-backed sources and in-range known dates, builds a
`ResearchRun`, and atomically saves validated JSON. Curation, ranking, reporting,
and the full pipeline remain unimplemented by design.

## Files Changed
- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/research.py`
- `/home/shanl/ai-weekly-agent/prompts/research.md`
- `/home/shanl/ai-weekly-agent/tests/test_research.py`
- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

## Important Decisions
- The public API is `research_category(...)`, `research_all_categories(...)`, and
  `save_research_run(...)`; `ResearchError` is the single stage-level exception.
- Research calls use `client.responses.parse(...)` with the runtime
  `OPENAI_MODEL`, `tools=[{"type": "web_search"}]`,
  `include=["web_search_call.action.sources"]`, and
  `text_format=CategoryResearchResult`. The client is injectable and is never
  created at import time.
- Structured Outputs are parsed directly into the existing
  `CategoryResearchResult` Pydantic model and validated again at the project
  boundary. Category mismatches and missing/invalid structured output fail
  clearly.
- Source provenance comes from `response.output` web-search calls. Search-action
  `action.sources` URLs are the primary allow-list; explicit `action.url` values
  from open/find activity are also accepted. Model-generated source URLs are
  retained only when they match this activity after stripping whitespace,
  lowercasing scheme/host, removing fragments, and normalizing trailing slashes.
- Unsupported sources are removed. A candidate with no supported source is
  removed without failing other candidates in the category.
- Known `published_date` values outside the inclusive `DateRange` are removed;
  null dates are retained and never inferred. Missing benchmark information
  remains null.
- All categories run sequentially in the frozen order and fail fast. Empty
  categories are valid.
- Raw data is only the validated `ResearchRun`, serialized as UTF-8 Pydantic JSON
  to `data/raw/<start>_to_<end>.json`. A same-directory temporary file and
  `os.replace` prevent a failed write from corrupting an existing file.

## Commands / Tests Run
- `.venv/bin/python -m pytest tests/test_research.py`
- `.venv/bin/python -m pytest`
- `PYTHONPATH=src .venv/bin/python -c 'import ai_weekly_agent.research as research; print(len(research.RESEARCH_CATEGORIES))'`
- `git diff --check`
- `git status --short`

## Test Results
- 29 tests passed in the full offline suite; 16 are Phase 2 research tests.
- The package research-module import check succeeded and printed `6` categories.
- `git diff --check` passed.
- No live OpenAI API request was made. Tests made no web requests; official
  OpenAI documentation was consulted separately.

## Deviations From Proposed Architecture
None. The implementation uses the current SDK's Pydantic Responses parse helper
and current web-search source metadata as requested.

## Known Issues
- Live compatibility depends on selecting an `OPENAI_MODEL` that supports the
  Responses API, built-in web search, and Structured Outputs. This has not yet
  been checked because live requests were explicitly out of scope.

## Open Questions
None blocking Phase 2.

## Recommended Next Step
Phase 2.5: one controlled live smoke test for ONE category only.
