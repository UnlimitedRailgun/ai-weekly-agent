# AI & Computer Engineering Weekly Research Agent

This project will produce a beginner-friendly weekly overview of important AI and Computer Engineering developments for university students. Version 0.1 is intentionally small and will use a linear workflow:

`Research -> Curate -> Report / Explain -> Save locally`

The project foundation currently provides configuration loading, Pydantic data models, deterministic date utilities, package metadata, and offline tests. Research, LLM curation, and report generation are placeholders and are not implemented yet.

## Architecture

Production code lives in `src/ai_weekly_agent/`. The `research.py`, `curate.py`, and `report.py` modules correspond to the three planned workflow stages. Reusable prompts live in `prompts/`, raw research will be stored in `data/raw/`, and final Markdown reports will be stored in `reports/`.

Version 0.1 will not include a database, RAG, a vector database, a web UI, a scheduler, Docker, delivery integrations, or a multi-agent framework.

## Local setup

Python 3.11 or newer is required.

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the package and development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` when local API configuration is eventually needed, then set `OPENAI_API_KEY` and `OPENAI_MODEL`. Neither value is required for the current foundation tests.

Run the tests:

```bash
python -m pytest
```

The planned eventual run command is:

```bash
python -m ai_weekly_agent.main
```

At present, that command only reports that the research pipeline has not been implemented.
