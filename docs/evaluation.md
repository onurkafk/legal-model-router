# Evaluation

What the decision models and the routing rules were measured on, and what they scored. Every run used
OpenRouter with the questions in [`config/questions.json`](../config/questions.json) and zero data
retention.

**The labels were written by Claude, not reviewed by a lawyer.** The figures show that the rules do what
they are meant to do on these sets. They are not a guarantee about any particular matter.

## The test sets

- **Holdout:** 55 fresh requests, labelled before any run. 31 need the law or a new draft.
- **Stress:** 116 hard requests (8 ambiguous ones excluded). 28 depend on the law.
- **Drafting:** 33 drafting requests labelled standard form (20) or bespoke (13).
- Together, 195 distinct requests. Answers: `docs/data/classifier-answers-<name>.jsonl`; labels:
  `docs/data/labels.json` (no request text). `tests/test_classifiers.py` replays them through the current
  rules on every test run.

## Decision models compared

| | d1-ultra (default) | Decider V1.3 | Elephant-1 |
|---|---|---|---|
| Vals ClaimBench | 100.0% | 99.8% | 97.3% |
| Holdout, work type right | **55/55** | 53/55 | 52/55 |
| Holdout, law + new drafting reach a top model | 31/31 | 31/31 | 31/31 |
| Stress, law-dependent requests caught | 28/28 | 28/28 | 28/28 |
| Stress, requests sent to a top model | 51/116 | 47/116 | 56/116 |
| Bespoke drafts trusted as standard forms | 0/13 | 0/13 | 0/13 |
| Standard forms trusted as standard forms (P >= 0.8) | 17/20 | 14/20 | 8/20 |
| Kind of work unclear (sent to the overall #1) | 33/195 | 20/195 | 23/195 |
| Cost to read a request | $0.00014 | free | $0.00014 |
| Router cost per task (`estimate_savings.py`) | **$8.27** | $8.66 | $9.94 |
| Saving against all-Opus 5.5 | **63%** | 62% | 55% |

All three pass the safety bar at every threshold measured (law 0.2 to 0.5, standard form 0.6 to 0.9) and
share the thresholds in `config/routing-policy.yaml`. d1-ultra is the default: it gets every holdout answer
right and, with the standard-form bar at 0.8, sends every request that needs the law or a bespoke draft to
Best or Opus 5.5.

The standard-form bar is 0.8, not 0.7. At 0.7, d1-ultra sent two employment documents to Efficient: a
California employee settlement and release (0.78) and a first UK employment contract the client called
"standard stuff" (0.79). Both carry jurisdiction-specific requirements. Decider V1.3 still rates the UK
contract 0.83 and sends it to Efficient, about a point behind Best on Labor & Employment.

## Where the 195 requests go (d1-ultra)

| Pick | Requests |
|---|---|
| Best | 78 |
| Economy | 57 |
| Efficient | 35 |
| Escalated (Opus 5.5) | 25 |

## What it costs (d1-ultra)

Each request priced at the Vals Legal Index cost per task of the model it was sent to, on its own Vals line:

| Sending every request to | Cost per task | Tokens per task | Router saves |
|---|---|---|---|
| Claude Opus 5.5 | $22.29 | 15.42M | 63% |
| GPT-6.2 Astra | $10.17 | 3.03M | 19% |
| Gemini 4 Neon | $6.72 | 5.99M | -23% |
| Legal Model Router | $8.27 | 7.03M | |

Without the 25 bespoke drafts it sends to Opus 5.5 by design, the router costs 73% less than Opus 5.5,
40% less than GPT-6.2 Astra and 9% less than Gemini 4 Neon. Escalating bespoke drafting to Opus 5.5 is the
one place it pays more than the cheapest flagship, and it is a policy choice in `config/routing-policy.yaml`.

## Real court opinions, end to end

Six requests written from real US appellate opinions (Caselaw Access Project), sent through the router as a
user would: decision model, route, answer. Graded against what the court held.

| Request | Opinion | Route today | Answer |
|---|---|---|---|
| Bar fight, Indiana: can the injured patron win? | *Gunter v. Village Pub* (Ind. Ct. App. 1993) | Best, Civil Negligence | Right, and on current law: cites the 2016 Indiana Supreme Court cases that replaced the 1993 test |
| Agent settled behind the landlord's back, Missouri: can he appeal? | *Amoso Realty v. Milton* (Mo. Ct. App. 2016) | Best, Civil Negligence | Right: no final judgment (Rule 74.01(a): not called a judgment, not signed) |
| Remove the stepfather as personal representative, Montana | *In re Estate of Anderson-Feeley* (Mont. 2007) | Best, Wills, Estates & Trusts | Right: § 72-3-526 MCA, conflict of interest; full petition drafted |
| DUI and felony assault on a trooper, North Dakota: pre-trial plan | *State v. Rende* (N.D. 2018) | Best, overall (kind of work unclear) | Right: suppression motion before trial, knowledge element in the instructions, invited error |
| Judge signed the other side's divorce judgment verbatim, Florida | *Plichta v. Plichta* (Fla. 2d DCA 2005) | Best, Family | Right: *Perlow v. Berg-Perlow*, rehearing, life insurance needs findings |
| Unpaid wages against LLC managers, Massachusetts | *Cook v. Patient EDU* (Mass. Super. 2011) | Best, Labor & Employment | Right, and on current law: cites the 2013 SJC decision that reversed it |

The answers were written by Gemini 4 Neon, before the three Census lines (personal injury, family,
criminal) were added to the practice areas. Today the divorce goes to Gemini 4 Carbon, the Family line's
Best; the other five still go to Neon.

## Long requests

A long contract pasted into a request is the common case. The decision model is shown the first and last
4,000 characters (the instruction is at one end, the document in the middle); the model doing the work
gets the whole request. On 124 requests each joined to a 40,000-character contract, with the instruction
placed first and then last (Elephant-1):

| Instruction | Shown to the decision model | Kind of work right | Mis-routed with confidence ≥ 0.7 |
|---|---|---|---|
| First | Whole request | 113/120 | 2 |
| First | Both ends | 116/124 | 2 |
| Last | Whole request | 114/118 | 0 |
| Last | Both ends | 122/124 | 0 |

Showing both ends scores as well as the whole text, and never runs past the decision model's input limit.
Without a document the same requests score 97.6%.
