# Repository Guidelines

## Product Goal and Audience

This repository contains Version 0.4.0 of an AI & Computer Engineering Weekly
Research Agent. Its target reader is a university Computer Engineering student
who is relatively new to the AI industry. The agent must produce a reliable,
approachable weekly overview without assuming deep industry knowledge, while
retaining enough technical detail to be useful. Keep the architecture small,
synchronous, explicit, and easy for a student to understand and debug.

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

`Research x6 -> save original raw ResearchRun -> Verify -> Curate -> Grounded Report -> local consistency validation -> deterministic Markdown -> save report -> RunRecord`

The stages have distinct responsibilities:

1. **Research:** Find candidate developments from the defined seven-day window with `web_search` through the OpenAI Responses API. Capture source URLs, evidence-role classifications, and enough source metadata to verify every candidate.
2. **Raw audit checkpoint:** Persist the original validated `ResearchRun` under `data/raw/` before filtering. Never replace this artifact with verifier output; it must retain items that Verify later rejects.
3. **Verify:** Apply deterministic, local evidence and structure checks without an API or network call. Produce a separate accepted `ResearchRun`; do not mutate the original. Only accepted items proceed to Curator.
4. **Curate:** Remove duplicates and select accepted developments based on relevance, technical importance, source quality, and usefulness to the target reader.
5. **Grounded Report:** In one non-search Responses API call for a non-empty selection, generate only interpretation and beginner guidance: `story_id`, `what_it_is`, `why_it_matters`, `student_takeaway`, and optional general concept explanations. Empty selections retain the deterministic zero-call report path.
6. **Consistency and rendering:** Validate story and concept IDs locally, reject model-generated URLs, and render authoritative upstream facts and sources into deterministic Markdown. Do not delegate factual fields back to the Report model.
7. **Save locally:** Completed weekly reports belong under `reports/`. Operational RunRecords belong under `data/runs/` and summarize stage counts, logical API-call telemetry, reliability settings, outcomes, and artifact paths without storing model content or secrets.

Main must create exactly one configured base OpenAI client per normal run, then
inject category-aware observed views into the six sequential Research calls and
stage-labelled observed views into Curator and Report. One telemetry recorder
spans the entire run. Direct standalone calls to those stages may retain their
fallback client creation. A normal successful non-empty run has eight logical
calls: six Research, one Curate, and one Report. Telemetry records logical
`responses.parse()` calls, not hidden SDK HTTP retries. Research records should
carry their canonical `research_category`; Curate and Report records must keep
that field null. Token totals are complete only when every observed call
supplies all required usage values; never substitute zero for missing usage.

RunRecord persistence is best-effort observability. Attempt a success record after the report is saved and a truthful partial record after an in-scope pipeline failure. A RunRecord save error must not invalidate a successful report or replace the primary pipeline error. Use `data/runs/<start>_to_<end>.json`; atomic replacement for the same date range is allowed independently of report `--overwrite` behavior.

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
semantic verification. Package/application version is 0.4.0; RunRecord schema
remains 1. One approved
Phase 5 live run completed with eight logical calls, eleven strict acceptances,
and ten final stories. No duplicate group occurred live; exact and semantic
duplicate resolution remain offline-tested, not live-proven by that sample.
Keep unknown-date, mutable-page, and single-source limitations explicit; no
additional live run or independent external fact-checking is implied.

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

Raw research is written under `data/raw/`, final reports under `reports/`, and RunRecords under `data/runs/`. Code must not assume these directories already exist; the saving stage should create them when needed. Use predictable, date-based filenames and avoid overwriting an existing report silently.

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
