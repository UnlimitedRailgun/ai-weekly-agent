# Codex Handoff — AI Weekly Agent v0.2 Phase 4.6

## Task

Complete the full v0.2 end-to-end live validation by inspecting the artifacts
from the user's successful manual CLI run, reconciling telemetry, and running
offline regression tests.

## Status

Passed.

## Summary

The successful live run completed the integrated pipeline and produced valid
raw Research, Markdown, and RunRecord artifacts. Offline Verify reproduced the
CLI counts without mutating Research. All eight logical API calls and the
271,930-token total reconcile exactly. The offline suite remains green and no
application defect was found.

## Live Attempts

### Attempt 1

- One Research logical call failed with external `APIConnectionError` while
  `OPENAI_MAX_RETRIES=0`.
- A truthful partial-failure RunRecord was saved with no raw/report artifact and
  no invented downstream counts.
- This live attempt validated the partial-failure observability path. The later
  success RunRecord atomically replaced the same-range failure record.

### Attempt 2

- The user manually performed one successful full E2E CLI run.
- Its artifacts and RunRecord are authoritative for the metrics below.

## Live Configuration

- Date range: `2026-08-30` through `2026-09-05`, inclusive.
- Requested and response model: `gpt-5.6-terra` on all eight calls.
- `OPENAI_MAX_RETRIES=0` explicitly.
- `OPENAI_TIMEOUT_SECONDS=None`; no SDK default was inferred.
- `--overwrite` was not used; target artifacts did not previously exist.
- Approximate duration from RunRecord timestamps: 295.8 seconds.
- Application version remained `0.1.0`, as required before Phase 4.7.

## Pipeline Outcome

Successful order:

`Research -> raw save -> Verify -> Curate -> Report -> Markdown save ->
RunRecord save`

All stages and all three persistence checkpoints completed.

## Research Statistics

- DateRange parsed correctly through `ResearchRun`.
- Canonical categories: 6, each present exactly once.
- Original items: 16.
- Source records: 19; usable sources: 19.
- `evidence_roles=None`: 0.
- Empty evidence-role lists: 0.
- Non-empty evidence-role lists: 19.
- Role occurrences: `event` 17, `event_date` 17, `technical` 19,
  `benchmark` 4, `background` 0.
- Pydantic parsing found no invalid evidence roles. Evidence roles remain
  model-reported classifications, not independent proof of page content.
- Phase 4.2's 7/7 role-aware one-category result generalized to 19/19 sources
  across all six categories.

## Verification Statistics

- Original items: 16.
- Accepted: 16.
- Rejected: 0.
- Warnings: 1.
- Information findings: 0.
- Finding: `category_05:item_001`, code `secondary_sources_only`, for
  "ABEJA and Murata demonstrated a dual-arm VLA manipulation workflow for
  laboratory automation". Deterministic reason: every usable source was
  classified as secondary.
- The input `ResearchRun` serialized identically before and after offline
  Verify.
- The live run did not exercise rejected-item raw persistence, but that
  invariant remains covered by offline Main integration tests.

## Curator and Report Statistics

- Items entering Curator: 16.
- Curated items: 12; `MAX_CURATED_ITEMS=12` was respected.
- All 12 report story titles occur in raw Research.
- No exact or normalized duplicate story heading was found.
- Report: 35,364 bytes, 480 lines, 12 represented stories, and 24 Markdown
  source links.
- Expected sections are present: title, `This Week in 60 Seconds`,
  `Major Updates`, `Concepts Worth Learning`, and `Source Index`.
- No unresolved template placeholder, raw JSON/Pydantic/debug marker,
  telemetry field, API-key variable, authorization marker, or credential-like
  `sk-...` token was found.

## Telemetry

RunRecord schema version 1 parsed successfully with `status=success`, null
`error_stage`, the exact DateRange, `max_retries=0`, and null timeout.

| # | Stage | Requested model | Response model | Status | Input tokens | Output tokens | Total tokens |
| -: | --- | --- | --- | --- | ---: | ---: | ---: |
| 1 | research | gpt-5.6-terra | gpt-5.6-terra | success | 39,410 | 2,314 | 41,724 |
| 2 | research | gpt-5.6-terra | gpt-5.6-terra | success | 40,980 | 1,968 | 42,948 |
| 3 | research | gpt-5.6-terra | gpt-5.6-terra | success | 40,290 | 2,108 | 42,398 |
| 4 | research | gpt-5.6-terra | gpt-5.6-terra | success | 40,870 | 1,600 | 42,470 |
| 5 | research | gpt-5.6-terra | gpt-5.6-terra | success | 38,262 | 2,030 | 40,292 |
| 6 | research | gpt-5.6-terra | gpt-5.6-terra | success | 41,136 | 1,854 | 42,990 |
| 7 | curate | gpt-5.6-terra | gpt-5.6-terra | success | 7,748 | 621 | 8,369 |
| 8 | report | gpt-5.6-terra | gpt-5.6-terra | success | 5,627 | 5,112 | 10,739 |

