---
name: legal-router
description: Use for legal work - legal research or advice, drafting a contract, letter, policy or court filing, or reviewing, marking up, extracting from, summarising or translating legal documents. Sends the task to the model best suited to it (Vals Legal Index) through the Legal Model Router. Also use when the user says a legal answer is not good enough.
argument-hint: <legal task>  |  not good enough <what was wrong>
---

Send the legal task to the Legal Model Router's `legal_router` tool.

- Put the whole task in `task`, including the text of any document the work is on (read files first).
- Task: $ARGUMENTS
- If the task starts with "best", set `best: true`.
- If the user says the previous answer was not good enough, call the tool again with the same task,
  `sent_back: true` and their words in `comment`.
- Show the tool's answer as returned, including its last line naming the model. Do not rewrite it.
