# Evaluation

What the decision models and the routing rules were measured on, and what they scored. Every run used
OpenRouter with the questions in [`config/questions.json`](../config/questions.json), the same 195
requests, and zero data retention.

**The labels were written by Claude, not reviewed by a lawyer.** The figures show that the rules do what
they are meant to do on these sets. They are not a guarantee about any particular matter.

## Decision models compared

| | d1-ultra (default) | Decider V1.3 | Elephant-1 |
|---|---|---|---|
| Vals ClaimBench | 100.0% | 99.8% | 97.3% |
| Holdout, top answer to the work-type question | **55/55** | 53/55 | 52/55 |
| Holdout, law + new drafting reach a top model (P >= 0.3) | 31/31 | 31/31 | 31/31 |
| Stress, law-dependent requests caught | 28/28 | 28/28 | 28/28 |
| Stress, requests sent to a top model | 51/116 | 47/116 | 56/116 |
| Bespoke drafts trusted as standard forms | 0/13 | 0/13 | 0/13 |
| Standard forms trusted as standard forms (P >= 0.7) | 17/20 | 15/20 | 11/20 |
| Section answer under 0.7 (sent to the overall #1) | 34/195 | 19/195 | 23/195 |
| Cost to read a request | $0.00014 | free | $0.00014 |
| Router cost per task (`estimate_savings.py`) | **$7.89** | $8.65 | $9.65 |
| Saving against all-Opus 5.5 | **64%** | 62% | 57% |

All three pass the safety bar at every threshold measured (law 0.2 to 0.5, standard form 0.6 to 0.9), so
they share the conservative thresholds in `config/routing-policy.yaml`. d1-ultra is the default because it
gets every holdout answer right; it also trusts more genuine standard forms, which is where its extra
saving comes from.

One request moves: a first UK employment contract the client calls "standard stuff, 3 month probation".
d1-ultra and Decider V1.3 read it as a standard form (0.79 and 0.83) and send it to Efficient, GPT-6.2 Astra
on Labor & Employment, about a point behind Best. Elephant-1 sent it to Opus 5.5.

The answers are in `docs/data/classifier-answers-<name>.jsonl` and the labels in `docs/data/labels.json`
(no request text). `tests/test_classifiers.py` replays them through the current rules on every test run.

## The question that matters most: does work that needs the law reach a top model?

The figures in this section and the next are Elephant-1's; the comparison above covers all three.

A wrong route in one direction costs money: routine work sent to Best. A wrong route in the other
direction costs quality: research or a bespoke draft sent to a cheaper model. The rules are tuned to
avoid the second.

| Set | Measure | Result |
|---|---|---|
| Holdout, 55 fresh requests | Requests that need the law or a bespoke draft, sent to a top model (P ≥ 0.3, 0.5 or 0.7) | 31/31 recall, 31/31 precision |
| Holdout | Top answer to the work-type question matches the label | 52/55 |
| Stress, 116 hard requests | Law-dependent requests caught (P(research) + P(new drafting) ≥ 0.3) | 28/28 (56 of 116 sent up) |
| Drafting set | Bespoke drafts sent to a cheaper model | 0/13 |
| Drafting set | Standard forms sent to a cheaper model (P(standard form) ≥ 0.7) | 11/20 |
| Repeat run | Same top answer on the same request | 172/179 |

The 3 holdout misses are motions and briefs (a motion to dismiss, an opposition to enforcement of an ICC
award) that sit between research and drafting. Either answer sends them to a top model: Opus 5.5 for new
drafting, Best for research.

Cost of the full run: $0.0264 for 195 requests, about $0.000135 per request.

## Where the 195 requests were routed

Replaying the stored classifier answers through the current rules:

| Pick | Requests |
|---|---|
| Best | 73 |
| Economy | 52 |
| Escalated (Opus 5.5) | 40 |
| Efficient | 30 |

The only drafting requests routed below Best or Opus 5.5 are standard forms (NDA, simple will,
consulting agreement), as intended.

## What it costs

With Elephant-1 reading them, the same 195 requests, each priced at the Vals Legal Index cost per task of the model it was sent
to, on its own Vals line (`scripts/estimate_savings.py`, using `docs/data/classifier-answers.jsonl`: the
classifier's answers only, no request text):

| Sending every request to | Cost per task | Tokens per task | Router saves |
|---|---|---|---|
| Claude Opus 5.5 | $22.34 | 15.42M | 57% |
| GPT-6.2 Astra | $10.18 | 3.03M | 5% |
| Gemini 4 Neon | $6.74 | 5.99M | -43% |
| Legal Model Router | $9.65 | 7.73M | |

Without the 40 bespoke drafts it sends to Opus 5.5 by design, the router costs 72% less than Opus 5.5,
39% less than GPT-6.2 Astra and 8% less than Gemini 4 Neon. Escalating bespoke drafting to Opus 5.5 is
the one place it pays more than the cheapest flagship, and it is a policy choice in
`config/routing-policy.yaml`.

## Long requests

A long contract pasted into a request is the common case. The classifier is shown the first and last
4,000 characters (the instruction is at one end, the document in the middle); the model doing the work
gets the whole request. On 124 requests each joined to a 40,000-character contract, with the instruction
placed first and then last:

| Instruction | Shown to classifier | Kind of work right | Mis-routed with confidence ≥ 0.7 |
|---|---|---|---|
| First | Whole request | 113/120 | 2 |
| First | Both ends | 116/124 | 2 |
| Last | Whole request | 114/118 | 0 |
| Last | Both ends | 122/124 | 0 |

Showing both ends scores as well as the whole text, and never runs past the classifier's input limit.
Without a document the same requests score 97.6%.
