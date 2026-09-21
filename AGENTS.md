# Repository Guidelines

## Product Goal and Audience

This repository's released baseline remains Version 0.5.0 of an AI & Computer
Engineering Weekly Research Agent. The working tree is locally versioned
0.6.0 for release preparation but has not been committed, tagged, pushed, or
released. Version 0.6 focuses on reliable weekly runs and history integrity.
Phase 2C connects the offline-tested immutable persistence core,
manifest-backed history reader, exact-range lock, and per-attempt telemetry to
the normal CLI. The candidate has completed one controlled live validation. Its
target reader is a university Computer Engineering student who is relatively
new to the AI industry. The agent must produce a reliable, approachable weekly
overview without assuming deep industry knowledge, while retaining enough
technical detail to be useful. Keep the architecture small, synchronous,
explicit, and easy for a student to understand and debug.

Each run should research important developments published or announced during the previous seven days in these areas:

- AI model releases
- AI developer tools/frameworks
- AI research
- GPU / semiconductor / AI infrastructure
- robotics / physical AI
- other important computer engineering developments

Prioritize significance over volume. The report is a curated overview, not an exhaustive news feed.

## Current Scope and Pipeline

Keep the implementation intentionally simple and use one linear pipeline:

`lock exact range -> preflight -> Research x6 -> save immutable original raw ResearchRun -> Verify -> load publication history -> Curate -> Grounded Report -> local consistency validation -> save immutable Markdown -> publish manifest -> save attempt RunRecord`

The stages have distinct responsibilities:

1. **Research:** Find candidate developments from the defined seven-day window with `web_search` through the OpenAI Responses API. Capture source URLs, evidence-role classifications, and enough source metadata to verify every candidate.
2. **Raw audit checkpoint:** Persist the original validated `ResearchRun` under `data/raw/` before filtering. Never replace this artifact with verifier output; it must retain items that Verify later rejects.
3. **Verify:** Apply deterministic, local evidence and structure checks without an API or network call. Produce a separate accepted `ResearchRun`; do not mutate the original. Only accepted items proceed to Curator.
4. **Historical load:** Reconstruct previously published stories read-only from authenticated publication manifests, with strict legacy successful-RunRecord compatibility. Treat degraded history conservatively; never restore an item rejected by current Verify.
5. **Curate:** After existing hard filters and exact current-run deduplication, retrieve at most three historical candidates per current item, assess continuity inside the existing single Curate call when needed, remove `REPEAT`, and select accepted developments based on relevance, technical importance, source quality, and usefulness to the target reader.
6. **Grounded Report:** In one non-search Responses API call for a non-empty selection, generate only interpretation and beginner guidance: `story_id`, `what_it_is`, `why_it_matters`, `student_takeaway`, and optional general concept explanations. Empty selections retain the deterministic zero-call report path.
7. **Consistency and rendering:** Validate story and concept IDs locally, reject model-generated URLs, and render authoritative upstream facts, sources, and validated historical context into deterministic Markdown. Do not delegate factual or historical fields back to the Report model.
8. **Save locally:** Attempt raw/report files are immutable. A canonical exact-range manifest is the publication authority. Per-attempt RunRecords summarize stage counts, logical API-call telemetry, reliability settings, publication outcome, artifact paths, and content-free history counts without storing model content or secrets.

Main must create exactly one configured base OpenAI client per normal run, then
inject category-aware observed views into the six sequential Research calls and
stage-labelled observed views into Curator and Report. One telemetry recorder
spans the entire run. Direct standalone calls to those stages may retain their
fallback client creation. A normal successful non-empty run has eight logical
calls: six Research, one Curate, and one Report. An assessed empty selection
uses seven calls, and no prepared Curate candidates uses six. Historical loading
and retrieval are local and add no call. These logical counts do not by
themselves establish token usage or monetary cost. Telemetry records logical
`responses.parse()` calls, not hidden SDK HTTP retries. Research records should
carry their canonical `research_category`; Curate and Report records must keep
that field null. Token totals are complete only when every observed call
supplies all required usage values; never substitute zero for missing usage.

