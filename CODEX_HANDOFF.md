# Codex Handoff

## Task
Perform Phase 2.5: one controlled live research smoke test.

## Status
Completed successfully.

## Summary
Made exactly one live Responses API request by calling `research_category(...)`
for `AI model releases` and the fixed inclusive range 2026-08-30 through
2026-09-05. Automatic SDK retries were disabled. The structured response
contained four items; all four remained after source/date validation. No raw
research was persisted, and no application code was changed.

## Files Changed
- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

No application files were changed. A temporary smoke-test script under `/tmp`
and its bytecode were removed after use.

## Important Decisions
- Used the runtime model `gpt-5.6-terra`; no model override was applied.
- Used the implemented signature
  `research_category(date_range, category, config, *, client=None)` exactly once.
- Injected an `OpenAI` client configured with `max_retries=0` to guarantee no
  automatic retry. `research_all_categories(...)` and `save_research_run(...)`
  were not called.
- A temporary response-capturing wrapper observed pre-filter item count, source
  metadata, and usage without making another request or changing production code.

## Commands / Tests Run
- `.venv/bin/python -m pytest`
- `git check-ignore -v .env`
- `PYTHONPATH=src .venv/bin/python -c 'import inspect, sys; from ai_weekly_agent.config import load_config; from ai_weekly_agent.research import research_category; config = load_config(); missing = [name for name, value in (("OPENAI_API_KEY", config.openai_api_key), ("OPENAI_MODEL", config.openai_model)) if not value]; print("OPENAI_API_KEY: present" if config.openai_api_key else "OPENAI_API_KEY: missing"); print(f"OPENAI_MODEL: {config.openai_model}" if config.openai_model else "OPENAI_MODEL: missing"); print(f"research_category{inspect.signature(research_category)}"); sys.exit(1 if missing else 0)'`
- `PYTHONPATH=src .venv/bin/python -m py_compile /tmp/ai_weekly_phase25_smoke.py`
- `PYTHONPATH=src .venv/bin/python /tmp/ai_weekly_phase25_smoke.py`
- `git diff --check`
- `git status --short`

## Test Results
- Offline suite: 29 tests passed in 1.05 seconds.
- `.env` is ignored by the `.gitignore` rule on line 2.
- `OPENAI_API_KEY` and `OPENAI_MODEL` were present; the key value was not printed.
- Exactly one live Responses API request was made and succeeded in approximately
  52.19 seconds.
- Model: `gpt-5.6-terra`; category: `AI model releases`; range: 2026-08-30 through
  2026-09-05.
- Structured items: 4. Retained items: 4. Rejected items: 0.
- The response contained 9 `web_search_call` items and source metadata. The
  deterministic allow-list contained 107 normalized URLs, and every retained
  source matched it.
- Usage: 79,668 input tokens, 3,431 output tokens, 83,099 total tokens; output
  included 1,482 reasoning tokens and input included 5,083 cache-write tokens.
- No API, parsing, schema, or SDK compatibility error occurred.

## Known Issues
- Source provenance proves that a URL appeared in web-search activity, not that
  every claim is supported by that URL.
- The Claude Fable/Mythos item retained a generic Anthropic newsroom URL while
  labeling it as a specific announcement; its technical and benchmark claims
  require manual verification against a direct primary page.
- The Muse Spark item included a generic, tracked Meta Llama URL that may not
  directly support the story. It also placed performance-style claims in
  `technical_details` while leaving `benchmark_information` null.
- Gemini and GPT-6 Astra used direct primary URLs, but their benchmark and other
  provider-reported claims still require manual verification. No duplicate event
  was apparent.
- All four reported dates were syntactically inside the range, but this smoke test
  did not make follow-up requests to confirm that page dates and underlying event
  dates match.
- One category consumed 83,099 tokens, which should be reviewed before running all
  six categories.

## Open Questions
- Should generic landing/newsroom URLs be rejected when a direct announcement URL
  should exist?
- Is the observed token usage acceptable for the eventual six-category run, or
  should the research prompt/request be constrained first?

## Recommended Next Step
Review the Phase 2.5 source-quality and token-usage findings before deciding
whether to tighten the existing research prompt/validation. No compatibility fix
is required, and Phase 3 should not start until that review is complete.