- Logical calls: 8 successful, 0 failed.
- Stage distribution: Research 6, Curate 1, Report 1, Verify 0.
- Aggregate usage: 254,323 input, 17,607 output, 271,930 total tokens;
  `usage_complete=true`.
- Per-call sums equal every stored aggregate exactly.

| Stage | Calls | Input tokens | Output tokens | Total tokens | % of total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Research | 6 | 240,948 | 11,874 | 252,822 | 92.97% |
| Curate | 1 | 7,748 | 621 | 8,369 | 3.08% |
| Report | 1 | 5,627 | 5,112 | 10,739 | 3.95% |

Research call totals ranged from 40,292 to 42,990, averaging 42,137. The
maximum was 2.02% above the mean and the minimum 4.38% below it, so no single
Research call is a clear outlier. Telemetry does not store Research category,
so individual Research calls cannot be mapped to categories without guessing.
The large total is internally consistent and is concentrated across all six
Research calls; it is not evidence of a telemetry defect. No quantitative
v0.1 comparison is available.

## Artifacts

- `data/raw/2026-08-30_to_2026-09-05.json`: exists, valid `ResearchRun`, and
  preserves all 16 original items.
- `reports/2026-W36.md`: exists, non-empty, and structurally valid.
- `data/runs/2026-08-30_to_2026-09-05.json`: exists, valid `RunRecord`, with
  matching recorded path and existing raw/report paths.

All three are ignored by current repository policy and remain uncommitted.
They were inspected but not modified.

## v0.1 Compatibility

| Area | v0.1 expectation | v0.2 observed result |
| --- | --- | --- |
| Six-category Research | yes | completed 6/6 |
| Raw Research saved | yes | valid original 16-item JSON |
| Curator call | yes | completed once with 16 accepted items |
| Report call | yes | completed once |
| Markdown report | yes | valid 12-story report |
| Deterministic Verify | no | completed locally, no API call |
| Evidence filtering | no | 16 accepted, 0 rejected, 1 warning |
| API telemetry | no | 8 coherent logical-call records |
| Token accounting | no | complete and exactly reconciled |
| RunRecord | no | valid successful schema-v1 artifact |

The v0.1 external Research, Curator, Report, raw-save, and Markdown behaviors
remain present. v0.2 adds Verify and observability without changing report
format or overwrite semantics.

## Files Changed

- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

No production code, tests, prompts, README, AGENTS guidance, version metadata,
or generated artifact was changed.

## Important Decisions

- Attempt 2's success RunRecord is authoritative for success metrics; Attempt
  1 is documented separately as a successful partial-failure-path exercise.
- `271,930` is accepted as correctly recorded because all per-call, per-stage,
  and aggregate values reconcile exactly.
- The secondary-source warning is an expected evidence-quality diagnostic, not
  an integration or schema defect.

## Commands / Tests Run

- Parsed raw Research with `ResearchRun.model_validate_json(...)` and reran
  `verify_research_run(...)` offline.
- Parsed telemetry with `RunRecord.model_validate_json(...)` and calculated
  per-call/per-stage reconciliation locally.
- Inspected report structure and safe leak markers with local Python and `rg`.
- `.venv/bin/python -m pytest`
- `git diff --check`
- `git status --short`
- `git check-ignore -v` for all three generated artifacts.

## Test Results

- Final offline suite: 269 passed in 1.05 seconds.
- `git diff --check`: passed before the handoff-only update.
- Tracked worktree was clean before this handoff-only update.
- Live API/model calls during this inspection: 0.
- Production code changes: 0.

## Known Issues

- Evidence roles remain model-reported classifications.
- Deterministic Verify cannot semantically prove historical claims on mutable
  product pages.
- SDK-internal HTTP retry attempts remain invisible to logical-call telemetry.
- Research category identity is not recorded per telemetry call.
- The first live attempt encountered a transient external connection failure;
  retry-zero behavior and partial-failure persistence worked as designed.

## Open Questions

None blocking Phase 4.7.

## Git Status

Expected final tracked state:

- modified: `CODEX_HANDOFF.md`

The three live artifacts remain ignored and uncommitted.

## Recommended Next Step

Proceed to Phase 4.7:

`final v0.2 release-readiness review -> version bump from 0.1.0 to 0.2.0 ->
final regression -> release commit/checkpoint -> tag v0.2.0 -> GitHub Release`

Do not perform these release actions as part of Phase 4.6.
