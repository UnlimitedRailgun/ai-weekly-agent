# AI & Computer Engineering Weekly Research Agent

This project produces a beginner-friendly weekly overview of important AI and
Computer Engineering developments for university students. Version 0.4.0 is
the released baseline. The local worktree is prepared as Version 0.5.0 but is
not published. It adds local historical awareness while keeping the application
small, synchronous, and local-first.

```text
Research ×6
-> save original raw ResearchRun
-> Verify
-> load local report history
-> Curate
-> Grounded Report
-> local consistency validation
-> deterministic Markdown
-> RunRecord
```

## Architecture

Production code lives in `src/ai_weekly_agent/`. A normal run creates one
configured OpenAI client. Lightweight observed views label the six Research
categories, Curate, and Report while sharing one telemetry recorder. Verify and
report consistency validation are deterministic local Python and make no API
calls.

Research results are saved under `data/raw/` before verification. This preserves the original audit artifact, including items that Verify later rejects. Sources may carry model-reported evidence roles such as event, event date, technical, benchmark, or background evidence. Verify checks these classifications and other deterministic rules, but it does not fetch pages or independently prove that a source supports a claim. Rejected items do not reach Curator.

### Version 0.4 provenance support

Sources now optionally carry `fact_support`: summary and benchmark support flags
plus zero-based technical-detail indices. Old raw Research JSON still parses
without migration. The Research prompt requests complete metadata.

`verify_research_run(run, require_provenance=True)` requires explicit support
from model-classified primary/original sources for the summary, known date, and
every technical detail. Original `benchmark` reports may support performance
results but do not qualify for event/date or product-specification coverage.
Missing or contradictory evidence rejects the item without rewriting its facts.
These checks enforce reported provenance consistency, not webpage semantics.

Normal fresh main execution now explicitly requires provenance; entirely legacy
or partially supported fresh candidates cannot enter Curator through compatibility
handling. The raw ResearchRun is saved unchanged before strict filtering.
Standalone `verify_research_run(old_run)` still supports historical JSON with
lower-assurance warnings. Any new metadata activates strict checks even under
that default interface; partial metadata cannot downgrade to legacy handling.
Version 0.4.0 includes this provenance policy while retaining legacy parsing.

### Version 0.4 exact deduplication

Curator now groups candidates across categories using the first explicitly
summary-supporting primary event Source URL and the same known published date.
It reuses Research URL normalization without redirects or query stripping.
This narrow, model-reported URL/date identity proxy is not semantic proof: a
multi-event page can still cause a false merge if misclassified as the anchor.

Title-only matching requires identical normalized titles and non-empty normalized
organizations, no conflicting known dates, and no conflicting explicit anchors.
Unknown dates remain compatible for guarded titles, but cannot bridge conflicting
dated groups. Finalized anchor groups are not regrouped through titles. Arbitrary
shared/background URLs no longer create local identity matches.

Exact groups keep one complete original record, preferring complete provenance,
unique primary factual support, then relevant explicit supporting Sources,
known dates, and original order. No facts, detail order, Sources, or metadata are
merged; prose length and background count do not influence this choice.
Original benchmark evidence may improve benchmark support, not event-primary
quality. Legacy candidates remain supported through guarded title matching.
Unresolved or ambiguous duplicates still reach the existing single non-search
Curator assessment. Historical/manual Curator preparation still supports legacy
candidates, but normal fresh main execution accepts only strict Verify output.

### Version 0.4 integration and validation

Normal runs now use `verify_research_run(run, require_provenance=True)` without
an opt-out, compatibility retry, new setting, or extra API call. Candidate-level
rejection is ordinary filtering, not a whole-run error. If no candidates survive
Verify, six Research calls still occur and the report is rendered locally without
Curator or Report calls. If Curator selects nothing, Report likewise makes no call.

RunRecords retain schema version 1 and distinct research, Verify accepted/rejected,
and final curated counts. Exact dedup does not reduce the Verify accepted count;
no local prepared/dedup counter is stored. Populated successful fake integration
runs exercise eight logical calls, one base client/shared recorder, truthful
usage and failure paths, and unchanged upstream factual Markdown ownership.
One approved live run for 2026-09-06 through 2026-09-12 also completed successfully:
11 raw candidates, 11 strict Verify acceptances, 11 candidates after exact
preparation, and 10 final stories using eight logical calls. Every retained
Source carried FactSupport and evidence roles. No exact or semantic duplicate
group occurred in that sample; duplicate resolution and strict rejection remain
offline-tested rather than demonstrated live by this run. Neither offline tests
nor this single live sample independently verify webpage semantics or establish
universal model compliance. No additional live run is implied or authorized.

### Version 0.5 historical awareness (local release preparation; not published)

The v0.5 development code reconstructs prior coverage from three existing local
artifacts: a successful RunRecord, its canonical raw `ResearchRun`, and its
canonical Markdown report. Raw-only candidates and stories absent from the
report are not treated as previously reported. Reconciliation requires matching
category, organization, date, normalized title, normalized summary, and the
exact rendered technical-detail and benchmark sections, plus the complete
normalized source-URL set; a unique shared mutable URL is not enough.
The loader is read-only and accepts at most the four most recent usable prior
runs. This means four runs, not four guaranteed calendar weeks.

