# Codex Handoff

## Task

Perform Phase 3.5: controlled live Curator smoke test.

## Status

Completed successfully. Exactly one live Responses API request was made. No
application code, prompts, thresholds, or diversity behavior were changed.

## Summary

Ran the existing `curate_research_run()` against a temporary, explicitly
synthetic nine-candidate `ResearchRun`. The live Structured Output parsed, every
candidate received one valid assessment, the intended semantic duplicate was
recognized, thresholding removed weak candidates, and deterministic selection
returned five items. The temporary fixture was removed and no research data was
persisted.

## Files Changed

- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

No other repository file was changed.

## Important Decisions

- Runtime model: `gpt-5.6-terra` from `OPENAI_MODEL`; it was not overridden.
- The injected OpenAI client used `max_retries=0`.
- The request contained no `tools` or `tool_choice`. The response contained one
  `message` output, zero `web_search_call` outputs, and zero other tool calls.
- Input IDs were `candidate_001` through `candidate_009`. All nine passed hard
  filtering, no candidates were exact-deduplicated, and all nine reached the LLM.
- Assessment summary (`impact/technical_significance/novelty/student_relevance`):

  | ID | Scores | Final | Semantic duplicate |
  | --- | --- | ---: | --- |
  | candidate_001 | 4/4/4/5 | 4.25 | None |
  | candidate_002 | 4/3/1/4 | 3.00 | candidate_001 |
  | candidate_003 | 3/2/2/4 | 2.75 | None |
  | candidate_004 | 3/4/4/5 | 4.00 | None |
  | candidate_005 | 1/1/1/1 | 1.00 | None |
  | candidate_006 | 3/4/4/5 | 4.00 | None |
  | candidate_007 | 4/4/4/5 | 4.25 | None |
  | candidate_008 | 3/4/3/5 | 3.75 | None |
  | candidate_009 | 2/3/2/5 | 3.00 | None |
- The intentionally duplicated Helios-3 coverage (`candidate_002`) correctly
  referenced `candidate_001`. The deterministic resolver kept `candidate_001`
  because its 4.25 score exceeded 3.00; its two primary/direct sources would also
  have been stronger tie-break evidence.
- All assessed candidates below 3.25 were candidate_002, candidate_003,
  candidate_005, and candidate_009. Because duplicate resolution happens first,
  thresholding itself removed candidate_003, candidate_005, and candidate_009.
  The intentionally minor spinner-color patch was candidate_005 and was removed.
- Diversity did not alter this run: baseline quality order and diversity order
  were both 001, 007, 004, 006, 008. Category order was AI model releases; GPU /
  semiconductor / AI infrastructure; AI developer tools/frameworks; AI research;
  robotics / physical AI. No quota was applied.
- Final selected list:

  1. Example Labs launches Helios-3 multimodal foundation model — AI model
     releases — 4.25
  2. NovaSilicon unveils modular chiplet AI accelerator — GPU / semiconductor /
     AI infrastructure — 4.25
  3. CircuitForge introduces deterministic GPU kernel replay debugger — AI
     developer tools/frameworks — 4.00
  4. SparseBridge research reduces transformer activation memory — AI research
     — 4.00
  5. Embodied Systems Lab releases tactile robot-learning platform — robotics /
     physical AI — 3.75
- Five selected items is valid; the Curator does not force eight. The 12-item
  maximum had no effect.
- The live result supports freezing the Version 0.1 Curator. No code or constant
  changes are recommended from this single synthetic sample.

## Commands / Tests Run

- `.venv/bin/python -m pytest`
- `git check-ignore -q .env`
- `git check-ignore -v .env`
- `rg -n "responses\\.parse|tools|web_search" src/ai_weekly_agent/curate.py prompts/curate.md`
- `.venv/bin/python -m py_compile /tmp/ai_weekly_phase35_smoke.py`
- `PYTHONPATH=src .venv/bin/python -c "from openai import OpenAI; c=OpenAI(api_key='synthetic-preflight-key', max_retries=0); print('max_retries:', c.max_retries)"`
- `PYTHONPATH=src .venv/bin/python /tmp/ai_weekly_phase35_smoke.py`
- `find /tmp/__pycache__ -maxdepth 1 -type f -name 'ai_weekly_phase35_smoke*.pyc' -print 2>/dev/null`
- `git diff --check`
- `git status --short`

## Test Results

- Offline suite: 104 tests passed in 1.10 seconds.
- Live request count: exactly 1.
- Structured assessment count: 9 expected, 9 received, with exact candidate-ID
  coverage.
- Elapsed time: approximately 5.713 seconds.
- Usage: 2,247 input tokens; 333 output tokens; 0 reasoning tokens; 2,580 total
  tokens.
- Zero `web_search` calls and zero tool calls occurred. No automatic retry or
  follow-up Responses API request occurred.
- `git diff --check` passed. Final status contains only this handoff modification.
- The current official OpenAI Structured Outputs documentation was consulted
  separately; this was not an application Responses API or project web-search
  call.

## Known Issues

No runtime, SDK, schema, or deterministic-selection issues were observed. This
was one synthetic sample and is not evidence for retuning the score threshold or
diversity window.

## Open Questions

None blocking the Version 0.1 Curator freeze.

## Recommended Next Step

Freeze the Version 0.1 Curator and implement the Report / Explain stage.
