# Codex Handoff

## Task

Perform Phase 2.7: controlled A/B live research smoke test.

## Status

Completed: exactly one live Responses API request succeeded. No retry or
follow-up API/web request was made. The duplicate attachment received during
review was treated as the same task, not authorization for a second request.

## Summary

Used runtime model `gpt-5.6-terra`, category `AI model releases`, and inclusive
dates 2026-08-30 through 2026-09-05. All four structured stories were retained;
total tokens fell 49.19% from Phase 2.5. Benchmark placement improved, but generic
sources and release-time availability uncertainty remain.

## Files Changed

- `/home/shanl/ai-weekly-agent/CODEX_HANDOFF.md`

Application code, prompts, and configuration were unchanged. No ResearchRun or
raw output was persisted. The temporary script
`/tmp/ai-weekly-phase27-jZnIEj/smoke.py` and its empty directory were removed.

## Important Decisions

- Called `research_category(date_range, category, config, client=client)` exactly
  once live, using an injected `OpenAI(..., max_retries=0)` client and the existing
  `max_tool_calls=4` request. No model override, all-category run, or save call.
- Captured the parsed response before deterministic filtering in memory; inspected
  only structured fields, tool metadata, usage, and status. No hidden reasoning or
  credentials were printed.
- Classifications below are observations from returned URLs/titles and claims,
  not independent source verification.
- This is one before/after sample; it does not establish complete coverage or a
  repeatable causal effect.

## Commands / Tests Run

- `.venv/bin/python -m pytest`
- `git check-ignore -v .env`
- `git ls-files --error-unmatch .env` (expected nonzero: .env is untracked)
- `PYTHONPATH=src .venv/bin/python -B /tmp/ai-weekly-phase27-jZnIEj/smoke.py`
- `git diff --check`
- `git status --short`

## Test Results

- All 35 offline tests passed in 1.02 seconds before the live call.
- Prerequisites confirmed: .env ignored/untracked, API key present without
  displaying its value, runtime model matches baseline, tool-call limit four,
  public research_category signature inspected, injected SDK retries zero.
- One live request succeeded; response status was `completed`; no API, Pydantic,
  parsing, or SDK exception occurred.
- Web-search source metadata was present. All eight retained source entries
  matched the 82-URL normalized allow-list. No stories were rejected.
- One source entry was removed: `https://openai.com/index/gpt-6-astra/` was absent
  from the normalized allow-list. Its story retained two other sources.

| Metric | Phase 2.5 | Phase 2.7 | Change |
| --- | ---: | ---: | ---: |
| Responses API requests | 1 | 1 | 0 |
| web_search_call items | 9 | 5 | -44.44% |
| Input tokens | 79,668 | 39,424 | -50.51% |
| Output tokens | 3,431 | 2,799 | -18.42% |
| Total tokens | 83,099 | 42,223 | -49.19% |
| Normalized source URLs | 107 | 82 | -23.36% |
| Structured stories | 4 | 4 | 0 |
| Retained stories | 4 | 4 | 0 |
| Elapsed seconds | 52.19 | 39.59 | -24.14% |

Additional Phase 2.7 usage: 1,130 reasoning tokens, 5,395 cache-write tokens, and
0 cached-input tokens. Elapsed baseline comes from the recorded Phase 2.5 result.

## Known Issues

- Tool limit observation: three searches and one open_page were `completed`;
  a fifth open_page item remained `searching`, despite the response completing.
  Four completed calls are consistent with the processing cap, but a strict
  four-item output ceiling was not observed. Do not equate emitted and completed
  tool calls. No compatibility fix is established by this observation alone.
- The existing provenance allow-list includes tool URLs without filtering action
  status; matching it does not prove a page was successfully read or supports all
  claims. This test cannot attribute every retained URL to a completed action.
- GPT-6 Astra (OpenAI, 2026-09-03): DIRECT_PRIMARY safety/model documentation;
  specific announcement URL was removed. Vendor benchmarks have attribution and
  context, but the retained sources' support for the launch date and every score
  is unverified.
- Claude Fable/Mythos 5.1 (Anthropic, 2026-09-01): PRIMARY_BUT_GENERIC overall;
  versionless model product pages plus rolling release notes. The 85% safeguard
  intervention comparison is correctly in benchmark_information. Release-time
  applicability of mutable pages is uncertain.
- Gemini 3.8 Flash (Google DeepMind, 2026-09-02): DIRECT_PRIMARY via its specific
  model card, with a generic Flash product page also retained. Benchmark claims
  are attributed; the DeepSWE claim is approximate (>70%). The Cyber variant
  present in Phase 2.5 is absent from this result.
- Muse Spark 1.3 (Meta AI, 2026-09-02): DIRECT_PRIMARY announcement. The 20% fewer
  tool calls / 25% fewer tokens comparison moved into benchmark_information with
  attribution and a methodological caveat. Maximum reasoning is described as
  available, whereas Phase 2.5 said it was pending: possible page-update versus
  event-date mismatch requiring review.
- All four dates are known and within range; none is null. All benchmark fields
  are populated, so live null-fallback behavior was not exercised. No misplaced
  quantitative performance claim or obvious duplicate was observed.
- Source quality improved partly (tracked Meta link/newsroom index absent), but
  generic product pages persist. Same four main events were retained; complete
  coverage is not established.

## Open Questions

Can all dated availability claims be tied to release-time evidence? Should
provenance distinguish completed from unfinished tool actions? Neither question
was investigated with additional requests.

## Recommended Next Step

Adjust Phase 2's direct-event-source and release-time availability guidance before
routine six-category use; review unfinished-tool provenance offline. No confirmed
SDK compatibility fix is needed. No code or prompt change was made in this task.
Do not perform another live request or start Phase 3 without a new instruction.
