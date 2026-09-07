# Codex Handoff

## Task

Perform Phase 4.5: controlled live Report smoke test.

## Status

Completed successfully. Exactly one live Responses API request was made. The
Version 0.1 Report stage is ready to freeze.

## Summary

Ran `generate_report()` once with four synthetic CuratedItems covering model,
accelerator, robotics, and developer-tool stories. The actual Structured Output
mapped correctly, rendered deterministically, preserved benchmark caveats,
applied the fixed null-benchmark message, and used only fixture source URLs. No
synthetic report was persisted.

## Files Changed

- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

No application code, prompt, model, test, threshold, or production output file
was changed.

## Important Decisions

- Used the runtime `OPENAI_MODEL` value `gpt-5.6-terra` with an injected OpenAI
  client configured as `max_retries=0`.
- Sent four synthetic stories with stable IDs `story_001` through `story_004`.
  The response returned four explanations in exact one-to-one ID coverage, with
  no unknown, duplicate, or missing IDs.
- The request contained no `tools` or `tool_choice`; the response contained only
  a `message`, with zero `web_search` and zero other tool calls.
- The model prompt contained zero fixture source URLs. Structured prose contained
  no URL-like text. Every Markdown link matched an input `NewsItem.sources` URL.
  Existing offline tests remain the evidence that URL-like model prose fails
  closed with `ReportError`.
- Six source entries were rendered with their stories. The consolidated Source
  Index contained five unique normalized URLs, correctly deduplicating the shared
  secondary URL.
- The model returned four concise summary bullets. They accurately synthesized
  the model, chiplet, tactile-robotics, and GPU-debugging stories without adding
  unsupported event claims.
- The model returned five grounded concepts: sparse mixture-of-experts routing;
  inference throughput and deployment conditions; chiplets/coherence/shared
  memory; closed-loop tactile robot control; and deterministic replay for
  concurrency debugging. All related IDs referenced supplied stories.
- Each story included a clear event description, beginner-friendly definition,
  concrete technical significance, relevant engineering explanation, and a
  practical student learning direction. The prose avoided hype and generally
  marked unspecified implementation details explicitly.
- The Helios-4 benchmark explanation repeated only supplied quantities: 72
  tokens/s, one Example X900 accelerator, batch size 1, and 8-bit weights. It
  preserved that the result was company-reported, unverified, and lacked a
  comparison baseline. One minor wording inference called the supplied inference
  API “hosted”; this did not affect metadata, citations, or benchmark accuracy and
  does not justify a prompt/code change from one synthetic sample.
- The three stories with null benchmark data each rendered exactly: “No reliable
  benchmark information was available in the researched sources.” No model
  benchmark claim appeared in those rendered sections.
- Story order, titles, categories, organizations, dates, and curation scores all
  matched the CuratedItem input. These values came from deterministic Python, not
  model output.
- No production changes are recommended. The Report stage is ready to freeze for
  Version 0.1.

## Commands / Tests Run

- `.venv/bin/python -m pytest`
- `git check-ignore -v .env`
- `PYTHONPATH=src .venv/bin/python -c "from ai_weekly_agent.config import load_config; c=load_config(); print('OPENAI_API_KEY present:', bool(c.openai_api_key)); print('OPENAI_MODEL present:', bool(c.openai_model)); print('OPENAI_MODEL:', c.openai_model if c.openai_model else '<missing>')"`
- `rg -n "responses\\.parse|tools|tool_choice|web_search" src/ai_weekly_agent/report.py prompts/report.md`
- `.venv/bin/python -m py_compile /tmp/ai_weekly_phase45_smoke.py`
- `rg -n "generate_report\\(|render_markdown\\(|research_category\\(|research_all_categories\\(|curate_research_run\\(|responses\\.parse|tools|tool_choice|web_search" /tmp/ai_weekly_phase45_smoke.py`
- `PYTHONPATH=src .venv/bin/python /tmp/ai_weekly_phase45_smoke.py`
- `find /tmp -maxdepth 2 -type f -name 'ai_weekly_phase45_smoke*' -print 2>/dev/null`
- `rm -f /tmp/__pycache__/ai_weekly_phase45_smoke.cpython-312.pyc`
- `git diff --check`
- `git status --short`

## Test Results

- Offline suite: 146 tests passed in 1.09 seconds.
- Live Responses API requests: exactly 1; no retry or follow-up request.
- Model: `gpt-5.6-terra`.
- Elapsed time: approximately 29.378 seconds.
- Usage: 1,575 input tokens; 2,183 output tokens; 0 reasoning tokens; 3,758
  total tokens.
- Structured result: 4/4 expected story explanations, 4 summary bullets, and 5
  concepts with valid related-story IDs.
- URL result: zero prompt source URLs, zero model-prose URLs, all final links
  trusted, and 5/5 Source Index URLs unique after normalization.
- Zero `web_search` calls and zero tool calls occurred. No commit was created.
- The current official OpenAI Structured Outputs documentation was consulted
  separately; this was not an application Responses API or project web-search
  call.

## Known Issues

No runtime, SDK, schema, rendering, benchmark, or citation-safety issue was
observed. One phrase (“hosted inference API”) was slightly more specific than the
fixture’s “inference API”; monitor this in real reports, but do not tune from one
synthetic example.

## Open Questions

None blocking the Report-stage freeze.

## Recommended Next Step

Freeze the Version 0.1 Report stage and implement the minimal end-to-end CLI
pipeline.