The current window and windows ending on or after its end date are excluded.
An earlier run whose range overlaps the beginning of the current window remains
eligible. Artifact paths must resolve to the expected configured roots and
date-based filenames. Missing, malformed, ambiguous, or unsafe artifacts degrade
history to `partial` or `unavailable` with concise diagnostics instead of being
silently trusted. No history setting or CLI flag has been added.

Historical retrieval runs locally after current Verify, Curator hard filtering,
and exact current-run deduplication. It supplies at most three deterministic
prior candidates per current item. Retrieval signals include a shared source
URL, a guarded exact title, or a non-empty matching organization with at least
two distinctive title terms. These signals identify possible relationships;
they do not prove previous coverage or duplication, and bounded retrieval can
miss related events.

Continuity decisions are split deliberately:

- With complete usable history and no retrieved candidate, local code assigns
  `NEW`: new within the loaded local history, not globally novel.
- With partial usable history and no retrieved candidate, local code assigns
  `UNCERTAIN`.
- With unavailable history, no continuity status is attached.
- When candidates are retrieved, the existing single Curate model call chooses
  `NEW`, `FOLLOW_UP`, `REPEAT`, or `UNCERTAIN` under strict local validation.

`FOLLOW_UP` requires a selected prior candidate and exact references to the
current verified summary, technical-detail index, or benchmark field. Those
references support comparison but do not independently prove the semantic
material-change judgment. A model-assessed `REPEAT` is intended to identify
substantially the same event with no material current development; it is removed
before semantic duplicate resolution, score thresholding, ordering, diversity,
and the item cap. Structural validation does not prove that this semantic label
is correct.

Historical status and resolved current facts are never sent to the Report
model. The Report response contract remains unchanged; local code renders
`NEW`, `FOLLOW_UP`, and `UNCERTAIN` blocks deterministically, and `REPEAT` is
rejected from normal rendering. Historical model judgments are not current
evidence verification or independent fact-checking.

RunRecords retain schema version 1 and may include an optional content-free
history summary: load state, usable-run and reconstructed-story counts, a
combined skipped-entry count, prepared and matched current-candidate counts,
validated status totals, repeats suppressed, and selected follow-up count. A
numeric zero means that stage ran and observed none; `null` means the stage did
not complete or the value was not established. Titles, URLs, facts, prompts,
model output, and artifact paths are not stored in this summary. Current code
loads older schema-v1 records without the field. The released v0.4 Pydantic
reader shape ignores the additive field; no compatibility claim is made for
untested external consumers.

The controlled v0.5 Curate evaluations are recorded in
[`docs/v0.5-validation.md`](docs/v0.5-validation.md). One ambiguous synthetic
case was classified as `REPEAT` and suppressed in both history-enabled runs,
including after a reviewed prompt clarification; its frozen expectation remains
`UNCERTAIN`. The response was structurally valid, so the local validator could
not reject the unsupported semantic judgment. At the observed score of 1.00,
changing only the status would not have selected that case, but false suppression
of useful items on other inputs remains possible and unmeasured. Risk acceptance
is pending user decision. These evaluations did not exercise a live selected
historical-context path or a live full weekly pipeline.

### Grounded reporting

The Report model writes only interpretation and student-focused explanation:
what the development is, why it matters, what the student should learn, and
optional general concept explanations. Authoritative structured facts—including
story order, title, organization, date, summary, technical details, benchmark
information, and sources—remain owned by the upstream data and are rendered
deterministically.

Before Markdown rendering, local consistency checks require exactly one
explanation for every selected story, reject unknown or duplicate story IDs,
validate concept references, and reject model-generated URLs. Keeping factual
fields out of the Report response reduces Report-stage factual drift. It does
not independently fact-check the semantic content of source webpages.

### Persistence and telemetry

Final Markdown reports are stored under `reports/`. A concise operational
RunRecord is atomically written to `data/runs/` after success and is attempted
after pipeline failures. RunRecord persistence is best-effort: failure to save
telemetry cannot invalidate an otherwise successful report or replace the
primary pipeline error.

RunRecords contain logical call stage, status, supported error metadata, token
usage, and Research category identity when the category-aware Research path is
used. A successful run with selected stories uses eight logical Responses API
calls:

```text
6 Research + 1 Curate + 1 Report = 8 logical API calls
```

If Curate assesses candidates but selects none, including an all-repeat result,
the run uses seven calls and renders the empty report locally. If deterministic
preparation produces no Curate candidates, it uses six calls. Historical
loading and retrieval add no call. These unchanged logical request counts do
not establish unchanged token usage or monetary cost.

This describes application-level `responses.parse()` calls, not hidden HTTP
retry attempts inside the OpenAI SDK. A failure can end the run with fewer
logical calls. Missing usage values remain unknown rather than being replaced
with zero.

