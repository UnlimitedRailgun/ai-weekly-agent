# Repository Guidelines

## Product Goal and Audience

This repository contains Version 0.1 of an AI & Computer Engineering Weekly Research Agent. Its target reader is a university Computer Engineering student who is relatively new to the AI industry. The agent must produce a reliable, approachable weekly overview without assuming deep industry knowledge, while retaining enough technical detail to be useful.

Each run should research important developments published or announced during the previous seven days in these areas:

- AI model releases
- AI developer tools and frameworks
- Important AI research
- GPUs, semiconductors, and AI infrastructure
- Robotics and physical AI
- Other important computer engineering developments

Prioritize significance over volume. The report is a curated overview, not an exhaustive news feed.

## Version 0.1 Scope and Pipeline

Keep the implementation intentionally simple and use one linear pipeline:

`Research -> Curate -> Report / Explain -> Save locally`

The stages have distinct responsibilities:

1. **Research:** Find candidate developments from the defined seven-day window with `web_search` through the OpenAI Responses API. Capture source URLs and enough source metadata to verify every candidate.
2. **Curate:** Remove duplicates, exclude items outside the time window, and select developments based on relevance, technical importance, source quality, and usefulness to the target reader.
3. **Report / Explain:** In one non-search Responses API call, explain all selected developments using only supported facts, then render deterministic Markdown with source links close to the claims they support.
4. **Save locally:** Raw research artifacts belong under `data/raw/`; completed weekly reports belong under `reports/`.

Do not add a database, vector database, RAG system, web UI, Docker setup, email delivery, scheduled jobs, multi-agent framework, or Slack/Discord integration in Version 0.1. Do not introduce abstractions intended only for these out-of-scope features.

## Report Content Requirements

For every important update, explain:

- What happened and when
- What the product, model, tool, hardware, or research work is
- Who created or published it
- Why it matters
- Important technical details
- Benchmark or performance information when reliable data exists
- A beginner-friendly explanation of unfamiliar concepts and practical significance
- Credible source URLs

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

Add production modules under `src/ai_weekly_agent/` and mirror that layout under `tests/` (for example, `src/ai_weekly_agent/research.py` and `tests/test_research.py`). Keep research, curation, report explanation, Markdown rendering, and local persistence as separate concerns, without turning them into a framework. Put reusable prompts in `prompts/` and one-off maintenance utilities in `scripts/`.

Raw research should eventually be written under `data/raw/`, and final reports under `reports/`. Code must not assume these directories already exist; the saving stage should create them when needed. Use predictable, date-based filenames and avoid overwriting an existing report silently.

The `.agents/` and `.codex/` directories are reserved for agent configuration. Treat `.venv/`, caches, generated research/report output, and local credentials as local-only unless the repository explicitly adopts sanitized fixtures or sample reports. Do not commit generated environments or secrets.

## Build, Test, and Development Commands

- `python3 -m venv .venv` creates the local virtual environment.
- `source .venv/bin/activate` activates it on Linux or macOS.
- `python -m pip install -e ".[dev]"` installs the project and development dependencies in editable mode.
- `python -m pytest` runs the test suite once tests exist.
- `python -m pytest tests/test_research.py -k keyword` runs a focused test selection.

Runtime and development dependencies, Python 3.11+ support, packaging metadata, and console-script entry points are declared in `pyproject.toml`.

## Coding Style and Design Rules

Follow PEP 8 with four-space indentation. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants. Add type hints to public functions. Use Pydantic models at boundaries where research candidates, curated items, analyzed items, or configuration need validation.

Prefer small functions, explicit dependency injection, and explicit configuration over module-level state. Keep network access, model interaction, validation, business rules, Markdown rendering, and filesystem persistence separable so each can be tested independently. Avoid premature plugin systems, generalized orchestration layers, and speculative abstractions. If introducing Ruff, Black, or another formatter, commit its configuration and apply it repository-wide.

## Testing Guidelines

Use pytest; name files `test_*.py` and tests `test_<behavior>`. Tests must never make real OpenAI API calls or live web requests. Mock or fake the OpenAI client, Responses API results, `web_search` output, and other network boundaries so tests remain deterministic and consume no credentials or quota.

Cover the main pipeline behavior as well as malformed or incomplete model responses, invalid structured data, empty research results, duplicate candidates, dates outside the seven-day window, missing or unsupported citations, retries, external-service failures, and filesystem errors. Test that unverified benchmark/specification claims are rejected or omitted and that reports preserve source URLs. Add a regression test with every bug fix. No coverage threshold is configured yet; new features should exercise their main branches.

## Security and Configuration

Load API keys and other secrets from environment variables or an ignored `.env` file. Commit a sanitized `.env.example` when configuration is introduced. Never commit or log API keys, tokens, full sensitive responses, or user-specific data. Error messages should provide useful context without exposing request credentials or sensitive response bodies.

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