The normal CLI creates one `PublicationStorage` rooted at the current working
directory and holds one non-blocking Linux/WSL exact-range lock from preflight
through best-effort telemetry completion. Save immutable artifacts under
`data/raw/<range>/<run_id>.json` and `reports/<range>/<run_id>.md`, publish
`data/runs/published/<range>.json` last, and save attempt telemetry once at
`data/runs/attempts/<range>/<run_id>/run.json`. `--overwrite` may advance only
the exact range's manifest; it never mutates the prior artifact set. Legacy
top-level raw/report/RunRecord files are read-only compatibility data and are
never migrated automatically.

RunRecord persistence is best-effort observability, not publication authority.
Attempt one final success record after manifest publication or one truthful
partial record after an in-scope pipeline failure. A RunRecord save error must
not invalidate a successful publication or replace the primary pipeline error.
Schema version 1 has an optional strict `publication` summary for the current
attempt; older records without it remain readable.

Do not add a database, vector database, RAG system, web UI, Docker setup, email delivery, scheduled jobs, multi-agent framework, Slack/Discord integration, additional verification fetching, semantic page fact-checking, cost estimation, retry-attempt transport instrumentation, async pipeline, dashboard, or historical analytics in the current scope. Do not introduce abstractions intended only for these out-of-scope features.

## Report Content Requirements

For every important update, the final report must explain:

- What happened and when
- What the product, model, tool, hardware, or research work is
- Who created or published it
- Why it matters
- Important technical details
- Benchmark or performance information when reliable data exists
- A beginner-friendly explanation of unfamiliar concepts and practical significance
- Credible source URLs

Authoritative story identity, order, title, category, organization, published
date, score, summary, technical details, benchmark information, and source
metadata belong to the upstream structured data and deterministic renderer. The
Report model owns only `story_id`, `what_it_is`, `why_it_matters`,
`student_takeaway`, and optional general concept explanations. Stale factual
response fields such as `what_happened`, technical or benchmark rewrites, and a
model-written weekly summary must be rejected rather than rendered.

Local Report validation enforces structural consistency and factual ownership;
it does not establish the semantic truth of webpage content or arbitrary model
interpretation. Do not add natural-language date parsing or another Report API
call to simulate fact-checking.

Do not invent or infer release dates, benchmark numbers, hardware or model specifications, or research results. If reliable information is unavailable, omit the claim or clearly state that it was not independently established. Label company-reported and paper-reported results as such; do not present them as independently verified. Preserve relevant qualifications such as benchmark setup, comparison baseline, hardware, dataset, and evaluation conditions when the source provides them.

## Sources and Research Rules

Prefer primary sources:

- Official company or project announcements
- Official documentation
- Official GitHub repositories and release notes
- Original research papers and arXiv pages
- University and research-lab publications

Use reputable secondary reporting only when it adds necessary context or when no suitable primary source is available. Do not rely on search-result snippets as evidence; open and evaluate the underlying source. Cross-check consequential or surprising claims when practical. A source's publication or update date is not automatically the event's release date, so verify that the development itself falls inside the reporting window.

Every selected item must retain at least one credible URL. Links must resolve to sources that directly support the associated claims. Analysis may simplify technical material for beginners, but simplification must not change the meaning or certainty of the source.

Source evidence roles are model-reported classifications. Deterministic Verify can enforce their presence and consistency with structured fields, but cannot establish the semantic truth of page content or historical claims on mutable product pages. Keep that limitation explicit and do not treat verification success as independent fact-checking.

### Version 0.4 Provenance and Integration

