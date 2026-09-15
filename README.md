# AI & Computer Engineering Weekly Research Agent

This project produces a beginner-friendly weekly overview of important AI and
Computer Engineering developments for university students. Version 0.3 is
deliberately small, synchronous, and local-first, with grounded report output
and per-category Research telemetry.

```text
Research ×6
-> save original raw ResearchRun
-> Verify
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
used. A normal successful non-empty run is expected to use eight logical
Responses API calls:

```text
6 Research + 1 Curate + 1 Report = 8 logical API calls
```

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
stories, obtains grounded explanations in one non-search Report call, validates
the response locally, and writes one Markdown report. An empty curated result
uses the existing deterministic empty report and makes no Report call. CLI
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
- Report interpretations and beginner explanations can still be imperfect even
  though authoritative factual fields are rendered from upstream data.
- Research is synchronous and processes the six categories sequentially.
- Telemetry observes application-level Responses API calls, not hidden SDK HTTP
  retry attempts, and it does not estimate cost.
- Reports and telemetry are local files. There is no scheduler or automatic
  delivery.
- Databases, RAG, a web UI, and historical analytics remain out of scope.

## Tests

Run the tests:

```bash
python -m pytest
```
