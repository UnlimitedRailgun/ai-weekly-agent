# Codex Handoff

## Task

Implement Phase 3: Curator for Version 0.1.

## Status

Completed. The Curator is implemented and all offline tests pass. Phase 3.5 and
report generation were not performed.

## Summary

Added hybrid curation from a `ResearchRun` to a deterministic list of up to 12
strong `CuratedItem` objects. Curation performs local filtering and exact
deduplication, one tool-free structured LLM assessment, then local semantic
duplicate resolution, scoring, thresholding, diversity preference, and limiting.

## Files Changed

Changed for this task:

- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/curate.py`
- `/home/shanl/ai-weekly-agent/prompts/curate.md`
- `/home/shanl/ai-weekly-agent/tests/test_curate.py`
- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

Pre-existing Phase 2.8 modifications in `src/ai_weekly_agent/research.py`,
`prompts/research.md`, and `tests/test_research.py` were preserved and not edited
during Phase 3.

## Important Decisions

- Public API: `curate_research_run(research_run, config, *, client=None) ->
  list[CuratedItem]`; `calculate_final_score()` exposes the simple score formula.
- Candidates are flattened in category/item order and receive temporary stable
  IDs such as `candidate_001`. IDs are assigned before filtering so each refers
  to its original input position.
- Local preprocessing rejects missing/blank required content, missing or invalid
  source content, and known out-of-range dates. Unknown dates remain allowed.
- Normalized-title duplicates are merged. Shared normalized URLs merge only with
  matching organization/category and nonconflicting dates. The representative
  preference is more sources, known date, richer technical detail, then earlier
  input position.
- Nonempty inputs use one `responses.parse()` request with runtime `OPENAI_MODEL`,
  Pydantic Structured Outputs, and no tools or `web_search`. Client injection
  keeps tests offline. One-candidate inputs still receive the same assessment.
- The response must contain exactly one bounded `CurationAssessment` per expected
  ID. Unknown, missing, repeated, self-referencing, and invalid duplicate IDs fail
  with `CuratorError` rather than receiving fallback scores.
- Semantic duplicate links form small connected groups, including cycles. Each
  group keeps the highest score, then most primary/direct sources, most total
  sources, known date, and earliest input position.
- `final_score` is the equal-weight mean of impact, technical significance,
  novelty, and student relevance. `MIN_CURATED_SCORE = 3.25` prevents neutral or
  weak filler. `MAX_CURATED_ITEMS = 12`; no minimum is forced.
- Among candidates within 0.25 points of the current top score, selection prefers
  the least-represented category, then deterministic quality tie-breakers. There
  are no category quotas, and candidates outside that near-tie window never gain
  a diversity advantage.
- Empty inputs return `[]` before configuration validation and make no API call.
- No Pydantic model changes were needed. `CuratedItem` retains the selected
  `NewsItem` and deterministic final score, not the transient LLM assessment.

## Commands / Tests Run

- `python -m pytest tests/test_curate.py` (could not start: global `python` is not
  available in this shell)
- `.venv/bin/python -m pytest tests/test_curate.py`
- `.venv/bin/python -m pytest`
- `.venv/bin/python -c "import ai_weekly_agent.curate; print('curate import: ok')"`
  (failed because this src-layout package is not installed in the environment)
- `PYTHONPATH=src .venv/bin/python -c "import ai_weekly_agent.curate; print('curate import: ok')"`
- `git diff --check`
- `git status --short`

## Test Results

- 36 Curator tests passed.
- 104 total offline tests passed, including the frozen research suite.
- The import check passed with `PYTHONPATH=src`.
- `git diff --check` passed.
- Zero live OpenAI API calls, `web_search` calls, or other application network
  calls were made. No commit was created.

## Known Issues

- The package is not installed into `.venv`, so a bare interpreter import needs
  `PYTHONPATH=src`. Pytest already configures the source path.
- The threshold and 0.25 diversity window are conservative initial defaults and
  have not been calibrated against live weekly candidate sets.

## Open Questions

None blocking Phase 3.5. Live smoke testing may show whether the initial threshold
or diversity window needs adjustment; they should not be tuned without evidence.

## Recommended Next Step

Phase 3.5: controlled live curation smoke test using a small fixed candidate set.
