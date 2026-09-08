# AI & Computer Engineering Weekly Research Agent

This project produces a beginner-friendly weekly overview of important AI and Computer Engineering developments for university students. Its current integrated workflow is deliberately small and synchronous:

`Research -> save raw -> Verify -> Curate -> Report / Explain -> save locally`

The package version remains `0.1.0` while the integrated verification and operational-observability work intended for Version 0.2 is tested.

## Architecture

Production code lives in `src/ai_weekly_agent/`. The main workflow uses one configured OpenAI client, with stage-labelled views for Research, Curator, and Report so one telemetry recorder can observe their logical Responses API calls. Verify is deterministic local Python and makes no API call.

Research results are saved under `data/raw/` before verification. This preserves the original audit artifact, including items that Verify later rejects. Sources may carry model-reported evidence roles such as event, event date, technical, benchmark, or background evidence. Verify checks these classifications and other deterministic rules, but it does not fetch pages or independently prove that a source supports a claim. Rejected items do not reach Curator.

Final Markdown reports are stored under `reports/`. A concise operational RunRecord is atomically written to `data/runs/` after success and is attempted after pipeline failures. RunRecord persistence is best-effort: failure to save telemetry cannot invalidate an otherwise successful report or replace the primary pipeline error.

Each run researches these six categories:

- AI model releases
- AI developer tools and frameworks
- Important AI research
- GPUs, semiconductors, and AI infrastructure
- Robotics and physical AI
- Other important computer engineering developments

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

Each run researches all six categories sequentially, preserves the original structured research, verifies evidence metadata locally, curates accepted stories, and writes one Markdown report. CLI completion output includes the logical API-call count and either a complete total-token count or an explicit `incomplete telemetry` message.

Telemetry counts calls to `responses.parse()` made by the application. It does not expose hidden HTTP retry attempts performed inside the SDK. Missing response usage remains unknown and is never represented as zero. RunRecords contain operational metadata and counts, not prompts, response bodies, API keys, or source contents.

The application does not schedule or automatically trigger weekly runs.

## Tests

Run the tests:

```bash
python -m pytest
```
