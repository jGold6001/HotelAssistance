---
name: run-report
description: Capture today's verified development work into a dated report and refresh the compact CURRENT.md checkpoint for the next session. Use only when explicitly invoked by the user.
disable-model-invocation: true
---

# Run Report

Create a trustworthy end-of-session handoff without loading unnecessary history.

## Live repository snapshot

- Local date: !`date +%F`
- Branch: !`git branch --show-current 2>/dev/null || true`
- HEAD: !`git rev-parse --short HEAD 2>/dev/null || true`
- Working tree: !`git status --short 2>/dev/null || true`
- Changed files: !`git diff --name-status HEAD 2>/dev/null || true`
- Recent commits: !`git log -5 --oneline --decorate 2>/dev/null || true`

## Procedure

1. Determine today's local date and target `docs/work-reports/YYYY-MM-DD.md`.
2. If today's report already exists, read it before updating it. Do not read older reports by default.
3. Build the report only from evidence available in the current session and repository state. Useful evidence includes current edits, Git status/diff metadata, commits, and commands/tests actually run.
4. Do not claim a task is complete merely because an older report says so. Verify from the current repository when verification is possible.
5. Do not run a full test suite only to make the report look complete. Record checks already run. If verification is missing, state that clearly.
6. Do not modify application code while executing this skill. Only create/update report files unless the user explicitly requests something else.
7. Never include secrets, API keys, tokens, credentials, raw authorization headers, or large raw diffs.

## Daily report format

Write `docs/work-reports/YYYY-MM-DD.md` in English with these sections:

```md
# Daily Work Report - YYYY-MM-DD

## Summary
Concise goal and outcome for the day.

## Completed Work
Only work supported by current-session or repository evidence.

## Files Changed
Important files only, with a short reason for each.

## Architecture / Decisions
Material technical decisions and rationale.

## Tests / Verification
Commands/checks actually run and their results. Explicitly list important checks not run.

## Open Issues / Blockers
Known problems, risks, TODOs, or unanswered questions.

## Next Steps
Ordered next actions.

## Resume Context
A compact handoff explaining where work stopped and what should be inspected first next time.
```

Keep the daily report useful but concise. Prefer summaries over pasted logs or diffs.

## Refresh CURRENT.md

After the dated report is updated, overwrite `docs/work-reports/CURRENT.md` with a compact checkpoint derived from the current repository and today's report.

Keep `CURRENT.md` to roughly 80 lines or fewer. It must contain:

```md
# Current Development State

Updated: YYYY-MM-DD
Branch: <branch>
HEAD: <short SHA>
Working tree: <clean | concise status>

## Current Goal
One short paragraph.

## Completed
Only the most relevant verified accomplishments, maximum 6 bullets.

## Current State
What is implemented now and what is still incomplete.

## Last Verification
Only checks actually run, with result. Say `Not run` when appropriate.

## Relevant Files
Maximum 10 paths that matter for the next step.

## Next Step
Exactly one primary next action.

## Open Questions
Maximum 5 concise items, or `None`.

## Source Report
- docs/work-reports/YYYY-MM-DD.md
```

Rules for `CURRENT.md`:
- It is a checkpoint, not a historical narrative.
- Do not copy the whole daily report into it.
- Do not include speculative future implementation details as completed facts.
- Preserve exact branch and HEAD values from the live repository snapshot when Git is available.
- If the working tree is dirty, summarize only the relevant changed paths/status.

## Finish

Respond with:
- the dated report path;
- the `CURRENT.md` path;
- one sentence stating the resume point.
