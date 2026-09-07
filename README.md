# AI & Computer Engineering Weekly Research Agent

This project will produce a beginner-friendly weekly overview of important AI and Computer Engineering developments for university students. Version 0.1 is intentionally small and will use a linear workflow:

`Research -> Curate -> Report / Explain -> Save locally`

The Research, Curator, and Report / Explain stages are implemented and covered by offline tests. The full end-to-end CLI pipeline is not implemented yet; the stages are not yet connected through `main.py`.

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

Copy `.env.example` to `.env` for live research, curation, or report explanation generation, then set `OPENAI_API_KEY` and `OPENAI_MODEL`. Tests mock all network boundaries and do not require either value.

Run the tests:

```bash
python -m pytest
```

The planned eventual run command is:

```bash
python -m ai_weekly_agent.main
```

At present, that command remains a placeholder and does not run the implemented stages end to end.
