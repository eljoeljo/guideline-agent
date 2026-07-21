Project goal:
Build a Responsible AI intake agent that interviews project owners and stores structured project context.

Version 1:
- Ask fixed number of questions from mock database
- Save responses to JSON
- No conditional logic yet

Moving on to the 2nd version, where I will implement conditional logic.
Here is what has been added:
- Switched from 5-10 mock questions to the real 88 question checklist (still in JSON format)
- Using schemas, implemented an applicability layer which combines deterministic logic with LLM reasoning