Source-local FactSupport is additive and optional for legacy raw parsing. New
metadata items receive deterministic per-fact primary/original-evidence checks;
entirely legacy historical/manual items retain compatibility behavior with a
lower-assurance warning under standalone default verification. Normal fresh main
execution explicitly passes `require_provenance=True` after saving the unchanged
raw ResearchRun; no fresh candidate may use legacy acceptance to enter Curator.
Do not add a gate opt-out or compatibility retry. All-rejected candidates use the
existing successful empty-report path without Curator/Report API requests.
Curator exact deduplication is implemented: the first qualifying explicit
primary summary/event Source URL plus a known matching date supplies a narrow
cross-category identity proxy. Guard title matches by non-empty organization and
compatible dates, with no conflicting anchors or transitive bridging. Keep one
whole upstream record; never merge facts or metadata. Prefer explicit supporting
evidence, not prose length or background count. Benchmark originals support
evaluation results, not primary event/date quality. Legacy candidates remain
supported and ambiguous duplicates still reach the single semantic assessment.
Verify acceptance counts describe pre-dedup accepted items, not prepared Curator
counts. Keep RunRecord schema 1 and existing truthful empty/failure telemetry.
These model-reported classifications and identity proxies are not independent
semantic verification. The v0.4 release used package/application version
0.4.0; the released package/application version is now 0.5.0. RunRecord schema
remains 1. One approved
Phase 5 live run completed with eight logical calls, eleven strict acceptances,
and ten final stories. No duplicate group occurred live; exact and semantic
duplicate resolution remain offline-tested, not live-proven by that sample.
Keep unknown-date, mutable-page, and single-source limitations explicit; no
additional live run or independent external fact-checking is implied.

### Version 0.5 Historical Awareness (Released)

Historical coverage requires a successful schema-v1 RunRecord, its canonical
raw `ResearchRun`, and its canonical Markdown report. Reconstruct only stories
that occur in the report; raw-only and unselected candidates are not coverage.
Require matching report/raw category, organization, date, normalized title,
normalized summary, exact rendered technical-detail and benchmark sections,
and complete normalized source-URL set. A unique mutable or generic URL is not
sufficient identity. Keep reconciliation conservative and unique; do not add
fuzzy Markdown parsing or a new snapshot artifact.

Load at most the four most recent usable prior runs. This is a run limit, not a
claim of four complete calendar weeks. Exclude the current range and any run
ending on or after the current end date; an earlier-ending overlap may remain
eligible. Enforce configured artifact roots and expected date-based paths.
Classify usable history as `complete` or `partial`; use `unavailable` when no
stories are safely reconstructed. Expected artifact problems degrade with
concise diagnostics. Do not catch unexpected programming errors as missing
history, mutate historical artifacts, fetch historical pages, or add a history
configuration/CLI switch.

Candidate retrieval is deterministic and occurs inside Curate only after current
hard filtering and exact deduplication. It is capped at three historical
candidates per current item and uses explainable shared-URL, guarded exact-title,
or organization-plus-distinctive-title-term signals. Retrieval is permissive and
does not establish coverage, duplication, or semantic truth. Bounded local
retrieval can miss related events.

When complete history has no match, assign local `NEW`; this means new within
the usable local history, not global novelty. When partial history has no match,
assign local `UNCERTAIN`. Unavailable history preserves the no-history contract.
For retrieved candidates, the existing one-call Curate assessment returns
`NEW`, `FOLLOW_UP`, `REPEAT`, or `UNCERTAIN` under strict per-current-item ID and
shape validation. `FOLLOW_UP` must reference exact current verified facts by
summary, technical-detail index, or benchmark field. Those references support
comparison but do not independently prove a material semantic change. Remove
`REPEAT` before semantic deduplication, thresholding, ordering, diversity, and
the item cap.

Strict Verify preserves accepted title, category, organization, date, summary,
technical details, and benchmark fields; it only filters/normalizes Sources and
does not mutate the raw audit artifact. Deterministic Report rendering publishes
those accepted factual fields directly. Historical Curate payloads contain the
reconciled prior factual fields but exclude source URLs, Report interpretation,
artifact paths, diagnostics, and historical model prose. Raw-only or rejected
facts must never be introduced as evidence of prior coverage.

The Report Structured Output contract remains unchanged. Never serialize an
entire `CuratedItem` into its prompt: explicitly exclude `historical_context`,
prior identity, history diagnostics, source URLs, and material-change facts.
Render validated `NEW`, `FOLLOW_UP`, and `UNCERTAIN` context locally. `REPEAT`
must not reach normal rendering. Keep no-history callers compatible.

The optional schema-v1 RunRecord history summary is content-free: load state,
usable runs, reconstructed stories, combined skipped RunRecord/artifact/story
entries, prepared and matched current candidates, validated status totals,
repeats suppressed, and selected follow-ups. Zero means a completed stage saw
none; null means not executed or not established. Invalid assessments, failures,
and interruptions may retain only counts established before they occurred.
Older schema-v1 records without history must remain readable. The released v0.4
Pydantic reader's default extra-field behavior accepts the additive field, but
do not generalize that result to untested external consumers.

