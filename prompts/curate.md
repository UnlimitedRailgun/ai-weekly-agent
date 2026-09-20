# Weekly Candidate Curation

Assess the supplied research candidates for this audience: {audience}.

Use only the evidence already supplied with each candidate.
Do not browse, search, call tools, invent facts, or rewrite the stories.
Return one assessment for every candidate, using only its supplied
`candidate_id`.

Score every dimension with an integer from 1 (low) through 5 (high):

- `impact`: How much could this development affect the AI or Computer
  Engineering industry, research direction, developer ecosystem, hardware
  landscape, or real-world use?
- `technical_significance`: Does it introduce meaningful architectural,
  algorithmic, hardware, systems, or engineering changes?
- `novelty`: Is it actually new rather than a minor, incremental, or repackaged
  update?
- `student_relevance`: Would understanding it help a Computer Engineering
  student understand important AI/CE technology or industry direction?

Use `semantic_duplicate_of` only when two candidates describe the same
underlying event, such as separate coverage of one launch or different headlines
for one research result. Related topics, products in the same family, or events
from the same organization are not duplicates. When candidates are duplicates,
point the weaker candidate to the stronger representative's candidate ID. Set
the stronger representative's `semantic_duplicate_of` to null. Use null for all
non-duplicates.

<!-- HISTORICAL_CONTINUITY_START -->
## Historical continuity

Some candidates include up to three `historical_candidates` retrieved from
prior local weekly reports. Retrieval only identifies a possible relationship;
it does not mean that the current candidate is a duplicate. The supplied match
reasons are retrieval signals, not conclusions. The same organization alone,
the same product family or topic alone, or a shared mutable URL alone is never
enough to classify a story as `REPEAT`.

For a current candidate with one or more historical candidates, set
`historical_status` to exactly one of:

- `REPEAT`: substantially the same event and substantive facts were previously
  reported, and the current verified item contains no material new development.
- `FOLLOW_UP`: the current event continues a previously covered event, product,
  or topic and contains at least one materially new CURRENT verified fact.
- `NEW`: the current event is meaningfully distinct from the retrieved prior
  candidates. For example, one company releasing Model B is not a repeat of its
  earlier Model A release.
- `UNCERTAIN`: the supplied current and historical facts are insufficient to
  distinguish safely among the other statuses.

First establish event identity from the supplied facts. Use `REPEAT` only when
enough identifying facts establish the same specific prior event and
substantively repeated coverage without a material current development. If no
new development is identifiable but event equivalence itself remains unresolved,
use `UNCERTAIN`, not `REPEAT`. A low quality score is not evidence of repetition;
continuity and the four quality scores are separate. Never choose `FOLLOW_UP`
without a valid `material_change_refs` pointer to a materially new current fact.

For `FOLLOW_UP`, set `historical_match_id` to one supplied `history_id` and use
one or more `material_change_refs` to point only to the current item's `summary`,
`technical_detail` with its zero-based index, or `benchmark_information`. Never
write a factual what-changed sentence or refer to a historical fact as current
change evidence. A newly verified API general-availability fact may establish a
follow-up to an earlier product announcement.

For `REPEAT`, set `historical_match_id` to one supplied `history_id` and return
no material-change references. For `NEW`, use no historical match ID or change
references. For `UNCERTAIN`, a supplied history ID is optional, but change
references are forbidden.

If `historical_candidates` is empty, leave `historical_status` and
`historical_match_id` null and `material_change_refs` empty. The application
assigns the safe local status from history completeness. Historical continuity
is not a fifth score and must not change the meaning of the four existing score
dimensions.
<!-- HISTORICAL_CONTINUITY_END -->

Do not calculate a final score. The application will validate the assessments,
resolve duplicates, calculate equal-weight scores, and select stories locally.
The structured response must contain exactly one assessment for every supplied
candidate, with no omitted, repeated, or unknown candidate IDs.

Candidates:

{candidates_json}