Generated raw Research JSON, RunRecord JSON, and Markdown reports are local
runtime artifacts and are ignored by Git by default. The RunRecord schema stays
at version 1 in this release; its `application_version` identifies the producing
application release separately.

Each run researches these six canonical categories:

- AI model releases
- AI developer tools/frameworks
- AI research
- GPU / semiconductor / AI infrastructure
- robotics / physical AI
- other important computer engineering developments

The current scope does not include a database, RAG, a vector database, a web UI, a scheduler, Docker, delivery integrations, or a multi-agent framework.

## Installation

Python 3.11 or newer is required.

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the package in editable mode with its development dependencies:

```bash
python -m pip install -e ".[dev]"
```

## Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Set both values in `.env`:

```text
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-model-name
```

Two optional reliability settings are also supported:

```text
OPENAI_MAX_RETRIES=2
OPENAI_TIMEOUT_SECONDS=60
```

When either optional value is omitted, the OpenAI SDK default remains in effect. An explicit retry value of `0` is preserved. The application loads `.env` automatically. Never commit a real API key. Tests mock all network boundaries and do not require any configuration values.

## Run

Run the default seven-calendar-day period ending on the local date:

```bash
ai-weekly
```

The equivalent module command is:

```bash
python -m ai_weekly_agent.main
```

Use an explicit inclusive date range:

```bash
ai-weekly --start 2026-08-30 --end 2026-09-05
```

Or choose a positive number of inclusive calendar days ending today:

```bash
ai-weekly --days 7
```

Final reports are protected from silent replacement. To replace an existing report intentionally, use:

```bash
ai-weekly --overwrite
```

Each run researches all six categories sequentially, preserves the original
structured research, verifies evidence metadata locally, curates accepted
stories with optional local history, obtains grounded explanations in one
non-search Report call, validates the response locally, and writes one Markdown
report. Empty paths make no Report call and distinguish no prepared candidates,
ordinary no-selection, and an all-repeat assessment. CLI
completion output includes the logical API-call count and either a complete
total-token count or an explicit `incomplete telemetry` message.

RunRecords contain operational metadata and counts, not prompts, response
bodies, API keys, request bodies, or source contents.

Expected pipeline, persistence, and configuration failures return a nonzero exit
status with a concise error. The application does not automatically retry a
failed pipeline stage; any HTTP retries are controlled by the OpenAI SDK and the
optional `OPENAI_MAX_RETRIES` setting. A partial RunRecord is attempted after an
in-scope failure without replacing the primary error.

The application does not schedule or automatically trigger weekly runs.

## Limitations

- Verify checks structure, dates, URLs, and model-reported evidence roles
  locally; it does not reopen sources or independently establish semantic truth.
- Research facts remain model-reported and evidence-covered rather than
  independently verified against webpage meaning.
- FactSupport and primary/original source classifications are model-reported.
  Mutable pages may not establish historical launch-time evidence. Unknown
  event dates may remain null with a warning, so weekly inclusion is uncertain.
- Strict Verify rejects an entire candidate when required evidence is missing;
  this favors precision over recall rather than repairing unsupported details.
- Canonical URL/date identity is a conservative proxy that can miss duplicates
  or falsely merge misclassified multi-event pages. Exact merging was not
  exercised in the approved v0.4 live sample. Keeping one whole record discards
  complementary evidence from other duplicate records.
- Historical reconstruction depends on consistent local RunRecord, raw, and
  report artifacts. Partial or unavailable history reduces continuity assurance
  but does not invalidate current source verification.
- Historical retrieval is bounded to four usable earlier runs and three
  candidates per current story. A missing match does not prove global novelty,
  and mutable URLs or conservative title matching can still cause missed or
  spurious candidates.
- Retrieved-candidate classifications are model-assessed semantic judgments.
  Exact current-fact references do not prove that a change is material, and
  offline mocked tests do not establish live-model semantic accuracy.
- A structurally valid `REPEAT` judgment can still be semantically unsupported.
  One ambiguous synthetic case was classified as `REPEAT` and suppressed in
  both evaluated history-enabled runs. It scored below the selection threshold
  in those samples, but low observed scores are not a general safeguard against
  false suppression on other inputs. This risk is unmeasured. The user accepted
  it as a known limitation for v0.5.0 release preparation; the semantic issue
  remains unresolved, and publication has not been authorized.
- The v0.5 live evaluations were Curate-only and selected no stories. They did
  not exercise live selected historical-context rendering or a live full weekly
  pipeline.
- Report interpretations and beginner explanations can still be imperfect even
  though authoritative factual fields are rendered from upstream data.
- Research is synchronous and processes the six categories sequentially.
- Telemetry observes application-level Responses API calls, not hidden SDK HTTP
  retry attempts, and it does not estimate cost.
- Reports and telemetry are local files. There is no scheduler or automatic
  delivery.
- Report filenames use the end date's ISO week; different ranges ending in the
  same week collide unless intentionally overwritten.
- Databases, RAG, a web UI, and historical analytics remain out of scope.

## Tests

Run the tests:

```bash
python -m pytest
```
