# Project: SD WebUI Forge Task Scheduler

A task scheduling extension for Stable Diffusion WebUI Forge that allows users to queue generation tasks and run them later, providing flexibility for managing large batches without waiting for each to complete.

## Critical Claude Tooling Instructions

**IMPORTANT: These instructions address known tool behavior issues that MUST be followed to avoid failures.**

### File Editing - Read and Edit in Same Message

When editing files, the Read and Edit tools MUST be called together in the same message block. Calling them in separate messages causes state loss and results in:
- Edit failing with "File has been unexpectedly modified"
- Write failing with "File has not been read yet"

**CORRECT - Both tools in same message:**
```
Message 1:
  [Read file_path="/path/to/file"]
  [Edit file_path="/path/to/file" old_string="..." new_string="..."]
```

**INCORRECT - Tools in separate messages:**
```
Message 1:
  [Read file_path="/path/to/file"]

Message 2:
  [Edit file_path="/path/to/file" ...]  <- WILL FAIL
```

This applies to both Edit and Write tools. Always read and modify files in a single response.

## Critical Rules For Project

- When operator (developer) ask you a question, carefully understand what operator trying to convey, if question is unclear, do not jump to conclusions, always ask followback questions.
- Unless operator specifically asked you to make code change, do not make any change to code. Operator asking question, and having clear answer does not mean you can proceed with changes in your answer. Always ask for confirmation before making changes to code.
- When operator approves changes for one file, that does not mean your task end at editing file. Remember what I said earlier, if you made any change, there's good chance that it could impact other places.
- Always honor the current folder structure, places new files in correct place. If you are unsure of where a new file belong, ask operator what to do.
- When you are making a significant alteration to any logic, ask operator if backwards compatibility has to be maintained. Do not assume one way or another, always ask.
- When running migration script or making any change to the databases (workflow_db, workflow_prod_db), always create a backup of original database. Before running any database migration script or run inline script which contains database changes, show operator what you are going to do and ask for confirmation.
- **Never update the stable branch without confirmation.** Do not rebase, merge, or push changes to the current stable branch unless operator explicitly asks you to do so. Always ask for confirmation before updating stable branch with changes from dev or other branches.
- **Commit frequently and proactively.** Do NOT wait for operator to remind you. Commit at these checkpoints:
  - After completing a bug fix (even if operator might test it next)
  - After adding a new feature or capability
  - After refactoring or restructuring files
  - After updating configuration or prompts
  - Before moving on to a different task or file
  - When you've made 3+ related file changes
  - If you're about to ask operator to test something, commit first
  When you see "[REMINDER] Uncommitted changes detected" from the Stop hook, immediately commit before continuing. Use meaningful commit messages describing what was changed and why.
- Never create modules that are specific to a single workflow. Modules must be generic, reusable, and workflow-agnostic. All workflow-specific logic should be handled through module configuration (inputs), not hardcoded in module code. If a complex scenario requires new functionality, design a generic module that can handle similar patterns across different workflows.

## Debugging and Verification Rules

**CRITICAL: These rules exist because of repeated failures. Follow them exactly.**

### When Writing New Code (Scripts, Modules, Functions)

1. **Enumerate ALL cases before coding.** Before writing code that handles multiple types/cases (e.g., event types, file types, error conditions), explicitly list every case that needs handling. Ask operator to confirm the list is complete.

2. **Trace through with concrete data.** After writing code, trace through it with real example data to verify it works. Don't just claim "this should work" - prove it with a specific example.

3. **When operator says "make sure X is handled"** - Don't just say "yes it's handled." Show the specific line of code that handles X, or admit it's not handled and add it.

### When Debugging Issues

1. **Assume YOUR code is wrong first.** When something breaks after you made changes, the bug is most likely in YOUR new code, not in existing code that was working before. Investigate your changes first.

2. **Don't blame existing code without proof.** Before suggesting fixes to existing code, verify with concrete data that the existing code is actually the problem. Query the database, trace through the logic, show the actual values.

3. **Fix root causes, not symptoms.** If you find yourself making a "fix" that works around an issue, stop and ask: "What is the actual root cause?" The first fix that comes to mind is often treating a symptom.

4. **When a fix doesn't work, question your diagnosis.** If your fix didn't solve the problem, your understanding of the problem is wrong. Go back to investigation, don't keep adding more fixes.

### Verification Checkpoints

Before saying "this is complete" or "this should work":
- [ ] Have I enumerated all cases/types this code needs to handle?
- [ ] Have I traced through with real data showing it works?
- [ ] If this deletes/modifies data, have I shown exactly what will be affected?
- [ ] Have I tested the failure modes, not just the happy path?
