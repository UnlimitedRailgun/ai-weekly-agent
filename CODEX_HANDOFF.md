# Codex Handoff — AI Weekly Agent v0.2 Phase 4.5

## Task

Integrate the completed v0.2 Verify, client configuration, and telemetry
components into the real Main/CLI pipeline.

## Status

Completed.

## Summary

Main now runs the integrated synchronous pipeline, writes success or truthful
partial-failure RunRecords from current telemetry, and reports concise
verification/API usage summaries. Documentation and offline Main integration
coverage now reflect the implemented behavior. Package metadata remains
`0.1.0`.

## Integrated Pipeline

Implemented order:

`Research -> save original raw ResearchRun -> Verify -> Curate accepted run ->
Report -> save Markdown -> construct RunRecord -> best-effort save RunRecord`

## Client Ownership

- Main creates exactly one configured base OpenAI client per normal run with
  `create_openai_client(config)`.
- Research, Curator, and Report receive separate stage-labelled observed views
  over that same base client and one shared `TelemetryRecorder`.
- Verify receives no client and makes no API or network call.
- Direct standalone calls to Research, Curator, and Report retain their existing
  fallback client creation.

## Raw Audit Invariant

- The original `ResearchRun` is saved before Verify and is not mutated.
- Verifier-rejected items remain in raw JSON.
- Curator receives only `verification_result.accepted_run`.

## Telemetry and RunRecord Behavior

- One recorder spans all Research, Curator, and Report calls and is read only
  when the final success or partial-failure record is constructed.
- Records represent logical `responses.parse()` calls, including failed calls;
  SDK-internal HTTP retry attempts remain invisible.
- Numeric totals are emitted only when usage is complete. Any missing usage
  makes all token totals null and the CLI prints `Tokens: incomplete telemetry`.
- Success records include current version, range/timestamps, configured retry
  and timeout values, API records/totals, original Research counts, Verify
  counts, curated count, and successful artifact paths.
- Failures in Research, Verify, Curator, Report, raw save, or report save attempt
  a partial record with unknown downstream values left null.
- RunRecords use `data/runs/<start>_to_<end>.json`. Persistence is best-effort,
  is not retried, cannot invalidate a successful report, and cannot replace the
  primary pipeline failure.

## CLI Compatibility

- Date arguments, `--overwrite`, report naming, report format, and raw JSON
  format are unchanged.
- Progress now includes Verify. Successful output adds verification counts,
  RunRecord path when saved, logical API-call count, and strict token status.
- The report collision check still occurs before configuration and expensive
  Research work.

## Files Changed

- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/main.py`
- `/home/shanl/ai-weekly-agent/tests/test_main.py`
- `/home/shanl/ai-weekly-agent/README.md`
- `/home/shanl/ai-weekly-agent/AGENTS.md`
- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

No stage implementation, prompt, model, configuration, telemetry schema,
package-version, raw data, report, or committed generated-output file changed.

## Important Decisions

- Raw persistence remains before deterministic verification.
- Main uses the existing typed verification result and finding severities; it
  does not duplicate verifier rules.
- Artifact paths are populated only after successful saves. The intended
  RunRecord path is recorded using the Phase 4.4 filename convention.
- RunRecord failure warnings go to stderr while preserving the primary result.
- Unexpected programming errors remain unswallowed, matching prior behavior.

## Commands / Tests Run

- Consulted the official OpenAI Responses API reference for response usage and
  built-in-tool metadata; this was documentation lookup only.
- `.venv/bin/python -m pytest tests/test_main.py`
- `.venv/bin/python -m pytest`
- `git diff --check`
- `git status --short`
- Inspected ignored output directories with `find`, `stat`, and
  `git status --short --ignored`.

## Test Results

- Focused Main/integration suite: 40 passed.
- Complete offline suite: 269 passed in 1.07 seconds.
- Zero live model calls and zero project Research/web-search calls were made.
- No new generated raw, report, or RunRecord artifact remains in the repository.

## Known Issues

- Evidence roles remain model-reported classifications.
- Deterministic Verify cannot semantically prove historical claims on mutable
  product pages.
- SDK-internal HTTP retry attempts remain invisible to logical-call telemetry.
- Token usage remains incomplete when a response omits required usage metadata.

## Open Questions

None for Phase 4.5.

## Git Status

Expected final state:

- modified: `AGENTS.md`
- modified: `CODEX_HANDOFF.md`
- modified: `README.md`
- modified: `src/ai_weekly_agent/main.py`
- modified: `tests/test_main.py`

## Recommended Next Step

Perform Phase 4.6: one controlled full v0.2 end-to-end live CLI run for a
single weekly range, comparing output and telemetry behavior against v0.1
expectations. Do not begin Phase 4.6 as part of this task.
