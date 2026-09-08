# Codex Handoff — AI Weekly Agent v0.2 Phase 4.1

## Task

Implement v0.2 Phase 4.1: additive source evidence-role metadata,
deterministic evidence verification, and offline tests. Do not integrate Verify
into the CLI or implement later v0.2 work.

## Status

Completed.

## Summary

Added backward-compatible evidence roles to `Source`, updated the Research
prompt to classify what each source supports, and added a standalone,
deterministic verifier. Verify returns a separate accepted `ResearchRun` with
typed findings and rejected item IDs; it never mutates the original run and
makes no API or network calls.

## Files Changed

- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/models.py`
- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/research.py`
- `/home/shanl/ai-weekly-agent/src/ai_weekly_agent/verify.py` (new)
- `/home/shanl/ai-weekly-agent/prompts/research.md`
- `/home/shanl/ai-weekly-agent/tests/test_models.py`
- `/home/shanl/ai-weekly-agent/tests/test_research.py`
- `/home/shanl/ai-weekly-agent/tests/test_verify.py` (new)
- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

No CLI, telemetry, reliability configuration, report, Curator, generated data,
or version file was changed.

## Important Decisions

- `Source.evidence_roles` is nullable for v0.1 compatibility and accepts only
  `event`, `event_date`, `technical`, `benchmark`, and `background`. Duplicate
  roles are rejected consistently by Pydantic validation.
- Research now asks for roles that describe what each specific source supports;
  these are model-reported classifications, not independent fact checking.
- Item IDs use one-based input positions in the exact format
  `category_NN:item_NNN`, for example `category_01:item_002`.
- A malformed run raises `VerificationError`. Missing, duplicated, and
  unsupported canonical category results are run-level failures.
- Item hard failures are: no usable HTTP(S) source, category mismatch, known
  event date outside the inclusive window, no `event` evidence for fully
  role-aware data, known date without `event_date` evidence for fully
  role-aware data, and non-empty `benchmark_information` without `benchmark`
  evidence for fully role-aware data.
- Warnings are: an unusable source removed, legacy/mixed missing role metadata,
  unknown event date, all usable sources explicitly typed `secondary`, and
  non-empty `technical_details` without `technical` evidence on fully
  role-aware data.
- URL normalization and normalized-URL duplicate removal produce information
  findings. Verify reuses Research's existing HTTP(S) normalization behavior,
  performs no DNS validation, and changes only copied output objects.
- The dedicated `benchmark_information` field safely establishes when benchmark
  evidence is required; the verifier does not scan prose for keywords.
- Legacy or mixed role-less items warn and skip role-coverage hard failures,
  preventing old v0.1 JSON from being rejected solely for lacking new metadata.
- Provenance from completed web-search calls remains enforced by Research.
  Verify cannot reconstruct or independently check that allow-list from a saved
  `ResearchRun` because the tool-call metadata is not persisted.

## Commands / Tests Run

- `git status --short`
- Read `AGENTS.md`, `CODEX_HANDOFF.md`, the Phase 4.1 request, current models,
  Research implementation/prompt, and relevant tests with `sed` and `rg`.
- `.venv/bin/python -m pytest tests/test_models.py tests/test_research.py tests/test_verify.py`
- `.venv/bin/python -m pytest` (run twice after final refinements)
- `git diff --check`
- `git status --short`

## Test Results

- Focused Phase 4.1 tests: 90 passed.
- Final complete offline suite: 210 passed in 1.61 seconds.
- Zero live OpenAI API calls, web searches, or other network requests were made.

## Known Issues

- Evidence roles are Research-produced metadata and do not prove that a source
  page actually contains the classified evidence.
- Saved `ResearchRun` JSON does not retain the completed web-search provenance
  allow-list, so Verify relies on Research having already enforced provenance.
- To preserve backward compatibility, any usable source with
  `evidence_roles=None` makes role-coverage checks warning-only for that item.
- `source_type` remains a free string in the v0.1 schema. The secondary-only
  warning is therefore emitted only when every usable source is explicitly
  `secondary`; unknown types are not guessed.

## Open Questions

None for Phase 4.1.

## Recommended Next Step

After explicit approval, perform Phase 4.2: one controlled single-category live
Research/Verify compatibility smoke test. Do not integrate Verify into the CLI
or begin telemetry during that smoke test.
