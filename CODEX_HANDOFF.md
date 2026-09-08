# Codex Handoff — AI Weekly Agent v0.2 Phase 4.3

## Task

Implement v0.2 Phase 4.3: configurable OpenAI SDK retries and request timeout,
centralized client construction, and offline tests.

## Status

Completed.

## Summary

Added optional retry and timeout settings to `AppConfig`, parsed them from the
existing environment configuration, and introduced one canonical
`create_openai_client()` factory. Research, Curator, and Report retain their
existing `client=` injection and standalone fallback behavior, but every
production fallback now uses the factory. No telemetry or Verify/Main
integration was introduced.

## Files Changed

- `/home/shanl/ai-weekly-agent/.env.example`
- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/config.py`
- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/research.py`
- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/curate.py`
- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/report.py`
- `/home/shanl/ai-weekly-agent/tests/test_config.py`
- `/home/shanl/ai-weekly-agent/tests/test_research.py`
- `/home/shanl/ai-weekly-agent/tests/test_curate.py`
- `/home/shanl/ai-weekly-agent/tests/test_report.py`
- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

## Important Decisions

- Added `openai_max_retries: int | None` with a minimum of zero and
  `openai_timeout_seconds: float | None` constrained to positive, finite
  values.
- `OPENAI_MAX_RETRIES` accepts integer text, including `0`; non-integer and
  negative values fail clearly. `OPENAI_TIMEOUT_SECONDS` accepts positive
  integer or decimal text; nonnumeric, non-finite, zero, and negative values
  fail clearly.
- Blank or whitespace-only reliability environment values become `None`.
- When retry is unset, `max_retries` is omitted from `OpenAI(...)`. When
  timeout is unset, `timeout` is omitted. This preserves current and future
  SDK defaults rather than copying them into application configuration.
- `max_retries=0` is passed explicitly and is never dropped by truthiness
  handling.
- `create_openai_client()` passes the existing API key and only configured
  optional SDK arguments. It performs no logging, retry loop, transport
  customization, telemetry, or stage-specific work.
- Research, Curator, and Report still accept explicitly injected fake/shared
  clients. When omitted, each stage calls the central factory. Within
  `research_all_categories()`, the one factory-created Research client remains
  shared across all category calls.
- Main remains unchanged to avoid mixing reliability configuration with later
  telemetry/orchestration work. It still causes separate fallback clients for
  Research, Curator, and Report, but all three use the same canonical factory
  and reliability settings. One cross-stage shared client is deferred to the
  telemetry/Main integration phase.
- Official OpenAI Python documentation confirms that retries and timeouts are
  SDK client options; no second application retry system was added.

## Commands / Tests Run

- Read the Phase 4.3 request, `AGENTS.md`, `CODEX_HANDOFF.md`, configuration,
  stage modules, Main, environment example, and relevant tests with `sed` and
  `rg`.
- Consulted the official OpenAI Python API library documentation for SDK retry
  and timeout behavior.
- `.venv/bin/python -m pytest tests/test_config.py`
- `.venv/bin/python -m pytest tests/test_config.py tests/test_research.py tests/test_curate.py tests/test_report.py`
- `.venv/bin/python -m pytest`
- `git diff --check`
- `git status --short`
- `rg -n "\\bOpenAI\\(" src/ai_weekly_agent`
- Scope audit for deferred Verify, telemetry, and RunRecord integration with
  `rg`.

## Test Results

- Configuration-only tests: 26 passed.
- Focused configuration/stage tests: 163 passed.
- Complete offline suite: 236 passed in 1.02 seconds.
- Tests made zero live OpenAI/model calls and zero project Research/web calls.
- The only network activity was official OpenAI documentation lookup.

## Compatibility

- Existing Research, Curator, and Report fake-client injection remains
  functional and is covered by the full regression suite.
- Existing direct stage signatures remain unchanged.
- CLI arguments and progress messages changed: no.
- Research behavior, call budget, and provenance semantics changed: no.
- Curator behavior changed: no.
- Report behavior or Markdown format changed: no.
- Phase 4.1 verification behavior changed: no.
- Main orchestration or Verify integration changed: no.

## Known Issues

- Main does not yet create one client shared across Research, Curator, and
  Report. This is intentionally deferred so telemetry can wrap a single owned
  boundary during later Main integration.
- SDK retry attempts are not observable and response usage remains discarded;
  both remain deferred telemetry concerns.

## Open Questions

None for Phase 4.3.

## Git Status

Expected modified files:

- `.env.example`
- `src/ai_weekly_agent/config.py`
- `src/ai_weekly_agent/curate.py`
- `src/ai_weekly_agent/report.py`
- `src/ai_weekly_agent/research.py`
- `tests/test_config.py`
- `tests/test_curate.py`
- `tests/test_report.py`
- `tests/test_research.py`
- `CODEX_HANDOFF.md`

No unrelated or generated files are present.

## Recommended Next Step

Implement Phase 4.4: telemetry observation, aggregation, and atomic local
`RunRecord` persistence with offline tests only.
