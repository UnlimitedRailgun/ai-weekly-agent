# Codex Handoff — AI Weekly Agent v0.4 Phase 6B

## Task

Publish the approved Version 0.4.0 release from the completed Phase 6B.1
release-unblock state: review and verify the release diff, create one release
commit and annotated tag, push `main` and `v0.4.0` to the approved origin, and
create and verify the GitHub Release when authenticated tooling is available.

## Status

**Release preparation complete; external publication authorized and in progress.**
This handoff is intentionally truthful at the release-commit boundary. The final
task result records the verified post-commit and external publication state; the
annotated tag must not be moved merely to update this file afterward.

## Released Version / Previous Baseline

- Release target: `0.4.0`.
- Previous released baseline: annotated `v0.3.0` at
  `226b3e68defa6e13e3abeef14efb070e8989158e`.
- Authoritative version files: `pyproject.toml` and
  `src/ai_weekly_agent/__init__.py`.
- Refreshed editable distribution, imported `__version__`, and project metadata
  all report `0.4.0`.

## Summary / Final Version 0.4 Scope

- Added source-local `FactSupport` for summaries, technical details, and
  benchmark information.
- Added deterministic per-fact primary/original-evidence checks. Fresh Main
  execution requires provenance; historical standalone validation retains an
  explicit lower-assurance compatibility path.
- Added conservative cross-category exact deduplication using a qualifying
  primary event URL plus known date, guarded exact-title matching, and
  evidence-aware whole-record representative selection without fact merging.
- Corrected benchmark semantics: original benchmark evidence can support an
  evaluation result, but cannot substitute for primary event/date or product
  specification evidence.
- Preserved grounded Report factual ownership, deterministic Markdown,
  schema-v1 RunRecords, and the normal populated eight-call architecture:
  six Research calls, one Curate call, and one Report call.
- Included the Phase 6B.1 clock fix: if the sampled finish wall-clock time is
  earlier than start, Main warns and omits the invalid best-effort RunRecord.
  It does not fabricate/clamp time, and saved-report or primary-failure behavior
  remains authoritative.

## Files Changed

The release commit contains exactly these reviewed tracked files:

- `AGENTS.md`
- `CODEX_HANDOFF.md`
- `README.md`
- `prompts/research.md`
- `pyproject.toml`
- `src/ai_weekly_agent/__init__.py`
- `src/ai_weekly_agent/curate.py`
- `src/ai_weekly_agent/main.py`
- `src/ai_weekly_agent/models.py`
- `src/ai_weekly_agent/verify.py`
- `tests/test_curate.py`
- `tests/test_main.py`
- `tests/test_models.py`
- `tests/test_research.py`
- `tests/test_verify.py`

No generated output, credential, environment, cache, egg-info/build output, raw
Research JSON, RunRecord JSON, weekly report, or temporary diagnostic is part of
the reviewed release diff.

## Important Decisions

- `FactSupport` and evidence-role/source-type classifications remain
  model-reported metadata. Verify checks structural consistency and explicit
  coverage; it is not independent webpage semantic fact-checking.
- Normal fresh execution has no provenance opt-out or compatibility retry.
- Exact deduplication uses a narrow identity proxy and keeps one complete
  upstream record. It does not merge complementary evidence from duplicates.
- Unknown dates remain allowed with an explicit warning; weak stories are not
  invented to fill categories.
- RunRecord schema remains 1. Logical call telemetry does not instrument hidden
  SDK HTTP retries.
- An inverted run wall clock results in an explicit warning and no RunRecord,
  rather than false timestamps or a changed primary outcome.
- One release commit and one immutable annotated `v0.4.0` tag are preferred.

## Commands / Tests Run

Final Phase 6B verification:

```bash
.venv/bin/python -c 'from importlib.metadata import version; from ai_weekly_agent import __version__; assert version("ai-weekly-agent") == __version__ == "0.4.0"; print(__version__)'
.venv/bin/python -m pytest
.venv/bin/python -m ai_weekly_agent.main --help
.venv/bin/ai-weekly --help
.venv/bin/ai-weekly-agent --help
git diff --check
git status --short
```

Release preflight also used:

```bash
git remote -v
git branch --show-current
git status --short --untracked-files=all
git tag --list v0.4.0
git diff --check
git diff --cached --stat
git diff --numstat
git diff
```

Phase 6B.1 additionally ran the seven targeted suites, focused backwards-clock
regressions, repeated socket-blocked full suites, editable-install/version
checks, CLI checks, and artifact-hygiene checks recorded in that task result.
No OpenAI Responses, `web_search`, weekly-pipeline, external fact-checking, or
other product-network request was made during release preparation.

## Test Results

- Final ordinary offline suite: **478 passed in 4.16s**.
- Phase 6B.1 seven targeted suites: **442 passed**.
- Phase 6B.1 focused backwards-clock regressions: **3 passed**.
- Phase 6B.1 three consecutive socket-blocked full suites: **478 passed each**,
  with zero connection attempts.
- Phase 6B.1 separate final socket-blocked suite: **478 passed**, zero attempts.
- All three supported CLI help entry points passed.
- Editable-package/public version assertion printed `0.4.0` and passed.
- `git diff --check` passed.

Before the bounded clock fix, intermittent guarded full-suite failures exposed
inverted wall-clock samples at RunRecord construction. A controlled rollback
reproduced the defect. The final results above are post-fix; the earlier failures
are not presented as release-validation passes.

## Phase 5 Controlled Live Summary

One approved live run for 2026-09-06 through 2026-09-12 used the normal pipeline:
11 raw candidates, 11 strict Verify acceptances, 11 prepared candidates, 10
final stories, eight logical Responses calls, and 266,276 reported tokens. All
retained Sources carried `FactSupport` and evidence-role metadata; all 44
technical details and all 3 non-null benchmark fields had explicit model-reported
support. No duplicate group occurred in that sample, so exact and semantic
duplicate handling remain offline-tested rather than live-demonstrated.

## Release Publication Record

- Release commit SHA: pending at release-commit boundary; final task result.
- Annotated tag object: pending; final task result.
- Annotated tag peeled commit: pending; final task result.
- Approved origin: `https://github.com/UnlimitedRailgun/ai-weekly-agent.git`.
- Branch push: pending; final task result.
- Tag push: pending; final task result.
- Remote branch SHA: pending; final task result.
- Remote peeled tag SHA: pending; final task result.
- GitHub Release status: pending; final task result.
- GitHub Release title: `AI Weekly Agent v0.4.0 — Evidence Provenance and Research Quality`.
- GitHub Release URL: pending; final task result.

## Known Issues / Limitations

- Provenance metadata is not independent semantic proof, and mutable pages may
  not establish historical launch-time evidence.
- The conservative URL/date identity proxy can miss duplicates or theoretically
  merge distinct events when upstream metadata is wrong.
- Whole-record representative selection intentionally discards complementary
  evidence from losing duplicates.
- Strict candidate rejection favors precision over recall.
- The approved live sample did not exercise an exact duplicate group.
- ISO-week report filenames can collide for different ranges ending in the same
  week, and hidden SDK HTTP retries remain uninstrumented.
- A backwards run clock causes best-effort RunRecord loss with a warning.

## Open Questions / Remaining Publication Issue

No local release blocker remains. At this release-commit boundary, Git/GitHub
publication and its remote verification are the only pending external steps.

## Recommended Next Step

Complete and verify the authorized `main` and `v0.4.0` publication plus the
normal GitHub Release. After release, consider future themes such as improving
source classification quality, collision-safe report naming, and deciding
whether duplicate evidence merging is justified. Do not begin Version 0.5 in
this task.
