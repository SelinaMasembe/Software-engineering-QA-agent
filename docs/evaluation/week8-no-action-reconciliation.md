# Week 8: reconciling `no_action` with the citation rule

**Status:** scripted evidence only. Prompt v1.3 has **not** been run against a
real model.

## The conflict

Two parts of the system disagreed about when the agent may decline.

- **Prompt v1.2, FAILURE BEHAVIOR:** "If you cannot determine a grounded next
  action, return "action": "no_action" and explain why in "rationale"." It said
  nothing about evidence, so a model could decline with an empty `evidence`
  list even when sources were supplied.
- **The citation validator (`src/orchestrator/validation.py`, US-8):** rejects
  every evidence-free proposal, with one exception: a `no_action` when
  retrieval deterministically found nothing (`confirmed_not_in_corpus=True`
  and an empty allow-list).

So a response that followed v1.2 could be rejected by the loop. The Week 2
case `edge_vague_requirement` is exactly that response: `no_action`,
`"evidence": []`, `"confidence": "low"`, with a source supplied. The Week 2
harness passes it because it predates the validator. The real loop would
reject it as uncited.

## The change: prompt v1.3

`docs/prompts/propose_action/v1.3.md` is v1.2 with only FAILURE BEHAVIOR
extended (ROLE and TASK are byte-identical to v1.1, so the task contract still
matches). The new rules:

1. If the context says "No relevant evidence was found for this query.",
   return `no_action` with empty evidence.
2. If evidence was provided but is insufficient or ambiguous, return
   `no_action`, cite each source read with a note on what is missing, and set
   confidence to low.
3. Never return `no_action` with empty evidence in any other case.

The validator is unchanged. Rule 1 is its existing exception; rules 2 and 3
make the prompt ask for what the validator already requires.

## Evidence (scripted planner, real loop and validator)

| Case | What the scripted planner returns | Result |
|---|---|---|
| ADV-EDG-04 | v1.3 style: `no_action` citing both vague sources, low confidence | Accepted. Loop ends `no_action`. |
| ADV-EDG-05 | Turn 1: v1.2 style, evidence-free `no_action` with sources present. Turn 2: v1.3 style. | Turn 1 rejected by the validator (`citation_rejected`); turn 2 accepted. |
| ADV-EDG-06 | Evidence-free `no_action` when the context says nothing was found | Accepted. |

These show the validator and the v1.3 wording agree. They do **not** show
that a model follows v1.3: the responses are written by hand.

## What is unchanged

- `tests/fixtures/prompt_eval_cases.json` still encodes the old behaviour for
  `edge_vague_requirement` (evidence-free `no_action`, expected to pass). It is
  not edited, because the Week 2 result is a record of what was evaluated
  then. `tests/test_evaluation_scorer.py` pins it as the one case where the
  Week 2 harness and the current rules disagree.
- The prompt harness CLI and its offline test use the latest prompt on disk,
  which is now v1.3. The offline test uses scripted responses and does not
  read the prompt text, so it still passes; it is not evidence about v1.3.

## Still to do

- Run the ten Week 2 cases against v1.3 with a real model and record the result.
- Decide whether a v1.3-era evaluation should replace the Week 2 expectation
  for `edge_vague_requirement`.
