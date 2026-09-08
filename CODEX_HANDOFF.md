# Codex Handoff — AI Weekly Agent v0.2 Phase 4.4

## Task

Implement v0.2 Phase 4.4: API-call observation, telemetry aggregation, typed
local RunRecord models, atomic RunRecord persistence, and offline tests.

## Status

Completed.

## Summary

Added a standalone telemetry module that creates stage-labelled observed views
of one existing OpenAI client. Each delegated `responses.parse()` invocation
records one logical call while preserving the exact response or re-raising the
original exception. Added strict token aggregation, typed success/partial-failure
RunRecords, deterministic date-range filenames, and atomic local persistence.
Telemetry is not wired into Main yet.

## Files Changed

- `/home/shanl/ai-weekly-agent/.gitignore`
- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/telemetry.py` (new)
- `/home/shanl/ai-weekly-agent/tests/test_telemetry.py` (new)
- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

No Research, Verify, Curator, Report, Main, prompt, configuration, version, or
generated data file was changed.

## Important Decisions

- `observe_openai_client(base_client, recorder, stage)` uses composition, not
  SDK subclassing. It wraps only the public `responses.parse()` call used by
  the current stages and delegates other attributes to the underlying objects.
- Supported API stage labels are `research`, `curate`, and `report`.
  Verify is intentionally absent because it makes no API call.
- One wrapper invocation creates one logical `ApiCallRecord`, independent of
  any SDK-internal HTTP retry attempts.
- Successful calls return the identical response object. Failed calls record
  safe metadata and re-raise the identical exception object.
- Records contain stage, requested model from the existing `model=` keyword,
  response model, aware UTC timestamps, status, nullable input/output/total
  tokens, and exception class name on failure.
- Usage extraction handles mapping- or attribute-style response objects.
  Missing, partial, malformed, negative, or boolean token values remain `None`;
  they are never converted to zero.
- Aggregation is strict. With zero calls, token totals are known zeros and
  `usage_complete=true`. With calls, completeness requires all three token
  values on every record. If any required value is missing, all aggregate token
  totals are `null` and `usage_complete=false`.
- One `TelemetryRecorder` can be shared by independent research, curate, and
  report views over the same base client. Records retain synchronous completion
  order.
- `RunRecord` uses schema version 1 without changing the package version. It
  stores caller-supplied application version, DateRange, UTC timestamps, run
  status/error stage, nullable reliability settings, call records/totals,
  nullable research/verification/curation counts, and nullable output paths.
  These nullable fields represent partial failed runs honestly.
- Telemetry schemas contain no prompt, instructions, input, output body, API
  key, authorization header, source contents, stack trace, or exception message.
- Run records use `data/runs/<start>_to_<end>.json`, reusing the established
  date-range JSON filename format. `data/runs/*.json` is ignored specifically.
- `save_run_record()` creates the directory, writes and fsyncs a same-directory
  temporary file, then uses `os.replace`. It cleans up temporary files and
  propagates `OSError`. Best-effort persistence is an orchestration policy for
  Phase 4.5; it is not hidden in this low-level function.

## Commands / Tests Run

- Read both identical Phase 4.4 attachments, `AGENTS.md`,
  `CODEX_HANDOFF.md`, date/persistence helpers, package metadata, and current
  client usage with `sed`, `cmp`, `diff`, and `rg`.
- Inspected installed SDK Response/usage fields locally with
  `.venv/bin/python -c ...`.
- Consulted the official OpenAI Responses API reference for response usage
  fields.
- `.venv/bin/python -m pytest tests/test_telemetry.py` (run twice)
- `.venv/bin/python -m pytest`
- `git diff --check`
- `git status --short`
- Checked modified source/test line lengths with `awk`.

## Test Results

- Focused telemetry tests: 21 passed.
- Complete offline suite: 257 passed in 1.35 seconds.
- Zero live OpenAI/model calls and zero project Research/web-search calls were
  made. The only network activity was official OpenAI documentation lookup.

## Compatibility

- Research production behavior changed: no.
- Verify production behavior changed: no.
- Curator production behavior changed: no.
- Report production behavior changed: no.
- Main production behavior changed: no.
- Existing client injection and all prior tests remain functional.
- No telemetry is automatically attached to fallback or Main-owned clients yet.

## Known Issues

- SDK-internal HTTP retry attempts remain invisible; records count logical
  `responses.parse()` invocations only.
- Telemetry cannot recover token usage the API response does not provide.
- Telemetry and RunRecord persistence are not yet wired into Main.
- The stored `api_totals` are supplied from the recorder when constructing a
  RunRecord; Phase 4.5 must continue using that pairing consistently.

## Open Questions

None for Phase 4.4.

## Git Status

Expected final state:

- modified: `.gitignore`
- modified: `CODEX_HANDOFF.md`
- untracked: `src/ai_weekly_agent/telemetry.py`
- untracked: `tests/test_telemetry.py`

No unrelated or generated files are present.

## Recommended Next Step

Implement Phase 4.5 Main integration:

`one configured base OpenAI client -> stage-labelled telemetry views -> Research
-> raw save -> Verify -> Curate -> Report -> report save -> final RunRecord`

Include best-effort RunRecord persistence and documentation updates. Do not
begin that integration as part of Phase 4.4.