The v0.6 Phase 2B/2C development path adds the explicit
`load_publication_history(..., storage=...)` reader while preserving the old
standalone `load_history()` contract. The normal CLI now calls the new reader
exactly once with its single storage object. It discovers canonical publication
manifests and top-level legacy RunRecords under the one supplied trusted root,
chooses authority by exact range before loading, and never scans attempts.
Manifest presence masks same-range legacy data even when the manifest is
invalid, empty, or only partially reconcilable; only absence permits strict
legacy fallback. Unsafe or unreadable manifest discovery fails closed. Parse
only the authenticated raw/report bytes returned by `PublicationStorage`, then
reuse the existing strict parser and story reconciliation. Keep valid-empty and
bad ranges from consuming the usable-run cap, sort by report range rather than
publication time. Exact-range CLI preflight treats a valid empty publication as
published, fails closed on an invalid current manifest or ambiguous current
legacy authority, and does no configuration/client work before that decision.

History is not current evidence verification or independent fact-checking.
Offline mocked classifications validate contracts, not live-model semantic
accuracy. Controlled Curate-only validation found that one ambiguous synthetic
case was classified as `REPEAT` and suppressed in both history-enabled runs,
including after the reviewed prompt clarification, despite the frozen and
offline-adjudicated `UNCERTAIN` expectation. The response was structurally
valid, and the local validator does not prove semantic truth. At its observed
score of 1.00, changing only the status would not have selected it; false
suppression of useful items on other inputs remains possible and unmeasured,
and low scores are not a general mitigation. The user accepted this documented
risk specifically as a known limitation for the v0.5.0 release; the semantic
issue remains unresolved. The live evaluations selected no items, so selected
historical-context rendering and a full v0.5 weekly pipeline remain untested
live. Version 0.5.0 is released; that fact does not authorize another live run
or any later release. Do not claim the issue is fixed or that its semantic
evaluation passed, and do not start additional live validation without separate
authorization.

For local v0.6.0 release preparation, the user separately accepted the
documented residual risks, including the unresolved false-`REPEAT` issue, the
matched-history live-coverage gaps, the single-source/vendor-claim risks, the
incomplete per-tool-call evidence, the unresolved timing difference, and the
Linux/WSL persistence boundaries. Acceptance does not mean these limitations
were fixed and does not authorize staging, commit, tag, push, another live run,
or publication.

## Technology Requirements

Use:

- Python 3.11 or newer
- The official OpenAI Python SDK
- The OpenAI Responses API
- The Responses API `web_search` tool for web research
- Pydantic for typed configuration and structured intermediate data
- pytest for tests

Do not substitute the Chat Completions API or an unrelated scraping/search stack for the required Responses API research flow. Keep model names and run settings configurable rather than scattering them through the code.

## Project Structure and Module Organization

Add production modules under `src/ai_weekly_agent/` and mirror that layout under `tests/` (for example, `src/ai_weekly_agent/research.py` and `tests/test_research.py`). Keep research, deterministic verification, curation, report explanation, Markdown rendering, telemetry, and local persistence as separate concerns, without turning them into a framework. Put reusable prompts in `prompts/` and one-off maintenance utilities in `scripts/`.

Raw research is written under `data/raw/<range>/`, final reports under
`reports/<range>/`, attempt RunRecords under `data/runs/attempts/<range>/`, and
publication manifests under `data/runs/published/`. Code must not assume these
directories already exist. Keep immutable run-ID artifacts and exact-range
manifest identity; do not silently overwrite an existing publication.

The `.agents/` and `.codex/` directories are reserved for agent configuration. Treat `.venv/`, caches, generated research/report output, and local credentials as local-only unless the repository explicitly adopts sanitized fixtures or sample reports. Do not commit generated environments or secrets.

## Build, Test, and Development Commands

