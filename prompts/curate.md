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

Do not calculate a final score. The application will validate the assessments,
resolve duplicates, calculate equal-weight scores, and select stories locally.
The structured response must contain exactly one assessment for every supplied
candidate, with no omitted, repeated, or unknown candidate IDs.

Candidates:

{candidates_json}
