# Codex Handoff — AI Weekly Agent v0.3 Phase 6B

## Task / Status

Prepare and release AI Weekly Agent Version 0.3.0. Final offline validation is
complete; release commit, tag, and push results remain to be recorded.

## Released Version

`0.3.0`

## Release Scope

- Grounded Report contract: authoritative facts remain upstream-owned and are
  rendered deterministically; the Report model supplies interpretation and
  student guidance only.
- Research category telemetry: Research call records retain canonical category
  identity on success and failure, while Curate and Report categories remain
  null and schema-v1 compatibility is preserved.
- The successful non-empty call budget remains six Research calls, one Curate
  call, and one Report call.

## Files Changed for Release Preparation

- `pyproject.toml`: project version changed from `0.2.0` to `0.3.0`.
- `src/ai_weekly_agent/__init__.py`: runtime version changed from `0.2.0` to
  `0.3.0`.
- `README.md`: temporary pre-release wording replaced with released Version 0.3
  wording.
- `CODEX_HANDOFF.md`: replaced the Phase 6A review with this release handoff.

The release commit also contains the 12 previously reviewed Version 0.3
implementation, test, prompt, and documentation changes listed in the final
diff summary.

## Version Consistency

Active project metadata, runtime source, runtime import, and refreshed editable
installation metadata all report `0.3.0`. The ignored Phase 5 RunRecord remains
unchanged at `0.2.0` because it truthfully identifies the build used for that
controlled live validation.

## Commands / Tests Run

Commands run include:

```bash
git status --short
git branch --show-current
git remote -v
git log --oneline --decorate -5
git tag --list --sort=version:refname
git diff --check
git diff --stat
git diff
git grep -n -E '0\.2\.0|0\.3\.0|v0\.2\.0|v0\.3\.0'
.venv/bin/python -m pytest
.venv/bin/python -m ai_weekly_agent.main --help
.venv/bin/ai-weekly --help
.venv/bin/ai-weekly-agent --help
.venv/bin/python -c "import ai_weekly_agent; print(ai_weekly_agent.__version__)"
.venv/bin/python -c "from importlib.metadata import version; print(version('ai-weekly-agent'))"
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
git check-ignore -v .env data/raw/2026-09-06_to_2026-09-12.json reports/2026-W37.md data/runs/2026-09-06_to_2026-09-12.json
git grep -l -E 'sk-[[:alnum:]_-]{20,}'
git ls-files --others --exclude-standard
```

The first editable-install refresh could not obtain isolated build tooling in
the restricted environment. The no-build-isolation attempt found no local
setuptools in the virtualenv. The authorized retry of
`.venv/bin/python -m pip install --no-deps -e .` then succeeded using the
declared build requirement. No dependency declaration changed.

No live OpenAI or project web request was made during Phase 6B.

## Test Results

- Complete offline suite: **295 passed in 1.46 seconds**.
- All three supported CLI help paths passed.
- `git diff --check` passed.
- Runtime and editable package metadata both report `0.3.0`.
- `.env` and the Phase 5 raw, report, and RunRecord artifacts remain ignored.
- No tracked API-key-shaped value, unignored artifact, debug file, or temporary
  file was found.

## Final Diff Summary

The reviewed release diff contains exactly 14 approved tracked files: the 12
Version 0.3 implementation, prompt, test, and documentation changes approved in
Phase 6A, plus `pyproject.toml` and `src/ai_weekly_agent/__init__.py`. No
unrelated tracked file or generated runtime artifact appears.

## Release Commit

Pending creation.

## Annotated Tag

Pending creation of `v0.3.0`.

## Push Status

Pending safe authentication check and push to the configured `origin` remote.

## GitHub Release Status

Not published. Release notes are prepared below; publication status will be
updated after the commit/tag push attempt.

## Known Limitations

- Verification validates evidence coverage and structure, not independent
  semantic webpage fact-checking.
- Primary sources are preferred but not mandatory; secondary-only stories may
  proceed with a warning.
- Logical telemetry does not expose hidden SDK transport retries.
- ISO-week report filenames may collide for overlapping explicit date ranges.
- Reports and run artifacts remain local, and execution remains manually
  triggered.

## Final Release Notes

### AI Weekly Agent v0.3.0

#### Highlights

- **Grounded reporting** — authoritative story facts remain in upstream
  structured data while the Report model is limited to interpretation and
  student-oriented explanation.
- **Deterministic factual rendering** — summaries, technical details, benchmark
  information, sources, and the five-story at-a-glance section are rendered
  directly from structured data.
- **Research category telemetry** — logical Research call records identify their
  canonical category on both success and failure.

#### Reliability and validation

- Strict Report response models reject stale factual output fields.
- Local consistency validation checks story/concept identity and prohibited
  model-generated URLs.
- Research category telemetry remains backward-compatible with schema-v1
  RunRecords.
- The complete offline suite passes with 295 tests.
- A controlled six-category live validation completed with 14 raw Research
  candidates, 13 Verify-accepted candidates, 11 final stories, eight logical
  API calls, and no observed Grounded Report factual-ownership drift.

#### Architecture

The normal successful non-empty pipeline remains:

```text
Research ×6
→ raw Research save
→ Verify
→ Curate
→ Grounded Report
→ deterministic Markdown
→ schema-v1 RunRecord
```

Expected logical API budget: `6 Research + 1 Curate + 1 Report = 8`.

#### Known limitations

- Verification validates evidence coverage and structure; it is not independent
  semantic webpage fact-checking.
- Primary sources are preferred but not mandatory; secondary-only stories may
  proceed with warnings.
- Logical telemetry does not expose hidden SDK transport retry attempts.
- ISO-week report filenames may collide for overlapping explicit date ranges.
- Reports and run artifacts remain local, and execution is manually triggered.

## Open Questions

None blocking the local release. GitHub Release page publication depends on the
available authenticated release workflow after the tag is pushed.

## Recommended Next Development Direction

Publish the GitHub Release from `v0.3.0` if it is not published in this phase,
then plan Version 0.4 separately. Candidate future work includes collision-safe
explicit-range report filenames and a reviewed policy for secondary-only
sources. Do not begin Version 0.4 implementation as part of Phase 6B.