- `python3 -m venv .venv` creates the local virtual environment.
- `source .venv/bin/activate` activates it on Linux or macOS.
- `python -m pip install -e ".[dev]"` installs the project and development dependencies in editable mode.
- `python -m pytest` runs the test suite once tests exist.
- `python -m pytest tests/test_research.py -k keyword` runs a focused test selection.

Runtime and development dependencies, Python 3.11+ support, packaging metadata, and console-script entry points are declared in `pyproject.toml`.

## Coding Style and Design Rules

Follow PEP 8 with four-space indentation. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants. Add type hints to public functions. Use Pydantic models at boundaries where research candidates, curated items, report explanations, telemetry, or configuration need validation.

Prefer small functions, explicit dependency injection, and explicit configuration over module-level state. Keep network access, model interaction, validation, deterministic verification, business rules, Markdown rendering, telemetry, and filesystem persistence separable so each can be tested independently. Avoid premature plugin systems, generalized orchestration layers, and speculative abstractions. If introducing Ruff, Black, or another formatter, commit its configuration and apply it repository-wide.

## Testing Guidelines

Use pytest; name files `test_*.py` and tests `test_<behavior>`. Tests must never make real OpenAI API calls or live web requests. Mock or fake the OpenAI client, Responses API results, `web_search` output, and other network boundaries so tests remain deterministic and consume no credentials or quota.

Cover the main pipeline behavior as well as malformed or incomplete model responses, invalid structured data, empty research results, duplicate candidates, dates outside the seven-day window, missing or unsupported citations, retries, external-service failures, partial RunRecords, incomplete usage metadata, and filesystem errors. Test the raw-before-Verify audit invariant, that rejected items do not reach Curator, that unverified benchmark/specification claims are rejected or omitted, and that reports preserve upstream facts and source URLs. Keep regression coverage for the grounded Report response boundary, ordered Research category telemetry, category identity on failed Research calls, category-null Curate/Report records, the one-base-client invariant, and the eight-call normal pipeline. Add a regression test with every bug fix. No coverage threshold is configured yet; new features should exercise their main branches.

For historical awareness, retain coverage for strict three-artifact
reconciliation, raw-only exclusion, mutable-URL identity rejection, current and
future window exclusion, earlier overlap, four-run and three-candidate caps,
complete/partial/unavailable behavior, per-item history-ID validation, exact
current fact references, collector reuse/reset, repeat suppression, Report
prompt isolation, deterministic continuity rendering, null-versus-zero
telemetry, failure/interruption state, path-specific 8/7/7/6 call budgets, and
the production save/render/load round trip. Tests must not describe mocked
continuity classifications as semantic accuracy.

## Security and Configuration

Load API keys and other secrets from environment variables or an ignored `.env` file. `OPENAI_MAX_RETRIES` and `OPENAI_TIMEOUT_SECONDS` are optional; preserve SDK defaults when unset and preserve explicit retry zero. Commit a sanitized `.env.example` when configuration is introduced. Never commit or log API keys, prompts, model response bodies, source contents, full sensitive responses, or user-specific data. Error messages and RunRecords should provide useful operational context without exposing request credentials or sensitive response bodies.

## Commit and Pull Request Guidelines

Use concise Conventional Commit subjects such as `feat: add research collector` or `fix: reject undated candidates`. Keep commits focused. Pull requests should explain the change, list verification commands, link relevant issues, and call out configuration or output-format changes. Include sample output or screenshots when user-visible Markdown formatting changes, but do not include secrets or unreviewed generated research data.

## Codex Handoff

After every meaningful implementation, architecture, review, debugging, or testing task, update the root-level `CODEX_HANDOFF.md` file. The handoff must describe the repository's current state after the latest meaningful task and contain:

- Task
- Status
- Summary
- Files changed
- Important decisions
- Commands/tests run
- Test results
- Known issues
- Open questions
- Recommended next step

Keep the handoff concise and factual. Do not include chain-of-thought, hidden reasoning, or a copy of the entire conversation. Mention exact file paths when files changed and exact commands when tests or scripts ran. Clearly distinguish completed work from proposed work. If no files changed, explicitly say so. If no tests ran, explicitly state why.

Replace the previous handoff with the latest task instead of appending a continuous history. `CODEX_HANDOFF.md` is a repository artifact intended for review and sharing and must not be added to `.gitignore`.
