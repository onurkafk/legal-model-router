# Evaluation

What the classifier and the routing rules were measured on, and what they scored. Every run used
Elephant-1 on OpenRouter with the questions in [`config/questions.json`](../config/questions.json).

**The labels were written by Claude, not reviewed by a lawyer.** The figures show that the rules do what
they are meant to do on these sets. They are not a guarantee about any particular matter.

## The question that matters most: does work that needs the law reach a top model?

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
