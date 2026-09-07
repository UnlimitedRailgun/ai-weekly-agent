# AI & Computer Engineering Weekly Research Agent

This project will produce a beginner-friendly weekly overview of important AI and Computer Engineering developments for university students. Version 0.1 is intentionally small and will use a linear workflow:

`Research -> Curate -> Report / Explain -> Save locally`

The Research, Curator, and Report / Explain stages are connected by a small synchronous command-line pipeline and covered by offline tests.

## Architecture

Production code lives in `src/ai_weekly_agent/`. The `research.py`, `curate.py`, and `report.py` modules correspond to the three planned workflow stages. Reusable prompts live in `prompts/`, raw research will be stored in `data/raw/`, and final Markdown reports will be stored in `reports/`.

Version 0.1 will not include a database, RAG, a vector database, a web UI, a scheduler, Docker, delivery integrations, or a multi-agent framework.

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

The application loads this file automatically. Never commit a real API key. Tests mock all network boundaries and do not require either value.

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

Version 0.1 researches all six categories sequentially, saves validated raw research under `data/raw/`, curates the important stories, and writes one Markdown report under `reports/`. It does not schedule or automatically trigger weekly runs.

## Tests

Run the tests:

```bash
python -m pytest
```
